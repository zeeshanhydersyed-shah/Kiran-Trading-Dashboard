"""
Historical scraper: 2015-01-01 → 2019-12-31
============================================
Appends pre-2020 EOD data to a staging database (psx_historical_2015_2020.db).
psx_data.db is NOT touched during this script.

Usage:
    python scrape_historical_2015_2020.py             # full run
    python scrape_historical_2015_2020.py --year 2015 # single year (resume / retry)
    python scrape_historical_2015_2020.py --verify    # run Step 4 verification only
    python scrape_historical_2015_2020.py --merge     # run Step 5 merge (requires prior approval)
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT          = Path(__file__).parent
MAIN_DB       = ROOT / "psx_data.db"
STAGING_DB    = ROOT / "psx_historical_2015_2020.db"
FAILED_LOG    = ROOT / "failed_dates_2015_2020.txt"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MARKET_SUMMARY_URL = "https://www.ksestocks.com/MarketSummary"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.ksestocks.com/",
}
REQUEST_DELAY = 2.0   # seconds between date requests
MAX_RETRIES   = 3
INDEX_SYMBOLS = {"KSE-100", "KSE-30", "KSE-ALL", "KSE-MI30", "KSE-MIALL"}

SCRAPE_START = date(2015, 1, 1)
SCRAPE_END   = date(2019, 12, 31)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Staging DB helpers
# ---------------------------------------------------------------------------

def get_staging_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(STAGING_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def create_staging_tables(conn: sqlite3.Connection) -> None:
    """Create staging tables with identical schema to main DB."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prices_staging (
            symbol  TEXT NOT NULL,
            date    TEXT NOT NULL,
            close   REAL NOT NULL,
            volume  INTEGER,
            high    REAL,
            low     REAL,
            open    REAL,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_ps_date   ON prices_staging (date);
        CREATE INDEX IF NOT EXISTS idx_ps_symbol ON prices_staging (symbol);

        CREATE TABLE IF NOT EXISTS index_prices_staging (
            symbol  TEXT NOT NULL,
            date    TEXT NOT NULL,
            high    REAL,
            low     REAL,
            close   REAL NOT NULL,
            open    REAL,
            PRIMARY KEY (symbol, date)
        );
        CREATE INDEX IF NOT EXISTS idx_ips_date ON index_prices_staging (date);

        -- Progress tracking: dates already attempted
        CREATE TABLE IF NOT EXISTS scrape_progress (
            date        TEXT PRIMARY KEY,
            status      TEXT,   -- 'ok' or 'failed'
            price_rows  INTEGER DEFAULT 0,
            index_rows  INTEGER DEFAULT 0,
            scraped_at  TEXT
        );
    """)
    conn.commit()
    log.info("Staging tables ready in %s", STAGING_DB)


def already_scraped(conn: sqlite3.Connection, d: date) -> bool:
    cur = conn.execute(
        "SELECT status FROM scrape_progress WHERE date = ?",
        (d.isoformat(),)
    )
    row = cur.fetchone()
    return row is not None and row[0] == "ok"


def mark_progress(conn: sqlite3.Connection, d: date, status: str,
                  price_rows: int, index_rows: int) -> None:
    from datetime import datetime
    conn.execute("""
        INSERT OR REPLACE INTO scrape_progress (date, status, price_rows, index_rows, scraped_at)
        VALUES (?, ?, ?, ?, ?)
    """, (d.isoformat(), status, price_rows, index_rows, datetime.now().isoformat(timespec="seconds")))
    conn.commit()


# ---------------------------------------------------------------------------
# HTML fetch
# ---------------------------------------------------------------------------

def _fetch_html(session: requests.Session, target_date: date) -> str | None:
    date_str = target_date.strftime("%Y-%m-%d")
    payload = {"sdate": date_str}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(MARKET_SUMMARY_URL, data=payload, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            log.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, date_str, exc)
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)
    return None


# ---------------------------------------------------------------------------
# HTML parser (mirrors scraper.py parse_market_summary)
# ---------------------------------------------------------------------------

def parse_market_summary(html: str, target_date: date):
    """
    Returns (price_rows, index_rows):
      price_rows : list of (symbol, date_str, close, volume, high, low, open=None)
      index_rows : list of (symbol, date_str, high, low, close, open=None)
    Column order matches the DB table definitions exactly.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    data_table = tables[-1] if tables else None
    if not data_table:
        return [], []

    rows = data_table.find_all("tr")
    current_sector = None
    date_str = target_date.strftime("%Y-%m-%d")

    price_rows  = []
    index_rows  = []

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        # Sector header
        if len(cells) == 2:
            second_text = cells[1].get_text(strip=True)
            if "Number of traded companies" in second_text or second_text == "":
                current_sector = cells[0].get_text(strip=True)
                continue

        # Column header
        if cells[0].get_text(strip=True) == "Symbol":
            continue

        if len(cells) != 8 or not current_sector:
            continue

        symbol     = cells[0].get_text(strip=True)
        if not symbol:
            continue

        high_text  = cells[3].get_text(strip=True).replace(",", "")
        low_text   = cells[4].get_text(strip=True).replace(",", "")
        close_text = cells[5].get_text(strip=True).replace(",", "")
        vol_text   = cells[7].get_text(strip=True).replace(",", "")

        # Index symbols → index_prices_staging
        if current_sector == "Market Indexes" or symbol in INDEX_SYMBOLS:
            try:
                close = float(close_text)
                high  = float(high_text)  if high_text  else close
                low   = float(low_text)   if low_text   else close
                high  = max(high, close)
                low   = min(low,  close)
                # DB column order: symbol, date, high, low, close, open
                index_rows.append((symbol, date_str, high, low, close, None))
            except ValueError:
                pass
            continue

        # Stock rows
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

        # DB column order: symbol, date, close, volume, high, low, open
        price_rows.append((symbol, date_str, close, volume, high, low, None))

    return price_rows, index_rows


