# Loughran & McDonald (2011) Replication — SEC 10-K Sentiment & Stock Returns

A from-scratch, end-to-end replication of:

> **Loughran, T., & McDonald, B. (2011).** *When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks.* **Journal of Finance** 66(1), 35–65.

Tables I, II, IV, and V are reproduced — including the Fama-Macbeth regressions for their main results.

---

## Why this paper matters

Before LM (2011), textual analysis in finance imported general-purpose sentiment dictionaries (e.g. Harvard's *General Inquirer*) and counted words. The problem: those dictionaries flag words like *liability*, *vice*, *cost*, *expense*, *tax* as **negative**. In 10-K filings these are mostly accounting terms with no negative connotation, so the resulting "negativity" score is noise.

LM (2011) built a **domain-specific Sentiment Dictionary** by hand-tagging 80,000+ words from 10-Ks and showed that this finance-tuned dictionary's negative-tone score:

- Is negatively associated with filing-period (four-day window) excess returns.
- The result is statistically signficant at 1% level, outperforming a Harvard-dictionary-based "noise" measure that even has the *wrong* sign.

The paper became foundational for empirical finance NLP — the dictionary is downloaded thousands of times a year and is the de-facto standard for English-language financial-text sentiment.

**What replicating it teaches**: how to assemble an SEC EDGAR corpus at scale, write a fault-tolerant downloader respecting fair-access rate limits, parse messy pre-XBRL HTML/SGML, tokenize the text, run a Fama-MacBeth pipeline with HAC standard errors, and reason carefully about why your numbers differ from the published ones (because they will).

---

## Replication snapshot

| Cell | This repo | LM (2011) |
|---|---:|---:|
| **Table I final sample** | **51,015** firm-years / **8,950** firms | 50,115 / 8,341 |
| **Table II Fin-Neg mean** | **1.36 %** | 1.39 % |
| **Table IV col(2) Fin-Neg t** | **−2.96** | −2.64 |
| **Table IV col(4) Fin-Neg tf-idf t** | **−2.62** | −3.11 |
| **Table V col(2) Fin-Neg MD&A t** | **−3.49** | −0.68 (ours stronger) |
| **Table V col(4) Fin-Neg tf-idf MD&A t** | **−3.38** | −1.96 (ours stronger) |
| **R²** | 2.36 – 2.61 % | 2.45 – 2.76 % |

All sentiment coefficients carry the correct (negative) sign and remain significant at the 1 % level. R² values are within 0.2 percentage points of LM across all four regressions.

Full side-by-side: [`docs/baseline_vs_LM.md`](docs/baseline_vs_LM.md).
Robustness across 4 panel variants × 12 configs: [`docs/variant_grid_summary.md`](docs/variant_grid_summary.md).

---

## What the pipeline does

```
SEC EDGAR (1994-2008 quarterly master indexes)
       │
       ▼
[step1] Build manifest of 10-K family filings  →  ~117 k unique accessions
       │
       ▼
[step3] Resumable HTTP downloader (8 req/s)    →  ~20 GB compressed .txt.gz
       │
       ▼
[step4] HTML/SGML/XBRL strip → LM tokenization →  per-filing word counts
       │                                          + sparse (filings × neg-words) tf matrix
       ▼
[step5] Table I sample funnel  ────────┐
       (CIK→GVKEY→PERMNO, shrcd, prc, │
        BM, N_words ≥ 2000, …)        │
       ▼                                ▼
[preclean.py]  WRDS pulls:        [step6] Build a panel dataset
   - CRSP daily + FF factors            (event-window excret, size, turnover,
   - CRSP monthly                        FF3-α, IO from 13F, FF48 industry,
   - Compustat-CCM (book equity)         sentiment scores)
   - Thomson Reuters 13F
       │                                ▼
       └──────────► input/*.dta ───►  [step7] Fama-MacBeth quarterly
                                          (60 quarterly cross-sections,
                                           n-weighted time-series avg,
                                           Newey-West HAC SE, FF48 FEs)
                                          → Tables II, IV, V
```

---

## Repository layout

```
.
├── code/                        # All pipeline + analysis scripts
│   ├── edgar_client.py          # SEC EDGAR HTTP client (rate-limited, retrying)
│   ├── mdna_extract.py          # 10-K text cleaning + MD&A section extraction
│   ├── preclean.py              # Build WRDS inputs (CRSP/Compustat/13F) via Python
│   ├── step1_manifest.py        # Manifest of 10-K filings, 1994–2008
│   ├── step2_pilot_2007.py      # Pilot download (2007)
│   ├── step2b_validate_2007.py  # Validate pilot vs SRAF reference counts
│   ├── step3_full_download.py   # Full LM-window download (1994–2008 10-Ks)
│   ├── step4_word_counts.py     # Tokenize + count Fin-Neg / Fin-Pos per filing
│   ├── step4a_mdna_sample.py    # Spot-check MD&A extraction quality
│   ├── step5_build_sample.py    # Apply Table I funnel
│   ├── step6_build_panel.py     # Build analysis panel with market controls
│   ├── step7_tables.py          # Produce Tables II, IV, V
│   ├── step8_variant_grid.py    # Robustness: 4 panels × 12 configs grid
│   ├── build_baseline_vs_lm.py  # Build docs/baseline_vs_LM.md from outputs
│   ├── build_variant_summary.py # Build docs/variant_grid_summary.md
│   ├── build_panel_lm_counts.py # Diagnostic: panel using SRAF's published counts
│   └── run_variant_grid.sh      # Bash driver for the variant grid
│
├── docs/                        # Methodology + results documentation
│   ├── baseline_vs_LM.md        # ⭐ MAIN RESULT — side-by-side vs LM
│   ├── cleaning_process.md      # Step-by-step methodology
│   ├── python_preclean_baseline.md  # Stata→Python preclean migration notes
│   └── variant_grid_summary.md  # Robustness across panel/config variants
│
├── input/                       # Input data (NOT committed — see DATA.md)
│   └── README.md                # Describes required files + sources
│
├── output/                      # Generated artifacts
│   ├── table1_sample_funnel.csv # Final canonical Table I
│   ├── table2.csv               # Final Table II descriptive stats
│   ├── table4_cols2_4.csv       # Final Table IV cols (2) and (4)
│   ├── table5_cols2_4.csv       # Final Table V cols (2) and (4)
│   ├── replication_diagnostic.md
│   └── variant_grid_results.csv
│
├── README.md                    # this file
├── DATA.md                      # required input data, sources, layout
├── requirements.txt
└── .gitignore
```

Intermediate parquet panels, sparse matrices, the SQLite download log, the raw 10-K corpus, all WRDS extracts, and the SRAF reference CSVs are **not** committed (they're regenerable from code + license-required source data). See `.gitignore` and [`DATA.md`](DATA.md).

---

## Installation

1. **Python 3.10+** is required (developed under Anaconda env `py310`).

2. Clone and install dependencies:

   ```bash
   git clone https://github.com/<your-handle>/lm2011-replication.git
   cd lm2011-replication
   pip install -r requirements.txt
   ```

3. **Set required environment variables** (the code intentionally has no credentials baked in):

   ```bash
   # SEC EDGAR fair-access policy requires every request to carry a contact:
   export SEC_EDGAR_USER_AGENT="Your Name your.email@example.com"

   # WRDS account login (only needed if running code/preclean.py)
   export WRDS_USERNAME="your_wrds_login"
   ```

   On Windows PowerShell:
   ```powershell
   $env:SEC_EDGAR_USER_AGENT = "Your Name your.email@example.com"
   $env:WRDS_USERNAME = "your_wrds_login"
   ```

4. **Acquire the required input data** — see [`DATA.md`](DATA.md). The pipeline expects WRDS extracts (CRSP, Compustat, 13F), Loughran-McDonald reference data from SRAF, Ken French's SIC-48 mapping, and ~20–30 GB of raw 10-K text from SEC EDGAR.

---

## Running the pipeline

```bash
PY=python   # or full path to your interpreter

# 0. Build all input/*.dta files from WRDS (replaces legacy preclean.do)
$PY code/preclean.py                          # ~60 min over residential broadband

# 1. Build manifest of 10-K filings (1994–2008)
$PY code/step1_manifest.py

# 2. (optional) Pilot download for 2007 only — useful to validate before the full run
$PY code/step2_pilot_2007.py
$PY code/step2b_validate_2007.py              # cross-check vs SRAF reference counts

# 3. Full download (~20 GB compressed; ~10 hr at 8 req/s)
$PY code/step3_full_download.py

# 4. Tokenize + count Fin-Neg / Fin-Pos per filing (~15 min)
$PY code/step4_word_counts.py

# 5. Apply Table I sample funnel (~5 min)
$PY code/step5_build_sample.py

# 6. Build analysis panel with market controls (~5 min)
$PY code/step6_build_panel.py

# 7. Produce Tables II, IV, V
$PY code/step7_tables.py

# 8. (optional) Robustness: 4 panel variants × 12 configs (~30 min)
$PY code/step8_variant_grid.py
```

After step 7, the canonical outputs live in `output/`:

- `table1_sample_funnel.csv`
- `table2.csv`
- `table4_cols2_4.csv`
- `table5_cols2_4.csv`
- `replication_diagnostic.md`

---

## Key methodology choices

Per the LM (2011) paper text and Internet Appendix:

| Choice | Source |
|---|---|
| Sample: 10-K and 10-K405 only (no 10-KSB, no amendments) | Paper p. 39 |
| CIK ↔ PERMNO link via WRDS SEC Suite (`compustat_gvkey_permno.dta`) | Paper footnote 5 |
| `shrcd ∈ {10, 11}` (ordinary common equity, US-domiciled) | Convention; matches LM Table I |
| `\|prc\| ≥ $3` on trading day before filing | Paper p. 40 |
| `≥ 60 days` returns + volume both pre and post filing | Paper p. 40 |
| Exclude exhibits (`<TYPE>EX-*`) from text | Appendix |
| Remove `<TABLE>` blocks where > 25 % of nonblank chars are digits | Appendix |
| Tokenizer: alphabetic, length ≥ 2, hyphens allowed | Appendix |
| `N_Words` = count of master-dictionary tokens only | Appendix |
| Excess return = compounded BH × 100 (percent) | Appendix variable defs |
| Share turnover = `Σ vol [-252,-6] / shrout_filedate` | Appendix variable defs |
| Fama-MacBeth quarterly, time-series avg weighted by n_obs/q | Paper p. 52 ("weighted by frequency") |
| Newey-West HAC, 1 lag | Paper p. 52 |
| Winsorize 1/99 % over full sample | Paper convention |
| FF48 industry dummies in every quarterly regression | Paper p. 52 |

Full methodology + the rationale for each choice: [`docs/cleaning_process.md`](docs/cleaning_process.md).

---

## Known discrepancies vs LM (2011)

These are catalogued in detail in [`docs/baseline_vs_LM.md`](docs/baseline_vs_LM.md). Briefly:

1. **NASDAQ dummy sign flip**: ours −0.28, LM +0.07. Driven entirely by 2000–02 dot-com bust period; in the pre-bust and post-bust subsamples we recover LM's pattern. Documented as a sample-period finding, not a methodology bug.
2. **`log(size)` / `log(BM)` t-stats**: ours ≈ 1.0–1.6, LM ≈ 3.0. Different size-distribution tail (median matches LM exactly; mean is smaller).
3. **Coefficient magnitudes ≈ 50 % larger** on Fin-Neg. Source: our per-filing `N_Negative` correlates 0.77 with SRAF's continuously-maintained reference counts. The 23 % unexplained cross-sectional variance — our pipeline parses 10-K text differently from LM's (unpublished) production code, even though we follow the appendix's stated rules.

We deliberately do **not** substitute SRAF's published per-filing counts into our regressions — that would mean we are running LM's numbers through our regression rather than replicating LM's pipeline. The diagnostic comparison vs SRAF is reported separately in `docs/baseline_vs_LM.md`.

---

## Skills demonstrated

- **NLP / textual analysis**: dictionary-based sentiment scoring, tf-idf weighting, MD&A section extraction from semi-structured legal text, robust regex pipelines across SGML / HTML / XBRL filing formats.
- **Large-scale data engineering**: SEC EDGAR corpus assembly, rate-limited fault-tolerant downloader (8 req/s, exponential-backoff retry, resumable via SQLite log), gzip-streamed local storage of ~1 M filings.
- **Empirical asset pricing**: Fama-MacBeth quarterly regressions with frequency weighting and Newey-West HAC standard errors; event-study cumulative-return construction; book-to-market and FF48 industry classification; institutional-ownership panel construction from raw 13F holdings.
- **WRDS / financial databases**: SQL queries via the Python `wrds` package against CRSP daily/monthly, Compustat fundamentals, the CCM link table, Thomson Reuters 13F (`tfn.s34`), and Fama-French factors; CIK ↔ GVKEY ↔ PERMNO link logic respecting LM's footnote 5.
- **Reproducible research**: full numbered pipeline, results parameterized by env vars, side-by-side comparison vs published target, variant grid documenting sensitivity to defensible methodology choices, and clean separation of source data (excluded) from derived artifacts (committed).

---

## Limitations / reproducibility notes

- **Data licensing**: CRSP, Compustat, and Thomson Reuters 13F are commercial datasets requiring WRDS access (university or commercial license). The Loughran-McDonald Master Dictionary is freely available from [SRAF](https://sraf.nd.edu/loughranmcdonald-master-dictionary/). Ken French's industry mapping is freely available from his [data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). See [`DATA.md`](DATA.md).
- **Compute**: The pilot 2007 run finishes in ~30 min on residential broadband. The full 1994–2008 corpus is ~20 GB compressed and takes ~10 hr to download at the SEC's 8 req/s cap. The Fama-MacBeth step is CPU-bound and takes ~5 min.
- **Exact-number replication is hard.** Text-derived measures depend on exhibit-stripping rules, table-detection thresholds, tokenizer edge cases, and SGML/XBRL parsing choices that LM did not fully publish. Our magnitudes are ~50 % off LM's but signs and significance match. The [variant grid](docs/variant_grid_summary.md) documents how stable each result is to defensible alternative choices.
- **Hard-coded paths**: scripts default to `D:\Sentiment_analysis_project\` and `D:\Data\10_K_10_Q\`. Edit the `ROOT` / `DATA_ROOT` constants at the top of each script for your environment, or override via env vars where supported.

---

## References

- **Paper**: Loughran, T., & McDonald, B. (2011). *When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks.* **Journal of Finance** 66(1), 35–65. DOI: [10.1111/j.1540-6261.2010.01625.x](https://doi.org/10.1111/j.1540-6261.2010.01625.x)
- **SRAF data + dictionary**: <https://sraf.nd.edu/sec-edgar-data/>
- **Loughran-McDonald Master Dictionary**: <https://sraf.nd.edu/loughranmcdonald-master-dictionary/>
- **Fama-French data library**: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html>
- **SEC EDGAR full-index**: <https://www.sec.gov/Archives/edgar/full-index/>
- **WRDS** (Wharton Research Data Services): <https://wrds-www.wharton.upenn.edu/>

---

## License

Code: **MIT**. Replicates a published paper for academic and portfolio purposes.
The input data used here is licensed separately by the respective providers (WRDS, SRAF, SEC EDGAR public-domain filings) — see `DATA.md`.
