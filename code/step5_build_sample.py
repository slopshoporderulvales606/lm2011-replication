"""
Step 5: Apply the Table I sample funnel to produce the LM (2011) analysis sample.

Configurable via env vars:
  - LM_SHRCD       : comma-separated CRSP share-codes to keep (default "10,11")
  - LM_LINK_MODE   : "compustat_only" or "compustat_with_comphist" (default the latter)

Note (per Loughran-McDonald 2011 footnote 5): the WRDS SEC Suite link table
between CIK and GVKEY is what `compustat_gvkey_permno.dta` actually contains
(it has CIK directly merged onto each Compustat row). LM uses a "WDS CIK file"
to map CIK to PERMNO; we approximate that by going through GVKEY since WRDS
doesn't ship a direct CIK ↔ PERMNO file. comphist_cik_gvkey.dta is point-in-time
and can serve as a fallback for filings where compustat doesn't have the cik.

Inputs:
  - output/filing_word_counts.parquet     (from step 4)
  - manifest/filings_10k_1994_2008.parquet
  - input/compustat_gvkey_permno.dta      (PRIMARY CIK ↔ GVKEY/PERMNO link)
  - input/comphist_cik_gvkey.dta          (OPTIONAL fallback)
  - input/crsp_daily_1993_2019.dta
  - input/crsp_monthly_1993_2019.dta

Outputs:
  - output/filing_to_gvkey_permno.parquet
  - output/sample.parquet
  - output/table1_sample_funnel.csv
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(r"D:\Sentiment_analysis_project")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
INP = ROOT / "input"
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)

MAN = DATA_ROOT / "manifest" / "filings_10k_1994_2008.parquet"
WC = OUT / "filing_word_counts.parquet"
COMPHIST = INP / "comphist_cik_gvkey.dta"
COMPUSTAT = INP / "compustat_gvkey_permno.dta"
CRSP_DAILY = INP / "crsp_daily_1993_2019.dta"
CRSP_MONTHLY = INP / "crsp_monthly_1993_2019.dta"


def now() -> float:
    return time.monotonic()


def load_manifest_10k() -> pd.DataFrame:
    """Per LM (2011) appendix: 10-K and 10-K405 ONLY (drop 10-KSB family)."""
    df = pd.read_parquet(MAN)
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    df = df[df["form_type"].isin(["10-K", "10-K405"])].copy()
    df = (df.sort_values("date_filed")
            .drop_duplicates("accession").reset_index(drop=True))
    df["filing_year"] = df["date_filed"].dt.year
    df["cik"] = df["cik"].astype("int64")
    return df


def load_wordcounts() -> pd.DataFrame:
    df = pd.read_parquet(WC)
    df["accession"] = df["accession"].astype(str)
    return df


def load_comphist() -> pd.DataFrame:
    """Primary CIK ↔ GVKEY link with effective intervals."""
    df = pd.read_stata(COMPHIST)
    df["cik"] = pd.to_numeric(df["cik"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["cik"]).copy()
    df["cik"] = df["cik"].astype("int64")
    df["linkdt"] = pd.to_datetime(df["linkdt"], errors="coerce")
    df["linkenddt"] = pd.to_datetime(df["linkenddt"], errors="coerce")
    # Open-ended links: set sentinel
    df["linkenddt"] = df["linkenddt"].fillna(pd.Timestamp("2099-12-31"))
    df["linkdt"] = df["linkdt"].fillna(pd.Timestamp("1900-01-01"))
    return df[["cik", "gvkey", "linkdt", "linkenddt"]].copy()


def load_compustat_cik_link() -> pd.DataFrame:
    """Fallback CIK ↔ (gvkey, permno) via Compustat header."""
    cols = ["gvkey", "permno", "cik", "fyear", "datadate", "exchg", "sic", "sich",
            "be", "bm", "mktValue", "at"]
    df = pd.read_stata(COMPUSTAT, columns=cols)
    df["cik"] = pd.to_numeric(df["cik"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["cik", "gvkey"]).copy()
    df["cik"] = df["cik"].astype("int64")
    df["fyear"] = df["fyear"].astype("Int64")
    df["permno"] = df["permno"].astype("Int64")
    df["datadate"] = pd.to_datetime(df["datadate"], errors="coerce")
    return df


def link_cik_to_gvkey(filings: pd.DataFrame,
                      compustat: pd.DataFrame,
                      comphist: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Primary link: Compustat (CIK ↔ GVKEY+PERMNO via WRDS SEC Suite). Each filing
        gets the gvkey/permno from the Compustat row whose fyear is closest to
        (filing_year - 1).
    Optional fallback: comphist (point-in-time CIK ↔ GVKEY). Used only for
        filings without a Compustat-cik match.

    Adds match_source ∈ {'compustat', 'comphist', 'none'}.
    """
    f = filings[["accession", "cik", "date_filed", "filing_year"]].copy()

    # PRIMARY: Compustat (CIK direct).
    cmp_keys = compustat.dropna(subset=["gvkey", "fyear", "permno"])[
        ["cik", "gvkey", "permno", "fyear"]
    ].copy()
    cand = f.merge(cmp_keys, on="cik", how="left")
    cand["diff"] = (cand["fyear"] - (cand["filing_year"] - 1)).abs()
    cand = cand.sort_values(["accession", "diff", "fyear"],
                            ascending=[True, True, False])
    fA = cand.drop_duplicates("accession", keep="first")[
        ["accession", "gvkey", "permno"]
    ].rename(columns={"gvkey": "gvkey_A", "permno": "permno_A"})

    out = f.merge(fA, on="accession", how="left")
    out["gvkey"] = out["gvkey_A"]
    out["permno"] = out["permno_A"]
    out["match_source"] = np.where(out["gvkey_A"].notna(), "compustat", "none")

    # OPTIONAL FALLBACK: comphist.
    if comphist is not None and len(comphist) > 0:
        miss = out["gvkey"].isna()
        if miss.any():
            f_miss = out.loc[miss, ["accession", "cik", "date_filed", "filing_year"]]
            fB = f_miss.merge(comphist, on="cik", how="left")
            in_range = (fB["date_filed"] >= fB["linkdt"]) & (fB["date_filed"] <= fB["linkenddt"])
            fB = fB[in_range].sort_values(["accession", "linkdt"]).drop_duplicates("accession", keep="last")
            fB = fB[["accession", "gvkey", "filing_year"]].rename(columns={"gvkey": "gvkey_B"})
            # map fb's gvkey → permno via compustat closest-fyear lookup
            permno_lookup = (compustat.dropna(subset=["gvkey", "permno", "fyear"])
                             [["gvkey", "permno", "fyear"]].copy())
            permno_lookup["gvkey"] = permno_lookup["gvkey"].astype("int64")
            fB["gvkey_B_int"] = pd.to_numeric(fB["gvkey_B"], errors="coerce").astype("Int64")
            cand2 = fB[["accession", "gvkey_B_int", "filing_year"]].rename(
                columns={"gvkey_B_int": "gvkey"}).merge(permno_lookup, on="gvkey", how="left")
            cand2["diff"] = (cand2["fyear"] - (cand2["filing_year"] - 1)).abs()
            cand2 = cand2.sort_values(["accession", "diff"]).drop_duplicates("accession", keep="first")
            fB_merged = fB[["accession", "gvkey_B"]].merge(
                cand2[["accession", "permno"]], on="accession", how="left"
            ).rename(columns={"gvkey_B": "gvkey_B_val", "permno": "permno_B_val"})

            out = out.merge(fB_merged, on="accession", how="left")
            fill_mask = out["gvkey"].isna() & out["gvkey_B_val"].notna()
            out.loc[fill_mask, "gvkey"] = out.loc[fill_mask, "gvkey_B_val"]
            out.loc[fill_mask, "permno"] = out.loc[fill_mask, "permno_B_val"]
            out.loc[fill_mask, "match_source"] = "comphist"

    return out[["accession", "cik", "date_filed", "filing_year",
                "gvkey", "permno", "match_source"]]


