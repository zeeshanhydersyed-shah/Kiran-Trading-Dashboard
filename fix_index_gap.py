"""
fix_index_gap.py
----------------
Fetches missing index_prices data for June 6, 8-11 from ksestocks.com
and inserts into psx_data.db. Does NOT touch today (June 12).

Run from psx_pipeline root:
    python fix_index_gap.py
"""

import sqlite3, os
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(BASE, "psx_data.db")

# Only the missing dates — explicitly listed, today excluded
MISSING_DATES = [
    date(2026, 6,  6),   # Friday
    date(2026, 6,  8),   # Monday
    date(2026, 6,  9),
    date(2026, 6, 10),
    date(2026, 6, 11),
]

from scraper import scrape_date, build_session

session = build_session()
all_index_rows = []

for d in MISSING_DATES:
    print(f"Scraping {d} ...", end=" ", flush=True)
    try:
        _, _, index_rows = scrape_date(d, session)
        if index_rows:
            all_index_rows.extend(index_rows)
            print(f"{len(index_rows)} index rows")
        else:
            print("no data (holiday or not published yet)")
    except Exception as e:
        print(f"ERROR: {e}")

print(f"\nTotal index rows recovered: {len(all_index_rows)}")
if not all_index_rows:
    print("Nothing to insert.")
else:
    # index_rows from scraper: (symbol, date_str, high, low, close)
    # index_prices schema:      symbol, date, high, low, close, open
    rows_to_insert = [(r[0], r[1], r[2], r[3], r[4], None) for r in all_index_rows]

    con = sqlite3.connect(LIVE)
    con.execute("BEGIN")
    con.executemany(
        "INSERT OR IGNORE INTO index_prices(symbol,date,high,low,close,open) VALUES(?,?,?,?,?,?)",
        rows_to_insert
    )
    con.commit()
    cur = con.cursor()
    cur.execute("SELECT MAX(date) FROM index_prices")
    print(f"Latest index date in DB: {cur.fetchone()[0]}")
    cur.execute("SELECT symbol,date,close FROM index_prices WHERE date>='2026-06-06' ORDER BY symbol,date")
    for r in cur.fetchall():
        print(f"  {r}")
    con.close()

print("\n✅ Done. Restart Kiran.")
