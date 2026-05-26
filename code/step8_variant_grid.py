"""
Step 8: Systematic variant grid for the open methodology decisions.

Runs the LM (2011) Table IV (full text) and Table V (MD&A) col(2) and col(4)
regressions under a battery of variant settings, saves all results to a
single comparison CSV.

Data-side variants (dictionary vintage, link table) are handled by SEPARATE
panel files (`panel_<variant>.parquet`) that step 4/5/6 produce when run
with appropriate env vars. This script reads those panels if present.

Regression-side variants are toggled directly here.
"""

from __future__ import annotations

import itertools
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

warnings.filterwarnings("ignore")

ROOT = Path(r"D:\Sentiment_analysis_project")
OUT = ROOT / "output"
PANEL_DEFAULT = OUT / "panel.parquet"


# --------------------------------------------------------------------------- #
# Regression engine — parameterized                                           #
# --------------------------------------------------------------------------- #

def winsorize(s: pd.Series, lo: float, hi: float) -> pd.Series:
    a, b = s.quantile(lo), s.quantile(hi)
    return s.clip(lower=a, upper=b)


def fama_macbeth(d: pd.DataFrame, y: str, x_main: str, controls: list[str],
                 industry_col: str = "ff48",
                 nw_lags: int = 1,
                 freq_weight: bool = False,
                 ts_weight_by_n: bool = True,
                 min_obs: int = 30,
                 winsor_scope: str = "full",
                 winsor_lo: float = 0.01,
                 winsor_hi: float = 0.99,
                 drop_thin_industries: int = 0,
                 ) -> dict:
    """One Fama-MacBeth quarterly regression. Returns coef + t for x_main and
    every control. Output keys: <var>_coef, <var>_t."""
    d = d.copy()
    d["yq"] = d["date_filed"].dt.to_period("Q")
    needed = [y, x_main] + controls + [industry_col, "yq", "date_filed"]
    d = d.dropna(subset=needed)
    if winsor_scope == "full":
        cont = [y, x_main] + [c for c in controls if c != "nasdaq"]
        for c in cont:
            d[c] = winsorize(d[c], winsor_lo, winsor_hi)

    all_vars = [x_main] + controls
    betas_by_var = {v: [] for v in all_vars}
    ar2s, ns = [], []

    for q, g in d.groupby("yq"):
        if len(g) < min_obs:
            continue
        if winsor_scope == "quarter":
            g = g.copy()
            for c in [y, x_main] + [c for c in controls if c != "nasdaq"]:
                g[c] = winsorize(g[c], winsor_lo, winsor_hi)

        if drop_thin_industries > 0:
            ind_counts = g.groupby(industry_col).size()
            keep = ind_counts[ind_counts >= drop_thin_industries].index
            g = g[g[industry_col].isin(keep)]
            if len(g) < min_obs:
                continue

        if freq_weight:
            dc = g.groupby("date_filed").size()
            wt = (1.0 / g["date_filed"].map(dc)).astype(float).values
        else:
            wt = np.ones(len(g))

        ind_d = pd.get_dummies(g[industry_col], prefix="ff48",
                               drop_first=True).astype(float)
        X = pd.concat([g[all_vars].astype(float).reset_index(drop=True),
                       ind_d.reset_index(drop=True)], axis=1)
        X = sm.add_constant(X, has_constant="add")
        cols = list(X.columns)
        yvec = g[y].astype(float).values
        try:
            res = sm.WLS(yvec, X.values, weights=wt).fit()
            for v in all_vars:
                if v in cols:
                    betas_by_var[v].append(res.params[cols.index(v)])
                else:
                    betas_by_var[v].append(np.nan)
            ar2s.append(res.rsquared_adj)
            ns.append(int(res.nobs))
        except Exception:
            continue

    if not ar2s:
        out = {"n": 0, "n_quarters": 0, "r2_avg": np.nan}
        for v in all_vars:
            out[f"{v}_coef"] = np.nan
            out[f"{v}_t"] = np.nan
        return out

    ns_arr = np.array(ns, dtype=float)
    out = {"n": int(np.sum(ns)), "n_quarters": len(ar2s),
           "r2_avg": float(np.mean(ar2s))}
    for v in all_vars:
        betas = np.array(betas_by_var[v], dtype=float)
        try:
            if ts_weight_by_n:
                nw = sm.WLS(betas, np.ones(len(betas)), weights=ns_arr,
                            missing="drop").fit(cov_type="HAC",
                                                cov_kwds={"maxlags": nw_lags})
            else:
                nw = sm.OLS(betas, np.ones(len(betas)),
                            missing="drop").fit(cov_type="HAC",
                                                cov_kwds={"maxlags": nw_lags})
            out[f"{v}_coef"] = float(nw.params[0])
            out[f"{v}_t"] = float(nw.params[0] / nw.bse[0]) if nw.bse[0] else np.nan
        except Exception:
            out[f"{v}_coef"] = np.nan
            out[f"{v}_t"] = np.nan
    # Backward-compat keys
    out["coef"] = out.get(f"{x_main}_coef", np.nan)
    out["t"] = out.get(f"{x_main}_t", np.nan)
    return out


