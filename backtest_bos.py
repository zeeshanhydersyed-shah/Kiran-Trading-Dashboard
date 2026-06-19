"""
BOS Breakout Backtest
Winner = bos_flag=1 AND base_tightness<10 on day 0,
         hit +18% before hitting -6% within next 20 trading days.
"""
import sqlite3
import pandas as pd

DB = 'psx_data.db'
WIN_TARGET   = 0.18   # +18%
LOSS_STOP    = -0.06  # -6%
LOOKFORWARD  = 20     # trading days

con = sqlite3.connect(DB)

# ── 1. Pull all qualifying BOS signals ───────────────────────────────────────
print("Loading BOS signals...")
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
print(f"  {len(signals):,} qualifying BOS events")

# ── 2. Pull all prices for forward-looking ───────────────────────────────────
print("Loading prices...")
prices = pd.read_sql_query("""
    SELECT symbol, date, close
    FROM prices_adjusted
    ORDER BY symbol, date
""", con)
con.close()

prices['date'] = pd.to_datetime(prices['date'])
signals['date'] = pd.to_datetime(signals['date'])

# Build per-symbol price index: {symbol: DataFrame(date, close) sorted}
sym_prices = {}
for sym, grp in prices.groupby('symbol'):
    sym_prices[sym] = grp.reset_index(drop=True)

# ── 3. Tag each signal WIN / LOSS / INCOMPLETE ────────────────────────────────
print("Running forward simulation...")
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
    i0 = idx[0]
    entry = sp.loc[i0, 'close']
    if not entry or entry <= 0:
        continue

    outcome = 'INCOMPLETE'
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

    results.append({
        'date':            date,
        'symbol':          sym,
        'rs_rank':         row['rs_rank'],
        'sector_rs_rank':  row['sector_rs_rank'],
        'rs_score_20':     row['rs_score_20'],
        'base_tightness':  row['base_tightness'],
        'avg_vol_10d':     row['avg_vol_10d'],
        'stage2_bull':     row['stage2_bull'],
        'regime':          row['regime'],
        'outcome':         outcome,
        'max_gain':        round(max_gain * 100, 1),
    })

df = pd.DataFrame(results)
print(f"  {len(df):,} events evaluated")

# ── 4. Overall summary ────────────────────────────────────────────────────────
df_ex = df[df['outcome'].isin(['WIN','LOSS'])]
total = len(df_ex)
wins  = (df_ex['outcome'] == 'WIN').sum()
wr    = wins / total * 100 if total else 0

print("\n" + "="*60)
print(f"OVERALL  |  Events: {total:,}  |  Wins: {wins:,}  |  Win Rate: {wr:.1f}%")
ev = wr/100 * WIN_TARGET * 100 + (1 - wr/100) * LOSS_STOP * 100
print(f"Expected Value per trade: {ev:.2f}%")
print("="*60)

# ── 5. By RS rank bucket ──────────────────────────────────────────────────────
print("\n── BY RS RANK BUCKET (at time of BOS) ──")
bins   = [0, 25, 50, 100, 200, 999]
labels = ['Top 25','26-50','51-100','101-200','201+']
df_ex2 = df_ex.copy()
df_ex2['rs_bucket'] = pd.cut(df_ex2['rs_rank'], bins=bins, labels=labels)
tbl = df_ex2.groupby('rs_bucket', observed=True)['outcome'].apply(
    lambda x: pd.Series({
        'Events': len(x),
        'Wins':   (x=='WIN').sum(),
        'Win%':   round((x=='WIN').mean()*100, 1)
    })
).unstack()
print(tbl.to_string())

# ── 6. By sector RS rank bucket ───────────────────────────────────────────────
print("\n── BY SECTOR RS RANK (stock's rank within sector at BOS) ──")
bins2   = [0, 3, 6, 10, 999]
labels2 = ['Top 3','4-6','7-10','11+']
df_ex2['sec_bucket'] = pd.cut(df_ex2['sector_rs_rank'], bins=bins2, labels=labels2)
tbl2 = df_ex2.groupby('sec_bucket', observed=True)['outcome'].apply(
    lambda x: pd.Series({
        'Events': len(x),
        'Wins':   (x=='WIN').sum(),
        'Win%':   round((x=='WIN').mean()*100, 1)
    })
).unstack()
print(tbl2.to_string())

# ── 7. By BBW bucket ──────────────────────────────────────────────────────────
print("\n── BY BBW% AT TIME OF BOS ──")
bins3   = [0, 3, 5, 7, 10]
labels3 = ['<3%','3-5%','5-7%','7-10%']
df_ex2['bbw_bucket'] = pd.cut(df_ex2['base_tightness'], bins=bins3, labels=labels3)
tbl3 = df_ex2.groupby('bbw_bucket', observed=True)['outcome'].apply(
    lambda x: pd.Series({
        'Events': len(x),
        'Wins':   (x=='WIN').sum(),
        'Win%':   round((x=='WIN').mean()*100, 1)
    })
).unstack()
print(tbl3.to_string())

# ── 8. By market regime ───────────────────────────────────────────────────────
print("\n── BY MARKET REGIME AT TIME OF BOS ──")
tbl4 = df_ex2.groupby('regime', observed=True)['outcome'].apply(
    lambda x: pd.Series({
        'Events': len(x),
        'Wins':   (x=='WIN').sum(),
        'Win%':   round((x=='WIN').mean()*100, 1)
    })
).unstack()
print(tbl4.to_string())

# ── 9. Stage2 vs non-Stage2 ───────────────────────────────────────────────────
print("\n── STAGE2_BULL FLAG AT TIME OF BOS ──")
tbl5 = df_ex2.groupby('stage2_bull', observed=True)['outcome'].apply(
    lambda x: pd.Series({
        'Events': len(x),
        'Wins':   (x=='WIN').sum(),
        'Win%':   round((x=='WIN').mean()*100, 1)
    })
).unstack()
print(tbl5.to_string())

# ── 10. Combined: top sector + top RS + stage2 ───────────────────────────────
print("\n── BEST COMBO: stage2=1 + RS rank ≤50 + sector rank ≤8 ──")
combo = df_ex2[
    (df_ex2['stage2_bull'] == 1) &
    (df_ex2['rs_rank'] <= 50) &
    (df_ex2['sector_rs_rank'] <= 8)
]
if len(combo):
    cw = (combo['outcome']=='WIN').sum()
    print(f"Events: {len(combo):,}  Wins: {cw:,}  Win%: {cw/len(combo)*100:.1f}%")
    ev2 = cw/len(combo) * WIN_TARGET * 100 + (1 - cw/len(combo)) * LOSS_STOP * 100
    print(f"Expected Value: {ev2:.2f}%")
else:
    print("No events.")

print("\nDone.")
