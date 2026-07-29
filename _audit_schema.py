import sqlite3
conn = sqlite3.connect('psx_data.db')

for t in ['setup_log', 'mv_signals', 'stm_signals']:
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({t})').fetchall()]
    cnt = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    # find date col
    date_col = next((c for c in cols if 'date' in c.lower()), None)
    if date_col:
        mn = conn.execute(f'SELECT MIN({date_col}) FROM {t}').fetchone()[0]
        mx = conn.execute(f'SELECT MAX({date_col}) FROM {t}').fetchone()[0]
    else:
        mn = mx = 'no date col'
    print(f'\n{t}: {cnt} rows, {mn} to {mx}')
    print(f'  cols: {cols}')
    if 'signal_type' in cols:
        st_counts = conn.execute(f'SELECT signal_type, COUNT(*) FROM {t} GROUP BY signal_type').fetchall()
        print(f'  signal_types: {st_counts}')
    if 'setup_type' in cols:
        st_counts = conn.execute(f'SELECT setup_type, COUNT(*) FROM {t} GROUP BY setup_type').fetchall()
        print(f'  setup_types: {st_counts}')

conn.close()
