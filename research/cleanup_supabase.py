"""
One-time cleanup: remove holiday ghost rows from Supabase.
Run as:  DATABASE_URL="postgresql://..." python cleanup_supabase.py
"""
import os, sys

url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
if not url:
    print("ERROR: set DATABASE_URL env var before running this script.")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(__file__))
from database_pg import cleanup_ghost_dates, get_price_date_range

mn, mx = get_price_date_range()
print(f"Supabase price range: {mn} → {mx}")

deleted = cleanup_ghost_dates()
print(f"Deleted {deleted} ghost rows.")

mn2, mx2 = get_price_date_range()
print(f"Price range after cleanup: {mn2} → {mx2}")
