"""archive/financials_pipeline.py -- Bronze/Silver/Gold orchestration, fully
decoupled from the main Kiran pipeline. Mirrors tests/test_ca_v2_prototype.py's
conventions (tmp_path + monkeypatch'd ARCHIVE_ROOT, a synthetic source fixture,
real-behavior assertions rather than just "it runs").
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import duckdb
import pytest

from archive import bronze_ingest, financials_pipeline as fpl


def _row_html(symbol: str, date_text: str, ann: str) -> str:
    return (
        '<tr class="data-tr">'
        f'<td class="plain">X Ltd<br />({symbol})</td>'
        f'<td class="plain">{date_text}</td>'
        f'<td class="plain">{ann}</td>'
        '</tr>'
    )


def _write_ledger(path: Path, symbols: list[str]) -> None:
    con = sqlite3.connect(path)
    cols = ["announce_date", "bonus_pct", "book_closure_from", "book_closure_to",
           "classification", "close_before", "dedup_merged_from", "div_per_share",
           "dividend_pct_face_value", "era", "event_types", "ex_date", "expected_drop",
           "factor_basis", "index_neutral_move_pct", "is_compound", "matched_ex_date",
           "n_components", "note", "observed_drop", "observed_ratio", "price_factor",
           "rights_pct", "rights_price", "source", "symbol"]
    con.execute(f"CREATE TABLE ca_ledger ({', '.join(c + ' TEXT' for c in cols)})")
    for i, sym in enumerate(symbols):
        row = {c: None for c in cols}
        row.update({
            "symbol": sym, "announce_date": "2020-01-15", "event_types": "CASH_DIVIDEND",
            "classification": "CONFIRMED", "is_compound": "0", "n_components": "1",
            "dividend_pct_face_value": str(10.0 + i), "div_per_share": str(1.0 + i),
            "source": "ksestocks",
        })
        con.execute(f"INSERT INTO ca_ledger ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [row[c] for c in cols])
    con.execute("CREATE TABLE meta (k TEXT, v TEXT)")
    con.executemany("INSERT INTO meta VALUES (?,?)",
                    [("built_at", "2026-09-18T00:00:00"), ("n_events", str(len(symbols)))])
    con.commit()
    con.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(fpl, "ARCHIVE_ROOT", root)

    cache_dir = tmp_path / "announcements_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "AAA.html").write_text(
        _row_html("AAA", "January 1st, 2020", "EPS = 1.00 | FOR THE QUARTER ENDED 31/12/2019"),
        encoding="utf-8")
    (cache_dir / "BBB.html").write_text(
        _row_html("BBB", "February 1st, 2020", "EPS = 2.00"), encoding="utf-8")

    ledger_db = tmp_path / "full_ca_ledger.sqlite"
    _write_ledger(ledger_db, ["AAA", "BBB"])

    store_root = root / "financials_archive"
    return store_root, cache_dir, ledger_db


# --------------------------------------------------------------------- basic

def test_backfill_builds_both_tables(env):
    store_root, cache_dir, ledger_db = env
    res = fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    assert res["outcome"] == "built"
    assert res["symbols_checked"] == 2
    assert res["symbols_changed"] == 2
    assert res["stock_announcement_rows_added"] == 2
    assert res["corporate_actions"]["rows"] == 2

    con = duckdb.connect(str(store_root / "financials_serving.duckdb"), read_only=True)
    try:
        symbols = {r[0] for r in con.execute("SELECT symbol FROM stock_announcements").fetchall()}
        assert symbols == {"AAA", "BBB"}
        aaa = con.execute("SELECT eps_unspecified, fiscal_period_ended FROM stock_announcements "
                          "WHERE symbol = 'AAA'").fetchone()
        assert aaa == (1.00, "2019-12-31")
        ca_symbols = {r[0] for r in con.execute("SELECT symbol FROM corporate_actions").fetchall()}
        assert ca_symbols == {"AAA", "BBB"}
    finally:
        con.close()

    assert not (store_root / "financials_serving_staging.duckdb").exists()


def test_backfill_second_run_unchanged_reprocesses_nothing(env):
    store_root, cache_dir, ledger_db = env
    fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    res2 = fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    assert res2["symbols_changed"] == 0
    assert res2["stock_announcement_rows_added"] == 0
    # data from the first run must still be there -- a zero-change run must not wipe anything
    con = duckdb.connect(str(store_root / "financials_serving.duckdb"), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM stock_announcements").fetchone()[0] == 2
    finally:
        con.close()


def test_only_changed_symbol_is_reprocessed(env):
    """AAA's HTML gains a second announcement; BBB is untouched. Only AAA
    should be reparsed -- BBB's existing row must survive unmodified."""
    store_root, cache_dir, ledger_db = env
    fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)

    (cache_dir / "AAA.html").write_text(
        _row_html("AAA", "January 1st, 2020", "EPS = 1.00 | FOR THE QUARTER ENDED 31/12/2019")
        + _row_html("AAA", "April 1st, 2020", "EPS = 1.50"),
        encoding="utf-8")

    res2 = fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    assert res2["symbols_changed"] == 1
    assert res2["stock_announcement_rows_added"] == 2  # AAA's full re-parsed set (2 rows)

    con = duckdb.connect(str(store_root / "financials_serving.duckdb"), read_only=True)
    try:
        aaa_rows = con.execute(
            "SELECT announce_date, eps_unspecified FROM stock_announcements "
            "WHERE symbol = 'AAA' ORDER BY row_index").fetchall()
        assert aaa_rows == [("2020-01-01", 1.00), ("2020-04-01", 1.50)]
        bbb_rows = con.execute(
            "SELECT count(*) FROM stock_announcements WHERE symbol = 'BBB'").fetchone()[0]
        assert bbb_rows == 1  # untouched
    finally:
        con.close()


