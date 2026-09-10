"""Phase 3, Task 3.2 -- Silver build (archive/silver_build.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 3 / MEDALLION.md):
rebuild prices_adjusted (CA-adjusted + circuit flags) + the conformed universe
from the live Bronze store; deterministic re-run; ca_v2 wired but gated OFF;
never opens psx_data.db for write.
"""
from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive import bronze_ingest, silver_build

_CSV_HEADER = ("symbol,date,close_before,close_after,pct_change,peer_avg_change,"
               "magnitude_category,likely_action,peers_used,sector,review_status\n")


def _bronze_prices(root, rows):
    by_year = {}
    for r in rows:
        by_year.setdefault(r[1][:4], []).append(r)
    for year, rs in by_year.items():
        t = pa.table({
            "symbol": [r[0] for r in rs], "date": [r[1] for r in rs],
            "close": [r[2] for r in rs], "volume": [r[3] for r in rs],
            "high": [r[4] for r in rs], "low": [r[5] for r in rs], "open": [r[6] for r in rs],
        }, schema=bronze_ingest.PRICES_SCHEMA)
        fp = root / "prices_archive" / "bronze" / "prices" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(bronze_ingest._sort(t), fp, **bronze_ingest.PARQUET_OPTS)


def _frozen_silver(root, sectors, meta_rows, adj_rows):
    s = root / "silver"
    st = pa.table({"symbol": [x[0] for x in sectors], "sector": [x[1] for x in sectors]},
                  schema=pa.schema([("symbol", pa.string()), ("sector", pa.string())]))
    (s / "sectors").mkdir(parents=True, exist_ok=True)
    pq.write_table(st, s / "sectors" / "sectors.parquet", **bronze_ingest.PARQUET_OPTS)

    mt = pa.table({k: [r.get(k) for r in meta_rows] for k in
                   ["symbol", "company_name", "sector", "listing_date", "delisting_date",
                    "is_active", "in_kse100", "notes"]},
                  schema=pa.schema([("symbol", pa.string()), ("company_name", pa.string()),
                                    ("sector", pa.string()), ("listing_date", pa.string()),
                                    ("delisting_date", pa.string()), ("is_active", pa.int64()),
                                    ("in_kse100", pa.int64()), ("notes", pa.string())]))
    (s / "stock_metadata").mkdir(parents=True, exist_ok=True)
    pq.write_table(mt, s / "stock_metadata" / "stock_metadata.parquet", **bronze_ingest.PARQUET_OPTS)

    for year in sorted({r[1][:4] for r in adj_rows}):
        rs = [r for r in adj_rows if r[1][:4] == year]
        at = pa.table({k: [r[i] for r in rs] for i, k in enumerate(silver_build.PRICES_ADJ_COLUMNS)},
                      schema=silver_build.PRICES_ADJ_SCHEMA)
        fp = s / "prices_adjusted" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(bronze_ingest._sort(at), fp, **bronze_ingest.PARQUET_OPTS)


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    (root / "prices_archive").mkdir(parents=True)
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(silver_build, "ARCHIVE_ROOT", root)

    csv_path = tmp_path / "ca_suspects.csv"
    csv_path.write_text(_CSV_HEADER +
        # HBL: a 2:1 bonus on 2026-03-02 (close 200 -> 100), DROP_50 auto-confirm
        "HBL,2026-03-02,200,100,-50,-2,DROP_50,Bonus,10,COMMERCIAL BANKS,PENDING\n"
        # OGDC DROP_OTHER -> NOT auto-confirmed, PENDING -> ignored
        "OGDC,2026-03-02,210,190,-9.5,-1,DROP_OTHER,Rights,10,OIL & GAS,PENDING\n")
    monkeypatch.setattr(silver_build, "CSV_PATH", csv_path)

    _bronze_prices(root, [
        ("HBL", "2026-03-01", 200.0, 1000, 201.0, 199.0, 199.5),
        ("HBL", "2026-03-02", 100.0, 1500, 101.0, 99.0, 100.0),
        ("HBL", "2026-03-03", 102.0, 1200, 103.0, 101.0, 101.5),
        ("OGDC", "2026-03-01", 208.0, 900, 209.0, 207.0, 207.5),
        ("OGDC", "2026-03-02", 190.0, 950, 191.0, 189.0, 190.5),
        ("786", "2026-03-01", 5.0, 10, 5.1, 4.9, 5.0),          # non-equity -> dropped
    ])
    _frozen_silver(
        root,
        sectors=[("HBL", "COMMERCIAL BANKS"), ("OGDC", "OIL & GAS"),
                 ("786", "COMMERCIAL BANKS"), ("OLDMOD", "MODARABAS")],
        meta_rows=[
            {"symbol": "HBL", "company_name": "Habib Bank", "sector": "COMMERCIAL BANKS",
             "listing_date": "2005-01-03", "delisting_date": None, "is_active": 1,
             "in_kse100": 1, "notes": None},
            {"symbol": "LEGACY", "company_name": "Old Co", "sector": "SUGAR & ALLIED INDUSTRIES",
             "listing_date": "2006-01-01", "delisting_date": "2019-01-01", "is_active": 0,
             "in_kse100": 0, "notes": "manual: delisted"},
        ],
        adj_rows=[
            # frozen prices_adjusted -- HBL already bonus-adjusted, OGDC raw
            ("HBL", "2026-03-01", 100.0, 1000, 100.5, 99.5, 99.75, 0, 0, 0),
            ("HBL", "2026-03-02", 100.0, 1500, 101.0, 99.0, 100.0, 0, 0, 0),
            ("HBL", "2026-03-03", 102.0, 1200, 103.0, 101.0, 101.5, 0, 0, 0),
            ("OGDC", "2026-03-01", 208.0, 900, 209.0, 207.0, 207.5, 0, 0, 0),
            ("OGDC", "2026-03-02", 190.0, 950, 191.0, 189.0, 190.5, 0, 0, 0),
        ],
    )
    return root


