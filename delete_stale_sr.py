import sqlite3

conn = sqlite3.connect("psx_data.db")
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM trade_setups WHERE source='Support Reversal' AND status='Pending'")
print(f"Pending Support Reversal setups: {cur.fetchone()[0]}")

cur.execute("DELETE FROM trade_setups WHERE source='Support Reversal' AND status='Pending'")
print(f"Deleted: {cur.rowcount} rows")
conn.commit()
cur.close()
conn.close()
print("Done.")
