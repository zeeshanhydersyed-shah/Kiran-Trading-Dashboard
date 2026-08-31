"""TR-01 Phase 1d -- SQLite <-> Postgres parity for `boring_signals`.

Trust Register §34.9 item 5 / §35.8 item 4 / §40.7: *"an integration test
asserting SQLite/Postgres rs_60/rs_60_decile agreement over a shared,
gap-free date range -- would have caught §35.1 before it reached
production."*

§35.1's bug: `_rs60_and_liquidity_asof()` walks a **positional** 60-row
lookback, not a calendar-date one. Postgres `prices_adjusted` was missing
every row for 2026-07-07 (a table-wide gap SQLite did not have), so the
60-position window landed on a different calendar date for every symbol
whose window straddled it -- `close_then`, and therefore `rs_60` and
sometimes `rs_60_decile`, diverged between backends. Nothing tested for it.

`_rs60_and_liquidity_asof` / `_breakout_fires` / the qcut decile block are
backend-agnostic -- they take plain dicts. Divergence can only come from
(a) the per-backend loaders (`_load_price_history` vs `_load_price_history_pg`,
etc.) handing the shared code different data from the same source, or
(b) the hand-duplicated `_scan_boring_breakouts_{sqlite,pg}` glue drifting
(§34.9 item 7). This module pins both.

The Postgres path is exercised against a real SQLite database through a
compact RealDictCursor-emulating shim (`_PgLikeCursor`) -- no live Supabase,
no network. The shim translates only the SQL these functions actually issue.
psycopg2's NUMERIC->Decimal / DATE->date decoding (which the `_pg` loaders
already normalise away with `CAST(... AS DOUBLE PRECISION)` / `::text`) is
covered directly by test_boring_signals_pg.py; this module tests the LOGIC
parity given normalised inputs.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import boring_signals as bs  # noqa: E402
import database_pg  # noqa: E402


# ---------------------------------------------------------------------------
# SQLite-as-Postgres shim
# ---------------------------------------------------------------------------

class _PgLikeCursor:
    """psycopg2 RealDictCursor over a real sqlite3 connection. Translates the
    (small, fixed) set of PG-isms boring_signals.py's _pg functions emit."""

    def __init__(self, sqlite_cur):
        self._c = sqlite_cur

    def execute(self, sql, params=None):
        params = list(params) if params is not None else []
        # `col = ANY(%s)` with a list param -> `col IN (?, ?, ...)`
        if "ANY(%s)" in sql and params and isinstance(params[-1], (list, tuple)):
            seq = list(params[-1])
            sql = sql.replace("= ANY(%s)", "IN (%s)" % ",".join(["%s"] * len(seq)))
            params = params[:-1] + seq
        sql = sql.replace("::text", "")
        sql = re.sub(r"DOUBLE PRECISION", "REAL", sql)
        sql = re.sub(r"\bIS TRUE\b", "= 1", sql)
        sql = re.sub(r"\bIS FALSE\b", "= 0", sql)
        sql = re.sub(r"\bNOW\(\)", "datetime('now')", sql)
        sql = re.sub(r"ON CONFLICT\s*\([^)]*\)\s*DO NOTHING", "", sql, flags=re.I)
        if re.match(r"\s*INSERT INTO", sql, flags=re.I):
            sql = re.sub(r"\bINSERT INTO\b", "INSERT OR IGNORE INTO", sql, count=1, flags=re.I)
        sql = sql.replace("%s", "?")
        self._c.execute(sql, params)
        return self

    def _dictify(self, rows):
        if self._c.description is None:
            return rows
        cols = [d[0] for d in self._c.description]
        return [dict(zip(cols, r)) for r in rows]

    def fetchall(self):
        return self._dictify(self._c.fetchall())

    def fetchone(self):
        row = self._c.fetchone()
        return self._dictify([row])[0] if row is not None else None

    @property
    def rowcount(self):
        return self._c.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _PgLikeConn:
    def __init__(self, sqlite_conn):
        self._conn = sqlite_conn

    def cursor(self, **_kw):
        return _PgLikeCursor(self._conn.cursor())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *a):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


# ---------------------------------------------------------------------------
# synthetic dataset
# ---------------------------------------------------------------------------

