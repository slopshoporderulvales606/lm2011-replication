"""
Step 4a (sampler): produce ~30 MD&A samples for manual verification.

For each sampled filing, write into output/mda_samples/{accession}/:
  - 0_meta.txt              filing metadata + EDGAR URL
  - 1_raw_filing.txt        the original undecoded .txt (no cleaning)
  - 2_cleaned_full.txt      cleaned, uppercased full 10-K text
  - 3_extracted_mdna.txt    just the MD&A section (or empty + status note)

Plus an index CSV: output/mda_samples/_index.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from mdna_extract import (  # noqa: E402
    clean_text, extract_mdna, read_filing, tokenize,
)

ROOT = Path(r"D:\Sentiment_analysis_project")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
OUT = ROOT / "output" / "mda_samples"
OUT.mkdir(parents=True, exist_ok=True)

# Pick ~2 filings per year, balanced across 1994-2008 to span format eras.
PER_YEAR = 2
RNG_SEED = 42


def pick_samples() -> pd.DataFrame:
    df = pd.read_parquet(DATA_ROOT / "manifest" / "filings_10k_1994_2008.parquet")
    df = df[df["form_family"] == "10K"].copy()
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    df["year"] = df["date_filed"].dt.year
    df = df.drop_duplicates("accession")
    # Stratified sample.
    sample = (df.groupby("year", group_keys=False)
                .apply(lambda g: g.sample(n=PER_YEAR, random_state=RNG_SEED))
                .reset_index(drop=True))
    return sample


def local_path(row) -> Path:
    return (DATA_ROOT / "raw" / row.form_family / str(row.year)
            / f"{int(row.cik)}_{row.accession}.txt.gz")


def main() -> None:
    samples = pick_samples()
    print(f"Selected {len(samples)} sample filings ({PER_YEAR} per year × {samples['year'].nunique()} years).")

    index_rows = []
    for r in samples.itertuples(index=False):
        acc = r.accession
        path = local_path(r)
        if not path.exists():
            print(f"  SKIP {acc} — file missing on disk")
            continue

        sub = OUT / acc
        sub.mkdir(exist_ok=True)

        # 1. Raw (undecoded) — write a HEAD of the raw text only (full file
        #    can be 5+ MB; head is enough for inspection).
        raw = read_filing(path)
        (sub / "1_raw_filing.txt").write_text(
            raw, encoding="utf-8", errors="replace")

        # 2. Cleaned full text.
        cleaned = clean_text(raw)
        (sub / "2_cleaned_full.txt").write_text(
            cleaned, encoding="utf-8", errors="replace")
        n_words_full = len(tokenize(cleaned))

        # 3. MD&A extraction (form-aware).
        mdna, status = extract_mdna(cleaned, form_type=r.form_type)
        if mdna is not None:
            (sub / "3_extracted_mdna.txt").write_text(
                mdna, encoding="utf-8", errors="replace")
            n_words_mdna = len(tokenize(mdna))
        else:
            (sub / "3_extracted_mdna.txt").write_text(
                f"[MD&A NOT EXTRACTED — status: {status}]\n",
                encoding="utf-8")
            n_words_mdna = 0

        # 0. Metadata header.
        edgar_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?"
            f"action=getcompany&CIK={int(r.cik):010d}&type=10-K&dateb=&owner=include&count=40"
        )
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(r.cik)}/{acc}-index.htm"
        meta = (
            f"accession    : {acc}\n"
            f"cik          : {int(r.cik)}\n"
            f"company      : {r.company_name}\n"
            f"form_type    : {r.form_type}\n"
            f"date_filed   : {r.date_filed.date()}\n"
            f"year         : {int(r.year)}\n"
            f"raw_bytes    : {len(raw):,}\n"
            f"cleaned_words: {n_words_full:,}\n"
            f"mdna_status  : {status}\n"
            f"mdna_words   : {n_words_mdna:,}\n"
            f"mdna_pct     : {100*n_words_mdna/max(n_words_full,1):.1f}%\n"
            f"\nedgar_index  : {filing_url}\n"
            f"company_page : {edgar_url}\n"
        )
        (sub / "0_meta.txt").write_text(meta, encoding="utf-8")

        index_rows.append({
            "year": int(r.year), "accession": acc, "cik": int(r.cik),
            "company": r.company_name, "form_type": r.form_type,
            "filing_date": r.date_filed.date(),
            "raw_bytes": len(raw), "cleaned_words": n_words_full,
            "mdna_status": status, "mdna_words": n_words_mdna,
            "mdna_pct": round(100 * n_words_mdna / max(n_words_full, 1), 1),
            "edgar_url": filing_url,
        })
        print(f"  {acc}  {int(r.year)}  {r.company_name[:30]:30s}  "
              f"full={n_words_full:>7,}  mdna={n_words_mdna:>6,}  status={status}")

    # Write index.
    idx_path = OUT / "_index.csv"
    with open(idx_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(index_rows[0].keys()))
        w.writeheader()
        w.writerows(index_rows)
    print(f"\nWrote index → {idx_path}")
    print(f"Wrote {len(index_rows)} sample folders under {OUT}")

    # Summary stats.
    idx = pd.DataFrame(index_rows)
    print("\nStatus by year:")
    print(idx.groupby(["year", "mdna_status"]).size().unstack(fill_value=0).to_string())
    print("\nMD&A length distribution (where status='ok'):")
    ok = idx[idx["mdna_status"] == "ok"]["mdna_words"]
    if not ok.empty:
        print(f"  n={len(ok)}, min={ok.min():,}, p25={int(ok.quantile(.25)):,}, "
              f"median={int(ok.median()):,}, p75={int(ok.quantile(.75)):,}, max={ok.max():,}")


if __name__ == "__main__":
    main()