def load_crsp_monthly_min() -> pd.DataFrame:
    """Slice with shrcd / exchcd / siccd / prc for point-in-time filters."""
    cols = ["permno", "yrmon", "shrcd", "exchcd", "siccd", "prc"]
    df = pd.read_stata(CRSP_MONTHLY, columns=cols)
    df["permno"] = df["permno"].astype("int64")
    df["yrmon"] = pd.to_datetime(df["yrmon"])
    return df


def lookup_crsp_monthly(linked: pd.DataFrame, crspm: pd.DataFrame) -> pd.DataFrame:
    """
    Attach shrcd / exchcd / siccd from CRSP monthly at the filing month.
    Falls back to nearest preceding month (within 12 months) via groupby ffill.
    """
    s = linked.copy()
    s["yrmon"] = pd.to_datetime(
        s["date_filed"].dt.to_period("M").dt.to_timestamp())
    s = s.dropna(subset=["permno"]).copy()
    s["permno"] = s["permno"].astype("int64")

    # Build a full (permno × month) grid then forward-fill so we can do an
    # exact-month merge with no missingness for permnos that ever traded.
    cm = crspm.sort_values(["permno", "yrmon"]).copy()
    cm["permno"] = cm["permno"].astype("int64")
    cm["yrmon"] = pd.to_datetime(cm["yrmon"])
    cm = cm.drop_duplicates(["permno", "yrmon"], keep="last")

    # Exact-month merge
    j = s.merge(cm[["permno", "yrmon", "shrcd", "exchcd", "siccd", "prc"]],
                on=["permno", "yrmon"], how="left")

    # For misses, pick the most recent prior observation per permno (groupby).
    miss = j["shrcd"].isna()
    if miss.any():
        # Build a small lookup using merge_asof properly (sort GLOBALLY by yrmon).
        left = j[miss][["accession", "permno", "yrmon"]].sort_values("yrmon")
        right = cm[["permno", "yrmon", "shrcd", "exchcd", "siccd", "prc"]].sort_values("yrmon")
        bb = pd.merge_asof(
            left, right, on="yrmon", by="permno",
            direction="backward", tolerance=pd.Timedelta(days=400),
        )
        bb = bb[["accession", "shrcd", "exchcd", "siccd", "prc"]].dropna(subset=["shrcd"])
        j = j.set_index("accession")
        bb = bb.set_index("accession")
        for c in ["shrcd", "exchcd", "siccd", "prc"]:
            j.loc[bb.index, c] = bb[c]
        j = j.reset_index()

    return j