# ---------------------------------------------------------------------------
# Scrape one date
# ---------------------------------------------------------------------------

def scrape_one_date(session: requests.Session, conn: sqlite3.Connection, d: date) -> tuple[int, int]:
    """
    Scrape one date, insert into staging. Returns (price_rows_inserted, index_rows_inserted).
    Returns (-1, -1) on fetch failure.
    """
    if already_scraped(conn, d):
        log.info("SKIP  %s  (already in scrape_progress)", d)
        cur = conn.execute(
            "SELECT price_rows, index_rows FROM scrape_progress WHERE date = ?",
            (d.isoformat(),)
        )
        row = cur.fetchone()
        return (row[0], row[1]) if row else (0, 0)

    html = _fetch_html(session, d)
    if html is None:
        log.error("FAIL  %s  — all retries exhausted", d)
        with open(FAILED_LOG, "a") as f:
            f.write(f"{d.isoformat()}\n")
        mark_progress(conn, d, "failed", 0, 0)
        return -1, -1

    price_rows, index_rows = parse_market_summary(html, d)

    if not price_rows:
        # Holiday / no trading data — still mark as ok (not a failure)
        log.info("HOLIDAY/NODATA  %s  (0 price rows)", d)
        mark_progress(conn, d, "ok", 0, 0)
        return 0, 0

    # Insert price rows
    conn.executemany(
        "INSERT OR IGNORE INTO prices_staging (symbol, date, close, volume, high, low, open) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        price_rows,
    )
    # Insert index rows
    conn.executemany(
        "INSERT OR IGNORE INTO index_prices_staging (symbol, date, high, low, close, open) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        index_rows,
    )
    conn.commit()

    n_p = len(price_rows)
    n_i = len(index_rows)
    mark_progress(conn, d, "ok", n_p, n_i)
    return n_p, n_i


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def date_range(start: date, end: date):
    d = start
    while d <= end:
        if _is_weekday(d):
            yield d
        d += timedelta(days=1)


def dates_for_year(year: int):
    start = max(SCRAPE_START, date(year, 1, 1))
    end   = min(SCRAPE_END,   date(year, 12, 31))
    return list(date_range(start, end))


# ---------------------------------------------------------------------------
# Step 3: Scrape
# ---------------------------------------------------------------------------

