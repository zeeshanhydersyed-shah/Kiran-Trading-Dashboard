"""
Phase 1 — Historical data backfill for KIRAN ML pipeline.

Scrapes PSX daily closes from a target start date up to the earliest date
already in the database, then merges everything in.

Usage:
    python backfill_history.py                  # default: from 2024-01-01
    python backfill_history.py 2023-01-01       # custom start date
"""

import sys
import logging
import time
from datetime import date, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backfill_history.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from database import init_db, upsert_sectors, upsert_prices, upsert_index_prices, get_price_date_range, count_prices
from scraper import build_session, scrape_date, scrape_date_range

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_START = date(2024, 1, 1)
BATCH_SIZE    = 20      # scrape N dates, then upsert — keeps memory low
SAVE_INTERVAL = 20      # log progress every N dates


def weekdays_between(start: date, end: date) -> list[date]:
    """Return Mon–Fri dates from start up to (but not including) end."""
    result = []
    d = start
    while d < end:
        if d.weekday() < 5:
            result.append(d)
        d += timedelta(days=1)
    return result


def test_date(target: date, session) -> bool:
    """Quick check: does the website return data for this date?"""
    logger.info("Testing website availability for %s …", target)
    s_rows, p_rows, i_rows = scrape_date(target, session)
    if p_rows:
        logger.info("  OK  Got %d price records - website has data for %s", len(p_rows), target)
        return True
    logger.warning("  FAIL  No data returned for %s", target)
    return False


def main():
    start_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_START

    init_db()
    mn, mx = get_price_date_range()
    logger.info("Current DB range: %s to %s  (%d price records)", mn, mx, count_prices())

    # Determine scrape window: start_date up to the day before earliest DB date
    if mn:
        earliest_in_db = date.fromisoformat(mn)
        scrape_end = earliest_in_db      # exclusive upper bound
    else:
        scrape_end = date.today()

    if start_date >= scrape_end:
        logger.info("Nothing to backfill — DB already starts on or before %s.", start_date)
        return

    all_dates = weekdays_between(start_date, scrape_end)
    logger.info(
        "Backfill window: %s → %s  (%d weekdays to scrape)",
        start_date, scrape_end - timedelta(days=1), len(all_dates),
    )

    session = build_session()

    # ── Probe a known trading day near the start date ─────────────────────────
    # Jan 2 2024 was a Tuesday — good test
    probe = date(2024, 1, 2)
    if probe >= scrape_end:
        probe = all_dates[0] if all_dates else start_date
    if not test_date(probe, session):
        logger.error("Website does not appear to serve data for %s. Aborting.", probe)
        return
    time.sleep(2)

    # ── Scrape in batches ─────────────────────────────────────────────────────
    total      = len(all_dates)
    done       = 0
    skipped    = 0
    total_px   = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = all_dates[batch_start : batch_start + BATCH_SIZE]
        sector_rows, price_rows, index_rows = scrape_date_range(batch, session)

        if price_rows:
            upsert_sectors(sector_rows)
            upsert_prices(price_rows)
            total_px += len(price_rows)
        if index_rows:
            upsert_index_prices(index_rows)
        else:
            skipped += len(batch)

        done += len(batch)
        pct   = done / total * 100
        logger.info(
            "Progress: %d/%d dates (%.0f%%)  |  %d price records stored so far",
            done, total, pct, count_prices(),
        )

    # ── Final summary ─────────────────────────────────────────────────────────
    mn2, mx2 = get_price_date_range()
    logger.info("=" * 60)
    logger.info("Backfill complete.")
    logger.info("  Date range now : %s to %s", mn2, mx2)
    logger.info("  Total prices   : %d", count_prices())
    logger.info("  New records    : ~%d", total_px)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
