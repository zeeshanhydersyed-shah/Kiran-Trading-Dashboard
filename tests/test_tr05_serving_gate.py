"""TR-05 Blocker 2 -- serving-time fail-closed publication gate in dashboard.py.

Uses Streamlit's AppTest harness, same pattern as tests/test_app_boot.py.
data_health.check_all is monkeypatched to a fixed Verdict so the serving
decision is deterministic -- these tests assert the actual rendered content
differs by verdict, not just that the banner text changes (per this task's
explicit requirement: test the serving decision, not the banner).

DATABASE: same fixture-or-real-local-db convention as test_app_boot.py,
read-only (AppTest only renders, never writes). DATABASE_URL/SUPABASE_DB_URL
are forced empty for the whole session so these tests can never reach
production Postgres.
"""
from __future__ import annotations

import os
import shutil
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from data_health import Item, Verdict

DASHBOARD = os.path.join(_ROOT, "dashboard.py")
LIVE_DB = os.path.join(_ROOT, "psx_data.db")
FIXTURE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "psx_fixture.db")

NOT_VERIFIED_TEXT = "NOT VERIFIED"


@pytest.fixture(scope="session", autouse=True)
def _no_production_db():
    mp = pytest.MonkeyPatch()
    for key in ("DATABASE_URL", "SUPABASE_DB_URL"):
        mp.setenv(key, "")
    yield
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Use the real local DB if there is one; otherwise stage the fixture.

    Read-only use only -- AppTest renders pages, it does not write. Mirrors
    tests/test_app_boot.py's established, already-safe convention exactly.
    """
    if os.path.exists(LIVE_DB):
        yield LIVE_DB
        return
    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"no psx_data.db and no fixture at {FIXTURE_DB}")
    shutil.copyfile(FIXTURE_DB, LIVE_DB)
    try:
        yield LIVE_DB
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = LIVE_DB + suffix
            if os.path.exists(path):
                os.remove(path)


def _verdict(level: str, items=None) -> Verdict:
    return Verdict(level=level, expected="2026-08-24", expected_source="ksestocks",
                   items=items or [])


def _run(monkeypatch, page: str | None, verdict: Verdict):
    """Run dashboard.py with data_health.check_all patched to a fixed verdict.

    Patching the attribute on the data_health module (rather than trying to
    intercept dashboard.py's own `import data_health as _dh_mod` binding)
    works regardless of import ordering, because dashboard.py looks up
    `_dh_mod.check_all` at call time, not at import time.
    """
    import data_health
    monkeypatch.setattr(data_health, "check_all", lambda expected_session, source_error: verdict)

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


def _all_text(at) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    # st.expander's own title isn't part of at.markdown/at.caption -- pull it
    # separately so assertions can see "Kiran's Voice" / the blocked label,
    # which live in the expander title, not the body.
    parts += [getattr(e, "label", "") for e in at.expander]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 1. Fresh verdict -> actionable content may render
# ---------------------------------------------------------------------------

def test_green_verdict_renders_explorer_normally(monkeypatch):
    at = _run(monkeypatch, "🔍 Explorer", _verdict("green"))
    _assert_clean(at, "Explorer (green)")
    assert NOT_VERIFIED_TEXT not in _all_text(at)


# ---------------------------------------------------------------------------
# 2 & 3. Stale / cannot-verify verdict -> actionable content is blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page", [
    "🔍 Explorer", "📋 Setup History", "🏆 Leaders", "🔄 Recovery Bases", "🗂️ Portfolio",
])
def test_red_verdict_blocks_actionable_pages(monkeypatch, page):
    at = _run(monkeypatch, page,
              _verdict("red", items=[Item("prices", "stale", "3 sessions behind", behind=3)]))
    _assert_clean(at, f"{page} (red)")
    assert NOT_VERIFIED_TEXT in _all_text(at)


def test_amber_verdict_blocks_actionable_page(monkeypatch):
    at = _run(monkeypatch, "🔍 Explorer",
              _verdict("amber", items=[Item("prices", "unknown", "cannot reach ksestocks")]))
    _assert_clean(at, "Explorer (amber)")
    assert NOT_VERIFIED_TEXT in _all_text(at)


# ---------------------------------------------------------------------------
# 4. Blocked state visibly communicates NOT VERIFIED — DO NOT TRADE
# ---------------------------------------------------------------------------

def test_blocked_state_shows_required_label(monkeypatch):
    at = _run(monkeypatch, "🔍 Explorer",
              _verdict("red", items=[Item("prices", "stale", "stale")]))
    _assert_clean(at, "Explorer (red, label check)")
    assert "NOT VERIFIED — DO NOT TRADE" in _all_text(at)


# ---------------------------------------------------------------------------
# 5. kiran_voice.py cannot bypass the dashboard-level gate
# ---------------------------------------------------------------------------

def test_kiran_voice_blocked_when_not_verified(monkeypatch):
    at = _run(monkeypatch, "🎯 Market Gates Dashboard",
              _verdict("red", items=[Item("prices", "stale", "stale")]))
    _assert_clean(at, "Kiran's Voice panel (red)")
    text = _all_text(at)
    assert "Kiran's Voice" in text
    assert "unavailable — not verified" in text
    # The interactive Ask/Morning Brief controls must not be present.
    ask_buttons = [b for b in at.button if getattr(b, "label", "") == "Ask"]
    assert ask_buttons == [] or all(not b.value for b in ask_buttons)


def test_kiran_voice_available_when_verified(monkeypatch):
    """When verified, the gate must take the normal-render branch, not the
    blocked branch -- i.e. the panel's own try body ran (whatever it renders
    or doesn't, per its pre-existing "never crashes the dashboard" swallow),
    rather than the else-branch's blocked-label expander."""
    at = _run(monkeypatch, "🎯 Market Gates Dashboard", _verdict("green"))
    _assert_clean(at, "Kiran's Voice panel (green)")
    text = _all_text(at)
    assert "unavailable — not verified" not in text


# ---------------------------------------------------------------------------
# 6. Non-actionable diagnostic information (Data Health) remains available
# ---------------------------------------------------------------------------

def test_data_health_page_remains_available_when_not_verified(monkeypatch):
    at = _run(monkeypatch, "🏥 Data Health",
              _verdict("red", items=[Item("prices", "stale", "stale")]))
    _assert_clean(at, "Data Health (red)")
    text = _all_text(at)
    # The page's own diagnostic content must render, not the blocking message.
    assert "Data Health" in text
    assert "Corporate Action Review" in text


# ---------------------------------------------------------------------------
# 7. Newly-identified always-on surfaces (independent-audit correction pass):
# the main-area Regime+Kelly header, and the sidebar Live Regime widget.
# Run on the Data Health page specifically -- exempt from the common
# page-dispatch gate, so these assertions isolate the widget-level gate
# (_pub_ok, checked directly in each block) from the page-dispatch gate's own
# blocking box, exactly like the Kiran's Voice tests above.
# ---------------------------------------------------------------------------

def test_regime_kelly_header_blocked_when_not_verified(monkeypatch):
    at = _run(monkeypatch, "🏥 Data Health",
              _verdict("red", items=[Item("prices", "stale", "stale")]))
    _assert_clean(at, "Regime+Kelly header (red)")
    text = _all_text(at)
    assert "Regime status and Kelly sizing withheld" in text
    assert "Kelly (30T)" not in text


def test_regime_kelly_header_available_when_verified(monkeypatch):
    at = _run(monkeypatch, "🏥 Data Health", _verdict("green"))
    _assert_clean(at, "Regime+Kelly header (green)")
    text = _all_text(at)
    assert "Regime status and Kelly sizing withheld" not in text


def test_sidebar_regime_widget_blocked_when_not_verified(monkeypatch):
    at = _run(monkeypatch, "🏥 Data Health",
              _verdict("red", items=[Item("prices", "stale", "stale")]))
    _assert_clean(at, "Sidebar Market Regime widget (red)")
    text = _all_text(at)
    assert "Market Regime withheld" in text


def test_sidebar_regime_widget_available_when_verified(monkeypatch):
    at = _run(monkeypatch, "🏥 Data Health", _verdict("green"))
    _assert_clean(at, "Sidebar Market Regime widget (green)")
    text = _all_text(at)
    assert "Market Regime withheld" not in text


def test_source_date_widget_remains_available_when_not_verified(monkeypatch):
    """Deliberate non-gating decision (diagnostic, not actionable) -- confirm
    it still renders its own content when publication is blocked, same
    exemption rationale as the Data Health page itself."""
    at = _run(monkeypatch, "🏥 Data Health",
              _verdict("red", items=[Item("prices", "stale", "stale")]))
    _assert_clean(at, "Source-date status widget (red)")
    text = _all_text(at)
    assert "Data Status" in text