_SECTOR = "CEMENT"          # not in config.EXCLUDED_SECTORS
# 90 gap-free "sessions" -- >= RS_WINDOW(60) + LOOKBACK_NS max(60) + slack, so
# both the 20d and 60d Donchian definitions are evaluable on the scan date.
_DATES = ([f"2026-04-{d:02d}" for d in range(1, 31)] +
          [f"2026-05-{d:02d}" for d in range(1, 32)] +
          [f"2026-06-{d:02d}" for d in range(1, 30)])   # 30 + 31 + 29 = 90
_SCAN_I = len(_DATES) - 1


def _dataset():
    """12 symbols, 90 sessions. Each symbol grows monotonically at its own
    gentle rate (so RS_60 as of t-1 varies across the universe and a decile
    spread exists), then jumps +3.5% on the final (scan) date so a Donchian
    breakout fires for BOTH lookbacks, for every liquid symbol. Volumes
    straddle the 200k liquidity line."""
    symbols = [f"SYM{i:02d}" for i in range(12)]
    n = len(_DATES)
    price_rows = []
    for s_i, sym in enumerate(symbols):
        rate = 1.0015 + s_i * 0.0009            # SYM00 slow ... SYM11 fast
        close = 100.0 * rate ** np.arange(n)
        close[-1] = close[-2] * 1.035           # breakout day
        vol_base = 150_000 + s_i * 45_000       # SYM00..01 below 200k, rest above
        for d_i, dt in enumerate(_DATES):
            c = float(close[d_i])
            price_rows.append((sym, dt, c * 1.02, c * 0.98, c, float(vol_base + d_i)))
    kse_close = 100.0 * 1.004 ** np.arange(n)   # middle growth rate
    kse_rows = [("KSE-100", dt, float(kse_close[i])) for i, dt in enumerate(_DATES)]
    return symbols, price_rows, kse_rows


