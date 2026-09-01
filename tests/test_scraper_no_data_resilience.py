"""Scraper resilience to an upstream no-data day / single-date failure.

Design contract (audit ledger §39.17 row 18, §39.19, §82; TR-05/TR-07):
an upstream outage or a page with no parseable table is a *no-data day*,
never a fatal error -- ingestion is "logged, non-fatal" and a genuinely
missed session is caught downstream by main.run_freshness_gate().

Regression target (§82): parse_market_summary()'s "no table" path returned
`[], []` (2 values) while every caller unpacks 3 -> ValueError -> the whole
daily pipeline aborted before any hook ran. The cloud scraper was down
2026-08-28 -> 2026-08-30 for exactly this reason.
"""
from __future__ import annotations

import datetime as dt

import pytest

import scraper


NO_TABLE_HTML = "<html><body><p>Service temporarily unavailable</p></body></html>"
D = dt.date(2026, 8, 28)


# --------------------------------------------------------------------------
# Part 1 -- parse_market_summary returns a 3-tuple on EVERY path
# --------------------------------------------------------------------------

def test_parse_market_summary_no_table_returns_three_empty_lists():
    result = scraper.parse_market_summary(NO_TABLE_HTML, D)
    assert result == ([], [], [])
    assert len(result) == 3


def test_parse_market_summary_no_table_unpacks_as_three():
    # the exact shape that raised ValueError before the fix
    sector_rows, price_rows, index_rows = scraper.parse_market_summary(NO_TABLE_HTML, D)
    assert sector_rows == [] and price_rows == [] and index_rows == []


def test_parse_market_summary_empty_html_returns_three():
    assert scraper.parse_market_summary("", D) == ([], [], [])


def test_scrape_date_no_table_returns_three_empty_lists(monkeypatch):
    monkeypatch.setattr(scraper, "_fetch_html", lambda td, s: NO_TABLE_HTML)
    assert scraper.scrape_date(D, object()) == ([], [], [])


def test_scrape_date_unreachable_source_returns_three_empty_lists(monkeypatch):
    monkeypatch.setattr(scraper, "_fetch_html", lambda td, s: None)
    assert scraper.scrape_date(D, object()) == ([], [], [])


# --------------------------------------------------------------------------
# Part 2 -- scrape_date_range isolates a single date's failure
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)


def test_scrape_date_range_continues_past_a_raising_date(monkeypatch, caplog):
    good = dt.date(2026, 8, 27)
    bad = dt.date(2026, 8, 28)

    def fake_scrape_date(d, session, coverage_out=None):
        if d == bad:
            raise ValueError("not enough values to unpack (expected 3, got 2)")
        return ([("HBL", "COMMERCIAL BANKS")],
                [("HBL", d.strftime("%Y-%m-%d"), 100.0, 98.0, 99.0, 1000, 99.5)],
                [])

    monkeypatch.setattr(scraper, "scrape_date", fake_scrape_date)
    with caplog.at_level("WARNING"):
        sectors, prices, indices = scraper.scrape_date_range([good, bad], object())

    # the good date's data survived; the bad date was skipped, not fatal
    assert [p[0] for p in prices] == ["HBL"]
    assert dict(sectors) == {"HBL": "COMMERCIAL BANKS"}
    assert any("Scrape FAILED for 2026-08-28" in r.message for r in caplog.records)
    assert any("could not be scraped and were skipped" in r.message for r in caplog.records)


def test_scrape_date_range_all_dates_fail_returns_empty_not_raise(monkeypatch):
    def boom(d, session, coverage_out=None):
        raise RuntimeError("ksestocks 522")

    monkeypatch.setattr(scraper, "scrape_date", boom)
    # must NOT raise -- returns three empty lists so cmd_update() continues
    # to the freshness gate
    assert scraper.scrape_date_range(
        [dt.date(2026, 8, 27), dt.date(2026, 8, 28)], object()
    ) == ([], [], [])


def test_scrape_date_range_no_table_day_is_non_fatal_end_to_end(monkeypatch):
    """The real scrape_date -> parse_market_summary chain on a table-less
    page: scrape_date_range returns empties, never raises (the §82 scenario)."""
    monkeypatch.setattr(scraper, "_fetch_html", lambda td, s: NO_TABLE_HTML)
    assert scraper.scrape_date_range([D], object()) == ([], [], [])
