import sqlite3
import pandas as pd

conn = sqlite3.connect('psx_data.db')

print('=== 1. index_prices row count ===')
r = conn.execute('SELECT COUNT(*) FROM index_prices').fetchone()
print(f'Total rows: {r[0]}')

print()
print('=== 2. Date range ===')
r = conn.execute('SELECT MIN(date), MAX(date) FROM index_prices').fetchone()
print(f'Min date: {r[0]}  Max date: {r[1]}')

print()
print('=== 3. KSE-100 count ===')
r = conn.execute("SELECT COUNT(*) FROM index_prices WHERE symbol = 'KSE-100'").fetchone()
print(f'KSE-100 rows: {r[0]}')

print()
print('=== 4. KSE-100 first 10 rows ===')
df = pd.read_sql("SELECT * FROM index_prices WHERE symbol = 'KSE-100' ORDER BY date ASC LIMIT 10", conn)
print(df.to_string(index=False))

print()
print('=== 5. Gap analysis (gaps > 7 days) ===')
df_dates = pd.read_sql("SELECT date FROM index_prices WHERE symbol = 'KSE-100' ORDER BY date ASC", conn)
df_dates['date'] = pd.to_datetime(df_dates['date'])
df_dates['prev'] = df_dates['date'].shift(1)
df_dates['gap_days'] = (df_dates['date'] - df_dates['prev']).dt.days
gaps = df_dates[df_dates['gap_days'] > 7]
if gaps.empty:
    print('No gaps > 7 days found.')
else:
    print(f'Found {len(gaps)} gaps > 7 days:')
    for _, row in gaps.iterrows():
        print(f'  {row["prev"].date()} -> {row["date"].date()}  ({int(row["gap_days"])} days)')

conn.close()
print('\nDone.')
