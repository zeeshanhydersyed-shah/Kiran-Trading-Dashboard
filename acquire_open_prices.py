"""
Open Price Acquisition Tool -- standalone, independent, read-only against production.

Purpose
-------
Independently reconstructs the complete PSX Open-price history (2005 -> today)
directly from the original source (ksestocks.com/MarketSummary), for EVERY
trading date in range -- regardless of whether an Open value already exists in
psx_data.db. The existing Open values in the production database (mainly 2020
onward) have uncertain provenance: they are not reproducible from the current
codebase. Rather than trust them, this tool rebuilds an authoritative dataset
from scratch and reports where the two disagree.

Independence from production (deliberate design choice)
---------------------------------------------------------
This tool does NOT import scraper.py, config.py, or database.py. Constants and
parsing logic are duplicated on purpose: if the production parser has a latent
bug, importing it here would make this "independent" validation susceptible to
the same bug, and it would silently agree with production instead of catching
the discrepancy.

Its only interaction with psx_data.db is a single read-only connection
(SQLite URI mode=ro). A startup self-test issues a no-op write against it and
confirms SQLite actually rejects it before any scraping begins -- if that
self-test does not raise, the script aborts rather than proceed.

Note on High/Low: production's scraper.py clamps high >= close >= low before
storing (see scraper.py: parse_market_summary). This tool does NOT apply that
clamp -- it stores High/Low/Close exactly as the source reports them. This
means HIGH_MISMATCH / LOW_MISMATCH against the DB are EXPECTED in some volume
and do not by themselves indicate a source problem; CLOSE_MISMATCH or
OPEN_MISMATCH are more likely to indicate something worth investigating.

This tool NEVER writes to psx_data.db. Outputs are entirely independent:
    open_acquisition_output/open_prices_stocks.csv
    open_acquisition_output/open_prices_indexes.csv
    open_acquisition_output/acquisition_staging.db   (resumable progress + raw data)
    open_acquisition_output/acquisition.log
    open_acquisition_output/summary_report.json

Usage
-----
    python acquire_open_prices.py                          # full 2005-01-01 -> yesterday
    python acquire_open_prices.py --start 2010-01-01 --end 2015-12-31
    python acquire_open_prices.py --spot-check              # 3 known dates, quick parser check
    python acquire_open_prices.py --force                   # re-scrape dates already marked done
    python acquire_open_prices.py --export-only              # regenerate CSVs from staging DB only
    python acquire_open_prices.py --no-db-compare            # skip touching psx_data.db entirely

Resuming: just run the same command again. Dates already marked 'done' or
'holiday' in the staging DB are skipped automatically. Interrupting with
Ctrl+C is safe -- the current date's request may be lost, but every
previously completed date is already committed to the staging DB.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants (duplicated from production intentionally -- see module docstring)
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "open_acquisition_output"
PROD_DB_PATH = SCRIPT_DIR / "psx_data.db"

STAGING_DB_PATH = OUTPUT_DIR / "acquisition_staging.db"
STOCK_CSV_PATH = OUTPUT_DIR / "open_prices_stocks.csv"
INDEX_CSV_PATH = OUTPUT_DIR / "open_prices_indexes.csv"
LOG_PATH = OUTPUT_DIR / "acquisition.log"
SUMMARY_PATH = OUTPUT_DIR / "summary_report.json"

BASE_URL = "https://www.ksestocks.com"
MARKET_SUMMARY_URL = f"{BASE_URL}/MarketSummary"
SOURCE_LABEL = "ksestocks.com/MarketSummary"

REQUEST_DELAY = 2.0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
MAX_CONSECUTIVE_FAILURES = 15  # safety valve -- stop early if the source seems broken/unreachable

# Recovery backoff after a failed date: transient local network/DNS blips (observed in
# practice as getaddrinfo failures lasting anywhere from seconds to a couple minutes)
# are far more common than the source actually being down. Pausing here, escalating with
# consecutive failures, lets the run bridge a brief outage on its own instead of tripping
# the circuit breaker and requiring a manual rerun every time.
FAILURE_BACKOFF_BASE = 30      # seconds
FAILURE_BACKOFF_MAX = 300      # seconds cap

MISMATCH_EPSILON = 0.01

INDEX_SYMBOLS = {"KSE-100", "KSE-30", "KSE-ALL", "KSE-MI30", "KSE-MIALL"}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.ksestocks.com/",
}

SPOT_CHECK_DATES = [date(2005, 1, 3), date(2015, 6, 1), date(2024, 3, 4)]

DEFAULT_START = date(2005, 1, 1)

logger = logging.getLogger("open_acquisition")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    OUTPUT_DIR.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")

    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)


# ---------------------------------------------------------------------------
# Staging DB -- entirely independent of production (progress + raw acquired data)
# ---------------------------------------------------------------------------

STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS date_progress (
    trading_date  TEXT PRIMARY KEY,
    status        TEXT NOT NULL,      -- pending | done | holiday | failed
    stock_rows    INTEGER DEFAULT 0,
    index_rows    INTEGER DEFAULT 0,
    attempts      INTEGER DEFAULT 0,
    last_error    TEXT,
    started_at    TEXT,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS stock_open_raw (
    symbol            TEXT NOT NULL,
    trading_date      TEXT NOT NULL,
    open              REAL,
    raw_open_text     TEXT,
    high              REAL,
    low               REAL,
    close             REAL,
    volume            INTEGER,
    source            TEXT,
    fetched_at        TEXT,
    valid_numeric     INTEGER,
    valid_positive    INTEGER,
    within_hl_range   INTEGER,
    validation_flags  TEXT,
    in_db             INTEGER,
    db_open           REAL,
    db_high           REAL,
    db_low            REAL,
    db_close          REAL,
    comparison_flags  TEXT,
    PRIMARY KEY (symbol, trading_date)
);

CREATE TABLE IF NOT EXISTS index_open_raw (
    symbol            TEXT NOT NULL,
    trading_date      TEXT NOT NULL,
    open              REAL,
    raw_open_text     TEXT,
    high              REAL,
    low               REAL,
    close             REAL,
    source            TEXT,
    fetched_at        TEXT,
    valid_numeric     INTEGER,
    valid_positive    INTEGER,
    within_hl_range   INTEGER,
    validation_flags  TEXT,
    in_db             INTEGER,
    db_open           REAL,
    db_high           REAL,
    db_low            REAL,
    db_close          REAL,
    comparison_flags  TEXT,
    PRIMARY KEY (symbol, trading_date)
);

CREATE TABLE IF NOT EXISTS duplicate_log (
    trading_date  TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    row_type      TEXT NOT NULL,     -- stock | index
    occurrences   INTEGER NOT NULL
);
"""


