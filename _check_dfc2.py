import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

# Broader search - check all tables for any that might contain DFC/futures data
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('All tables:')
for t in tables:
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info({t})').fetchall()]
    print(f'  {t}: {cols}')

conn.close()
