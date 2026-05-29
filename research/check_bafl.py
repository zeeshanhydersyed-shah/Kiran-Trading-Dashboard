import sqlite3
from config import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=== BAFL TRADES ===")
cursor.execute("""
    SELECT id, symbol, source, status, outcome, actual_entry, entry_price, created_date
    FROM trade_setups
    WHERE symbol='BAFL'
    ORDER BY id
""")

rows = cursor.fetchall()
print(f"Found {len(rows)} BAFL trade(s)")
for row in rows:
    print(f"\nID: {row['id']}")
    print(f"  Symbol: {row['symbol']}")
    print(f"  Source: {row['source']}")
    print(f"  Status: {row['status']}")
    print(f"  Outcome: {row['outcome']}")
    print(f"  Entry: {row['entry_price']}, Actual Entry: {row['actual_entry']}")
    print(f"  Created: {row['created_date']}")

conn.close()
