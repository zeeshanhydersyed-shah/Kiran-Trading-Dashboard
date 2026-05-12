"""
Load historical price data from merged BI CSVs into psx_data.db.

Sources:
  merged_psx_data.csv   — 2020-01-01 to 2026-05-08, 409 symbols
  merged_index_data.csv — 2020-01-01 to 2026-05-08, 3 index codes

Strategy:
  INSERT ... ON CONFLICT DO UPDATE (fills NULL highs/lows, never overwrites
  existing close). So scraper data for 2024+ is preserved; pre-2024 BI data
  fills the historical gap.

Run once whenever merged CSVs are refreshed from the BI PostgreSQL source.
"""

import logging
import sys
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from database import get_conn, init_db, upsert_prices, upsert_index_prices

# Map BI index codes → Kiran index_prices symbol names
INDEX_CODE_MAP = {
    "KSE100": "KSE-100",
    "KSE-100": "KSE-100",
    "KSE30": "KSE-30",
    "KSE-30": "KSE-30",
    "ALLSHR": "KSE-ALL",
    "KSE-ALL": "KSE-ALL",
}

BATCH = 5_000   # rows per INSERT batch


def load_company_history(csv_path: str = "merged_psx_data.csv"):
    logger.info("Reading %s ...", csv_path)
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["symbol", "date", "close"])
    df["volume"] = df["volume"].fillna(0).astype(int)
    df["high"]   = df["high"].fillna(df["close"])
    df["low"]    = df["low"].fillna(df["close"])

    logger.info("  Rows: %d  Symbols: %d  Range: %s to %s",
                len(df), df["symbol"].nunique(),
                df["date"].min(), df["date"].max())

    rows = [
        (r.symbol, r.date, float(r.high), float(r.low), float(r.close), int(r.volume))
        for r in df.itertuples(index=False)
    ]

    total = len(rows)
    for i in range(0, total, BATCH):
        upsert_prices(rows[i:i + BATCH])
        logger.info("  Upserted %d / %d rows", min(i + BATCH, total), total)

    logger.info("Company history load complete.")


def load_index_history(csv_path: str = "merged_index_data.csv"):
    logger.info("Reading %s ...", csv_path)
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["symbol", "date", "close"])

    # Normalise symbol names to Kiran convention
    df["symbol"] = df["symbol"].map(lambda s: INDEX_CODE_MAP.get(s, s))
    df["high"]   = df["high"].fillna(df["close"]) if "high" in df.columns else df["close"]
    df["low"]    = df["low"].fillna(df["close"])  if "low"  in df.columns else df["close"]

    logger.info("  Rows: %d  Symbols: %s  Range: %s to %s",
                len(df), list(df["symbol"].unique()),
                df["date"].min(), df["date"].max())

    rows = [
        (r.symbol, r.date, float(r.high), float(r.low), float(r.close))
        for r in df.itertuples(index=False)
    ]

    for i in range(0, len(rows), BATCH):
        upsert_index_prices(rows[i:i + BATCH])

    logger.info("Index history load complete.")


def verify():
    with get_conn() as conn:
        r = conn.execute(
            "SELECT MIN(date) mn, MAX(date) mx, COUNT(*) n, COUNT(DISTINCT symbol) s FROM prices"
        ).fetchone()
        logger.info("prices  : %d rows  %d symbols  %s → %s", r[2], r[3], r[0], r[1])

        r2 = conn.execute(
            "SELECT MIN(date) mn, MAX(date) mx, COUNT(*) n FROM index_prices"
        ).fetchone()
        logger.info("index_prices: %d rows  %s → %s", r2[2], r2[0], r2[1])

        pre = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE date < '2024-01-01'"
        ).fetchone()[0]
        logger.info("Pre-2024 rows now in DB: %d", pre)


def main():
    init_db()
    load_company_history()
    load_index_history()
    verify()
    logger.info("Done. Run: python backtest.py")


if __name__ == "__main__":
    main()