def _build_db(path, drop_date=None):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, high REAL, low REAL,
                                      close REAL, volume REAL);
        CREATE TABLE index_prices (symbol TEXT, date TEXT, close REAL);
        CREATE TABLE stock_metadata (symbol TEXT, is_active INTEGER);
        CREATE TABLE sectors (symbol TEXT, sector TEXT);
    """)
    bs.ensure_boring_signals_table(con)
    symbols, price_rows, kse_rows = _dataset()
    if drop_date is not None:
        price_rows = [r for r in price_rows if r[1] != drop_date]
    con.executemany("INSERT INTO prices_adjusted VALUES (?,?,?,?,?,?)", price_rows)
    con.executemany("INSERT INTO index_prices VALUES (?,?,?)", kse_rows)
    con.executemany("INSERT INTO stock_metadata VALUES (?,1)", [(s,) for s in symbols])
    con.executemany("INSERT INTO sectors VALUES (?,?)", [(s, _SECTOR) for s in symbols])
    con.commit()
    return con


@pytest.fixture(autouse=True)
def _no_pg_url(monkeypatch):
    monkeypatch.setattr(bs, "_PG_URL", None)


# ---------------------------------------------------------------------------
# loader parity -- identical source rows -> identical dicts
# ---------------------------------------------------------------------------

def _dicts_equal(a, b):
    if a.keys() != b.keys():
        return False
    for k in a:
        for field in ("dates", "high", "low", "close", "volume"):
            if not np.array_equal(np.asarray(a[k][field]), np.asarray(b[k][field])):
                return False
    return True


def test_load_price_history_parity_gap_free(tmp_path):
    con = _build_db(str(tmp_path / "p.db"))
    universe = bs._eligible_universe(con)
    a = bs._load_price_history(con, universe)
    b = bs._load_price_history_pg(_PgLikeCursor(con.cursor()), universe)
    assert set(a) == set(b) == universe
    assert _dicts_equal(a, b)
    for sym in a:
        for f in ("high", "low", "close", "volume"):
            assert a[sym][f].dtype == float and b[sym][f].dtype == float


def test_eligible_universe_parity(tmp_path):
    con = _build_db(str(tmp_path / "p.db"))
    assert bs._eligible_universe(con) == bs._eligible_universe_pg(_PgLikeCursor(con.cursor()))


def test_load_kse100_parity(tmp_path):
    con = _build_db(str(tmp_path / "p.db"))
    a = bs._load_kse100(con)
    b = bs._load_kse100_pg(_PgLikeCursor(con.cursor()))
    assert np.array_equal(a["dates"], b["dates"])
    assert np.array_equal(a["close"], b["close"])


# ---------------------------------------------------------------------------
# full scan parity -- identical data -> identical boring_signals rows
# ---------------------------------------------------------------------------

_CMP_COLS = ("symbol", "signal_date", "lookback_n", "rs_60", "rs_60_decile",
             "liquidity_pass", "strategy_confirmed", "breakout_level",
             "trigger_price", "target_price", "stop_price")


def _signals(con):
    cur = con.execute(
        f"SELECT {','.join(_CMP_COLS)} FROM boring_signals ORDER BY symbol, signal_date, lookback_n")
    out = []
    for row in cur.fetchall():
        d = dict(zip(_CMP_COLS, row))
        d["liquidity_pass"] = int(d["liquidity_pass"])       # bool<->int0/1 equivalence
        d["strategy_confirmed"] = int(d["strategy_confirmed"])
        for f in ("rs_60", "breakout_level", "trigger_price", "target_price", "stop_price"):
            d[f] = round(d[f], 9)
        out.append(d)
    return out


def _run_pg_scan(pg_db_path, scan_date, monkeypatch):
    con = sqlite3.connect(pg_db_path)
    monkeypatch.setattr(database_pg, "get_conn", lambda: _PgLikeConn(con))
    bs._scan_boring_breakouts_pg(scan_date)
    return con


def test_scan_parity_gap_free(tmp_path, monkeypatch):
    scan_date = _DATES[-1]
    sq = _build_db(str(tmp_path / "sqlite.db"))
    sq.close()
    monkeypatch.setattr(bs, "DB_PATH", str(tmp_path / "sqlite.db"))
    bs._scan_boring_breakouts_sqlite(scan_date)
    sqlite_rows = _signals(sqlite3.connect(str(tmp_path / "sqlite.db")))

    _build_db(str(tmp_path / "pg.db")).close()
    pg_con = _run_pg_scan(str(tmp_path / "pg.db"), scan_date, monkeypatch)
    pg_rows = _signals(pg_con)

    # the fixture must exercise the branches parity could diverge on, or the
    # test is quietly vacuous
    assert len(sqlite_rows) >= 20
    assert {r["lookback_n"] for r in sqlite_rows} == set(bs.LOOKBACK_NS)
    assert {r["liquidity_pass"] for r in sqlite_rows} == {0, 1}
    assert {r["rs_60_decile"] for r in sqlite_rows} >= {-1, 0, 9}
    assert any(r["strategy_confirmed"] == 1 for r in sqlite_rows)

    assert sqlite_rows == pg_rows


def test_scan_diverges_when_pg_history_has_a_gap(tmp_path, monkeypatch):
    """The §35.1 scenario: a table-wide gap on ONE mid-window date on the PG
    side only. The positional RS_60 window then straddles a different
    calendar span -> rs_60 must differ for at least one signal. This is the
    failure the parity test exists to make impossible to ship silently."""
    scan_date = _DATES[-1]
    # The gap must fall STRICTLY INSIDE the 60-position RS window -- i.e.
    # between close_then (t1_idx - 60 ~= 28) and close_now (t1_idx ~= 88) --
    # so PG's 60 positions span 61 real sessions and land close_then on a
    # different calendar date. A gap before close_then just shifts both ends
    # equally and cancels (that is the subtle part of §35.1).
    gap = _DATES[55]

    _build_db(str(tmp_path / "sqlite.db")).close()
    monkeypatch.setattr(bs, "DB_PATH", str(tmp_path / "sqlite.db"))
    bs._scan_boring_breakouts_sqlite(scan_date)
    sqlite_rows = {(r["symbol"], r["signal_date"], r["lookback_n"]): r["rs_60"]
                   for r in _signals(sqlite3.connect(str(tmp_path / "sqlite.db")))}

    _build_db(str(tmp_path / "pg.db"), drop_date=gap).close()
    pg_con = _run_pg_scan(str(tmp_path / "pg.db"), scan_date, monkeypatch)
    pg_rows = {(r["symbol"], r["signal_date"], r["lookback_n"]): r["rs_60"]
               for r in _signals(pg_con)}

    shared = set(sqlite_rows) & set(pg_rows)
    assert shared, "no shared signals to compare"
    assert any(sqlite_rows[k] != pg_rows[k] for k in shared), \
        "a one-day PG price gap did NOT perturb rs_60 -- the parity check is blind to §35.1"