def load_crsp_daily_min(years: tuple[int, int]) -> pd.DataFrame:
    """
    Read the relevant slice of CRSP daily into RAM. 5.5 GB file → use cols-only.
    """
    cols = ["permno", "date", "prc", "ret", "vol", "shrout",
            "vwretd", "mktrf", "smb", "hml", "rf"]
    df = pd.read_stata(CRSP_DAILY, columns=cols)
    df["permno"] = df["permno"].astype("int64")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"].dt.year >= years[0]) & (df["date"].dt.year <= years[1])].copy()
    return df


def event_window_check(sample: pd.DataFrame, crspd: pd.DataFrame
                       ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Return (ev_ok, pre_post_ok, prc_day_minus_1) aligned to sample.
        ev_ok            — ≥4 valid daily returns AND volume obs in [0,+3]
        pre_post_ok      — ≥60 valid returns+volume in 252 days before AND
                           ≥60 valid returns+volume in 252 days after (LM filter 10)
        prc_day_minus_1  — absolute price on the trading day immediately before
                           the filing (LM Table I filter 7: ≥ $3)
    """
    crspd_valid = crspd.dropna(subset=["ret"]).copy()
    crspd_valid["vol_valid"] = crspd_valid["vol"].notna() & (crspd_valid["vol"] >= 0)
    by_permno = {p: g.sort_values("date") for p, g in crspd_valid.groupby("permno")}

    ev_ok = []
    pre_post_ok = []
    prc_m1 = []
    for r in sample.itertuples(index=False):
        permno = int(r.permno) if not pd.isna(r.permno) else None
        if permno is None or permno not in by_permno:
            ev_ok.append(False); pre_post_ok.append(False); prc_m1.append(np.nan); continue
        g = by_permno[permno]
        d = r.date_filed

        # Event window [0, +3]: returns AND volume both required.
        ev = g[g["date"] >= d].head(4)
        ev_returns_ok = (len(ev) == 4) and ev["ret"].notna().all() and ev["vol_valid"].all()
        ev_ok.append(bool(ev_returns_ok))

        # Find day -1 price (trading day immediately before filing): use the
        # last bar with date strictly < filing date. (If ev_returns_ok is False
        # we may not have a valid event-day-0 reference, but day -1 is well-
        # defined as the last bar before filing_date.)
        before_filing = g[g["date"] < d]
        if len(before_filing) == 0:
            prc_m1.append(np.nan)
        else:
            prc_m1.append(abs(float(before_filing.iloc[-1]["prc"])))

        if not ev_returns_ok:
            pre_post_ok.append(False); continue
        ev0 = ev["date"].iloc[0]

        # Pre window: 252 trading days ending day -6
        before = g[g["date"] < ev0]
        if len(before) < 65:
            pre_post_ok.append(False); continue
        pre_252 = before.tail(252 + 5)
        pre_252 = pre_252.iloc[:-5] if len(pre_252) > 5 else pre_252  # drop -5..-1
        pre_valid = (pre_252["ret"].notna() & pre_252["vol_valid"]).sum()

        # Post window: 252 trading days starting day +6 (LM filter 10)
        after = g[g["date"] > ev["date"].iloc[-1]]
        post_252 = after.head(252)
        post_valid = (post_252["ret"].notna() & post_252["vol_valid"]).sum()

        pre_post_ok.append(bool(pre_valid >= 60 and post_valid >= 60))

    return (pd.Series(ev_ok, index=sample.index),
            pd.Series(pre_post_ok, index=sample.index),
            pd.Series(prc_m1, index=sample.index, dtype=float))


def main() -> None:
    """
    Apply Table I filters in LM (2011) order:
       1. EDGAR 10-K / 10-K405 unique accessions
       2. First filing per (cik, calendar year)
       3. ≥ 180 days between firm's 10-K filings
       4. CRSP PERMNO match
       5. shrcd ∈ {10, 11}
       6. CRSP market cap available
       7. |prc| ≥ $3 on day −1
       8. Returns + volume for [0, +3] event window
       9. NYSE/AMEX/NASDAQ listing
      10. ≥ 60 days returns + volume before AND after filing
      11. BM available + book equity > 0
      12. N_Words ≥ 2,000
    """
    t0 = now()
    funnel = []

    # CONFIG via env vars.
    shrcd_codes_env = os.environ.get("LM_SHRCD", "10,11")
    shrcd_codes = [float(x) for x in shrcd_codes_env.split(",")]
    link_mode = os.environ.get("LM_LINK_MODE", "compustat_with_comphist")
    run_tag = os.environ.get("LM_RUN_TAG", "default")
    print(f"Config: shrcd in {shrcd_codes}, link_mode = {link_mode}, tag = {run_tag}")

    print("Loading manifest ...")
    fil = load_manifest_10k()
    funnel.append(("01_EDGAR_10K_10K405_unique", len(fil)))

    # Filter 2: First filing per (cik, calendar year)
    fil = fil.sort_values("date_filed").drop_duplicates(
        ["cik", "filing_year"], keep="first").reset_index(drop=True)
    funnel.append(("02_first_filing_per_cik_year", len(fil)))

    # Filter 3: ≥ 180 days between same-firm 10-K filings
    fil = fil.sort_values(["cik", "date_filed"])
    fil["prev_date"] = fil.groupby("cik")["date_filed"].shift(1)
    fil["gap_days"] = (fil["date_filed"] - fil["prev_date"]).dt.days
    fil = fil[(fil["gap_days"].isna()) | (fil["gap_days"] >= 180)].copy()
    fil = fil.drop(columns=["prev_date", "gap_days"]).reset_index(drop=True)
    funnel.append(("03_ge_180_days_between_filings", len(fil)))

    # Filter 4: CRSP PERMNO match (via gvkey link)
    print("Linking CIK → GVKEY → PERMNO ...")
    compustat = load_compustat_cik_link()
    comphist = load_comphist() if link_mode == "compustat_with_comphist" else None
    link = link_cik_to_gvkey(fil, compustat, comphist)
    link.to_parquet(OUT / "filing_to_gvkey_permno.parquet", index=False)
    print("  match_source counts:")
    print(link["match_source"].value_counts().to_string())

    sample = fil.merge(link[["accession", "gvkey", "permno", "match_source"]],
                       on="accession", how="left")
    sample = sample[(sample["match_source"] != "none") & sample["permno"].notna()].copy()
    sample["permno"] = sample["permno"].astype("int64")
    funnel.append(("04_CRSP_PERMNO_match", len(sample)))

    # Filter 5: shrcd ∈ {10, 11}
    print("Joining CRSP monthly (shrcd/exchcd/siccd/prc at filing month) ...")
    crspm = load_crsp_monthly_min()
    sample = lookup_crsp_monthly(sample, crspm)
    sample = sample[sample["shrcd"].isin(shrcd_codes)].copy()
    funnel.append((f"05_shrcd_{shrcd_codes_env.replace(',','_')}", len(sample)))

    # Filter 6: CRSP market cap available (require non-null monthly prc as proxy)
    sample = sample[sample["prc"].notna()].copy()
    funnel.append(("06_CRSP_mkt_cap_available", len(sample)))

    # Load CRSP daily early so we can compute day -1 price (LM Table I filter 7).
    print("Loading CRSP daily slice ...")
    crspd = load_crsp_daily_min(years=(1993, 2010))
    print("Checking event window + pre/post windows + day-1 price ...")
    ev_ok, pp_ok, prc_m1 = event_window_check(sample, crspd)
    sample["prc_day_minus_1"] = prc_m1.values

    # Filter 7: |prc| ≥ $3 on trading day immediately before filing (LM page 40).
    sample = sample[sample["prc_day_minus_1"].notna() &
                    (sample["prc_day_minus_1"] >= 3.0)].copy()
    ev_ok = ev_ok.reindex(sample.index, fill_value=False)
    pp_ok = pp_ok.reindex(sample.index, fill_value=False)
    funnel.append(("07_price_ge_3_day_minus_1", len(sample)))

    # Filter 8: returns + volume for [0,3] event window
    sample = sample[ev_ok.values].copy()
    pp_ok = pp_ok.reindex(sample.index, fill_value=False)
    funnel.append(("08_returns_volume_event_window", len(sample)))

    # Filter 9: exchcd ∈ {1, 2, 3}
    sample = sample[sample["exchcd"].isin([1.0, 2.0, 3.0])].copy()
    pp_ok = pp_ok.reindex(sample.index, fill_value=False)
    funnel.append(("09_NYSE_AMEX_NASDAQ", len(sample)))

    # Filter 10: ≥60 days returns + volume in 252 days before AND after filing
    sample = sample[pp_ok.values].copy()
    funnel.append(("10_ge_60d_pre_AND_post", len(sample)))

    # Filter 11: BM available + book equity > 0
    print("Joining Compustat annuals (mktValue/bm/be at fyear-1) ...")
    cmp_full = compustat[["gvkey", "fyear", "mktValue", "bm", "be", "at",
                          "sich", "sic", "exchg"]].copy()
    cmp_full["fyear"] = cmp_full["fyear"].astype("Int64")
    cmp_full["gvkey"] = cmp_full["gvkey"].astype("int64")
    sample["fyear_prev"] = (sample["filing_year"] - 1).astype("Int64")
    sample["gvkey"] = pd.to_numeric(sample["gvkey"], errors="coerce").astype("int64")
    sample = sample.merge(
        cmp_full, left_on=["gvkey", "fyear_prev"], right_on=["gvkey", "fyear"],
        how="left", suffixes=("", "_cmp"))
    sample = sample[sample["bm"].notna() & sample["be"].notna() &
                    (sample["be"] > 0) & sample["mktValue"].notna()].copy()
    funnel.append(("11_BM_avail_book_gt_0", len(sample)))

    # Filter 12: N_Words ≥ 2,000
    wc = load_wordcounts()
    keep = wc[(wc["ok"]) & (wc["n_words_full"] >= 2000)]["accession"]
    sample = sample[sample["accession"].isin(set(keep))].copy()
    funnel.append(("12_Nwords_ge_2000", len(sample)))

    # Write outputs (per-run-tag funnel CSV, single sample.parquet).
    sample.to_parquet(OUT / "sample.parquet", index=False)
    funnel_path = OUT / f"table1_sample_funnel_{run_tag}.csv"
    try:
        pd.DataFrame(funnel, columns=["step", "rows"]).to_csv(funnel_path, index=False)
        print(f"  Wrote {funnel_path.name}")
    except PermissionError:
        print(f"  WARN: {funnel_path.name} locked; skipping CSV write")
    # Also write a generic copy for backward compatibility
    try:
        pd.DataFrame(funnel, columns=["step", "rows"]).to_csv(
            OUT / "table1_sample_funnel.csv", index=False)
    except PermissionError:
        pass

    print("\nTable I funnel (LM order):")
    for step, n in funnel:
        print(f"  {step:<40s}  {n:>8,}")
    n_firms = sample["permno"].nunique()
    print(f"\nFinal sample firm-years : {len(sample):,}  (target 50,115)")
    print(f"Unique permnos          : {n_firms:,}  (target 8,341)")

    elapsed = now() - t0
    print(f"\nDone. Elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
