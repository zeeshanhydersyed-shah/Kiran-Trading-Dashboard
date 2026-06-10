"""
breakout_signal.py  —  Zeeshan Breakout Signal Engine
======================================================
Entry rules (confirmed from 8 real trades — DGKC, FFC, UBL, TPLP):

  LONG signal (all liquid stocks):
    1. Stage 2  : close > SMA20 > SMA50 > SMA200
    2. Pivot BO : close > 60-day highest close (prior day)
    3. Volume   : today's volume >= 2x 20-day avg volume
    4. Market   : KSE-100 close > SMA50
    5. RS Rating: percentile rank >= 60  (stock outperforming at least 60% of market)
    6. Liquidity: 20-day avg volume >= 100,000 shares
    7. Volatility: ATR14 as % of close between 1.0% and 6.0%

  SHORT signal (DFC counters only — inverse rules):
    1. Stage 4  : close < SMA20 < SMA50 < SMA200
    2. Pivot BD : close < 60-day lowest close (prior day)
    3. Volume   : today's volume >= 2x 20-day avg volume
    4. Market   : KSE-100 close < SMA50  (bear regime)
    5. RS Rating: percentile rank <= 40  (stock underperforming 60%+ of market)
    6. Liquidity: 20-day avg volume >= 100,000 shares

Usage:
    python breakout_signal.py                     # today's signals
    python breakout_signal.py --date 2024-09-19   # signals on a specific date
    python breakout_signal.py --all_dates          # scan full history
"""

import argparse, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE      = Path(__file__).parent
STOCK_CSV = BASE / "merged_psx_data.csv"
INDEX_CSV = BASE / "merged_index_data.csv"
OUT_DIR   = BASE / "backtest_results"
OUT_DIR.mkdir(exist_ok=True)

# ── Parameters ────────────────────────────────────────────────────────────────
PARAMS = dict(
    min_avg_vol  = 100_000,   # 20-day avg vol floor
    vol_mult     = 2.0,       # volume must be >= N x 20-day avg
    rs_min_long  = 60,        # RS percentile floor for longs
    rs_max_short = 40,        # RS percentile ceiling for shorts
    atr_min_pct  = 1.0,       # min ATR% (filter ultra-flat stocks)
    atr_max_pct  = 6.0,       # max ATR% (filter too volatile)
    resist_win   = 60,        # lookback for pivot high/low
    sma_trend    = 50,        # regime SMA for index
)

# DFC counters — only these can be shorted on PSX
from config import DFC_SYMBOLS


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD
# ══════════════════════════════════════════════════════════════════════════════

def load_data():
    stocks = pd.read_csv(STOCK_CSV, parse_dates=["date"])
    stocks = stocks.sort_values(["symbol", "date"]).reset_index(drop=True)

    index = pd.read_csv(INDEX_CSV, parse_dates=["date"])
    index = (index[index["symbol"] == "KSE-100"][["date", "close"]]
             .rename(columns={"close": "idx_close"})
             .sort_values("date")
             .reset_index(drop=True))
    return stocks, index


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURES
# ══════════════════════════════════════════════════════════════════════════════

