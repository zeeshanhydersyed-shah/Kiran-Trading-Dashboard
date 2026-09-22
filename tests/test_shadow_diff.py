"""Phase 5, Task 5b -- shadow-diff comparator (archive/shadow_diff.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 5), rescoped 2026-09-22
(owner-approved): per-session diff of the three EVERY_SESSION tables the
incoming simplified dashboard actually reads -- `market_regime`,
`stock_signals`, `sector_signals` -- between Gold and live Supabase.
`boring_signals`/`setup_log` are being retired in their current form and are
no longer part of `digest_all`/`compare_digests`; `digest_boring`/
`digest_setup_log`/`_cmp_boring`/`_cmp_setup_log` still exist and are still
tested directly below (kept as a starting point for a future rebuild), just
not exercised through the gate's own pipeline anymore.

A one-sided symbol/pair in an EXCLUDED_SECTORS sector is Gold correctly
narrowing the universe (3.3b/3.3c), not a disagreement -- `noted`, not
`halting`. verdict: CLEAN (no halting diffs) / DISAGREE (>=1 halting diff) /
INCOMPLETE (one side hasn't reached the date yet).
"""
from __future__ import annotations

import sqlite3

import pytest

from archive import shadow_diff as sd

_SCHEMA = """
CREATE TABLE market_regime (date TEXT, regime TEXT);
CREATE TABLE stock_signals (date TEXT, symbol TEXT, bos_flag INTEGER,
    pivot_distance_pct REAL, base_tightness REAL, stage2_bull INTEGER,
    avg_vol_10d REAL, sector_rs_rank INTEGER);
CREATE TABLE sector_signals (date TEXT, sector TEXT, rs_rank REAL,
    composite_score REAL, breadth_score REAL);
CREATE TABLE boring_signals (symbol TEXT, signal_date TEXT,
    strategy_confirmed INTEGER, status TEXT);
CREATE TABLE setup_log (symbol TEXT, setup_date TEXT, setup_type TEXT);
CREATE TABLE sectors (symbol TEXT, sector TEXT);
"""


def _source(regime=None, stock_signals=(), sector_signals=(), boring=(), setup_log=(), sectors=()):
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    if regime is not None:
        conn.execute("INSERT INTO market_regime VALUES ('2026-09-10', ?)", (regime,))
    conn.executemany(
        "INSERT INTO stock_signals VALUES ('2026-09-10', ?, ?, ?, ?, ?, ?, ?)", stock_signals)
    conn.executemany(
        "INSERT INTO sector_signals VALUES ('2026-09-10', ?, ?, ?, ?)", sector_signals)
    conn.executemany(
        "INSERT INTO boring_signals VALUES (?, '2026-09-10', ?, ?)", boring)
    conn.executemany(
        "INSERT INTO setup_log VALUES (?, '2026-09-10', ?)", setup_log)
    conn.executemany("INSERT INTO sectors VALUES (?, ?)", sectors)
    conn.commit()
    return sd._Source(conn, "sqlite", "test")


# -------------------------------------------------------------- digest core

