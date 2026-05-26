"""
Step 4: Tokenize + count Fin-Neg / Fin-Pos / N_Words for every 10-K filing.

Two text scopes per filing:
  - Full cleaned 10-K text
  - MD&A section (Item 7 / Item 6 / Roman-numeral variant)

Persists:
  - output/filing_word_counts.parquet : one row per filing with counts + MD&A status
  - output/filing_negword_tf.npz       : sparse CSR (n_filings × |LM-neg|) raw counts (full text)
  - output/filing_mdna_negword_tf.npz  : same shape, MD&A counts
  - output/filing_index.parquet        : ordered (accession) ↔ row index lookup for sparse matrices

Cross-validates totals against LM_10X_Summaries.

Parallelized across 14 workers (leave 2 cores for OS / I/O).
"""

from __future__ import annotations

import gzip
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
import mdna_extract as mx  # noqa: E402

ROOT = Path(r"D:\Sentiment_analysis_project")
DATA_ROOT = Path(r"D:\Data\10_K_10_Q")
INP = ROOT / "input"
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)

MAN = DATA_ROOT / "manifest" / "filings_10k_1994_2008.parquet"
LM_DICT = INP / "Loughran-McDonald_MasterDictionary_1993-2025.csv"
LM_SUM = INP / "Loughran-McDonald_10X_Summaries_1993-2025.csv"

N_WORKERS = 14

# Per-worker globals (populated by init).
_NEG_SET: frozenset[str] = frozenset()
_POS_SET: frozenset[str] = frozenset()
_MASTER_SET: frozenset[str] = frozenset()
_NEG_W2I: dict[str, int] = {}


def init_worker(neg_set, pos_set, master_set, neg_w2i) -> None:
    global _NEG_SET, _POS_SET, _MASTER_SET, _NEG_W2I
    _NEG_SET = neg_set
    _POS_SET = pos_set
    _MASTER_SET = master_set
    _NEG_W2I = neg_w2i


def count_text(text: str) -> tuple[int, int, int, dict[int, int]]:
    """
    Tokenize and return (n_words, n_neg, n_pos, neg_word_counts_by_idx).

    Per LM (2011) Appendix: n_words is the count of tokens that appear in the
    master dictionary (NOT all alphabetic tokens). Tokens that aren't dictionary
    words (proper nouns, acronyms, tickers, misspellings) are excluded.
    """
    tokens = mx.tokenize(text)
    if not tokens:
        return 0, 0, 0, {}
    c = Counter(tokens)
    # N_Words counts only tokens IN master dictionary.
    n_words = sum(v for w, v in c.items() if w in _MASTER_SET)
    n_neg = sum(v for w, v in c.items() if w in _NEG_SET)
    n_pos = sum(v for w, v in c.items() if w in _POS_SET)
    neg_idx_counts = {_NEG_W2I[w]: v for w, v in c.items() if w in _NEG_W2I}
    return n_words, n_neg, n_pos, neg_idx_counts


def process_one(arg: tuple) -> dict:
    """Worker: process a single (accession, form_type, year, cik) row."""
    accession, form_type, year, cik = arg
    path = (DATA_ROOT / "raw" / "10K" / str(year) / f"{int(cik)}_{accession}.txt.gz")
    if not path.exists():
        return {"accession": accession, "ok": False, "error": "file_missing"}
    try:
        with gzip.open(path, "rb") as fh:
            raw = fh.read().decode("latin-1", errors="replace")
        cleaned = mx.clean_text(raw)
        n_w, n_n, n_p, neg_full = count_text(cleaned)

        mdna_text, mdna_status = mx.extract_mdna(cleaned, form_type=form_type)
        if mdna_text:
            m_w, m_n, m_p, neg_mda = count_text(mdna_text)
        else:
            m_w, m_n, m_p, neg_mda = 0, 0, 0, {}

        return {
            "accession": accession, "cik": int(cik), "form_type": form_type,
            "year": int(year),
            "n_words_full": n_w, "n_neg_full": n_n, "n_pos_full": n_p,
            "n_words_mda": m_w, "n_neg_mda": m_n, "n_pos_mda": m_p,
            "mdna_status": mdna_status,
            "neg_full": neg_full, "neg_mda": neg_mda,
            "ok": True, "error": "",
        }
    except Exception as e:  # noqa: BLE001
        return {"accession": accession, "ok": False,
                "error": f"{type(e).__name__}: {e}"[:200]}


def load_dictionary() -> tuple[frozenset[str], frozenset[str], frozenset[str], dict[str, int]]:
    """Returns (neg_set, pos_set, master_set, neg_w2i).

    Controlled by env var LM_DICT_RULE:
      "nonzero" (default) — flag = (col != 0); includes -2020 removed words
      "positive"          — flag = (col > 0);  excludes -2020 removed words
                             (matches LM 2025 SRAF Summaries methodology)
    """
    import os as _os
    rule = _os.environ.get("LM_DICT_RULE", "nonzero")
    d = pd.read_csv(LM_DICT, usecols=["Word", "Negative", "Positive"])
    d["Word"] = d["Word"].astype(str).str.upper()
    if rule == "positive":
        neg_words = d.loc[d["Negative"] > 0, "Word"].tolist()
        pos_words = d.loc[d["Positive"] > 0, "Word"].tolist()
    else:
        neg_words = d.loc[d["Negative"] != 0, "Word"].tolist()
        pos_words = d.loc[d["Positive"] != 0, "Word"].tolist()
    master_words = d["Word"].tolist()
    neg_set = frozenset(neg_words)
    pos_set = frozenset(pos_words)
    master_set = frozenset(master_words)
    neg_w2i = {w: i for i, w in enumerate(sorted(neg_set))}
    print(f"LM dictionary rule={rule}: {len(master_set):,} master words; "
          f"{len(neg_set):,} negative, {len(pos_set):,} positive")
    return neg_set, pos_set, master_set, neg_w2i


