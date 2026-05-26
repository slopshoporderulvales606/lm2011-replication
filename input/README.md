# Input data sources

This folder is **not committed** (excluded via `.gitignore` because the files are too large for GitHub and most come from licensed sources). The pipeline expects the following files to be placed here.

---

## 1. CRSP data (from WRDS)

| File | Description | Vars used by pipeline |
|---|---|---|
| `crsp_daily_1993_2019.dta` | CRSP daily stock file, 1993–2019 | `permno, date, prc, ret, vol, shrout, shrcd, exchcd, siccd, hsiccd, vwretd, mktrf, smb, hml, rf` |
| `crsp_monthly_1993_2019.dta` | CRSP monthly, 1993–2019 | `permno, yrmon, prc, shrcd, exchcd, siccd, ...` |

Both files are produced by `code/preclean.do`, which reads from raw WRDS extracts. The daily file has Fama-French daily factors (`mktrf, smb, hml, rf, rmw, cma`) merged in.

**Important**: CRSP daily `shrout` is in **millions** of shares (verified empirically: Apple Jan 2007 = 860.22 → ≈ 860M shares). Pipeline uses this convention.

---

## 2. Compustat data (from WRDS, via SEC Suite link)

| File | Description |
|---|---|
| `compustat_gvkey_permno.dta` | Compustat annual joined with CCM-style PERMNO link and direct CIK column |
| `comphist_cik_gvkey.dta` | Historical CIK ↔ GVKEY link table with effective date ranges (optional fallback) |
| `sec_analytics_cik_gvkey.dta` | Alternative CIK ↔ GVKEY mapping (not used in baseline) |

The baseline uses `compustat_gvkey_permno.dta` as the primary CIK ↔ PERMNO link, per LM (2011) footnote 5. See `code/step5_build_sample.py` for link logic.

---

## 3. 13F institutional ownership

| File | Description |
|---|---|
| `13f_instOwn_stock_level.dta` | Stock-quarter level institutional ownership (built from Thomson Reuters 13F) |

Cleaned in `preclean.do`; raw source is Thomson Reuters 13F (WRDS).

---

## 4. SRAF reference data

From <https://sraf.nd.edu/sec-edgar-data/>:

| File | Description | Use |
|---|---|---|
| `Loughran-McDonald_MasterDictionary_1993-2025.csv` | LM Master Dictionary with sentiment classifications | **Required** — drives word-level negative/positive flags |
| `Loughran-McDonald_10X_Summaries_1993-2025.csv` | Per-filing word counts (N_Words, N_Negative, etc.) for ALL 10-K family filings | Validation only — see `docs/baseline_vs_LM.md` |
| `LoughranMcDonald_10-K_HeaderData_1993-2025.csv` | 10-K filer header metadata | Optional |
| `Loughran-McDonald_EDGAR_MasterIndexAnalysis_1993-2024.xlsx` | Filing tabulations | Reference only |
| `Documentation_LoughranMcDonald_MasterDictionary.pdf` | Dictionary documentation | Reference |
| `MasterIndex_20260318/` | SRAF-mirrored EDGAR master index files (`.idx`) | Reference; we re-download from EDGAR directly in step 1 |

---

## 5. FF48 industry classification

| File | Description |
|---|---|
| `Siccodes48.txt` | Ken French's Fama-French 48 industry SIC mapping | Required for FF48 industry dummies |

Available from Ken French's data library: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html>.

---

## 6. Raw 10-K filings (NOT in this folder)

10-K text files are downloaded from SEC EDGAR by `code/step3_full_download.py` and stored separately at:

```
D:\Data\10_K_10_Q\
├── raw\10K\<YYYY>\<cik>_<accession>.txt.gz
├── manifest\filings_10k_1994_2008.parquet
└── index\master_<YYYY>_Q<q>.gz
```

Total size: ~110 GB across 157,292 filings. Configure the data root in the script if your path differs.

---

## How to obtain

| Source | How |
|---|---|
| WRDS (CRSP, Compustat, 13F) | Institutional access required (university or commercial license) |
| SRAF data | Free download from <https://sraf.nd.edu/sec-edgar-data/> |
| Fama-French factors | Free download from Ken French's library |
| Ken French SIC codes | Free download |
| SEC EDGAR (10-K filings) | Free; rate-limited to 8 req/sec; pipeline handles via `edgar_client.py` |

After placing all files here, the pipeline (`step1` → `step7`) reproduces all results.