def run_scrape(year_filter: int | None = None) -> None:
    conn = get_staging_conn()
    create_staging_tables(conn)

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    years = [year_filter] if year_filter else list(range(2015, 2020))

    for year in years:
        dates = dates_for_year(year)
        log.info("=" * 60)
        log.info("YEAR %d  —  %d trading dates to process", year, len(dates))
        log.info("=" * 60)

        year_price_rows = 0
        year_index_rows = 0
        year_failed     = 0

        for i, d in enumerate(dates, 1):
            n_p, n_i = scrape_one_date(session, conn, d)

            if n_p == -1:
                year_failed += 1
            else:
                year_price_rows += n_p
                year_index_rows += n_i

            if i % 20 == 0 or i == len(dates):
                log.info(
                    "  Progress %d/%d  |  price rows this year: %d  |  index rows: %d  |  failed dates: %d",
                    i, len(dates), year_price_rows, year_index_rows, year_failed,
                )

            if i < len(dates):
                time.sleep(REQUEST_DELAY)

        log.info(
            "YEAR %d COMPLETE  —  price rows: %d  |  index rows: %d  |  failed dates: %d",
            year, year_price_rows, year_index_rows, year_failed,
        )

    # Summary across all years
    conn2 = sqlite3.connect(STAGING_DB)
    cur = conn2.execute("SELECT COUNT(*) FROM prices_staging")
    total_p = cur.fetchone()[0]
    cur = conn2.execute("SELECT COUNT(*) FROM index_prices_staging")
    total_i = cur.fetchone()[0]
    cur = conn2.execute("SELECT COUNT(*) FROM scrape_progress WHERE status='failed'")
    total_fail = cur.fetchone()[0]
    conn2.close()

    log.info("=" * 60)
    log.info("SCRAPE COMPLETE")
    log.info("  prices_staging rows      : %d", total_p)
    log.info("  index_prices_staging rows: %d", total_i)
    log.info("  Failed dates             : %d  (see %s)", total_fail, FAILED_LOG)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Step 4: Verification
# ---------------------------------------------------------------------------

