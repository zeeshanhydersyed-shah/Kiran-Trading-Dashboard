"""archive/financials_parser.py -- parsing against real, confirmed edge cases
from the ksestocks.com announcements corpus (docs/FINANCIALS_PIPELINE_DESIGN.md
Section 3.1). Each test's HTML is quoted verbatim from the actual cached pages,
not synthesized, so a regex change that breaks a real page fails here first.
"""
from __future__ import annotations

from archive import financials_parser as fp


def _row(company_cell: str, date_cell: str, ann_cell: str) -> str:
    return (
        '<tr class="data-tr">'
        f'<td class="plain" style="x">{company_cell}</td>'
        f'<td class="plain" style="x">{date_cell}</td>'
        f'<td class="plain" style="x">{ann_cell}</td>'
        '</tr>'
    )


# ------------------------------------------------------------- parse_amount

def test_parse_amount_plain():
    assert fp.parse_amount("39.50") == (39.50, False)


def test_parse_amount_thousands_comma():
    assert fp.parse_amount("279,314.861") == (279314.861, False)


def test_parse_amount_parenthesized_negative():
    assert fp.parse_amount("(12.5)") == (-12.5, False)


def test_parse_amount_thousands_separator_bug_corrected():
    """The real HBL data-entry error: '.' used as a thousands separator."""
    val, corrected = fp.parse_amount("8.041.416")
    assert val == 8041.416
    assert corrected is True


def test_parse_amount_nil_and_empty():
    assert fp.parse_amount(None) == (None, False)
    assert fp.parse_amount("") == (None, False)


# ------------------------------------------------------------ real HTML rows

def test_ogdc_dual_basis_row():
    """OGDC 2025-09-23: both CONSOLIDATED and UNCONSOLIDATED EPS/PBT/PAT, plus
    dividend, AGM, and book closure, all in ONE row."""
    html = _row(
        "Oil and Gas Development Company Limited<br />(OGDC)",
        "September 23rd, 2025",
        "FINANCIAL RESULT FOR THE YEAR ENDED 30/06/2025<br />"
        "(UNCONSOLIDATED) PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 279,314.861<br />"
        "(UNCONSOLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 169,903.614<br />"
        "(UNCONSOLIDATED) EPS = 39.50<br />"
        "(CONSOLIDATED) PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 279,313.761<br />"
        "(CONSOLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 169,902.514<br />"
        "(CONSOLIDATED) EPS = 39.50<br />"
        "DIVIDEND = 50%(F)<br />"
        "ANNUAL GENERAL MEETING WILL BE HELD ON 27/10/2025<br />"
        "BOOK CLOSURE FROM 23/10/2025<br />"
        "BOOK CLOSURE TO 27/10/2025",
    )
    rows = fp.extract_rows("OGDC", html)
    assert len(rows) == 1
    r = rows[0]
    assert r["announce_date"] == "2025-09-23"
    assert r["fiscal_period_type"] == "YEAR"
    assert r["fiscal_period_ended"] == "2025-06-30"
    assert r["eps_consolidated"] == 39.50
    assert r["eps_unconsolidated"] == 39.50
    assert r["eps_unspecified"] is None
    assert r["eps_basis_inferred"] is False
    assert r["pbt_unconsolidated"] == 279314.861
    assert r["pbt_consolidated"] == 279313.761
    assert r["pat_unconsolidated"] == 169903.614
    assert r["pat_consolidated"] == 169902.514
    assert r["dividend_pct"] == 50.0
    assert r["dividend_flag"] == "F"
    assert r["agm_date"] == "2025-10-27"
    assert r["book_closure_from"] == "2025-10-23"
    assert r["book_closure_to"] == "2025-10-27"
    assert r["parse_confidence"] == "HIGH"


