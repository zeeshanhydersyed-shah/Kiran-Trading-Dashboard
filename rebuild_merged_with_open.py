"""
Rebuild merged_psx_data.csv and merged_index_data.csv with an Open price column.

Reads open prices from the BI PostgreSQL (localhost:55432) and merges them into
the existing merged CSVs.  The existing H/L/C/V data is never overwritten —
open is added as a new column (or filled in where currently NULL/NaN).

Run once after any BI PostgreSQL refresh:
    python rebuild_merged_with_open.py

Requirements:
    pip install psycopg2-binary pandas
"""

import logging
import sys
import pandas as pd
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# BI PostgreSQL connection
BI_HOST     = "localhost"
BI_PORT     = 55432
BI_DB       = "postgres"
BI_USER     = "postgres"
BI_PASSWORD = "1234"

STOCK_CSV = "merged_psx_data.csv"
INDEX_CSV = "merged_index_data.csv"

INDEX_CODE_MAP = {
    "KSE100":  "KSE-100",
    "KSE-100": "KSE-100",
    "KSE30":   "KSE-30",
    "KSE-30":  "KSE-30",
    "ALLSHR":  "KSE-ALL",
    "KSE-ALL": "KSE-ALL",
}


def bi_connect():
    return psycopg2.connect(
        host=BI_HOST, port=BI_PORT, dbname=BI_DB,
        user=BI_USER, password=BI_PASSWORD
    )


def fetch_bi_stock_open(conn) -> pd.DataFrame:
    """Pull (symbol, eventdate, open) from company_history."""
    logger.info("Fetching stock open prices from BI PostgreSQL ...")

    # Discover actual column names
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'company_history' ORDER BY ordinal_position
        """)
        cols = [r[0] for r in cur.fetchall()]
        logger.info("  company_history columns: %s", cols)

    query = """
        SELECT code AS symbol, eventdate::text AS date, open
        FROM company_history
        WHERE open IS NOT NULL
        ORDER BY code, eventdate
    """
    df = pd.read_sql(query, conn)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    logger.info("  Fetched %d rows, %d symbols", len(df), df["symbol"].nunique())
    return df


def fetch_bi_index_open(conn) -> pd.DataFrame:
    """Pull (symbol, eventdate, open) from index_history."""
    logger.info("Fetching index open prices from BI PostgreSQL ...")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'index_history' ORDER BY ordinal_position
        """)
        cols = [r[0] for r in cur.fetchall()]
        logger.info("  index_history columns: %s", cols)
        # Use 'code' if present, else 'symbol'
        sym_col = "code" if "code" in cols else "symbol"

    query = f"""
        SELECT {sym_col} AS symbol, eventdate::text AS date, open
        FROM index_history
        WHERE open IS NOT NULL
        ORDER BY {sym_col}, eventdate
    """
    df = pd.read_sql(query, conn)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["symbol"] = df["symbol"].map(lambda s: INDEX_CODE_MAP.get(s, s))
    logger.info("  Fetched %d rows, symbols: %s", len(df), list(df["symbol"].unique()))
    return df


def rebuild_stock_csv(bi_open: pd.DataFrame):
    logger.info("Reading %s ...", STOCK_CSV)
    existing = pd.read_csv(STOCK_CSV)
    logger.info("  Existing columns: %s  Rows: %d", list(existing.columns), len(existing))

    # Merge BI open prices in — left join so existing rows are never dropped
    merged = existing.merge(
        bi_open[["symbol", "date", "open"]],
        on=["symbol", "date"],
        how="left",
        suffixes=("", "_bi"),
    )

    # If open column already existed (partial data), fill NaN from BI
    if "open" in existing.columns:
        merged["open"] = merged["open"].combine_first(merged.get("open_bi", pd.Series(dtype=float)))
        if "open_bi" in merged.columns:
            merged.drop(columns=["open_bi"], inplace=True)
    else:
        # open came in from the merge as "open" — nothing to rename
        pass

    # Column order: symbol, date, open, high, low, close, volume
    base_cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    extra = [c for c in merged.columns if c not in base_cols]
    merged = merged[base_cols + extra]

    filled = merged["open"].notna().sum()
    total  = len(merged)
    logger.info("  open filled: %d / %d rows (%.1f%%)", filled, total, 100 * filled / total)

    merged.to_csv(STOCK_CSV, index=False)
    logger.info("  Saved %s", STOCK_CSV)


def rebuild_index_csv(bi_open: pd.DataFrame):
    logger.info("Reading %s ...", INDEX_CSV)
    existing = pd.read_csv(INDEX_CSV)
    logger.info("  Existing columns: %s  Rows: %d", list(existing.columns), len(existing))

    merged = existing.merge(
        bi_open[["symbol", "date", "open"]],
        on=["symbol", "date"],
        how="left",
        suffixes=("", "_bi"),
    )

    if "open" in existing.columns:
        merged["open"] = merged["open"].combine_first(merged.get("open_bi", pd.Series(dtype=float)))
        if "open_bi" in merged.columns:
            merged.drop(columns=["open_bi"], inplace=True)

    base_cols = ["symbol", "date", "open", "high", "low", "close"]
    extra = [c for c in merged.columns if c not in base_cols]
    merged = merged[base_cols + extra]

    filled = merged["open"].notna().sum()
    total  = len(merged)
    logger.info("  open filled: %d / %d rows (%.1f%%)", filled, total, 100 * filled / total)

    merged.to_csv(INDEX_CSV, index=False)
    logger.info("  Saved %s", INDEX_CSV)


def main():
    try:
        conn = bi_connect()
        logger.info("Connected to BI PostgreSQL at %s:%d", BI_HOST, BI_PORT)
    except Exception as e:
        logger.error("Cannot connect to BI PostgreSQL: %s", e)
        logger.error("Make sure the BI database is running (StartDB.cmd).")
        sys.exit(1)

    try:
        stock_open = fetch_bi_stock_open(conn)
        index_open = fetch_bi_index_open(conn)
    finally:
        conn.close()

    rebuild_stock_csv(stock_open)
    rebuild_index_csv(index_open)

    logger.info("")
    logger.info("Done. Next steps:")
    logger.info("  1. python load_bi_history.py   — reload updated CSVs into psx_data.db")
    logger.info("  2. git add merged_psx_data.csv merged_index_data.csv")
    logger.info("  3. git commit -m 'Add open prices to merged CSVs'")
    logger.info("  4. git push origin main")


if __name__ == "__main__":
    main()
