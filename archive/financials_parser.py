r"""
Kiran Local-First Migration -- Financials/Announcements Pipeline: HTML parser.

Pure parsing functions only -- no network, no filesystem, no DB. Turns one
ksestocks.com per-symbol announcements page (the raw HTML already described in
docs/FINANCIALS_PIPELINE_DESIGN.md Section 3) into a list of ``stock_announcements``
records, one per source ``<tr class="data-tr">``.

Design doc: docs/FINANCIALS_PIPELINE_DESIGN.md (Sections 5.1 schema, 6 parsing design).
Deliberately reuses the field-name conventions of the two existing, narrower
extractors (dividend_strategy_study's phase_4b_eps_payout_extraction.py and
ca_pipeline_kse100_20260907's l0b_match_announcements.py) but is a fresh
implementation, not an import of either -- neither covers PBT/PAT/AGM date, and
phase_4b's stricter regexes silently drop rows this pipeline needs to keep.

Known, deliberately-handled real-corpus edge cases (each has a matching test in
tests/test_financials_parser.py):
  - dual-basis figures in one row (OGDC-shaped: both CONSOLIDATED and
    UNCONSOLIDATED EPS/PBT/PAT in the same announcement)
  - the same announce_date split across two separate <tr> rows with an
    unlabeled EPS whose basis must be inferred from row context (HBL-shaped)
  - a real misspelling, "UNCONSLIDATED" (missing the O), tolerated alongside
    the correct spelling
  - a source data-entry error using '.' as a thousands separator
    (e.g. "8.041.416" -> 8041.416), detected and corrected, confidence downgraded
  - "BOOK CLOSURE FROM D1 TO D2" on one combined line, an older phrasing the
    existing CA-ledger extractor does NOT handle (confirmed by reading it)
  - a dividend announced with no trailing (F)/(I)/(II) flag at all -- the
    existing phase_4b extractor's DIV_RE requires that flag and would drop
    the row entirely; this parser's flag group is optional
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as _html_module
import re

# --------------------------------------------------------------------- regex

_ROW_RE = re.compile(r'<tr class="data-tr">(.*?)</tr>', re.DOTALL)
_TD_RE = re.compile(r'<td class="plain"[^>]*>(.*?)</td>', re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_CODE_RE = re.compile(r"\(([A-Z0-9]{2,10})\)\s*$")
_ORDINAL_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)", re.IGNORECASE)

# Basis label: parenthetical "(CONSOLIDATED)" or bare prefix "CONSOLIDATED ".
# Tolerates the confirmed real misspelling "UNCONSLIDATED" (missing the O).
_BASIS = (r"(?:\((CONSOLIDATED|UNCONSOLIDATED|UNCONSLIDATED)\)\s*"
          r"|(CONSOLIDATED|UNCONSOLIDATED|UNCONSLIDATED)\s+)?")
# "PROFIT", "PROFIT/LOSS", or "P/L" -- all three phrasings confirmed in the corpus.
_PROFIT_WORD = r"P(?:ROFIT)?(?:[/\\]L(?:OSS)?)?"
_AMOUNT = r"(\(?-?[\d,.]+\)?)"

EPS_RE = re.compile(_BASIS + r"EPS\s*=\s*" + _AMOUNT, re.IGNORECASE)
PBT_RE = re.compile(
    _BASIS + _PROFIT_WORD + r"\s+BEFORE\s+TAX(?:ATION)?\s+RS\.?\s+IN\s+MIL(?:LION)?\s+" + _AMOUNT,
    re.IGNORECASE)
PAT_RE = re.compile(
    _BASIS + _PROFIT_WORD + r"\s+AFTER\s+TAX(?:ATION)?\s+RS\.?\s+IN\s+MIL(?:LION)?\s+" + _AMOUNT,
    re.IGNORECASE)

AGM_RE = re.compile(r"ANNUAL\s+GENERAL\s+MEETING\s+WILL\s+BE\s+HELD\s+ON\s+(\d{2}/\d{2}/\d{4})",
                    re.IGNORECASE)
BC_COMBINED_RE = re.compile(
    r"BOOK\s+CLOSURE\s+FROM\s+(\d{2}/\d{2}/\d{4})\s+TO\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
BC_FROM_RE = re.compile(r"BOOK\s+CLOSURE\s+FROM\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
BC_TO_RE = re.compile(r"BOOK\s+CLOSURE\s+TO\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

FISCAL_PERIOD_RE = re.compile(
    r"FOR\s+THE\s+(YEAR|HALF\s+YEAR|QUARTER)\s+ENDED\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

# Reused convention from the existing CA extractor (l0b_match_announcements.py),
# with one deliberate widening: the flag group is OPTIONAL (that script's sibling,
# phase_4b_eps_payout_extraction.py, requires it and silently drops a plain
# "DIVIDEND = 15%" with no flag -- confirmed in the real corpus), and the flag
# itself allows 1-3 letters, not just one (the corpus has "(II)" for a second
# interim dividend, which a single-letter group would not capture).
DIV_RE = re.compile(
    r"DIVIDEND\s*(?:=|:|FOR\s+THE\s+(?:YEAR|HALF\s+YEAR|QUARTER)\s+ENDED\s+\d{2}/\d{2}/\d{4})\s*"
    r"(Nil|[\d.]+\s*%)\s*(\([A-Za-z]{1,3}\))?", re.IGNORECASE)
BONUS_RE = re.compile(
    r"BONUS(?:\s+ISSUE)?\s*(?:=|:|FOR\s+THE\s+(?:YEAR|HALF\s+YEAR|QUARTER)\s+ENDED\s+\d{2}/\d{2}/\d{4})?"
    r"\s*([\d.]+)\s*%", re.IGNORECASE)

_CONF_ORDER = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}


# ------------------------------------------------------------------- helpers

def parse_amount(raw: str | None) -> tuple[float | None, bool]:
    """(value, corrected). ``corrected=True`` marks a detected/repaired
    thousands-separator data-entry error, e.g. '8.041.416' -> 8041.416 --
    only after comma-stripping, so a normal '12,345.67' is untouched."""
    if raw is None:
        return None, False
    s = raw.strip()
    if not s:
        return None, False
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    s = s.replace(",", "")
    corrected = False
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
        corrected = True
    try:
        val = float(s)
    except ValueError:
        return None, False
    return (-val if neg else val), corrected


def _ddmmyyyy_to_iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _parse_announce_date(raw: str) -> str | None:
    cleaned = _ORDINAL_RE.sub(r"\1", raw).replace(",", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    try:
        return dt.datetime.strptime(cleaned, "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def _flatten_cell(cell_html: str) -> str:
    text = _BR_RE.sub(" | ", cell_html)
    text = _TAG_RE.sub("", text)
    text = _html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _downgrade(current: str, candidate: str) -> str:
    return candidate if _CONF_ORDER[candidate] < _CONF_ORDER[current] else current


def _basis_key(basis_paren: str | None, basis_prefix: str | None) -> str:
    basis = (basis_paren or basis_prefix or "").upper()
    if basis == "CONSOLIDATED":
        return "consolidated"
    if basis in ("UNCONSOLIDATED", "UNCONSLIDATED"):
        return "unconsolidated"
    return "unspecified"


def _extract_basis_amounts(regex: re.Pattern, text: str) -> dict[str, tuple[float, bool] | None]:
    """First match per basis key wins; later duplicates in the same row are
    ignored (the corpus has no confirmed case of two figures for the same
    basis in one row -- if one ever appears, silently keeping the first is
    safer than overwriting with an unexplained later value)."""
    out: dict[str, tuple[float, bool] | None] = {"consolidated": None, "unconsolidated": None, "unspecified": None}
    for m in regex.finditer(text):
        key = _basis_key(m.group(1), m.group(2))
        if out[key] is None:
            out[key] = parse_amount(m.group(3))
    return out


def _dominant_basis(pbt: dict, pat: dict) -> str | None:
    bases = {k for d in (pbt, pat) for k in ("consolidated", "unconsolidated") if d[k] is not None}
    return next(iter(bases)) if len(bases) == 1 else None


def _val(entry: tuple[float, bool] | None) -> float | None:
    return entry[0] if entry is not None else None


# --------------------------------------------------------------------- rows

def parse_row(symbol: str, row_index: int, announce_date: str | None, raw_text: str) -> dict:
    """Parse one announcement's already-flattened text into a full
    stock_announcements record (schema: docs/FINANCIALS_PIPELINE_DESIGN.md §5.1)."""
    notes: list[str] = []
    confidence = "HIGH"

    fiscal_m = FISCAL_PERIOD_RE.search(raw_text)
    fiscal_period_type = fiscal_m.group(1).upper().replace("  ", " ") if fiscal_m else None
    fiscal_period_ended = _ddmmyyyy_to_iso(fiscal_m.group(2)) if fiscal_m else None

    eps = _extract_basis_amounts(EPS_RE, raw_text)
    pbt = _extract_basis_amounts(PBT_RE, raw_text)
    pat = _extract_basis_amounts(PAT_RE, raw_text)

    eps_basis_inferred = False
    if eps["unspecified"] is not None and eps["consolidated"] is None and eps["unconsolidated"] is None:
        dominant = _dominant_basis(pbt, pat)
        if dominant:
            eps[dominant] = eps["unspecified"]
            eps["unspecified"] = None
            eps_basis_inferred = True
            confidence = _downgrade(confidence, "MEDIUM")
            notes.append(f"EPS basis inferred as {dominant} from row context")

    for tier_name, d in (("eps", eps), ("pbt", pbt), ("pat", pat)):
        for basis, val in d.items():
            if val is not None and val[1]:
                confidence = _downgrade(confidence, "LOW")
                notes.append(f"{tier_name}_{basis}: corrected apparent thousands-separator error "
                            f"in source ({basis})")

    div_m = DIV_RE.search(raw_text)
    dividend_pct = dividend_is_nil = dividend_flag = None
    if div_m:
        raw_val, raw_flag = div_m.group(1), div_m.group(2)
        dividend_flag = raw_flag.strip("()") if raw_flag else None
        if raw_val.strip().lower() == "nil":
            dividend_pct, dividend_is_nil = 0.0, True
        else:
            dividend_pct, _c = parse_amount(raw_val.replace("%", ""))
            dividend_is_nil = False

    bonus_m = BONUS_RE.search(raw_text)
    bonus_pct = parse_amount(bonus_m.group(1))[0] if bonus_m else None

    agm_m = AGM_RE.search(raw_text)
    agm_date = _ddmmyyyy_to_iso(agm_m.group(1)) if agm_m else None

    bc_combo = BC_COMBINED_RE.search(raw_text)
    if bc_combo:
        book_closure_from = _ddmmyyyy_to_iso(bc_combo.group(1))
        book_closure_to = _ddmmyyyy_to_iso(bc_combo.group(2))
    else:
        bc_from_m = BC_FROM_RE.search(raw_text)
        bc_to_m = BC_TO_RE.search(raw_text)
        book_closure_from = _ddmmyyyy_to_iso(bc_from_m.group(1)) if bc_from_m else None
        book_closure_to = _ddmmyyyy_to_iso(bc_to_m.group(1)) if bc_to_m else None

    if announce_date is None:
        confidence = "LOW"
        notes.append("could not parse announce_date from Date cell")

    return {
        "symbol": symbol, "announce_date": announce_date, "row_index": row_index,
        "fiscal_period_type": fiscal_period_type, "fiscal_period_ended": fiscal_period_ended,
        "eps_consolidated": _val(eps["consolidated"]), "eps_unconsolidated": _val(eps["unconsolidated"]),
        "eps_unspecified": _val(eps["unspecified"]), "eps_basis_inferred": eps_basis_inferred,
        "pbt_consolidated": _val(pbt["consolidated"]), "pbt_unconsolidated": _val(pbt["unconsolidated"]),
        "pbt_unspecified": _val(pbt["unspecified"]),
        "pat_consolidated": _val(pat["consolidated"]), "pat_unconsolidated": _val(pat["unconsolidated"]),
        "pat_unspecified": _val(pat["unspecified"]),
        "dividend_pct": dividend_pct, "dividend_is_nil": dividend_is_nil, "dividend_flag": dividend_flag,
        "bonus_pct": bonus_pct, "agm_date": agm_date,
        "book_closure_from": book_closure_from, "book_closure_to": book_closure_to,
        "raw_text": raw_text, "parse_confidence": confidence,
        "parse_notes": "; ".join(notes) if notes else None,
        "source_row_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    }


def extract_rows(symbol: str, html_text: str) -> list[dict]:
    """One record per source <tr class="data-tr">, in document order."""
    out = []
    for row_index, row_html in enumerate(_ROW_RE.findall(html_text)):
        cells = _TD_RE.findall(row_html)
        if len(cells) < 3:
            continue
        company_cell, date_cell, ann_cell = cells[0], cells[1], cells[2]
        announce_date = _parse_announce_date(_flatten_cell(date_cell))
        raw_text = _flatten_cell(ann_cell)
        record = parse_row(symbol, row_index, announce_date, raw_text)

        m = _CODE_RE.search(_flatten_cell(company_cell))
        code_in_cell = m.group(1) if m else None
        if code_in_cell and code_in_cell != symbol:
            extra = f"company-cell code {code_in_cell!r} != filename symbol {symbol!r}"
            record["parse_notes"] = f"{record['parse_notes']}; {extra}" if record["parse_notes"] else extra

        out.append(record)
    return out