def open_staging_db() -> sqlite3.Connection:
    OUTPUT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(STAGING_DB_PATH)
    conn.executescript(STAGING_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Production DB -- strictly read-only, comparison purposes only
# ---------------------------------------------------------------------------

def open_readonly_prod_db(db_path: Path) -> sqlite3.Connection:
    db_path = db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Production DB not found at {db_path}")

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)

    # Self-test: confirm the connection genuinely rejects writes before any
    # scraping begins. WHERE 1=0 can never match a row, but SQLite still
    # evaluates write permission before evaluating the WHERE clause, so this
    # is a safe, side-effect-free way to prove the read-only lock is real.
    try:
        conn.execute("UPDATE prices SET open = open WHERE 1 = 0")
        conn.rollback()
        raise RuntimeError(
            "SAFETY ABORT: read-only self-test did not raise an error -- the "
            "connection to psx_data.db may not be truly read-only. Refusing "
            "to proceed rather than risk a write."
        )
    except sqlite3.OperationalError as exc:
        if "readonly" not in str(exc).lower():
            raise
        logger.info("Read-only self-test passed: production DB write rejected (%s)", exc)

    return conn


def fetch_prod_day(conn: sqlite3.Connection | None, trading_date: str, table: str) -> dict:
    """Return {symbol: (open, high, low, close)} for one date from the given table."""
    if conn is None:
        return {}
    rows = conn.execute(
        f"SELECT symbol, open, high, low, close FROM {table} WHERE date = ?",
        (trading_date,),
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def weekday_range(start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        if _is_weekday(d):
            out.append(d)
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(REQUEST_HEADERS)
    return s


def fetch_html(session: requests.Session, target_date: date) -> str | None:
    date_str = target_date.strftime("%Y-%m-%d")
    payload = {"sdate": date_str}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(MARKET_SUMMARY_URL, data=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Fetch attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, date_str, exc)
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)
    return None


# ---------------------------------------------------------------------------
# Parsing -- extracts Open (cells[2]), which production scraper.py skips.
# Deliberately does NOT clamp high/low to close (see module docstring).
# ---------------------------------------------------------------------------

def _to_float(text: str) -> float | None:
    text = text.replace(",", "").strip()
    if not text or text in ("-", "N/A", "n/a"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_market_summary(html: str):
    """
    Returns (stock_rows, index_rows), each a list of dicts.

    Table layout (per data row, 8 TDs):
      Symbol, Company, Open, High, Low, Close, Change, Vol
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    data_table = tables[-1] if tables else None
    if not data_table:
        return [], []

    rows = data_table.find_all("tr")
    current_sector = None
    stock_rows: list[dict] = []
    index_rows: list[dict] = []

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        if len(cells) == 2:
            second_text = cells[1].get_text(strip=True)
            if "Number of traded companies" in second_text or second_text == "":
                current_sector = cells[0].get_text(strip=True)
                continue

        if cells[0].get_text(strip=True) == "Symbol":
            continue

        if len(cells) != 8:
            continue

        symbol = cells[0].get_text(strip=True)
        if not symbol:
            continue

        open_text = cells[2].get_text(strip=True)
        high_text = cells[3].get_text(strip=True)
        low_text = cells[4].get_text(strip=True)
        close_text = cells[5].get_text(strip=True)
        vol_text = cells[7].get_text(strip=True)

        open_val = _to_float(open_text)
        high_val = _to_float(high_text)
        low_val = _to_float(low_text)
        close_val = _to_float(close_text)

        if close_val is None:
            continue  # no anchor price -- unusable row

        if current_sector == "Market Indexes":
            index_rows.append({
                "symbol": symbol, "open": open_val, "open_text": open_text,
                "high": high_val, "low": low_val, "close": close_val,
            })
            continue

        if symbol in INDEX_SYMBOLS:
            continue

        volume_val = None
        vol_clean = vol_text.replace(",", "").strip()
        if vol_clean:
            try:
                volume_val = int(float(vol_clean))
            except ValueError:
                volume_val = None

        stock_rows.append({
            "symbol": symbol, "open": open_val, "open_text": open_text,
            "high": high_val, "low": low_val, "close": close_val,
            "volume": volume_val,
        })

    return stock_rows, index_rows


# ---------------------------------------------------------------------------
# Validation (per-record, self-consistency -- does not touch the DB)
# ---------------------------------------------------------------------------

def validate_row(open_val: float | None, high_val: float | None, low_val: float | None):
    flags = []
    valid_numeric = open_val is not None
    if not valid_numeric:
        flags.append("NON_NUMERIC")

    valid_positive = valid_numeric and open_val > 0
    if valid_numeric and not valid_positive:
        flags.append("NON_POSITIVE")

    within_range = None
    if valid_numeric and high_val is not None and low_val is not None:
        within_range = low_val <= open_val <= high_val
        if not within_range:
            flags.append("OUTSIDE_HL_RANGE")

    return valid_numeric, valid_positive, within_range, "|".join(flags)


# ---------------------------------------------------------------------------
# Comparison against production DB (validation only -- never written back)
# ---------------------------------------------------------------------------

def _mismatch(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) > MISMATCH_EPSILON


def compare_row(open_val, high_val, low_val, close_val, db_entry):
    if db_entry is None:
        return None, None, None, None, False, "NOT_IN_DB"

    db_open, db_high, db_low, db_close = db_entry
    flags = []
    if _mismatch(high_val, db_high):
        flags.append("HIGH_MISMATCH")
    if _mismatch(low_val, db_low):
        flags.append("LOW_MISMATCH")
    if _mismatch(close_val, db_close):
        flags.append("CLOSE_MISMATCH")
    if db_open is not None and _mismatch(open_val, db_open):
        flags.append("OPEN_MISMATCH")

    return db_open, db_high, db_low, db_close, True, "|".join(flags)


# ---------------------------------------------------------------------------
# Per-date processing
# ---------------------------------------------------------------------------

@dataclass
class RunStats:
    dates_requested: int = 0
    dates_success: int = 0
    dates_holiday: int = 0
    dates_failed: int = 0
    consecutive_failures: int = 0
    aborted_early: bool = False


def _persist_rows(staging_conn, table: str, rows: list[dict], date_str: str,
                   fetched_at: str, prod_day: dict, has_volume: bool) -> int:
    n = 0
    for r in rows:
        valid_numeric, valid_positive, within_range, vflags = validate_row(
            r["open"], r["high"], r["low"]
        )
        db_entry = prod_day.get(r["symbol"])
        db_open, db_high, db_low, db_close, in_db, cflags = compare_row(
            r["open"], r["high"], r["low"], r["close"], db_entry
        )

        within_range_val = None if within_range is None else int(within_range)

        if has_volume:
            staging_conn.execute(
                f"""INSERT OR REPLACE INTO {table}
                    (symbol, trading_date, open, raw_open_text, high, low, close, volume,
                     source, fetched_at, valid_numeric, valid_positive, within_hl_range,
                     validation_flags, in_db, db_open, db_high, db_low, db_close, comparison_flags)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["symbol"], date_str, r["open"], r["open_text"], r["high"], r["low"], r["close"],
                 r["volume"], SOURCE_LABEL, fetched_at, int(valid_numeric), int(valid_positive),
                 within_range_val, vflags, int(bool(in_db)), db_open, db_high, db_low, db_close, cflags),
            )
        else:
            staging_conn.execute(
                f"""INSERT OR REPLACE INTO {table}
                    (symbol, trading_date, open, raw_open_text, high, low, close,
                     source, fetched_at, valid_numeric, valid_positive, within_hl_range,
                     validation_flags, in_db, db_open, db_high, db_low, db_close, comparison_flags)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["symbol"], date_str, r["open"], r["open_text"], r["high"], r["low"], r["close"],
                 SOURCE_LABEL, fetched_at, int(valid_numeric), int(valid_positive),
                 within_range_val, vflags, int(bool(in_db)), db_open, db_high, db_low, db_close, cflags),
            )

        if vflags or cflags:
            logger.info(
                "[FLAG] %s %s open=%s validation=[%s] comparison=[%s]",
                date_str, r["symbol"], r["open"], vflags, cflags,
            )
        n += 1

    staging_conn.commit()
    return n


def process_date(session, staging_conn, prod_conn, target_date: date, stats: RunStats):
    date_str = target_date.strftime("%Y-%m-%d")
    started_at = datetime.now(timezone.utc).isoformat()

    staging_conn.execute(
        """INSERT INTO date_progress (trading_date, status, attempts, started_at)
           VALUES (?, 'pending', 1, ?)
           ON CONFLICT(trading_date) DO UPDATE
               SET attempts = attempts + 1, started_at = excluded.started_at, status = 'pending'""",
        (date_str, started_at),
    )
    staging_conn.commit()

    html = fetch_html(session, target_date)
    fetched_at = datetime.now(timezone.utc).isoformat()

    if html is None:
        stats.dates_failed += 1
        stats.consecutive_failures += 1
        staging_conn.execute(
            "UPDATE date_progress SET status='failed', last_error=?, finished_at=? WHERE trading_date=?",
            ("fetch failed after retries", fetched_at, date_str),
        )
        staging_conn.commit()
        logger.error("[FAILED] %s -- fetch exhausted retries", date_str)

        if stats.consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            backoff = min(FAILURE_BACKOFF_BASE * stats.consecutive_failures, FAILURE_BACKOFF_MAX)
            logger.warning(
                "Pausing %ds before the next date (consecutive failures: %d/%d) -- "
                "giving a possible transient network/DNS blip time to clear before "
                "the circuit breaker trips.",
                backoff, stats.consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            time.sleep(backoff)
        return

    stock_rows, index_rows = parse_market_summary(html)

    if not stock_rows and not index_rows:
        stats.dates_holiday += 1
        stats.consecutive_failures = 0
        staging_conn.execute(
            "UPDATE date_progress SET status='holiday', stock_rows=0, index_rows=0, finished_at=? WHERE trading_date=?",
            (fetched_at, date_str),
        )
        staging_conn.commit()
        logger.info("[HOLIDAY] %s -- no trading data returned (weekend-adjacent holiday or thin/frozen session)", date_str)
        return

    # Duplicate detection: same symbol appearing more than once on one page
    for row_type, rows in (("stock", stock_rows), ("index", index_rows)):
        counts = Counter(r["symbol"] for r in rows)
        for sym, cnt in counts.items():
            if cnt > 1:
                staging_conn.execute(
                    "INSERT INTO duplicate_log (trading_date, symbol, row_type, occurrences) VALUES (?, ?, ?, ?)",
                    (date_str, sym, row_type, cnt),
                )
                logger.warning("[DUPLICATE] %s %s appears %d times in %s rows", date_str, sym, cnt, row_type)

    prod_stock_day = fetch_prod_day(prod_conn, date_str, "prices")
    prod_index_day = fetch_prod_day(prod_conn, date_str, "index_prices")

    stock_n = _persist_rows(staging_conn, "stock_open_raw", stock_rows, date_str, fetched_at, prod_stock_day, has_volume=True)
    index_n = _persist_rows(staging_conn, "index_open_raw", index_rows, date_str, fetched_at, prod_index_day, has_volume=False)

    staging_conn.execute(
        "UPDATE date_progress SET status='done', stock_rows=?, index_rows=?, finished_at=? WHERE trading_date=?",
        (stock_n, index_n, fetched_at, date_str),
    )
    staging_conn.commit()

    stats.dates_success += 1
    stats.consecutive_failures = 0
    logger.info("[OK] %s -- %d stock rows, %d index rows", date_str, stock_n, index_n)


# ---------------------------------------------------------------------------
# Main acquisition loop
# ---------------------------------------------------------------------------

def determine_dates_to_process(staging_conn, all_dates: list[date], force: bool) -> list[date]:
    if force:
        return all_dates
    done_or_holiday = {
        row[0] for row in staging_conn.execute(
            "SELECT trading_date FROM date_progress WHERE status IN ('done', 'holiday')"
        ).fetchall()
    }
    return [d for d in all_dates if d.strftime("%Y-%m-%d") not in done_or_holiday]


def run_acquisition(start: date, end: date, force: bool, use_db_compare: bool):
    setup_logging()
    logger.info("=== Open Price Acquisition started: %s -> %s ===", start, end)

    staging_conn = open_staging_db()
    prod_conn = open_readonly_prod_db(PROD_DB_PATH) if use_db_compare else None
    if not use_db_compare:
        logger.warning("Running with --no-db-compare: cross-validation against psx_data.db is DISABLED")

    all_dates = weekday_range(start, end)
    to_process = determine_dates_to_process(staging_conn, all_dates, force)
    logger.info(
        "%d weekday dates in requested range, %d remaining to process (resume-aware)",
        len(all_dates), len(to_process),
    )

    stats = RunStats(dates_requested=len(to_process))
    session = build_session()
    run_started = time.time()

    for i, d in enumerate(to_process, 1):
        process_date(session, staging_conn, prod_conn, d, stats)

        if stats.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.critical(
                "ABORTING RUN: %d consecutive fetch failures -- the source may be unreachable "
                "or its page structure may have changed. Stopped at %s (%d/%d dates attempted "
                "this run). Already-completed dates remain safely recorded; rerun the same "
                "command later to resume.",
                stats.consecutive_failures, d, i, len(to_process),
            )
            stats.aborted_early = True
            break

        if i < len(to_process):
            time.sleep(REQUEST_DELAY)

    runtime = time.time() - run_started
    logger.info("=== Acquisition loop finished in %.1f min ===", runtime / 60)

    export_csvs(staging_conn)
    summary = build_summary_report(staging_conn, start, end, stats, runtime)
    write_summary(summary)

    if prod_conn:
        prod_conn.close()
    staging_conn.close()

    if stats.aborted_early:
        remaining = len(to_process) - i
        logger.warning(
            "RUN INCOMPLETE: stopped early after the consecutive-failure circuit breaker "
            "tripped. %d date(s) in the requested range were never attempted this run. "
            "Rerun the same command to resume -- already-completed dates are skipped "
            "automatically. Full audit report: %s",
            remaining, SUMMARY_PATH,
        )
    else:
        logger.info("Done -- full requested range completed. Full audit report: %s", SUMMARY_PATH)
    return summary


# ---------------------------------------------------------------------------
# CSV export (regenerable at any time from the staging DB)
# ---------------------------------------------------------------------------

STOCK_CSV_COLUMNS = [
    "symbol", "trading_date", "open", "raw_open_text", "high", "low", "close", "volume",
    "source", "fetched_at", "valid_numeric", "valid_positive", "within_hl_range",
    "validation_flags", "in_db", "db_open", "db_high", "db_low", "db_close", "comparison_flags",
]
INDEX_CSV_COLUMNS = [c for c in STOCK_CSV_COLUMNS if c != "volume"]


def _export_table(staging_conn, table: str, columns: list[str], out_path: Path):
    cols_sql = ", ".join(columns)
    rows = staging_conn.execute(
        f"SELECT {cols_sql} FROM {table} ORDER BY trading_date, symbol"
    ).fetchall()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def export_csvs(staging_conn):
    _export_table(staging_conn, "stock_open_raw", STOCK_CSV_COLUMNS, STOCK_CSV_PATH)
    _export_table(staging_conn, "index_open_raw", INDEX_CSV_COLUMNS, INDEX_CSV_PATH)
    logger.info("Exported %s and %s", STOCK_CSV_PATH.name, INDEX_CSV_PATH.name)


# ---------------------------------------------------------------------------
# Summary / audit report
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def build_summary_report(staging_conn, start: date, end: date, stats: RunStats, runtime_sec: float) -> dict:
    def count(sql: str, params: tuple = ()) -> int:
        return staging_conn.execute(sql, params).fetchone()[0]

    total_stock_rows = count("SELECT COUNT(*) FROM stock_open_raw")
    total_index_rows = count("SELECT COUNT(*) FROM index_open_raw")
    duplicate_rows = count("SELECT COUNT(*) FROM duplicate_log")

    invalid_open = (
        count("SELECT COUNT(*) FROM stock_open_raw WHERE valid_numeric = 0")
        + count("SELECT COUNT(*) FROM index_open_raw WHERE valid_numeric = 0")
    )
    nonpositive_open = (
        count("SELECT COUNT(*) FROM stock_open_raw WHERE valid_numeric = 1 AND valid_positive = 0")
        + count("SELECT COUNT(*) FROM index_open_raw WHERE valid_numeric = 1 AND valid_positive = 0")
    )
    outside_range = (
        count("SELECT COUNT(*) FROM stock_open_raw WHERE within_hl_range = 0")
        + count("SELECT COUNT(*) FROM index_open_raw WHERE within_hl_range = 0")
    )
    hlc_mismatches = (
        count("""SELECT COUNT(*) FROM stock_open_raw WHERE
                  comparison_flags LIKE '%HIGH_MISMATCH%' OR
                  comparison_flags LIKE '%LOW_MISMATCH%' OR
                  comparison_flags LIKE '%CLOSE_MISMATCH%'""")
        + count("""SELECT COUNT(*) FROM index_open_raw WHERE
                    comparison_flags LIKE '%HIGH_MISMATCH%' OR
                    comparison_flags LIKE '%LOW_MISMATCH%' OR
                    comparison_flags LIKE '%CLOSE_MISMATCH%'""")
    )
    open_mismatches = (
        count("SELECT COUNT(*) FROM stock_open_raw WHERE comparison_flags LIKE '%OPEN_MISMATCH%'")
        + count("SELECT COUNT(*) FROM index_open_raw WHERE comparison_flags LIKE '%OPEN_MISMATCH%'")
    )
    not_in_db = (
        count("SELECT COUNT(*) FROM stock_open_raw WHERE in_db = 0")
        + count("SELECT COUNT(*) FROM index_open_raw WHERE in_db = 0")
    )

    date_counts = dict(staging_conn.execute(
        "SELECT status, COUNT(*) FROM date_progress GROUP BY status"
    ).fetchall())

    return {
        "report_generated_utc": datetime.now(timezone.utc).isoformat(),
        "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
        "runtime_minutes": round(runtime_sec / 60, 2),
        "aborted_early": stats.aborted_early,
        "dates": {
            "done": date_counts.get("done", 0),
            "holiday": date_counts.get("holiday", 0),
            "failed": date_counts.get("failed", 0),
            "total_tracked_in_staging_db": sum(date_counts.values()),
        },
        "rows": {
            "total_stock_rows": total_stock_rows,
            "total_index_rows": total_index_rows,
            "duplicate_rows_detected": duplicate_rows,
        },
        "validation": {
            "invalid_open_non_numeric": invalid_open,
            "open_non_positive": nonpositive_open,
            "open_outside_high_low_range": outside_range,
        },
        "comparison_vs_production_db": {
            "not_found_in_db": not_in_db,
            "high_low_close_mismatches": hlc_mismatches,
            "open_mismatches": open_mismatches,
            "note": (
                "HIGH/LOW mismatches are expected in some volume: production scraper.py "
                "clamps high>=close>=low before storing, this tool does not. CLOSE or "
                "OPEN mismatches are more likely to indicate a real anomaly worth reviewing."
            ),
        },
        "output_files": {
            "stock_csv": str(STOCK_CSV_PATH),
            "stock_csv_sha256": sha256_of(STOCK_CSV_PATH),
            "index_csv": str(INDEX_CSV_PATH),
            "index_csv_sha256": sha256_of(INDEX_CSV_PATH),
        },
    }


def write_summary(summary: dict):
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info("Summary report written to %s", SUMMARY_PATH)
    logger.info("%s", json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--start", type=str, default=DEFAULT_START.isoformat(),
                         help="Start date YYYY-MM-DD (default 2005-01-01)")
    parser.add_argument("--end", type=str, default=(date.today() - timedelta(days=1)).isoformat(),
                         help="End date YYYY-MM-DD (default yesterday, to avoid a same-day partial session)")
    parser.add_argument("--force", action="store_true",
                         help="Re-scrape dates already marked done/holiday in the staging DB")
    parser.add_argument("--spot-check", action="store_true",
                         help="Run 3 known dates only, to validate the parser before a full run")
    parser.add_argument("--no-db-compare", action="store_true",
                         help="Skip all interaction with psx_data.db (acquisition-only, no cross-validation)")
    parser.add_argument("--export-only", action="store_true",
                         help="Regenerate CSVs + summary report from the existing staging DB; no scraping")
    args = parser.parse_args()

    if args.export_only:
        setup_logging()
        staging_conn = open_staging_db()
        export_csvs(staging_conn)
        summary = build_summary_report(staging_conn, DEFAULT_START, date.today(), RunStats(), 0.0)
        write_summary(summary)
        staging_conn.close()
        return

    if args.spot_check:
        setup_logging()
        logger.info("=== Spot check: %s ===", SPOT_CHECK_DATES)
        staging_conn = open_staging_db()
        prod_conn = None if args.no_db_compare else open_readonly_prod_db(PROD_DB_PATH)
        stats = RunStats(dates_requested=len(SPOT_CHECK_DATES))
        session = build_session()
        for i, d in enumerate(SPOT_CHECK_DATES, 1):
            process_date(session, staging_conn, prod_conn, d, stats)
            if i < len(SPOT_CHECK_DATES):
                time.sleep(REQUEST_DELAY)
        export_csvs(staging_conn)
        logger.info("Spot check complete: %s", stats)
        if prod_conn:
            prod_conn.close()
        staging_conn.close()
        return

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end:
        raise SystemExit(f"--start ({start}) must be <= --end ({end})")

    run_acquisition(start, end, force=args.force, use_db_compare=not args.no_db_compare)


if __name__ == "__main__":
    main()
