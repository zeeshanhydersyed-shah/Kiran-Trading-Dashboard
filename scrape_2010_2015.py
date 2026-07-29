"""
PSX Historical Scraper — 2010-01-01 to 2014-12-31
Staging only. psx_data.db is NOT touched.

Parser mirrors scraper.py exactly:
  - Sector-aware 8-cell row detection
  - "Market Indexes" section → index_prices_staging (no volume, no open)
  - All other sections       → prices_staging       (no open, volume captured)

Usage:
    python scrape_2010_2015.py            # full 2010–2014 run
    python scrape_2010_2015.py --year 2010  # single year (resume safe)

Output:
    psx_historical_2010_2015.db  (staging DB)
    failed_dates_2010_2015.txt   (dates that exhausted all retries)
"""

import sqlite3
import requests
import time
import sys
import argparse
from datetime import date, timedelta
from bs4 import BeautifulSoup
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_DIR   = Path(r"C:\Users\Lenovo\psx_pipeline")
STAGING_DB    = PROJECT_DIR / "psx_historical_2010_2015.db"
FAILED_LOG    = PROJECT_DIR / "failed_dates_2010_2015.txt"
URL           = "https://www.ksestocks.com/MarketSummary"
REQUEST_DELAY = 2.0
MAX_RETRIES   = 3

# Must match config.py — these appear in "Market Indexes" section and are
# routed to index_prices_staging, not prices_staging.
INDEX_SYMBOLS = {"KSE-100", "KSE-30", "KSE-ALL", "KSE-MI30", "KSE-MIALL"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.ksestocks.com/",
}


