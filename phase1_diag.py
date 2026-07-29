import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

# 1. Row count
cur.execute('SELECT COUNT(*) FROM stock_signals')
print('1. stock_signals rows:', cur.fetchone()[0])

# 2. Columns
cur.execute('PRAGMA table_info(stock_signals)')
cols = cur.fetchall()
print('\n2. stock_signals columns:')
for c in cols:
    print(f'   {c[0]:2d}  {c[1]:30s}  {c[2]}')

# 3. vol_contraction existence
names = [c[1] for c in cols]
print('\n3. vol_contraction exists:', 'vol_contraction' in names)

# 4. NULL volumes for top 5 symbols
print('\n4. NULL volume counts in prices_adjusted:')
for sym in ['ENGRO', 'LUCK', 'HBL', 'PSO', 'UBL']:
    cur.execute('SELECT COUNT(*) FROM prices_adjusted WHERE symbol=? AND volume IS NULL', (sym,))
    print(f'   {sym}: {cur.fetchone()[0]} NULLs')

# 5. Sample 20 ENGRO rows from 2015-01-01
print('\n5. ENGRO sample (date, close, volume):')
cur.execute(
    "SELECT date, close, volume FROM prices_adjusted "
    "WHERE symbol='ENGRO' AND date>='2015-01-01' ORDER BY date ASC LIMIT 20"
)
for r in cur.fetchall():
    print(f'   {r}')

# 6. NULL base_tightness count
cur.execute('SELECT COUNT(*) FROM stock_signals WHERE base_tightness IS NULL')
print('\n6. base_tightness NULL count:', cur.fetchone()[0])

conn.close()
