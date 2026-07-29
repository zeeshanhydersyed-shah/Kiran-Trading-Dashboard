import sqlite3
con = sqlite3.connect("psx_data.db")

print("=== leaders_scan ===")
rows = con.execute(
    "SELECT scan_date, setup_type, symbol, final_score, flag FROM leaders_scan ORDER BY setup_type, final_score DESC"
).fetchall()
for r in rows:
    print(r)

print()
print("=== leaders_top_picks ===")
rows = con.execute(
    "SELECT scan_date, setup_type, rank, symbol, entry_trigger, sl_pct, key_reason FROM leaders_top_picks ORDER BY setup_type, rank"
).fetchall()
for r in rows:
    print(r)

con.close()
