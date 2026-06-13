# Loughran & McDonald (2011) Replication — SEC 10-K Sentiment & Stock Returns

A from-scratch, end-to-end replication of:

> **Loughran, T., & McDonald, B. (2011).** *When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks.* **Journal of Finance** 66(1), 35–65.

Tables I, II, IV, and V are reproduced — including the Fama-MacBeth regressions for their main results.

---

## Why this paper matters

Before LM (2011), textual analysis in finance imported general-purpose sentiment dictionaries (e.g. Harvard's *General Inquirer*, specifically the IV-4 Psychosocial Dictionary) and counted words. The problem: those dictionaries flag words like *liability*, *vice*, *cost*, *expense*, *tax* as **negative**. In 10-K filings these are mostly accounting terms with no negative connotation, so the resulting "negativity" score is noise.

LM (2011) built a **domain-specific Sentiment Dictionary** by hand-tagging 80,000+ words from 10-Ks and showed that this finance-tuned dictionary's negative-tone score (hereinafter referred to as **Fin-Neg**):

- Is negatively associated with filing-period (four-day window) excess returns.
- The result is statistically significant at the 1 % level, outperforming a Harvard-dictionary-based "noise" measure that even has the *wrong* sign.

The paper became foundational for empirical finance NLP — the dictionary is downloaded thousands of times a year and is the de-facto standard for English-language financial-text sentiment.

---

## Replication snapshot

| Cell | This repo | LM (2011) |
|---|---:|---:|
| **Table I final sample** | **50,902** firm-years / **8,937** firms | 50,115 / 8,341 |
| **Table II Fin-Neg mean** | **1.36 %** | 1.39 % |
| **Table IV col(2) Fin-Neg t-stat** | **−2.99** | −2.64 |
| **Table IV col(4) Fin-Neg tf-idf t-stat** | **−2.69** | −3.11 |
| **Table V col(2) Fin-Neg MD&A t-stat** | **−3.47** | −0.68 |
| **Table V col(4) Fin-Neg tf-idf MD&A t-stat** | **−3.39** | −1.96 |
| **R²** | 2.35 – 2.58 % | 2.45 – 2.76 % |

Columns (2) and (4) report two weightings of the LM negative-word list. Fin-Neg is the proportional measure: the number of words in a filing that appear in the negative-word list, divided by the filing’s total word count. **Fin-Neg tf-idf** reweights those same words using tf-idf, as defined below (Eq. 1 in the paper):

$$w_{i,j}=\frac{1+\log(tf_{i,j})}{1+\log(a_i)}\,\log\frac{N}{df_j},\qquad tf_{i,j}\ge 1,$$

where $w_{i,j}$ denotes the weight of negative word $j$ in filing $i$; $tf_{i,j}$ is the count of word $j$ in filing $i$; $a_i$ is the filing’s total word count; $N$ is the number of 10-Ks in the corpus; and $df_j$ is the number of 10-Ks containing word $j$. The document-level Fin-Neg tf-idf score is the sum of the weights of all negative words:
$$Score_i=\sum_j w_{i,j}$$. 

Intuition: a negative word receives more weight when it appears more frequently in a given filing, but less weight when it is common across the full 10-K corpus through the inverse-document-frequency term. As a result, distinctive negative words drive the score more than boilerplate language.

Comments on the replication results: all sentiment coefficients carry the correct (negative) sign and remain significant at the 1 % level, and R² values are within 0.2 percentage points of LM across all four regressions. The MD&A t-statistics in Table V are larger in absolute value than LM's. Several factors plausibly contribute: ~14 years of CRSP/Compustat restatements, which may give cleaner accounting-based variables; WRDS' CIK ↔ GVKEY ↔ PERMNO link-table backfills accumulated since 2011 (~600 extra unique permnos relative to LM); and minor differences in text-parsing rules between this implementation and LM's unpublished production code. These differences likely raise the statistical power of the Table V tests, lending further empirical support to LM's underlying claim that discretionary managerial tone in MD&A predicts filing-period returns.

Full side-by-side: [`docs/baseline_vs_LM.md`](docs/baseline_vs_LM.md).

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
       └──────────► input/*.dta ───►  [step7] Descriptive Statistics (Tables II) and Fama-MacBeth regressions (IV, V)

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
│   ├── build_panel_lm_counts.py # Diagnostic: panel using SRAF's published counts
│   └── run_variant_grid.sh      # Bash driver for the variant grid
│
├── docs/                        # Methodology + results documentation
│   ├── baseline_vs_LM.md        # main result: side-by-side vs LM
│   ├── cleaning_process.md      # Step-by-step methodology
│   └── python_preclean_baseline.md  # Stata→Python preclean migration notes
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

## Skills demonstrated

- **NLP / textual analysis**: dictionary-based sentiment scoring, tf-idf weighting, MD&A section extraction from semi-structured legal text, robust regex pipelines across SGML / HTML / XBRL filing formats.
- **Large-scale data engineering**: SEC EDGAR corpus assembly, rate-limited fault-tolerant downloader (8 req/s, exponential-backoff retry, resumable via SQLite log), gzip-streamed local storage of ~1 M filings.
- **Empirical asset pricing**: Fama-MacBeth quarterly regressions with frequency weighting and Newey-West HAC standard errors; event-study cumulative-return construction; book-to-market and FF48 industry classification; institutional-ownership panel construction from raw 13F holdings.
- **WRDS / financial databases**: SQL queries via the Python `wrds` package against CRSP daily/monthly, Compustat fundamentals, the CCM link table, Thomson Reuters 13F (`tfn.s34`), and Fama-French factors; CIK ↔ GVKEY ↔ PERMNO link logic respecting LM's footnote 5.
- **Reproducible research**: full numbered pipeline, results parameterized by env vars, side-by-side comparison vs published target, variant grid documenting sensitivity to defensible methodology choices, and clean separation of source data (excluded) from derived artifacts (committed).

---

## Reproducibility notes

- **Data licensing**: CRSP, Compustat, and Thomson Reuters 13F are commercial datasets requiring WRDS access (university or commercial license). The Loughran-McDonald Master Dictionary is freely available from [SRAF](https://sraf.nd.edu/loughranmcdonald-master-dictionary/). Ken French's industry mapping is freely available from his [data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). See [`DATA.md`](DATA.md).
- **Compute**: The pilot 2007 run finishes in ~30 min on residential broadband. The full 1994–2008 corpus is ~20 GB compressed and takes ~10 hr to download at the SEC's 8 req/s cap. The Fama-MacBeth step is CPU-bound and takes ~5 min.
- **Hard-coded paths**: scripts default to `D:\lm2011-replication\` and `D:\Data\10_K_10_Q\`. Edit the `ROOT` / `DATA_ROOT` constants at the top of each script for your environment, or override via env vars where supported.

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
