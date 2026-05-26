"""
preclean.py — Replaces all Stata preclean code (upstream + preclean.do).

Loads CRSP daily, CRSP monthly, Compustat CCM annual, and Thomson Reuters
13F via the WRDS Python package; computes only the variables the LM (2011)
replication pipeline actually consumes; and writes the four input .dta files:

  input/compustat_gvkey_permno.dta        ← Compustat annual + CCM permno + BE/BM
  input/crsp_daily_1993_2019.dta          ← CRSP daily + FF5 daily merged
  input/crsp_monthly_1993_2019.dta        ← CRSP monthly (subset of columns)
  input/13f_instOwn_stock_level.dta       ← (permno, yqtr, instOwn) aggregation

Variables/derived measures NOT used by the pipeline are skipped:
  - mb, leverage, roa, roe, profitGross, ROA*, sga2*, CapEx2A, OpCycle, saleVol, CFVol …
  - industry10/12/49 (step 6 derives FF48 from CRSP siccd directly)
  - firmAge, naics2, ticker-class standardization, ncusip backfill loops
  - intermediate files (13f_temp2.dta, 13f_temp3.dta, compustat_all_variables.dta)
  - diagnostic count statements

Prerequisites:
  pip install wrds pandas pyreadstat
  WRDS pgpass file (run wrds.Connection(...).create_pgpass_file() once)

Usage (from project root):
  python code/preclean.py

If you forgot where pgpass lives:
  Windows:  %APPDATA%\\postgresql\\pgpass.conf
  Linux/Mac: ~/.pgpass
  If absent, the connection call below will prompt for password and offer
  to create it.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import wrds  # type: ignore

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "input"

# WRDS username — set via env var so this script can ship without exposing
# institutional credentials. Run `wrds.Connection().create_pgpass_file()` once
# beforehand to persist your password so the connection does not prompt.
WRDS_USER = os.environ.get("WRDS_USERNAME", "").strip()
if not WRDS_USER:
    sys.exit(
        "WRDS_USERNAME env var is not set. "
        "Export it as your WRDS login and rerun, e.g.:\n"
        "  export WRDS_USERNAME=your_wrds_login"
    )

# Date window: cover [-252,-6] before 1994 filings and [+6,+252] after 2008 filings
START_YR = 1992
END_YR = 2019


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Connecting to WRDS as user '{WRDS_USER}' ...")
    conn = wrds.Connection(wrds_username=WRDS_USER)
    try:
        t0 = time.monotonic()
        build_compustat(conn)
        build_crsp_monthly(conn)         # before 13F (13F needs the monthly file)
        build_crsp_daily(conn)
        build_13f_instOwn(conn)
        print(f"\nAll inputs built. Elapsed: {(time.monotonic()-t0)/60:.1f} min")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 1. Compustat CRSP-Merged Annual                                              #
# --------------------------------------------------------------------------- #

def build_compustat(conn: "wrds.Connection") -> None:
    """Compustat funda × CCM linkhist → permno-attached annual, with BE and BM."""
    print("\n[1/4] Compustat CCM annual ...")
    # comp.funda has sich (historical), comp.company has the static sic.
    # comp.funda does NOT have loc (HQ country) — that lives in comp.company.
    # We don't actually need loc downstream; skip it.
    sql = f"""
    SELECT a.gvkey, a.datadate, a.fyear,
           a.tic AS ticker, a.exchg,
           a.cik, a.cusip, a.conm AS coname,
           a.fic,
           a.at, a.lt, a.seq, a.ceq, a.upstk, a.txditc,
           a.pstkrv, a.pstkl, a.pstk,
           a.csho, a.prcc_f, a.mkvalt,
           a.sich, a.naicsh,
           c.sic,
           b.lpermno AS permno, b.lpermco AS permco
      FROM comp.funda a
      LEFT JOIN comp.company c ON a.gvkey = c.gvkey
      LEFT JOIN crsp.ccmxpf_lnkhist b
        ON a.gvkey = b.gvkey
       AND b.linkprim IN ('P', 'C')
       AND b.linktype IN ('LU', 'LC')              -- canonical CCM "usable" links
       AND a.datadate >= b.linkdt
       AND (b.linkenddt IS NULL OR a.datadate <= b.linkenddt)
     WHERE a.indfmt = 'INDL'
       AND a.datafmt = 'STD'
       AND a.popsrc  = 'D'
       AND a.consol  = 'C'
       AND a.curcd   = 'USD'
       AND a.fyear BETWEEN {START_YR} AND {END_YR}
    """
    cmp = conn.raw_sql(sql)

    # Some gvkey-fyear pairs land twice if the link table has overlapping
    # ranges. Keep the first (sorted by datadate then permno).
    cmp = (cmp.sort_values(["gvkey", "fyear", "datadate", "permno"])
              .drop_duplicates(["gvkey", "fyear"], keep="first"))

    # Drop rows missing total assets (the only required Compustat var)
    cmp = cmp[cmp["at"].notna()].copy()
    cmp["datadate"] = pd.to_datetime(cmp["datadate"])

    # exchg → string label (matches preclean.do)
    exchg_map = {11: "NYSE", 12: "AMEX", 14: "NASDAQ"}
    cmp["exchg"] = (cmp["exchg"].astype("Int64").map(exchg_map)
                                .fillna("OTHER").astype(str))

    # mktValue: prefer Compustat mkvalt; fallback to |prcc_f| × csho
    cmp["mktValue"] = cmp["mkvalt"].fillna(cmp["prcc_f"].abs() * cmp["csho"])

    # Book equity (Novy-Marx 2013 tiered definitions, per preclean.do)
    se = (cmp["seq"]
          .fillna(cmp["ceq"] + cmp["upstk"].fillna(0))
          .fillna(cmp["at"] - cmp["lt"]))
    dt = cmp["txditc"].fillna(0)
    ps = (cmp["pstkrv"].fillna(cmp["pstkl"])
                       .fillna(cmp["pstk"])
                       .fillna(0))
    cmp["be"] = se + dt - ps
    cmp.loc[cmp["be"] <= 0, "be"] = np.nan

    # Book-to-market
    cmp["bm"] = cmp["be"] / cmp["mktValue"]

    # Trim to the columns the pipeline actually reads
    keep = ["gvkey", "permno", "permco", "cik", "fyear", "datadate",
            "ticker", "exchg", "coname", "fic",
            "sic", "sich", "naicsh",
            "at", "be", "bm", "mktValue"]
    cmp = cmp[keep].copy()

    # Type cleanup so to_stata is happy
    for c in ["gvkey", "permno", "permco", "cik", "fyear", "sic", "sich"]:
        cmp[c] = pd.to_numeric(cmp[c], errors="coerce").astype("Int64")
    for c in ["ticker", "exchg", "coname", "fic", "naicsh"]:
        cmp[c] = cmp[c].astype(str).where(cmp[c].notna(), "")

    print(f"  rows: {len(cmp):,}  permno-matched: {cmp['permno'].notna().sum():,}")
    _save_dta(cmp, OUT / "compustat_gvkey_permno.dta")


# --------------------------------------------------------------------------- #
# 2. CRSP Monthly                                                              #
# --------------------------------------------------------------------------- #

def build_crsp_monthly(conn: "wrds.Connection") -> None:
    print("\n[2/4] CRSP monthly ...")
    sql = f"""
    SELECT a.permno, a.permco, a.date, a.prc, a.ret, a.retx, a.shrout, a.vol,
           b.shrcd, b.exchcd, b.siccd, b.hsiccd,
           b.ncusip, b.cusip
      FROM crsp.msf a
      LEFT JOIN crsp.msenames b
        ON a.permno = b.permno
       AND a.date >= b.namedt
       AND a.date <= COALESCE(b.nameendt, CURRENT_DATE)
     WHERE a.date BETWEEN '{START_YR}-01-01' AND '{END_YR}-12-31'
    """
    df = conn.raw_sql(sql)
    df["date"]  = pd.to_datetime(df["date"])
    df["prc"]   = df["prc"].abs()
    df["siccd"] = df["siccd"].replace(0, np.nan)
    df = df.drop_duplicates(["permno", "date"], keep="first").copy()

    df["yr"]    = df["date"].dt.year
    df["mon"]   = df["date"].dt.month
    df["yrmon"] = df["date"].values.astype("datetime64[M]").astype("datetime64[ns]")

    # 8-digit CUSIPs (pipeline reads cusip8/ncusip8)
    df["cusip8"]  = df["cusip"].astype(str).str[:8].replace("None", "")
    df["ncusip8"] = df["ncusip"].astype(str).str[:8].replace("None", "")

    # Pipeline-required columns; preserve order similar to current .dta
    keep = ["permno", "permco", "date", "yr", "mon", "yrmon",
            "prc", "ret", "retx", "shrout",
            "shrcd", "exchcd", "siccd", "hsiccd",
            "ncusip8", "cusip8"]
    df = df[keep].copy()
    for c in ["permno", "permco", "yr", "mon", "shrcd", "exchcd", "siccd", "hsiccd"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

    print(f"  rows: {len(df):,}")
    _save_dta(df, OUT / "crsp_monthly_1993_2019.dta")


# --------------------------------------------------------------------------- #
# 3. CRSP Daily + FF5                                                          #
# --------------------------------------------------------------------------- #

def build_crsp_daily(conn: "wrds.Connection") -> None:
    """CRSP daily × dsenames × dsi × FF5 daily, written as a single .dta.

    Queries year-by-year to manage memory (a single 1992-2019 query can use
    several GB of RAM).
    """
    print("\n[3/4] CRSP daily + FF5 ...")
    frames = []
    for yr in range(START_YR, END_YR + 1):
        sys.stdout.write(f"  {yr} ... ")
        sys.stdout.flush()
        sql = f"""
        SELECT a.permno, a.permco, a.date,
               a.prc, a.ret, a.retx, a.vol, a.shrout,
               b.shrcd, b.exchcd, b.siccd, b.hsiccd,
               c.vwretd, c.vwretx, c.ewretd, c.ewretx,
               d.mktrf, d.smb, d.hml, d.rf, d.rmw, d.cma
          FROM crsp.dsf a
          LEFT JOIN crsp.dsenames b
            ON a.permno = b.permno
           AND a.date >= b.namedt
           AND a.date <= COALESCE(b.nameendt, CURRENT_DATE)
          LEFT JOIN crsp.dsi c          ON a.date = c.date
          LEFT JOIN ff.fivefactors_daily d ON a.date = d.date
         WHERE a.date BETWEEN '{yr}-01-01' AND '{yr}-12-31'
        """
        df = conn.raw_sql(sql)

        df["date"]   = pd.to_datetime(df["date"])
        df["prc"]    = df["prc"].abs()
        df["shrout"] = df["shrout"] / 1000.0          # thousands → millions
        df["siccd"]  = df["siccd"].replace(0, np.nan)
        # Market-adjusted excess return (kept for compatibility; cheap)
        df["retAb"]  = df["retx"] - df["vwretx"]
        df = df.drop_duplicates(["permno", "date"], keep="first").copy()
        df["yr"]  = df["date"].dt.year
        df["mon"] = df["date"].dt.month

        frames.append(df)
        sys.stdout.write(f"{len(df):>9,}\n")
        sys.stdout.flush()

    daily = pd.concat(frames, ignore_index=True)
    print(f"  total: {len(daily):,}")

    keep = ["permno", "permco", "date", "yr", "mon",
            "prc", "ret", "retx", "vol", "shrout",
            "shrcd", "exchcd", "siccd", "hsiccd",
            "vwretd", "vwretx", "ewretd", "ewretx", "retAb",
            "mktrf", "smb", "hml", "rf", "rmw", "cma"]
    daily = daily[keep].copy()
    for c in ["permno", "permco", "yr", "mon", "shrcd", "exchcd", "siccd", "hsiccd"]:
        daily[c] = pd.to_numeric(daily[c], errors="coerce").astype("Int64")

    _save_dta(daily, OUT / "crsp_daily_1993_2019.dta")


# --------------------------------------------------------------------------- #
# 4. Thomson Reuters 13F → stock-quarter institutional ownership               #
# --------------------------------------------------------------------------- #

def build_13f_instOwn(conn: "wrds.Connection") -> None:
    """Build (permno, yqtr, instOwn).

    Steps:
      (a) Aggregate 13F holdings to (cusip, rdate), keeping the latest fdate
          for each (mgrno, cusip, rdate) — handles re-filings.
      (b) Join with CRSP monthly to get (permno, shrout) via 8-digit ncusip
          at the same year-month.
      (c) Aggregate to (permno, yqtr) — handle co-listed securities.
    """
    print("\n[4/4] Thomson Reuters 13F → institutional ownership ...")

    # WRDS has moved 13F data around over the years. Try the historic Thomson
    # table first (covers 1980-2020), then alternative names if missing.
    src_table = None
    for candidate in ("tfn.s34", "tfn.s34type1", "tr_13f.s34", "wrdsapps.s34h"):
        try:
            conn.raw_sql(f"SELECT 1 FROM {candidate} LIMIT 1")
            src_table = candidate
            break
        except Exception:
            continue
    if src_table is None:
        raise RuntimeError(
            "No 13F source table found on WRDS. Tried: tfn.s34, tfn.s34type1, "
            "tr_13f.s34, wrdsapps.s34h. Check WRDS listings at "
            "https://wrds-www.wharton.upenn.edu/ for the current 13F table name."
        )
    print(f"  source table: {src_table}")

    sql = f"""
    WITH latest AS (
        SELECT DISTINCT ON (mgrno, cusip, rdate)
               mgrno, cusip, rdate, shares
          FROM {src_table}
         WHERE rdate BETWEEN '{START_YR}-01-01' AND '{END_YR}-12-31'
           AND shares > 0
         ORDER BY mgrno, cusip, rdate, fdate DESC
    )
    SELECT cusip AS ncusip8, rdate, SUM(shares) AS total_shares
      FROM latest
     GROUP BY cusip, rdate
    """
    h = conn.raw_sql(sql)
    h["rdate"]   = pd.to_datetime(h["rdate"])
    h["ncusip8"] = h["ncusip8"].astype(str).str[:8]
    h = h[h["rdate"].dt.month.isin([3, 6, 9, 12])].copy()
    h["yr"]  = h["rdate"].dt.year
    h["mon"] = h["rdate"].dt.month
    print(f"  13F aggregated (cusip × rdate): {len(h):,} rows")

    # Pull permno/shrout from the CRSP monthly file we just wrote (so the join
    # is consistent with everything else in the pipeline).
    crspm = pd.read_stata(OUT / "crsp_monthly_1993_2019.dta",
                          columns=["permno", "ncusip8", "yr", "mon", "shrout"])
    crspm["ncusip8"] = crspm["ncusip8"].astype(str)
    crspm = crspm[crspm["ncusip8"].str.len() == 8].copy()

    merged = h.merge(crspm, on=["ncusip8", "yr", "mon"], how="inner")
    print(f"  joined with CRSP monthly:       {len(merged):,} rows")

    # shrout (in monthly file) is in thousands → multiply by 1000 to get shares
    merged["instOwn"] = merged["total_shares"] / (merged["shrout"] * 1000.0)

    # Calendar-quarter timestamp = LAST day of the quarter (matches `rdate`,
    # which is the 13F report date and is always quarter-end). step6 merges
    # on quarter-end as well.
    merged["yqtr"] = (pd.PeriodIndex(merged["rdate"], freq="Q")
                       .to_timestamp(how="end").normalize())

    # Aggregate across co-listed securities to one record per (permno, yqtr)
    inst = (merged.groupby(["permno", "yqtr"], as_index=False)["instOwn"]
                  .sum())
    inst["permno"] = inst["permno"].astype("int32")
    print(f"  final stock-quarter rows:       {len(inst):,}")

    _save_dta(inst, OUT / "13f_instOwn_stock_level.dta")


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _save_dta(df: pd.DataFrame, path: Path) -> None:
    """Write a DataFrame as a Stata .dta file with sensible type coercion.

    pandas.to_stata can't write:
      - Nullable Int64 columns directly → coerce to float64
      - ±inf values → coerce to NaN
      - object columns with mixed types → coerce to str
    """
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_extension_array_dtype(out[c]):
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
        if pd.api.types.is_object_dtype(out[c]):
            out[c] = out[c].astype(str).fillna("")
        elif pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].replace([np.inf, -np.inf], np.nan)
    out.to_stata(path, write_index=False)
    print(f"  saved → {path.name}  ({path.stat().st_size/1e6:,.1f} MB)")


if __name__ == "__main__":
    main()
