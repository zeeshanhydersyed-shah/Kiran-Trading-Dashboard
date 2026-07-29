"""
backtest_full_universe.py — Minervini 14-gate backtest across all PSX stocks
=============================================================================
Entry  : All 14 gates fire → enter at close of signal day
Hard SL: 0.5% below the low of the entry candle (checked via next-day low)
Trail  : Close drops below EMA20 → exit at next day's open
One position per stock at a time; re-entry allowed after exit.
"""

import warnings; warnings.filterwarnings("ignore")
import sqlite3, time
import pandas as pd
import numpy as np
from pathlib import Path

BASE    = Path("C:/Users/Lenovo/psx_pipeline")
OUT_DIR = BASE / "backtest_results"
OUT_DIR.mkdir(exist_ok=True)

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
    sl_below_low_pct      = 0.005,
)


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD
# ══════════════════════════════════════════════════════════════════════════════
def load_all():
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
    sectors = pd.read_sql("SELECT symbol, sector FROM sectors", con)
    con.close()

    stocks = (pd.concat(sf_list)
                .drop_duplicates(["symbol","date"])
                .sort_values(["symbol","date"])
                .reset_index(drop=True))
    index  = (pd.concat(ix_list)
                .drop_duplicates(["date"])
                .sort_values("date")
                .rename(columns={"close":"idx_close"})
                .reset_index(drop=True))
    stocks = stocks.merge(sectors, on="symbol", how="left")
    return stocks, index


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURES
# ══════════════════════════════════════════════════════════════════════════════
def build_features(stocks, index):
    df = stocks.copy()
    g  = df.groupby("symbol", sort=False)

    t0 = time.time()
    def tick(msg):
        print(f"  {msg:<40} {time.time()-t0:5.1f}s")

    for n in [20, 50, 200]:
        df[f"ema{n}"] = g["close"].transform(lambda s, n=n: s.ewm(span=n, adjust=False).mean())
    tick("EMAs done")

    df["stage2"] = (
        (df["close"] > df["ema20"]) &
        (df["ema20"] > df["ema50"]) &
        (df["ema50"] > df["ema200"])
    )

    pc = g["close"].transform(lambda s: s.shift(1))
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    df["atr14"]   = g["close"].transform(lambda s: tr.loc[s.index].rolling(14, min_periods=14).mean())
    df["atr_pct"] = df["atr14"] / df["close"] * 100
    tick("ATR done")

    rw = PARAMS["resist_win"]
    df["pivot_high"] = g["close"].transform(lambda s: s.rolling(rw, min_periods=rw).max().shift(1))
    _prev = g["close"].transform(lambda s: s.shift(1))
    df["bo_long"] = (df["close"] > df["pivot_high"]) & (_prev <= df["pivot_high"])
    tick("Pivot / breakout done")

    def _bb(s):
        sma = s.rolling(20, min_periods=20).mean()
        std = s.rolling(20, min_periods=20).std(ddof=1)
        return (4.0 * std / sma * 100).shift(1)
    df["bb_width"]   = g["close"].transform(_bb)
    df["tight_base"] = df["bb_width"] <= PARAMS["bb_max_width"]
    tick("BB width done")

    df["high_200d"]   = g["high"].transform(lambda s: s.rolling(200, min_periods=200).max().shift(1))
    df["no_overhead"] = (
        df["high_200d"].notna() &
        df["pivot_high"].notna() &
        (df["high_200d"] <= df["pivot_high"] * PARAMS["overhead_mult"])
    )
    tick("No-overhead done")

    df["vol_avg20"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean().shift(1))
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]
    df["liquid"]    = df["vol_avg20"] >= PARAMS["min_avg_vol"]
    df["vol_ok"]    = df["vol_ratio"] >= PARAMS["vol_mult"]
    tick("Volume done")

    for w, c in [(21,"r21"),(63,"r63"),(126,"r126"),(252,"r252")]:
        df[c] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["rs_raw"]    = 0.40*df["r252"] + 0.30*df["r126"] + 0.20*df["r63"] + 0.10*df["r21"]
    df["rs_rating"] = df.groupby("date")["rs_raw"].rank(pct=True, method="average") * 100
    tick("RS Rating done")

    idx = index.copy()
    for w, c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
        idx[c] = idx["idx_close"] / idx["idx_close"].shift(w) - 1
    idx["idx_ema50"] = idx["idx_close"].ewm(span=50, adjust=False).mean()
    idx["market_up"] = idx["idx_close"] > idx["idx_ema50"]
    df = df.merge(idx[["date","ir21","ir63","ir126","ir252","market_up","idx_close","idx_ema50"]], on="date", how="left")
    df["market_up"] = df["market_up"].fillna(False).astype(bool)
    df["vol_filter"] = (df["atr_pct"] >= PARAMS["atr_min_pct"]) & (df["atr_pct"] <= PARAMS["atr_max_pct"])
    tick("Index merge done")

    df["above_ema20"] = (df["close"] > df["ema20"]).astype(float)
    mkt_b = (df.groupby("date")["above_ema20"].mean() * 100).rename("mkt_breadth")
    df = df.merge(mkt_b.reset_index(), on="date", how="left")
    df["breadth_ok"] = df["mkt_breadth"] >= PARAMS["mkt_breadth_min"]
    tick("Market breadth done")

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
    tick("Sector RS rank done")

    sec_b = (df.groupby(["date","sector"])["above_ema20"].mean() * 100).reset_index()
    sec_b.rename(columns={"above_ema20":"sector_breadth"}, inplace=True)
    df = df.merge(sec_b, on=["date","sector"], how="left")
    df["sector_breadth_ok"] = df["sector_breadth"] >= PARAMS["sector_breadth_min"]
    tick("Sector breadth done")

    df["rs_rank"] = df.groupby("date")["rs_rating"].rank(ascending=False, method="min")
    df["rs_rank_ok"] = df["rs_rank"] <= PARAMS["stock_rs_rank_max"]
    tick("Stock RS rank done")

    df["stock_sec_rank"] = df.groupby(["date","sector"])["rs_rating"].rank(ascending=False, method="min")
    df["stock_sec_rank_ok"] = df["stock_sec_rank"] <= PARAMS["stock_sector_rank_max"]
    tick("Stock sector rank done")

    df["signal_long"] = (
        df["stage2"]            &
        df["bo_long"]           &
        df["tight_base"]        &
        df["no_overhead"]       &
        df["vol_ok"]            &
        df["liquid"]            &
        df["market_up"]         &
        df["vol_filter"]        &
        df["breadth_ok"]        &
        df["sector_rs_ok"]      &
        df["sector_breadth_ok"] &
        df["rs_rank_ok"]        &
        df["stock_sec_rank_ok"] &
        (df["rs_rating"] >= PARAMS["rs_min_long"])
    )
    tick("Signal done")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SIMULATE — per stock, one position at a time
