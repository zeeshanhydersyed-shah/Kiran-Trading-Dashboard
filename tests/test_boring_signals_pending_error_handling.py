"""Regression tests for scan_boring_breakouts_pending()'s exception handling
fix (docs/KIRAN_CLEANUP_AUDIT.md §44).

Background: the per-date scan loop used a single broad
`except Exception -> log.warning` and CONTINUED to the next date on any
failure. If scan_boring_breakouts() has a genuine bug (not a transient DB
blip) that fails on every pending date, the loop would silently continue
through all of them, log N warnings nobody reads, and return total=0 --
which main.py's hook then reports via _record_hook(status="ok",
rows_written=0), indistinguishable from a clean scan that legitimately found
no new signals. boring_signals feeds real trading capital (the PRL incident,
§33) -- "0 new signals" must mean that, not "the scanner silently failed."

Mirrors the fix already proven for backfill_setup_log.py's SQLite path
(tests/test_setup_log_backfill_error_handling.py): a transient error
(sqlite3.OperationalError) breaks the loop so a later run can still reach
the date via the boring_signals_scanned marker (TR-13/OI-6); anything else
raises.

Uses minimal monkeypatching of the module's own helpers rather than a full
universe/price-history fixture -- this test targets the loop's failure
semantics specifically, not the scan logic itself (covered elsewhere).
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import boring_signals as bs  # noqa: E402

DATES = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_psx.db")
    con = sqlite3.connect(db)
    bs.ensure_boring_signals_table(con)
    con.close()

    monkeypatch.setattr(bs, "DB_PATH", db)
    monkeypatch.setattr(bs, "_PG_URL", None)
    # Bypass real universe/price-history construction -- the loop under test
    # only needs `all_dates` to be non-trivial and non-empty.
    monkeypatch.setattr(bs, "_eligible_universe", lambda conn: {"AAA"})
    monkeypatch.setattr(
        bs, "_load_price_history",
        lambda conn, universe: {"AAA": {"dates": DATES}},
    )
    return db


def _signal_dates_scanned(calls):
    return list(calls)


def test_unexpected_error_raises_instead_of_silently_continuing(temp_db, monkeypatch):
    calls = []

    def _boom(scan_date):
        calls.append(scan_date)
        if scan_date == DATES[2]:
            raise ValueError("simulated unexpected bug")
        return 0

    monkeypatch.setattr(bs, "scan_boring_breakouts", _boom)

    with pytest.raises(ValueError, match="simulated unexpected bug"):
        bs.scan_boring_breakouts_pending()

    # The loop must not have continued past the failure to later dates.
    assert DATES[3] not in calls
    assert DATES[4] not in calls


def test_transient_error_breaks_without_raising(temp_db, monkeypatch):
    calls = []

    def _locked(scan_date):
        calls.append(scan_date)
        if scan_date == DATES[2]:
            raise sqlite3.OperationalError("database is locked")
        return 0

    monkeypatch.setattr(bs, "scan_boring_breakouts", _locked)

    # Must NOT raise -- a transient blip is tolerated, not fatal.
    total = bs.scan_boring_breakouts_pending()

    assert total == 0
    assert DATES[3] not in calls
    assert DATES[4] not in calls


def test_clean_run_with_no_errors_scans_every_pending_date(temp_db, monkeypatch):
    calls = []

    def _clean(scan_date):
        calls.append(scan_date)
        return 1 if scan_date == DATES[4] else 0

    monkeypatch.setattr(bs, "scan_boring_breakouts", _clean)

    total = bs.scan_boring_breakouts_pending()

    assert calls == DATES
    assert total == 1