def test_hbl_same_date_split_across_two_rows():
    """HBL 2008-02-14: the same announce_date split across two separate <tr>
    rows -- one CONSOLIDATED, one UNCONSOLIDATED with an unlabeled EPS whose
    basis must be inferred from the row's other tokens. Also exercises the
    thousands-separator bug ('8.041.416') in the second row."""
    row_a = _row(
        "Habib Bank Limited<br />(HBL)", "February 14th, 2008",
        "FINANCIAL RESULT FOR THE YEAR ENDED 31/12/2007<br />"
        "DIVIDEND = 40%(F)<br />"
        "BONUS ISSUE = 10%<br />"
        "CONSOLIDATED P/L BEFORE TAX RS. IN MIL 15,144.617<br />"
        "BOOK CLOSURE TO 28/03/2008<br />"
        "EPS = 14.49<br />"
        "ANNUAL GENERAL MEETING WILL BE HELD ON 28/03/2008<br />"
        "BOOK CLOSURE FROM 14/03/2008<br />"
        "CONSOLIDATED P/L AFTER TAX RS. IN MIL 10,084.037",
    )
    row_b = _row(
        "Habib Bank Limited<br />(HBL)", "February 14th, 2008",
        "FINANCIAL RESULT FOR THE YEAR ENDED 31/12/2007<br />"
        "EPS = 11.65<br />"
        "UNCONSOLIDATED P/L AFTER TAX RS. IN MIL 8.041.416<br />"
        "UNCONSOLIDATED P/L BEFORE TAX RS. IN MIL 13,127.002",
    )
    rows = fp.extract_rows("HBL", row_a + row_b)
    assert len(rows) == 2

    a = rows[0]
    assert a["row_index"] == 0
    assert a["eps_consolidated"] == 14.49
    assert a["eps_unconsolidated"] is None
    assert a["eps_basis_inferred"] is True
    assert a["pbt_consolidated"] == 15144.617
    assert a["pat_consolidated"] == 10084.037
    assert a["dividend_pct"] == 40.0 and a["dividend_flag"] == "F"
    assert a["bonus_pct"] == 10.0
    assert a["book_closure_from"] == "2008-03-14"
    assert a["book_closure_to"] == "2008-03-28"
    assert a["agm_date"] == "2008-03-28"
    assert a["parse_confidence"] == "MEDIUM"

    b = rows[1]
    assert b["row_index"] == 1
    assert b["eps_unconsolidated"] == 11.65
    assert b["eps_consolidated"] is None
    assert b["eps_basis_inferred"] is True
    assert b["pat_unconsolidated"] == 8041.416  # corrected from '8.041.416'
    assert b["pbt_unconsolidated"] == 13127.002
    assert b["parse_confidence"] == "LOW"  # the thousands-separator correction
    assert "thousands-separator" in b["parse_notes"]


def test_unconslidated_misspelling_parses_like_correct_spelling():
    html = _row(
        "Fauji Fertilizer Company Limited<br />(FFC)", "April 28th, 2015",
        "FINANCIAL RESULT FOR THE QUARTER ENDED 31/03/2015<br />"
        "(UNCONSLIDATED) EPS = 5.12<br />"
        "(UNCONSLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 1,234.5",
    )
    rows = fp.extract_rows("FFC", html)
    r = rows[0]
    assert r["eps_unconsolidated"] == 5.12
    assert r["pat_unconsolidated"] == 1234.5
    assert r["parse_confidence"] == "HIGH"


def test_ffc_pbt_pat_present_eps_absent_for_that_basis():
    """FFC-shaped: (CONSOLIDATED) PBT/PAT present, consolidated EPS token
    simply absent from this row -- must not crash, must leave eps_* as None."""
    html = _row(
        "Fauji Fertilizer Company Limited<br />(FFC)", "July 27th, 2016",
        "(CONSOLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 8,760.815<br />"
        "DIVIDEND = 17.5 %(II)",
    )
    rows = fp.extract_rows("FFC", html)
    r = rows[0]
    assert r["pat_consolidated"] == 8760.815
    assert r["eps_consolidated"] is None
    assert r["eps_unconsolidated"] is None
    assert r["eps_unspecified"] is None
    assert r["dividend_pct"] == 17.5
    assert r["dividend_flag"] == "II"


def test_plain_dividend_with_no_trailing_flag_still_parsed():
    """A real gap in the existing phase_4b extractor: DIVIDEND = 15% with no
    (F)/(I) flag at all would be silently dropped there. Must not be here."""
    html = _row(
        "Al-Abbas Sugar Mills Limited<br />(AABS)", "January 9th, 2009",
        "FINANCIAL RESULT FOR THE YEAR ENDED 30/09/2008<br />"
        "DIVIDEND = 15%<br />"
        "PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 96.427<br />"
        "PROFIT/LOSS AFTER TAXATION RS. IN MILLION 75.045<br />"
        "EPS = 4.32<br />"
        "ANNUAL GENERAL MEETING WILL BE HELD ON 31/01/2009<br />"
        "BOOK CLOSURE FROM 24/01/2009<br />"
        "BOOK CLOSURE TO 31/01/2009",
    )
    r = fp.extract_rows("AABS", html)[0]
    assert r["dividend_pct"] == 15.0
    assert r["dividend_flag"] is None
    assert r["eps_unspecified"] == 4.32  # no other basis-labeled token in the row to infer from
    assert r["eps_consolidated"] is None and r["eps_unconsolidated"] is None
    assert r["pbt_unspecified"] == 96.427
    assert r["pat_unspecified"] == 75.045