def _adj(root):
    g = root / "prices_archive" / "silver" / "prices_adjusted"
    return pq.read_table(g / "year=2026" / "data.parquet")


def test_load_legacy_events_filters_and_sorts(store):
    ev = silver_build.load_legacy_events(baseline_db=None)
    assert [(e["symbol"], e["date"]) for e in ev] == [("HBL", "2026-03-02")]
    assert ev[0]["category"] == "DROP_50"


def test_build_applies_ca_and_writes_flags(store):
    res = silver_build.build(store / "prices_archive", ca_source="legacy")
    assert res["outcome"] == "built"
    t = _adj(store).to_pydict()
    row = {(s, d): i for i, (s, d) in enumerate(zip(t["symbol"], t["date"]))}
    # HBL pre-ex-date (03-01) multiplied by 100/200 = 0.5, ROUND 4
    i = row[("HBL", "2026-03-01")]
    assert t["close"][i] == 100.0 and t["open"][i] == 99.75 and t["high"][i] == 100.5
    # HBL on/after ex-date untouched
    assert t["close"][row[("HBL", "2026-03-02")]] == 100.0
    assert t["close"][row[("HBL", "2026-03-03")]] == 102.0
    # OGDC never adjusted (DROP_OTHER PENDING)
    assert t["close"][row[("OGDC", "2026-03-01")]] == 208.0
    assert set(t) >= {"hit_circuit_up", "hit_circuit_down", "thin_trading_flag"}


def test_build_is_idempotent(store):
    import hashlib
    silver_build.build(store / "prices_archive", ca_source="legacy")
    g = store / "prices_archive" / "silver"
    snap1 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(g.rglob("*.parquet"))}
    silver_build.build(store / "prices_archive", ca_source="legacy")
    snap2 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(g.rglob("*.parquet"))}
    assert snap1 == snap2 and len(snap1) >= 3


def test_universe_conforming(store):
    silver_build.build(store / "prices_archive", ca_source="legacy")
    g = store / "prices_archive" / "silver"
    secs = pq.read_table(g / "sectors" / "sectors.parquet").column("symbol").to_pylist()
    assert "786" not in secs and "HBL" in secs        # non-equity dropped

    meta = {r["symbol"]: r for r in
            pq.read_table(g / "stock_metadata" / "stock_metadata.parquet").to_pylist()}
    assert "LEGACY" in meta and meta["LEGACY"]["notes"] == "manual: delisted"   # preserved
    assert meta["HBL"]["sector"] == "COMMERCIAL BANKS"
    assert "OLDMOD" not in meta                         # MODARABAS excluded, never was in frozen


def test_parity_report_written(store):
    res = silver_build.build(store / "prices_archive", ca_source="legacy")
    rep = json.loads((store / "prices_archive" / "_silver_parity.json").read_text())
    assert rep["only_frozen"] == 0 and rep["only_new"] == 0
    assert res["parity_vs_frozen"]["status"] in ("clean", "residual")


def test_ca_source_v2_wired_but_guarded(store):
    # v2 is available but not default; a missing reader dir fails cleanly, it
    # does not silently fall back or corrupt the build.
    with pytest.raises(SystemExit, match="ca_v2_reader.py not found"):
        silver_build.build(store / "prices_archive", ca_source="v2",
                           ca_v2_dir=store / "no_such_dir")


def test_never_writes_psx_data_db(store):
    text = open(silver_build.__file__).read()
    # the only DB connection is the frozen baseline, opened strictly read-only
    assert 'sqlite3.connect(f"file:{baseline_db}?mode=ro&immutable=1"' in text
    assert "import database" not in text
    assert text.count("sqlite3.connect") == 1
