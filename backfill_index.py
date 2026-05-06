"""
Backfill KSE-100 (and other index) historical data into index_prices table.

Scrapes ksestocks.com MarketSummary for every date in the prices table
and stores the Market Indexes section into index_prices.

Only inserts rows that don't already exist (safe to re-run).

Usage:
    python backfill_index.py
"""

import logging
import sys
import time

import requests
from bs4 import BeautifulSoup

from config import (
    MARKET_SUMMARY_URL, REQUEST_DELAY, REQUEST_HEADERS, MAX_RETRIES,
)
from database import get_conn, init_db, upsert_index_prices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def get_all_price_dates() -> list[str]:
    """Return all distinct dates in the prices table, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM prices ORDER BY date"
        ).fetchall()
    return [r[0] for r in rows]


def get_indexed_dates() -> set[str]:
    """Dates already in index_prices for KSE-100."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM index_prices WHERE symbol = 'KSE-100'"
        ).fetchall()
    return {r[0] for r in rows}


def scrape_index_for_date(date_str: str, session: requests.Session) -> list[tuple]:
    """
    Scrape the Market Indexes section for one date.
    Returns list of (symbol, date, high, low, close) tuples.
    """
    payload = {"sdate": date_str}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(MARKET_SUMMARY_URL, data=payload, timeout=30)
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as exc:
            log.warning("Attempt %d/%d failed for %s: %s",
                        attempt, MAX_RETRIES, date_str, exc)
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)
    else:
        return []

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    data_table = tables[-1] if tables else None
    if not data_table:
        return []

    results = []
    current_sector = None

    for row in data_table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue

        # Sector header
        if len(cells) == 2:
            second = cells[1].get_text(strip=True)
            if "Number of traded companies" in second or second == "":
                current_sector = cells[0].get_text(strip=True)
            continue

        if cells[0].get_text(strip=True) == "Symbol":
            continue

        # Only capture Market Indexes rows
        if len(cells) == 8 and current_sector == "Market Indexes":
            symbol     = cells[0].get_text(strip=True)
            high_text  = cells[3].get_text(strip=True).replace(",", "")
            low_text   = cells[4].get_text(strip=True).replace(",", "")
            close_text = cells[5].get_text(strip=True).replace(",", "")

            if not symbol or symbol == "Symbol":
                continue

            try:
                close = float(close_text)
                high  = float(high_text)  if high_text  else close
                low   = float(low_text)   if low_text   else close
                high  = max(high, close)
                low   = min(low,  close)
                results.append((symbol, date_str, high, low, close))
            except ValueError:
                continue

    return results


def main():
    init_db()

    all_dates     = get_all_price_dates()
    indexed_dates = get_indexed_dates()
    todo          = [d for d in all_dates if d not in indexed_dates]

    log.info("Total price dates  : %d", len(all_dates))
    log.info("Already indexed    : %d", len(indexed_dates))
    log.info("Dates to backfill  : %d", len(todo))

    if not todo:
        log.info("index_prices already complete for KSE-100. Nothing to do.")
        return

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    total_rows = 0
    for i, date_str in enumerate(todo, 1):
        rows = scrape_index_for_date(date_str, session)
        if rows:
            upsert_index_prices(rows)
            total_rows += len(rows)

        kse = next((r for r in rows if r[0] == "KSE-100"), None)
        kse_str = f"KSE-100={kse[4]:,.0f}" if kse else "no KSE-100"
        log.info("[%d/%d] %s — %d index rows  (%s)",
                 i, len(todo), date_str, len(rows), kse_str)

        if i < len(todo):
            time.sleep(REQUEST_DELAY)

    log.info("Backfill complete. Total index rows inserted: %d", total_rows)

    # Final check
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM index_prices WHERE symbol='KSE-100'"
        ).fetchone()[0]
    log.info("KSE-100 rows in DB: %d", count)


if __name__ == "__main__":
    main()
