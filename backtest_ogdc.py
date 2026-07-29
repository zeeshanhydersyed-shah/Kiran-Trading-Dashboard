"""
backtest_ogdc.py — Minervini breakout backtest for OGDC  (2005–2026)
=====================================================================
Entry  : All 14 gates fire on signal day → enter at that day's close
Stop   : 0.5% below the low of the entry candle  (hard SL, checked intraday)
Trail  : Close drops below EMA20 → exit at next day's open
One position at a time; re-entry allowed after exit.

Data sources (stitched chronologically):
  2005-2009  psx_historical_2005_2010.db   prices_staging / index_prices_staging
  2010-2014  psx_historical_2010_2015.db
  2015-2019  psx_historical_2015_2020.db
  2020-2026  psx_data.db                   prices / index_prices
"""

import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd

BASE    = Path(__file__).parent
OUT_DIR = BASE / "backtest_results"
OUT_DIR.mkdir(exist_ok=True)

TARGET  = "OGDC"
OGDC_SECTOR = "OIL & GAS EXPLORATION COMPANIES"

PARAMS = dict(
    min_avg_vol           = 100_000,
    vol_mult              = 2.0,
    rs_min_long           = 60,
    atr_min_pct           = 1.0,
    atr_max_pct           = 6.0,
    resist_win            = 60,
    bb_max_width          = 12.0,
    overhead_mult         = 1.05,
    ema_trend             = 50,
    mkt_breadth_min       = 60.0,
    sector_rs_rank_max    = 6,
    sector_breadth_min    = 70.0,
    stock_rs_rank_max     = 50,
    stock_sector_rank_max = 5,
    sl_below_low_pct      = 0.005,   # 0.5% below entry candle low
)


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD — stitch all historical DBs + current DB
# ══════════════════════════════════════════════════════════════════════════════

def load_all():
    hist_dbs = [
        BASE / "psx_historical_2005_2010.db",
        BASE / "psx_historical_2010_2015.db",
        BASE / "psx_historical_2015_2020.db",
    ]
    main_db = BASE / "psx_data.db"

    stock_frames = []
    index_frames = []

    # Historical DBs
    for path in hist_dbs:
        con = sqlite3.connect(path)
        sf = pd.read_sql("SELECT symbol,date,open,high,low,close,volume FROM prices_staging", con, parse_dates=["date"])
        ix = pd.read_sql("SELECT symbol,date,close FROM index_prices_staging WHERE symbol='KSE-100'", con, parse_dates=["date"])
        con.close()
        stock_frames.append(sf)
        index_frames.append(ix)

    # Main DB (2020+)
    con = sqlite3.connect(main_db)
    sf  = pd.read_sql("SELECT symbol,date,open,high,low,close,volume FROM prices", con, parse_dates=["date"])
    ix  = pd.read_sql("SELECT symbol,date,close FROM index_prices WHERE symbol='KSE-100'", con, parse_dates=["date"])

    # Sector mapping from main DB
    sectors = pd.read_sql("SELECT symbol, sector FROM sectors", con)
    con.close()

    stock_frames.append(sf)
    index_frames.append(ix)

    stocks = pd.concat(stock_frames, ignore_index=True)
    stocks = stocks.drop_duplicates(subset=["symbol","date"]).sort_values(["symbol","date"]).reset_index(drop=True)

    index = pd.concat(index_frames, ignore_index=True)
    index = (index.drop_duplicates(subset=["date"])
                  .sort_values("date")
                  .rename(columns={"close":"idx_close"})
                  .reset_index(drop=True))

    # Attach sector — fill OGDC explicitly for pre-2020 rows lacking it
    stocks = stocks.merge(sectors[["symbol","sector"]], on="symbol", how="left")
    stocks.loc[(stocks["symbol"]==TARGET) & stocks["sector"].isna(), "sector"] = OGDC_SECTOR

    return stocks, index


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURES
# ══════════════════════════════════════════════════════════════════════════════

