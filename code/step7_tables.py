"""
Step 7: Produce Tables II, IV, V from the analysis panel.

Per LM (2011) Internet Appendix, the regressions are:
  - Fama-MacBeth (1973) quarterly cross-sectional regressions
  - Newey-West (1987) standard errors with one lag on the time series of
    cross-sectional coefficients
  - FF48 industry dummies + constant in each quarterly regression

Inputs:
  - output/panel.parquet (from step 6)

Outputs:
  - output/table2.csv
  - output/table4_cols2_4.csv
  - output/table5_cols2_4.csv
  - output/replication_diagnostic.md
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="statsmodels")

ROOT = Path(r"D:\lm2011-replication")
OUT = ROOT / "output"
PANEL = OUT / "panel.parquet"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def winsorize(s: pd.Series, lo: float = 0.01, hi: float = 0.99) -> pd.Series:
    a, b = s.quantile(lo), s.quantile(hi)
    return s.clip(lower=a, upper=b)


def describe(s: pd.Series) -> dict:
    s = s.dropna()
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "std": float(s.std()),
        "min": float(s.min()),
        "max": float(s.max()),
    }


# --------------------------------------------------------------------------- #
# Table II                                                                    #
# --------------------------------------------------------------------------- #

def build_table_2(p: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    spec = [
        ("Fin-Neg",                 "fin_neg_prop"),
        ("Fin-Pos",                 "fin_pos_prop"),
        ("Excess return [0,3] (%)", "excret_03"),
        ("Size ($B)",               "size_b"),
        ("Book-to-market",          "bm"),
        ("Turnover (pre, median)",  "turnover_pre"),
        ("1-yr pre-event FF alpha", "ff_alpha_pre"),
        ("Institutional ownership", "io"),
        ("NASDAQ dummy",            "nasdaq"),
    ]
    for label, col in spec:
        if col not in p.columns:
            continue
        s = p[col]
        if col != "nasdaq":
            s = winsorize(s)
        d = describe(s)
        d["variable"] = label
        rows.append(d)
    return pd.DataFrame(rows)[["variable", "n", "mean", "median", "std", "min", "max"]]


# --------------------------------------------------------------------------- #
# Fama-MacBeth quarterly with Newey-West                                       #
# --------------------------------------------------------------------------- #

def fama_macbeth_quarterly(d: pd.DataFrame, y: str, x_main: str,
                           controls: list[str], industry_col: str = "ff48",
                           nw_lags: int = 1, freq_weight: bool = False,
                           ts_weight_by_n: bool = True) -> dict:
    """
    LM (2011) page 52: Fama-MacBeth quarterly + Newey-West (1 lag) SE,
    "weighted by frequency, since the calendar distribution of file dates is
    clustered around specific dates (see Griffin (2003))."

    Implementation:
        For each calendar quarter q:
            if freq_weight: weight each filing by 1/n_same_filing_date in q
            Run WLS:  y_i = α_q + β_q · x_main_i + γ_q · controls + θ_q · ind_d + ε
            Save β_q
        β̄ = mean(β_q), SE_NW = Newey-West (1 lag) on β_q time series.

    Returns dict with coef, se, t, p, N, n_quarters, adj_r2_avg.
    """
    d = d.copy()
    d["yq"] = d["date_filed"].dt.to_period("Q")

    needed = [y, x_main] + controls + [industry_col, "yq", "date_filed"]
    d = d.dropna(subset=needed)

    # Winsorize continuous variables (1/99% over full sample).
    cont = [y, x_main] + [c for c in controls if c != "nasdaq"]
    for c in cont:
        d[c] = winsorize(d[c])

    betas, ar2s, ns = [], [], []
    for q, g in d.groupby("yq"):
        if len(g) < 30:
            continue
        # Per LM page 52: weight by frequency (1 / n_same_filing_date within q)
        if freq_weight:
            date_counts = g.groupby("date_filed").size()
            wt = (1.0 / g["date_filed"].map(date_counts)).astype(float).values
        else:
            wt = np.ones(len(g))

        # Design matrix
        ind_d = pd.get_dummies(g[industry_col], prefix="ff48", drop_first=True).astype(float)
        X = pd.concat([g[[x_main] + controls].astype(float).reset_index(drop=True),
                       ind_d.reset_index(drop=True)], axis=1)
        X = sm.add_constant(X, has_constant="add")
        yvec = g[y].astype(float).values
        try:
            res = sm.WLS(yvec, X.values, weights=wt, missing="drop").fit()
            beta_idx = list(X.columns).index(x_main)
            betas.append(res.params[beta_idx])
            ar2s.append(res.rsquared_adj)
            ns.append(int(res.nobs))
        except Exception:
            continue

    if not betas:
        return {"coef": np.nan, "se": np.nan, "t": np.nan, "p": np.nan,
                "n": 0, "n_quarters": 0, "adj_r2_avg": np.nan}

    betas = np.array(betas, dtype=float)
    ns_arr = np.array(ns, dtype=float)
    if ts_weight_by_n:
        # Time-series average weighted by n_obs in each quarter (option B)
        nw = sm.WLS(betas, np.ones(len(betas)), weights=ns_arr).fit(
            cov_type="HAC", cov_kwds={"maxlags": nw_lags})
    else:
        nw = sm.OLS(betas, np.ones(len(betas))).fit(
            cov_type="HAC", cov_kwds={"maxlags": nw_lags})
    coef = float(nw.params[0])
    se = float(nw.bse[0])
    t = coef / se if se else np.nan
    from scipy.stats import norm
    p = 2.0 * (1.0 - norm.cdf(abs(t))) if not np.isnan(t) else np.nan
    return {"coef": coef, "se": se, "t": t, "p": p,
            "n": int(np.sum(ns)), "n_quarters": len(betas),
            "adj_r2_avg": float(np.mean(ar2s))}


def fit_one(p: pd.DataFrame, sentiment: str, label: str,
            with_ff48: bool = True) -> dict:
    """LM (2011) Table IV / IA.I controls: 6 variables + (optional) FF48 FEs."""
    controls = [
        "log_size", "log_bm", "log_turnover",
        "ff_alpha_pre", "nasdaq", "io",
    ]
    if with_ff48:
        industry_col = "ff48"
    else:
        # Pass a constant column so the function skips industry dummy generation
        # (only one level → drop_first leaves zero dummies).
        p = p.copy()
        p["_no_ind"] = 1
        industry_col = "_no_ind"
    res = fama_macbeth_quarterly(
        p, y="excret_03", x_main=sentiment, controls=controls,
        industry_col=industry_col,
    )
    res["label"] = label
    res["sentiment_var"] = sentiment
    res["ff48_dummies"] = with_ff48
    return res


def build_tables_4_5(p: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pV = p[p["mdna_status"].astype(str).str.startswith("ok").fillna(False)].copy()
    pV["fin_neg_prop_mda"] = np.where(
        pV["n_words_mda"] > 0,
        100.0 * pV["n_neg_mda"] / pV["n_words_mda"], np.nan)

    rows4, rows5 = [], []
    for use_ff48 in (True, False):
        rows4.append(fit_one(p,  "fin_neg_prop",       "col2_FinNeg_prop",       use_ff48))
        rows4.append(fit_one(p,  "fin_neg_tfidf_full", "col4_FinNeg_tfidf",      use_ff48))
        rows5.append(fit_one(pV, "fin_neg_prop_mda",   "col2_FinNeg_prop_MDA",   use_ff48))
        rows5.append(fit_one(pV, "fin_neg_tfidf_mda",  "col4_FinNeg_tfidf_MDA",  use_ff48))

    cols = ["label", "ff48_dummies", "sentiment_var", "coef", "se", "t", "p",
            "n", "n_quarters", "adj_r2_avg"]
    return pd.DataFrame(rows4)[cols], pd.DataFrame(rows5)[cols]


def write_diagnostic(t2: pd.DataFrame, t4: pd.DataFrame, t5: pd.DataFrame,
                     n_sample: int, n_firms: int) -> None:
    md = []
    fmt = lambda x: f"{x:.4f}"
    md.append("# LM (2011) replication diagnostic — v2 (post-appendix fixes)\n")
    md.append(f"Analysis sample: **{n_sample:,} firm-years** / **{n_firms:,} unique permnos**.")
    md.append("Paper targets: **50,115 firm-years / 8,341 firms**.\n")
    md.append("## Methodology fixes applied (LM 2011 Internet Appendix)")
    md.append("- 10-K and 10-K405 only (drop 10-KSB family)")
    md.append("- Strip exhibits (`<TYPE>EX-*`), keep only the primary 10-K body")
    md.append("- Strip tables where > 25% of nonblank chars are digits")
    md.append("- Replace `hyphen + LF` with `hyphen` before tokenizing")
    md.append("- N_Words = count of tokens IN the master dictionary")
    md.append("- Excess return = buy-and-hold compounded × 100 (in percent)")
    md.append("- Control: log(turnover), not raw turnover")
    md.append("- Fama-MacBeth quarterly with Newey-West (1 lag) SEs\n")
    md.append("\n## Table II — descriptive statistics (ours)\n")
    md.append("```")
    md.append(t2.to_string(index=False, float_format=fmt))
    md.append("```\n")
    md.append("## Table IV — Excess-return regressions, full 10-K (ours)\n")
    md.append("```")
    md.append(t4.to_string(index=False, float_format=fmt))
    md.append("```\n")
    md.append("## Table V — Excess-return regressions, MD&A only (ours)\n")
    md.append("```")
    md.append(t5.to_string(index=False, float_format=fmt))
    md.append("```\n")
    md.append("## LM (2011) reported reference values\n")
    md.append("Table IV col (2) Fin-Neg proportional: t ≈ -2.84, sign negative")
    md.append("Table IV col (4) Fin-Neg tf-idf:       t ≈ -5.27, larger magnitude than col (2)")
    md.append("Table V cols (2)/(4): same sign, larger |t| for tf-idf than proportional")
    md.append("\n_(LM signs are negative — higher negative tone predicts lower filing-period excess return.)_")
    (OUT / "replication_diagnostic.md").write_text("\n".join(md), encoding="utf-8")
    print("Wrote replication_diagnostic.md")


def main() -> None:
    t0 = time.monotonic()
    print("Loading panel ...")
    p = pd.read_parquet(PANEL)
    p["date_filed"] = pd.to_datetime(p["date_filed"])
    n = len(p)
    n_firms = p["permno"].nunique()
    print(f"  {n:,} rows × {p.shape[1]} cols  /  {n_firms:,} unique permnos\n")

    print("=== Table II ===")
    t2 = build_table_2(p)
    try:
        t2.to_csv(OUT / "table2.csv", index=False)
    except PermissionError:
        print("  WARN: table2.csv locked; skipping")
    print(t2.to_string(index=False))

    print("\n=== Tables IV & V (Fama-MacBeth quarterly with Newey-West) ===")
    t4, t5 = build_tables_4_5(p)
    for name, df in [("table4_cols2_4.csv", t4), ("table5_cols2_4.csv", t5)]:
        try:
            df.to_csv(OUT / name, index=False)
        except PermissionError:
            print(f"  WARN: {name} locked; skipping")
    print("\nTable IV (full text):")
    print(t4.to_string(index=False))
    print("\nTable V (MD&A only):")
    print(t5.to_string(index=False))

    write_diagnostic(t2, t4, t5, n, n_firms)
    print(f"\nDone. Elapsed: {time.monotonic()-t0:.1f}s")


if __name__ == "__main__":
    main()
