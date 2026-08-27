"""TR-05 serving-boundary integration test.

Closes the proof gap identified in the 2026-08-26 forensic investigation
(docs/KIRAN_CLEANUP_AUDIT.md TR-05 section): does a genuinely stale
temporary database drive the REAL data_health.check_all() result into the
REAL dashboard.py serving/publication gate, without mocking check_all()
itself?

Every existing TR-05 test proves one half in isolation:
  - tests/test_data_health.py proves check_all()'s own detection logic
    against real (temp) SQLite state, in isolation from dashboard.py.
  - tests/test_tr05_serving_gate.py proves dashboard.py's consumption of a
    verdict -- but by handing check_all() a hand-built Verdict object via
    monkeypatch (`monkeypatch.setattr(data_health, "check_all", lambda ...)`),
    never letting the real function run.
Neither proves the two halves work correctly wired together. This file
does: it takes a throwaway copy of tests/fixtures/psx_fixture.db (the
repo's existing full-schema dashboard-test fixture -- dashboard.py's
unconditional sidebar touches many tables beyond the freshness-relevant
ones, e.g. count_sectors()/count_prices(), so a from-scratch minimal schema
is not sufficient here) and makes it genuinely stale by the same logic
tests/test_data_health.py's test_stale_table_named_with_session_count uses
(one EVERY_SESSION table's most recent rows deleted while every other table,
including prices, keeps its real dates). It then points every DB_PATH
binding dashboard.py's render can reach at that copy, and renders the real
dashboard.py through Streamlit's AppTest with check_all() completely
unmocked.

Only the live ksestocks.com network fetch (refresh_manager.get_source_date_cached)
is isolated -- it is an unrelated external dependency (today's expected
session, the INPUT check_all() is called with), not part of the
freshness-detection logic or the publication-decision logic under test. This
keeps the test deterministic and network-free without touching what it's
actually trying to prove. See the "Isolated separately" note on the fixture
below.

PRODUCTION-SAFETY: follows tests/test_tr06_dashboard_corporate_action_regression.py's
isolated_dashboard_db fixture pattern exactly -- isolated tmp_path DB, both
frozen DB_PATH bindings (config.DB_PATH and database.DB_PATH -- two
separately-bound names, per that file's documented 2026-08-24 incident)
patched, plus an active sqlite3.connect guard that refuses any connection to
the real production database path. This test never calls record_run() or
writes anything (AppTest only renders), but reuses the write-test-grade
fixture shape anyway since it is already proven safe and already established
in this repo.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import config  # noqa: E402
import data_health  # noqa: E402
import database  # noqa: E402
import refresh_manager  # noqa: E402

DASHBOARD = os.path.join(_ROOT, "dashboard.py")
REAL_DB_PATH = os.path.abspath(os.path.join(_ROOT, "psx_data.db"))
FIXTURE_DB = os.path.join(_ROOT, "tests", "fixtures", "psx_fixture.db")

# The fixture's own real latest session (confirmed via direct inspection:
# MAX(date) is 2026-08-13 across prices/index_prices/prices_adjusted/
# stock_signals/sector_signals/market_regime alike -- an internally
# consistent, fully-current snapshot before this fixture induces staleness).
LATEST = "2026-08-13"
# sector_signals' rows after this date are deleted below, leaving it 2
# sessions behind (2026-08-12, 2026-08-13 missing) while prices -- the
# reference table -- keeps both. Exact construction
# tests/test_data_health.py's test_stale_table_named_with_session_count
# uses, reused here so check_all() has to discover it itself.
STALE_CUTOFF = "2026-08-11"


@pytest.fixture
def stale_isolated_db(tmp_path, monkeypatch):
    """A throwaway copy of the repo's full-schema dashboard fixture, made
    genuinely stale by deleting sector_signals' most recent rows. Nothing
    here constructs a Verdict -- check_all() must discover the staleness
    itself from this DB's actual rows.
    """
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")

    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"no fixture at {FIXTURE_DB}")

    temp_db = str(tmp_path / "stale_serving_boundary.db")
    assert os.path.abspath(temp_db) != REAL_DB_PATH, (
        "isolated test database resolved to the real production path -- "
        "refusing to proceed"
    )
    shutil.copyfile(FIXTURE_DB, temp_db)

    con = sqlite3.connect(temp_db)
    # The induced stale condition: sector_signals silently stopped two
    # sessions ago while everything else (including prices, the reference
    # table) kept going.
    con.execute("DELETE FROM sector_signals WHERE date > ?", (STALE_CUTOFF,))
    con.commit()
    con.close()

    monkeypatch.setattr(config, "DB_PATH", temp_db)
    # database.py does `from config import DB_PATH` at its own module level
    # -- a separate, import-time-frozen name in database's own namespace,
    # not an alias that tracks config.DB_PATH (see
    # tests/test_tr06_dashboard_corporate_action_regression.py's fixture
    # docstring for the 2026-08-24 incident this caused). Every function in
    # database.py (including get_latest_stock_date(), called unconditionally
    # by dashboard.py's sidebar on every render before any page-specific
    # code runs) must be redirected explicitly.
    monkeypatch.setattr(database, "DB_PATH", temp_db)
    monkeypatch.setattr(data_health, "_PG_URL", None)

    # Isolated separately, deliberately: the live ksestocks.com fetch
    # dashboard.py uses to learn "today's" expected session. This is the
    # INPUT check_all() is called with, not part of check_all()'s detection
    # logic or dashboard.py's publication decision -- both of those still
    # run for real below. Fixed to LATEST so the "prices" item itself reads
    # ok (current through LATEST), which isolates the induced staleness to
    # sector_signals alone, deterministically, with zero network calls.
    monkeypatch.setattr(
        refresh_manager, "get_source_date_cached",
        lambda session_state, max_age_seconds=1800: (LATEST, _dt.datetime.now()),
    )

    _real_connect = sqlite3.connect

    def _guarded_connect(db_arg, *args, **kwargs):
        try:
            resolved = os.path.abspath(str(db_arg))
        except Exception:
            resolved = None
        if resolved == REAL_DB_PATH:
            raise RuntimeError(
                f"BLOCKED: attempted to open the real production database "
                f"({REAL_DB_PATH!r}) during an isolated test -- isolation "
                f"guard tripped, refusing the connection."
            )
        return _real_connect(db_arg, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _guarded_connect)

    yield temp_db


def _independent_verdict_check():
    """Confirms the fixture itself is genuinely stale, independently of
    dashboard.py/AppTest -- so a failure here means the FIXTURE is wrong,
    not the production code under test. Calls the real check_all(), not a
    mock."""
    v = data_health.check_all(expected_session=LATEST)
    assert v.level == "red", (
        f"fixture did not produce a stale verdict as intended: level={v.level}, "
        f"items={[(i.label, i.status, i.detail) for i in v.items]}"
    )
    bad = [i for i in v.items if i.label == "sector_signals"]
    assert bad and bad[0].status == "stale", (
        "expected sector_signals specifically to be the stale item"
    )
    return v


def test_real_stale_db_drives_real_check_all_into_real_dashboard_gate(stale_isolated_db):
    """The integration proof this file exists for: a genuinely stale temp DB
    drives the real check_all() result into the real dashboard.py serving
    gate, and every actionable surface is withheld as a result.
    data_health.check_all is never monkeypatched anywhere in this test."""
    # A. Real stale detection, proven independently first.
    _independent_verdict_check()

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(DASHBOARD, default_timeout=300)
    at.run()

    assert not at.exception, (
        "dashboard raised an uncaught exception against a genuinely stale DB:\n"
        + "\n".join(
            f"{e.value}\n{''.join(e.stack_trace or [])}" for e in at.exception
        )
    )

    all_markdown = [m.value for m in at.markdown]
    all_captions = [c.value for c in at.caption]
    combined = "\n".join(all_markdown + all_captions)

    # B. Real serving gate: sidebar banner reflects the real (red) verdict
    # this DB actually produced -- not a fixed string a mock returned.
    assert "DATA STALE" in combined, (
        "sidebar banner did not show the stale verdict from the real, "
        "unmocked check_all() result"
    )
    assert "sector_signals" in combined, (
        "sidebar banner did not name the actual stale table"
    )

    # C. Actionable surfaces withheld -- all three global gates.
    assert any("Market Regime withheld" in c for c in all_captions), (
        "sidebar regime widget was not withheld"
    )
    assert any(
        "Regime status and Kelly sizing withheld" in c for c in all_captions
    ), "main-area regime/Kelly header was not withheld"
    assert "Kiran's Voice is withheld" in combined, (
        "Kiran's Voice panel was not withheld"
    )

    # D. Fail-closed messaging present, and the page-dispatch gate actually
    # stopped execution before PAGES[0]'s own actionable content rendered
    # (its unique, unmistakable header markup is "MARKET GATES" -- absent
    # here proves st.stop() cut the run short, not just that a banner
    # happened to render alongside a normal page).
    assert "NOT VERIFIED" in combined and "DO NOT TRADE" in combined
    assert "This page's content is withheld" in combined
    assert "MARKET GATES" not in combined, (
        "PAGES[0]'s actionable content rendered despite a stale/unverified "
        "state -- the page-dispatch gate did not withhold it"
    )


def test_data_health_page_remains_accessible_when_stale(stale_isolated_db):
    """The one exempt page (Data Health, PAGES[14]) must still render its
    own diagnostic content when the system is stale -- it is the surface a
    user needs precisely when the gate above is active. Confirms the gate
    is a publication gate, not an app-wide outage."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(DASHBOARD, default_timeout=300)
    at.session_state["page"] = "\U0001f3e5 Data Health"
    at.run()

    assert not at.exception, (
        "Data Health page raised an uncaught exception against a stale DB:\n"
        + "\n".join(
            f"{e.value}\n{''.join(e.stack_trace or [])}" for e in at.exception
        )
    )

    combined = "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])
    assert "This page's content is withheld" not in combined, (
        "Data Health page was incorrectly gated -- it must stay accessible "
        "when unverified so the user has somewhere to look"
    )
