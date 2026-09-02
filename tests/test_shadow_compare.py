"""TR-01 shadow-mode Component C -- shadow_compare.py (SHADOWMODE_SPEC_DRAFT.md
§7 / ledger §112).

Fully isolated: three SQLite DBs stand in for the authoritative Postgres,
`psx_data.db` (local compute) and `psx_archive.db` (pull-sync mirror). The
"Postgres" one is wrapped in a compact `%s`->`?` shim. No network -- the
ntfy push is an injected spy.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import shadow_compare as sc  # noqa: E402


class _PgCur:
    def __init__(self, c): self._c = c
    def execute(self, sql, params=()): self._c.execute(sql.replace("%s", "?"), params); return self
    def fetchall(self): return self._c.fetchall()
    def fetchone(self): return self._c.fetchone()
    def close(self): self._c.close()


class _PgConn:
    def __init__(self, path): self._conn = sqlite3.connect(path)
    def cursor(self): return _PgCur(self._conn.cursor())
    def rollback(self): self._conn.rollback()
    def close(self): self._conn.close()


_SCHEMA = {
    "current_publication": "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, promoted_at TEXT, source_as_of TEXT, promoted INTEGER, coherence TEXT",
    "prices": "symbol TEXT, date TEXT, close REAL",
    "prices_adjusted": "symbol TEXT, date TEXT, close REAL",
    "stock_signals": "symbol TEXT, date TEXT, bos_flag INTEGER, pivot_distance_pct REAL, base_tightness REAL, stage2_bull INTEGER, avg_vol_10d REAL, sector_rs_rank INTEGER",
    "sector_signals": "sector TEXT, date TEXT, rs_rank INTEGER, composite_score REAL, breadth_score REAL",
    "boring_signals": "symbol TEXT, signal_date TEXT, strategy_confirmed INTEGER, status TEXT",
    "setup_log": "symbol TEXT, setup_date TEXT, setup_type TEXT",
    "market_regime": "date TEXT, regime TEXT",
}

SESSION = "2026-09-02"


def _make_db(path):
    con = sqlite3.connect(path)
    for name, cols in _SCHEMA.items():
        con.execute(f"CREATE TABLE {name} ({cols})")
    con.commit()
    con.close()


def _seed_signal_tables(path, session=SESSION):
    con = sqlite3.connect(path)
    try:
        for i in range(3):
            con.execute("INSERT INTO prices VALUES (?, ?, ?)", (f"SYM{i}", session, 100.0 + i))
            con.execute("INSERT INTO prices_adjusted VALUES (?, ?, ?)", (f"SYM{i}", session, 100.0 + i))
            con.execute("INSERT INTO stock_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (f"SYM{i}", session, i % 2, 2.0, 5.0, 1, 500000.0, i + 1))
            con.execute("INSERT INTO sector_signals VALUES (?, ?, ?, ?, ?)",
                        (f"SEC{i}", session, i + 1, 1.0, 1.0))
        con.execute("INSERT INTO boring_signals VALUES (?, ?, ?, ?)", ("PRL", session, 1, "Pending"))
        con.execute("INSERT INTO setup_log VALUES (?, ?, ?)", ("SYM0", session, "BREAKOUT"))
        con.execute("INSERT INTO market_regime VALUES (?, ?)", (session, "TRENDING_UP"))
        con.commit()
    finally:
        con.close()


@pytest.fixture
def dbs(tmp_path):
    auth, local, archive = (str(tmp_path / n) for n in ("pg.db", "psx_data.db", "psx_archive.db"))
    for p in (auth, local, archive):
        _make_db(p)
    # authoritative gets a promoted+coherent publication row
    con = sqlite3.connect(auth)
    con.execute("INSERT INTO current_publication (run_id, promoted_at, source_as_of, promoted, coherence) "
                "VALUES (?, ?, ?, ?, ?)", ("run-x", SESSION + "T20:00Z", SESSION, 1, "COHERENT"))
    con.commit()
    con.close()
    for p in (auth, local, archive):
        _seed_signal_tables(p)
    return dict(auth=auth, local=local, archive=archive)


def _run(dbs, floor=10, notify=None):
    conn = _PgConn(dbs["auth"])
    spy = notify if notify is not None else _Spy()
    try:
        out = sc.run_compare(auth_conn=conn, local_path=dbs["local"],
                             archive_path=dbs["archive"], floor=floor, notify=spy)
    finally:
        conn.close()
    return out, spy


class _Spy:
    def __init__(self): self.calls = []
    def __call__(self, title, message): self.calls.append((title, message))


def _mutate(path, sql, params=()):
    con = sqlite3.connect(path)
    con.execute(sql, params)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
def test_identical_data_is_clean_and_increments(dbs):
    out, spy = _run(dbs)
    assert out["verdict"] == sc.VERDICT_CLEAN
    assert out["clean_session_number"] == 1
    assert spy.calls == []


def test_boring_signal_existence_disagreement_halts(dbs):
    _mutate(dbs["local"], "DELETE FROM boring_signals WHERE symbol = 'PRL'")
    out, spy = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert out["clean_session_number"] == 0
    assert any(h["table"] == "boring_signals" and h["kind"] == "existence"
               for h in out["halting"])
    assert len(spy.calls) == 1


def test_close_within_tolerance_is_clean(dbs):
    _mutate(dbs["local"], "UPDATE prices SET close = 100.0005 WHERE symbol = 'SYM0'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_CLEAN


def test_close_outside_tolerance_halts(dbs):
    _mutate(dbs["local"], "UPDATE prices SET close = 142.0 WHERE symbol = 'SYM0'")
    out, spy = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert any(h["kind"] == "close_outside_tolerance" for h in out["halting"])


def test_bos_flag_disagreement_halts(dbs):
    _mutate(dbs["local"], "UPDATE stock_signals SET bos_flag = 1 WHERE symbol = 'SYM0'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert any(h["table"] == "stock_signals" and h["kind"] == "bos_flag"
               for h in out["halting"])


def test_setup_log_membership_disagreement_halts(dbs):
    _mutate(dbs["local"], "INSERT INTO setup_log VALUES ('SYM2', ?, 'PRE_BREAKOUT')", (SESSION,))
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert any(h["table"] == "setup_log" for h in out["halting"])


def test_prices_coverage_disagreement_halts(dbs):
    _mutate(dbs["local"], "DELETE FROM prices WHERE symbol = 'SYM2'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert any(h["table"] == "prices" and h["kind"] == "coverage" for h in out["halting"])


def test_boring_strategy_confirmed_disagreement_halts(dbs):
    _mutate(dbs["local"], "UPDATE boring_signals SET strategy_confirmed = 0 WHERE symbol = 'PRL'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert any(h["kind"] == "strategy_confirmed" for h in out["halting"])


def test_market_regime_label_difference_is_noted_not_halt(dbs):
    _mutate(dbs["local"], "UPDATE market_regime SET regime = 'RANGING' WHERE date = ?", (SESSION,))
    out, spy = _run(dbs)
    assert out["verdict"] == sc.VERDICT_CLEAN
    assert any(n["table"] == "market_regime" for n in out["noted"])
    assert spy.calls == []


def test_sector_signal_flip_is_noted_not_halt(dbs):
    _mutate(dbs["local"], "UPDATE sector_signals SET composite_score = -1.0 WHERE sector = 'SEC0'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_CLEAN
    assert any(n["table"] == "sector_signals" for n in out["noted"])


def test_boring_status_flip_is_noted_not_halt(dbs):
    _mutate(dbs["local"], "UPDATE boring_signals SET status = 'Target' WHERE symbol = 'PRL'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_CLEAN
    assert any(n.get("field") == "status" for n in out["noted"])


def test_archive_mismatch_is_incomplete_and_alerts(dbs):
    _mutate(dbs["archive"], "UPDATE boring_signals SET strategy_confirmed = 0 WHERE symbol = 'PRL'")
    out, spy = _run(dbs)
    assert out["verdict"] == sc.VERDICT_INCOMPLETE
    assert "Component B" in out["detail"]
    assert len(spy.calls) == 1


def test_local_behind_is_incomplete_not_disagree(dbs):
    for t in ("prices", "prices_adjusted", "stock_signals", "sector_signals",
              "boring_signals", "setup_log", "market_regime"):
        _mutate(dbs["local"], f"DELETE FROM {t}")
    out, spy = _run(dbs)
    assert out["verdict"] == sc.VERDICT_INCOMPLETE
    assert out["clean_session_number"] == 0  # prev was 0, carried
    assert spy.calls == []


def test_authoritative_unreachable_is_incomplete_no_crash(dbs):
    class _Boom:
        def cursor(self): raise RuntimeError("connection refused")
        def rollback(self): pass
        def close(self): pass
    out = sc.run_compare(auth_conn=_Boom(), local_path=dbs["local"],
                         archive_path=dbs["archive"], notify=_Spy())
    assert out["verdict"] == sc.VERDICT_INCOMPLETE
    assert out["status"] == "authoritative unreachable"


def test_no_eligible_session(dbs):
    _mutate(dbs["auth"], "UPDATE current_publication SET promoted = 0")
    out, _ = _run(dbs)
    assert out["status"] == "no eligible session"


def test_non_coherent_session_is_not_eligible(dbs):
    _mutate(dbs["auth"], "UPDATE current_publication SET coherence = 'UNKNOWN'")
    out, _ = _run(dbs)
    assert out["status"] == "no eligible session"


def test_already_compared_clean_is_skipped(dbs):
    _run(dbs)
    out2, spy2 = _run(dbs)
    assert out2["status"] == "already compared"
    assert out2["verdict"] == sc.VERDICT_CLEAN


def test_incomplete_is_retried(dbs):
    for t in _SCHEMA:
        if t != "current_publication":
            _mutate(dbs["local"], f"DELETE FROM {t}")
    out1, _ = _run(dbs)
    assert out1["verdict"] == sc.VERDICT_INCOMPLETE
    # local catches up
    _seed_signal_tables(dbs["local"])
    out2, _ = _run(dbs)
    assert out2["status"] == "compared"
    assert out2["verdict"] == sc.VERDICT_CLEAN


def test_counter_resets_on_disagree_then_restarts(dbs, tmp_path):
    """A DISAGREE at streak 7 -> 0, then a subsequent CLEAN -> 1 (§4.6)."""
    arc = sqlite3.connect(dbs["archive"])
    arc.execute(sc._SHADOW_DDL)
    for i, d in enumerate(["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
                           "2026-08-28", "2026-08-29", "2026-09-01"], start=1):
        arc.execute("INSERT INTO shadow_comparison VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (d, d + "T20:00Z", sc.VERDICT_CLEAN, i, "[]", "[]", "clean"))
    arc.commit()
    arc.close()

    _mutate(dbs["local"], "DELETE FROM boring_signals WHERE symbol = 'PRL'")
    out, _ = _run(dbs)
    assert out["verdict"] == sc.VERDICT_DISAGREE
    assert out["clean_session_number"] == 0

    # a later session, now clean
    _mutate(dbs["local"], "INSERT INTO boring_signals VALUES ('PRL', '2026-09-03', 1, 'Pending')")
    _mutate(dbs["auth"], "INSERT INTO boring_signals VALUES ('PRL', '2026-09-03', 1, 'Pending')")
    _mutate(dbs["archive"], "INSERT INTO boring_signals VALUES ('PRL', '2026-09-03', 1, 'Pending')")
    for p in (dbs["auth"], dbs["local"], dbs["archive"]):
        for i in range(3):
            _mutate(p, "INSERT INTO prices VALUES (?, '2026-09-03', ?)", (f"SYM{i}", 100.0 + i))
            _mutate(p, "INSERT INTO prices_adjusted VALUES (?, '2026-09-03', ?)", (f"SYM{i}", 100.0 + i))
            _mutate(p, "INSERT INTO stock_signals VALUES (?, '2026-09-03', ?, 2.0, 5.0, 1, 500000.0, ?)", (f"SYM{i}", i % 2, i + 1))
            _mutate(p, "INSERT INTO sector_signals VALUES (?, '2026-09-03', ?, 1.0, 1.0)", (f"SEC{i}", i + 1))
        _mutate(p, "INSERT INTO setup_log VALUES ('SYM0', '2026-09-03', 'BREAKOUT')")
        _mutate(p, "INSERT INTO market_regime VALUES ('2026-09-03', 'TRENDING_UP')")
    _mutate(dbs["auth"], "INSERT INTO current_publication (run_id, promoted_at, source_as_of, promoted, coherence) "
                         "VALUES ('run-y', '2026-09-03T20:00Z', '2026-09-03', 1, 'COHERENT')")
    out2, _ = _run(dbs)
    assert out2["verdict"] == sc.VERDICT_CLEAN
    assert out2["clean_session_number"] == 1


def test_shadow_status_reports_pass_at_floor(dbs):
    arc = sqlite3.connect(dbs["archive"])
    arc.execute(sc._SHADOW_DDL)
    for i in range(1, 11):
        d = f"2026-08-{i:02d}"
        arc.execute("INSERT INTO shadow_comparison VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (d, d, sc.VERDICT_CLEAN, i, "[]", "[]", "clean"))
    arc.commit()
    arc.close()
    st = sc.shadow_status(dbs["archive"], floor=10)
    assert st["best_streak"] == 10
    assert st["shadow_passes"] is True