def build_features(stocks: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    df = stocks.copy()
    g  = df.groupby("symbol", sort=False)

    print("  EMAs ...")
    for n in [20, 50, 200]:
        df[f"ema{n}"] = g["close"].transform(lambda s, n=n: s.ewm(span=n, adjust=False).mean())

    df["stage2"] = (
        (df["close"] > df["ema20"]) &
        (df["ema20"] > df["ema50"]) &
        (df["ema50"] > df["ema200"])
    )

    print("  ATR14 ...")
    pc = g["close"].transform(lambda s: s.shift(1))
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    df["atr14"]   = g["close"].transform(lambda s: tr.loc[s.index].rolling(14, min_periods=14).mean())
    df["atr_pct"] = df["atr14"] / df["close"] * 100

    print("  Pivot / breakout ...")
    rw = PARAMS["resist_win"]
    df["pivot_high"] = g["close"].transform(lambda s: s.rolling(rw, min_periods=rw).max().shift(1))
    df["pivot_low"]  = g["close"].transform(lambda s: s.rolling(rw, min_periods=rw).min().shift(1))

    _prev = g["close"].transform(lambda s: s.shift(1))
    df["bo_long"] = (df["close"] > df["pivot_high"]) & (_prev <= df["pivot_high"])

    print("  Bollinger Band width ...")
    def _bb(s):
        sma = s.rolling(20, min_periods=20).mean()
        std = s.rolling(20, min_periods=20).std(ddof=1)
        return (4.0 * std / sma * 100).shift(1)

    df["bb_width"]   = g["close"].transform(_bb)
    df["tight_base"] = df["bb_width"] <= PARAMS["bb_max_width"]

    print("  No-overhead supply ...")
    df["high_200d"]   = g["high"].transform(lambda s: s.rolling(200, min_periods=200).max().shift(1))
    df["no_overhead"] = (
        df["high_200d"].notna() &
        df["pivot_high"].notna() &
        (df["high_200d"] <= df["pivot_high"] * PARAMS["overhead_mult"])
    )

    print("  Volume ...")
    df["vol_avg20"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean().shift(1))
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]
    df["liquid"]    = df["vol_avg20"] >= PARAMS["min_avg_vol"]
    df["vol_ok"]    = df["vol_ratio"] >= PARAMS["vol_mult"]

    print("  RS Rating ...")
    for w, c in [(21,"r21"),(63,"r63"),(126,"r126"),(252,"r252")]:
        df[c] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["rs_raw"]    = 0.40*df["r252"] + 0.30*df["r126"] + 0.20*df["r63"] + 0.10*df["r21"]
    df["rs_rating"] = df.groupby("date")["rs_raw"].rank(pct=True, method="average") * 100

    print("  Index merge + market_up ...")
    idx = index.copy()
    for w, c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
        idx[c] = idx["idx_close"] / idx["idx_close"].shift(w) - 1
    idx["idx_ema50"] = idx["idx_close"].ewm(span=PARAMS["ema_trend"], adjust=False).mean()
    idx["market_up"] = idx["idx_close"] > idx["idx_ema50"]

    df = df.merge(idx[["date","ir21","ir63","ir126","ir252","market_up","idx_close","idx_ema50"]], on="date", how="left")
    df["market_up"] = df["market_up"].fillna(False).astype(bool)

    df["vol_filter"] = (df["atr_pct"] >= PARAMS["atr_min_pct"]) & (df["atr_pct"] <= PARAMS["atr_max_pct"])

    print("  Market breadth (% stocks above EMA20) ...")
    df["above_ema20"] = (df["close"] > df["ema20"]).astype(float)
    mkt_breadth = (df.groupby("date")["above_ema20"].mean() * 100).rename("mkt_breadth")
    df = df.merge(mkt_breadth.reset_index(), on="date", how="left")
    df["breadth_ok"] = df["mkt_breadth"] >= PARAMS["mkt_breadth_min"]

    print("  Sector RS-20 rank ...")
    # RS-20 = 20-day return of stock relative to KSE-100, averaged per sector
    df["r20"] = g["close"].transform(lambda s: s / s.shift(20) - 1)
    idx_r20 = idx[["date"]].copy()
    idx_r20["idx_r20"] = idx["idx_close"] / idx["idx_close"].shift(20) - 1
    df = df.merge(idx_r20[["date","idx_r20"]], on="date", how="left")
    df["rs20_vs_idx"] = df["r20"] - df["idx_r20"]

    sec_rs = (df.groupby(["date","sector"])["rs20_vs_idx"].mean()
                .reset_index().rename(columns={"rs20_vs_idx":"sec_rs20"}))
    sec_rs["sector_rs_rank"] = sec_rs.groupby("date")["sec_rs20"].rank(ascending=False, method="min")
    df = df.merge(sec_rs[["date","sector","sector_rs_rank"]], on=["date","sector"], how="left")
    df["sector_rs_ok"] = df["sector_rs_rank"] <= PARAMS["sector_rs_rank_max"]

    print("  Sector breadth ...")
    sec_breadth = (df.groupby(["date","sector"])["above_ema20"].mean() * 100).reset_index()
    sec_breadth.rename(columns={"above_ema20":"sector_breadth"}, inplace=True)
    df = df.merge(sec_breadth, on=["date","sector"], how="left")
    df["sector_breadth_ok"] = df["sector_breadth"] >= PARAMS["sector_breadth_min"]

    print("  Stock RS rank (market-wide) ...")
    df["rs_rank"] = df.groupby("date")["rs_rating"].rank(ascending=False, method="min")
    df["rs_rank_ok"] = df["rs_rank"] <= PARAMS["stock_rs_rank_max"]

    print("  Stock RS rank (within sector) ...")
    df["stock_sec_rank"] = df.groupby(["date","sector"])["rs_rating"].rank(ascending=False, method="min")
    df["stock_sec_rank_ok"] = df["stock_sec_rank"] <= PARAMS["stock_sector_rank_max"]

    print("  Full signal ...")
    df["signal_long"] = (
        df["stage2"]           &
        df["bo_long"]          &
        df["tight_base"]       &
        df["no_overhead"]      &
        df["vol_ok"]           &
        df["liquid"]           &
        df["market_up"]        &
        df["vol_filter"]       &
        df["breadth_ok"]       &
        df["sector_rs_ok"]     &
        df["sector_breadth_ok"] &
        df["rs_rank_ok"]       &
        df["stock_sec_rank_ok"] &
        (df["rs_rating"] >= PARAMS["rs_min_long"])
    )

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SIMULATE TRADES
# ══════════════════════════════════════════════════════════════════════════════