# ── Schema ────────────────────────────────────────────────────────────────────
# prices_staging  : matches prices  (symbol, date, close, volume, high, low, open)
#                   open is always NULL — scraper does not capture it.
# index_prices_staging : matches index_prices (symbol, date, high, low, close)
#                        NO volume column, NO open column.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prices_staging (
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,
    close   REAL,
    volume  INTEGER,
    high    REAL,
    low     REAL,
    open    REAL,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS index_prices_staging (
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,
    high    REAL,
    low     REAL,
    close   REAL,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS scrape_progress (
    date        TEXT PRIMARY KEY,
    status      TEXT NOT NULL,   -- 'done' | 'failed'
    rows_added  INTEGER DEFAULT 0,
    scraped_at  TEXT DEFAULT (datetime('now'))
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def already_scraped(conn: sqlite3.Connection, dt: str) -> bool:
    row = conn.execute(
        "SELECT status FROM scrape_progress WHERE date = ?", (dt,)
    ).fetchone()
    return row is not None and row[0] == "done"


def log_failed(dt: str):
    with open(FAILED_LOG, "a") as f:
        f.write(f"{dt}\n")


# ── Parser (mirrors scraper.py parse_market_summary exactly) ─────────────────
def parse_market_summary(html: str, dt: str):
    """
    Parse ksestocks MarketSummary HTML.

    Table structure (single large <table>):
      - Section header row : 2 TDs, second contains "Number of traded companies"
      - Column header row  : first TD text == "Symbol"
      - Stock data row     : 8 TDs → Symbol, Company, Open, High, Low, Close, Change, Vol

    Returns:
        price_rows : list of (symbol, date, high, low, close, volume)   — no open
        index_rows : list of (symbol, date, high, low, close)            — no volume
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    data_table = tables[-1] if tables else None
    if not data_table:
        return [], []

    rows = data_table.find_all("tr")
    current_sector = None
    price_rows = []
    index_rows = []

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        # ── Sector / section header ──
        if len(cells) == 2:
            second_text = cells[1].get_text(strip=True)
            if "Number of traded companies" in second_text or second_text == "":
                current_sector = cells[0].get_text(strip=True)
                continue

        # ── Column header row ──
        if cells[0].get_text(strip=True) == "Symbol":
            continue

        # ── 8-cell data row ──
        if len(cells) != 8 or not current_sector:
            continue

        symbol     = cells[0].get_text(strip=True)
        high_text  = cells[3].get_text(strip=True).replace(",", "")
        low_text   = cells[4].get_text(strip=True).replace(",", "")
        close_text = cells[5].get_text(strip=True).replace(",", "")
        vol_text   = cells[7].get_text(strip=True).replace(",", "")

        if not symbol or symbol == "Symbol":
            continue

        # ── Market Indexes → index_prices_staging ──
        if current_sector == "Market Indexes":
            try:
                close = float(close_text)
                high  = float(high_text)  if high_text  else close
                low   = float(low_text)   if low_text   else close
                high  = max(high, close)
                low   = min(low,  close)
                index_rows.append((symbol, dt, high, low, close))
            except ValueError:
                pass
            continue

        # ── Skip stray index symbols appearing in stock sections ──
        if symbol in INDEX_SYMBOLS:
            continue

        # ── Stock row → prices_staging ──
        try:
            close = float(close_text)
        except ValueError:
            continue

        if close <= 0:
            continue

        try:
            high = float(high_text) if high_text else close
        except ValueError:
            high = close

        try:
            low = float(low_text) if low_text else close
        except ValueError:
            low = close

        high = max(high, close)
        low  = min(low,  close)

        try:
            volume = int(float(vol_text)) if vol_text else 0
        except (ValueError, OverflowError):
            volume = 0

        price_rows.append((symbol, dt, high, low, close, volume))

    return price_rows, index_rows


def fetch_html(session: requests.Session, dt: str) -> str:
    """POST to ksestocks for one date; retry up to MAX_RETRIES. Raises on failure."""
    payload = {"sdate": dt}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(URL, data=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(REQUEST_DELAY * attempt)


def insert_rows(conn: sqlite3.Connection, price_rows, index_rows) -> int:
    inserted = 0

    for sym, dt, high, low, close, volume in price_rows:
        conn.execute(
            "INSERT OR IGNORE INTO prices_staging "
            "(symbol, date, close, volume, high, low, open) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (sym, dt, close, volume, high, low),
        )
        if conn.execute("SELECT changes()").fetchone()[0]:
            inserted += 1

    for sym, dt, high, low, close in index_rows:
        conn.execute(
            "INSERT OR IGNORE INTO index_prices_staging "
            "(symbol, date, high, low, close) "
            "VALUES (?, ?, ?, ?, ?)",
            (sym, dt, high, low, close),
        )
        if conn.execute("SELECT changes()").fetchone()[0]:
            inserted += 1

    return inserted


def trading_dates(start: date, end: date):
    """Yield Mon–Fri ISO strings in [start, end]."""
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            yield cur.isoformat()
        cur += timedelta(days=1)


# ── Per-year runner ───────────────────────────────────────────────────────────
def run_year(conn: sqlite3.Connection, year: int):
    start = date(year, 1, 1)
    end   = date(year, 12, 31)
    dates = list(trading_dates(start, end))
    total = len(dates)

    session   = requests.Session()
    year_rows = 0
    skipped   = 0
    failed_n  = 0

    print(f"\n{'='*60}")
    print(f"  YEAR {year}  |  {total} weekdays to process")
    print(f"{'='*60}")

    for seq, dt in enumerate(dates, 1):
        if already_scraped(conn, dt):
            skipped += 1
            continue

        try:
            html = fetch_html(session, dt)
            price_rows, index_rows = parse_market_summary(html, dt)
            n = insert_rows(conn, price_rows, index_rows)
            conn.execute(
                "INSERT OR REPLACE INTO scrape_progress (date, status, rows_added) "
                "VALUES (?, 'done', ?)",
                (dt, n),
            )
            conn.commit()
            year_rows += n
            label = f"{len(price_rows):3d}p + {len(index_rows):1d}i  rows  (year total: {year_rows:,})"
            print(f"  [{seq:3d}/{total}] {dt}  →  {label}")
        except Exception as e:
            failed_n += 1
            log_failed(dt)
            conn.execute(
                "INSERT OR REPLACE INTO scrape_progress (date, status, rows_added) "
                "VALUES (?, 'failed', 0)",
                (dt,),
            )
            conn.commit()
            print(f"  [{seq:3d}/{total}] {dt}  ✗  FAILED ({e})  → logged")

        time.sleep(REQUEST_DELAY)

    print(f"\n  Year {year} complete.")
    print(f"  Rows added   : {year_rows:,}")
    print(f"  Skipped      : {skipped:,}  (already scraped)")
    print(f"  Failed dates : {failed_n}")
    return year_rows


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary(conn: sqlite3.Connection):
    print("\n" + "="*60)
    print("  STAGING SUMMARY")
    print("="*60)

    r = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM prices_staging"
    ).fetchone()
    print(f"  prices_staging       : {r[0]:>8,} rows  |  {r[1]} → {r[2]}")

    r = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM index_prices_staging"
    ).fetchone()
    print(f"  index_prices_staging : {r[0]:>8,} rows  |  {r[1]} → {r[2]}")

    print("\n  Rows by year (prices_staging):")
    for yr, cnt in conn.execute(
        "SELECT substr(date,1,4), COUNT(*) FROM prices_staging "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"    {yr}  :  {cnt:,}")

    failed = conn.execute(
        "SELECT COUNT(*) FROM scrape_progress WHERE status='failed'"
    ).fetchone()[0]
    if failed:
        print(f"\n  ⚠️  Failed dates: {failed}  (see failed_dates_2010_2015.txt)")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--year", type=int, choices=[2010, 2011, 2012, 2013, 2014],
        help="Scrape a single year only (resume safe)",
    )
    args = parser.parse_args()

    print(f"Staging DB : {STAGING_DB}")
    conn = init_db(STAGING_DB)

    years      = [args.year] if args.year else [2010, 2011, 2012, 2013, 2014]
    total_rows = 0
    for year in years:
        total_rows += run_year(conn, year)

    print_summary(conn)
    conn.close()

    print(f"\nTotal rows written : {total_rows:,}")
    print("Scrape complete. Run verify_2010_2015.py next.")


if __name__ == "__main__":
    main()
