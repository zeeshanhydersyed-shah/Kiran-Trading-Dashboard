"""Phase 2 contemporaneous scrape capture (archive/scrape_capture.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 2 / CAPTURE_FILES.md):
one immutable data/incoming/YYYY-MM-DD.parquet per source date + a
freely-overwritten latest.parquet; reuses scraper.py's fetch/parse; idempotent;
never touches psx_data.db / Supabase / daily_scraper.yml.

All network is monkeypatched -- these tests never hit ksestocks.
"""
from __future__ import annotations

import datetime as dt

import pyarrow.parquet as pq
import pytest

import scraper
from archive import scrape_capture


D = dt.date(2026, 9, 9)

# scraper.scrape_date returns (sector_rows, price_rows, index_rows)
#   price_rows : (symbol, date_str, high, low, close, volume, open)
#   index_rows : (symbol, date_str, high, low, close, open)
_SECTORS = [("HBL", "COMMERCIAL BANKS"), ("OGDC", "OIL & GAS EXPLORATION")]
_PRICES = [
    ("HBL", "2026-09-09", 101.0, 98.0, 100.0, 1_000_000, 99.0),
    ("OGDC", "2026-09-09", 210.0, 205.0, 208.0, 500_000, 206.0),
]
_INDEX = [("KSE100", "2026-09-09", 78_500.0, 78_000.0, 78_400.0, 78_100.0)]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(scraper, "build_session", lambda: object())
    monkeypatch.setattr(scraper, "get_source_date", lambda session: D)

    def _fake_scrape_date(target_date, session, coverage_out=None):
        if coverage_out is not None:
            coverage_out.append({
                "scrape_date": target_date.isoformat(),
                "expected_total": 2, "parsed_total": 2, "detail": None,
            })
        return list(_SECTORS), list(_PRICES), list(_INDEX)

    monkeypatch.setattr(scraper, "scrape_date", _fake_scrape_date)
    # keep every run's code_version deterministic and offline
    monkeypatch.setattr(scrape_capture, "resolve_code_version", lambda: "0" * 40)


def _read(path):
    t = pq.read_table(path)
    meta = {k.decode(): v.decode() for k, v in (t.schema.metadata or {}).items()}
    return t.to_pylist(), meta


def test_written_outcome_and_file_layout(tmp_path):
    res = scrape_capture.capture(tmp_path)
    assert res["outcome"] == "written"
    assert res["source_date"] == "2026-09-09"
    assert (tmp_path / "2026-09-09.parquet").is_file()
    assert (tmp_path / "latest.parquet").is_file()
    assert res["stock_rows"] == 2 and res["index_rows"] == 1 and res["sector_count"] == 2


def test_row_content_stock_and_index(tmp_path):
    scrape_capture.capture(tmp_path)
    rows, _ = _read(tmp_path / "2026-09-09.parquet")
    by_sym = {r["symbol"]: r for r in rows}

    hbl = by_sym["HBL"]
    assert hbl["record_type"] == "stock"
    assert hbl["trading_date"] == "2026-09-09"
    assert (hbl["open"], hbl["high"], hbl["low"], hbl["close"]) == (99.0, 101.0, 98.0, 100.0)
    assert hbl["volume"] == 1_000_000
    assert hbl["sector"] == "COMMERCIAL BANKS"

    idx = by_sym["KSE100"]
    assert idx["record_type"] == "index"
    assert idx["volume"] is None
    assert idx["sector"] is None
    assert idx["close"] == 78_400.0

    # deterministic ordering: indices sort before stocks
    assert [r["record_type"] for r in rows] == ["index", "stock", "stock"]


def test_metadata_embedded(tmp_path):
    scrape_capture.capture(tmp_path)
    _, meta = _read(tmp_path / "2026-09-09.parquet")
    assert meta["capture_schema_version"] == "1"
    assert meta["source_date"] == "2026-09-09"
    assert meta["coverage_status"] == "COMPLETE"
    assert meta["stock_rows"] == "2"
    assert meta["expected_total"] == "2" and meta["parsed_total"] == "2"
    assert meta["code_version"] == "0" * 40
    assert len(meta["scraper_sha256"]) == 64
    assert "scraped_at_utc" in meta
    assert meta["date_override"] == "false"


