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
stocks.loc[(stocks["symbol"]=="OGDC") & stocks["sector"].isna(), "sector"] = "OIL & GAS EXPLORATION COMPANIES"

print("Data loaded. Building features...")

df = stocks.copy()
g  = df.groupby("symbol", sort=False)

for n in [20,50,200]:
    df[f"ema{n}"] = g["close"].transform(lambda s,n=n: s.ewm(span=n,adjust=False).mean())
df["stage2"] = (df["close"]>df["ema20"])&(df["ema20"]>df["ema50"])&(df["ema50"]>df["ema200"])

pc = g["close"].transform(lambda s: s.shift(1))
tr = pd.concat([df["high"]-df["low"],(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
df["atr14"] = g["close"].transform(lambda s: tr.loc[s.index].rolling(14,min_periods=14).mean())
df["atr_pct"] = df["atr14"]/df["close"]*100

df["pivot_high"] = g["close"].transform(lambda s: s.rolling(60,min_periods=60).max().shift(1))
_prev = g["close"].transform(lambda s: s.shift(1))
df["bo_long"] = (df["close"]>df["pivot_high"])&(_prev<=df["pivot_high"])

def _bb(s):
    sma=s.rolling(20,min_periods=20).mean()
    std=s.rolling(20,min_periods=20).std(ddof=1)
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

idx = index.copy()
for w,c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
    idx[c] = idx["idx_close"]/idx["idx_close"].shift(w)-1
idx["idx_ema50"] = idx["idx_close"].ewm(span=50,adjust=False).mean()
idx["market_up"] = idx["idx_close"]>idx["idx_ema50"]
df = df.merge(idx[["date","ir21","ir63","ir126","ir252","market_up","idx_close","idx_ema50"]],on="date",how="left")
df["market_up"] = df["market_up"].fillna(False).astype(bool)
df["vol_filter"] = (df["atr_pct"]>=1.0)&(df["atr_pct"]<=6.0)

df["above_ema20"] = (df["close"]>df["ema20"]).astype(float)
mkt_b = (df.groupby("date")["above_ema20"].mean()*100).rename("mkt_breadth")
df = df.merge(mkt_b.reset_index(),on="date",how="left")
df["breadth_ok"] = df["mkt_breadth"]>=60.0

df["r20"] = g["close"].transform(lambda s: s/s.shift(20)-1)
idx_r20 = idx[["date"]].copy()
idx_r20["idx_r20"] = idx["idx_close"]/idx["idx_close"].shift(20)-1
df = df.merge(idx_r20[["date","idx_r20"]],on="date",how="left")
df["rs20_vs_idx"] = df["r20"]-df["idx_r20"]

sec_rs = (df.groupby(["date","sector"])["rs20_vs_idx"].mean()
            .reset_index().rename(columns={"rs20_vs_idx":"sec_rs20"}))
sec_rs["sector_rs_rank"] = sec_rs.groupby("date")["sec_rs20"].rank(ascending=False,method="min")
df = df.merge(sec_rs[["date","sector","sector_rs_rank"]],on=["date","sector"],how="left")
df["sector_rs_ok"] = df["sector_rs_rank"]<=6

sec_b = (df.groupby(["date","sector"])["above_ema20"].mean()*100).reset_index()
sec_b.rename(columns={"above_ema20":"sector_breadth"},inplace=True)
df = df.merge(sec_b,on=["date","sector"],how="left")
df["sector_breadth_ok"] = df["sector_breadth"]>=70.0

df["rs_rank"] = df.groupby("date")["rs_rating"].rank(ascending=False,method="min")
df["rs_rank_ok"] = df["rs_rank"]<=50

df["stock_sec_rank"] = df.groupby(["date","sector"])["rs_rating"].rank(ascending=False,method="min")
df["stock_sec_rank_ok"] = df["stock_sec_rank"]<=5

print("Done. Checking 2016-12-05...\n")

TARGET_DATE = pd.Timestamp("2016-12-05")
ogdc = df[df["symbol"]=="OGDC"].copy()
row  = ogdc[ogdc["date"]==TARGET_DATE]

if row.empty:
    print("No data for OGDC on 2016-12-05")
else:
    r = row.iloc[0]
    gates = [
        ("Stage 2",             bool(r["stage2"])),
        ("Breakout (60d high)", bool(r["bo_long"])),
        ("Tight Base <=12%",   bool(r["tight_base"])),
        ("No Overhead <=5%",   bool(r["no_overhead"])),
        ("Volume >=2x avg",    bool(r["vol_ok"])),
        ("Liquid >=100k",      bool(r["liquid"])),
        ("Market Up (EMA50)",  bool(r["market_up"])),
        ("ATR 1-6%",           bool(r["vol_filter"])),
        ("Mkt Breadth >=60%",  bool(r["breadth_ok"])),
        ("Sector RS Top-6",    bool(r["sector_rs_ok"])),
        ("Sector Breadth >=70%",bool(r["sector_breadth_ok"])),
        ("RS Rank <=50",       bool(r["rs_rank_ok"])),
        ("Sec Rank <=5",       bool(r["stock_sec_rank_ok"])),
        ("RS Rating >=60",     bool(r["rs_rating"]>=60)),
    ]

    print(f"OGDC  2016-12-05")
    print(f"  Close={r['close']:.2f}  Vol={r['volume']/1e6:.3f}M  VolAvg20={r['vol_avg20']/1e6:.3f}M  VolRatio={r['vol_ratio']:.2f}x")
    print(f"  EMA20={r['ema20']:.2f}  EMA50={r['ema50']:.2f}  EMA200={r['ema200']:.2f}")
    print(f"  PivotHigh(60d)={r['pivot_high']:.2f}  High200d={r['high_200d']:.2f}  BBwidth={r['bb_width']:.2f}%")
    print(f"  ATR%={r['atr_pct']:.2f}%  RS_Rating={r['rs_rating']:.1f}  RS_Rank={r['rs_rank']:.0f}")
    print(f"  MktBreadth={r['mkt_breadth']:.1f}%  SecRSRank={r['sector_rs_rank']:.0f}  SecBreadth={r['sector_breadth']:.1f}%")
    print(f"  StockSecRank={r['stock_sec_rank']:.0f}")
    print()
    for label, val in gates:
        status = "PASS" if val else "FAIL"
        print(f"  [{status}]  {label}")

    top_sectors = sec_rs[sec_rs["date"]==TARGET_DATE].sort_values("sector_rs_rank")
    print(f"\nTop sectors by RS-20 on 2016-12-05:")
    print(top_sectors[["sector","sec_rs20","sector_rs_rank"]].head(10).to_string(index=False))

    # Also show nearby OGDC signal days (where it nearly fired)
    print(f"\nOGDC gate status around Dec 2016 (where bo_long=True):")
    nearby = ogdc[(ogdc["date"]>="2016-10-01") & (ogdc["date"]<="2017-02-28") & ogdc["bo_long"]]
    if nearby.empty:
        print("  No breakout days in that window")
    else:
        for _, nr in nearby.iterrows():
            print(f"  {str(nr['date'])[:10]}  close={nr['close']:.1f}  vol_ok={nr['vol_ok']}  breadth={nr['mkt_breadth']:.1f}%  sec_rs={nr['sector_rs_rank']:.0f}  rs_rank={nr['rs_rank']:.0f}  rs_rat={nr['rs_rating']:.1f}")