# ══════════════════════════════════════════════════════════════════════════════
def simulate_stock(rows):
    """rows: sorted DataFrame for one symbol."""
    rows = rows.reset_index(drop=True)
    n    = len(rows)
    trades = []
    in_trade = False

    i = 0
    while i < n:
        r = rows.iloc[i]

        if not in_trade:
            if r["signal_long"]:
                entry_price = r["close"]
                sl          = r["low"] * (1 - PARAMS["sl_below_low_pct"])
                entry_date  = r["date"]
                entry_idx   = i
                in_trade    = True
            i += 1
            continue

        if i == entry_idx:
            i += 1
            continue

        # Hard SL — intraday low breaches stop
        if r["low"] <= sl:
            trades.append(_rec(r["symbol"], r["sector"], entry_date, r["date"],
                               entry_price, sl, "Hard SL"))
            in_trade = False
            i += 1
            continue

        # Trailing SL — close below EMA20, exit next open
        if r["close"] < r["ema20"]:
            if i + 1 < n:
                nxt = rows.iloc[i + 1]
                # fall back to close if open is missing
                ep = nxt["open"] if pd.notna(nxt["open"]) else nxt["close"]
                ed = nxt["date"]
            else:
                ep, ed = r["close"], r["date"]
            trades.append(_rec(r["symbol"], r["sector"], entry_date, ed,
                               entry_price, ep, "Trail EMA20"))
            in_trade = False
            i += 2
            continue

        i += 1

    if in_trade:
        last = rows.iloc[-1]
        trades.append(_rec(last["symbol"], last["sector"], entry_date, last["date"],
                           entry_price, last["close"], "OPEN"))

    return trades


