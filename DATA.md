# Required input data

This repository **does not include** any of the underlying data:

- **Raw SEC 10-K filings** (~20 GB compressed for 1994–2008; up to ~250 GB if extended through 2026) are excluded for size.
- **WRDS extracts** (CRSP, Compustat, Thomson Reuters 13F) are commercial data and cannot be redistributed.
- **SRAF reference data** (Loughran-McDonald Master Dictionary, per-filing word-count summaries, header metadata) is freely available from <https://sraf.nd.edu/sec-edgar-data/> but is not bundled here to keep the repo lean.
- **Copyrighted journal PDFs** are excluded; link to the publishers below.

This document explains what you need, where to get it, and where to put it.

---

## Expected local layout

The pipeline expects the following layout. **None of these folders are committed to Git** (see `.gitignore`); you create them locally:

```
.
├── input/                            # WRDS extracts + reference data (NOT committed)
│   ├── compustat_gvkey_permno.dta    ← from preclean.py (WRDS Compustat-CCM)
│   ├── comphist_cik_gvkey.dta        ← from preclean.py (historical fallback link)
│   ├── crsp_daily_1993_2019.dta      ← from preclean.py (CRSP daily + FF factors)
│   ├── crsp_monthly_1993_2019.dta    ← from preclean.py (CRSP monthly)
│   ├── 13f_instOwn_stock_level.dta   ← from preclean.py (Thomson Reuters 13F)
│   ├── Loughran-McDonald_MasterDictionary_1993-2025.csv   ← SRAF
│   ├── Loughran-McDonald_10X_Summaries_1993-2025.csv      ← SRAF (validation only)
│   ├── Siccodes48.txt                                     ← Ken French data library (not bundled — see §5)
│   └── README.md                                          ← (committed)
│
└── (off-repo, configurable via DATA_ROOT constant)
    └── D:\Data\10_K_10_Q\
        ├── raw\10K\<YYYY>\<cik>_<accession>.txt.gz   ← from step3 downloader
        ├── raw\10Q\<YYYY>\<cik>_<accession>.txt.gz   ← (extended pipeline only)
        ├── manifest\filings_10k_1994_2008.parquet
        └── index\master_<YYYY>_Q<q>.gz
```

---

## 1. CRSP data (WRDS)

| File | Description | Source |
|---|---|---|
| `crsp_daily_1993_2019.dta` | CRSP daily stock file with FF daily factors merged in | `crsp.dsf` + `ff.fivefactors_daily` |
| `crsp_monthly_1993_2019.dta` | CRSP monthly stock file | `crsp.msf` + `crsp.msenames` |

**Variables used downstream**: `permno, date, prc, ret, vol, shrout, shrcd, exchcd, siccd, vwretd, mktrf, smb, hml, rf`.

`shrout` in the CRSP daily file is in **millions** of shares (verified empirically: AAPL Jan 2007 ≈ 860 → 860 M shares). Both extracts are produced by [`code/preclean.py`](code/preclean.py).

---

## 2. Compustat data (WRDS, via SEC Suite link)

| File | Description |
|---|---|
| `compustat_gvkey_permno.dta` | Compustat annual joined with the CCM link table and a direct CIK column |
| `comphist_cik_gvkey.dta` | Historical CIK ↔ GVKEY link table with effective date ranges (optional fallback) |

The baseline uses `compustat_gvkey_permno.dta` as the primary CIK ↔ PERMNO bridge, per LM (2011) footnote 5. Linking logic: filter CCM to `linkprim ∈ {P,C}` and `linktype ∈ {LU,LC}`; for each filing, pick the row whose `fyear` is closest to `filing_year − 1`. Book equity is built per the Novy-Marx tiered definition (`seq → ceq+upstk → at − lt`; plus `txditc`; minus `pstkrv → pstkl → pstk`).

Produced by [`code/preclean.py`](code/preclean.py).

---

## 3. 13F institutional ownership (WRDS via Thomson Reuters)

| File | Description |
|---|---|
| `13f_instOwn_stock_level.dta` | Quarter-end stock-level institutional ownership (Σ shares held by 13F filers ÷ shrout) |

Source table: `tfn.s34`. Built with `DISTINCT ON (mgrno, cusip, rdate)` keeping the latest `fdate` per holdings filing, aggregated by `(cusip, rdate)`, joined to CRSP monthly by NCUSIP×year×month. `yqtr` is the calendar-quarter-end (matches `rdate`).

Produced by [`code/preclean.py`](code/preclean.py).

---

## 4. SRAF reference data (free download)

Available from <https://sraf.nd.edu/sec-edgar-data/>:

| File | Use |
|---|---|
| `Loughran-McDonald_MasterDictionary_1993-2025.csv` | **Required** — drives word-level negative / positive flags |
| `Loughran-McDonald_10X_Summaries_1993-2025.csv` | **Validation only** — per-filing word counts maintained by the SRAF team; never substituted into the regression. See `docs/baseline_vs_LM.md`. |
| `LoughranMcDonald_10-K_HeaderData_1993-2025.csv` | Optional 10-K filer header metadata |
| `Loughran-McDonald_EDGAR_MasterIndexAnalysis_1993-2024.xlsx` | Filing tabulations (reference) |
| Documentation PDF for the Master Dictionary | Reference (link from the SRAF site) |

The Master Dictionary is the canonical Loughran-McDonald list of ~86,553 words with per-word `Negative / Positive / Uncertainty / Litigious / StrongModal / WeakModal / Constraining` flags. My `N_Negative` counts tokens whose `Negative ≠ 0` (the integer is the year of inclusion).

---

## 5. Fama-French industry classification (Ken French data library)

`code/step6_build_panel.py` parses **`input/Siccodes48.txt`** — Ken French's
Fama-French 48-industry SIC mapping.

**This file is NOT bundled with the repository.** Download it directly from
Ken French's data library:

- Page: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html>
- Direct link: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes48.zip>
  → unzip → place `Siccodes48.txt` in `input/`.

The file is a plain-text mapping of SIC-code ranges to 48 industry buckets
(33 KB). Free for academic / personal use per Prof. French's site terms.

---

## 6. Raw 10-K filings (SEC EDGAR — public, free)

10-K text files are downloaded from EDGAR by [`code/step3_full_download.py`](code/step3_full_download.py) into:

```
D:\Data\10_K_10_Q\
├── raw\10K\<YYYY>\<cik>_<accession>.txt.gz
├── manifest\filings_10k_1994_2008.parquet
└── index\master_<YYYY>_Q<q>.gz
```

The default root is `D:\Data\10_K_10_Q\`; edit `DATA_ROOT` at the top of the relevant scripts for your environment.

Size: ~20 GB compressed for 1994–2008 (~157,000 filings).

**SEC fair-access rules** (non-negotiable): max 8 requests/sec global, exponential-backoff retry on 429/503, contact User-Agent on every request. See [`code/edgar_client.py`](code/edgar_client.py).

---

## How to obtain each source

| Source | How |
|---|---|
| **WRDS** (CRSP, Compustat, 13F) | Institutional WRDS access required (university or commercial license). One-time setup: `python -c "import wrds; wrds.Connection(wrds_username='YOUR_USER').create_pgpass_file()"` |
| **SRAF data** | Free download from <https://sraf.nd.edu/sec-edgar-data/> |
| **Fama-French factors** | Free; pulled into the CRSP daily extract by `code/preclean.py` |
| **Ken French SIC-48 mapping** | Free; download directly from his library |
| **SEC EDGAR (10-K filings)** | Free; rate-limited to 8 req/s by SEC policy. Pipeline handles this via [`code/edgar_client.py`](code/edgar_client.py) |

---

## Credentials & environment variables

The repo deliberately contains **no credentials**. Set the following before running:

```bash
# Required by every SEC EDGAR HTTP request
export SEC_EDGAR_USER_AGENT="Your Name your.email@example.com"

# Required only by code/preclean.py (the WRDS pull)
export WRDS_USERNAME="your_wrds_login"

# (One-time) cache your WRDS password so preclean.py doesn't prompt:
#   python -c "import wrds; wrds.Connection(wrds_username='YOUR_USER').create_pgpass_file()"
```

On Windows PowerShell, use `$env:NAME = "value"` syntax.

---

## Reference papers

These journal PDFs are **not** bundled (copyright). The full citations:

- **Loughran, T., & McDonald, B. (2011).** *When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks.* **Journal of Finance** 66(1), 35–65.
  DOI: [10.1111/j.1540-6261.2010.01625.x](https://doi.org/10.1111/j.1540-6261.2010.01625.x)
- **Loughran, T., & McDonald, B. (2011).** *Online Appendix — When Is a Liability Not a Liability?* Available on the *Journal of Finance* supplementary materials page (DOI above).
- **Jegadeesh, N., & Wu, D. (2013).** *Word Power: A New Approach for Content Analysis.* **Journal of Financial Economics** 110(3), 712–729. DOI: [10.1016/j.jfineco.2013.08.018](https://doi.org/10.1016/j.jfineco.2013.08.018)

---

## After all data is in place

The pipeline (`code/step1_…` → `code/step7_tables.py`) reproduces all results documented in [`docs/baseline_vs_LM.md`](docs/baseline_vs_LM.md). See [`README.md`](README.md) for the step-by-step run order.
