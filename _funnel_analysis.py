"""
Funnel analysis — full PSX universe
Shows where signal count dies gate by gate, and which gates are
structurally mismatched to PSX vs genuinely protective.
"""
import warnings; warnings.filterwarnings("ignore")
import sqlite3, pandas as pd, numpy as np
from pathlib import Path

BASE = Path("C:/Users/Lenovo/psx_pipeline")

hist_dbs = [
    BASE / "psx_historical_2005_2010.db",
    BASE / "psx_historical_2010_2015.db",
    BASE / "psx_historical_2015_2020.db",
]
main_db = BASE / "psx_data.db"

sf_list, ix_list = [], []
for path in hist_dbs:
    con = sqlite3.connect(path)
    sf_list.append(pd.read_sql("SELECT symbol,date,open,high,low,close,volume FROM prices_staging", con, parse_dates=["date"]))
    ix_list.append(pd.read_sql("SELECT symbol,date,close FROM index_prices_staging WHERE symbol='KSE-100'", con, parse_dates=["date"]))
    con.close()
con = sqlite3.connect(main_db)
sf_list.append(pd.read_sql("SELECT symbol,date,open,high,low,close,volume FROM prices", con, parse_dates=["date"]))
ix_list.append(pd.read_sql("SELECT symbol,date,close FROM index_prices WHERE symbol='KSE-100'", con, parse_dates=["date"]))
sectors = pd.read_sql("SELECT symbol, sector FROM sectors", con); con.close()

stocks = pd.concat(sf_list).drop_duplicates(["symbol","date"]).sort_values(["symbol","date"]).reset_index(drop=True)
index  = pd.concat(ix_list).drop_duplicates(["date"]).sort_values("date").rename(columns={"close":"idx_close"}).reset_index(drop=True)
stocks = stocks.merge(sectors, on="symbol", how="left")

print("Building features...")
df = stocks.copy()
g  = df.groupby("symbol", sort=False)

for n in [20,50,200]:
    df[f"ema{n}"] = g["close"].transform(lambda s,n=n: s.ewm(span=n,adjust=False).mean())
df["stage2"] = (df["close"]>df["ema20"])&(df["ema20"]>df["ema50"])&(df["ema50"]>df["ema200"])

