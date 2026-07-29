import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

# 1. PRAGMA
cur.execute('PRAGMA table_info(stock_signals)')
cols = cur.fetchall()
print('PRAGMA table_info(stock_signals):')
for c in cols:
    print(f'  {c[0]:2d}  {c[1]:30s}  {c[2]}')
names = [c[1] for c in cols]
print(f'\navg_vol_10d exists: {"avg_vol_10d" in names}')

# 2. Row count
cur.execute('SELECT COUNT(*) FROM stock_signals')
print(f'\nstock_signals row count: {cur.fetchone()[0]:,}')

conn.close()
