import sqlite3, sys
sys.path.insert(0, r'C:\Users\Lenovo\psx_pipeline')
from config import DB_PATH
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

signal_date = '2026-06-18'

# STEP 1
print('=== STEP 1: LOTCHEM STOCK SIGNALS (' + signal_date + ') ===')
q = '''
SELECT ss.*, sm.sector, sm.company_name, sm.in_kse100
FROM stock_signals ss
JOIN stock_metadata sm ON ss.symbol = sm.symbol
WHERE ss.symbol = 'LOTCHEM' AND ss.date = ?
'''
row = conn.execute(q, (signal_date,)).fetchone()
if row:
    for k in row.keys():
        print(f'  {k}: {row[k]}')
else:
    print('Not found')

# STEP 2 - Sector 30-day trajectory
print('\n=== STEP 2: CHEMICAL SECTOR - LAST 30 DAYS ===')
rows = conn.execute('''
SELECT date, composite_score, breadth_score, rs_score_20, rs_rank, adv_dec_ratio,
       vol_ratio, rs_inflection, regime
FROM sector_signals
WHERE sector = 'CHEMICAL'
ORDER BY date DESC LIMIT 30
''').fetchall()
print(f"{'Date':<12} {'CompScore':>10} {'Breadth':>8} {'RS20':>8} {'RSRank':>7} {'AdvDec':>7} {'VolRat':>7} {'Inflec':>7} {'Regime'}")
for r in rows:
    print(f"{r['date']:<12} {r['composite_score']:>10.3f} {r['breadth_score']:>8.3f} {r['rs_score_20']:>8.3f} {r['rs_rank']:>7} {r['adv_dec_ratio']:>7.3f} {r['vol_ratio']:>7.3f} {r['rs_inflection']:>7} {r['regime']}")

# STEP 2B - All-sector ranking
print('\n=== STEP 2B: ALL-SECTOR RANKING ON ' + signal_date + ' ===')
rows2 = conn.execute('''
SELECT sector, composite_score, rs_rank, breadth_score, regime, rs_inflection
FROM sector_signals WHERE date = ?
ORDER BY composite_score DESC
''', (signal_date,)).fetchall()
for i, r in enumerate(rows2, 1):
    flag = ' <-- CHEMICAL' if r['sector'] == 'CHEMICAL' else ''
    print(f"{i:>3}. {r['sector']:<25} composite={r['composite_score']:>7.3f}  rs_rank={r['rs_rank']:>3}  breadth={r['breadth_score']:>6.3f}  regime={str(r['regime']):<15}  inflec={r['rs_inflection']}{flag}")

# STEP 3 - Price history last 50 days + vol_ratio
print('\n=== STEP 3: LOTCHEM PRICE HISTORY (LAST 50 DAYS) ===')
prices = conn.execute('''
SELECT date, high, low, close, volume
FROM prices
WHERE symbol = 'LOTCHEM'
ORDER BY date DESC LIMIT 60
''').fetchall()

# Reverse to compute rolling avg
prices_asc = list(reversed(prices))
results = []
for i, p in enumerate(prices_asc):
    start = max(0, i - 19)
    window = prices_asc[start:i+1]
    avg_vol = sum(w['volume'] for w in window) / len(window)
    vol_ratio = p['volume'] / avg_vol if avg_vol > 0 else 0
    results.append((p['date'], p['high'], p['low'], p['close'], p['volume'], vol_ratio))

# Show last 50, most recent first
pivot_high = row['pivot_high'] if row else None
print(f"{'Date':<12} {'High':>8} {'Low':>8} {'Close':>8} {'Volume':>12} {'VolRatio':>9}  Notes")
for d, h, l, c, v, vr in reversed(results[-50:]):
    flag = ''
    if vr > 2.0:
        flag = 'HIGH_VOL'
        if pivot_high and c >= pivot_high:
            flag += ' ABOVE_PIVOT'
        elif pivot_high and h >= pivot_high and c < pivot_high:
            flag += ' REJECTED_AT_PIVOT'
    print(f"{d:<12} {h:>8.2f} {l:>8.2f} {c:>8.2f} {v:>12,} {vr:>9.2f}  {flag}")

# STEP 3B - Pivot high and overhead supply (last 120 days)
print('\n=== STEP 3B: OVERHEAD SUPPLY (last 120 days vs pivot_high=' + str(pivot_high) + ') ===')
hist = conn.execute('''
SELECT date, high, low, close, volume
FROM prices WHERE symbol = 'LOTCHEM'
ORDER BY date DESC LIMIT 120
''').fetchall()
if pivot_high:
    supply_levels = [(r['date'], r['high']) for r in hist if r['high'] > pivot_high]
    if supply_levels:
        print('Dates where high exceeded pivot_high:')
        for d, h in supply_levels[:20]:
            print(f'  {d}: high={h:.2f}  (overhead by {((h/pivot_high)-1)*100:.1f}%)')
    else:
        print('No overhead supply found above pivot_high in last 120 days.')

conn.close()