# ---------------------------------------------------------------- isolation

def test_decoupled_from_main_pipeline_store(env):
    store_root, cache_dir, ledger_db = env
    fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    root = store_root.parent
    assert not (root / "psx_serving").exists()
    assert not (root / "prices_archive").exists()
    assert not (root / "shadow_diff.duckdb").exists()


def test_missing_ledger_raises_clear_error(env):
    store_root, cache_dir, _ledger_db = env
    with pytest.raises(SystemExit, match="not found"):
        fpl.run("backfill", store_root, cache_dir=cache_dir,
               ledger_db=cache_dir / "does_not_exist.sqlite")


def test_missing_cache_dir_raises_clear_error(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(fpl, "ARCHIVE_ROOT", root)
    with pytest.raises(SystemExit, match="not found"):
        fpl.run("backfill", root / "financials_archive", cache_dir=tmp_path / "nope")


# ------------------------------------------------------------ crash safety

def test_crash_before_promote_does_not_lose_the_change(env):
    """Simulates a crash: Bronze captured a change, but the previous serving
    DB (with its OLD promoted_bronze_hashes) never got swapped out. A re-run
    must still detect the symbol as changed, not silently skip it because
    Bronze's on-disk file already reflects the new content."""
    store_root, cache_dir, ledger_db = env
    fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)

    # Change AAA's content (as if a real fetch happened) and manually write
    # the Bronze artifact directly, bypassing run() -- emulating "the crash
    # happened after Bronze capture but before the atomic promote".
    from archive.financials_pipeline import Store
    store = Store(store_root)
    new_html = _row_html("AAA", "January 1st, 2020", "EPS = 9.99")
    store.bronze_dir.mkdir(parents=True, exist_ok=True)
    crash_date = dt.date.today().isoformat()
    (store.bronze_dir / f"date={crash_date}").mkdir(parents=True, exist_ok=True)
    (store.bronze_dir / f"date={crash_date}" / "AAA.html").write_text(new_html, encoding="utf-8")
    # store.db (the last PROMOTED state) still has the OLD promoted_bronze_hashes --
    # exactly the "crashed before promote" condition.

    promoted_before = fpl._read_promoted_hashes(store)
    # sanity: the on-disk Bronze hash now differs from what was last promoted
    on_disk_hash = fpl._sha256_text(new_html)
    assert promoted_before.get("AAA") != on_disk_hash

    # Now update the cache_dir too (what a real next run's fetch/read would see)
    # and run again -- AAA must be picked up.
    (cache_dir / "AAA.html").write_text(new_html, encoding="utf-8")
    res = fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    assert res["symbols_changed"] >= 1  # AAA must be among the changed set
    con = duckdb.connect(str(store_root / "financials_serving.duckdb"), read_only=True)
    try:
        val = con.execute(
            "SELECT eps_unspecified FROM stock_announcements WHERE symbol='AAA'").fetchone()[0]
        assert val == 9.99
    finally:
        con.close()


# ------------------------------------------------------------------ daily mode

def test_daily_mode_uses_injected_fetch_never_touches_network(env):
    store_root, cache_dir, ledger_db = env
    calls = []

    def fake_fetch(symbol):
        calls.append(symbol)
        return _row_html(symbol, "March 1st, 2021", "EPS = 5.00")

    res = fpl.run("daily", store_root, cache_dir=cache_dir, ledger_db=ledger_db,
                 fetch_fn=fake_fetch)
    assert sorted(calls) == ["AAA", "BBB"]
    assert res["symbols_changed"] == 2
    assert res["stock_announcement_rows_added"] == 2


def test_daily_mode_fetch_failure_does_not_crash_the_sweep(env):
    store_root, cache_dir, ledger_db = env

    def flaky_fetch(symbol):
        if symbol == "AAA":
            raise RuntimeError("simulated network failure")
        return _row_html(symbol, "March 1st, 2021", "EPS = 5.00")

    res = fpl.run("daily", store_root, cache_dir=cache_dir, ledger_db=ledger_db,
                 fetch_fn=flaky_fetch)
    assert res["symbols_fetch_failed"] == 1
    assert "AAA" in res["fetch_failures"]
    assert res["symbols_changed"] == 1  # BBB still got through


# ------------------------------------------------------- corporate_actions

def test_corporate_actions_typed_conformance(env):
    store_root, cache_dir, ledger_db = env
    fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    con = duckdb.connect(str(store_root / "financials_serving.duckdb"), read_only=True)
    try:
        row = con.execute(
            "SELECT is_compound, n_components, dividend_pct_face_value FROM corporate_actions "
            "WHERE symbol = 'AAA'").fetchone()
        assert row[0] is False  # cast from TEXT "0"
        assert row[1] == 1
        assert row[2] == 10.0
    finally:
        con.close()


def test_build_log_and_ingest_log_are_written(env):
    store_root, cache_dir, ledger_db = env
    fpl.run("backfill", store_root, cache_dir=cache_dir, ledger_db=ledger_db)
    store = fpl.Store(store_root)
    assert store.build_log.exists()
    assert store.ingest_log.exists()
    entries = [json.loads(l) for l in store.ingest_log.read_text().splitlines()]
    assert {e["symbol"] for e in entries} == {"AAA", "BBB"}
