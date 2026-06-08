"""
Step 3: Full download for LM (2011) replication.

Scope:
  - form_family == '10K' only (10-K, 10-K405, 10-KSB, 10-KSB40, 10-KSB).
    Matches the LM (2011) sample. 10-K/A amendments and 10-KT transitional
    filings are NOT downloaded here.
  - Dedupe by accession: one .txt.gz per unique submission. Co-filer mirror
    rows (same accession under multiple CIKs) are not re-downloaded because
    EDGAR returns byte-identical content; the parquet manifest preserves the
    full (cik, accession) mapping for downstream lookup.

Resumable: skips any accession already 'ok' in download_log.
"""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from edgar_client import get  # noqa: E402

ROOT = Path(r"D:\lm2011-replication")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
MAN = DATA_ROOT / "manifest" / "filings_10k_1994_2008.parquet"
DB = ROOT / "temp" / "pipeline.db"
LOG = ROOT / "temp" / "logs" / "step3_full.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

PROGRESS_EVERY = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS download_log (
            accession    TEXT PRIMARY KEY,
            cik          INTEGER,
            form_family  TEXT,
            url          TEXT,
            local_path   TEXT,
            http_status  INTEGER,
            bytes        INTEGER,
            elapsed_ms   INTEGER,
            sha256       TEXT,
            status       TEXT,
            error        TEXT,
            completed_at TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS ix_status ON download_log(status)")
    con.commit()
    return con


def already_done(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT accession FROM download_log WHERE status='ok'")}


def fetch(row) -> tuple[str, dict]:
    """Year-aware fetch: writes to raw/10K/{YYYY}/{cik}_{accession}.txt.gz."""
    acc = row.accession
    cik = int(row.cik)
    year = pd.to_datetime(row.date_filed).year
    url = row.txt_url
    dest = DATA_ROOT / "raw" / "10K" / str(year) / f"{cik}_{acc}.txt.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)

    rec = {
        "accession": acc, "cik": cik, "form_family": "10K",
        "url": url, "local_path": str(dest),
        "http_status": None, "bytes": 0, "elapsed_ms": 0,
        "sha256": None, "status": "error", "error": None,
        "completed_at": now_iso(),
    }
    if dest.exists() and dest.stat().st_size > 0:
        with open(dest, "rb") as fh:
            h = hashlib.sha256(fh.read()).hexdigest()
        rec.update(http_status=200, bytes=dest.stat().st_size,
                   sha256=h, status="ok", error="cached")
        return "ok", rec

    t0 = time.monotonic()
    try:
        r = get(url, stream=True)
        h = hashlib.sha256()
        tmp = dest.with_suffix(dest.suffix + ".part")
        n = 0
        with gzip.open(tmp, "wb", compresslevel=6) as gz:
            for blk in r.iter_content(chunk_size=1 << 15):
                if blk:
                    gz.write(blk)
                    h.update(blk)
                    n += len(blk)
        tmp.replace(dest)
        rec.update(http_status=r.status_code, bytes=n,
                   elapsed_ms=int((time.monotonic() - t0) * 1000),
                   sha256=h.hexdigest(), status="ok")
        return "ok", rec
    except Exception as e:
        rec.update(elapsed_ms=int((time.monotonic() - t0) * 1000),
                   error=f"{type(e).__name__}: {e}"[:500])
        return "error", rec


def upsert(con, rec) -> None:
    con.execute("""
        INSERT INTO download_log
        (accession, cik, form_family, url, local_path, http_status, bytes,
         elapsed_ms, sha256, status, error, completed_at)
        VALUES (:accession,:cik,:form_family,:url,:local_path,:http_status,:bytes,
                :elapsed_ms,:sha256,:status,:error,:completed_at)
        ON CONFLICT(accession) DO UPDATE SET
            http_status=excluded.http_status, bytes=excluded.bytes,
            elapsed_ms=excluded.elapsed_ms, sha256=excluded.sha256,
            status=excluded.status, error=excluded.error,
            completed_at=excluded.completed_at, local_path=excluded.local_path
    """, rec)


def main() -> None:
    df = pd.read_parquet(MAN)
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    # Scope: 10-K family proper, deduped by accession.
    df = df[df["form_family"] == "10K"].copy()
    df = df.sort_values("date_filed").drop_duplicates("accession").reset_index(drop=True)
    print(f"10-K unique accessions in manifest: {len(df):,}")

    con = init_db()
    done = already_done(con)
    todo = df[~df["accession"].isin(done)].reset_index(drop=True)
    print(f"Already complete : {len(done):,}")
    print(f"Remaining        : {len(todo):,}")

    succeeded = len(done)
    failed = 0
    total_bytes = 0
    t_start = time.monotonic()
    log_fh = open(LOG, "a", encoding="utf-8")
    log_fh.write(f"\n===== run @ {now_iso()} =====\n")

    bar = tqdm(todo.itertuples(index=False), total=len(todo), desc="10K", unit="f")
    for i, row in enumerate(bar, 1):
        status, rec = fetch(row)
        try:
            upsert(con, rec)
            if i % 100 == 0:
                con.commit()
        except sqlite3.Error as e:
            log_fh.write(f"sqlite error {rec['accession']}: {e}\n")
        if status == "ok":
            succeeded += 1
            total_bytes += rec["bytes"]
        else:
            failed += 1
            log_fh.write(f"FAIL {rec['accession']} {rec['url']} :: {rec['error']}\n")

        if i % PROGRESS_EVERY == 0:
            elapsed = time.monotonic() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else float("inf")
            bar.write(f"  [{i:>6}/{len(todo)}]  ok={succeeded}  err={failed}  "
                      f"{rate:.2f} req/s  eta={eta/3600:.2f}h")

    con.commit()
    con.close()
    log_fh.close()

    elapsed = time.monotonic() - t_start
    attempted = len(todo)
    print("\n--- Step 3 summary ---")
    print(f"Unique 10-K manifest     : {len(df):,}")
    print(f"Attempted this run       : {attempted:,}")
    print(f"Succeeded (cumulative)   : {succeeded:,}")
    print(f"Failed (this run)        : {failed:,}")
    print(f"Bytes this run           : {total_bytes:,}  ({total_bytes/1e9:.2f} GB)")
    print(f"Wall-clock seconds       : {elapsed:,.1f}")
    if elapsed > 0 and attempted > 0:
        print(f"Effective req/s          : {attempted/elapsed:.2f}")


if __name__ == "__main__":
    main()
