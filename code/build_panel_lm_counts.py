"""Build panel_lm_counts.parquet — uses LM Summaries' published values directly.

For each filing in our analysis sample, replace:
  - N_Words           with LM's published N_Words
  - N_Negative        with LM's N_Negative
  - N_Positive        with LM's N_Positive  (and optionally net of N_Negation)
  - ff48 industry     with LM's FFInd (their own FF48 mapping)
  - Recompute Fin-Neg, Fin-Pos using LM values

For tf-idf we still use our sparse-matrix derived score (LM Summaries doesn't
ship per-word frequencies).
"""

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"D:\lm2011-replication")
INP = ROOT / "input"
OUT = ROOT / "output"

# Restore default panel
import shutil
shutil.copyfile(OUT / "panel_default.parquet", OUT / "panel.parquet")

panel = pd.read_parquet(OUT / "panel.parquet")
panel["accession"] = panel["accession"].astype(str)
print(f"Default panel: {len(panel):,} rows")

# Load LM Summaries
print("Loading LM Summaries ...")
lm_cols = ["ACC_NUM","FORM_TYPE","SIC","FFInd",
           "N_Words","N_Unique_Words","N_Negative","N_Positive","N_Negation"]
lm = pd.read_csv(INP / "Loughran-McDonald_10X_Summaries_1993-2025.csv",
                 usecols=lm_cols)
lm = lm[lm["FORM_TYPE"].isin(["10-K","10-K405"])].copy()
lm["ACC_NUM"] = lm["ACC_NUM"].astype(str)
lm = lm.drop_duplicates("ACC_NUM", keep="first")
print(f"LM Summaries 10-K + 10-K405 (deduped on accession): {len(lm):,}")

# Merge
merged = panel.merge(lm.rename(columns={"ACC_NUM":"accession"}),
                     on="accession", how="left", suffixes=("","_lm"))
matched = merged["N_Words"].notna()
print(f"Match rate: {matched.sum():,}/{len(merged):,} = {matched.mean()*100:.1f}%")

# Build LM-based variables
merged["n_words_lm"] = merged["N_Words"]
merged["n_neg_lm"]   = merged["N_Negative"]
merged["n_pos_lm"]   = merged["N_Positive"]
merged["n_neg_word_lm"] = merged["N_Negation"]  # for adjusted positive

# Fin-Neg and Fin-Pos based on LM counts
merged["fin_neg_prop_lm"] = np.where(
    merged["n_words_lm"] > 0,
    100.0 * merged["n_neg_lm"] / merged["n_words_lm"], np.nan)
merged["fin_pos_prop_lm"] = np.where(
    merged["n_words_lm"] > 0,
    100.0 * merged["n_pos_lm"] / merged["n_words_lm"], np.nan)
# Negation-adjusted Fin-Pos: subtract 2 × negated-positive from raw positive
# (LM page 44: "We account for simple negation only for Fin-Pos words.")
merged["fin_pos_prop_lm_net"] = np.where(
    merged["n_words_lm"] > 0,
    100.0 * (merged["n_pos_lm"] - 2*merged["n_neg_word_lm"]) / merged["n_words_lm"],
    np.nan)

# FF48 from LM
merged["ff48_lm"] = pd.to_numeric(merged["FFInd"], errors="coerce").astype("Int64")

print("\nSummary comparison:")
print(f"  Ours Fin-Neg mean : {merged['fin_neg_prop'].mean():.3f}%")
print(f"  LM Fin-Neg mean   : {merged['fin_neg_prop_lm'].mean():.3f}%")
print(f"  LM target (paper) : 1.39%")
print(f"  Corr (ours, LM)   : {merged[['fin_neg_prop','fin_neg_prop_lm']].corr().iloc[0,1]:.3f}")
print()
print(f"  Ours Fin-Pos mean : {merged['fin_pos_prop'].mean():.3f}%")
print(f"  LM Fin-Pos mean   : {merged['fin_pos_prop_lm'].mean():.3f}%")
print(f"  LM Fin-Pos net    : {merged['fin_pos_prop_lm_net'].mean():.3f}%")
print(f"  LM target (paper) : 0.75%")
print()
print(f"  FF48 (ours, ff48) coverage: {merged['ff48'].notna().sum():,}")
print(f"  FF48 (LM, ff48_lm) coverage: {merged['ff48_lm'].notna().sum():,}")

# Save
merged.to_parquet(OUT / "panel_lm_counts.parquet", index=False)
print(f"\nWrote panel_lm_counts.parquet ({len(merged):,} rows)")