# --------------------------------------------------------------------------- #
# Run one config across 4 cells (IV col2/4, V col2/4) and return rows        #
# --------------------------------------------------------------------------- #

def run_config(panel_label: str, panel: pd.DataFrame,
               config_label: str, **kw) -> list[dict]:
    controls = ["log_size", "log_bm", "log_turnover",
                "ff_alpha_pre", "nasdaq", "io"]
    panel = panel.copy()
    panel["date_filed"] = pd.to_datetime(panel["date_filed"])
    panel["fin_neg_prop_mda"] = np.where(
        panel["n_words_mda"] > 0,
        100.0 * panel["n_neg_mda"] / panel["n_words_mda"], np.nan)

    pV = panel[panel["mdna_status"].astype(str).str.startswith("ok").fillna(False)]

    rows = []
    for ff48 in (True, False):
        ind_col = "ff48" if ff48 else None
        # Inject a constant single-level industry to skip dummies
        if ind_col is None:
            panel_use = panel.copy(); panel_use["_one"] = 1
            pV_use = pV.copy(); pV_use["_one"] = 1
            ind_col = "_one"
        else:
            panel_use = panel
            pV_use = pV

        for label, df_use, var in [
            ("IV_col2_prop",       panel_use, "fin_neg_prop"),
            ("IV_col4_tfidf",      panel_use, "fin_neg_tfidf_full"),
            ("V_col2_prop_mda",    pV_use,    "fin_neg_prop_mda"),
            ("V_col4_tfidf_mda",   pV_use,    "fin_neg_tfidf_mda"),
        ]:
            r = fama_macbeth(df_use, "excret_03", var, controls,
                             industry_col=ind_col, **kw)
            r.update({"panel": panel_label, "config": config_label,
                      "ff48": ff48, "cell": label, "sentiment_var": var})
            rows.append(r)
    return rows


# --------------------------------------------------------------------------- #
# Main: enumerate variants                                                    #
# --------------------------------------------------------------------------- #

