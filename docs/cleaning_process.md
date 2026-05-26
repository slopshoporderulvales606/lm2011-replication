# Cleaning Process — LM (2011) Replication Pipeline

This document summarizes every cleaning / filtering / transformation step from
raw EDGAR 10-K filings through to the final analysis panel used in Tables I, II,
IV, and V. Each step cites the LM (2011) source (main paper or Internet
Appendix) where relevant.

---

## Stage 1 — Manifest Construction

**Source**: EDGAR quarterly master index files (`master.gz`) for 1994Q1–2008Q4
(60 files), downloaded from `https://www.sec.gov/Archives/edgar/full-index/`.

**Steps**:
1. Filter the index rows to form types `{10-K, 10-K405, 10-KSB, 10-K/A, …, 10-KT}`.
2. **Per LM (2011) main paper Section II.A**: restrict to **10-K and 10-K405 only**
   (drop 10-KSB family and all amendments).
3. Deduplicate by (cik, accession) — each unique accession is downloaded once;
   co-filer mirrors point at byte-identical files on EDGAR.
4. Result: 157,293 unique 10-K-family accessions in our broad manifest;
   **117,021** unique 10-K + 10-K405 accessions for the LM-style sample.

---

## Stage 2 — File Download

**Steps**:
1. Each filing URL is `https://www.sec.gov/Archives/<filename>` from the master
   index.
2. SEC EDGAR `User-Agent` header set via the `SEC_EDGAR_USER_AGENT` env var (the SEC fair-access policy requires every request to carry a contact address; see `README.md`).
3. Global rate limit: 8 requests/sec (SEC fair-access cap), token-bucket with
   tenacity exponential-backoff retry on 429 / 503 (max 5 attempts).
4. Saved gzipped to `D:\Data\10_K_10_Q\raw\10K\{YYYY}\{cik}_{accession}.txt.gz`.
5. Result: **157,292 / 157,293** files downloaded (1 EDGAR 404 — accession
   `0000884219-96-000033`).

---

## Stage 3 — Document Parsing (per LM 2011 Internet Appendix Section I)

For each `.txt.gz`:

1. **Decompress** with gzip, decode as `latin-1` (LM default).
2. **Slice to the primary 10-K document only.** Match the first
   `<DOCUMENT><TYPE>10-K|10-K405<TEXT>...</TEXT></DOCUMENT>` block; **drop all
   subsequent `<DOCUMENT>` blocks** (these are the `<TYPE>EX-*` exhibits that
   LM explicitly removes).
3. **Remove encoded binary blobs**: `<PDF>`, `<GRAPHIC>`, `<ZIP>`, `<EXCEL>`,
   `<JSON>`, `<XML>`, `<XBRL>` and any uuencoded streams.
4. **Decode HTML entities** (`&nbsp;`, `&amp;`, `&#8217;`, etc.).
5. **Remove numeric-heavy tables** (per LM appendix): for each `<TABLE>...</TABLE>`,
   compute fraction-of-nonblank-chars-that-are-digits. If > 25%, replace the
   whole table with a space. This catches financial-statement tables but
   preserves tables of contents.
6. **Replace `hyphen + line-feed` with `hyphen`** so multi-line hyphenated
   words tokenize as one word (per LM appendix).
7. **Strip remaining HTML/SGML/inline-XBRL tags** via `<[^>]+>` regex.
8. **Normalize Unicode**: curly quotes → ASCII, en-/em-dashes → `-`, NBSP →
   space, NFKC normalization.
9. **Uppercase** everything; collapse runs of whitespace.

The result is the cleaned, uppercased 10-K body that feeds both the full-text
word counts and the MD&A extractor.

---

## Stage 4 — Tokenization (per LM 2011 Internet Appendix)

Regex: `\b[A-Z][A-Z\-]+\b` — matches all alphabetic tokens of length ≥ 2 with
hyphens allowed mid-word. **No apostrophes** in the character class (LM
specifies "two or more alphabetic characters [with] hyphens also allowed";
apostrophes are not mentioned, so `MANAGEMENT'S → MANAGEMENT` + dropped `S`).

---

## Stage 5 — N_Words Calculation

**Per LM appendix**: "we have a collection of alphabetic characters (tokens),
which we then look up in our master dictionary."

- `N_Words` = number of tokens that appear in the LM master dictionary (86,553
  base words). Tokens not in the dictionary (proper nouns, acronyms, tickers,
  misspellings, made-up words) are **excluded** from `N_Words`.
- `N_Negative` = number of tokens whose dictionary entry has `Negative ≠ 0`
  (2,355 words; per user spec — flagged regardless of add/remove year).
- `N_Positive` = number of tokens whose `Positive ≠ 0` (354 words).

`Fin-Neg = 100 × N_Negative / N_Words` (in percent).
`Fin-Pos = 100 × N_Positive / N_Words` (in percent).

---

## Stage 6 — MD&A Extraction (LM-style, three-tier)