def simulate(ogdc: pd.DataFrame) -> pd.DataFrame:
    rows = ogdc.reset_index(drop=True)
    n    = len(rows)
    trades = []
    in_trade = False

    i = 0
    while i < n:
        r = rows.iloc[i]

        if not in_trade:
            if r["signal_long"]:
                entry_price = r["close"]
                entry_low   = r["low"]
                sl          = entry_low * (1 - PARAMS["sl_below_low_pct"])
                entry_date  = r["date"]
                entry_idx   = i
                in_trade    = True
            i += 1
            continue

        # Already in trade — evaluate from day after entry
        if i == entry_idx:
            i += 1
            continue

        # 1. Hard SL: low of current bar breaches SL
        if r["low"] <= sl:
            trades.append(_trade(entry_date, r["date"], entry_price, sl, "Hard SL"))
            in_trade = False
            i += 1
            continue

        # 2. Trailing SL: close below EMA20 → exit next open
        if r["close"] < r["ema20"]:
            if i + 1 < n:
                nxt = rows.iloc[i + 1]
                exit_price = nxt["open"]
                exit_date  = nxt["date"]
            else:
                exit_price = r["close"]
                exit_date  = r["date"]
            trades.append(_trade(entry_date, exit_date, entry_price, exit_price, "Trail EMA20"))
            in_trade = False
            i += 2
            continue

        i += 1

    # Open at end of data
    if in_trade:
        last = rows.iloc[-1]
        trades.append(_trade(entry_date, last["date"], entry_price, last["close"], "OPEN"))

    return pd.DataFrame(trades)


