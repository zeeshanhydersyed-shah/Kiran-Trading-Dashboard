import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
dfc = [t for t in tables if 'dfc' in t.lower() or 'future' in t.lower() or 'short' in t.lower()]
print('Potential DFC tables:', dfc)

for t in dfc:
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info({t})').fetchall()]
    count = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    sample = cur.execute(f'SELECT * FROM {t} LIMIT 10').fetchall()
    print(f'\n{t} ({count} rows) cols={cols}')
    for r in sample:
        print(' ', r)

conn.close()