pc = g["close"].transform(lambda s: s.shift(1))
tr = pd.concat([df["high"]-df["low"],(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
df["atr14"]   = g["close"].transform(lambda s: tr.loc[s.index].rolling(14,min_periods=14).mean())
df["atr_pct"] = df["atr14"]/df["close"]*100

df["pivot_high"] = g["close"].transform(lambda s: s.rolling(60,min_periods=60).max().shift(1))
_prev = g["close"].transform(lambda s: s.shift(1))
df["bo_long"] = (df["close"]>df["pivot_high"])&(_prev<=df["pivot_high"])

def _bb(s):
    sma=s.rolling(20,min_periods=20).mean(); std=s.rolling(20,min_periods=20).std(ddof=1)
    return (4*std/sma*100).shift(1)
df["bb_width"]   = g["close"].transform(_bb)
df["tight_base"] = df["bb_width"]<=12.0

df["high_200d"]   = g["high"].transform(lambda s: s.rolling(200,min_periods=200).max().shift(1))
df["no_overhead"] = df["high_200d"].notna()&df["pivot_high"].notna()&(df["high_200d"]<=df["pivot_high"]*1.05)

df["vol_avg20"] = g["volume"].transform(lambda s: s.rolling(20,min_periods=20).mean().shift(1))
df["vol_ratio"] = df["volume"]/df["vol_avg20"]
df["liquid"]    = df["vol_avg20"]>=100_000
df["vol_ok"]    = df["vol_ratio"]>=2.0

for w,c in [(21,"r21"),(63,"r63"),(126,"r126"),(252,"r252")]:
    df[c] = g["close"].transform(lambda s,w=w: s/s.shift(w)-1)
df["rs_raw"]    = 0.40*df["r252"]+0.30*df["r126"]+0.20*df["r63"]+0.10*df["r21"]
df["rs_rating"] = df.groupby("date")["rs_raw"].rank(pct=True,method="average")*100

idx=index.copy()
for w,c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
    idx[c]=idx["idx_close"]/idx["idx_close"].shift(w)-1
idx["idx_ema50"]=idx["idx_close"].ewm(span=50,adjust=False).mean()
idx["market_up"]=idx["idx_close"]>idx["idx_ema50"]
df=df.merge(idx[["date","ir21","ir63","ir126","ir252","market_up","idx_close","idx_ema50"]],on="date",how="left")
df["market_up"]=df["market_up"].fillna(False).astype(bool)
df["vol_filter"]=(df["atr_pct"]>=1.0)&(df["atr_pct"]<=6.0)

df["above_ema20"]=(df["close"]>df["ema20"]).astype(float)
mkt_b=(df.groupby("date")["above_ema20"].mean()*100).rename("mkt_breadth")
df=df.merge(mkt_b.reset_index(),on="date",how="left")
df["breadth_ok"]=df["mkt_breadth"]>=60.0

df["r20"]=g["close"].transform(lambda s: s/s.shift(20)-1)
idx_r20=idx[["date"]].copy(); idx_r20["idx_r20"]=idx["idx_close"]/idx["idx_close"].shift(20)-1
df=df.merge(idx_r20[["date","idx_r20"]],on="date",how="left")
df["rs20_vs_idx"]=df["r20"]-df["idx_r20"]
sec_rs=(df.groupby(["date","sector"])["rs20_vs_idx"].mean().reset_index().rename(columns={"rs20_vs_idx":"sec_rs20"}))
sec_rs["sector_rs_rank"]=sec_rs.groupby("date")["sec_rs20"].rank(ascending=False,method="min")
df=df.merge(sec_rs[["date","sector","sector_rs_rank"]],on=["date","sector"],how="left")
df["sector_rs_ok"]=df["sector_rs_rank"]<=6

sec_b=(df.groupby(["date","sector"])["above_ema20"].mean()*100).reset_index().rename(columns={"above_ema20":"sector_breadth"})
df=df.merge(sec_b,on=["date","sector"],how="left")
df["sector_breadth_ok"]=df["sector_breadth"]>=70.0

df["rs_rank"]=df.groupby("date")["rs_rating"].rank(ascending=False,method="min")
df["rs_rank_ok"]=df["rs_rank"]<=50

df["stock_sec_rank"]=df.groupby(["date","sector"])["rs_rating"].rank(ascending=False,method="min")
df["stock_sec_rank_ok"]=df["stock_sec_rank"]<=5

print("Done.\n")

# ── 1. Cumulative funnel across the full universe ──────────────────────────────
print("="*65)
print("  GATE FUNNEL — Full PSX Universe (all stock-days)")
print("="*65)

# Only rows that pass stage2 AND bo_long (real candidates)
candidates = df[df["stage2"] & df["bo_long"]].copy()
total = len(candidates)
print(f"\n  Base: Stage2 + Breakout = {total:,} candidate days\n")

gates = [
    ("Tight Base <=12%",      candidates["tight_base"]),
    ("No Overhead <=5%",      candidates["no_overhead"]),
    ("Volume >=2x avg",       candidates["vol_ok"]),
    ("Liquid >=100k",         candidates["liquid"]),
    ("ATR 1-6%",              candidates["vol_filter"]),
    ("Market Up (EMA50)",     candidates["market_up"]),
    ("Mkt Breadth >=60%",     candidates["breadth_ok"]),
    ("RS Rating >=60",        candidates["rs_rating"]>=60),
    ("Sector RS Top-6",       candidates["sector_rs_ok"]),
    ("Sector Breadth >=70%",  candidates["sector_breadth_ok"]),
    ("RS Rank <=50",          candidates["rs_rank_ok"]),
    ("Sec Rank <=5",          candidates["stock_sec_rank_ok"]),
]

print(f"  {'Gate':<28} {'Solo%':>7}  {'Removed':>8}  {'Remaining':>10}")
print("  " + "-"*60)
cum = pd.Series([True]*len(candidates), index=candidates.index)
prev_count = total
for label, mask in gates:
    solo_pass = int(mask.sum())
    cum = cum & mask
    c   = int(cum.sum())
    removed = prev_count - c
    print(f"  {label:<28} {solo_pass/total*100:>6.1f}%  {removed:>8,}  {c:>10,}")
    prev_count = c

print(f"\n  Final signals: {prev_count:,} over 20 years")

# ── 2. Market breadth — how often does PSX meet >=60% threshold? ──────────────
print(f"\n{'='*65}")
print(f"  MARKET BREADTH — how often does PSX meet the >=60% threshold?")
print(f"{'='*65}")
daily_breadth = df.groupby("date")["above_ema20"].mean()*100
total_days = len(daily_breadth)
pass_days  = (daily_breadth>=60).sum()
print(f"\n  Total trading days in data : {total_days:,}")
print(f"  Days breadth >=60%         : {pass_days:,}  ({pass_days/total_days*100:.1f}%)")
print(f"  Days breadth <60%  (BLOCKED): {total_days-pass_days:,}  ({(total_days-pass_days)/total_days*100:.1f}%)")
print(f"\n  Breadth distribution:")
for threshold in [40, 50, 60, 70, 80]:
    p = (daily_breadth>=threshold).sum()
    print(f"    >=  {threshold}%: {p:,} days  ({p/total_days*100:.1f}%)")

# Breadth by year
print(f"\n  Avg breadth and % of days >=60% by year:")
bdf = daily_breadth.reset_index()
bdf.columns = ["date","breadth"]
bdf["year"] = bdf["date"].dt.year
yr = bdf.groupby("year").agg(avg_breadth=("breadth","mean"), days_above=("breadth", lambda x: (x>=60).sum()), total=("breadth","count"))
yr["pct_above"] = yr["days_above"]/yr["total"]*100
for y, row in yr.iterrows():
    bar = "#"*int(row["pct_above"]//5)
    print(f"    {y}  avg={row['avg_breadth']:>5.1f}%  days>=60%: {row['pct_above']:>5.1f}%  [{bar}]")

# ── 3. Volume 2x — PSX specific ───────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  VOLUME SPIKE — how restrictive is the 2x gate?")
print(f"{'='*65}")
# Among stage2 + bo_long candidates, how many have vol >=2x?
print(f"\n  Among Stage2+BO candidates ({total:,} days):")
for mult in [1.0, 1.5, 2.0, 2.5, 3.0]:
    p = (candidates["vol_ratio"]>=mult).sum()
    print(f"    Vol >= {mult:.1f}x avg:  {p:>6,}  ({p/total*100:.1f}%)")

# ── 4. RS Rank — PSX universe is large with many illiquid stocks ──────────────
print(f"\n{'='*65}")
print(f"  RS RANK — is top-50 appropriate for PSX's universe size?")
print(f"{'='*65}")
# How many liquid stocks exist on avg per day?
liquid_per_day = df[df["liquid"]].groupby("date")["symbol"].count()
print(f"\n  Liquid stocks per day (avg): {liquid_per_day.mean():.0f}")
print(f"  Liquid stocks per day (med): {liquid_per_day.median():.0f}")
print(f"  Total unique symbols in universe: {df['symbol'].nunique():,}")
print(f"\n  Among Stage2+BO+liquid candidates, RS rank distribution:")
liq_cands = candidates[candidates["liquid"]]
for rank in [25, 50, 75, 100, 150, 200]:
    p = (liq_cands["rs_rank"]<=rank).sum()
    print(f"    RS rank <=  {rank:>3}:  {p:>5,}  ({p/len(liq_cands)*100:.1f}% of liquid BO candidates)")

# ── 5. No overhead — how many PSX breakouts are true ATH breakouts? ───────────
print(f"\n{'='*65}")
print(f"  NO OVERHEAD — is 5% tolerance appropriate for PSX?")
print(f"{'='*65}")
print(f"\n  Among Stage2+BO candidates, overhead distribution:")
ov = (candidates["high_200d"] / candidates["pivot_high"] - 1) * 100
for pct in [0, 5, 10, 15, 20, 30]:
    p = (ov<=pct).sum() if pct>0 else (ov<=0).sum()
    label = f"<= {pct}% overhead"
    print(f"    {label:<20}:  {p:>6,}  ({p/total*100:.1f}%)")