def build_features(stocks: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    df = stocks.copy()
    g  = df.groupby("symbol", sort=False)

    # ── Moving averages ───────────────────────────────────────────────────────
    for n in [20, 50, 200]:
        df[f"sma{n}"] = g["close"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean()
        )

    # Stage 2: close > SMA20 > SMA50 > SMA200
    df["stage2"] = (
        (df["close"] > df["sma20"]) &
        (df["sma20"] > df["sma50"]) &
        (df["sma50"] > df["sma200"])
    )

    # Stage 4: close < SMA20 < SMA50 < SMA200  (for DFC shorts)
    df["stage4"] = (
        (df["close"] < df["sma20"]) &
        (df["sma20"] < df["sma50"]) &
        (df["sma50"] < df["sma200"])
    )

    # ── ATR14 ─────────────────────────────────────────────────────────────────
    pc = g["close"].transform(lambda s: s.shift(1))
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    df["atr14"]   = g["close"].transform(
        lambda s: tr.loc[s.index].rolling(14, min_periods=14).mean()
    )
    df["atr_pct"] = df["atr14"] / df["close"] * 100

    # ── Pivot high / low (60-day, shift 1 to avoid fwd leakage) ──────────────
    rw = PARAMS["resist_win"]
    df["pivot_high"] = g["close"].transform(
        lambda s: s.rolling(rw, min_periods=rw).max().shift(1)
    )
    df["pivot_low"]  = g["close"].transform(
        lambda s: s.rolling(rw, min_periods=rw).min().shift(1)
    )

    # Breakout / breakdown
    df["bo_long"]  = df["close"] > df["pivot_high"]   # close above 60-day high
    df["bo_short"] = df["close"] < df["pivot_low"]    # close below 60-day low

    # ── Volume ────────────────────────────────────────────────────────────────
    df["vol_avg20"] = g["volume"].transform(
        lambda s: s.rolling(20, min_periods=20).mean().shift(1)
    )
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]
    df["liquid"]    = df["vol_avg20"] >= PARAMS["min_avg_vol"]
    df["vol_ok"]    = df["vol_ratio"] >= PARAMS["vol_mult"]

    # ── RS Rating (cross-sectional percentile per date) ───────────────────────
    for w, c in [(21,"r21"),(63,"r63"),(126,"r126"),(252,"r252")]:
        df[c] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["rs_raw"] = (
        0.40 * df["r252"] + 0.30 * df["r126"] +
        0.20 * df["r63"]  + 0.10 * df["r21"]
    )
    df["rs_rating"] = (
        df.groupby("date")["rs_raw"]
          .rank(pct=True, method="average") * 100
    )

    # ── RS score vs KSE-100 ───────────────────────────────────────────────────
    idx = index.copy()
    for w, c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
        idx[c] = idx["idx_close"] / idx["idx_close"].shift(w) - 1
    idx["idx_sma50"] = idx["idx_close"].rolling(PARAMS["sma_trend"], min_periods=PARAMS["sma_trend"]).mean()
    idx["market_up"] = idx["idx_close"] > idx["idx_sma50"]

    df = df.merge(
        idx[["date","ir21","ir63","ir126","ir252","market_up","idx_close","idx_sma50"]],
        on="date", how="left"
    )
    df["market_up"] = df["market_up"].fillna(False).astype(bool)
    df["rs_score"] = df["rs_raw"] - (
        0.40*df["ir252"] + 0.30*df["ir126"] +
        0.20*df["ir63"]  + 0.10*df["ir21"]
    )

    # ── Volatility filter ─────────────────────────────────────────────────────
    df["vol_filter"] = (
        (df["atr_pct"] >= PARAMS["atr_min_pct"]) &
        (df["atr_pct"] <= PARAMS["atr_max_pct"])
    )

    # ── DFC flag ──────────────────────────────────────────────────────────────
    df["is_dfc"] = df["symbol"].isin(DFC_SYMBOLS)

    # ══ LONG SIGNAL ══════════════════════════════════════════════════════════
    df["signal_long"] = (
        df["stage2"]      &
        df["bo_long"]     &
        df["vol_ok"]      &
        df["liquid"]      &
        df["market_up"]   &
        df["vol_filter"]  &
        (df["rs_rating"] >= PARAMS["rs_min_long"])
    )

    # ══ SHORT SIGNAL (DFC only) ══════════════════════════════════════════════
    df["signal_short"] = (
        df["is_dfc"]      &
        df["stage4"]      &
        df["bo_short"]    &
        df["vol_ok"]      &
        df["liquid"]      &
        (~df["market_up"])&          # bear market regime for shorts
        df["vol_filter"]  &
        (df["rs_rating"] <= PARAMS["rs_max_short"])
    )

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

