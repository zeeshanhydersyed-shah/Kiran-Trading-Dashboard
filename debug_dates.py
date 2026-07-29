"""Debug script to see what dates and data are in the database."""

from datetime import date, timedelta
from database import get_conn

with get_conn() as conn:
    cursor = conn.cursor()

    # Get all distinct dates in the database
    cursor.execute("SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 10")
    dates = [row[0] for row in cursor.fetchall()]
    print("Latest 10 dates in prices table:")
    for d in dates:
        cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (d,))
        count = cursor.fetchone()[0]
        print(f"  {d}: {count} rows")

    print("\n" + "="*60)

    # Check today and yesterday specifically
    today = date.today().strftime("%Y-%m-%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\nToday ({today}):")
    cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (today,))
    today_count = cursor.fetchone()[0]
    print(f"  Total rows: {today_count}")

    if today_count > 0:
        cursor.execute("SELECT symbol, open, high, low, close FROM prices WHERE date = ? LIMIT 3", (today,))
        print("  Sample rows:")
        for row in cursor.fetchall():
            print(f"    {row}")

    print(f"\nYesterday ({yesterday}):")
    cursor.execute("SELECT COUNT(*) FROM prices WHERE date = ?", (yesterday,))
    yesterday_count = cursor.fetchone()[0]
    print(f"  Total rows: {yesterday_count}")

    if yesterday_count > 0:
        cursor.execute("SELECT symbol, open, high, low, close FROM prices WHERE date = ? LIMIT 3", (yesterday,))
        print("  Sample rows:")
        for row in cursor.fetchall():
            print(f"    {row}")

    # Check if they're identical
    if today_count > 0 and yesterday_count > 0:
        cursor.execute("""
            SELECT COUNT(*) FROM prices p1
            WHERE p1.date = ?
            AND EXISTS (
                SELECT 1 FROM prices p2
                WHERE p2.date = ?
                AND p1.symbol = p2.symbol
                AND p1.open IS p2.open
                AND p1.high IS p2.high
                AND p1.low IS p2.low
                AND p1.close = p2.close
            )
        """, (today, yesterday))
        matches = cursor.fetchone()[0]
        print(f"\nMatching rows (same OHLC): {matches}/{today_count}")
