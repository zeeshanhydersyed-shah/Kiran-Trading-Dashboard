"""
Backfill HIGH and LOW prices for all existing price rows.

The scraper now captures High (cells[3]) and Low (cells[4]) from the
ksestocks.com market summary table, but historical rows have NULL high/low.

This script re-scrapes every date that has prices but NULL high values
and updates ONLY the high and low columns (close is never touched).

Usage:
    python backfill_high_low.py
"""

import logging
import sys
import sqlite3
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config import (
    MARKET_SUMMARY_URL, REQUEST_DELAY, REQUEST_HEADERS,
    MAX_RETRIES, INDEX_SYMBOLS,
)
from database import get_conn, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def get_dates_needing_hl() -> list[str]:
    """Return all dates where at least one row has NULL high."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT date FROM prices
               WHERE high IS NULL
               ORDER BY date"""
        ).fetchall()
    return [r[0] for r in rows]


def scrape_hl_for_date(date_str: str, session: requests.Session) -> dict[str, tuple]:
    """
    Scrape High and Low for all symbols on a given date.
    Returns {symbol: (high, low)} dict.
    """
    payload = {"sdate": date_str}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(MARKET_SUMMARY_URL, data=payload, timeout=30)
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as exc:
            log.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, date_str, exc)
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)
    else:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    data_table = tables[-1] if tables else None
    if not data_table:
        return {}

    result = {}
    current_sector = None
    for row in data_table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        if len(cells) == 2:
            second = cells[1].get_text(strip=True)
            if "Number of traded companies" in second or second == "":
                current_sector = cells[0].get_text(strip=True)
            continue
        if cells[0].get_text(strip=True) == "Symbol":
            continue
        if len(cells) == 8 and current_sector and current_sector != "Market Indexes":
            symbol    = cells[0].get_text(strip=True)
            high_text = cells[3].get_text(strip=True).replace(",", "")
            low_text  = cells[4].get_text(strip=True).replace(",", "")
            close_text= cells[5].get_text(strip=True).replace(",", "")
            if symbol in INDEX_SYMBOLS or not symbol:
                continue
            try:
                close = float(close_text)
                high  = float(high_text) if high_text else close
                low   = float(low_text)  if low_text  else close
                high  = max(high, close)
                low   = min(low,  close)
                result[symbol] = (high, low)
            except ValueError:
                continue
    return result


def update_hl(date_str: str, hl_map: dict[str, tuple]) -> int:
    """UPDATE high and low for matching (symbol, date) rows. Returns rows updated."""
    if not hl_map:
        return 0
    rows = [(h, l, sym, date_str) for sym, (h, l) in hl_map.items()]
    with get_conn() as conn:
        conn.executemany(
            """UPDATE prices SET high = ?, low = ?
               WHERE symbol = ? AND date = ? AND high IS NULL""",
            rows,
        )
    return len(rows)


def main():
    init_db()   # runs migrations — adds high/low columns if missing
    dates = get_dates_needing_hl()
    log.info("Dates needing H/L backfill: %d", len(dates))
    if not dates:
        log.info("All rows already have H/L data. Nothing to do.")
        return

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    total_updated = 0
    for i, date_str in enumerate(dates, 1):
        hl_map = scrape_hl_for_date(date_str, session)
        n = update_hl(date_str, hl_map)
        total_updated += n
        log.info("[%d/%d] %s — %d symbols updated", i, len(dates), date_str, n)
        if i < len(dates):
            time.sleep(REQUEST_DELAY)

    log.info("Backfill complete. Total rows updated: %d", total_updated)

    # Report remaining NULLs
    with get_conn() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE high IS NULL"
        ).fetchone()[0]
    log.info("Rows still missing H/L: %d", remaining)


if __name__ == "__main__":
    main()
