import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

cur.execute('ALTER TABLE stock_signals ADD COLUMN vol_contraction REAL')
conn.commit()
print('ALTER TABLE executed.')

cur.execute('PRAGMA table_info(stock_signals)')
cols = cur.fetchall()
print(f'\nPRAGMA table_info — {len(cols)} columns:')
for c in cols:
    print(f'   {c[0]:2d}  {c[1]:30s}  {c[2]}')

cur.execute('SELECT COUNT(*) FROM stock_signals WHERE vol_contraction IS NOT NULL')
print('\nvol_contraction NOT NULL count:', cur.fetchone()[0])

conn.close()
