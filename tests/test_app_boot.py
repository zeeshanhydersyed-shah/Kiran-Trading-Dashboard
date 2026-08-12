"""Boot smoke tests for dashboard.py.

WHY THIS EXISTS, SEPARATELY FROM THE UNIT TESTS
-----------------------------------------------
The unit tests in this directory cover pure logic (backfill generators, gap
detection). They would not have caught the crash that actually shipped:
`st.secrets` being read before `st.set_page_config()`, which raises
`StreamlitSetPageConfigMustBeFirstCommandError` on Streamlit 1.39.1 (the
version requirements.txt pins) but is silently tolerated by the much newer
Streamlit that had drifted into the local dev environment. That bug sat
undetected for a week -- see docs/KIRAN_CLEANUP_AUDIT.md §21 root cause 3
and §22 A6.

These tests run the real dashboard script through Streamlit's own
`AppTest` harness, which executes it with a genuine script-run context, so
Streamlit-runtime errors (not just Python import errors) surface. Verified
2026-08-12 to reproduce both shipped bugs when run against the pre-fix code:
  * the `set_page_config` ordering crash (whole app dead), and
  * `st.dataframe(..., width='stretch')` raising
    `TypeError: 'str' object cannot be interpreted as an integer`,
    which was breaking 3 of the 15 pages outright.

DATABASE
--------
The app needs a SQLite database with the production schema. If a real
`psx_data.db` is present in the repo root (a developer machine), it is used
as-is and never modified. If not (a fresh CI checkout -- `psx_data.db` is
gitignored), the committed fixture at `tests/fixtures/psx_fixture.db` is
copied into place for the duration of the test session and removed
afterwards. Regenerate the fixture with
`python tests/fixtures/build_fixture_db.py` after any schema change.

`DATABASE_URL`/`SUPABASE_DB_URL` are forced to empty for the whole session,
so these tests can never reach production Postgres -- matching this
project's standing rule that automated tests never touch production data.
"""
from __future__ import annotations

import os
import shutil
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

DASHBOARD = os.path.join(_ROOT, "dashboard.py")
LIVE_DB = os.path.join(_ROOT, "psx_data.db")
FIXTURE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "psx_fixture.db")

# Mirrors dashboard.py's PAGES list. Kept as a literal rather than imported
# so that a page silently disappearing from dashboard.py fails this test
# loudly instead of quietly shrinking the matrix -- the PAGES list has
# drifted from its documentation before (audit §0).
PAGES = [
    "🎯 Market Gates Dashboard", "🧭 Regime", "📊 Market", "🔍 Explorer",
    "📈 History", "📋 Trade Log", "📉 Analytics", "🔄 Recovery Bases",
    "🎯 Setup Perf", "🤖 Backtest", "🗂️ Portfolio", "🤖 Agent",
    "🏆 Leaders", "📋 Setup History", "🏥 Data Health",
]

# ASCII ids so pytest -v output stays readable on a Windows cp1252 console.
PAGE_IDS = [p.split(" ", 1)[1].replace(" ", "-").lower() for p in PAGES]


@pytest.fixture(scope="session", autouse=True)
def _no_production_db():
    """Hard guarantee: these tests never connect to production Postgres.

    Set (not deleted) because dashboard.py only copies `DATABASE_URL` out of
    `st.secrets` when the key is absent from os.environ -- an empty string is
    both present and falsy, so it blocks a stray local secrets.toml from
    pointing the test at Supabase.
    """
    mp = pytest.MonkeyPatch()
    for key in ("DATABASE_URL", "SUPABASE_DB_URL"):
        mp.setenv(key, "")
    yield
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Use the real local DB if there is one; otherwise stage the fixture."""
    if os.path.exists(LIVE_DB):
        yield LIVE_DB  # developer machine -- read-only use, never touched
        return
    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"no psx_data.db and no fixture at {FIXTURE_DB}")
    shutil.copyfile(FIXTURE_DB, LIVE_DB)
    try:
        yield LIVE_DB
    finally:
        # Leave the tree as it was found -- the fixture is a test artifact,
        # not a database this repo should start carrying around.
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = LIVE_DB + suffix
            if os.path.exists(path):
                os.remove(path)


def _run_page(page: str | None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(DASHBOARD, default_timeout=300)
    if page is not None:
        at.session_state["page"] = page
    at.run()
    return at


def _assert_clean(at, label: str):
    if at.exception:
        details = "\n\n".join(
            f"{e.value}\n" + "".join(e.stack_trace or []) for e in at.exception
        )
        pytest.fail(f"{label} raised an uncaught app exception:\n\n{details}")


def test_app_boots():
    """The app renders its default page without an uncaught exception."""
    at = _run_page(None)
    _assert_clean(at, "dashboard.py (default page)")
    assert len(at.markdown) > 0, "app produced no output at all"


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_renders(page):
    """Every page in the nav renders without an uncaught exception.

    Page selection is seeded through `st.session_state["page"]`, which is
    exactly what dashboard.py's sidebar selectbox writes -- no widget
    interaction needed, and no dependence on the selectbox's own layout.
    """
    at = _run_page(page)
    _assert_clean(at, f"page {page!r}")
