"""
Backup step for the 2026-07-31 production data fix (see docs/KIRAN_CLEANUP_AUDIT.md
Section 16). Dumps the full production index_prices and market_regime tables to
timestamped CSVs before any write, so there is a restore path if anything goes wrong.
Read-only -- makes no changes to the database.
"""
import os
import csv
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\Lenovo\psx_pipeline\.env")
import psycopg2

url = os.environ.get("SUPABASE_DB_URL")
conn = psycopg2.connect(url)
cur = conn.cursor()

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

for table, order in [
    ("index_prices", "symbol, date"),
    ("market_regime", "date"),
]:
    cur.execute(f"SELECT * FROM {table} ORDER BY {order}")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    out_path = os.path.join(OUT_DIR, f"{table}_backup_2026-07-31.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(rows)
    print(f"Backed up {table}: {len(rows)} rows -> {out_path}")

conn.close()
