"""
One-time fix: relabel mislabeled 2026-06-02 data as 2026-06-01.
This fixes data scraped this morning before the market data was available.
"""

from datetime import date, timedelta
from database import get_conn

def fix_mislabeled_date():
    """Relabel today's data as yesterday if it's stale (identical to yesterday's)."""
    with get_conn() as conn:
        cursor = conn.cursor()

        today = date.today()
        yesterday = today - timedelta(days=1)

        today_str = today.strftime("%Y-%m-%d")
        yesterday_str = yesterday.strftime("%Y-%m-%d")

        print(f"Checking for mislabeled data: {today_str} → {yesterday_str}")

        # Check if today's data exists
        cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (today_str,))
        today_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (yesterday_str,))
        yesterday_count = cursor.fetchone()[0]

        if today_count == 0:
            print(f"✓ No data for {today_str} — nothing to fix.")
            return

        if yesterday_count == 0:
            print(f"⚠ No data for {yesterday_str} to compare against.")
            print(f"  Found {today_count} rows for {today_str}.")
            response = input(f"Relabel these {today_count} rows as {yesterday_str}? (y/n): ")
            if response.lower() == 'y':
                cursor.execute(
                    "UPDATE prices SET date = ? WHERE date = ?",
                    (yesterday_str, today_str)
                )
                cursor.execute(
                    "UPDATE index_prices SET date = ? WHERE date = ?",
                    (yesterday_str, today_str)
                )
                affected = cursor.rowcount
                print(f"✓ Relabeled {affected} rows to {yesterday_str}")
            else:
                print("Cancelled.")
        else:
            # Compare fingerprints: are they identical?
            cursor.execute(
                """
                SELECT COUNT(DISTINCT symbol) FROM (
                    SELECT symbol, high, low, close FROM prices WHERE date = ?
                    INTERSECT
                    SELECT symbol, high, low, close FROM prices WHERE date = ?
                )
                """,
                (today_str, yesterday_str)
            )
            matches = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT symbol) FROM prices WHERE date = ?", (yesterday_str,))
            yesterday_symbols = cursor.fetchone()[0]

            if yesterday_symbols > 0 and matches / yesterday_symbols > 0.90:
                print(f"✓ Detected stale data: {matches}/{yesterday_symbols} symbols identical")
                print(f"  {today_count} rows for {today_str} are actually {yesterday_str} data")

                cursor.execute(
                    "UPDATE prices SET date = ? WHERE date = ?",
                    (yesterday_str, today_str)
                )
                cursor.execute(
                    "UPDATE index_prices SET date = ? WHERE date = ?",
                    (yesterday_str, today_str)
                )
                affected = cursor.rowcount
                print(f"✓ Relabeled {affected} rows to {yesterday_str}")
            else:
                print(f"✗ Data for {today_str} does NOT match {yesterday_str}")
                print(f"  This may be legitimate new data. Not relabeling.")

if __name__ == "__main__":
    fix_mislabeled_date()
