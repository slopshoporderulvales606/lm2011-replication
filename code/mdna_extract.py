"""
Shared text-cleaning and MD&A extraction module.

Used by:
  - step4a_mdna_sample.py  (writes ~30 samples for manual verification)
  - step4_word_counts.py   (full-corpus tokenization, to be added later)

Design goal: one cleaning function and one MD&A extractor, both correct across
the 1994-2008 EDGAR format evolution (plain text → HTML).
"""

from __future__ import annotations

import gzip
import html
import re
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- #
# 1. Document cleaning                                                        #
# --------------------------------------------------------------------------- #

# Match <TYPE>10-K (or family) … and grab the body of THAT <DOCUMENT>.
DOC_BLOCK_RE = re.compile(
    r"<DOCUMENT>\s*<TYPE>(?P<type>10-?K(?:SB)?(?:40)?(?:405)?(?:T)?(?:/A)?)"
    r"[^<]*?(?:<SEQUENCE>[^<]*)?(?:<FILENAME>[^<]*)?(?:<DESCRIPTION>[^<]*)?"
    r"<TEXT>(?P<body>.*?)</TEXT>\s*</DOCUMENT>",
    re.IGNORECASE | re.DOTALL,
)

# Binary / non-text blocks inside <TEXT>…</TEXT> we should drop wholesale.
BIN_BLOCK_RE = re.compile(
    r"<(PDF|GRAPHIC|ZIP|EXCEL|JSON|XML|XBRL)>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

# Encoded uuencode/base64 streams (older filings embed images this way).
UU_RE = re.compile(r"begin\s+\d{3}\s+\S+\n.*?\nend\s*\n", re.DOTALL)

# Inline-XBRL hidden-fact blocks: <ix:hidden>...</ix:hidden> wraps content tagged
# for machine readers but NOT rendered to humans. The content inside is often
# numeric (durations, CIK numbers, GAAP URIs — harmless), but in early-adopter
# filings (2019-2022) can include duplicated narrative prose that would inflate
# N_Words / N_Negative if it survived into the token stream. Strip these blocks
# entirely before the general tag strip. (Pre-2009 filings have no inline XBRL,
# so this is a no-op on the LM in-sample window.)
IX_HIDDEN_RE = re.compile(r"<ix:hidden\b[^>]*>.*?</ix:hidden>",
                          re.IGNORECASE | re.DOTALL)

# Strip ALL remaining tags (HTML / SGML / inline XBRL like <ix:…>).
TAG_RE = re.compile(r"<[^>]+>")

# Whitespace cleanup.
WS_RE = re.compile(r"[ \t\f\v]+")
NL_RE = re.compile(r"\n{3,}")


def _normalize_unicode(s: str) -> str:
    """Map curly quotes, fancy dashes, NBSP to ASCII equivalents."""
    s = unicodedata.normalize("NFKC", s)
    table = {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "–": "-", "—": "-", "−": "-", "­": "-",
        " ": " ", " ": "\n", " ": "\n",
    }
    return s.translate(str.maketrans(table))


def read_filing(path: Path) -> str:
    """Decompress a .txt.gz filing and return its raw text (latin-1)."""
    with gzip.open(path, "rb") as fh:
        return fh.read().decode("latin-1", errors="replace")


# Match the 10-K / 10-K405 primary submission. Explicit alternation on TYPE
# rules out 10-KSB / 10-KT / 10-K/A. Trailing \s prevents 10-K matching inside
# 10-KSB. (Per LM 2011 appendix: 10-K and 10-K405 only.)
DOC10K_RE = re.compile(
    r"<DOCUMENT>\s*<TYPE>(?P<type>10-K405|10K405|10-K|10K)\s+"
    r"(?P<header>.*?)"           # consumes optional <SEQUENCE>/<FILENAME>/...
    r"<TEXT>(?P<body>.*?)(?:</TEXT>|</DOCUMENT>)",
    re.IGNORECASE | re.DOTALL,
)

# Tables: match an entire <TABLE>...</TABLE> block (with optional attributes).
TABLE_RE = re.compile(r"<TABLE[^>]*>.*?</TABLE>", re.IGNORECASE | re.DOTALL)

# Hyphen followed by line-feed: word continuation; replace with hyphen only.
HYPH_LF_RE = re.compile(r"-\s*\n\s*")


def _table_is_numeric_heavy(table_html: str, threshold: float = 0.25) -> bool:
    """Per LM (2011): remove a <TABLE> if >25% of its nonblank chars are digits."""
    # Strip tags and entities from the table for the count
    inside = TAG_RE.sub(" ", html.unescape(table_html))
    chars = re.sub(r"\s+", "", inside)
    if not chars:
        return False
    digits = sum(1 for c in chars if c.isdigit())
    return digits / len(chars) > threshold


def clean_text(raw: str) -> str:
    """
    LM (2011) Appendix Section I parsing pipeline:
      1. Take the <TYPE>10-K or <TYPE>10-K405 DOCUMENT only (drop EX-* exhibits).
      2. Remove SEC header (implicit — we slice after <TEXT>).
      3. Re-encode HTML entities (&nbsp; → space, &amp; → &, etc.).
      4. Remove encoded graphics / binary blobs.
      5. Remove tables where > 25% of nonblank chars are digits.
      6. Replace 'hyphen + line-feed' with 'hyphen' so multi-line hyphenated
         words tokenize correctly.
      7. Strip remaining HTML tags.
      8. Normalize Unicode → ASCII; uppercase; collapse whitespace.

    Returns the cleaned, uppercased body text. Tokenization (and dictionary
    lookup) happens in step 4, not here.
    """
    # 1. Find the 10-K / 10-K405 primary document. If none, return empty
    #    string (the caller will tally as 0 words and the filing gets filtered).
    m = DOC10K_RE.search(raw)
    if not m:
        return ""
    body = m.group("body")

    # 2. Remove binary subdocuments and uuencode streams (covers encoded graphics).
    body = BIN_BLOCK_RE.sub(" ", body)
    body = UU_RE.sub(" ", body)

    # 3. Strip inline-XBRL hidden-fact blocks BEFORE entity decoding & tag strip.
    #    These wrap content tagged for machines but not rendered to humans.
    body = IX_HIDDEN_RE.sub(" ", body)

    # 4. Decode HTML entities BEFORE table-filtering and tag-stripping.
    body = html.unescape(body)

    # 4. Remove numeric-heavy tables. Iterate so we don't accidentally
    #    delete tables that are mostly text (e.g., the table of contents).
    def _table_repl(mm: re.Match) -> str:
        return " " if _table_is_numeric_heavy(mm.group(0)) else mm.group(0)
    body = TABLE_RE.sub(_table_repl, body)

    # 5. Hyphen + line-feed → hyphen.
    body = HYPH_LF_RE.sub("-", body)

    # 6. Strip remaining tags.
    body = TAG_RE.sub(" ", body)

    # 7. Normalize unicode.
    body = _normalize_unicode(body)

    # 8. Uppercase + whitespace cleanup.
    body = body.upper()
    body = WS_RE.sub(" ", body)
    body = NL_RE.sub("\n\n", body)
    return body.strip()


# --------------------------------------------------------------------------- #
# 2. MD&A extraction (tiered, form-aware)                                     #
# --------------------------------------------------------------------------- #
#
# Three filing-type patterns to handle:
#   - 10-K / 10-K405      ITEM 7 = MD&A, end at ITEM 7A or ITEM 8
#   - 10-KSB family       ITEM 6 = MD&A, end at ITEM 7
#   - Roman-numeral 10-KSB  VI. = MD&A, end at next Roman numeral or "FINANCIAL"
# Plus a content-based fallback when section numbering is absent.

# Apostrophe variants: ASCII ', curly ', or fully omitted ("MANAGEMENTS"). The
# common token is the phrase "MANAGEMENT('S) DISCUSSION (AND ANALYSIS)?".
_MD_PHRASE = r"MANAGEMENT(?:\s*['’]\s*S|S)?\s+DISCUSSION(?:\s+AND\s+ANALYSIS)?"

# Tier 1: form-aware ITEM N start.
_T1_10K  = re.compile(rf"ITEM\s*7[\.\s\-:\)]+(?:.{{0,400}}?){_MD_PHRASE}",
                      re.IGNORECASE | re.DOTALL)
_T1_10KSB = re.compile(rf"ITEM\s*6[\.\s\-:\)]+(?:.{{0,400}}?){_MD_PHRASE}",
                       re.IGNORECASE | re.DOTALL)

# Tier 2: Roman numeral section header (V., VI., VII., VIII.) + MD&A within range.
# Anchored to start-of-line to avoid mid-sentence Roman numerals.
_T2_ROMAN = re.compile(
    rf"(?:^|\n)\s*(?:[IVX]+\.)\s*(?:.{{0,200}}?){_MD_PHRASE}",
    re.IGNORECASE | re.DOTALL,
)

# Tier 3: bare phrase fallback — match the heading at start of a line, no
# section-number prefix required. Riskier (may match cross-references).
_T3_BARE = re.compile(
    rf"(?:^|\n)\s*{_MD_PHRASE}",
    re.IGNORECASE,
)

# End boundary candidates (tried in order; first match after start wins).
_END_PATTERNS = [
    re.compile(r"ITEM\s*7\s*A[\.\s\-:\)]", re.IGNORECASE),                     # 10-K post-1998
    re.compile(r"ITEM\s*8[\.\s\-:\)]+(?:.{0,200}?)FINANCIAL\s+STATEMENTS",     # 10-K
              re.IGNORECASE | re.DOTALL),
    re.compile(r"ITEM\s*7[\.\s\-:\)]+(?:.{0,200}?)FINANCIAL\s+STATEMENTS",     # 10-KSB
              re.IGNORECASE | re.DOTALL),
    re.compile(r"QUANTITATIVE\s+AND\s+QUALITATIVE\s+DISCLOSURES",              # content-based
              re.IGNORECASE),
    re.compile(r"REPORT\s+OF\s+(?:INDEPENDENT|MANAGEMENT)", re.IGNORECASE),    # auditors' report
    re.compile(r"CONSOLIDATED\s+BALANCE\s+SHEETS?", re.IGNORECASE),            # financial stmts proxy
]

MIN_MDNA_WORDS = 250
MAX_MDNA_WORDS = 100_000  # sanity ceiling


def _try_tier(start_pat: re.Pattern, cleaned: str) -> tuple[int, int] | None:
    """Try a start pattern, return (start_idx, end_idx) for the longest valid span, else None."""
    starts = list(start_pat.finditer(cleaned))
    if not starts:
        return None
    # Try start positions from LAST to first (TOC entries appear earliest).
    for sm in reversed(starts):
        s = sm.start()
        for end_pat in _END_PATTERNS:
            em = end_pat.search(cleaned, s + 100)
            if not em:
                continue
            mdna = cleaned[s:em.start()]
            n = len(mdna.split())
            if MIN_MDNA_WORDS <= n <= MAX_MDNA_WORDS:
                return s, em.start()
    return None


def extract_mdna(cleaned: str, form_type: str = "10-K") -> tuple[str | None, str]:
    """
    Extract the MD&A section from cleaned, uppercased text.

    Returns (mdna_text or None, status). status ∈ {
        'ok'         extraction succeeded (length within bounds),
        'no_match'   no tier matched,
    }.
    """
    is_ksb = "KSB" in form_type.upper()
    # Tier order: form-specific first, then Roman numeral, then bare.
    tiers: list[tuple[str, re.Pattern]] = []
    if is_ksb:
        tiers.append(("t1_ksb_item6", _T1_10KSB))
    else:
        tiers.append(("t1_10k_item7", _T1_10K))
    # Roman-numeral attempt for 10-KSBs that use VI. headings.
    if is_ksb:
        tiers.append(("t2_roman", _T2_ROMAN))
    tiers.append(("t3_bare", _T3_BARE))

    for tier_name, pat in tiers:
        hit = _try_tier(pat, cleaned)
        if hit is not None:
            s, e = hit
            return cleaned[s:e].strip(), f"ok_{tier_name}"

    return None, "no_match"


# --------------------------------------------------------------------------- #
# 3. Tokenization                                                              #
# --------------------------------------------------------------------------- #

# LM (2011) appendix: "two or more alphabetic characters. (Hyphens are also
# allowed in the character collections.)" — no apostrophes. So "MANAGEMENT'S"
# becomes "MANAGEMENT" + dropped "S", giving a dictionary hit.
TOKEN_RE = re.compile(r"\b[A-Z][A-Z\-]+\b")


def tokenize(text: str) -> list[str]:
    """LM-style tokenization: alphabetic tokens (length ≥ 2), hyphens allowed."""
    return TOKEN_RE.findall(text)
