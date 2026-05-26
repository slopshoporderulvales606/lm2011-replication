"""
Step 2b: Validate the 2007 pilot downloads against Loughran-McDonald reference data.

Validation passes:
  V1  Coverage vs LM 10X Summaries (primary). Filter LM to 2007 + 10-K-family
      form types; compare accession sets to our manifest.
  V2  Coverage vs LM 10-K HeaderData (secondary, independent).
  V3  File-size sanity: decompressed size of each downloaded .txt.gz vs LM's
      GrossFileSize for the same accession. Flag big outliers.

Outputs:
  - Prints a console report.
  - Writes CSVs of mismatches/outliers to D:\\Sentiment_analysis_project\\output\\.
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(r"D:\Sentiment_analysis_project")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
INP = ROOT / "input"
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)

MAN = DATA_ROOT / "manifest" / "filings_10k_1994_2008.parquet"
LM_SUM = INP / "Loughran-McDonald_10X_Summaries_1993-2025.csv"
LM_HDR = INP / "LoughranMcDonald_10-K_HeaderData_1993-2025.csv"

# Map LM form-type strings to our 3-family scheme. LM uses both slash and dash
# variants for amendments (e.g. "10-K/A" and "10-K-A"); handle both.
F_10K = {"10-K", "10-K405", "10KSB", "10-KSB", "10KSB40"}
F_10KA = {"10-K/A", "10-K-A", "10-K405/A", "10-K405-A",
          "10KSB/A", "10KSB-A", "10-KSB/A", "10-KSB-A",
          "10KSB40/A", "10KSB40-A"}
F_10KT = {"10-KT", "10KT405", "10-KT/A", "10-KT-A", "10KT405/A", "10KT405-A"}
LM_FORM_FAMILY = (
    {f: "10K" for f in F_10K} | {f: "10KA" for f in F_10KA} | {f: "10KT" for f in F_10KT}
)


def load_my_manifest_2007() -> pd.DataFrame:
    df = pd.read_parquet(MAN)
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    m = df[df["date_filed"].dt.year == 2007].copy()
    return m


def load_lm_summaries_2007() -> pd.DataFrame:
    """Stream the 197 MB CSV, keep only 2007 10-K-family rows + needed cols."""
    cols = ["CIK", "FILING_DATE", "ACC_NUM", "CPR", "FORM_TYPE",
            "CoName", "GrossFileSize", "NetFileSize", "N_Words"]
    chunks = []
    for ch in pd.read_csv(LM_SUM, usecols=cols, chunksize=200_000,
                          dtype={"CIK": "Int64", "FILING_DATE": "Int64",
                                 "ACC_NUM": str, "FORM_TYPE": str,
                                 "GrossFileSize": "Int64", "NetFileSize": "Int64",
                                 "N_Words": "Int64"}):
        ch = ch[(ch["FILING_DATE"] >= 20070101) & (ch["FILING_DATE"] <= 20071231)]
        ch = ch[ch["FORM_TYPE"].isin(LM_FORM_FAMILY)]
        if not ch.empty:
            chunks.append(ch)
    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=cols)
    df["form_family"] = df["FORM_TYPE"].map(LM_FORM_FAMILY)
    return df


def load_lm_header_2007() -> pd.DataFrame:
    cols = ["filing_firm_cik", "filing_date", "g_accession_number",
            "g_conformed_submission_type", "g_conformed_period_of_report",
            "cd_company_conformed_name"]
    chunks = []
    for ch in pd.read_csv(LM_HDR, usecols=cols, chunksize=200_000,
                          dtype={"filing_firm_cik": "Int64",
                                 "filing_date": "Int64",
                                 "g_accession_number": str,
                                 "g_conformed_submission_type": str}):
        ch = ch[(ch["filing_date"] >= 20070101) & (ch["filing_date"] <= 20071231)]
        ch = ch[ch["g_conformed_submission_type"].isin(LM_FORM_FAMILY)]
        if not ch.empty:
            chunks.append(ch)
    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=cols)
    df["form_family"] = df["g_conformed_submission_type"].map(LM_FORM_FAMILY)
    return df


def coverage_report(name: str, mine: set[str], theirs: set[str]) -> dict:
    inter = mine & theirs
    only_lm = theirs - mine
    only_us = mine - theirs
    print(f"\n--- {name} coverage ---")
    print(f"  mine                : {len(mine):>7,}")
    print(f"  LM ({name})         : {len(theirs):>7,}")
    print(f"  intersection         : {len(inter):>7,}")
    print(f"  in LM, not in ours   : {len(only_lm):>7,}")
    print(f"  in ours, not in LM   : {len(only_us):>7,}")
    if theirs:
        print(f"  recall (LM-coverage) : {len(inter)/len(theirs)*100:.2f}%")
    return {"intersection": inter, "only_lm": only_lm, "only_us": only_us}


def family_breakdown(label: str, df_mine: pd.DataFrame, df_lm: pd.DataFrame,
                     mine_fam_col: str, lm_fam_col: str) -> None:
    print(f"\n  {label} by form_family:")
    a = df_mine[mine_fam_col].value_counts().rename("mine")
    b = df_lm[lm_fam_col].value_counts().rename("LM")
    cross = pd.concat([a, b], axis=1).fillna(0).astype(int)
    cross["diff"] = cross["mine"] - cross["LM"]
    print(cross.to_string())


def size_sanity(my_man: pd.DataFrame, lm_sum: pd.DataFrame) -> pd.DataFrame:
    """
    For every (cik, accession) we downloaded, decompress the .txt.gz and compare
    its byte length to LM's GrossFileSize. Big ratios in either direction signal
    truncation/corruption.
    """
    # LM's GrossFileSize is per accession (one row per filing). Join on ACC_NUM.
    lm_by_acc = (lm_sum.dropna(subset=["GrossFileSize"])
                       .drop_duplicates(subset=["ACC_NUM"])
                       .set_index("ACC_NUM"))
    rows = []
    miss_local = 0
    for r in my_man.itertuples(index=False):
        acc = r.accession
        cik = int(r.cik)
        fam = r.form_family
        local = DATA_ROOT / "raw" / fam / "2007" / f"{cik}_{acc}.txt.gz"
        if not local.exists():
            miss_local += 1
            continue
        if acc not in lm_by_acc.index:
            continue
        try:
            with gzip.open(local, "rb") as fh:
                n_local = sum(len(b) for b in iter(lambda: fh.read(1 << 16), b""))
        except Exception as e:
            rows.append({"accession": acc, "cik": cik, "local_bytes": -1,
                         "lm_gross": int(lm_by_acc.loc[acc, "GrossFileSize"]),
                         "ratio": float("nan"), "error": str(e)[:80]})
            continue
        lm_g = int(lm_by_acc.loc[acc, "GrossFileSize"])
        ratio = n_local / lm_g if lm_g > 0 else float("nan")
        rows.append({"accession": acc, "cik": cik, "local_bytes": n_local,
                     "lm_gross": lm_g, "ratio": ratio, "error": ""})
    out = pd.DataFrame(rows)
    print(f"\n--- File-size sanity (decompressed local vs LM GrossFileSize) ---")
    print(f"  files compared           : {len(out):,}")
    print(f"  files missing locally    : {miss_local}")
    if not out.empty:
        good = out["ratio"].between(0.95, 1.05)
        print(f"  ratio in [0.95, 1.05]    : {good.sum():,}  ({good.mean()*100:.2f}%)")
        print(f"  ratio < 0.5              : {(out['ratio'] < 0.5).sum()}")
        print(f"  ratio > 1.5              : {(out['ratio'] > 1.5).sum()}")
        print(f"  median ratio             : {out['ratio'].median():.4f}")
        print(f"  mean   ratio             : {out['ratio'].mean():.4f}")
    return out


def main() -> None:
    print("Loading my 2007 manifest ...")
    mine = load_my_manifest_2007()
    print(f"  rows: {len(mine):,}  unique accessions: {mine['accession'].nunique():,}")

    print("\nStreaming LM 10X Summaries (filter to 2007 10-K family) ...")
    lm_s = load_lm_summaries_2007()
    print(f"  LM Summaries 2007 rows: {len(lm_s):,}  unique acc: {lm_s['ACC_NUM'].nunique():,}")

    print("\nStreaming LM 10-K HeaderData (filter to 2007 10-K family) ...")
    lm_h = load_lm_header_2007()
    print(f"  LM HeaderData 2007 rows: {len(lm_h):,}  unique acc: {lm_h['g_accession_number'].nunique():,}")

    mine_accs = set(mine["accession"].unique())

    # V1
    s_accs = set(lm_s["ACC_NUM"].dropna().unique())
    rep1 = coverage_report("LM Summaries", mine_accs, s_accs)
    family_breakdown("LM Summaries", mine.drop_duplicates("accession"), lm_s.drop_duplicates("ACC_NUM"),
                     "form_family", "form_family")

    # V2
    h_accs = set(lm_h["g_accession_number"].dropna().unique())
    rep2 = coverage_report("LM HeaderData", mine_accs, h_accs)
    family_breakdown("LM HeaderData", mine.drop_duplicates("accession"), lm_h.drop_duplicates("g_accession_number"),
                     "form_family", "form_family")

    # Dump diffs for inspection
    if rep1["only_lm"]:
        lm_s[lm_s["ACC_NUM"].isin(rep1["only_lm"])].to_csv(OUT / "val_2007_in_LMsum_not_in_ours.csv", index=False)
    if rep1["only_us"]:
        mine[mine["accession"].isin(rep1["only_us"])].to_csv(OUT / "val_2007_in_ours_not_in_LMsum.csv", index=False)
    if rep2["only_lm"]:
        lm_h[lm_h["g_accession_number"].isin(rep2["only_lm"])].to_csv(OUT / "val_2007_in_LMhdr_not_in_ours.csv", index=False)

    # V3: size sanity (uses only the rows present in both)
    sz = size_sanity(mine.drop_duplicates("accession"), lm_s)
    if not sz.empty:
        sz.to_csv(OUT / "val_2007_size_check.csv", index=False)
        outliers = sz[(sz["ratio"] < 0.5) | (sz["ratio"] > 1.5)].sort_values("ratio")
        if not outliers.empty:
            outliers.to_csv(OUT / "val_2007_size_outliers.csv", index=False)
            print("\n  size outliers (sample):")
            print(outliers.head(10).to_string(index=False))

    print("\nDone. Per-row diffs (if any) written under", OUT)


if __name__ == "__main__":
    main()