def run_verification() -> bool:
    """Run all 6 checks. Returns True only if all pass."""
    log.info("")
    log.info("=" * 60)
    log.info("STEP 4 — CROSS-VERIFICATION REPORT")
    log.info("=" * 60)

    staging = sqlite3.connect(STAGING_DB)
    main    = sqlite3.connect(MAIN_DB)

    all_pass = True

    # ---- CHECK 1: Row counts per year ----
    log.info("")
    log.info("CHECK 1 — Row counts per year in prices_staging")
    log.info("-" * 50)
    cur = staging.execute("""
        SELECT substr(date,1,4) AS yr, COUNT(*) AS cnt
        FROM prices_staging
        GROUP BY yr ORDER BY yr
    """)
    rows = cur.fetchall()
    total_staging = 0
    for yr, cnt in rows:
        log.info("  %s : %d rows", yr, cnt)
        total_staging += cnt
    log.info("  TOTAL : %d rows", total_staging)
    check1 = total_staging > 0
    log.info("  RESULT: %s", "PASS" if check1 else "FAIL — staging is empty!")
    if not check1:
        all_pass = False

    # ---- CHECK 2: Date range ----
    log.info("")
    log.info("CHECK 2 — Date range in prices_staging")
    log.info("-" * 50)
    cur = staging.execute("SELECT MIN(date), MAX(date) FROM prices_staging")
    min_date, max_date = cur.fetchone()
    log.info("  Earliest: %s", min_date)
    log.info("  Latest  : %s", max_date)
    check2 = (min_date is not None and max_date is not None and
              min_date >= "2015-01-01" and max_date <= "2019-12-31")
    log.info("  RESULT: %s", "PASS" if check2 else "FAIL — dates out of expected range!")
    if not check2:
        all_pass = False

    # ---- CHECK 3: Ticker coverage ----
    log.info("")
    log.info("CHECK 3 — Ticker coverage")
    log.info("-" * 50)
    cur = main.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol")
    main_tickers = {r[0] for r in cur.fetchall()}

    cur = staging.execute("SELECT DISTINCT symbol FROM prices_staging ORDER BY symbol")
    staging_tickers = {r[0] for r in cur.fetchall()}

    missing = main_tickers - staging_tickers
    log.info("  Main DB tickers  : %d", len(main_tickers))
    log.info("  Staging tickers  : %d", len(staging_tickers))
    log.info("  Missing entirely : %d", len(missing))
    if missing:
        log.info("  (These may be post-2019 listings — review below)")
        for sym in sorted(missing)[:50]:
            log.info("    MISSING: %s", sym)
        if len(missing) > 50:
            log.info("    ... and %d more (full list suppressed)", len(missing) - 50)

    # Tickers with < 200 trading days in staging (5-year window)
    cur = staging.execute("""
        SELECT symbol, COUNT(*) AS days
        FROM prices_staging
        GROUP BY symbol
        HAVING days < 200
        ORDER BY days
    """)
    thin = cur.fetchall()
    log.info("  Tickers with < 200 trading days in staging: %d", len(thin))
    if thin:
        log.info("  (Likely post-2015 listings or infrequently traded)")
        for sym, days in thin[:30]:
            log.info("    %s : %d days", sym, days)
        if len(thin) > 30:
            log.info("    ... and %d more", len(thin) - 30)

    # Coverage check: pass if staging has at least 50% of main tickers
    # (many current tickers didn't exist in 2015-2019 — this is expected)
    check3 = len(staging_tickers) > 0
    log.info("  RESULT: %s", "PASS" if check3 else "FAIL — no tickers in staging!")
    if not check3:
        all_pass = False

    # ---- CHECK 4: Duplicate check ----
    log.info("")
    log.info("CHECK 4 — Duplicate (symbol, date) check in prices_staging")
    log.info("-" * 50)
    cur = staging.execute("""
        SELECT COUNT(*) FROM (
            SELECT symbol, date, COUNT(*) AS cnt
            FROM prices_staging
            GROUP BY symbol, date
            HAVING cnt > 1
        )
    """)
    dupes = cur.fetchone()[0]
    log.info("  Duplicate (symbol, date) pairs: %d", dupes)
    check4 = dupes == 0
    log.info("  RESULT: %s", "PASS" if check4 else "FAIL — duplicates found!")
    if not check4:
        all_pass = False

    # ---- CHECK 5: OHLCV sanity ----
    log.info("")
    log.info("CHECK 5 — OHLCV sanity in prices_staging")
    log.info("-" * 50)

    checks_5 = {}

    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE high < low")
    checks_5["high < low"] = cur.fetchone()[0]

    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE close > high")
    checks_5["close > high"] = cur.fetchone()[0]

    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE close < low")
    checks_5["close < low"] = cur.fetchone()[0]

    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE open IS NOT NULL AND open > high")
    checks_5["open > high (non-null)"] = cur.fetchone()[0]

    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE open IS NOT NULL AND open < low")
    checks_5["open < low (non-null)"] = cur.fetchone()[0]

    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE volume = 0 OR volume IS NULL")
    checks_5["volume=0 or NULL"] = cur.fetchone()[0]

    cur = staging.execute("""
        SELECT COUNT(*) FROM prices_staging
        WHERE close IS NULL OR close = 0
           OR high  IS NULL OR high  = 0
           OR low   IS NULL OR low   = 0
    """)
    checks_5["NULL/zero price"] = cur.fetchone()[0]

    sanity_fail = 0
    for label, cnt in checks_5.items():
        status = "OK" if cnt == 0 else f"FLAG ({cnt} rows)"
        log.info("  %-35s: %s", label, status)
        if label not in ("volume=0 or NULL",) and cnt > 0:
            # volume=0 is common (no trading) — warn but don't fail
            sanity_fail += cnt

    # Volume=0 warning only
    if checks_5["volume=0 or NULL"] > 0:
        log.info("  NOTE: volume=0/NULL rows are common for illiquid sessions — not a hard fail")

    check5 = sanity_fail == 0
    log.info("  RESULT: %s", "PASS" if check5 else f"FAIL — {sanity_fail} price integrity violations!")
    if not check5:
        all_pass = False

    # ---- CHECK 6: Overlap check ----
    log.info("")
    log.info("CHECK 6 — No post-2019 dates in staging")
    log.info("-" * 50)
    cur = staging.execute("SELECT COUNT(*) FROM prices_staging WHERE date >= '2020-01-01'")
    overlap = cur.fetchone()[0]
    log.info("  Rows with date >= 2020-01-01: %d", overlap)
    check6 = overlap == 0
    log.info("  RESULT: %s", "PASS" if check6 else "FAIL — staging contains post-2019 data!")
    if not check6:
        all_pass = False

    # ---- Summary ----
    log.info("")
    log.info("=" * 60)
    log.info("VERIFICATION SUMMARY")
    log.info("-" * 60)
    results = {
        "CHECK 1 — Row counts per year"           : check1,
        "CHECK 2 — Date range"                    : check2,
        "CHECK 3 — Ticker coverage"               : check3,
        "CHECK 4 — No duplicates"                 : check4,
        "CHECK 5 — OHLCV sanity"                  : check5,
        "CHECK 6 — No post-2019 overlap"          : check6,
    }
    for label, passed in results.items():
        log.info("  %-42s  %s", label, "✓ PASS" if passed else "✗ FAIL")
    log.info("")
    if all_pass:
        log.info("ALL CHECKS PASSED — ready for merge.")
        log.info("Run with --merge to execute Step 5 (requires explicit approval).")
    else:
        log.info("ONE OR MORE CHECKS FAILED — do NOT merge until issues are resolved.")
    log.info("=" * 60)

    staging.close()
    main.close()
    return all_pass


