"""
Did winners have positive RS score at time of BOS?
TRENDING_UP only, 40d window.
"""
import sqlite3
import pandas as pd

DB = 'psx_data.db'
WIN_TARGET  = 0.18
LOSS_STOP   = -0.06
LOOKFORWARD = 40

con = sqlite3.connect(DB)
signals = pd.read_sql_query("""
    SELECT ss.date, ss.symbol,
           ss.rs_rank, ss.rs_score_20, ss.sector_rs_rank,
           ss.base_tightness, ss.avg_vol_10d,
           sec.rs_rank AS sec_global_rank,
           mr.regime
    FROM stock_signals ss
    LEFT JOIN market_regime mr ON mr.date = ss.date
    LEFT JOIN sector_signals sec
           ON sec.date = ss.date AND sec.sector = (
               SELECT sector FROM sectors WHERE symbol = ss.symbol LIMIT 1
           )
    WHERE ss.bos_flag = 1
      AND ss.base_tightness >= 5
      AND ss.base_tightness < 10
      AND ss.avg_vol_10d > 200000
      AND ss.rs_rank >= 50
      AND ss.rs_rank <= 200
      AND mr.regime = 'TRENDING_UP'
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
    sp  = sym_prices[sym]
    idx = sp[sp['date'] == date].index
    if len(idx) == 0:
        continue
    i0    = idx[0]
    entry = sp.loc[i0, 'close']
    if not entry or entry <= 0:
        continue
    outcome = 'INCOMPLETE'
    for j in range(i0 + 1, min(i0 + LOOKFORWARD + 1, len(sp))):
        c = sp.loc[j, 'close']
        if c is None: continue
        chg = (c - entry) / entry
        if chg <= LOSS_STOP:  outcome = 'LOSS'; break
        if chg >= WIN_TARGET: outcome = 'WIN';  break
    results.append({**row.to_dict(), 'outcome': outcome})

df = pd.DataFrame(results)
df_ex = df[df['outcome'].isin(['WIN','LOSS'])].copy()

def stats(label, sub):
    if len(sub) == 0:
        print(f"  {label:<40}  no events")
        return
    wins = (sub['outcome'] == 'WIN').sum()
    wr   = wins / len(sub) * 100
    ev   = wr/100 * WIN_TARGET*100 + (1-wr/100) * LOSS_STOP*100
    print(f"  {label:<40}  n={len(sub):>4}  wins={wins:>3}  WR={wr:.1f}%  EV={ev:+.2f}%")

print("=" * 65)
print("RS SCORE AT TIME OF BOS  (TRENDING_UP + RS rank 50-200 + BBW 5-10, 40d)")
print("=" * 65)

print("\n-- RS Score: positive vs negative --")
stats("RS score > 0  (outperforming index)", df_ex[df_ex['rs_score_20'] > 0])
stats("RS score <= 0 (underperforming index)", df_ex[df_ex['rs_score_20'] <= 0])

print("\n-- RS Score buckets --")
bins   = [-999, -10, -5, 0, 5, 10, 20, 999]
labels = ['<-10', '-10 to -5', '-5 to 0', '0 to 5', '5 to 10', '10 to 20', '>20']
df_ex['rs_bucket'] = pd.cut(df_ex['rs_score_20'], bins=bins, labels=labels)
for b in labels:
    stats(f"RS score {b}", df_ex[df_ex['rs_bucket'] == b])

print("\n-- Winners: what was their RS score distribution? --")
winners = df_ex[df_ex['outcome'] == 'WIN']
print(f"  Winners with RS score > 0 : {(winners['rs_score_20'] > 0).sum()} ({(winners['rs_score_20'] > 0).mean()*100:.1f}%)")
print(f"  Winners with RS score <= 0: {(winners['rs_score_20'] <= 0).sum()} ({(winners['rs_score_20'] <= 0).mean()*100:.1f}%)")
print(f"  Avg RS score of winners   : {winners['rs_score_20'].mean():.2f}")
print(f"  Avg RS score of losers    : {df_ex[df_ex['outcome']=='LOSS']['rs_score_20'].mean():.2f}")
print(f"  Median RS score of winners: {winners['rs_score_20'].median():.2f}")
print(f"  Median RS score of losers : {df_ex[df_ex['outcome']=='LOSS']['rs_score_20'].median():.2f}")

print("\n-- Best combo: RS score > 0 + sector top 3 or 6-12 (40d) --")
sec_ok = (
    (df_ex['sec_global_rank'] <= 3) |
    ((df_ex['sec_global_rank'] >= 6) & (df_ex['sec_global_rank'] <= 12))
)
stats("RS>0 + sector top3/6-12", df_ex[(df_ex['rs_score_20'] > 0) & sec_ok])
stats("RS>0 + sector top3/6-12 + sec_rank<=8", df_ex[
    (df_ex['rs_score_20'] > 0) & sec_ok & (df_ex['sector_rs_rank'] <= 8)
])
stats("RS<=0 + sector top3/6-12", df_ex[(df_ex['rs_score_20'] <= 0) & sec_ok])

print("\nDone.")