def _rec(symbol, sector, entry_date, exit_date, entry_price, exit_price, reason):
    pnl = (exit_price / entry_price - 1) * 100
    return dict(
        symbol      = symbol,
        sector      = sector,
        entry_date  = entry_date,
        exit_date   = exit_date,
        entry_price = round(float(entry_price), 2),
        exit_price  = round(float(exit_price), 2),
        pnl_pct     = round(float(pnl), 2),
        days_held   = (exit_date - entry_date).days,
        exit_reason = reason,
        outcome     = "Win" if pnl > 0 else ("Loss" if pnl < 0 else "BE"),
        year        = entry_date.year,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  STATS
# ══════════════════════════════════════════════════════════════════════════════
def stats_block(df, label="All trades"):
    closed = df[df["exit_reason"] != "OPEN"]
    if closed.empty:
        print(f"  {label}: no closed trades")
        return
    n  = len(closed)
    nw = (closed["outcome"]=="Win").sum()
    nl = (closed["outcome"]=="Loss").sum()
    wr = nw/n*100
    aw = closed[closed["outcome"]=="Win"]["pnl_pct"].mean()
    al = closed[closed["outcome"]=="Loss"]["pnl_pct"].mean()
    ev = closed["pnl_pct"].mean()
    mh = closed["days_held"].mean()
    print(f"  {label}")
    print(f"    Trades={n}  Wins={nw} ({wr:.1f}%)  Losses={nl} ({100-wr:.1f}%)")
    print(f"    Avg win={aw:+.2f}%  Avg loss={al:+.2f}%  Expectancy={ev:+.2f}%/trade")
    print(f"    Avg hold={mh:.1f}d  Max win={closed['pnl_pct'].max():.1f}%  Max loss={closed['pnl_pct'].min():.1f}%")


def print_summary(results):
    closed = results[results["exit_reason"] != "OPEN"]
    print(f"\n{'='*65}")
    print(f"  PSX FULL UNIVERSE — Minervini 14-Gate Backtest")
    print(f"{'='*65}")
    stats_block(results, "Overall (all signals)")

    print(f"\n  -- By exit reason --")
    for reason, grp in closed.groupby("exit_reason"):
        n  = len(grp)
        nw = (grp["outcome"]=="Win").sum()
        ev = grp["pnl_pct"].mean()
        print(f"    {reason:<14}  {n:>4} trades  Win={nw/n*100:.1f}%  Avg={ev:+.2f}%")

    print(f"\n  -- By year --")
    yr = (closed.groupby("year")["pnl_pct"]
               .agg(trades="count",
                    wins=lambda x: (x>0).sum(),
                    avg_pnl="mean",
                    total_pnl="sum")
               .reset_index())
    yr["win_pct"] = yr["wins"]/yr["trades"]*100
    for _, row in yr.iterrows():
        bar = "#" * int(max(0, row["win_pct"])//5)
        print(f"    {int(row['year'])}  {int(row['trades']):>4} trades  "
              f"Win={row['win_pct']:>5.1f}%  Avg={row['avg_pnl']:>+6.2f}%  [{bar}]")

    print(f"\n  -- Top 10 sectors by trade count --")
    sec = (closed.groupby("sector")["pnl_pct"]
                 .agg(trades="count",
                      wins=lambda x: (x>0).sum(),
                      avg_pnl="mean")
                 .reset_index()
                 .sort_values("trades", ascending=False)
                 .head(10))
    sec["win_pct"] = sec["wins"]/sec["trades"]*100
    for _, row in sec.iterrows():
        print(f"    {str(row['sector'])[:40]:<40}  {int(row['trades']):>4} trades  "
              f"Win={row['win_pct']:>5.1f}%  Avg={row['avg_pnl']:>+6.2f}%")

    print(f"\n  -- Top 15 stocks by trade count --")
    stk = (closed.groupby("symbol")["pnl_pct"]
                 .agg(trades="count",
                      wins=lambda x: (x>0).sum(),
                      avg_pnl="mean")
                 .reset_index()
                 .sort_values("trades", ascending=False)
                 .head(15))
    stk["win_pct"] = stk["wins"]/stk["trades"]*100
    for _, row in stk.iterrows():
        print(f"    {row['symbol']:<10}  {int(row['trades']):>3} trades  "
              f"Win={row['win_pct']:>5.1f}%  Avg={row['avg_pnl']:>+6.2f}%")

    print(f"\n  -- Gate relaxation comparison --")
    print(f"  (What if we drop the two gates OGDC failed on Dec 2016?)")

    # Full 14 gates = already in results
    # 13 gates: drop RS Rank <=50
    # 13 gates: drop Sector RS Top-6
    # 12 gates: drop both
    # We stored signal per trade from signal_long — need to recompute on df
    # We'll just report the current 14-gate result here; relaxation needs df


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 65)
    print("  PSX Full Universe Minervini Backtest")
    print("=" * 65)

    print("\n[1] Loading data ...")
    stocks, index = load_all()
    print(f"    {len(stocks):,} rows | {stocks['symbol'].nunique()} symbols | "
          f"{stocks['date'].min().date()} -> {stocks['date'].max().date()}")

    print("\n[2] Building features ...")
    df = build_features(stocks, index)

    n_signals = df["signal_long"].sum()
    print(f"\n    Total signal days (14-gate): {n_signals}")
    print(f"    Unique stocks with signals : {df[df['signal_long']]['symbol'].nunique()}")

    print("\n[3] Simulating trades ...")
    all_trades = []
    syms = df["symbol"].unique()
    for i, sym in enumerate(syms):
        sub = df[df["symbol"]==sym]
        if sub["signal_long"].any():
            all_trades.extend(simulate_stock(sub))
        if (i+1) % 200 == 0:
            print(f"    {i+1}/{len(syms)} stocks processed ...")

    results = pd.DataFrame(all_trades)
    print(f"    Total trades generated: {len(results)}")

    print_summary(results)

    # ── Gate relaxation analysis ───────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  GATE RELAXATION — drop RS Rank and/or Sector RS gates")
    print(f"{'='*65}")

    signal_cols_base = [
        "stage2","bo_long","tight_base","no_overhead","vol_ok","liquid",
        "market_up","vol_filter","breadth_ok","sector_breadth_ok","stock_sec_rank_ok",
    ]
    rs_rating_gate = df["rs_rating"] >= PARAMS["rs_min_long"]

    configs = {
        "14-gate (full)":            df["signal_long"],
        "13-gate (drop RS Rank<=50)":
            df[signal_cols_base].all(axis=1) & df["sector_rs_ok"] & df["stock_sec_rank_ok"] & rs_rating_gate,
        "13-gate (drop Sector RS)":
            df[signal_cols_base].all(axis=1) & df["rs_rank_ok"] & df["stock_sec_rank_ok"] & rs_rating_gate,
        "12-gate (drop both)":
            df[signal_cols_base].all(axis=1) & df["stock_sec_rank_ok"] & rs_rating_gate,
    }

    for label, sig_col in configs.items():
        df2 = df.copy()
        df2["signal_long"] = sig_col
        trades2 = []
        for sym in df2["symbol"].unique():
            sub = df2[df2["symbol"]==sym]
            if sub["signal_long"].any():
                trades2.extend(simulate_stock(sub))
        r2 = pd.DataFrame(trades2)
        if r2.empty:
            print(f"\n  {label}: no trades")
            continue
        closed2 = r2[r2["exit_reason"]!="OPEN"]
        if closed2.empty:
            continue
        n2  = len(closed2)
        nw2 = (closed2["outcome"]=="Win").sum()
        ev2 = closed2["pnl_pct"].mean()
        aw2 = closed2[closed2["outcome"]=="Win"]["pnl_pct"].mean() if nw2 else 0
        al2 = closed2[closed2["outcome"]=="Loss"]["pnl_pct"].mean() if (n2-nw2) else 0
        print(f"\n  {label}")
        print(f"    Signals={int(sig_col.sum()):,}  Trades={n2}  "
              f"Win={nw2/n2*100:.1f}%  Avg win={aw2:+.2f}%  Avg loss={al2:+.2f}%  EV={ev2:+.2f}%")

    # Save
    out = OUT_DIR / "full_universe_backtest.csv"
    if not results.empty:
        results.to_csv(out, index=False)
        print(f"\n  Results saved -> {out}")
