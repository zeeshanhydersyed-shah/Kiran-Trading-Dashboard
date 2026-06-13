import sqlite3
import pandas as pd
import numpy as np

DB = 'psx_data.db'

conn = sqlite3.connect(DB)

# ─── STEP 2: CREATE TABLE ────────────────────────────────────────────────────
print('=== STEP 2: Creating market_regime table ===')
conn.executescript("""
    CREATE TABLE IF NOT EXISTS market_regime (
        date           TEXT PRIMARY KEY,
        close          REAL,
        ema_20         REAL,
        ema_50         REAL,
        ema_200        REAL,
        atr_20         REAL,
        atr_pct        REAL,
        return_20d     REAL,
        regime         TEXT NOT NULL,
        regime_days    INTEGER,
        notes          TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_regime_date ON market_regime (date);
""")
conn.commit()
print('Table and index created (or already existed).')

# ─── STEP 3: COMPUTE INDICATORS ──────────────────────────────────────────────
print()
print('=== STEP 3: Loading KSE-100 data and computing indicators ===')

df = pd.read_sql(
    "SELECT date, high, low, close FROM index_prices WHERE symbol = 'KSE-100' ORDER BY date ASC",
    conn
)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
print(f'Loaded {len(df)} KSE-100 rows.')

# EMAs
df['ema_20']  = df['close'].ewm(span=20,  adjust=False).mean()
df['ema_50']  = df['close'].ewm(span=50,  adjust=False).mean()
df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