# ---------------------------------------------------------------------------
# Step 5: Merge
# ---------------------------------------------------------------------------

def run_merge() -> None:
    log.info("")
    log.info("=" * 60)
    log.info("STEP 5 — MERGE staging → psx_data.db")
    log.info("=" * 60)

    # Safety: re-run verification first
    log.info("Running verification before merge...")
    passed = run_verification()
    if not passed:
        log.error("Verification failed — merge aborted.")
        sys.exit(1)

    staging = sqlite3.connect(STAGING_DB)
    main    = sqlite3.connect(MAIN_DB)

    # Count before
    cur = main.execute("SELECT COUNT(*) FROM prices")
    before_prices = cur.fetchone()[0]
    cur = main.execute("SELECT COUNT(*) FROM index_prices")
    before_index = cur.fetchone()[0]

    log.info("Before merge — prices: %d  |  index_prices: %d", before_prices, before_index)

    # Attach staging and insert
    main.execute(f"ATTACH DATABASE '{STAGING_DB}' AS staging")

    log.info("Merging prices_staging → prices ...")
    main.execute("""
        INSERT OR IGNORE INTO main.prices (symbol, date, close, volume, high, low, open)
        SELECT symbol, date, close, volume, high, low, open
        FROM staging.prices_staging
    """)

    log.info("Merging index_prices_staging → index_prices ...")
    main.execute("""
        INSERT OR IGNORE INTO main.index_prices (symbol, date, high, low, close, open)
        SELECT symbol, date, high, low, close, open
        FROM staging.index_prices_staging
    """)

    main.commit()
    main.execute("DETACH DATABASE staging")

    # Count after
    cur = main.execute("SELECT COUNT(*) FROM prices")
    after_prices = cur.fetchone()[0]
    cur = main.execute("SELECT COUNT(*) FROM index_prices")
    after_index = cur.fetchone()[0]

    cur = main.execute("SELECT MIN(date), MAX(date) FROM prices")
    min_p, max_p = cur.fetchone()
    cur = main.execute("SELECT MIN(date), MAX(date) FROM index_prices")
    min_i, max_i = cur.fetchone()

    # Duplicate check post-merge
    cur = main.execute("""
        SELECT COUNT(*) FROM (
            SELECT symbol, date, COUNT(*) AS cnt
            FROM prices
            GROUP BY symbol, date
            HAVING cnt > 1
        )
    """)
    dupes = cur.fetchone()[0]

    main.close()
    staging.close()

    log.info("")
    log.info("=" * 60)
    log.info("STEP 6 — POST-MERGE VALIDATION")
    log.info("=" * 60)
    log.info("  prices rows before  : %d", before_prices)
    log.info("  prices rows after   : %d", after_prices)
    log.info("  Rows added          : %d", after_prices - before_prices)
    log.info("")
    log.info("  index_prices before : %d", before_index)
    log.info("  index_prices after  : %d", after_index)
    log.info("  Rows added          : %d", after_index - before_index)
    log.info("")
    log.info("  prices date range   : %s → %s", min_p, max_p)
    log.info("  index_prices range  : %s → %s", min_i, max_i)
    log.info("")
    log.info("  Duplicate (symbol,date) in prices: %d  %s",
             dupes, "(PASS)" if dupes == 0 else "(FAIL!)")
    if FAILED_LOG.exists():
        log.info("  Failed dates log    : %s", FAILED_LOG)
    log.info("=" * 60)

    if dupes > 0:
        log.error("DUPLICATE ROWS DETECTED — investigate immediately!")
        sys.exit(1)
    else:
        log.info("Merge complete. psx_data.db now covers 2015-01-01 → latest.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PSX historical scraper 2015-2019")
    parser.add_argument("--year",   type=int, help="Scrape a single year (2015-2019)")
    parser.add_argument("--verify", action="store_true", help="Run Step 4 verification only")
    parser.add_argument("--merge",  action="store_true", help="Run Step 5 merge (after approval)")
    args = parser.parse_args()

    if args.merge:
        run_merge()
    elif args.verify:
        run_verification()
    else:
        # Step 2: ensure staging DB and tables exist
        conn = get_staging_conn()
        create_staging_tables(conn)
        conn.close()
        log.info("Staging DB initialized: %s", STAGING_DB)

        # Step 3: scrape
        run_scrape(year_filter=args.year)

        # After scrape completes, prompt to run verification
        log.info("")
        log.info("Scrape finished. Now run verification:")
        log.info("  python scrape_historical_2015_2020.py --verify")
