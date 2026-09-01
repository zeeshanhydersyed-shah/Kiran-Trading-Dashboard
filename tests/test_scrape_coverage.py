"""TR-14.1a -- per-date scrape completeness vs the source's own per-sector
traded-company counts.

ksestocks' MarketSummary prints "(Number of traded companies in sector: N)"
per sector. scraper.parse_sector_counts() sums those (expected_total) and
counts the data rows actually present (parsed_total). data_health records a
COMPLETE / PARTIAL / UNKNOWN verdict per date to `scrape_coverage`.

§35.1's 2026-07-07 gap -- Postgres `prices_adjusted` empty for a whole date --
is exactly the PARTIAL (here, an empty/truncated page) this catches.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import data_health as dh  # noqa: E402
import scraper  # noqa: E402


# ---------------------------------------------------------------------------
# a minimal MarketSummary table
# ---------------------------------------------------------------------------

def _row(*cells):
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _sector_header(name, n):
    return _row(name, f"(Number of traded companies in sector: {n})")


def _stock(sym):
    return _row(sym, sym + " Ltd", "10", "11", "9", "10.5", "+1", "1000")


def _market_summary_html(sectors: dict[str, int], *, drop: dict[str, int] | None = None) -> str:
    """sectors = {name: stated_count}. drop = {name: how_many_rows_to_omit}
    (simulates a truncated page). Rows are otherwise stated_count per sector."""
    drop = drop or {}
    parts = ["<html><body><table>"]
    for name, n in sectors.items():
        parts.append(_sector_header(name, n))
        parts.append(_row("Symbol", "Company", "Open", "High", "Low", "Close", "Chg", "Vol"))
        present = n - drop.get(name, 0)
        for i in range(present):
            parts.append(_stock(f"{name[:3]}{i:02d}"))
    parts.append("</table></body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# parse_sector_counts
# ---------------------------------------------------------------------------

def test_parse_sector_counts_healthy_day():
    html = _market_summary_html({"CEMENT": 20, "CHEMICAL": 27, "REFINERY": 4})
    expected, parsed, per = scraper.parse_sector_counts(html)
    assert expected == 51
    assert parsed == 51
    assert per["CEMENT"] == (20, 20)


def test_parse_sector_counts_truncated_page():
    html = _market_summary_html({"CEMENT": 20, "CHEMICAL": 27}, drop={"CEMENT": 5})
    expected, parsed, per = scraper.parse_sector_counts(html)
    assert expected == 47
    assert parsed == 42
    assert per["CEMENT"] == (20, 15)


def test_parse_sector_counts_no_table_is_unknown():
    assert scraper.parse_sector_counts("<html><body>nothing</body></html>") == (None, 0, {})


def test_parse_sector_counts_ignores_uncounted_sections():
    # "Market Indexes" has an empty second header cell, no stated count -> excluded
    html = ("<html><body><table>"
            + _row("Market Indexes", "")
            + _row("KSE-100", "idx", "1", "2", "3", "4", "5", "6")
            + _sector_header("CEMENT", 3)
            + _stock("CEM01") + _stock("CEM02") + _stock("CEM03")
            + "</table></body></html>")
    expected, parsed, per = scraper.parse_sector_counts(html)
    assert expected == 3 and parsed == 3
    assert "Market Indexes" not in per


# ---------------------------------------------------------------------------
# _coverage_verdict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exp,parsed,want", [
    (None, 0, "UNKNOWN"),
    (100, 100, "COMPLETE"),
    (100, 101, "COMPLETE"),
    (100, 99, "PARTIAL"),
    (100, None, "PARTIAL"),
])
def test_coverage_verdict(exp, parsed, want):
    assert dh._coverage_verdict(exp, parsed) == want


# ---------------------------------------------------------------------------
# record_scrape_coverage + scrape_coverage_status  (isolated SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    db = str(tmp_path / "cov.db")
    sqlite3.connect(db).close()
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", db)
    return db


def test_record_and_read_back(sqlite_db):
    rows = [
        {"scrape_date": "2026-08-27", "expected_total": 490, "parsed_total": 490, "detail": None},
        {"scrape_date": "2026-08-28", "expected_total": 490, "parsed_total": 470,
         "detail": "CEMENT: 20 stated, 0 parsed"},
        {"scrape_date": "2026-08-25", "expected_total": None, "parsed_total": 0, "detail": None},
    ]
    out = dh.record_scrape_coverage(rows)
    assert {r["scrape_date"]: r["coverage_status"] for r in out} == {
        "2026-08-27": "COMPLETE", "2026-08-28": "PARTIAL", "2026-08-25": "UNKNOWN"}
    assert dh.scrape_coverage_status("2026-08-27") == "COMPLETE"
    assert dh.scrape_coverage_status("2026-08-28") == "PARTIAL"
    # idempotent upsert -- re-record the same dates, no duplicate rows
    dh.record_scrape_coverage(rows)
    con = sqlite3.connect(sqlite_db)
    assert con.execute("SELECT COUNT(*) FROM scrape_coverage").fetchone()[0] == 3
    con.close()


def test_record_scrape_coverage_empty_is_noop(sqlite_db):
    assert dh.record_scrape_coverage([]) == []


def test_scrape_coverage_status_missing_table_is_none(sqlite_db):
    # table not created yet (no record_scrape_coverage call)
    assert dh.scrape_coverage_status("2026-08-27") is None


def test_record_scrape_coverage_never_raises_on_write_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", str(tmp_path / "nonexistent_dir" / "x.db"))
    out = dh.record_scrape_coverage(
        [{"scrape_date": "2026-08-27", "expected_total": 1, "parsed_total": 1, "detail": None}])
    assert out[0]["coverage_status"] == "COMPLETE"      # verdict still computed


# ---------------------------------------------------------------------------
# scrape_date_range -> coverage_out  (fake HTTP, no network)
# ---------------------------------------------------------------------------

def test_scrape_date_range_populates_coverage_out(monkeypatch):
    full = _market_summary_html({"CEMENT": 3, "REFINERY": 2})
    short = _market_summary_html({"CEMENT": 3, "REFINERY": 2}, drop={"REFINERY": 1})

    def fake_fetch(d, session):
        return short if d == dt.date(2026, 8, 28) else full

    monkeypatch.setattr(scraper, "_fetch_html", fake_fetch)
    cov: list = []
    scraper.scrape_date_range([dt.date(2026, 8, 27), dt.date(2026, 8, 28)],
                              session=object(), coverage_out=cov)

    by_date = {r["scrape_date"]: r for r in cov}
    assert by_date["2026-08-27"]["expected_total"] == 5
    assert by_date["2026-08-27"]["parsed_total"] == 5
    assert by_date["2026-08-28"]["parsed_total"] == 4
    assert "REFINERY" in by_date["2026-08-28"]["detail"]
    assert dh._coverage_verdict(by_date["2026-08-28"]["expected_total"],
                                by_date["2026-08-28"]["parsed_total"]) == "PARTIAL"


def test_ghost_date_gets_no_coverage_row(monkeypatch):
    """A date PSX served as a stale copy of the prior session is skipped (no
    rows stored) -- and must get no scrape_coverage row either."""
    # _is_stale() needs >= 20 common symbols whose H/L/C match the prior day.
    big = _market_summary_html({"CEMENT": 25})
    monkeypatch.setattr(scraper, "_fetch_html", lambda d, s: big)
    prev = [(f"CEM{i:02d}", "2026-08-26", 11.0, 9.0, 10.5, 1000, 10.0) for i in range(25)]
    cov: list = []
    scraper.scrape_date_range([dt.date(2026, 8, 27)], session=object(),
                              prev_prices=prev, coverage_out=cov)
    assert cov == []


# ---------------------------------------------------------------------------
# TR-14.1b -- boring_signals._completeness_ok() prefers the authoritative
# scrape_coverage verdict, falls back to the rolling-median heuristic
# ---------------------------------------------------------------------------

import boring_signals as bs  # noqa: E402

_ABS = bs.MIN_UNIVERSE_ABS
_WIN = bs.COVERAGE_MEDIAN_WINDOW


def test_completeness_absolute_floor_still_hard_fails(sqlite_db):
    # Below the absolute floor -> fail regardless of any coverage verdict.
    dh.record_scrape_coverage([{"scrape_date": "2026-08-27", "expected_total": 500,
                                "parsed_total": 500, "detail": None}])
    assert bs._completeness_ok(_ABS - 1, [], "2026-08-27") is False


def test_completeness_complete_coverage_passes_even_below_median(sqlite_db):
    # A COMPLETE authoritative verdict beats the rolling-median heuristic:
    # symbols_priced well under 0.85*median still passes.
    dh.record_scrape_coverage([{"scrape_date": "2026-08-27", "expected_total": 490,
                                "parsed_total": 490, "detail": None}])
    prior = [490] * _WIN            # median 490 -> heuristic floor ~416
    assert bs._completeness_ok(300, prior, "2026-08-27") is True


def test_completeness_partial_coverage_fails_even_above_median(sqlite_db):
    # A PARTIAL authoritative verdict fails even when the count looks healthy.
    dh.record_scrape_coverage([{"scrape_date": "2026-08-27", "expected_total": 490,
                                "parsed_total": 470,
                                "detail": "CEMENT: 20 stated, 0 parsed"}])
    prior = [490] * _WIN
    assert bs._completeness_ok(488, prior, "2026-08-27") is False


def test_completeness_no_coverage_row_falls_back_to_heuristic(sqlite_db):
    # No scrape_coverage row for this date -> the old relative-floor behaviour.
    prior = [490] * _WIN           # floor ~416.5
    assert bs._completeness_ok(400, prior, "2026-08-27") is False   # below floor
    assert bs._completeness_ok(450, prior, "2026-08-27") is True    # above floor


def test_completeness_unknown_coverage_falls_back_to_heuristic(sqlite_db):
    dh.record_scrape_coverage([{"scrape_date": "2026-08-27", "expected_total": None,
                                "parsed_total": 0, "detail": None}])   # -> UNKNOWN
    prior = [490] * _WIN
    assert bs._completeness_ok(400, prior, "2026-08-27") is False
    assert bs._completeness_ok(450, prior, "2026-08-27") is True


def test_completeness_none_scan_date_is_pure_heuristic(sqlite_db):
    # Callers that don't pass scan_date get exactly the pre-TR-14.1b behaviour.
    prior = [490] * _WIN
    assert bs._completeness_ok(400, prior) is False
    assert bs._completeness_ok(450, prior) is True


def test_coverage_verdict_for_never_raises(monkeypatch):
    # A blown-up data_health query must degrade to None, not propagate.
    monkeypatch.setattr(dh.config, "DB_PATH", "/nonexistent/dir/x.db")
    monkeypatch.setattr(dh, "_PG_URL", None)
    assert bs._coverage_verdict_for("2026-08-27") is None
    # and _completeness_ok still works (heuristic path)
    assert bs._completeness_ok(_ABS + 5, [], "2026-08-27") is True
