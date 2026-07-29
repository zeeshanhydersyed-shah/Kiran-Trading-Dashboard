import sqlite3, pandas as pd

conn = sqlite3.connect("psx_data.db")

print("=== Support Reversal setups in DB ===")
df = pd.read_sql(
    "SELECT id, symbol, created_date, status, notes FROM trade_setups "
    "WHERE source='Support Reversal' ORDER BY created_date DESC LIMIT 20",
    conn
)
print(df.to_string())

print("\n=== Count by date ===")
df2 = pd.read_sql(
    "SELECT created_date, status, COUNT(*) as cnt FROM trade_setups "
    "WHERE source='Support Reversal' GROUP BY created_date, status ORDER BY created_date DESC",
    conn
)
print(df2.to_string())
conn.close()
