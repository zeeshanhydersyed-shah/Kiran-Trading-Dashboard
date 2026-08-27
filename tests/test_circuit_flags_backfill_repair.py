"""Regression tests for the 2026-08-21 prices_adjusted circuit-flags backfill
repair (docs/KIRAN_CLEANUP_AUDIT.md §47) AND the same-day follow-up causal
repair of the daily append hook itself (§49).

Background: hit_circuit_up / hit_circuit_down / thin_trading_flag have a
confirmed producer (C:\\Users\\Lenovo\\ml_feature_study\\scripts\\
compute_circuit_flags.py, §43/§45) whose formula was reproduced exactly
(zero mismatches, 1,752,550-row historical population, §45.3) before any
production write. 454 rows -- those written since 2026-08-03 by the daily
append hook, which silently defaulted these three columns to 0 -- were
identified as needing a real value and were restored, in production, under
this same producer contract (§47).

This file has three jobs:

1. Exercise the producer's exact formula (now ported into production as
   apply_price_adjustments.compute_circuit_flags/circuit_band_pct, §49) so
   both the historical-repair use case and the daily-append use case share
   one regression-tested implementation, not a scratch script.

2. Prove the causal defect §47 deliberately left open is now closed: new
   rows inserted by append_new_prices_adjusted() used to silently default
   these three columns to 0 (an explicit-but-incomplete INSERT column list
   hitting the columns' own NOT NULL DEFAULT 0). As of §49,
   append_new_prices_adjusted() computes real values for new rows using the
   same producer formula. This was previously pinned as a KNOWN_GAP test
   asserting the broken 0/0/0 behaviour was expected; per this repair's own
   test-governance requirement, that test is replaced below with a positive
   test proving the defect can no longer occur, not left asserting the old
   behaviour was acceptable.

3. Prove the specific failure mode is closed: fail-closed behaviour when the
   circuit-flag calculation itself fails, and column-name (not
   positional/SELECT *) safety in the INSERT.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import apply_price_adjustments as apa  # noqa: E402
from apply_price_adjustments import (  # noqa: E402
    append_new_prices_adjusted,
    compute_circuit_flags,
)


def _new_con_with_schema():
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE prices (symbol TEXT, date TEXT, close REAL, volume INT, "
        "high REAL, low REAL, open REAL)"
    )
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL, "
        "hit_circuit_up INTEGER NOT NULL DEFAULT 0, "
        "hit_circuit_down INTEGER NOT NULL DEFAULT 0, "
        "thin_trading_flag INTEGER NOT NULL DEFAULT 0)"
    )
    return con


# ── 1. The producer's exact formula, now the real production implementation ─
# (apply_price_adjustments.compute_circuit_flags / circuit_band_pct, ported
# verbatim from compute_circuit_flags.py -- see that module's docstring for
# the audited provenance). These two tests now exercise production code
# directly, not a test-only shadow copy.


def test_formula_matches_the_audited_production_result():
    """A controlled fixture reproducing the exact shape the real backfill
    (§47) restored: a frozen row that reaches the 10% band -> hit_circuit_up;
    a frozen row that reaches it downward -> hit_circuit_down; a frozen row
    that doesn't reach the band -> thin_trading_flag; a non-frozen row ->
    all zero, not a placeholder."""
    df = pd.DataFrame([
        # symbol, date,        close,  vol,  high,   low,    open
        ("XXX", "2026-08-04", 100.0,  1000, 100.0, 100.0, 100.0),  # prior for XXX
        ("XXX", "2026-08-05", 110.0,  1000, 110.0, 110.0, 110.0),  # +10% frozen -> hit_up
        ("XXX", "2026-08-06", 111.0,  1000, 115.0, 108.0, 112.0),  # normal day, not frozen
        ("YYY", "2026-08-04", 100.0,  1000, 100.0, 100.0, 100.0),  # prior for YYY
        ("YYY", "2026-08-05",  90.0,  1000,  90.0,  90.0,  90.0),  # -10% frozen -> hit_down
        ("ZZZ", "2026-08-04", 100.0,  1000, 100.0, 100.0, 100.0),  # prior for ZZZ
        ("ZZZ", "2026-08-05", 101.0,  1000, 101.0, 101.0, 101.0),  # frozen, band not reached -> thin
    ])
    df.columns = ["symbol", "date", "close", "volume", "high", "low", "open"]

    result = compute_circuit_flags(df)
    got = {
        (r.symbol, r.date): (r.hit_circuit_up, r.hit_circuit_down, r.thin_trading_flag)
        for r in result.itertuples()
    }
    assert got[("XXX", "2026-08-05")] == (1, 0, 0)
    assert got[("XXX", "2026-08-06")] == (0, 0, 0)   # non-frozen, correctly zero, not a placeholder
    assert got[("YYY", "2026-08-05")] == (0, 1, 0)
    assert got[("ZZZ", "2026-08-05")] == (0, 0, 1)


def test_restoration_only_touches_rows_that_actually_need_it():
    """Regression for 'accidental expansion of the repair beyond the
    intended population' (this task's own §9/§10 boundary). Given a mix of
    (a) a row already correctly zero, (b) a row needing a real value, and
    (c) a row from BEFORE the repair boundary that happens to look
    'frozen and circuit-eligible' too -- only the in-boundary, actually-wrong
    row should ever be selected for a write."""
    df = pd.DataFrame([
        ("AAA", "2026-08-01", 100.0, 1000, 100.0, 100.0, 100.0),  # before boundary -- must be excluded regardless of its own flag state
        ("AAA", "2026-08-02", 110.0, 1000, 110.0, 110.0, 110.0),  # before boundary, would compute hit_up=1 -- must NOT be in the repair set
        ("BBB", "2026-08-02", 100.0, 1000, 100.0, 100.0, 100.0),  # pre-boundary prior (out of scope itself, just establishes prior_close)
        ("BBB", "2026-08-05", 101.0, 1000, 105.0,  95.0, 101.0),  # in-boundary, NOT frozen (high!=low) -- correctly zero already
        ("CCC", "2026-08-02", 100.0, 1000, 100.0, 100.0, 100.0),  # pre-boundary prior
        ("CCC", "2026-08-06", 110.0, 1000, 110.0, 110.0, 110.0),  # in-boundary, frozen, +10% -- needs hit_up=1
    ])
    df.columns = ["symbol", "date", "close", "volume", "high", "low", "open"]

    computed = compute_circuit_flags(df)

    REPAIR_BOUNDARY = "2026-08-03"
    in_scope = computed[computed["date"] >= REPAIR_BOUNDARY]
    needs_write = in_scope[
        (in_scope["hit_circuit_up"] == 1)
        | (in_scope["hit_circuit_down"] == 1)
        | (in_scope["thin_trading_flag"] == 1)
    ]

    touched = set(zip(needs_write["symbol"], needs_write["date"]))
    assert touched == {("CCC", "2026-08-06")}, (
        f"repair scope must be exactly the one in-boundary row that needs a "
        f"value, got {touched}"
    )
    # the pre-boundary AAA row that WOULD compute hit_up=1 must never appear,
    # regardless of what the formula says about it in isolation
    assert ("AAA", "2026-08-02") not in touched


# ── 2. GAP CLOSED (§49): append_new_prices_adjusted() now computes real
#    circuit-flag values for new rows, using the confirmed producer formula,
#    instead of silently defaulting to 0/0/0. This replaces the old
#    KNOWN_GAP test, which asserted the broken behaviour was expected --
#    per this repair's test-governance requirement, that assertion is
#    inverted here into a positive proof the defect can no longer occur,
#    not left standing as documentation of acceptable brokenness.

def test_append_new_prices_adjusted_now_computes_real_circuit_flags(tmp_path):
    """Same fixture shape as the old KNOWN_GAP test (a new frozen +10% row
    that the producer formula says should be hit_circuit_up=1): the
    production append path must now produce exactly that value, matching
    the confirmed producer, not the old placeholder 0/0/0.
    """
    db = str(tmp_path / "test_psx.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE prices (symbol TEXT, date TEXT, close REAL, volume INT, "
        "high REAL, low REAL, open REAL)"
    )
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL, "
        "hit_circuit_up INTEGER NOT NULL DEFAULT 0, "
        "hit_circuit_down INTEGER NOT NULL DEFAULT 0, "
        "thin_trading_flag INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute("INSERT INTO prices_adjusted VALUES ('AAA','2026-08-01',100,1000,100,100,100,0,0,0)")
    con.execute("INSERT INTO prices VALUES ('AAA','2026-08-01',100,1000,100,100,100)")
    con.execute("INSERT INTO prices VALUES ('AAA','2026-08-02',110,1000,110,110,110)")  # +10%, frozen
    con.commit()

    append_new_prices_adjusted(con)

    row = con.execute(
        "SELECT hit_circuit_up, hit_circuit_down, thin_trading_flag "
        "FROM prices_adjusted WHERE symbol='AAA' AND date='2026-08-02'"
    ).fetchone()
    assert row == (1, 0, 0), (
        "the daily append path must compute the same value the confirmed "
        "producer formula computes for this row, not a placeholder"
    )
    con.close()


# Test 1 (task spec): given representative new price rows, the production
# append path produces exactly the same three flag values the confirmed
# producer computes independently for the same data.

def test_append_matches_producer_across_full_pipeline_and_direct_formula():
    con = _new_con_with_schema()
    seed = [
        # symbol, date,        close, vol,  high,  low,   open
        ("AAA", "2026-08-01", 100.0, 1000, 100.0, 100.0, 100.0),
        ("BBB", "2026-08-01", 100.0, 1000, 100.0, 100.0, 100.0),
        ("CCC", "2026-08-01", 100.0, 1000, 100.0, 100.0, 100.0),
        ("DDD", "2026-08-01", 100.0, 1000, 100.0, 100.0, 100.0),
    ]
    for row in seed:
        con.execute("INSERT INTO prices_adjusted VALUES (?,?,?,?,?,?,?,0,0,0)", row)
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?)", row)

    new_rows = [
        ("AAA", "2026-08-02", 110.0, 1000, 110.0, 110.0, 110.0),  # +10% frozen -> hit_up
        ("BBB", "2026-08-02",  90.0, 1000,  90.0,  90.0,  90.0),  # -10% frozen -> hit_down
        ("CCC", "2026-08-02", 101.0, 1000, 101.0, 101.0, 101.0),  # frozen, band not reached -> thin
        ("DDD", "2026-08-02", 101.0, 1200, 105.0,  98.0, 102.0),  # not frozen -> all zero
    ]
    for row in new_rows:
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?)", row)
    con.commit()

    append_new_prices_adjusted(con)

    got = dict(
        (r[0], r[1:]) for r in con.execute(
            "SELECT symbol, hit_circuit_up, hit_circuit_down, thin_trading_flag "
            "FROM prices_adjusted WHERE date='2026-08-02' ORDER BY symbol"
        )
    )

    # independently compute the expected values via the same producer
    # formula, from a plain DataFrame built directly from the fixture data
    # (not from reading prices_adjusted back) -- an arms-length check that
    # the production path and the formula agree.
    expected_df = compute_circuit_flags(pd.DataFrame(
        seed + new_rows, columns=["symbol", "date", "close", "volume", "high", "low", "open"]
    ))
    expected = {
        r.symbol: (r.hit_circuit_up, r.hit_circuit_down, r.thin_trading_flag)
        for r in expected_df[expected_df["date"] == "2026-08-02"].itertuples()
    }

    assert got == expected == {
        "AAA": (1, 0, 0),
        "BBB": (0, 1, 0),
        "CCC": (0, 0, 1),
        "DDD": (0, 0, 0),
    }
    con.close()


# Test 3 (task spec): schema/projection safety. `prices`' physical column
# order is deliberately scrambled relative to prices_adjusted's -- this
# would silently corrupt data (e.g. volume landing in the close column) if
# the INSERT ever regressed to SELECT * or any positional assumption,
# since the fix's whole point is an explicit, by-name column list.

def test_append_is_immune_to_prices_table_column_reordering():
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE prices (date TEXT, open REAL, high REAL, low REAL, "
        "close REAL, volume INT, symbol TEXT)"
    )
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL, "
        "hit_circuit_up INTEGER NOT NULL DEFAULT 0, "
        "hit_circuit_down INTEGER NOT NULL DEFAULT 0, "
        "thin_trading_flag INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute("INSERT INTO prices_adjusted VALUES ('AAA','2026-08-01',100,1000,100,100,100,0,0,0)")
    # deliberately distinctive, all-different values so any positional
    # column mixup is immediately detectable
    con.execute(
        "INSERT INTO prices (date, open, high, low, close, volume, symbol) "
        "VALUES ('2026-08-02', 111.0, 222.0, 33.0, 44.0, 5555, 'AAA')"
    )
    con.commit()

    append_new_prices_adjusted(con)

    row = con.execute(
        "SELECT close, volume, high, low, open FROM prices_adjusted "
        "WHERE symbol='AAA' AND date='2026-08-02'"
    ).fetchone()
    assert row == (44.0, 5555, 222.0, 33.0, 111.0), (
        f"column values landed in the wrong fields under a scrambled source "
        f"table layout -- SELECT * or a positional assumption was "
        f"reintroduced. Got {row}"
    )
    con.close()


# Test 4 (task spec): forced circuit-calculation failure must not commit a
# silently-incorrect row -- neither the flag columns nor the raw price row
# itself.

def test_append_rolls_back_completely_when_circuit_calc_fails(monkeypatch):
    con = _new_con_with_schema()
    con.execute("INSERT INTO prices_adjusted VALUES ('AAA','2026-08-01',100,1000,100,100,100,0,0,0)")
    con.execute("INSERT INTO prices VALUES ('AAA','2026-08-01',100,1000,100,100,100)")
    con.execute("INSERT INTO prices VALUES ('AAA','2026-08-02',110,1000,110,110,110)")
    con.commit()

    before = con.execute("SELECT COUNT(*) FROM prices_adjusted").fetchone()[0]

    def _boom(*args, **kwargs):
        raise RuntimeError("forced circuit-flag calculation failure")

    monkeypatch.setattr(apa, "compute_circuit_flags", _boom)

    with pytest.raises(RuntimeError, match="forced circuit-flag calculation failure"):
        append_new_prices_adjusted(con)

    after = con.execute("SELECT COUNT(*) FROM prices_adjusted").fetchone()[0]
    assert after == before, (
        "a failed circuit-flag calculation must not leave the raw price row "
        "committed either -- the whole append must roll back, fail closed"
    )
    assert con.execute(
        "SELECT COUNT(*) FROM prices_adjusted WHERE date='2026-08-02'"
    ).fetchone()[0] == 0
    con.close()


# Test 5 (task spec): unrelated columns retain their existing semantics --
# raw OHLCV values must be copied through exactly, unaffected by the flag
# computation being added.

def test_append_leaves_ohlcv_columns_unaffected_by_flag_computation():
    con = _new_con_with_schema()
    con.execute("INSERT INTO prices_adjusted VALUES ('AAA','2026-08-01',100,1000,100,100,100,0,0,0)")
    con.execute("INSERT INTO prices VALUES ('AAA','2026-08-01',100,1000,100,100,100)")
    con.execute("INSERT INTO prices VALUES ('AAA','2026-08-02',101.5,123456,105.25,98.75,102.0)")
    con.commit()

    append_new_prices_adjusted(con)

    row = con.execute(
        "SELECT close, volume, high, low, open FROM prices_adjusted "
        "WHERE symbol='AAA' AND date='2026-08-02'"
    ).fetchone()
    assert row == (101.5, 123456, 105.25, 98.75, 102.0)
    con.close()