def test_idempotent_second_call_is_noop(tmp_path):
    first = scrape_capture.capture(tmp_path)
    before = (tmp_path / "2026-09-09.parquet").read_bytes()
    second = scrape_capture.capture(tmp_path)
    after = (tmp_path / "2026-09-09.parquet").read_bytes()
    assert second["outcome"] == "exists"
    assert second["sha256"] == first["sha256"]
    assert before == after   # the immutable file was not rewritten


def test_force_overwrites_but_data_is_stable(tmp_path):
    scrape_capture.capture(tmp_path)
    rows1, _ = _read(tmp_path / "2026-09-09.parquet")
    res = scrape_capture.capture(tmp_path, force=True)
    rows2, _ = _read(tmp_path / "2026-09-09.parquet")
    assert res["outcome"] == "written"
    assert rows1 == rows2   # same scrape -> identical rows


def test_nodata_day_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "scrape_date",
                        lambda td, s, coverage_out=None: ([], [], []))
    res = scrape_capture.capture(tmp_path)
    assert res["outcome"] == "nodata"
    assert list(tmp_path.glob("*.parquet")) == []


def test_unreachable_source_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "get_source_date", lambda s: None)
    res = scrape_capture.capture(tmp_path)
    assert res["outcome"] == "unreachable"
    assert res["source_date"] is None
    assert list(tmp_path.glob("*.parquet")) == []


def test_latest_tracks_newest_and_backfill_does_not_regress_it(tmp_path, monkeypatch):
    # capture the "current" day
    scrape_capture.capture(tmp_path)
    newest = (tmp_path / "latest.parquet").read_bytes()
    assert newest == (tmp_path / "2026-09-09.parquet").read_bytes()

    # backfill an OLDER date via --date; latest.parquet must not change
    old = dt.date(2026, 9, 1)

    def _older(td, s, coverage_out=None):
        if coverage_out is not None:
            coverage_out.append({"scrape_date": td.isoformat(),
                                 "expected_total": 2, "parsed_total": 2, "detail": None})
        rows = [(sym, td.isoformat(), h, l, c, v, o)
                for (sym, _d, h, l, c, v, o) in _PRICES]
        return list(_SECTORS), rows, []

    monkeypatch.setattr(scraper, "scrape_date", _older)
    res = scrape_capture.capture(tmp_path, date_override=old)
    assert res["outcome"] == "written"
    assert (tmp_path / "2026-09-01.parquet").is_file()
    assert (tmp_path / "latest.parquet").read_bytes() == newest   # unchanged


def test_coverage_status_incomplete(tmp_path, monkeypatch):
    def _short(td, s, coverage_out=None):
        if coverage_out is not None:
            coverage_out.append({"scrape_date": td.isoformat(), "expected_total": 5,
                                 "parsed_total": 2, "detail": "OIL & GAS EXPLORATION: 3 stated, 0 parsed"})
        return list(_SECTORS), list(_PRICES), list(_INDEX)

    monkeypatch.setattr(scraper, "scrape_date", _short)
    res = scrape_capture.capture(tmp_path)
    assert res["outcome"] == "written"
    _, meta = _read(tmp_path / "2026-09-09.parquet")
    assert meta["coverage_status"] == "INCOMPLETE"
    assert "OIL & GAS EXPLORATION" in meta["coverage_detail"]


def test_github_output_emitted(tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    rc = scrape_capture.main(["--out-dir", str(tmp_path)])
    assert rc == 0
    text = out.read_text()
    assert "outcome=written" in text
    assert "source_date=2026-09-09" in text
    assert "coverage_status=COMPLETE" in text
    assert "sha256=" in text


def test_main_returns_zero_on_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "get_source_date", lambda s: None)
    assert scrape_capture.main(["--out-dir", str(tmp_path)]) == 0


def test_does_not_touch_psx_data_db(tmp_path):
    # capture must never open the production DB for write
    import os

    import config

    before = os.path.getmtime(config.DB_PATH) if os.path.exists(config.DB_PATH) else None
    scrape_capture.capture(tmp_path)
    if before is not None:
        assert os.path.getmtime(config.DB_PATH) == before