def _trade(entry_date, exit_date, entry_price, exit_price, reason):
    pnl = (exit_price / entry_price - 1) * 100
    return dict(
        entry_date  = entry_date,
        exit_date   = exit_date,
        entry_price = round(entry_price, 2),
        exit_price  = round(exit_price, 2),
        pnl_pct     = round(pnl, 2),
        days_held   = (exit_date - entry_date).days,
        exit_reason = reason,
        outcome     = "Win" if pnl > 0 else ("Loss" if pnl < 0 else "BE"),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  GATE FUNNEL
# ══════════════════════════════════════════════════════════════════════════════

def gate_funnel(ogdc: pd.DataFrame):
    total = len(ogdc)
    gates = [
        ("Stage 2",              ogdc["stage2"]),
        ("Breakout (60d high)",  ogdc["bo_long"]),
        ("Tight Base ≤12%",      ogdc["tight_base"]),
        ("No Overhead ≤5%",      ogdc["no_overhead"]),
        ("Volume ≥2×avg",        ogdc["vol_ok"]),
        ("Liquid ≥100k",         ogdc["liquid"]),
        ("Market Up (EMA50)",    ogdc["market_up"]),
        ("ATR 1–6%",             ogdc["vol_filter"]),
        ("Mkt Breadth ≥60%",     ogdc["breadth_ok"]),
        ("Sector RS Top-6",      ogdc["sector_rs_ok"]),
        ("Sector Breadth ≥70%",  ogdc["sector_breadth_ok"]),
        ("RS Rank ≤50",          ogdc["rs_rank_ok"]),
        ("Sec Rank ≤5",          ogdc["stock_sec_rank_ok"]),
        ("RS Rating ≥60",        ogdc["rs_rating"] >= PARAMS["rs_min_long"]),
    ]
    print(f"\n{'Gate':<28} {'Pass':>6}  {'%':>6}  {'Cum':>6}  {'Cum%':>6}")
    print("─" * 58)
    cum = pd.Series([True] * total)
    for label, mask in gates:
        solo = int(mask.sum())
        cum  = cum & mask
        c    = int(cum.sum())
        print(f"  {label:<26} {solo:>6}  {solo/total*100:>5.1f}%  {c:>6}  {c/total*100:>5.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY STATS
# ══════════════════════════════════════════════════════════════════════════════

def summary(results: pd.DataFrame):
    if results.empty:
        print("\n  No trades generated.")
        return

    closed = results[results["exit_reason"] != "OPEN"]
    wins   = closed[closed["outcome"] == "Win"]
    losses = closed[closed["outcome"] == "Loss"]
    n      = len(closed)
    nw     = len(wins)
    nl     = len(losses)

    print(f"\n{'═'*55}")
    print(f"  OGDC Minervini Backtest — Summary")
    print(f"{'═'*55}")
    print(f"  Period        : {results['entry_date'].min().date()} → {results['exit_date'].max().date()}")
    print(f"  Total trades  : {len(results)}  ({n} closed, {len(results)-n} open)")
    print(f"  Win rate      : {nw}/{n}  ({nw/n*100:.1f}%)" if n else "  No closed trades")
    if nw:
        print(f"  Avg win       : +{wins['pnl_pct'].mean():.2f}%   Max: +{wins['pnl_pct'].max():.2f}%")
    if nl:
        print(f"  Avg loss      :  {losses['pnl_pct'].mean():.2f}%   Max: {losses['pnl_pct'].min():.2f}%")
    if n:
        print(f"  Avg hold      : {closed['days_held'].mean():.1f} days")
        print(f"  Expectancy    : {closed['pnl_pct'].mean():.2f}% per trade")
        hard_sl = closed[closed["exit_reason"]=="Hard SL"]
        trail   = closed[closed["exit_reason"]=="Trail EMA20"]
        print(f"  Hard SL exits : {len(hard_sl)}")
        print(f"  Trail exits   : {len(trail)}")
    print(f"{'═'*55}")

    print(f"\n{'─'*80}")
    print(f"  Trade Log")
    print(f"{'─'*80}")
    print(f"  {'#':>3}  {'Entry':>12}  {'Exit':>12}  {'Entry Px':>9}  {'Exit Px':>8}  {'P&L%':>7}  {'Days':>5}  Reason")
    print(f"  {'─'*3}  {'─'*12}  {'─'*12}  {'─'*9}  {'─'*8}  {'─'*7}  {'─'*5}  {'─'*12}")
    for idx, row in results.iterrows():
        flag = "★" if row["outcome"]=="Win" else ("✗" if row["outcome"]=="Loss" else "○")
        print(f"  {idx+1:>3}  {str(row['entry_date'])[:10]:>12}  {str(row['exit_date'])[:10]:>12}  "
              f"{row['entry_price']:>9.2f}  {row['exit_price']:>8.2f}  "
              f"{row['pnl_pct']:>+7.2f}%  {row['days_held']:>5}  {flag} {row['exit_reason']}")

    by_reason = closed.groupby("exit_reason")["pnl_pct"].agg(["count","mean","min","max"])
    print(f"\n  By exit reason:\n{by_reason.to_string()}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  OGDC Minervini Backtest")
    print("=" * 60)

    print("\n[1] Loading data ...")
    stocks, index = load_all()
    print(f"    Stocks: {len(stocks):,} rows | {stocks['symbol'].nunique()} symbols | "
          f"{stocks['date'].min().date()} → {stocks['date'].max().date()}")
    print(f"    Index : {len(index):,} rows | {index['date'].min().date()} → {index['date'].max().date()}")

    print("\n[2] Building features ...")
    df = build_features(stocks, index)

    ogdc = df[df["symbol"] == TARGET].copy().reset_index(drop=True)
    print(f"\n    OGDC: {len(ogdc)} rows | {ogdc['date'].min().date()} → {ogdc['date'].max().date()}")
    print(f"    Signals: {int(ogdc['signal_long'].sum())}")

    print("\n[3] Gate funnel for OGDC:")
    gate_funnel(ogdc)

    print("\n[4] Simulating trades ...")
    results = simulate(ogdc)

    summary(results)

    # Save
    out = OUT_DIR / "ogdc_backtest_results.csv"
    if not results.empty:
        results.to_csv(out, index=False)
        print(f"\n  Saved → {out}")