# ATR
df['prev_close'] = df['close'].shift(1)
df['tr'] = df[['high', 'low', 'prev_close']].apply(
    lambda r: max(
        r['high'] - r['low'],
        abs(r['high'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
        abs(r['low']  - r['prev_close']) if pd.notna(r['prev_close']) else 0,
    ), axis=1
)
df['atr_20']  = df['tr'].rolling(20).mean()
df['atr_pct'] = df['atr_20'] / df['close'] * 100

# 20-day return
df['return_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100

print('Indicators computed.')

# ─── STEP 4: CLASSIFY REGIMES ────────────────────────────────────────────────
print()
print('=== STEP 4: Classifying regimes ===')

# Rows where EMA_200 is still warming up (first 199 rows by rolling logic).
# We use a hard cutoff: EMA_200 needs at least 200 data points.
# EWM doesn't go NaN, but is unreliable early; mark first 199 rows INSUFFICIENT_DATA.
INSUFFICIENT_ROWS = 199  # 0-indexed rows 0..198

def classify(row, idx):
    if idx < INSUFFICIENT_ROWS:
        return 'INSUFFICIENT_DATA'
    e20, e50, e200 = row['ema_20'], row['ema_50'], row['ema_200']
    c = row['close']
    r20 = row['return_20d']
    atr_pct = row['atr_pct']

    if pd.isna(r20) or pd.isna(atr_pct):
        return 'INSUFFICIENT_DATA'

    if e20 > e50 and e50 > e200 and c > e20 and r20 > 0:
        return 'TRENDING_UP'
    elif e20 < e50 and e50 < e200 and c < e20 and r20 < 0:
        return 'TRENDING_DOWN'
    elif atr_pct > 1.5:
        return 'VOLATILE'
    else:
        return 'RANGING'

df['regime'] = [classify(df.iloc[i], i) for i in range(len(df))]
print(f'Regimes classified.')

# ─── STEP 5: COMPUTE REGIME_DAYS ─────────────────────────────────────────────
print()
print('=== STEP 5: Computing regime_days ===')

regime_days = []
count = 0
prev_regime = None
for r in df['regime']:
    if r == prev_regime:
        count += 1
    else:
        count = 1
        prev_regime = r
    regime_days.append(count)
df['regime_days'] = regime_days
print('regime_days computed.')

# ─── STEP 6: INSERT INTO market_regime ───────────────────────────────────────
print()
print('=== STEP 6: Inserting into market_regime ===')

conn.execute('DELETE FROM market_regime')  # clear before full insert

rows = []
for _, row in df.iterrows():
    rows.append((
        row['date'].strftime('%Y-%m-%d'),
        float(row['close']),
        float(row['ema_20']),
        float(row['ema_50']),
        float(row['ema_200']),
        float(row['atr_20'])    if pd.notna(row['atr_20'])    else None,
        float(row['atr_pct'])   if pd.notna(row['atr_pct'])   else None,
        float(row['return_20d'])if pd.notna(row['return_20d'])else None,
        row['regime'],
        int(row['regime_days']),
        None,
    ))

conn.executemany(
    'INSERT OR REPLACE INTO market_regime VALUES (?,?,?,?,?,?,?,?,?,?,?)',
    rows
)
conn.commit()
inserted = conn.execute('SELECT COUNT(*) FROM market_regime').fetchone()[0]
print(f'Inserted {inserted} rows into market_regime.')

# ─── STEP 7: VALIDATION ──────────────────────────────────────────────────────
print()
print('=' * 60)
print('=== STEP 7: VALIDATION REPORT ===')
print('=' * 60)

vm = pd.read_sql('SELECT * FROM market_regime ORDER BY date ASC', conn)
vm['date'] = pd.to_datetime(vm['date'])

# 7.1 Total rows
print(f'\n1. Total rows: {len(vm)}')

# 7.2 Date range
print(f'2. Date range: {vm["date"].min().date()} → {vm["date"].max().date()}')

# 7.3 Regime distribution
print('\n3. Regime distribution:')
dist = vm['regime'].value_counts()
total = len(vm)
for regime, cnt in dist.items():
    print(f'   {regime:<20} {cnt:>5}  ({cnt/total*100:.1f}%)')

# 7.4 Longest streak per regime
print('\n4. Longest streak per regime:')
vm['grp'] = (vm['regime'] != vm['regime'].shift()).cumsum()
streaks = vm.groupby(['grp', 'regime']).agg(
    start=('date', 'first'),
    end=('date', 'last'),
    days=('date', 'count')
).reset_index()
best = streaks.loc[streaks.groupby('regime')['days'].idxmax()]
for _, row in best.sort_values('days', ascending=False).iterrows():
    print(f'   {row["regime"]:<20} {row["start"].date()} → {row["end"].date()}  ({int(row["days"])} days)')

# 7.5 Recent 30 days
print('\n5. Recent 30 days:')
recent = vm.tail(30)[['date', 'close', 'regime', 'regime_days']].copy()
recent['date'] = recent['date'].dt.strftime('%Y-%m-%d')
print(recent.to_string(index=False))

# 7.6 Spot checks
print('\n6. Spot checks:')
spot_checks = [
    ('2008-10-01', ['TRENDING_DOWN', 'VOLATILE']),
    ('2020-03-20', ['TRENDING_DOWN', 'VOLATILE']),
    ('2017-05-01', ['TRENDING_UP']),
    ('2021-06-01', ['TRENDING_UP']),
]
for date_str, expected in spot_checks:
    row = vm[vm['date'] == pd.Timestamp(date_str)]
    if row.empty:
        # find nearest trading day
        nearest = vm[vm['date'] >= pd.Timestamp(date_str)].head(1)
        if nearest.empty:
            print(f'   {date_str}  NOT FOUND')
            continue
        row = nearest
        actual_date = row.iloc[0]['date'].strftime('%Y-%m-%d')
        note = f'(nearest: {actual_date})'
    else:
        note = ''
    actual = row.iloc[0]['regime']
    status = 'PASS' if actual in expected else 'FAIL'
    print(f'   {date_str}  {note:<20} regime={actual:<16} expected={expected}  [{status}]')

# 7.7 Transition count
transitions = (vm['regime'] != vm['regime'].shift()).sum() - 1  # subtract first row
print(f'\n7. Total regime transitions across full history: {transitions}')

conn.close()
print('\n=== VALIDATION COMPLETE ===')
