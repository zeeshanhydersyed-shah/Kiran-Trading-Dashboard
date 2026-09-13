"""Front-end track -- Gold -> JSON export (archive/export_json.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md front-end checklist): the static
site reads precomputed JSON, computes nothing on load. This module is the
missing link -- 3.3f deferred the JSON export because no consumer existed to
validate a schema against; the front end is now that consumer.
"""
from __future__ import annotations

import json
import math

import duckdb
import pytest

from archive import export_json


def _build_store(tmp_path):
    root = tmp_path / "psx_serving"
    root.mkdir()
    con = duckdb.connect(str(root / "psx_serving.duckdb"))
    con.execute("CREATE TABLE sector_signals (date TEXT, sector TEXT, rs_score_20 DOUBLE, "
                "composite_score DOUBLE, breadth_score DOUBLE, sector_stage TEXT)")
    con.execute("CREATE TABLE stock_signals (date TEXT, symbol TEXT, rs_score_20 DOUBLE, "
                "rs_rank INTEGER, bos_flag INTEGER)")
    con.execute("CREATE TABLE stock_metadata (symbol TEXT, company_name TEXT, sector TEXT)")
    con.execute("CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close DOUBLE)")

    for i, d in enumerate(["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]):
        con.execute("INSERT INTO sector_signals VALUES (?, 'CEMENT', ?, ?, ?, 'Stage 2')",
                    [d, 10.0 + i, 0.5 + i * 0.1, 40.0])
        con.execute("INSERT INTO sector_signals VALUES (?, 'BANKS', ?, ?, ?, 'Stage 4')",
                    [d, 5.0 + i, -0.2, 20.0])

    con.execute("INSERT INTO stock_signals VALUES ('2026-09-11', 'HBL', 12.5, 1, 1)")
    con.execute("INSERT INTO stock_signals VALUES ('2026-09-11', 'LUCK', 8.0, 2, 0)")
    con.execute("INSERT INTO stock_metadata VALUES ('HBL', 'Habib Bank Limited', 'BANKS')")
    con.execute("INSERT INTO stock_metadata VALUES ('LUCK', 'Lucky Cement', 'CEMENT')")
    con.execute("INSERT INTO prices_adjusted VALUES ('HBL', '2026-09-10', 100.0)")
    con.execute("INSERT INTO prices_adjusted VALUES ('HBL', '2026-09-11', 110.0)")
    con.execute("INSERT INTO prices_adjusted VALUES ('LUCK', '2026-09-11', 50.0)")  # no prior close
    con.close()
    return root


def _build_overview_store(tmp_path, n_days=400, n_symbols=6):
    """A store with enough KSE-100 + per-symbol history for a real SMA50/breadth
    computation -- a synthetic uptrend with one symbol deliberately kept flat
    below its own SMA, so breadth is provably not 0% or 100%."""
    import datetime as dt
    import math

    root = tmp_path / "psx_serving"
    root.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(root / "psx_serving.duckdb"))
    con.execute("CREATE TABLE index_prices (symbol TEXT, date TEXT, open DOUBLE, "
                "high DOUBLE, low DOUBLE, close DOUBLE)")
    con.execute("CREATE TABLE market_regime (date TEXT, regime TEXT, regime_days INTEGER, atr_pct DOUBLE)")
    con.execute("CREATE TABLE stock_metadata (symbol TEXT, company_name TEXT, sector TEXT)")
    con.execute("CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close DOUBLE)")

    start = dt.date(2025, 1, 1)
    dates = []
    d = start
    while len(dates) < n_days:
        if d.weekday() < 5:
            dates.append(d)
        d += dt.timedelta(days=1)

    symbols = [f"SYM{i}" for i in range(n_symbols)]
    for sym in symbols:
        con.execute("INSERT INTO stock_metadata VALUES (?, ?, 'TESTSECTOR')", [sym, sym])

    for i, ds in enumerate(dates):
        iso = ds.isoformat()
        kse_close = 40000 + i * 15 + 200 * math.sin(i / 20)
        con.execute("INSERT INTO index_prices VALUES ('KSE-100', ?, ?, ?, ?, ?)",
                    [iso, kse_close - 30, kse_close + 40, kse_close - 40, kse_close])
        con.execute("INSERT INTO market_regime VALUES (?, 'TRENDING_UP', ?, ?)",
                    [iso, i + 1, 1.2])
        for j, sym in enumerate(symbols):
            if j == 0:
                # deliberately flat/declining -- stays below its own rolling SMA
                px = 100.0 - i * 0.01
            else:
                px = 50.0 * (j + 1) + i * 0.05 + j * math.sin(i / 15)
            con.execute("INSERT INTO prices_adjusted VALUES (?, ?, ?)", [sym, iso, round(px, 4)])
    con.close()
    return root, dates


@pytest.fixture
def env(tmp_path):
    store_root = _build_store(tmp_path)
    archive_root = tmp_path / "KIRAN_ARCHIVE"
    out_dir = tmp_path / "web_data"
    return store_root, archive_root, out_dir


def test_export_sector_grades_shape_and_history(env):
    store_root, archive_root, out_dir = env
    payload = export_json.export_sector_grades(store_root, out_dir)

    assert payload["as_of"] == "2026-09-11"
    by_sector = {s["sector"]: s for s in payload["sectors"]}
    assert set(by_sector) == {"CEMENT", "BANKS"}
    assert by_sector["CEMENT"]["sector_stage"] == "Stage 2"
    assert by_sector["CEMENT"]["history"] == [0.5, 0.6, 0.7, 0.8]  # chronological, 4 sessions

    written = json.loads((out_dir / "sector_grades.json").read_text())
    assert written == payload


def test_export_sector_grades_history_capped_at_window(tmp_path, monkeypatch):
    store_root = _build_store(tmp_path)
    monkeypatch.setattr(export_json, "SECTOR_HISTORY_SESSIONS", 2)
    payload = export_json.export_sector_grades(store_root, tmp_path / "out")
    by_sector = {s["sector"]: s for s in payload["sectors"]}
    assert by_sector["CEMENT"]["history"] == [0.7, 0.8]  # only the last 2 sessions


def test_export_signals_joins_metadata_and_computes_change(env):
    store_root, archive_root, out_dir = env
    payload = export_json.export_signals(store_root, archive_root, out_dir)

    assert payload["as_of"] == "2026-09-11"
    by_symbol = {s["symbol"]: s for s in payload["symbols"]}
    hbl = by_symbol["HBL"]
    assert hbl["company_name"] == "Habib Bank Limited"
    assert hbl["close"] == 110.0
    assert hbl["chg_pct"] == 10.0  # (110-100)/100 * 100
    assert hbl["price_basis"] == "legacy"

    luck = by_symbol["LUCK"]
    assert luck["chg_pct"] is None  # no prior close in the fixture


def test_export_signals_sorted_by_rs_rank(env):
    store_root, archive_root, out_dir = env
    payload = export_json.export_signals(store_root, archive_root, out_dir)
    assert [s["symbol"] for s in payload["symbols"]] == ["HBL", "LUCK"]  # rs_rank 1, 2


def test_export_signals_nan_cleaned_to_null(tmp_path):
    store_root = tmp_path / "psx_serving"
    store_root.mkdir()
    con = duckdb.connect(str(store_root / "psx_serving.duckdb"))
    con.execute("CREATE TABLE stock_signals (date TEXT, symbol TEXT, rs_score_20 DOUBLE, "
                "rs_rank INTEGER, bos_flag INTEGER)")
    con.execute("CREATE TABLE stock_metadata (symbol TEXT, company_name TEXT, sector TEXT)")
    con.execute("CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close DOUBLE)")
    con.execute("INSERT INTO stock_signals VALUES ('2026-09-11', 'XYZ', 'nan'::DOUBLE, 1, 0)")
    con.close()

    payload = export_json.export_signals(store_root, tmp_path / "archive", tmp_path / "out")
    assert payload["symbols"][0]["rs_score_20"] is None
    # confirm it's actually valid JSON (NaN would break json.dumps' default encoder in strict mode)
    raw = (tmp_path / "out" / "signals.json").read_text()
    assert "NaN" not in raw
    json.loads(raw)


def test_export_meta_verified_true_when_all_gates_pass(tmp_path):
    archive_root = tmp_path / "KIRAN_ARCHIVE"
    pub_dir = archive_root / "psx_serving"
    pub_dir.mkdir(parents=True)
    con = duckdb.connect(str(pub_dir / "current_publication.duckdb"))
    con.execute("CREATE TABLE current_publication (promoted_at TIMESTAMP, run_id TEXT, "
                "code_version TEXT, bronze_max TEXT, window_from TEXT, freshness_status TEXT, "
                "completeness_status TEXT, hook_coverage_status TEXT, coherence_status TEXT, "
                "promoted BOOLEAN, withheld_reason TEXT)")
    con.execute("INSERT INTO current_publication VALUES (now(), 'run1', 'abc123', "
                "'2026-09-11', '2024-09-11', 'VERIFIED', 'COMPLETE', 'COMPLETE', 'COHERENT', "
                "true, NULL)")
    con.close()

    payload = export_json.export_meta(tmp_path / "psx_serving", archive_root, tmp_path / "out")
    assert payload["verified"] is True
    assert payload["bronze_max"] == "2026-09-11"
    assert payload["gates"]["freshness"] == "VERIFIED"


def test_export_meta_verified_false_when_a_gate_fails(tmp_path):
    archive_root = tmp_path / "KIRAN_ARCHIVE"
    pub_dir = archive_root / "psx_serving"
    pub_dir.mkdir(parents=True)
    con = duckdb.connect(str(pub_dir / "current_publication.duckdb"))
    con.execute("CREATE TABLE current_publication (promoted_at TIMESTAMP, run_id TEXT, "
                "code_version TEXT, bronze_max TEXT, window_from TEXT, freshness_status TEXT, "
                "completeness_status TEXT, hook_coverage_status TEXT, coherence_status TEXT, "
                "promoted BOOLEAN, withheld_reason TEXT)")
    con.execute("INSERT INTO current_publication VALUES (now(), 'run1', 'abc123', "
                "'2026-09-08', '2024-09-08', 'STALE', 'COMPLETE', 'COMPLETE', 'COHERENT', "
                "false, 'freshness_stale')")
    con.close()

    payload = export_json.export_meta(tmp_path / "psx_serving", archive_root, tmp_path / "out")
    assert payload["verified"] is False
    assert payload["withheld_reason"] == "freshness_stale"


def test_export_meta_no_publication_record(tmp_path):
    archive_root = tmp_path / "KIRAN_ARCHIVE"  # no psx_serving dir at all
    payload = export_json.export_meta(tmp_path / "psx_serving", archive_root, tmp_path / "out")
    assert payload["verified"] is False
    assert "no publication record" in payload["reason"]


def test_export_all_writes_all_three_files_and_returns_counts(env):
    store_root, archive_root, out_dir = env
    result = export_json.export_all(store_root, archive_root, out_dir)

    assert result["sector_count"] == 2
    assert result["symbol_count"] == 2
    for name in ("meta.json", "sector_grades.json", "signals.json"):
        assert (out_dir / name).exists()
        json.loads((out_dir / name).read_text())  # valid JSON


def test_export_overview_shape_and_regime(tmp_path):
    root, dates = _build_overview_store(tmp_path)
    payload = export_json.export_overview(root, tmp_path / "out")

    assert payload["as_of"] == dates[-1].isoformat()
    assert payload["regime"]["regime"] == "TRENDING_UP"
    assert payload["regime"]["regime_days"] == len(dates)
    assert payload["regime"]["since_date"] == dates[0].isoformat()

    kse = payload["kse100"]
    assert len(kse["dates"]) == export_json.KSE100_DISPLAY_DAYS
    assert kse["dates"][-1] == dates[-1].isoformat()
    # a real synthetic uptrend -> close should sit above its own 50-session SMA at the end
    assert kse["close"][-1] > kse["sma50"][-1]
    assert kse["pct_from_sma50"][-1] > 0

    written = json.loads((tmp_path / "out" / "overview.json").read_text())
    assert written == payload


def test_export_overview_trailing_returns_positive_for_uptrend(tmp_path):
    root, dates = _build_overview_store(tmp_path)
    payload = export_json.export_overview(root, tmp_path / "out")
    perf = payload["performance"]
    assert perf["1m"] > 0
    assert perf["3m"] > 0
    # 400 trading days ~= 560 calendar days, so a full year IS covered here
    assert perf["1y"] > 0

    # a series that does NOT reach back a year should report None, not guess
    root2, _ = _build_overview_store(tmp_path / "second", n_days=120)
    payload2 = export_json.export_overview(root2, tmp_path / "out2")
    assert payload2["performance"]["1y"] is None
    assert payload2["performance"]["1m"] is not None


def test_export_overview_breadth_is_between_0_and_100_and_not_degenerate(tmp_path):
    root, dates = _build_overview_store(tmp_path)
    payload = export_json.export_overview(root, tmp_path / "out")
    breadth = payload["breadth_above_sma50"]
    assert len(breadth["dates"]) > 0
    assert breadth["dates"][-1] == dates[-1].isoformat()
    for pct in breadth["pct"]:
        assert 0.0 <= pct <= 100.0
    # SYM0 is deliberately below its own SMA all along -> breadth must be < 100%
    assert breadth["pct"][-1] < 100.0
    assert all(n == 6 for n in breadth["n_symbols"][-5:])


def test_export_overview_handles_missing_tables_gracefully(tmp_path):
    root = tmp_path / "psx_serving"
    root.mkdir()
    con = duckdb.connect(str(root / "psx_serving.duckdb"))
    con.execute("CREATE TABLE stock_metadata (symbol TEXT, company_name TEXT, sector TEXT)")
    con.close()

    payload = export_json.export_overview(root, tmp_path / "out")
    assert payload["as_of"] is None
    assert payload["regime"] is None
    assert payload["kse100"]["dates"] == []
    assert payload["breadth_above_sma50"]["dates"] == []
    raw = (tmp_path / "out" / "overview.json").read_text()
    json.loads(raw)  # still valid JSON


def test_write_json_atomic_leaves_no_tmp_file_behind(tmp_path):
    path = tmp_path / "out" / "x.json"
    export_json._write_json_atomic(path, {"a": 1})
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
    assert json.loads(path.read_text()) == {"a": 1}
