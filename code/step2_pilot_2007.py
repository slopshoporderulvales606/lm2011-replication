"""
Step 2: Pilot download — 2007 filings only.

- Reads the manifest, filters to date_filed in 2007.
- Streams each txt to disk, compresses with gzip, names
  {cik}_{accession}.txt.gz under raw/{form_family}/2007/.
- Logs every attempt to SQLite (resumable: skip if already 'ok').
- Errors logged and skipped (no crash).
"""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from edgar_client import get  # noqa: E402

ROOT = Path(r"D:\Sentiment_analysis_project")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
MAN = DATA_ROOT / "manifest" / "filings_10k_1994_2008.parquet"
RAW = DATA_ROOT / "raw"
DB = ROOT / "temp" / "pipeline.db"
LOG = ROOT / "temp" / "logs" / "step2_pilot_2007.log"
DB.parent.mkdir(parents=True, exist_ok=True)
LOG.parent.mkdir(parents=True, exist_ok=True)

PROGRESS_EVERY = 200


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
    cur = con.execute("SELECT accession FROM download_log WHERE status='ok'")
    return {r[0] for r in cur.fetchall()}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_one(row: pd.Series) -> tuple[str, dict]:
    """Download a single filing. Returns (status, log_record)."""
    acc = row.accession
    cik = int(row.cik)
    fam = row.form_family
    url = row.txt_url
    dest = RAW / fam / "2007" / f"{cik}_{acc}.txt.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)

    rec = {
        "accession": acc, "cik": cik, "form_family": fam,
        "url": url, "local_path": str(dest),
        "http_status": None, "bytes": 0, "elapsed_ms": 0,
        "sha256": None, "status": "error", "error": None,
        "completed_at": now_iso(),
    }

    if dest.exists() and dest.stat().st_size > 0:
        # Trust the file on disk; recompute hash for the log.
        with open(dest, "rb") as fh:
            h = hashlib.sha256(fh.read()).hexdigest()
        rec.update(http_status=200, bytes=dest.stat().st_size,
                   elapsed_ms=0, sha256=h, status="ok", error="cached")
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


def upsert(con: sqlite3.Connection, rec: dict) -> None:
    con.execute("""
        INSERT INTO download_log
        (accession, cik, form_family, url, local_path, http_status, bytes,
         elapsed_ms, sha256, status, error, completed_at)
        VALUES (:accession,:cik,:form_family,:url,:local_path,:http_status,:bytes,
                :elapsed_ms,:sha256,:status,:error,:completed_at)
        ON CONFLICT(accession) DO UPDATE SET
            http_status=excluded.http_status,
            bytes=excluded.bytes,
            elapsed_ms=excluded.elapsed_ms,
            sha256=excluded.sha256,
            status=excluded.status,
            error=excluded.error,
            completed_at=excluded.completed_at,
            local_path=excluded.local_path
    """, rec)


def main() -> None:
    df = pd.read_parquet(MAN)
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    df = df[df["date_filed"].dt.year == 2007].reset_index(drop=True)
    total = len(df)
    print(f"Pilot 2007: {total:,} filings to attempt.")

    con = init_db()
    done = already_done(con)
    print(f"Already complete in download_log: {len(done):,}")

    todo = df[~df["accession"].isin(done)].reset_index(drop=True)
    print(f"Remaining: {len(todo):,}")

    succeeded = len(done)
    failed = 0
    total_bytes = 0
    t_start = time.monotonic()
    log_fh = open(LOG, "a", encoding="utf-8")
    log_fh.write(f"\n===== run @ {now_iso()} =====\n")

    bar = tqdm(todo.itertuples(index=False), total=len(todo), desc="2007", unit="f")
    for i, row in enumerate(bar, 1):
        status, rec = fetch_one(row)
        try:
            upsert(con, rec)
            if i % 50 == 0:
                con.commit()
        except sqlite3.Error as e:
            log_fh.write(f"sqlite error for {rec['accession']}: {e}\n")
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
            bar.write(
                f"  [{i:>5}/{len(todo)}]  ok={succeeded}  err={failed}  "
                f"{rate:.2f} req/s  eta={eta/60:.1f}m"
            )

    con.commit()
    con.close()
    log_fh.close()

    elapsed = time.monotonic() - t_start
    attempted = len(todo)
    print("\n--- Step 2 summary ---")
    print(f"Filings in 2007 manifest : {total:,}")
    print(f"Attempted this run       : {attempted:,}")
    print(f"Succeeded (cumulative)   : {succeeded:,}")
    print(f"Failed (this run)        : {failed:,}")
    print(f"Bytes downloaded run     : {total_bytes:,}  ({total_bytes/1e9:.2f} GB)")
    print(f"Wall-clock seconds       : {elapsed:,.1f}")
    if elapsed > 0 and attempted > 0:
        print(f"Effective req/s          : {attempted/elapsed:.2f}")


if __name__ == "__main__":
    main()
