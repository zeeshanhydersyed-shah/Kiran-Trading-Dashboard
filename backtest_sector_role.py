"""
Does sector rank at time of BOS determine resolution?
Slice all outcomes AND incomplete events by sector rank bucket.
"""
import sqlite3
import pandas as pd

DB = 'psx_data.db'
WIN_TARGET  = 0.18
LOSS_STOP   = -0.06
WINDOWS     = [20, 40, 60]

con = sqlite3.connect(DB)
signals = pd.read_sql_query("""
    SELECT ss.date, ss.symbol,
           ss.rs_rank, ss.sector_rs_rank, ss.rs_score_20,
           ss.base_tightness, ss.avg_vol_10d, ss.stage2_bull,
           mr.regime,
           sec.rs_rank AS sector_global_rank
    FROM stock_signals ss
    LEFT JOIN market_regime mr ON mr.date = ss.date
    LEFT JOIN sector_signals sec
           ON sec.date = ss.date AND sec.sector = (
               SELECT sector FROM sectors WHERE symbol = ss.symbol LIMIT 1
           )
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

records = []
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

    rec = {k: row[k] for k in ['date','symbol','rs_rank','sector_rs_rank',
                                 'base_tightness','regime','stage2_bull','sector_global_rank']}
    for W in WINDOWS:
        outcome = 'INCOMPLETE'
        max_gain = 0.0
        for j in range(i0 + 1, min(i0 + W + 1, len(sp))):
            c = sp.loc[j, 'close']
            if c is None: continue
            chg = (c - entry) / entry
            max_gain = max(max_gain, chg)
            if chg <= LOSS_STOP:  outcome = 'WIN' if False else 'LOSS'; break
            if chg >= WIN_TARGET: outcome = 'WIN'; break
        rec[f'out_{W}d']  = outcome
        rec[f'gain_{W}d'] = round(max_gain * 100, 1)
    records.append(rec)

df = pd.DataFrame(records)

def stats(label, sub, window=20):
    col = f'out_{window}d'
    res = sub[sub[col].isin(['WIN','LOSS'])]
    inc = sub[sub[col] == 'INCOMPLETE']
    if len(res) == 0:
        print(f"  {label:<40}  no resolved events")
        return
    wr = (res[col] == 'WIN').mean() * 100
    ev = wr/100 * WIN_TARGET*100 + (1-wr/100) * LOSS_STOP*100
    print(f"  {label:<40}  resolved={len(res):>4} ({len(res)/len(sub)*100:.0f}%)  "
          f"incomplete={len(inc):>4}  WR={wr:.1f}%  EV={ev:+.2f}%")

# ── Sector global rank (sector's RS rank vs all other sectors) ────────────────
bins_g   = [0, 3, 5, 8, 12, 9999]
labels_g = ['Sector top 3','Sector 4-5','Sector 6-8','Sector 9-12','Sector 13+']
df['sec_global_bucket'] = pd.cut(df['sector_global_rank'], bins=bins_g, labels=labels_g)

print("=" * 75)
print("SECTOR GLOBAL RANK AT TIME OF BOS  (how strong was the sector vs all sectors?)")
print("=" * 75)
for W in WINDOWS:
    print(f"\n  -- {W}-day window --")
    for b in labels_g:
        stats(b, df[df['sec_global_bucket'] == b], W)

# ── TRENDING_UP only ──────────────────────────────────────────────────────────
up = df[df['regime'] == 'TRENDING_UP'].copy()
up['sec_global_bucket'] = pd.cut(up['sector_global_rank'], bins=bins_g, labels=labels_g)

print("\n" + "=" * 75)
print("TRENDING_UP ONLY — SECTOR GLOBAL RANK AT BOS")
print("=" * 75)
for W in WINDOWS:
    print(f"\n  -- {W}-day window --")
    for b in labels_g:
        stats(b, up[up['sec_global_bucket'] == b], W)

# ── Cross: sector global rank x stock RS rank (TRENDING_UP, 40d) ─────────────
print("\n" + "=" * 75)
print("TRENDING_UP + 40d: SECTOR RANK vs STOCK RS RANK CROSS")
print("=" * 75)
up['rs_bucket'] = pd.cut(up['rs_rank'], bins=[0,50,100,200,9999],
                          labels=['RS top 50','RS 51-100','RS 101-200','RS 201+'])
for sb in labels_g:
    for rb in ['RS top 50','RS 51-100','RS 101-200','RS 201+']:
        sub = up[(up['sec_global_bucket'] == sb) & (up['rs_bucket'] == rb)]
        if len(sub) < 10: continue
        stats(f"{sb} x {rb}", sub, 40)

print("\nDone.")