def test_combined_book_closure_from_to_on_one_line():
    """AABS 2005-01-09 narrative phrasing: 'BOOK CLOSURE FROM D1 TO D2' on one
    line -- confirmed the existing CA-ledger extractor gets this half-wrong
    (misses the TO date entirely). Both dates must be populated here."""
    html = _row(
        "Al-Abbas Sugar Mills Limited<br />(AABS)", "January 9th, 2005",
        "DIVIDEND FOR THE YEAR ENDED 30/09/2004 35%<br />"
        "PROFIT BEFORE TAXATION RS. IN MILLION 211.390<br />"
        "BOOK CLOSURE FROM 13/01/2005 TO 20/01/2005<br />"
        "ANNUAL GENERAL MEETING WILL BE HELD ON 20/01/2005<br />"
        "PROFIT AFTER TAXATION RS. IN MILLION 233.518",
    )
    r = fp.extract_rows("AABS", html)[0]
    assert r["book_closure_from"] == "2005-01-13"
    assert r["book_closure_to"] == "2005-01-20"
    assert r["dividend_pct"] == 35.0
    assert r["pbt_unspecified"] == 211.390
    assert r["pat_unspecified"] == 233.518


def test_book_closure_to_before_from_order_independent():
    """Field order in the raw text is not reliable (confirmed: TO appears
    before FROM in some real rows) -- both must still be found."""
    html = _row(
        "Al-Abbas Sugar Mills Limited<br />(AABS)", "December 20th, 2006",
        "FINANCIAL RESULT FOR THE YEAR ENDED 30/09/2006<br />"
        "PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 31.655<br />"
        "PROFIT/LOSS AFTER TAXATION RS. IN MILLION 4.864<br />"
        "BOOK CLOSURE TO 27/01/2007<br />"
        "ANNUAL GENERAL MEETING WILL BE HELD ON 27/01/2007<br />"
        "BOOK CLOSURE FROM 18/01/2007<br />"
        "EPS = 0.28",
    )
    r = fp.extract_rows("AABS", html)[0]
    assert r["book_closure_from"] == "2007-01-18"
    assert r["book_closure_to"] == "2007-01-27"


def test_company_cell_code_mismatch_flagged_not_fatal():
    html = _row(
        "Some Renamed Company<br />(WRONGCODE)", "March 1st, 2020",
        "EPS = 1.00",
    )
    r = fp.extract_rows("REALCODE", html)[0]
    assert r["eps_unspecified"] == 1.00
    assert "WRONGCODE" in r["parse_notes"] and "REALCODE" in r["parse_notes"]


def test_multiple_rows_in_one_page_get_sequential_row_index():
    html = (
        _row("X Ltd<br />(XLTD)", "January 1st, 2020", "EPS = 1.0")
        + _row("X Ltd<br />(XLTD)", "April 1st, 2020", "EPS = 2.0")
    )
    rows = fp.extract_rows("XLTD", html)
    assert [r["row_index"] for r in rows] == [0, 1]
    assert [r["announce_date"] for r in rows] == ["2020-01-01", "2020-04-01"]


def test_unparseable_date_still_returns_a_row_flagged_low_confidence():
    html = _row("X Ltd<br />(XLTD)", "not a real date", "EPS = 1.0")
    r = fp.extract_rows("XLTD", html)[0]
    assert r["announce_date"] is None
    assert r["parse_confidence"] == "LOW"
    assert "announce_date" in r["parse_notes"]


def test_no_data_tr_rows_returns_empty_list():
    assert fp.extract_rows("NOPE", "<html><body>no announcements</body></html>") == []


def test_source_row_sha256_is_stable_and_content_sensitive():
    html_a = _row("X Ltd<br />(XLTD)", "January 1st, 2020", "EPS = 1.0")
    html_b = _row("X Ltd<br />(XLTD)", "January 1st, 2020", "EPS = 1.1")
    a1 = fp.extract_rows("XLTD", html_a)[0]["source_row_sha256"]
    a2 = fp.extract_rows("XLTD", html_a)[0]["source_row_sha256"]
    b = fp.extract_rows("XLTD", html_b)[0]["source_row_sha256"]
    assert a1 == a2
    assert a1 != b
