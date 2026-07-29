import sqlite3
conn = sqlite3.connect("psx_data.db")

print("GATE 1 - indexes on prices table:")
rows = conn.execute("SELECT name FROM sqlite_master WHERE type=? AND tbl_name=?", ("index","prices")).fetchall()
if rows:
    for r in rows: print(" ", r[0])
else:
    print("  (none)")

print()
print("All price-related tables:")
rows2 = conn.execute("SELECT name FROM sqlite_master WHERE type=? AND name LIKE ?", ("table","%price%")).fetchall()
for r in rows2: print(" ", r[0])

conn.close()
