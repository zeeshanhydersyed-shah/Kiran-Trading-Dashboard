"""Check what sector GAL ends up in after the scraper's override logic."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, timedelta
from scraper import build_session, scrape_date_range

session = build_session()

# Find the last trading day
dates = []
for offset in range(1, 8):
    d = date.today() - timedelta(days=offset)
    if d.weekday() < 5:
        dates.append(d)
        break

sector_rows, price_rows, _ = scrape_date_range(dates, session)

sector_map = dict(sector_rows)
print(f"GAL sector (after override): {sector_map.get('GAL', 'NOT FOUND')!r}")
print(f"\nAll AUTOMOBILE ASSEMBLER stocks from this scrape:")
for sym, sec in sorted(sector_map.items()):
    if sec == "AUTOMOBILE ASSEMBLER":
        print(f"  {sym}")
