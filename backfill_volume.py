"""
Volume backfill — re-scrapes every date that has price records but NULL volume,
then UPDATEs the volume column in-place (close prices are never touched).

Usage:
    python backfill_volume.py          # fills all dates missing volume
    python backfill_volume.py 2025-01-01  # only dates on/after this date
"""

import sys
import logging
import time
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backfill_volume.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from database import init_db, get_conn, upsert_prices
from scraper import build_session, scrape_date
from config import REQUEST_DELAY

BATCH_SIZE = 20


def get_dates_needing_volume(since: date | None = None) -> list[date]:
    """Return all distinct dates where at least one price row has NULL volume."""
    with get_conn() as conn:
        if since:
            rows = conn.execute(
                """SELECT DISTINCT date FROM prices
                   WHERE volume IS NULL AND date >= ?
                   ORDER BY date""",
                (since.isoformat(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT date FROM prices
                   WHERE volume IS NULL
                   ORDER BY date"""
            ).fetchall()
    return [date.fromisoformat(r[0]) for r in rows]


def main():
    since = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None

    init_db()

    dates = get_dates_needing_volume(since)
    if not dates:
        logger.info("No dates found with missing volume. Nothing to do.")
        return

    logger.info(
        "Found %d dates needing volume backfill  (%s to %s)",
        len(dates), dates[0], dates[-1],
    )

    session  = build_session()
    total    = len(dates)
    filled   = 0
    skipped  = 0

    for idx, d in enumerate(dates, 1):
        _, price_rows, _idx = scrape_date(d, session)

        if price_rows:
            upsert_prices(price_rows)   # ON CONFLICT DO UPDATE — fills volume only
            filled += 1
        else:
            logger.warning("No data returned for %s — skipping", d)
            skipped += 1

        if idx % BATCH_SIZE == 0 or idx == total:
            pct = idx / total * 100
            logger.info(
                "Progress: %d/%d (%.0f%%)  |  filled=%d  skipped=%d",
                idx, total, pct, filled, skipped,
            )

        if idx < total:
            time.sleep(REQUEST_DELAY)

    logger.info("=" * 60)
    logger.info("Volume backfill complete.")
    logger.info("  Dates filled   : %d", filled)
    logger.info("  Dates skipped  : %d", skipped)

    # Quick sanity check
    with get_conn() as conn:
        still_null = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE volume IS NULL"
        ).fetchone()[0]
    logger.info("  Dates still missing volume: %d", still_null)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
