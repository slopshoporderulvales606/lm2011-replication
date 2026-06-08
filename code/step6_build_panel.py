"""
Step 6: Build the analysis panel — merge market controls and compute tf-idf sentiment.

Outputs:
  - output/panel.parquet — one row per analysis filing with:
      filing_date, cik, gvkey, permno, year,
      fin_neg_prop, fin_pos_prop, fin_neg_tfidf_full, fin_neg_tfidf_mda,
      excret_03, size_b, log_size, log_bm, bm,
      turnover_pre, ff_alpha_pre, io, nasdaq, ff48,
      n_words_full, n_words_mda, mdna_status, sqrt_nwords_full, sqrt_nwords_mda
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import load_npz, csr_matrix

ROOT = Path(r"D:\lm2011-replication")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
INP = ROOT / "input"
OUT = ROOT / "output"

SAMPLE = OUT / "sample.parquet"
WC = OUT / "filing_word_counts.parquet"
IDX = OUT / "filing_index.parquet"
TF_FULL = OUT / "filing_negword_tf.npz"
TF_MDA = OUT / "filing_mdna_negword_tf.npz"
NEG_COLS = OUT / "neg_word_columns.parquet"

CRSP_DAILY = INP / "crsp_daily_1993_2019.dta"
CRSP_MONTHLY = INP / "crsp_monthly_1993_2019.dta"
COMPUSTAT = INP / "compustat_gvkey_permno.dta"
INST_OWN = INP / "13f_instOwn_stock_level.dta"
SIC48 = INP / "Siccodes48.txt"


def now() -> float:
    return time.monotonic()


# --------------------------------------------------------------------------- #
# FF48 mapping                                                                 #
# --------------------------------------------------------------------------- #

def parse_siccodes48(path: Path) -> pd.DataFrame:
    """
    Parse Ken French's Siccodes48.txt into a (sic_low, sic_high, ind_num, abbrev) DataFrame.
    """
    rows = []
    cur_ind = None
    cur_abbrev = None
    with open(path, "r", encoding="latin-1") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = re.match(r"^\s*(\d+)\s+(\S+)\s+(.*)$", line)
            if m and not re.match(r"^\s+\d{4}-", line):
                cur_ind = int(m.group(1))
                cur_abbrev = m.group(2)
                continue
            m2 = re.match(r"^\s+(\d{4})-(\d{4})", line)
            if m2 and cur_ind is not None:
                rows.append({
                    "sic_low": int(m2.group(1)),
                    "sic_high": int(m2.group(2)),
                    "ind_num": cur_ind,
                    "abbrev": cur_abbrev,
                })
    return pd.DataFrame(rows)


def make_ff48_lookup(ranges: pd.DataFrame) -> np.ndarray:
    """Return a length-10000 array mapping SIC → FF48 ind_num (49 = 'Other' for unmapped)."""
    arr = np.full(10000, 49, dtype=np.int16)
    for r in ranges.itertuples(index=False):
        arr[int(r.sic_low):int(r.sic_high) + 1] = int(r.ind_num)
    return arr


# --------------------------------------------------------------------------- #
# Per-permno window computations                                              #
# --------------------------------------------------------------------------- #

def compute_window_vars(sample: pd.DataFrame, crspd: pd.DataFrame) -> pd.DataFrame:
    """
    For each filing in sample, compute (per LM 2011 Appendix Variable defs):
        excret_03      : BH compounded [0,3] excess return, in PERCENT
        size_b         : market cap on trading day -1, in $billions
        share_turnover : Σ vol over [-252,-6] / shrout at file date  (LM annual)
        ff_alpha_pre   : annualized intercept of FF3 over [-252,-6]
    using CRSP daily.

    Note: CRSP daily shrout is in MILLIONS of shares (per preclean label).
    LM's share turnover divides aggregate share volume by shares outstanding,
    so we use vol / (shrout * 1e6) to get a unitless ratio.
    """
    print("  preparing crsp groupby ...")
    crspd_valid = crspd.dropna(subset=["ret"]).copy()
    # FIXED: shrout in MILLIONS → shrout * 1e6 = shares
    crspd_valid["turnover"] = np.where(
        crspd_valid["shrout"] > 0,
        crspd_valid["vol"] / (crspd_valid["shrout"] * 1_000_000.0),
        np.nan)
    # NASDAQ pre-2002 volume halving (LM convention for double-counting)
    if "exchcd" in crspd_valid.columns:
        nasdaq_pre02 = (crspd_valid["exchcd"] == 3) & \
                       (crspd_valid["date"] <= pd.Timestamp("2001-12-31"))
        crspd_valid.loc[nasdaq_pre02, "turnover"] = (
            crspd_valid.loc[nasdaq_pre02, "turnover"] / 2.0)
    crspd_valid = crspd_valid.sort_values(["permno", "date"])
    by_permno = {p: g for p, g in crspd_valid.groupby("permno")}

    excret = np.full(len(sample), np.nan)
    size_b = np.full(len(sample), np.nan)
    share_turnover = np.full(len(sample), np.nan)
    ff_alpha = np.full(len(sample), np.nan)

    for i, r in enumerate(sample.itertuples(index=False)):
        permno = int(r.permno)
        if permno not in by_permno:
            continue
        g = by_permno[permno]
        d = r.date_filed

        # Event window: first trading day on/after d, take 4 days
        ev_mask = g["date"] >= d
        if not ev_mask.any():
            continue
        ev = g.loc[ev_mask].head(4)
        if len(ev) < 4:
            continue
        # LM Appendix: BH compounded over [0,3], minus VW index BH, in PERCENT.
        bh_firm = float(np.prod(1.0 + ev["ret"].values) - 1.0)
        bh_mkt  = float(np.prod(1.0 + ev["vwretd"].values) - 1.0)
        excret[i] = (bh_firm - bh_mkt) * 100.0

        # Size: at trading day immediately BEFORE event d=0
        before = g.loc[g["date"] < ev["date"].iloc[0]]
        if len(before) > 0:
            last = before.iloc[-1]
            if pd.notna(last["prc"]) and pd.notna(last["shrout"]):
                # shrout in millions → mkt cap = |prc| * shrout / 1000  (in $B)
                size_b[i] = abs(last["prc"]) * last["shrout"] / 1000.0

        # LM share turnover: Σ vol over [-252,-6] / shrout at file date
        if len(before) >= 60:
            # Σ vol over [-252,-6] = sum over the 247 days indexed -252..-6
            pre_period = before.tail(252).iloc[:-5] if len(before) >= 252 + 5 else before.iloc[:-5]
            if len(pre_period) >= 60:
                total_vol = pre_period["vol"].sum()  # in shares
                shr_at_file = abs(last["shrout"]) * 1_000_000.0  # shares
                if shr_at_file > 0:
                    # NASDAQ pre-2002 cumulative volume halving (same convention)
                    if "exchcd" in pre_period.columns:
                        is_nasdaq_pre02 = ((pre_period["exchcd"] == 3) &
                                           (pre_period["date"] <= pd.Timestamp("2001-12-31")))
                        adj_vol = np.where(is_nasdaq_pre02,
                                           pre_period["vol"] / 2.0,
                                           pre_period["vol"]).sum()
                    else:
                        adj_vol = total_vol
                    share_turnover[i] = adj_vol / shr_at_file

        # 1-yr FF α: regress (ret-rf) on (mktrf, smb, hml) over [-252, -6]
        if len(before) >= 60:
            pre = before.tail(252 + 5).iloc[:-5] if len(before) >= 252 + 5 else before.iloc[:-5]
            pre = pre.tail(252)
            valid = pre[["ret", "mktrf", "smb", "hml", "rf"]].notna().all(axis=1)
            pre = pre[valid]
            if len(pre) >= 60:
                y = pre["ret"].values - pre["rf"].values
                X = np.column_stack([
                    np.ones(len(pre)),
                    pre["mktrf"].values, pre["smb"].values, pre["hml"].values
                ])
                try:
                    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
                    ff_alpha[i] = coef[0] * 252.0     # annualize daily intercept
                except np.linalg.LinAlgError:
                    pass

    out = sample.copy()
    out["excret_03"] = excret
    out["size_b"] = size_b
    out["share_turnover"] = share_turnover     # LM cumulative annual measure
    out["turnover_pre"] = share_turnover        # keep legacy name as alias
    out["ff_alpha_pre"] = ff_alpha
    return out


# --------------------------------------------------------------------------- #
# tf-idf weighting per LM (2011) Eq. 3                                         #
# --------------------------------------------------------------------------- #

def tfidf_score(M: csr_matrix, row_idx: np.ndarray, n_words: np.ndarray) -> np.ndarray:
    """
    LM (2011) Eq. 3 tf-idf weight on the analysis subsample.

        w_ij = ((1 + log(tf_ij)) / (1 + log(a_i))) * log(N / df_j)   if tf_ij ≥ 1
        Fin-Neg_tfidf_i = Σ_j w_ij

    N and df_j are computed over the entire master corpus M (157,293 filings),
    not just the analysis sample — this gives stable idf weights regardless
    of which firms survive the Table I funnel. a_i = N_Words_i.
    """
    # idf computed on the FULL corpus (M, not subset)
    N_full = M.shape[0]
    df_j_full = np.asarray((M > 0).sum(axis=0)).ravel().astype(np.float64)
    df_j_safe = np.where(df_j_full == 0, 1, df_j_full)
    idf = np.log(N_full / df_j_safe)

    # tf for the analysis-sample rows
    M_sub = M[row_idx].astype(np.float64).tocsr()

    nw = np.asarray(n_words, dtype=np.float64).clip(min=1.0)
    denom_i = 1.0 + np.log(nw)

    rows = np.repeat(np.arange(M_sub.shape[0]), np.diff(M_sub.indptr))
    M_sub.data = (1.0 + np.log(M_sub.data)) * idf[M_sub.indices] / denom_i[rows]
    return np.asarray(M_sub.sum(axis=1)).ravel()


def main() -> None:
    t0 = now()

    print("Loading sample ...")
    sample = pd.read_parquet(SAMPLE)
    sample["date_filed"] = pd.to_datetime(sample["date_filed"])
    sample["permno"] = sample["permno"].astype("int64")
    sample["gvkey"] = sample["gvkey"].astype("int64")
    print(f"  rows: {len(sample):,}")

    # Attach word counts and MD&A status
    wc = pd.read_parquet(WC)[["accession", "n_words_full", "n_neg_full", "n_pos_full",
                              "n_words_mda", "n_neg_mda", "n_pos_mda", "mdna_status"]]
    sample = sample.merge(wc, on="accession", how="left")

    print("Loading sparse neg-word matrices ...")
    M_full = load_npz(TF_FULL)
    M_mda = load_npz(TF_MDA)
    idx = pd.read_parquet(IDX).set_index("accession")["row_idx"]
    sample["row_idx"] = sample["accession"].map(idx).astype("int64")

    print("Loading CRSP daily slice ...")
    cols = ["permno", "date", "prc", "ret", "vol", "shrout",
            "vwretd", "exchcd", "mktrf", "smb", "hml", "rf"]
    crspd = pd.read_stata(CRSP_DAILY, columns=cols)
    crspd["permno"] = crspd["permno"].astype("int64")
    crspd["date"] = pd.to_datetime(crspd["date"])
    crspd = crspd[crspd["date"].dt.year.between(1993, 2009)].copy()

    print("Computing event-window variables (excret, size, turnover, FFα) ...")
    sample = compute_window_vars(sample, crspd)
    del crspd

    print("Loading 13F instOwn ...")
    io = pd.read_stata(INST_OWN)
    io["permno"] = io["permno"].astype("int64")
    io["yqtr"] = pd.to_datetime(io["yqtr"])
    # `io` is the institutional-ownership snapshot at the END of the calendar
    # quarter immediately before the filing's calendar quarter. Both sides of
    # the merge key on the QUARTER-END timestamp (matches 13F `rdate`).
    sample["yqtr_pre"] = ((sample["date_filed"] - pd.offsets.QuarterEnd(1))
                          .dt.to_period("Q").dt.to_timestamp(how="end")
                          .dt.normalize())
    sample = sample.merge(
        io.rename(columns={"yqtr": "yqtr_pre", "instOwn": "io"}),
        on=["permno", "yqtr_pre"], how="left")

    # NASDAQ dummy: 1 if filed on NASDAQ (exchcd==3), 0 otherwise.
    # exchcd may be NaN for some filings; treat missing as 0 explicitly.
    sample["nasdaq"] = (sample["exchcd"].fillna(-1) == 3).astype(int)

    # FF48 assignment: primary CRSP siccd (already on sample), fallback Compustat sich, then sic
    print("Assigning FF48 industries ...")
    ranges = parse_siccodes48(SIC48)
    lookup = make_ff48_lookup(ranges)
    # SIC source choice — controlled by env var FF48_SIC_SOURCE:
    #   "crsp"          (default): CRSP siccd at filing month, fall back sich, sic
    #   "sich"                   : Compustat sich (historical FYE SIC), fall back sic
    #   "sic"                    : Compustat sic (most-recent header SIC), no fallback
    #   "header_static"          : LAST CRSP siccd per permno within LM sample period
    #                              (≤ 2008-12-31), populated to ALL observations of
    #                              that permno → mimics LM's static-per-firm header SIC
    import os as _os
    sic_source = _os.environ.get("FF48_SIC_SOURCE", "crsp")
    if sic_source == "sic":
        sic_src = sample["sic"]
    elif sic_source == "sich":
        sic_src = sample["sich"].fillna(sample["sic"])
    elif sic_source == "header_static":
        print("  building header-static SIC map (LAST CRSP siccd ≤ 2008-12-31 per permno) ...")
        cm = pd.read_stata(CRSP_MONTHLY, columns=["permno", "yrmon", "siccd"])
        cm["permno"] = cm["permno"].astype("int64")
        cm["yrmon"] = pd.to_datetime(cm["yrmon"])
        cm = cm[(cm["yrmon"] <= pd.Timestamp("2008-12-31")) & cm["siccd"].notna()]
        cm = cm.sort_values(["permno", "yrmon"]).drop_duplicates(
            "permno", keep="last")[["permno", "siccd"]]
        permno_to_sic = dict(zip(cm["permno"], cm["siccd"]))
        static_sic = sample["permno"].astype("int64").map(permno_to_sic)
        # Fall back to filing-month CRSP siccd, then sich, then sic
        sic_src = static_sic.fillna(sample["siccd"]).fillna(sample["sich"]).fillna(sample["sic"])
        print(f"  header_static SIC coverage: {static_sic.notna().sum():,} of {len(sample):,}")
    else:  # "crsp"
        sic_src = sample["siccd"].fillna(sample["sich"]).fillna(sample["sic"])
    print(f"  FF48_SIC_SOURCE = {sic_source}")
    sic_int = pd.to_numeric(sic_src, errors="coerce").fillna(-1).astype(int).clip(-1, 9999)
    sample["ff48"] = np.where(sic_int >= 0, lookup[sic_int], 49)
    sample["ff48_sic_source"] = sic_source

    # Sentiment variables.
    print("Computing sentiment scores ...")
    sample["fin_neg_prop"] = np.where(
        sample["n_words_full"] > 0,
        100.0 * sample["n_neg_full"] / sample["n_words_full"], np.nan)
    sample["fin_pos_prop"] = np.where(
        sample["n_words_full"] > 0,
        100.0 * sample["n_pos_full"] / sample["n_words_full"], np.nan)

    rows = sample["row_idx"].values
    sample["fin_neg_tfidf_full"] = tfidf_score(M_full, rows, sample["n_words_full"].values)
    # MD&A: only where MD&A available
    mdna_mask = sample["mdna_status"].astype(str).str.startswith("ok").fillna(False)
    mdna_score = np.full(len(sample), np.nan)
    if mdna_mask.any():
        sub_rows = sample.loc[mdna_mask, "row_idx"].values
        sub_nw = sample.loc[mdna_mask, "n_words_mda"].values
        mdna_score[mdna_mask.values] = tfidf_score(M_mda, sub_rows, sub_nw)
    sample["fin_neg_tfidf_mda"] = mdna_score

    # Auxiliary transforms.
    sample["log_size"] = np.log(sample["size_b"].clip(lower=1e-6))
    sample["log_bm"] = np.log(sample["bm"].clip(lower=1e-6))
    # Per LM (2011): log(share turnover) is the control variable.
    sample["log_turnover"] = np.log(sample["turnover_pre"].clip(lower=1e-9))
    sample["sqrt_nwords_full"] = np.sqrt(sample["n_words_full"].clip(lower=0))
    sample["sqrt_nwords_mda"] = np.sqrt(sample["n_words_mda"].clip(lower=0))

    # Final columns
    keep_cols = [
        "accession", "cik", "gvkey", "permno", "date_filed", "filing_year",
        "form_type", "match_source",
        # sentiment
        "fin_neg_prop", "fin_pos_prop", "fin_neg_tfidf_full", "fin_neg_tfidf_mda",
        "n_words_full", "n_words_mda", "n_neg_full", "n_pos_full",
        "n_neg_mda", "n_pos_mda", "mdna_status",
        # market controls
        "excret_03", "size_b", "log_size", "bm", "log_bm",
        "turnover_pre", "log_turnover", "ff_alpha_pre", "io",
        # discrete controls
        "nasdaq", "exchcd", "ff48", "sich", "sic", "siccd",
        # auxiliary
        "sqrt_nwords_full", "sqrt_nwords_mda",
    ]
    keep_cols = [c for c in keep_cols if c in sample.columns]
    panel = sample[keep_cols].copy()
    panel.to_parquet(OUT / "panel.parquet", index=False)
    print(f"\nWrote panel.parquet  ({len(panel):,} rows × {len(keep_cols)} cols)")

    # Coverage summary
    print("\nVariable coverage (non-null):")
    for c in ["fin_neg_prop", "fin_pos_prop", "fin_neg_tfidf_full",
              "fin_neg_tfidf_mda", "excret_03", "size_b", "bm",
              "turnover_pre", "ff_alpha_pre", "io", "ff48"]:
        if c in panel.columns:
            n = panel[c].notna().sum()
            print(f"  {c:<22}  {n:>7,}  ({100*n/len(panel):.1f}%)")

    elapsed = now() - t0
    print(f"\nDone. Elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
