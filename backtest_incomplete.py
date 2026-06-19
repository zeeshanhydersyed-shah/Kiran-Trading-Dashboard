"""
Investigate incomplete BOS events — what happens if we wait longer?
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
           ss.rs_rank, ss.sector_rs_rank,
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

# For each signal, simulate extended windows: 20, 30, 40, 60 days
WINDOWS = [20, 30, 40, 60]

records = []
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

    rec = {
        'date': date, 'symbol': sym,
        'rs_rank': row['rs_rank'],
        'sector_rs_rank': row['sector_rs_rank'],
        'base_tightness': row['base_tightness'],
        'regime': row['regime'],
        'stage2_bull': row['stage2_bull'],
    }

    # Simulate each window independently
    for W in WINDOWS:
        outcome  = 'INCOMPLETE'
        max_gain = 0.0
        min_chg  = 0.0
        for j in range(i0 + 1, min(i0 + W + 1, len(sp))):
            c = sp.loc[j, 'close']
            if c is None:
                continue
            chg = (c - entry) / entry
            max_gain = max(max_gain, chg)
            min_chg  = min(min_chg, chg)
            if chg <= LOSS_STOP:
                outcome = 'LOSS'
                break
            if chg >= WIN_TARGET:
                outcome = 'WIN'
                break
        rec[f'outcome_{W}d'] = outcome
        rec[f'maxgain_{W}d'] = round(max_gain * 100, 1)
        rec[f'mindraw_{W}d'] = round(min_chg  * 100, 1)

    records.append(rec)

df = pd.DataFrame(records)

# Focus on events that were INCOMPLETE at 20 days
inc20 = df[df['outcome_20d'] == 'INCOMPLETE'].copy()
res20 = df[df['outcome_20d'].isin(['WIN','LOSS'])].copy()

print("=" * 65)
print(f"TOTAL EVENTS     : {len(df):,}")
print(f"Resolved at 20d  : {len(res20):,}  ({len(res20)/len(df)*100:.1f}%)")
print(f"Incomplete at 20d: {len(inc20):,}  ({len(inc20)/len(df)*100:.1f}%)")

print("\n=== WHAT DO INCOMPLETE EVENTS LOOK LIKE AT 20 DAYS? ===")
print(f"  Avg max gain  : {inc20['maxgain_20d'].mean():.1f}%")
print(f"  Median max gain: {inc20['maxgain_20d'].median():.1f}%")
print(f"  Avg max drawdown: {inc20['mindraw_20d'].mean():.1f}%")
print(f"  % that gained >10% (close to target): {(inc20['maxgain_20d'] >= 10).mean()*100:.1f}%")
print(f"  % that gained >15% (almost there)   : {(inc20['maxgain_20d'] >= 15).mean()*100:.1f}%")
print(f"  % that gained < 3% (went nowhere)   : {(inc20['maxgain_20d'] < 3).mean()*100:.1f}%")

print("\n=== IF WE EXTEND THE WINDOW — HOW MANY RESOLVE? ===")
for W in WINDOWS:
    wins  = (df[f'outcome_{W}d'] == 'WIN').sum()
    losses= (df[f'outcome_{W}d'] == 'LOSS').sum()
    inc   = (df[f'outcome_{W}d'] == 'INCOMPLETE').sum()
    total_res = wins + losses
    wr = wins / total_res * 100 if total_res else 0
    ev = wr/100 * WIN_TARGET*100 + (1-wr/100) * LOSS_STOP*100
    print(f"  {W:2d}d window -> resolved: {total_res:>4} ({total_res/len(df)*100:.1f}%)  "
          f"incomplete: {inc:>4}  WR: {wr:.1f}%  EV: {ev:+.2f}%")

print("\n=== FOR EVENTS INCOMPLETE AT 20D — WHAT HAPPENS BY 60D? ===")
for outcome in ['WIN', 'LOSS', 'INCOMPLETE']:
    n = (inc20['outcome_60d'] == outcome).sum()
    print(f"  Eventually {outcome:<12}: {n:>4} ({n/len(inc20)*100:.1f}%)")

print("\n=== INCOMPLETE@20d BY REGIME ===")
for reg in ['TRENDING_UP', 'RANGING', 'TRENDING_DOWN', 'VOLATILE']:
    sub = inc20[inc20['regime'] == reg]
    if len(sub) == 0:
        continue
    eventually_win = (sub['outcome_60d'] == 'WIN').sum()
    print(f"  {reg:<16}  n={len(sub):>4}  avg_max_gain={sub['maxgain_20d'].mean():.1f}%  "
          f"eventually_win_60d={eventually_win} ({eventually_win/len(sub)*100:.1f}%)")

print("\n=== DISTRIBUTION OF MAX GAIN FOR INCOMPLETE@20d ===")
bins = [0, 3, 6, 9, 12, 15, 18]
labels = ['0-3%', '3-6%', '6-9%', '9-12%', '12-15%', '15-18%']
inc20['gain_bucket'] = pd.cut(inc20['maxgain_20d'], bins=bins, labels=labels)
dist = inc20['gain_bucket'].value_counts().sort_index()
for b, c in dist.items():
    bar = '#' * int(c / max(dist) * 30)
    print(f"  {b:<8} {c:>4}  {bar}")

print("\nDone.")