OUTPUT_COLS_LONG = [
    "symbol", "date", "close", "sma20", "sma50", "sma200",
    "pivot_high", "atr_pct", "vol_ratio", "rs_rating", "rs_score",
    "vol_avg20", "market_up", "is_dfc",
]
OUTPUT_COLS_SHORT = [
    "symbol", "date", "close", "sma20", "sma50", "sma200",
    "pivot_low", "atr_pct", "vol_ratio", "rs_rating", "rs_score",
    "vol_avg20", "market_up", "is_dfc",
]


def get_signals(df: pd.DataFrame, as_of_date=None):
    """
    Returns (watchlist_df, longs_df, shorts_df) for a given date.
    - watchlist: Stage 2 stocks within 3% of pivot high, not yet broken out
    - longs: stocks with signal_long == True
    - shorts: stocks with signal_short == True
    If as_of_date is None, uses the latest date in the data.
    """
    if as_of_date is None:
        as_of_date = df["date"].max()
    else:
        as_of_date = pd.Timestamp(as_of_date)

    day = df[df["date"] == as_of_date]

    longs  = day[day["signal_long"] == True][OUTPUT_COLS_LONG].copy()
    shorts = day[day["signal_short"] == True][OUTPUT_COLS_SHORT].copy()

    # Watchlist: Stage 2, not yet broken out, within 3% of pivot high, RS >= 50
    _wl_mask = (
        (day["stage2"] == True) &
        (day["signal_long"] != True) &
        (day["pivot_high"].notna()) &
        (day["close"] < day["pivot_high"]) &
        ((day["pivot_high"] - day["close"]) / day["pivot_high"] <= 0.03) &
        (day["rs_rating"] >= 50)
    )
    _wl_cols = ["symbol", "date", "close", "pivot_high", "atr_pct", "vol_ratio", "rs_rating", "rs_score"]
    watchlist = day[_wl_mask][[c for c in _wl_cols if c in day.columns]].copy()

    # Round for display
    for col in ["close","sma20","sma50","sma200","pivot_high","atr_pct","vol_ratio","rs_rating","rs_score"]:
        if col in longs.columns:
            longs[col] = longs[col].round(2)
    for col in ["close","sma20","sma50","sma200","pivot_low","atr_pct","vol_ratio","rs_rating","rs_score"]:
        if col in shorts.columns:
            shorts[col] = shorts[col].round(2)
    for col in ["close","pivot_high","atr_pct","vol_ratio","rs_rating","rs_score"]:
        if col in watchlist.columns:
            watchlist[col] = watchlist[col].round(2)

    longs     = longs.sort_values("rs_rating", ascending=False).reset_index(drop=True)
    shorts    = shorts.sort_values("rs_rating", ascending=True).reset_index(drop=True)
    watchlist = watchlist.sort_values("rs_rating", ascending=False).reset_index(drop=True)
    return watchlist, longs, shorts


def get_all_signals(df: pd.DataFrame):
    """Returns all historical long + short signals."""
    longs  = df[df["signal_long"]  == True][OUTPUT_COLS_LONG].copy()
    shorts = df[df["signal_short"] == True][OUTPUT_COLS_SHORT].copy()
    longs["direction"]  = "LONG"
    shorts["direction"] = "SHORT"
    longs  = longs.rename(columns={"pivot_high": "pivot_level"})
    shorts = shorts.rename(columns={"pivot_low":  "pivot_level"})
    all_sigs = pd.concat([longs, shorts]).sort_values(["date","symbol"]).reset_index(drop=True)
    return all_sigs


# ══════════════════════════════════════════════════════════════════════════════
#  VERIFICATION — replay known entries
# ══════════════════════════════════════════════════════════════════════════════

