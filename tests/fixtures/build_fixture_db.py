"""Build tests/fixtures/psx_fixture.db -- a small, committable slice of the
real local SQLite database, used by tests/test_app_boot.py so CI can boot the
dashboard against a realistic schema + data.

WHY A SLICE OF THE REAL DB, AND NOT database.init_db()
------------------------------------------------------
`init_db()` creates 14 tables; the live database has 49, and even the tables
it does create have drifted from what the code queries (confirmed 2026-08-12:
a fresh `init_db()` database crashes the dashboard with
`no such column: p.open` -- `prices.open` was added to the live DB during the
Open Price project and never added to `init_db()`'s CREATE TABLE). So
`init_db()` cannot stand in for "the schema production actually has", and
hand-maintaining a parallel schema file would drift the same way.

Copying the real DDL straight out of `sqlite_master` means the fixture's
schema is, by construction, whatever the live database actually has on the
day it was generated. Re-run this script whenever the schema changes.

WHAT IT COPIES
--------------
  * Every table's and index's DDL, verbatim -- all 49 tables exist in the
    fixture even when they hold no rows, so no query can fail with
    "no such table".
  * A bounded slice of rows: the most recent `--days` trading days, and for
    per-symbol tables only the symbols in a small representative universe
    (top `--per-sector` symbols per sector by recent volume).
  * Full copies of small reference/config tables (`sectors`,
    `stock_metadata`, ...) so joins resolve.
  * Nothing at all from the research/staging tables (see `EXCLUDE_ROWS`) --
    they are millions of rows of dead study data and no page reads them.

The source DB is opened strictly read-only (`mode=ro`), so this can never
mutate production data.

USAGE
-----
    python tests/fixtures/build_fixture_db.py            # default slice
    python tests/fixtures/build_fixture_db.py --days 400 --per-sector 4

Then commit the regenerated `psx_fixture.db`.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _ROOT)

import config  # noqa: E402

OUT_PATH = os.path.join(_HERE, "psx_fixture.db")

# Research / staging / retired-feature tables: schema copied, zero rows.
# These carry millions of rows between them and nothing in the live
# dashboard reads any of them (see docs/KIRAN_CLEANUP_AUDIT.md §5).
EXCLUDE_ROWS = {
    "pre_breakout_v2_staging",
    "pre_breakout_v2_staging_full",
    "stock_signals_breakout_v2_staging_DEPRECATED_243sym",
    "stock_signals_breakout_v2_staging_full",
    "sim_portfolio_trades",
    "sim_portfolio_trades_v2",
    "sim_portfolio_trades_v3",
}

# PERSONAL DATA -- schema copied, zero rows, non-negotiable.
# This fixture is COMMITTED to the repository. The live database holds the
# owner's real trades, real portfolio capital, and their private chat history
# with the agent (.gitignore's very first line exists for exactly this
# reason: "never commit the live DB ... contains personal trade data").
# Everything else in the fixture is public market data or signals computed
# from it. Do not move a table out of this set without deciding, explicitly,
# that its contents are safe to publish.
EXCLUDE_PERSONAL = {
    "trade_setups",             # real entries/exits/stops and actual P&L
    "portfolio_values",         # account capital over time
    "portfolio_transactions",
    "agent_chat_log",           # private conversations with the agent
    "agent_reports",            # narrative reports about the owner's trading
    "agent_learning_log",
    "agent_memory",
    "agent_trader_profile",     # behavioural profile of the owner
    "agent_opportunities",
    "agent_patterns",
    "agent_reference_breakouts",
    "prediction_log",
}

# Small reference tables copied in full regardless of size -- joins against
# these resolve to nothing useful if they are sliced.
COPY_FULL = {
    "sectors",
    "stock_metadata",
    "kse100_constituents",
    "stock_market_cap",
}

# Tables whose `symbol` values are not equities and so are never in the
# fixture universe -- sliced by date only, all symbols kept.
KEEP_ALL_SYMBOLS = {"index_prices"}

# Not every table calls its date column `date`. Checked in this order.
DATE_COLS = (
    "date", "setup_date", "as_of_date", "scan_date", "signal_date",
    "suspect_date", "trigger_date", "created_date",
)

# Tables with no date column that are still small enough to take whole.
MAX_FULL_ROWS = 5_000


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def _pick_universe(src: sqlite3.Connection, per_sector: int) -> list[str]:
    """Top `per_sector` symbols per sector by recent average volume.

    Uses `stock_signals.avg_vol_10d` on its latest date when available (that
    is the same liquidity measure the live setup queries filter on), falling
    back to raw `prices.volume` if `stock_signals` is empty.
    """
    latest = src.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
    if latest:
        rows = src.execute(
            """
            SELECT ss.symbol, s.sector, ss.avg_vol_10d AS vol
              FROM stock_signals ss
              JOIN sectors s ON s.symbol = ss.symbol
             WHERE ss.date = ?
            """,
            (latest,),
        ).fetchall()
    else:
        latest_p = src.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        rows = src.execute(
            """
            SELECT p.symbol, s.sector, p.volume AS vol
              FROM prices p
              JOIN sectors s ON s.symbol = p.symbol
             WHERE p.date = ?
            """,
            (latest_p,),
        ).fetchall()

    by_sector: dict[str, list[tuple[str, float]]] = {}
    for symbol, sector, vol in rows:
        by_sector.setdefault(sector, []).append((symbol, vol or 0))

    universe: list[str] = []
    for sector, items in sorted(by_sector.items()):
        items.sort(key=lambda t: t[1], reverse=True)
        universe.extend(sym for sym, _ in items[:per_sector])
    return sorted(set(universe))


def _cutoff_date(src: sqlite3.Connection, days: int) -> str:
    """The date `days` trading days back in `prices`, as an ISO string."""
    row = src.execute(
        "SELECT date FROM (SELECT DISTINCT date FROM prices ORDER BY date DESC "
        "LIMIT ?) ORDER BY date ASC LIMIT 1",
        (days,),
    ).fetchone()
    return row[0] if row else "0000-00-00"


def build(days: int, per_sector: int, out_path: str = OUT_PATH) -> None:
    if not os.path.exists(config.DB_PATH):
        raise SystemExit(
            f"source DB not found at {config.DB_PATH} -- this script can only be "
            "run on a machine that has the local production SQLite database."
        )
    if os.path.exists(out_path):
        os.remove(out_path)

    src = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    dst = sqlite3.connect(out_path)

    schema = src.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = [r[1] for r in schema if r[0] == "table"]

    # 1. schema first (tables, then everything else so indexes/views resolve)
    for typ, name, _tbl, sql in schema:
        if typ == "table":
            dst.execute(sql)
    for typ, name, _tbl, sql in schema:
        if typ != "table":
            try:
                dst.execute(sql)
            except sqlite3.OperationalError as exc:  # pragma: no cover
                print(f"  ! skipped {typ} {name}: {exc}")
    dst.commit()

    universe = _pick_universe(src, per_sector)
    cutoff = _cutoff_date(src, days)
    print(f"source     : {config.DB_PATH}")
    print(f"universe   : {len(universe)} symbols")
    print(f"date cutoff: {cutoff}  (last {days} trading days)")

    placeholders = ",".join("?" * len(universe))

    # 2. rows
    for table in sorted(tables):
        cols = _columns(src, table)
        has_symbol = "symbol" in cols and table not in KEEP_ALL_SYMBOLS
        date_col = next((c for c in DATE_COLS if c in cols), None)
        params: list = []

        if table in EXCLUDE_PERSONAL:
            print(f"  {table:52s} EMPTY (personal data -- never committed)")
            continue

        if table in EXCLUDE_ROWS:
            print(f"  {table:52s} skipped (research/staging)")
            continue

        if table in COPY_FULL:
            where = ""
        elif date_col and has_symbol:
            where = f'WHERE "{date_col}" >= ? AND symbol IN ({placeholders})'
            params = [cutoff, *universe]
        elif date_col:
            where = f'WHERE "{date_col}" >= ?'
            params = [cutoff]
        elif has_symbol:
            where = f"WHERE symbol IN ({placeholders})"
            params = list(universe)
        else:
            n = src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if n > MAX_FULL_ROWS:
                print(f"  {table:52s} skipped ({n} rows, no date column)")
                continue
            where = ""

        rows = src.execute(f'SELECT * FROM "{table}" {where}', params).fetchall()
        if rows:
            marks = ",".join("?" * len(cols))
            dst.executemany(f'INSERT INTO "{table}" VALUES ({marks})', rows)
        print(f"  {table:52s} {len(rows)} rows")

    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    src.close()

    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\nwrote {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=300,
                    help="trading days of history to keep (default 300 -- enough "
                         "for the 200-day overhead-supply lookback)")
    ap.add_argument("--per-sector", type=int, default=3,
                    help="symbols per sector in the fixture universe (default 3)")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()
    build(args.days, args.per_sector, args.out)
