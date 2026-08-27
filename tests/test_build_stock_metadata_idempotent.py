"""
Regression tests for build_stock_metadata.py's idempotent-upsert rework.

Guards three properties the old drop-and-rebuild broke or lacked:
  1. Running twice is a no-op the second time (idempotent).
  2. A manually-added row NOT in the computed include-set survives (no delete).
  3. config.UNIVERSE_WHITELIST symbols land with their SECTOR_OVERRIDES sector,
     even when their `sectors` row says "Unknown Sector".

Runs the script as a subprocess against an isolated DB via the
STOCK_METADATA_DB env var — never touches the real psx_data.db.
"""

import os
import sqlite3
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "build_stock_metadata.py")


def _make_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE sectors (symbol TEXT PRIMARY KEY, sector TEXT);
        CREATE TABLE kse100_constituents (symbol TEXT PRIMARY KEY, company_name TEXT);
        CREATE TABLE prices (symbol TEXT, date TEXT, close REAL);
        CREATE TABLE stock_metadata (
            symbol TEXT PRIMARY KEY, company_name TEXT, sector TEXT,
            listing_date TEXT, delisting_date TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            in_kse100 INTEGER NOT NULL DEFAULT 0, notes TEXT
        );
        """
    )
    con.executemany(
        "INSERT INTO sectors VALUES (?, ?)",
        [
            ("AAA", "COMMERCIAL BANKS"),        # normal tracked
            ("BBB", "TEXTILE SPINNING"),        # excluded sector
            ("SYM", "Unknown Sector"),          # whitelist + override
            ("BML", "Unknown Sector"),          # whitelist + override
            ("FCL", "Unknown Sector"),          # whitelist + override
            ("WAVESAPP", "Unknown Sector"),     # whitelist + override
            ("MSOT", "TEXTILE COMPOSITE"),      # override target APPAREL
            ("DELIST", "COMMERCIAL BANKS"),     # in include-set, hand-flagged delisted
        ],
    )
    con.executemany(
        "INSERT INTO prices VALUES (?, ?, ?)",
        [(s, "2026-08-20", 100.0) for s in ("AAA", "SYM", "BML", "FCL", "WAVESAPP", "MSOT")]
        # DELIST has a recent price row too -> the ACTIVE_CUTOFF heuristic would
        # say is_active=1, but the hand-set is_active=0 must win on UPDATE.
        + [("DELIST", "2026-08-20", 50.0)],
    )
    con.execute("INSERT INTO kse100_constituents VALUES ('AAA', 'Alpha Bank Ltd')")
    # A manually-curated row that the include-set will NOT contain.
    con.execute(
        "INSERT INTO stock_metadata (symbol, sector, is_active, in_kse100, notes) "
        "VALUES ('MANUAL', 'TEXTILE WEAVING', 1, 0, 'kept by hand')"
    )
    # A manually-curated *delisted* row that IS in the include-set (gets UPDATEd).
    con.execute(
        "INSERT INTO stock_metadata "
        "(symbol, sector, listing_date, delisting_date, is_active, in_kse100, notes) "
        "VALUES ('DELIST', 'COMMERCIAL BANKS', '2005-01-03', '2024-06-30', 0, 0, "
        "'Auto-flagged: delisted')"
    )
    con.commit()
    con.close()


def _run(db_path):
    env = dict(os.environ, STOCK_METADATA_DB=db_path)
    r = subprocess.run(
        [sys.executable, SCRIPT], cwd=REPO, env=env,
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _dump(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = {r["symbol"]: dict(r) for r in con.execute("SELECT * FROM stock_metadata")}
    con.close()
    return rows


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "iso.db")
    _make_db(p)
    return p


def test_whitelist_symbols_get_override_sector(db):
    _run(db)
    rows = _dump(db)
    assert rows["SYM"]["sector"] == "TECHNOLOGY & COMMUNICATION"
    assert rows["BML"]["sector"] == "COMMERCIAL BANKS"
    assert rows["FCL"]["sector"] == "CABLE & ELECTRICAL GOODS"
    assert rows["WAVESAPP"]["sector"] == "CABLE & ELECTRICAL GOODS"
    assert rows["MSOT"]["sector"] == "APPAREL"


def test_excluded_sector_symbol_not_added(db):
    _run(db)
    rows = _dump(db)
    assert "BBB" not in rows


def test_manual_row_preserved(db):
    _run(db)
    rows = _dump(db)
    assert "MANUAL" in rows
    assert rows["MANUAL"]["notes"] == "kept by hand"
    assert rows["MANUAL"]["sector"] == "TEXTILE WEAVING"


def test_idempotent_second_run_is_noop(db):
    _run(db)
    first = _dump(db)
    _run(db)
    second = _dump(db)
    assert first == second


def test_hand_flagged_delisted_row_stays_delisted(db):
    """is_active=0 / delisting_date are manual-curation columns: a rebuild must
    not re-activate a hand-flagged delisted symbol even when it has a fresh
    price row (regression: the first cut of the upsert recomputed is_active and
    flipped 9 real delisted symbols back to active)."""
    _run(db)
    rows = _dump(db)
    assert rows["DELIST"]["is_active"] == 0
    assert rows["DELIST"]["delisting_date"] == "2024-06-30"
    assert rows["DELIST"]["notes"] == "Auto-flagged: delisted"
    # source-derived columns still get refreshed on that same row
    assert rows["DELIST"]["sector"] == "COMMERCIAL BANKS"


def test_new_symbol_gets_computed_is_active(db):
    """On INSERT (not conflict) is_active is still computed from the price range."""
    _run(db)
    rows = _dump(db)
    assert rows["SYM"]["is_active"] == 1  # fresh 2026 price -> active


def test_notes_not_clobbered_on_update(db):
    _run(db)
    con = sqlite3.connect(db)
    con.execute("UPDATE stock_metadata SET notes = 'hand note' WHERE symbol = 'AAA'")
    con.commit()
    con.close()
    _run(db)
    rows = _dump(db)
    assert rows["AAA"]["notes"] == "hand note"
