"""
refresh_merged_csvs.py
======================
Keeps merged_psx_data.csv and merged_index_data.csv up-to-date by appending
any new rows from the local psx_data.db (SQLite) that are not already in
the files.

Usage
-----
    python refresh_merged_csvs.py            # append new data only (fast)
    python refresh_merged_csvs.py --rebuild  # full rebuild from psx_data.db

Run manually after any scrape, or add to run_update.bat.

Output files (both in repo root)
---------------------------------
    merged_psx_data.csv    — symbol, date, high, low, close, volume
    merged_index_data.csv  — symbol, date, high, low, close

Pre-2024 BI history already in the files is preserved.
Newer DB rows win on any duplicate (symbol, date) pairs.

Does NOT affect psx_data.db, Supabase, or any other part of the pipeline.
"""

import sqlite3
import sys
import logging
from pathlib import Path

import pandas as pd

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

ROOT       = Path(__file__).parent
DB_PATH    = ROOT / "psx_data.db"
PRICES_CSV = ROOT / "merged_psx_data.csv"
INDEX_CSV  = ROOT / "merged_index_data.csv"

REBUILD = "--rebuild" in sys.argv


# ── helpers ───────────────────────────────────────────────────────────────────
def _last_date_in_csv(path: Path, date_col: str = "date") -> str | None:
    """Return the latest date string already in the CSV, or None if missing."""
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=[date_col], parse_dates=[date_col])
    if df.empty:
        return None
    return df[date_col].max().strftime("%Y-%m-%d")


def _fetch_prices(since: str | None) -> pd.DataFrame:
    """Read symbol/date/OHLCV rows from psx_data.db newer than `since`."""
    where = f"WHERE date > '{since}'" if since else ""
    sql = f"""
        SELECT symbol, date,
               COALESCE(high,  close) AS high,
               COALESCE(low,   close) AS low,
               close,
               COALESCE(volume, 0)   AS volume
        FROM prices
        {where}
        ORDER BY date, symbol
    """
    label = f"after {since}" if since else "full rebuild"
    log.info("Reading prices from psx_data.db (%s) ...", label)
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(sql, conn)
    log.info("  → %d rows", len(df))
    return df


def _fetch_index(since: str | None) -> pd.DataFrame:
    """Read index OHLC rows from psx_data.db newer than `since`."""
    where = f"WHERE date > '{since}'" if since else ""
    sql = f"""
        SELECT symbol, date,
               COALESCE(high,  close) AS high,
               COALESCE(low,   close) AS low,
               close
        FROM index_prices
        {where}
        ORDER BY date, symbol
    """
    label = f"after {since}" if since else "full rebuild"
    log.info("Reading index_prices from psx_data.db (%s) ...", label)
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(sql, conn)
    log.info("  → %d rows", len(df))
    return df


def _append_and_save(existing_path: Path, new_df: pd.DataFrame,
                     key_cols: list = None):
    """
    Merge new_df into the existing CSV (or create it if missing).
    New DB rows win on any duplicate (symbol, date) pairs.
    """
    if key_cols is None:
        key_cols = ["symbol", "date"]

    if new_df.empty:
        log.info("No new rows for %s — already up to date.", existing_path.name)
        return

    if existing_path.exists() and not REBUILD:
        existing = pd.read_csv(existing_path, parse_dates=["date"])
        combined = pd.concat([existing, new_df], ignore_index=True)
        # DB rows (at the end of concat) win on duplicates
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
    else:
        combined = new_df.copy()

    combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    combined.to_csv(existing_path, index=False)

    log.info("Saved  %-30s  %d rows  |  %s  →  %s",
             existing_path.name,
             len(combined),
             combined["date"].min(),
             combined["date"].max())


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    if not DB_PATH.exists():
        log.error("psx_data.db not found at %s", DB_PATH)
        sys.exit(1)

    if REBUILD:
        log.info("REBUILD mode — reading full history from psx_data.db.")
        prices_since = None
        index_since  = None
    else:
        prices_since = _last_date_in_csv(PRICES_CSV)
        index_since  = _last_date_in_csv(INDEX_CSV)
        log.info("merged_psx_data.csv   last date : %s", prices_since or "file missing")
        log.info("merged_index_data.csv last date : %s", index_since  or "file missing")

    new_prices = _fetch_prices(prices_since)
    new_index  = _fetch_index(index_since)

    _append_and_save(PRICES_CSV, new_prices, key_cols=["symbol", "date"])
    _append_and_save(INDEX_CSV,  new_index,  key_cols=["symbol", "date"])

    log.info("Done.  Both CSV files are now current.")


if __name__ == "__main__":
    main()
