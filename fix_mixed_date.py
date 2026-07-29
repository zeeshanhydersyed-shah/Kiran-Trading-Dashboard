"""
Surgical fix: Move 2026-06-02 data back to 2026-06-01 (it's the morning's stale scrape).
This fixes the mixed date issue without deleting anything.
"""

from datetime import date, timedelta
from database import get_conn

def fix_mixed_date():
    with get_conn() as conn:
        cursor = conn.cursor()

        today = date.today().strftime("%Y-%m-%d")
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Check current state
        cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (today,))
        today_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (yesterday,))
        yesterday_count = cursor.fetchone()[0]

        print(f"Current state:")
        print(f"  {today}: {today_count} rows")
        print(f"  {yesterday}: {yesterday_count} rows")
        print()

        if today_count == 0:
            print("✓ No data for today — nothing to fix.")
            return

        print(f"Deleting {today_count} rows from {today}")
        print("(The morning's stale scrape will be removed so the scraper can re-fetch clean data.)")
        response = input(f"Proceed? (y/n): ")

        if response.lower() != 'y':
            print("Cancelled.")
            return

        # Delete prices for today (stale morning scrape)
        cursor.execute("DELETE FROM prices WHERE date = ?", (today,))
        prices_deleted = cursor.rowcount

        # Delete index_prices for today (stale morning scrape)
        cursor.execute("DELETE FROM index_prices WHERE date = ?", (today,))
        index_deleted = cursor.rowcount

        print(f"✓ Deleted {prices_deleted} stale price rows from {today}")
        print(f"✓ Deleted {index_deleted} stale index rows from {today}")
        print()
        print("Next step: Run 'python main.py --update' to scrape fresh data.")

if __name__ == "__main__":
    fix_mixed_date()