def load_manifest() -> pd.DataFrame:
    df = pd.read_parquet(MAN)
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    df = df[df["form_family"] == "10K"].copy()
    df = df.sort_values("date_filed").drop_duplicates("accession").reset_index(drop=True)
    df["year"] = df["date_filed"].dt.year
    return df


def build_sparse(rows: list[dict], key: str, n_cols: int) -> csr_matrix:
    """Build CSR sparse matrix from per-doc dicts at column `key`."""
    rs, cs, vs = [], [], []
    for i, r in enumerate(rows):
        if not r.get("ok"):
            continue
        d = r.get(key) or {}
        for col, v in d.items():
            rs.append(i)
            cs.append(col)
            vs.append(v)
    return csr_matrix(
        (np.array(vs, dtype=np.int32),
         (np.array(rs, dtype=np.int32), np.array(cs, dtype=np.int32))),
        shape=(len(rows), n_cols),
    )


def cross_check_vs_lm(per_doc: pd.DataFrame) -> None:
    """Join with LM Summaries; report distribution of relative diffs."""
    print("\nCross-checking against LM_10X_Summaries ...")
    cols = ["ACC_NUM", "FORM_TYPE", "N_Words", "N_Negative", "N_Positive"]
    chunks = []
    for ch in pd.read_csv(LM_SUM, usecols=cols, chunksize=200_000,
                          dtype={"ACC_NUM": str, "FORM_TYPE": str,
                                 "N_Words": "Int64", "N_Negative": "Int64",
                                 "N_Positive": "Int64"}):
        chunks.append(ch)
    lm = pd.concat(chunks, ignore_index=True)
    lm = lm.rename(columns={"ACC_NUM": "accession"})
    mine = per_doc[["accession", "n_words_full", "n_neg_full", "n_pos_full"]].copy()
    j = mine.merge(lm, on="accession", how="inner")
    print(f"  joinable: {len(j):,}  of mine={len(mine):,}  of LM={len(lm):,}")

    def diff_stats(mine_col, lm_col, label):
        a = j[mine_col].astype(float)
        b = j[lm_col].astype(float)
        # Relative diff against LM (avoid div-by-zero).
        mask = b > 0
        rel = (a[mask] - b[mask]) / b[mask]
        within_2 = (rel.abs() <= 0.02).mean() * 100
        within_5 = (rel.abs() <= 0.05).mean() * 100
        print(f"  {label:<14}  mean_rel_diff={rel.mean():+.4f}  "
              f"median_rel_diff={rel.median():+.4f}  "
              f"within ±2%: {within_2:.2f}%  within ±5%: {within_5:.2f}%")

    diff_stats("n_words_full", "N_Words", "N_Words")
    diff_stats("n_neg_full", "N_Negative", "N_Negative")
    diff_stats("n_pos_full", "N_Positive", "N_Positive")


def main() -> None:
    t0 = time.monotonic()

    neg_set, pos_set, master_set, neg_w2i = load_dictionary()
    n_neg_words = len(neg_w2i)

    manifest = load_manifest()
    print(f"Manifest: {len(manifest):,} unique 10-K accessions to process.")

    tasks = list(zip(
        manifest["accession"].tolist(),
        manifest["form_type"].tolist(),
        manifest["year"].tolist(),
        manifest["cik"].tolist(),
    ))

    print(f"Spawning {N_WORKERS} workers ...")
    with mp.Pool(processes=N_WORKERS,
                 initializer=init_worker,
                 initargs=(neg_set, pos_set, master_set, neg_w2i)) as pool:
        results = list(tqdm(
            pool.imap(process_one, tasks, chunksize=64),
            total=len(tasks), desc="step4", unit="f"))

    # Persist per-doc summary parquet.
    df = pd.DataFrame([
        {k: v for k, v in r.items() if k not in ("neg_full", "neg_mda")}
        for r in results
    ])
    df.to_parquet(OUT / "filing_word_counts.parquet", index=False)
    print(f"Wrote filing_word_counts.parquet  ({len(df):,} rows)")

    # Order index for sparse matrices.
    idx = df[["accession", "cik", "year"]].copy()
    idx["row_idx"] = range(len(idx))
    idx.to_parquet(OUT / "filing_index.parquet", index=False)

    # Sparse matrices.
    print("Building sparse matrices ...")
    M_full = build_sparse(results, "neg_full", n_neg_words)
    M_mda = build_sparse(results, "neg_mda", n_neg_words)
    from scipy.sparse import save_npz
    save_npz(OUT / "filing_negword_tf.npz", M_full)
    save_npz(OUT / "filing_mdna_negword_tf.npz", M_mda)
    print(f"  filing_negword_tf.npz       shape={M_full.shape}  nnz={M_full.nnz:,}")
    print(f"  filing_mdna_negword_tf.npz  shape={M_mda.shape}  nnz={M_mda.nnz:,}")

    # Save the column ordering for the sparse matrices.
    pd.DataFrame({"col_idx": range(n_neg_words),
                  "neg_word": sorted(neg_set)}).to_parquet(
        OUT / "neg_word_columns.parquet", index=False)

    # Cross-check (where rows succeeded).
    ok = df[df["ok"]].copy()
    print(f"\nSuccessful filings: {len(ok):,} / {len(df):,}")
    cross_check_vs_lm(ok)

    # MD&A status breakdown.
    print("\nMD&A extraction status:")
    print(ok["mdna_status"].value_counts().to_string())

    elapsed = time.monotonic() - t0
    print(f"\nDone. Elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
