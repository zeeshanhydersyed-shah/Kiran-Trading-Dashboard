"""
BOS Backtest - Deep Dive
Focus: TRENDING_UP regime sliced by RS rank, sector rank, BBW combos
"""
import sqlite3
import pandas as pd

DB = 'psx_data.db'
WIN_TARGET  = 0.18
LOSS_STOP   = -0.06
LOOKFORWARD = 20

con = sqlite3.connect(DB)
signals = pd.read_sql_query("""
    SELECT ss.date, ss.symbol,
           ss.rs_rank, ss.sector_rs_rank, ss.rs_score_20,
           ss.base_tightness, ss.avg_vol_10d,
           ss.stage2_bull,
           mr.regime
    FROM stock_signals ss
    LEFT JOIN market_regime mr ON mr.date = ss.date
    WHERE ss.bos_flag = 1
      AND ss.base_tightness IS NOT NULL
      AND ss.base_tightness < 10
      AND ss.avg_vol_10d > 200000
    ORDER BY ss.date, ss.symbol
""", con)

prices = pd.read_sql_query(
    "SELECT symbol, date, close FROM prices_adjusted ORDER BY symbol, date", con
)
con.close()

prices['date']  = pd.to_datetime(prices['date'])
signals['date'] = pd.to_datetime(signals['date'])

sym_prices = {}
for sym, grp in prices.groupby('symbol'):
    sym_prices[sym] = grp.reset_index(drop=True)

results = []
for _, row in signals.iterrows():
    sym  = row['symbol']
    date = row['date']
    if sym not in sym_prices:
        continue
    sp = sym_prices[sym]
    idx = sp[sp['date'] == date].index
    if len(idx) == 0:
        continue
    i0    = idx[0]
    entry = sp.loc[i0, 'close']
    if not entry or entry <= 0:
        continue
    outcome  = 'INCOMPLETE'
    max_gain = 0.0
    for j in range(i0 + 1, min(i0 + LOOKFORWARD + 1, len(sp))):
        c = sp.loc[j, 'close']
        if c is None:
            continue
        chg = (c - entry) / entry
        max_gain = max(max_gain, chg)
        if chg <= LOSS_STOP:
            outcome = 'LOSS'
            break
        if chg >= WIN_TARGET:
            outcome = 'WIN'
            break
    results.append({**row.to_dict(), 'outcome': outcome, 'max_gain': round(max_gain * 100, 1)})

df = pd.DataFrame(results)
df_ex = df[df['outcome'].isin(['WIN', 'LOSS'])].copy()

def summary(label, subset):
    total = len(subset)
    wins  = (subset['outcome'] == 'WIN').sum()
    wr    = wins / total * 100 if total else 0
    ev    = wr/100 * WIN_TARGET*100 + (1 - wr/100) * LOSS_STOP*100
    print(f"  {label:<45}  n={total:>4}  wins={wins:>3}  WR={wr:>5.1f}%  EV={ev:>+5.2f}%")

print("\n=== REGIME FILTER IS THE GATE ===")
for reg in ['TRENDING_UP', 'RANGING', 'TRENDING_DOWN', 'VOLATILE']:
    sub = df_ex[df_ex['regime'] == reg]
    summary(reg, sub)

up = df_ex[df_ex['regime'] == 'TRENDING_UP'].copy()
print(f"\n=== TRENDING_UP ONLY  (n={len(up)}) ===")

print("\n-- RS Rank buckets --")
bins   = [0, 25, 50, 100, 200, 9999]
labels = ['Top 25','26-50','51-100','101-200','201+']
up['rs_bucket'] = pd.cut(up['rs_rank'], bins=bins, labels=labels)
for b in labels:
    summary(f"RS rank {b}", up[up['rs_bucket'] == b])

print("\n-- Sector RS rank buckets --")
bins2   = [0, 3, 5, 8, 9999]
labels2 = ['Sec rank 1-3','Sec rank 4-5','Sec rank 6-8','Sec rank 9+']
up['sec_bucket'] = pd.cut(up['sector_rs_rank'], bins=bins2, labels=labels2)
for b in labels2:
    summary(b, up[up['sec_bucket'] == b])

print("\n-- BBW% buckets --")
bins3   = [0, 3, 5, 7, 10]
labels3 = ['BBW <3%','BBW 3-5%','BBW 5-7%','BBW 7-10%']
up['bbw_bucket'] = pd.cut(up['base_tightness'], bins=bins3, labels=labels3)
for b in labels3:
    summary(b, up[up['bbw_bucket'] == b])

print("\n-- Stage2 flag --")
summary("Stage2 = 1  (EMAs stacked)", up[up['stage2_bull'] == 1])
summary("Stage2 = 0  (EMAs NOT stacked)", up[up['stage2_bull'] == 0])

print("\n=== PROMISING COMBOS (TRENDING_UP only) ===")
combos = [
    ("Stage2 + RS<=100 + Sec<=8",
     up[(up['stage2_bull']==1) & (up['rs_rank']<=100) & (up['sector_rs_rank']<=8)]),
    ("Stage2 + RS<=100 + Sec<=5",
     up[(up['stage2_bull']==1) & (up['rs_rank']<=100) & (up['sector_rs_rank']<=5)]),
    ("Stage2 + RS 50-200 + Sec<=8",
     up[(up['stage2_bull']==1) & (up['rs_rank']>=50) & (up['rs_rank']<=200) & (up['sector_rs_rank']<=8)]),
    ("RS<=100 + Sec<=8 (no stage2 req)",
     up[(up['rs_rank']<=100) & (up['sector_rs_rank']<=8)]),
    ("RS 50-150 + Sec<=8 + BBW 5-10",
     up[(up['rs_rank']>=50) & (up['rs_rank']<=150) & (up['sector_rs_rank']<=8) & (up['base_tightness']>=5)]),
    ("RS<=200 + Sec<=5 + Stage2",
     up[(up['rs_rank']<=200) & (up['sector_rs_rank']<=5) & (up['stage2_bull']==1)]),
    ("No filters (TRENDING_UP baseline)",
     up),
]
for label, sub in combos:
    summary(label, sub)

print("\n=== INCOMPLETE EVENTS (did not resolve in 20 days) ===")
inc = df[df['outcome'] == 'INCOMPLETE']
print(f"  Total incomplete: {len(inc):,} of {len(df):,} ({len(inc)/len(df)*100:.1f}%)")
up_inc = inc[inc['regime'] == 'TRENDING_UP']
print(f"  In TRENDING_UP:   {len(up_inc):,}")
print(f"  Avg max_gain in TRENDING_UP incomplete: {up_inc['max_gain'].mean():.1f}%")
print()
print("Done.")
