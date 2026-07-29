import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

# Check prices_adjusted for UBL
print("prices_adjusted for UBL around Sep 2024:")
rows = cur.execute(
    "SELECT date, close, high FROM prices_adjusted WHERE symbol=? AND date BETWEEN ? AND ? ORDER BY date",
    ('UBL', '2024-09-10', '2024-09-25')
).fetchall()
for r in rows:
    print(r)

# Also check earlier history to see what pivot of 137.35 might correspond to
print("\nprices_adjusted for UBL - what does 137.35 area look like?")
rows = cur.execute(
    "SELECT date, close, high FROM prices_adjusted WHERE symbol=? AND high BETWEEN 130 AND 145 ORDER BY date DESC LIMIT 20",
    ('UBL',)
).fetchall()
for r in rows:
    print(r)

# Check prices (unadjusted) for same 137 range
print("\nprices (unadjusted) for UBL - 137 range:")
rows = cur.execute(
    "SELECT date, close FROM prices WHERE symbol=? AND close BETWEEN 130 AND 145 ORDER BY date DESC LIMIT 10",
    ('UBL',)
).fetchall()
for r in rows:
    print(r)

conn.close()