def main() -> None:
    t0 = time.monotonic()
    all_rows = []

    panels_to_try = []
    # Default panel (compustat_only link, current dictionary)
    if PANEL_DEFAULT.exists():
        panels_to_try.append(("default", PANEL_DEFAULT))
    # Alternative panels written by earlier runs (if present)
    for tag, path in [
        ("dict_pos_only",     OUT / "panel_dict_pos_only.parquet"),
        ("link_with_comphist", OUT / "panel_link_with_comphist.parquet"),
        ("shrcd_10_11",        OUT / "panel_shrcd_10_11.parquet"),
        ("shrcd_10_11_12_18",  OUT / "panel_shrcd_10_11_12_18.parquet"),
        ("sic_sich",           OUT / "panel_sic_sich.parquet"),
        ("sic_sic",            OUT / "panel_sic_sic.parquet"),
        ("sic_header",         OUT / "panel_sic_header.parquet"),  # NEW
    ]:
        if path.exists():
            panels_to_try.append((tag, path))

    print(f"Panels to test: {[p for p, _ in panels_to_try]}")

    # Regression-side variant grid (run on each available panel).
    # Defaults: freq_weight=False, ts_weight_by_n=True, min_obs=30, nw_lags=1,
    #           winsor_scope="full", drop_thin_industries=0.
    variants = [
        # ---- weighting variants ----
        dict(label="A_baseline_TSwt",            freq_weight=False, ts_weight_by_n=True),
        dict(label="B_equal_weight_FM",          freq_weight=False, ts_weight_by_n=False),
        dict(label="C_WLS_1_over_n_same_date",   freq_weight=True,  ts_weight_by_n=False),
        dict(label="D_WLS_freq_plus_TSwt",       freq_weight=True,  ts_weight_by_n=True),
        # ---- min_obs per quarter ----
        dict(label="E_min_obs_50",               freq_weight=False, ts_weight_by_n=True, min_obs=50),
        dict(label="F_min_obs_100",              freq_weight=False, ts_weight_by_n=True, min_obs=100),
        # ---- Newey-West lag ----
        dict(label="G_NW_lag_3",                 freq_weight=False, ts_weight_by_n=True, nw_lags=3),
        dict(label="H_NW_lag_6",                 freq_weight=False, ts_weight_by_n=True, nw_lags=6),
        # ---- winsorization scope ----
        dict(label="I_winsor_within_quarter",    freq_weight=False, ts_weight_by_n=True,
             winsor_scope="quarter"),
        dict(label="J_no_winsor",                freq_weight=False, ts_weight_by_n=True,
             winsor_scope="none"),
        # ---- drop thin FF48-quarter cells ----
        dict(label="K_drop_ff48_qtr_lt_5",       freq_weight=False, ts_weight_by_n=True,
             drop_thin_industries=5),
        dict(label="L_drop_ff48_qtr_lt_10",      freq_weight=False, ts_weight_by_n=True,
             drop_thin_industries=10),
    ]

    for panel_label, panel_path in panels_to_try:
        print(f"\n=== Loading {panel_label} ({panel_path.name}) ===")
        panel = pd.read_parquet(panel_path)
        print(f"  rows: {len(panel):,}, unique permnos: {panel['permno'].nunique():,}")

        for v in variants:
            label = v.pop("label")
            print(f"  variant {label} ...")
            try:
                rows = run_config(panel_label, panel, label, **v)
                all_rows.extend(rows)
            except Exception as e:
                print(f"    ERROR: {e}")
            v["label"] = label  # restore for next loop

    df = pd.DataFrame(all_rows)
    out_csv = OUT / "variant_grid_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}  ({len(df):,} rows)")

    # Print a compact pivot
    print("\nCompact view (IV col(2) and col(4) full-text, with FF48):")
    pv = df[(df["cell"].isin(["IV_col2_prop", "IV_col4_tfidf"])) & (df["ff48"] == True)]
    for panel_label in pv["panel"].unique():
        print(f"\n  Panel: {panel_label}")
        sub = pv[pv["panel"] == panel_label]
        for var in ["fin_neg_prop", "fin_neg_tfidf_full"]:
            s = sub[sub["sentiment_var"] == var].sort_values("t")
            for r in s.itertuples():
                print(f"    {r.config:32s} {var:22s} coef={r.coef:+.4f} t={r.t:+.2f} r2={r.r2_avg*100:.2f}%")

    print(f"\nDone. Elapsed: {(time.monotonic()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