Operates on the §3-cleaned text. Section boundaries differ by form type:

| Tier | Start pattern | End pattern | Used for |
|---|---|---|---|
| t1 (10-K family) | `ITEM 7 + MANAGEMENT('S) DISCUSSION` (last occurrence; bypasses TOC) | `ITEM 7A` or `ITEM 8 + FINANCIAL STATEMENTS` | 10-K, 10-K405 |
| t1 (10-KSB) | `ITEM 6 + MANAGEMENT'S DISCUSSION` | `ITEM 7 + FINANCIAL STATEMENTS` | 10-KSB family (not in LM main sample) |
| t2 (Roman) | `(VI\|VII)\.  + MANAGEMENT('S) DISCUSSION` | next Roman-numeral section | small filers using Roman numerals |
| t3 (bare) | `MANAGEMENT'S DISCUSSION AND ANALYSIS` line-anchored | `QUANTITATIVE AND QUALITATIVE` / `REPORT OF INDEPENDENT` / `CONSOLIDATED BALANCE SHEETS` | fallback |

**Min length**: 250 words (per LM appendix).

For each filing, the extractor walks the tiers in order; for each tier it tries
each start match (preferring the LAST occurrence, since TOC entries appear
first), pairs with each candidate end pattern, and accepts the first
combination yielding a section between 250 and 100,000 words.

`mdna_status` is recorded as `ok_t1_10k_item7 / ok_t1_ksb_item6 / ok_t2_roman /
ok_t3_bare / no_match`.

---

## Stage 7 — Sample Construction (Table I funnel, LM order)

All filters applied in the same order LM (2011) Table I lists them. **Final
configuration after tuning** (see `replication_results.md` for the comparison
of variants):

| # | Filter | Setting | LM Source |
|---|---|---|---|
| 1 | EDGAR 10-K + 10-K405 1994–2008, unique accessions | — | Table I row 1 |
| 2 | First filing per (cik, calendar year) | — | Table I row 2 |
| 3 | ≥ 180 days between same-cik 10-K filings | — | Table I row 3 |
| 4 | CRSP PERMNO match (`compustat_gvkey_permno.dta` only — WRDS SEC Suite) | `LM_LINK_MODE=compustat_only` | Table I row 4 |
| 5 | CRSP `shrcd ∈ {10, 11, 12}` at filing month | `LM_SHRCD=10,11,12` | Table I row 5 |
| 6 | CRSP market-cap data available (non-null prc) | — | Table I row 6 |
| 7 | `\|prc\| ≥ $3` at filing month (LM: day −1) | — | Table I row 7 |
| 8 | Valid returns + volume for all 4 days of [0, +3] | — | Table I row 8 |
| 9 | `exchcd ∈ {1, 2, 3}` (NYSE/AMEX/NASDAQ) | — | Table I row 9 |
| 10 | ≥ 60 days valid returns + volume in [−252, −6] AND [+6, +252] | — | Table I row 10 |
| 11 | Compustat BM available for `fyear = filing_year − 1` AND book equity > 0 | — | Table I row 11 |
| 12 | N_Words ≥ 2,000 (after §3 cleaning) | — | Table I row 12 |

**Tested variants** (counts from exploratory legacy Stata-preclean runs, kept for
the methodology trail; current Python-preclean baseline is the **first** row):

| variant | firm-years | firms | gap vs LM (50,115) |
|---|---|---|---|
| **shrcd {10,11} + compustat_only** ← **current Python baseline** | **51,015** | **8,950** | **+1.8%** |
| shrcd {10,11} + compustat+comphist  | 51,888 (legacy) | 9,097 | +3.5% |
| shrcd {10,11,12} + compustat_only | 51,492 (legacy) | 8,930 | +2.7% |
| shrcd {10,11,12} + compustat+comphist | 51,711 (legacy) | 9,097 | +3.2% |
| shrcd {10,11,12,18} + compustat_only | 53,001 (legacy) | 9,170 | +5.8% |
| shrcd {10,11,12,18} + compustat+comphist | 53,226 (legacy) | 9,340 | +6.2% |

The current baseline drops `shrcd = 12` (foreign-incorporated, US-listed) for
the tightest "ordinary common equity" definition.

---

## Stage 8 — CIK ↔ GVKEY ↔ PERMNO Linking

**Per LM (2011) footnote 5**: "We use the Wharton Data Services CIK file to link
SEC CIK numbers to the CRSP PERMNOs." WRDS does not ship a direct CIK ↔ PERMNO
file; the equivalent is the WRDS SEC Suite, which is embedded in Compustat as
the `cik` column on each `(gvkey, fyear)` row paired with `permno` (the CCM
link). That table is `compustat_gvkey_permno.dta` in our preclean output.

**Chosen link mode** (`compustat_only`): for each filing, look up the
Compustat row whose `cik` matches and whose `fyear` is closest to
`filing_year − 1`. Read `(gvkey, permno)`.

