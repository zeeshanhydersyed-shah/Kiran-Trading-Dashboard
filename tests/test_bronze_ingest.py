"""Phase 3, Task 3.1 -- Bronze ingest (archive/bronze_ingest.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 3 / MEDALLION.md):
append-only, deduped, gap-detecting; every consumed capture file recorded with
its SHA-256; re-run is byte-identical; never opens psx_data.db.

No network, no git, no live DB -- everything runs against a synthetic archive
root under tmp_path.
"""
from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive import bronze_ingest
from archive.scrape_capture import SCHEMA as CAPTURE_SCHEMA, PARQUET_OPTS as CAP_OPTS


# --------------------------------------------------------------------- helpers

def _frozen_bronze(root, prices_rows, index_rows):
    """Write a minimal frozen Phase 1 seed under <root>/bronze + STORE_MANIFEST.json."""
    by_year: dict[str, list] = {}
    for r in prices_rows:
        by_year.setdefault(r[1][:4], []).append(r)
    for year, rows in by_year.items():
        t = pa.table({
            "symbol": [r[0] for r in rows], "date": [r[1] for r in rows],
            "close": [r[2] for r in rows], "volume": [r[3] for r in rows],
            "high": [r[4] for r in rows], "low": [r[5] for r in rows],
            "open": [r[6] for r in rows],
        }, schema=bronze_ingest.PRICES_SCHEMA)
        fp = root / "bronze" / "prices" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(bronze_ingest._sort(t), fp, **bronze_ingest.PARQUET_OPTS)

    by_year = {}
    for r in index_rows:
        by_year.setdefault(r[1][:4], []).append(r)
    for year, rows in by_year.items():
        t = pa.table({
            "symbol": [r[0] for r in rows], "date": [r[1] for r in rows],
            "high": [r[2] for r in rows], "low": [r[3] for r in rows],
            "close": [r[4] for r in rows], "open": [r[5] for r in rows],
        }, schema=bronze_ingest.INDEX_SCHEMA)
        fp = root / "bronze" / "index_prices" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(bronze_ingest._sort(t), fp, **bronze_ingest.PARQUET_OPTS)

    (root / "STORE_MANIFEST.json").write_text(json.dumps({"stub": True}))


def _capture_file(captures_dir, source_date, stocks, indices, code_version="abc123"):
    """stocks: [(sym, sector, o,h,l,c,vol)]   indices: [(sym, o,h,l,c)]"""
    recs = []
    for sym, sec, o, h, l, c, v in stocks:
        recs.append({"record_type": "stock", "symbol": sym, "trading_date": source_date,
                     "open": o, "high": h, "low": l, "close": c, "volume": v, "sector": sec})
    for sym, o, h, l, c in indices:
        recs.append({"record_type": "index", "symbol": sym, "trading_date": source_date,
                     "open": o, "high": h, "low": l, "close": c, "volume": None, "sector": None})
    recs.sort(key=lambda r: (r["record_type"], r["symbol"]))
    cols = {c: [r[c] for r in recs] for c in [f.name for f in CAPTURE_SCHEMA]}
    t = pa.table(cols, schema=CAPTURE_SCHEMA).replace_schema_metadata({
        "capture_schema_version": "1", "source_date": source_date,
        "code_version": code_version, "coverage_status": "COMPLETE",
    })
    incoming = captures_dir / "data" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    pq.write_table(t, incoming / f"{source_date}.parquet", **CAP_OPTS)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    root.mkdir()
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    _frozen_bronze(
        root,
        prices_rows=[
            ("HBL", "2026-09-07", 100.0, 5, 101.0, 99.0, 99.5),
            ("HBL", "2026-09-08", 101.0, 6, 102.0, 100.0, 100.5),
            ("OGDC", "2026-09-08", 205.0, 7, 206.0, 204.0, 204.5),
        ],
        index_rows=[
            ("KSE-100", "2026-09-08", 79000.0, 78000.0, 78500.0, 78100.0),
        ],
    )
    captures = root / "data-captures"
    (captures / "data" / "incoming").mkdir(parents=True)
    return root, captures


# ----------------------------------------------------------------------- tests

def test_seed_copies_frozen_and_logs(archive):
    root, captures = archive
    store = bronze_ingest.Store(root / "prices_archive")
    res = bronze_ingest.seed(store)
    assert res["seeded"] is True
    assert res["seed_max_date"] == "2026-09-08"
    assert store.dates_present("prices") == {"2026-09-07", "2026-09-08"}
    entries = store.log_entries()
    assert len(entries) == 1 and entries[0]["action"] == "seed"
    assert entries[0]["store_manifest_sha256"] is not None
    # second seed is a no-op
    assert bronze_ingest.seed(store)["seeded"] is False
    assert len(store.log_entries()) == 1