def test_compare_digests_clean_when_identical():
    row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    gold = sd.digest_all(_source(regime="TRENDING_UP", stock_signals=[row]), "2026-09-10")
    pg = sd.digest_all(_source(regime="TRENDING_UP", stock_signals=[row]), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert halting == [] and noted == []


def test_digest_all_only_has_the_three_rescoped_tables():
    """2026-09-22 rescope: boring_signals/setup_log are no longer part of the
    gate's digest at all -- see module + file docstrings."""
    digest = sd.digest_all(_source(regime="TRENDING_UP"), "2026-09-10")
    assert set(digest.keys()) == {"market_regime", "stock_signals", "sector_signals"}


def test_bos_flag_diff_is_halting():
    gold_row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    pg_row = ("HBL", 0, 1.0, 5.0, 1, 300_000, 2)
    gold = sd.digest_all(_source(stock_signals=[gold_row]), "2026-09-10")
    pg = sd.digest_all(_source(stock_signals=[pg_row]), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert len(halting) == 1
    assert halting[0]["table"] == "stock_signals" and halting[0]["kind"] == "bos_flag"
    assert halting[0]["symbols"] == ["HBL"]


def test_other_stock_signal_fields_are_noted_not_halting():
    gold_row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)   # stage2_bull=1
    pg_row = ("HBL", 1, 1.0, 5.0, 0, 300_000, 2)      # stage2_bull=0, bos same
    gold = sd.digest_all(_source(stock_signals=[gold_row]), "2026-09-10")
    pg = sd.digest_all(_source(stock_signals=[pg_row]), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert halting == []
    assert any(n["table"] == "stock_signals" and n["field"] == "stage2" for n in noted)


def test_sector_signals_diffs_are_always_noted():
    gold = sd.digest_all(_source(sector_signals=[("CEMENT", 1, 5.0, 10.0)]), "2026-09-10")
    pg = sd.digest_all(_source(sector_signals=[("CEMENT", 5, -5.0, 10.0)]), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert halting == []
    fields = {n["field"] for n in noted if n["table"] == "sector_signals"}
    assert "top3" in fields and "composite_pos" in fields
    assert "breadth_pos" not in fields  # both positive -- unchanged


def test_regime_mismatch_is_noted_not_halting():
    gold = sd.digest_all(_source(regime="TRENDING_UP"), "2026-09-10")
    pg = sd.digest_all(_source(regime="RANGING"), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert halting == []
    assert noted == [{"table": "market_regime", "field": "regime", "gold": "TRENDING_UP", "pg": "RANGING"}]


# ---------------------------------------- retired tables (not gate-wired)
#
# boring_signals/setup_log are no longer part of digest_all/compare_digests
# (2026-09-22 rescope), but digest_boring/digest_setup_log/_cmp_boring/
# _cmp_setup_log still exist for a possible future rebuild -- tested here
# directly, calling the functions rather than going through the gate.

def test_digest_boring_and_cmp_boring_still_work_standalone():
    gold_digest = sd.digest_boring(_source(boring=[("HBL", 1, "Pending")]), "2026-09-10")
    pg_digest = sd.digest_boring(_source(boring=[]), "2026-09-10")
    excl = {"TEXTILE SPINNING"}
    sector_of = {"HBL": "COMMERCIAL BANKS"}
    halting, noted = [], []
    sd._cmp_boring(gold_digest, pg_digest, excl, sector_of, halting, noted)
    assert any(h["table"] == "boring_signals" and h["kind"] == "existence" and h["only_gold"] == ["HBL"]
               for h in halting)


def test_cmp_boring_excluded_sector_only_side_is_noted_not_halting():
    gold_digest = sd.digest_boring(_source(boring=[]), "2026-09-10")
    pg_digest = sd.digest_boring(_source(boring=[("GATM", 1, "Pending")]), "2026-09-10")
    excl = {"TEXTILE SPINNING"}
    sector_of = {"GATM": "TEXTILE SPINNING"}
    halting, noted = [], []
    sd._cmp_boring(gold_digest, pg_digest, excl, sector_of, halting, noted)
    assert halting == []
    assert any(n["table"] == "boring_signals" and n["kind"] == "existence_excluded_sector_expected"
               and n["only_pg"] == ["GATM"] for n in noted)


def test_cmp_boring_confirmed_diff_is_halting_status_is_noted():
    gold_digest = sd.digest_boring(_source(boring=[("HBL", 1, "Pending")]), "2026-09-10")
    pg_digest = sd.digest_boring(_source(boring=[("HBL", 0, "Stopped")]), "2026-09-10")
    halting, noted = [], []
    sd._cmp_boring(gold_digest, pg_digest, set(), {}, halting, noted)
    assert any(h["kind"] == "strategy_confirmed" and h["symbols"] == ["HBL"] for h in halting)
    assert any(n["table"] == "boring_signals" and n["field"] == "status" for n in noted)


def test_digest_setup_log_and_cmp_setup_log_still_work_standalone():
    gold_digest = sd.digest_setup_log(_source(setup_log=[("HBL", "BREAKOUT")]), "2026-09-10")
    pg_digest = sd.digest_setup_log(_source(setup_log=[]), "2026-09-10")
    sector_of = {"HBL": "COMMERCIAL BANKS"}
    halting, noted = [], []
    sd._cmp_setup_log(gold_digest, pg_digest, set(), sector_of, halting, noted)
    assert any(h["table"] == "setup_log" and h["kind"] == "membership"
               and h["only_gold"] == ["HBL/BREAKOUT"] for h in halting)


def test_cmp_setup_log_excluded_sector_membership_diff_is_noted():
    gold_digest = sd.digest_setup_log(_source(setup_log=[]), "2026-09-10")
    pg_digest = sd.digest_setup_log(_source(setup_log=[("GATM", "RS_LEADER_MARKET")]), "2026-09-10")
    excl = {"TEXTILE SPINNING"}
    sector_of = {"GATM": "TEXTILE SPINNING"}
    halting, noted = [], []
    sd._cmp_setup_log(gold_digest, pg_digest, excl, sector_of, halting, noted)
    assert halting == []
    assert any(n["table"] == "setup_log" and n["kind"] == "membership_excluded_sector_expected"
               and n["only_pg"] == ["GATM/RS_LEADER_MARKET"] for n in noted)


def test_boring_and_setup_log_diffs_no_longer_affect_the_gate():
    """The 2026-09-21 real-world case that triggered the rescope: a
    setup_log-only diff must not surface at all through the gate's own
    digest_all/compare_digests pipeline anymore, even though the underlying
    tables still disagree."""
    gold = sd.digest_all(
        _source(regime="TRENDING_UP", boring=[("HBL", 1, "Pending")],
                setup_log=[("HBL", "RS_LEADER_SECTOR")]),
        "2026-09-10")
    pg = sd.digest_all(_source(regime="TRENDING_UP"), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert halting == [] and noted == []


# ---------------------------------------------------------- missing table

def _source_missing_sector_signals(**kw):
    """A Gold-shaped source that never got a sector_signals table built."""
    src = _source(**kw)
    src.conn.execute("DROP TABLE sector_signals")
    return src


def test_missing_table_is_unavailable_not_a_crash():
    row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    gold = sd.digest_all(_source_missing_sector_signals(regime="TRENDING_UP", stock_signals=[row]), "2026-09-10")
    assert gold["sector_signals"] is sd.UNAVAILABLE
    assert gold["market_regime"] == "TRENDING_UP"  # other tables unaffected


def test_missing_table_is_skipped_as_noted_not_halting():
    row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    gold = sd.digest_all(_source_missing_sector_signals(regime="TRENDING_UP", stock_signals=[row]), "2026-09-10")
    pg = sd.digest_all(_source(regime="TRENDING_UP", stock_signals=[row],
                                sector_signals=[("CEMENT", 1, 5.0, 10.0)]), "2026-09-10")
    halting, noted = sd.compare_digests(gold, pg)
    assert halting == []  # NOT a giant one-sided sector_signals diff
    assert any(n["table"] == "sector_signals" and n["kind"] == "unavailable" for n in noted)


def test_missing_sector_signals_alone_does_not_make_the_session_incomplete():
    row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    gold = _source_missing_sector_signals(regime="TRENDING_UP", stock_signals=[row])
    pg = _source(regime="TRENDING_UP", stock_signals=[row])
    result = sd.compare_session(gold, pg, "2026-09-10")
    assert result["verdict"] == sd.VERDICT_CLEAN


# ------------------------------------------------------------ session-level

def test_compare_session_incomplete_when_one_side_empty():
    gold = _source(regime="TRENDING_UP", stock_signals=[("HBL", 1, 1.0, 5.0, 1, 300_000, 2)])
    pg = _source()  # nothing for this date yet
    result = sd.compare_session(gold, pg, "2026-09-10")
    assert result["verdict"] == sd.VERDICT_INCOMPLETE
    assert result["reason"] == "pg"


def test_compare_session_clean_when_no_halting_diffs():
    row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    gold = _source(regime="TRENDING_UP", stock_signals=[row])
    pg = _source(regime="TRENDING_UP", stock_signals=[row])
    result = sd.compare_session(gold, pg, "2026-09-10")
    assert result["verdict"] == sd.VERDICT_CLEAN


def test_compare_session_disagree_when_halting_diff_present():
    gold = _source(regime="TRENDING_UP", stock_signals=[("HBL", 1, 1.0, 5.0, 1, 300_000, 2)])
    pg = _source(regime="TRENDING_UP", stock_signals=[("HBL", 0, 1.0, 5.0, 1, 300_000, 2)])
    result = sd.compare_session(gold, pg, "2026-09-10")
    assert result["verdict"] == sd.VERDICT_DISAGREE
    assert len(result["halting"]) == 1


def test_default_session_date_picks_the_earlier_of_both_max_dates(tmp_path):
    import duckdb
    gcon = duckdb.connect(":memory:")
    gcon.execute("CREATE TABLE market_regime (date TEXT)")
    gcon.execute("INSERT INTO market_regime VALUES ('2026-09-10')")
    gold = sd._Source(gcon, "duckdb", "gold")

    pcon = sqlite3.connect(":memory:")
    pcon.execute("CREATE TABLE market_regime (date TEXT)")
    pcon.execute("INSERT INTO market_regime VALUES ('2026-09-09')")
    pg = sd._Source(pcon, "sqlite", "pg")

    assert sd._default_session_date(gold, pg) == "2026-09-09"


# ---------------------------------------------------------------- lineage

@pytest.fixture
def archive_root(tmp_path):
    return tmp_path / "KIRAN_ARCHIVE"


def _clean(date):
    return {"session_date": date, "verdict": sd.VERDICT_CLEAN, "halting": [], "noted": []}


def _disagree(date):
    return {"session_date": date, "verdict": sd.VERDICT_DISAGREE,
            "halting": [{"table": "stock_signals", "kind": "bos_flag", "symbols": ["HBL"]}], "noted": []}


def _incomplete(date):
    return {"session_date": date, "verdict": sd.VERDICT_INCOMPLETE, "halting": [], "noted": [], "reason": "pg"}


def test_record_session_streak_increments_on_clean(archive_root):
    r1 = sd.record_session(archive_root, _clean("2026-09-08"))
    r2 = sd.record_session(archive_root, _clean("2026-09-09"))
    r3 = sd.record_session(archive_root, _clean("2026-09-10"))
    assert (r1["clean_streak"], r2["clean_streak"], r3["clean_streak"]) == (1, 2, 3)


def test_record_session_streak_resets_on_disagree(archive_root):
    sd.record_session(archive_root, _clean("2026-09-08"))
    sd.record_session(archive_root, _clean("2026-09-09"))
    sd.record_session(archive_root, _disagree("2026-09-10"))
    result = sd.record_session(archive_root, _clean("2026-09-11"))
    assert result["clean_streak"] == 1


def test_record_session_incomplete_does_not_reset_the_streak(archive_root):
    sd.record_session(archive_root, _clean("2026-09-08"))
    sd.record_session(archive_root, _clean("2026-09-09"))
    sd.record_session(archive_root, _incomplete("2026-09-10"))
    result = sd.record_session(archive_root, _clean("2026-09-11"))
    assert result["clean_streak"] == 3


def test_record_session_rerun_same_date_replaces_not_duplicates(archive_root):
    sd.record_session(archive_root, _disagree("2026-09-10"))
    result = sd.record_session(archive_root, _clean("2026-09-10"))
    assert result["clean_streak"] == 1
    st = sd.status(archive_root)
    assert len(st["sessions"]) == 1
    assert st["sessions"][0]["verdict"] == sd.VERDICT_CLEAN


def test_status_with_no_prior_runs(archive_root):
    assert sd.status(archive_root) == {"streak": 0, "sessions": []}


def test_status_reports_recent_sessions_newest_first(archive_root):
    sd.record_session(archive_root, _clean("2026-09-08"))
    sd.record_session(archive_root, _clean("2026-09-09"))
    st = sd.status(archive_root)
    assert st["streak"] == 2
    assert [s["session_date"] for s in st["sessions"]] == ["2026-09-09", "2026-09-08"]


# --------------------------------------------------------------- run_once

def test_run_once_orchestrates_and_records(tmp_path, monkeypatch):
    row = ("HBL", 1, 1.0, 5.0, 1, 300_000, 2)
    gold_src = _source(regime="TRENDING_UP", stock_signals=[row])
    pg_src = _source(regime="TRENDING_UP", stock_signals=[row])
    monkeypatch.setattr(sd, "open_gold", lambda store_root: gold_src)
    monkeypatch.setattr(sd, "open_pg", lambda pg_url=None: pg_src)

    archive_root = tmp_path / "KIRAN_ARCHIVE"
    result = sd.run_once(tmp_path / "psx_serving", archive_root, session_date="2026-09-10")

    assert result["verdict"] == sd.VERDICT_CLEAN
    assert result["clean_streak"] == 1
    assert sd.status(archive_root)["streak"] == 1


def test_run_once_alerts_on_disagree(tmp_path, monkeypatch):
    gold_src = _source(regime="TRENDING_UP", stock_signals=[("HBL", 1, 1.0, 5.0, 1, 300_000, 2)])
    pg_src = _source(regime="TRENDING_UP", stock_signals=[("HBL", 0, 1.0, 5.0, 1, 300_000, 2)])
    monkeypatch.setattr(sd, "open_gold", lambda store_root: gold_src)
    monkeypatch.setattr(sd, "open_pg", lambda pg_url=None: pg_src)
    alerts = []
    monkeypatch.setattr(sd, "_alert_disagree", lambda result: alerts.append(result))

    result = sd.run_once(tmp_path / "psx_serving", tmp_path / "KIRAN_ARCHIVE", session_date="2026-09-10")

    assert result["verdict"] == sd.VERDICT_DISAGREE
    assert len(alerts) == 1


def test_run_once_closes_sources_even_on_comparison_error(tmp_path, monkeypatch):
    gold_src = _source()
    pg_src = _source()
    closed = []
    monkeypatch.setattr(gold_src, "close", lambda: closed.append("gold"))
    monkeypatch.setattr(pg_src, "close", lambda: closed.append("pg"))
    monkeypatch.setattr(sd, "open_gold", lambda store_root: gold_src)
    monkeypatch.setattr(sd, "open_pg", lambda pg_url=None: pg_src)
    monkeypatch.setattr(sd, "compare_session", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        sd.run_once(tmp_path / "psx_serving", tmp_path / "KIRAN_ARCHIVE", session_date="2026-09-10")

    assert set(closed) == {"gold", "pg"}


def test_main_status_flag(tmp_path, monkeypatch, capsys):
    archive_root = tmp_path / "KIRAN_ARCHIVE"
    sd.record_session(archive_root, _clean("2026-09-10"))
    rc = sd.main(["--status", "--archive-root", str(archive_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"streak": 1' in out


def test_main_returns_nonzero_when_verdict_is_disagree(tmp_path, monkeypatch):
    gold_src = _source(regime="TRENDING_UP", stock_signals=[("HBL", 1, 1.0, 5.0, 1, 300_000, 2)])
    pg_src = _source(regime="TRENDING_UP", stock_signals=[("HBL", 0, 1.0, 5.0, 1, 300_000, 2)])
    monkeypatch.setattr(sd, "open_gold", lambda store_root: gold_src)
    monkeypatch.setattr(sd, "open_pg", lambda pg_url=None: pg_src)
    monkeypatch.setattr(sd, "_alert_disagree", lambda result: None)

    rc = sd.main(["--store-root", str(tmp_path / "psx_serving"),
                  "--archive-root", str(tmp_path / "KIRAN_ARCHIVE"), "--date", "2026-09-10"])
    assert rc == 1
