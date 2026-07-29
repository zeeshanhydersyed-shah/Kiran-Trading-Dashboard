import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()
cur.execute("""
SELECT s.symbol
FROM stock_metadata s
LEFT JOIN (
    SELECT DISTINCT symbol FROM stock_signals
) ss ON s.symbol = ss.symbol
WHERE ss.symbol IS NULL
""")
rows = cur.fetchall()
print(f"Symbols in stock_metadata but NOT in stock_signals ({len(rows)} total):")
for r in rows:
    print(f"  {r[0]}")
conn.close()