- Final match counts: **73,935** filings linked (all from Compustat);
  unlinked filings (real estate / ABS trusts / mutual funds / private filers)
  are dropped at this step per LM convention.

The alternative `compustat_with_comphist` mode (Compustat primary, then
`comphist_cik_gvkey.dta` as point-in-time fallback) yields ~74,200 matches
but adds ~300 firms with weak time validation. We chose `compustat_only` for
the cleaner LM-aligned spec.

---

## Stage 9 — FF48 Industry Assignment (point-in-time)

`Siccodes48.txt` parsed into ~350 SIC ranges across 48 FF industries plus
"Other" (49).

SIC source is controlled by env var `FF48_SIC_SOURCE` with three options:
1. `crsp` (default): CRSP `siccd` from `crsp_monthly` at `(permno, yrmon=filing month)`, then fallback to `sich` then `sic`.
2. `sich`: Compustat historical SIC at `(gvkey, fyear=filing_year−1)`, fallback to `sic`.
3. `sic`: Compustat most-recent header SIC (no fallback).

We tested all three; see `replication_results.md` for the comparison table.

---

## Stage 10 — Market-Data Variables (per LM Appendix Variable Definitions)

Computed per filing from CRSP daily; units carefully checked.

| Variable | LM definition | Implementation note |
|---|---|---|
| Excess return [0,3] | Firm BH return − VW market BH return over 4 trading days starting on first trading day on/after filing, **× 100 (percent)** | `(∏(1+ret) − ∏(1+vwretd)) × 100` |
| Size ($B) | `\|prc\| × shrout` on day −1 | CRSP daily `shrout` is in **MILLIONS** → `\|prc\|×shrout/1000` gives $B |
| Book-to-market | Compustat `bm` for `(gvkey, fyear_prev)` | Already filtered to be > 0 |
| Share turnover | **Σ vol over [−252, −6] / shrout on file date** | shrout in millions → divide by `shrout × 1,000,000` to get unitless ratio. NASDAQ pre-2002 volume halved (LM convention). |
| 1-yr pre-event FF α | Intercept of `(ret − rf) ~ mktrf + smb + hml` over [−252, −6] (daily), **annualized × 252** | Fits via `np.linalg.lstsq` per permno-filing |
| Institutional ownership | `instOwn` from 13F at the quarter immediately before filing | `(permno, yqtr_pre)` join |
| NASDAQ dummy | 1 if `exchcd == 3` at filing month, else 0 | CRSP monthly |

---

## Stage 11 — tf-idf Score for Fin-Neg (LM 2011 Eq. 3)

For document i and LM-negative word j with raw count `tf_ij` ≥ 1:

```
            (1 + log(tf_ij))         N
w_ij  =  ─────────────────────  · log ───
           (1 + log(a_i))             df_j
```

- `a_i = N_Words_i` (per-document length normalization).
- `N` = number of documents in the **full 157k corpus**; `df_j` = count of
  documents in the full corpus containing word j (full-corpus idf is more
  stable than sample-only idf).
- Per-document score: `Fin-Neg_tfidf_i = Σ_j w_ij`.

The same formula is applied to the MD&A sparse count matrix for Table V's tf-idf.

---

## Stage 12 — Fama-MacBeth Regressions (per LM Tables IV, V)

Quarterly cross-sectional OLS:

```
ExcRet[0,3]_i = α_q + β_q · Sentiment_i
              + γ_q,1 · log(Size_i) + γ_q,2 · log(BM_i)
              + γ_q,3 · log(Share Turnover_i)
              + γ_q,4 · Pre-FF α_i
              + γ_q,5 · NASDAQ_i + γ_q,6 · IO_i
              + FF48 industry dummies
              + ε_i
```

Pooled estimate: **`β̄ = Σ(n_q · β_q) / Σ n_q`** — time-series average **weighted
by number of filings per quarter** (LM page 52: "the estimates for each period
are weighted by frequency, since the calendar distribution of file dates is
clustered around specific dates (see Griffin (2003))").

Standard error via **Newey-West HAC, 1 lag** on the time series of β_q values.
t-stat = `β̄ / se_NW`. P-value from the normal approximation.

**Both specifications reported** in the diagnostic — `with FF48` (LM's literal
spec per appendix) and `without FF48` (robustness).

**Continuous variables winsorized at 1/99%** over the full sample (once)
before fitting.

---

## Outputs

- `output/sample.parquet` — final analysis sample (one row per filing)
- `output/panel.parquet` — same with all sentiment + control variables
- `output/table1_sample_funnel.csv` — filter-by-filter sample counts
- `output/table2.csv` — Table II descriptive statistics
- `output/table4_cols2_4.csv` — Table IV regressions (cols 2 & 4)
- `output/table5_cols2_4.csv` — Table V regressions (cols 2 & 4)
- `output/replication_diagnostic.md` — full diagnostic with both regression specs
- `output/mda_samples/` — 30 manually-verifiable MD&A extraction samples