def test_ingest_appends_new_day(archive):
    root, captures = archive
    _capture_file(captures, "2026-09-09",
                  stocks=[("HBL", "COMMERCIAL BANKS", 101.0, 103.0, 100.5, 102.0, 900),
                          ("OGDC", "OIL & GAS", 206.0, 208.0, 205.0, 207.0, 500)],
                  indices=[("KSE-100", 78200.0, 79100.0, 78100.0, 78900.0)])
    store = bronze_ingest.Store(root / "prices_archive")
    bronze_ingest.seed(store)
    res = bronze_ingest.ingest(store, captures, pull=False)

    assert res["outcome"] == "ingested"
    assert res["ingested_dates"] == ["2026-09-09"]
    assert res["rows_added"] == 3
    assert store.dates_present("prices") == {"2026-09-07", "2026-09-08", "2026-09-09"}
    assert "2026-09-09" in store.dates_present("index_prices")

    part = store.read_partition("prices", "2026")
    assert part.column_names == bronze_ingest.PRICES_COLUMNS
    hbl_9 = part.filter(pa.compute.and_(
        pa.compute.equal(part.column("symbol"), "HBL"),
        pa.compute.equal(part.column("date"), "2026-09-09")))
    assert hbl_9.num_rows == 1 and hbl_9.column("close")[0].as_py() == 102.0

    log = [e for e in store.log_entries() if e["action"] == "ingest"]
    assert len(log) == 1
    assert log[0]["source_date"] == "2026-09-09"
    assert len(log[0]["capture_sha256"]) == 64
    assert log[0]["stock_rows_added"] == 2 and log[0]["index_rows_added"] == 1
    assert log[0]["capture_code_version"] == "abc123"


def test_reingest_is_byte_identical_and_no_log_growth(archive):
    root, captures = archive
    _capture_file(captures, "2026-09-09",
                  stocks=[("HBL", "COMMERCIAL BANKS", 101.0, 103.0, 100.5, 102.0, 900)],
                  indices=[("KSE-100", 78200.0, 79100.0, 78100.0, 78900.0)])
    store = bronze_ingest.Store(root / "prices_archive")
    bronze_ingest.seed(store)
    bronze_ingest.ingest(store, captures, pull=False)

    def snapshot():
        return {p.relative_to(store.root).as_posix(): bronze_ingest.sha256(p)
                for p in sorted(store.bronze.rglob("*.parquet"))}

    before = snapshot()
    log_before = store.log_path.read_bytes()

    res = bronze_ingest.ingest(store, captures, pull=False)
    assert res["outcome"] == "up_to_date"
    assert res["skipped_present"] == ["2026-09-09"]
    assert snapshot() == before                       # byte-identical
    assert store.log_path.read_bytes() == log_before   # no log append


def test_capture_for_seeded_date_is_deduped(archive):
    root, captures = archive
    _capture_file(captures, "2026-09-08",
                  stocks=[("HBL", "COMMERCIAL BANKS", 1.0, 2.0, 0.5, 1.5, 9)],
                  indices=[])
    store = bronze_ingest.Store(root / "prices_archive")
    bronze_ingest.seed(store)
    part_before = bronze_ingest.sha256(store.part_path("prices", "2026"))

    res = bronze_ingest.ingest(store, captures, pull=False)
    assert res["skipped_present"] == ["2026-09-08"]
    # the seeded 2026-09-08 HBL close (101.0) is untouched, not overwritten by 1.5
    assert bronze_ingest.sha256(store.part_path("prices", "2026")) == part_before
    assert not [e for e in store.log_entries() if e["action"] == "ingest"]


def test_gap_detection_flags_missing_weekday(archive):
    root, captures = archive
    # seed max is Tue 2026-09-08; capture Fri 2026-09-11 -> Wed 09-09 + Thu 09-10 gap
    _capture_file(captures, "2026-09-11",
                  stocks=[("HBL", "COMMERCIAL BANKS", 1.0, 2.0, 0.5, 1.5, 9)], indices=[])
    store = bronze_ingest.Store(root / "prices_archive")
    bronze_ingest.seed(store)
    res = bronze_ingest.ingest(store, captures, pull=False)

    assert res["gaps"]["missing_capture"] == ["2026-09-09", "2026-09-10"]
    report = json.loads((store.root / "_bronze_gaps.json").read_text())
    assert report["window"] == {"after": "2026-09-08", "through": "2026-09-11"}


def test_does_not_touch_psx_data_db():
    src = (bronze_ingest.__file__)
    text = open(src).read()
    assert "psx_data.db" not in text.replace(
        "Never opens ``psx_data.db``", "").replace("psx_data.db at all", "")
    assert "import sqlite3" not in text
    assert "import database" not in text and "import config" not in text
