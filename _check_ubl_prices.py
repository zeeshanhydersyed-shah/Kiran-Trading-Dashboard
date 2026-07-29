import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('Tables:', tables)

for tbl in ['ohlcv', 'stock_ohlcv', 'prices_ohlcv', 'daily_prices']:
    try:
        rows = cur.execute(
            f"SELECT date, close, high FROM {tbl} WHERE symbol=? AND date BETWEEN ? AND ? ORDER BY date",
            ('UBL', '2024-09-10', '2024-09-25')
        ).fetchall()
        if rows:
            print(f'\nTable {tbl}:')
            for r in rows:
                print(r)
    except Exception as e:
        pass

print('\nprices table (what we join against):')
rows = cur.execute(
    "SELECT date, close FROM prices WHERE symbol=? AND date BETWEEN ? AND ? ORDER BY date",
    ('UBL', '2024-09-10', '2024-09-25')
).fetchall()
for r in rows:
    print(r)

# Check how stock_signals.py loads stock_prices_vol - search database.py
conn.close()