def verify_known_entries(df: pd.DataFrame):
    """Check that the engine fires on the 8 confirmed trades."""
    known = [
        ("TPLP", "2021-05-27"),
        ("DGKC", "2025-02-19"),
        ("DGKC", "2025-08-04"),
        ("FFC",  "2024-09-19"),
        ("FFC",  "2025-07-15"),
        ("FFC",  "2025-11-03"),
        ("UBL",  "2024-09-20"),
        ("UBL",  "2025-12-26"),
    ]
    print("\n=== VERIFICATION — known entries ===")
    print("%-6s  %-12s  %-5s  %-5s  %-8s  %-8s  %-6s  %-6s  %-8s" % (
        "Symbol","Date","Stage","BO","Vol_ok","Vol_flt","RS_rat","Market","Signal"))
    print("-" * 85)
    hits = 0
    for sym, date_str in known:
        date = pd.Timestamp(date_str)
        row  = df[(df["symbol"]==sym) & (df["date"]<=date)].tail(1)
        if row.empty:
            print(f"  {sym:<6} {date_str:<12} NO DATA")
            continue
        r = row.iloc[0]
        sig = r["signal_long"]
        if sig:
            hits += 1
        print("%-6s  %-12s  %-5s  %-5s  %-8s  %-8s  %5.1f%%  %-6s  %s" % (
            sym, date_str,
            "YES" if r["stage2"]    else "no",
            "YES" if r["bo_long"]   else "no",
            "YES" if r["vol_ok"]    else "no",
            "YES" if r["vol_filter"]else "no",
            r["rs_rating"],
            "UP"  if r["market_up"] else "DN",
            "FIRE" if sig else "miss",
        ))
    print(f"\n  Captured {hits}/{len(known)} known entries")
    return hits


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date",      type=str, default=None, help="Date YYYY-MM-DD")
    ap.add_argument("--all_dates", action="store_true",    help="Dump full history")
    ap.add_argument("--verify",    action="store_true",    help="Replay known entries")
    ap.add_argument("--no_save",   action="store_true")
    return ap.parse_args()


def main():
    args = parse_args()
    print("Loading data ...")
    stocks, index = load_data()
    print("Building features ...")
    df = build_features(stocks, index)

    if args.verify or (not args.all_dates and not args.date):
        verify_known_entries(df)

    if args.all_dates:
        all_sigs = get_all_signals(df)
        print(f"\nTotal signals: {len(all_sigs)}  ({(all_sigs.direction=='LONG').sum()} long, {(all_sigs.direction=='SHORT').sum()} short)")
        if not args.no_save:
            path = OUT_DIR / "breakout_signals_history.csv"
            all_sigs.to_csv(path, index=False)
            print(f"Saved -> {path}")
        return

    target_date = args.date if args.date else None
    watchlist, longs, shorts = get_signals(df, target_date)
    date_used = target_date or df["date"].max().strftime("%Y-%m-%d")

    print(f"\n=== LONG SIGNALS  [{date_used}]  ({len(longs)} setups) ===")
    if not longs.empty:
        print(longs[["symbol","close","sma20","sma50","sma200","pivot_high",
                      "atr_pct","vol_ratio","rs_rating","rs_score","is_dfc"]].to_string(index=False))

    print(f"\n=== SHORT SIGNALS [{date_used}]  ({len(shorts)} setups — DFC only) ===")
    if not shorts.empty:
        print(shorts[["symbol","close","sma20","sma50","sma200","pivot_low",
                       "atr_pct","vol_ratio","rs_rating","rs_score"]].to_string(index=False))
    elif not longs.empty:
        print("  None")

    print(f"\n=== WATCHLIST     [{date_used}]  ({len(watchlist)} candidates — within 3% of pivot) ===")
    if not watchlist.empty:
        print(watchlist[["symbol","close","pivot_high","atr_pct","vol_ratio","rs_rating"]].to_string(index=False))

    if not args.no_save:
        if not longs.empty:
            longs.to_csv(OUT_DIR / f"longs_{date_used}.csv", index=False)
        if not shorts.empty:
            shorts.to_csv(OUT_DIR / f"shorts_{date_used}.csv", index=False)

if __name__ == "__main__":
    main()
