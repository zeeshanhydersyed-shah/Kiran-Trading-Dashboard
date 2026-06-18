"""
breakout_signal.py  —  Zeeshan Breakout Signal Engine  v3
==========================================================
v3 (2026-06-18):  Tighter market gates | Sector & stock rank filters

  LONG signal (all liquid stocks):
    1.  Stage 2          : close > EMA20 > EMA50 > EMA200
    2.  Pivot BO         : close > 60-day highest close (first break — yesterday still below)
    3.  Tight Base       : Bollinger Band width (prior day) ≤ 12%
    4.  No Overhead      : 200-day high ≤ 60-day pivot × 1.05
    5.  Volume           : today's volume >= 2x 20-day avg volume
    6.  Market trend     : KSE-100 close > EMA50
    7.  Market breadth   : ≥ 60% of all PSX stocks above their 20-day EMA
    8.  RS Rating        : cross-sectional percentile >= 60
    9.  Stock RS Rank    : market-wide rank <= 50
    10. Liquidity        : 20-day avg volume >= 100,000 shares
    11. Volatility       : ATR14 between 1.0% and 6.0% of price
    12. Sector RS rank   : sector ranks in top 6 by RS-20
    13. Sector breadth   : >= 70% of stocks in that sector above their EMA-20
    14. Stock sector rank: stock ranks <= 5 within its sector

  SHORT signal (DFC counters only — inverse rules):
    1. Stage 4     : close < EMA20 < EMA50 < EMA200
    2. Pivot BD    : close < 60-day lowest close (first breakdown — yesterday still above)
    3. Tight Base  : Bollinger Band width (prior day) ≤ 12%
    4. Market      : KSE-100 close < EMA50  (bear regime)
    5. RS Rating   : cross-sectional percentile <= 40
    6. Liquidity   : 20-day avg volume >= 100,000 shares
    7. Volatility  : ATR14 between 1.0% and 6.0% of price
    NOTE: No volume spike, no breadth/sector/rank gates on shorts

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
    min_avg_vol            = 100_000,  # 20-day avg vol floor
    vol_mult               = 2.0,      # volume must be >= N x 20-day avg
    rs_min_long            = 60,       # RS percentile floor for longs
    rs_max_short           = 40,       # RS percentile ceiling for shorts
    atr_min_pct            = 1.0,      # min ATR% (filter ultra-flat stocks)
    atr_max_pct            = 6.0,      # max ATR% (filter too volatile)
    resist_win             = 60,       # lookback for pivot high/low (rolling max of close)
    bb_max_width           = 12.0,     # Bollinger Band width ≤ 12% (tight base gate)
    overhead_mult          = 1.05,     # 200d HIGH must be ≤ pivot × 1.05 (5% max overhead)
    ema_trend              = 50,       # regime EMA for index (v3: EMA not SMA)
    mkt_breadth_min        = 60.0,     # % of all PSX stocks above 20-EMA (market gate)
    sector_rs_rank_max     = 6,        # top N sectors by RS-20
    sector_breadth_min     = 70.0,     # % of sector stocks above EMA-20
    stock_rs_rank_max      = 50,       # market-wide stock rank ceiling
    stock_sector_rank_max  = 5,        # stock rank within its sector ceiling
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

    # ── EMA 20 / 50 / 200 (v2: replaces SMA) ────────────────────────────────
    for n in [20, 50, 200]:
        df[f"ema{n}"] = g["close"].transform(
            lambda s, n=n: s.ewm(span=n, adjust=False).mean()
        )

    # Stage 2: close > EMA20 > EMA50 > EMA200
    df["stage2"] = (
        (df["close"] > df["ema20"]) &
        (df["ema20"] > df["ema50"]) &
        (df["ema50"] > df["ema200"])
    )

    # Stage 4: close < EMA20 < EMA50 < EMA200  (for DFC shorts)
    df["stage4"] = (
        (df["close"] < df["ema20"]) &
        (df["ema20"] < df["ema50"]) &
        (df["ema50"] < df["ema200"])
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

    # ── Pivot high / low (60-day rolling max of close, shift 1) ───────────────
    rw = PARAMS["resist_win"]
    df["pivot_high"] = g["close"].transform(
        lambda s: s.rolling(rw, min_periods=rw).max().shift(1)
    )
    df["pivot_low"] = g["close"].transform(
        lambda s: s.rolling(rw, min_periods=rw).min().shift(1)
    )

    # Breakout / breakdown — FIRST break only (yesterday still on other side)
    _prev_close    = g["close"].transform(lambda s: s.shift(1))
    df["bo_long"]  = (df["close"] > df["pivot_high"]) & (_prev_close <= df["pivot_high"])
    df["bo_short"] = (df["close"] < df["pivot_low"])  & (_prev_close >= df["pivot_low"])

    # ── Tight Base — Bollinger Band width (prior day) ≤ 12% (v2 new gate) ────
    # BB width = (Upper − Lower) / Middle × 100 = 4 × StdDev20 / SMA20 × 100
    def _bb_width_shifted(s):
        sma = s.rolling(20, min_periods=20).mean()
        std = s.rolling(20, min_periods=20).std(ddof=1)
        width = (4.0 * std / sma * 100)
        return width.shift(1)   # prior day's width

    df["bb_width"]   = g["close"].transform(_bb_width_shifted)
    df["tight_base"] = df["bb_width"] <= PARAMS["bb_max_width"]

    # ── No Overhead Supply (v2 new gate — LONG only) ─────────────────────────
    # 200-day rolling max of HIGH (shifted 1) must be ≤ pivot × 1.05
    df["high_200d"]   = g["high"].transform(
        lambda s: s.rolling(200, min_periods=200).max().shift(1)
    )
    df["no_overhead"] = (
        df["high_200d"].notna() &
        df["pivot_high"].notna() &
        (df["high_200d"] <= df["pivot_high"] * PARAMS["overhead_mult"])
    )

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
    idx["idx_ema50"] = idx["idx_close"].ewm(
        span=PARAMS["ema_trend"], adjust=False
    ).mean()
    idx["market_up"] = idx["idx_close"] > idx["idx_ema50"]

    df = df.merge(
        idx[["date","ir21","ir63","ir126","ir252","market_up","idx_close","idx_ema50"]],
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
        df["tight_base"]  &   # v2: BB width ≤ 12%
        df["no_overhead"] &   # v2: 200d high ≤ pivot × 1.05
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
        df["tight_base"]  &
        df["liquid"]      &
        (~df["market_up"])&
        df["vol_filter"]  &
        (df["rs_rating"] <= PARAMS["rs_max_short"])
    )   # no vol_ok — spec: no volume requirement on shorts

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

OUTPUT_COLS_LONG = [
    "symbol", "sector", "date", "close", "ema20", "ema50", "ema200",
    "pivot_high", "bb_width", "high_200d",
    "atr_pct", "vol_ratio", "rs_rating", "rs_score",
    "vol_avg20", "rs_rank", "sector_rs_rank", "sector_breadth",
    "market_up", "is_dfc",
]
OUTPUT_COLS_SHORT = [
    "symbol", "sector", "date", "close", "ema20", "ema50", "ema200",
    "pivot_low", "bb_width",
    "atr_pct", "vol_ratio", "rs_rating", "rs_score",
    "vol_avg20", "market_up", "is_dfc",
]


def get_signals(df: pd.DataFrame, as_of_date=None,
                mkt_breadth=None, sector_df=None, stock_ranks_df=None):
    """
    Returns (watchlist_df, longs_df, shorts_df) for a given date.

    Optional v3 gate arguments (all default to None = gate skipped):
      mkt_breadth    : float — % of all PSX stocks above 20-EMA (gate ≥ 60)
      sector_df      : DataFrame[sector, rs_rank, breadth_score] from sector_signals
      stock_ranks_df : DataFrame[symbol, rs_rank, sector_rs_rank] from stock_signals
    """
    if as_of_date is None:
        as_of_date = df["date"].max()
    else:
        as_of_date = pd.Timestamp(as_of_date)

    day = df[df["date"] == as_of_date].copy()

    # ── Merge sector-level data ───────────────────────────────────────────────
    if sector_df is not None and not sector_df.empty:
        _sec = sector_df.rename(columns={
            "rs_rank":      "_sec_rs_rank",
            "breadth_score": "sector_breadth",
        })[["sector", "_sec_rs_rank", "sector_breadth"]]
        day = day.merge(_sec, on="sector", how="left")
    else:
        day["_sec_rs_rank"]  = np.nan
        day["sector_breadth"] = np.nan

    # ── Merge stock-level rank data ───────────────────────────────────────────
    if stock_ranks_df is not None and not stock_ranks_df.empty:
        day = day.merge(
            stock_ranks_df[["symbol", "rs_rank", "sector_rs_rank"]],
            on="symbol", how="left"
        )
    else:
        day["rs_rank"]        = np.nan
        day["sector_rs_rank"] = np.nan

    # ── Market breadth gate ───────────────────────────────────────────────────
    mkt_ok = (mkt_breadth is not None and mkt_breadth >= PARAMS["mkt_breadth_min"])

    # ── Sector gates (boolean Series) ────────────────────────────────────────
    if sector_df is not None and not sector_df.empty:
        _sec_rank_ok    = day["_sec_rs_rank"].notna()   & (day["_sec_rs_rank"]   <= PARAMS["sector_rs_rank_max"])
        _sec_breadth_ok = day["sector_breadth"].notna() & (day["sector_breadth"] >= PARAMS["sector_breadth_min"])
    else:
        _sec_rank_ok    = pd.Series(True, index=day.index)
        _sec_breadth_ok = pd.Series(True, index=day.index)

    # ── Stock rank gates (boolean Series) ────────────────────────────────────
    if stock_ranks_df is not None and not stock_ranks_df.empty:
        _stk_rank_ok     = day["rs_rank"].notna()        & (day["rs_rank"]        <= PARAMS["stock_rs_rank_max"])
        _stk_sec_rank_ok = day["sector_rs_rank"].notna() & (day["sector_rs_rank"] <= PARAMS["stock_sector_rank_max"])
    else:
        _stk_rank_ok     = pd.Series(True, index=day.index)
        _stk_sec_rank_ok = pd.Series(True, index=day.index)

    _new_gates = _sec_rank_ok & _sec_breadth_ok & _stk_rank_ok & _stk_sec_rank_ok

    # ── LONG signals ──────────────────────────────────────────────────────────
    if not mkt_ok:
        longs = pd.DataFrame()
    else:
        _long_mask = (day["signal_long"] == True) & _new_gates
        longs = day[_long_mask][[c for c in OUTPUT_COLS_LONG if c in day.columns]].copy()
        if not longs.empty and mkt_breadth is not None:
            longs["mkt_breadth"] = round(mkt_breadth, 1)

    # ── SHORT signals — no breadth/sector/rank gates ──────────────────────────
    shorts = day[day["signal_short"] == True][
        [c for c in OUTPUT_COLS_SHORT if c in day.columns]
    ].copy()

    # ── WATCHLIST — coiling under pivot, all gates including new ones ─────────
    _wl_mask = (
        (mkt_ok) &
        (day["stage2"]      == True) &
        (day["tight_base"]  == True) &
        (day["no_overhead"] == True) &
        (day["market_up"]   == True) &
        (day["liquid"]      == True) &
        (day["vol_filter"]  == True) &
        (day["signal_long"] != True) &
        (day["pivot_high"].notna()) &
        (day["close"] < day["pivot_high"]) &
        ((day["pivot_high"] - day["close"]) / day["pivot_high"] <= 0.03) &
        (day["rs_rating"] >= PARAMS["rs_min_long"]) &
        _new_gates
    )
    _wl_cols = [
        "symbol", "sector", "date", "close", "pivot_high",
        "bb_width", "atr_pct", "vol_ratio", "rs_rating", "rs_score",
        "vol_avg20", "rs_rank", "sector_rs_rank", "sector_breadth",
    ]
    watchlist = day[_wl_mask][[c for c in _wl_cols if c in day.columns]].copy()
    if not watchlist.empty and mkt_breadth is not None:
        watchlist["mkt_breadth"] = round(mkt_breadth, 1)

    # ── Round for display ─────────────────────────────────────────────────────
    _long_round = ["close","ema20","ema50","ema200","pivot_high","bb_width",
                   "high_200d","atr_pct","vol_ratio","rs_rating","rs_score",
                   "vol_avg20","sector_breadth","mkt_breadth"]
    _short_round = ["close","ema20","ema50","ema200","pivot_low","bb_width",
                    "atr_pct","vol_ratio","rs_rating","rs_score"]
    _wl_round   = ["close","pivot_high","bb_width","atr_pct","vol_ratio",
                   "rs_rating","rs_score","vol_avg20","sector_breadth","mkt_breadth"]

    for col in _long_round:
        if col in longs.columns:
            longs[col] = longs[col].round(2)
    for col in _short_round:
        if col in shorts.columns:
            shorts[col] = shorts[col].round(2)
    for col in _wl_round:
        if col in watchlist.columns:
            watchlist[col] = watchlist[col].round(2)

    if not longs.empty:
        longs = longs.sort_values("rs_rating", ascending=False).reset_index(drop=True)
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
    """Check that the engine fires on the confirmed trades."""
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
    print("%-6s  %-12s  %-5s  %-5s  %-7s  %-8s  %-8s  %-6s  %-6s  %-8s" % (
        "Symbol","Date","Stage","BO","TBase","NoOvhd","Vol_flt","RS_rat","Market","Signal"))
    print("-" * 95)
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
        print("%-6s  %-12s  %-5s  %-5s  %-7s  %-8s  %-8s  %5.1f%%  %-6s  %s" % (
            sym, date_str,
            "YES" if r["stage2"]      else "no",
            "YES" if r["bo_long"]     else "no",
            "YES" if r["tight_base"]  else "no",
            "YES" if r["no_overhead"] else "no",
            "YES" if r["vol_filter"]  else "no",
            r["rs_rating"],
            "UP"  if r["market_up"]   else "DN",
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
        print(f"\nTotal signals: {len(all_sigs)}  "
              f"({(all_sigs.direction=='LONG').sum()} long, "
              f"{(all_sigs.direction=='SHORT').sum()} short)")
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
        print(longs[["symbol","close","ema20","ema50","ema200","pivot_high",
                      "bb_width","atr_pct","vol_ratio","rs_rating","rs_score","is_dfc"]
                    ].to_string(index=False))

    print(f"\n=== SHORT SIGNALS [{date_used}]  ({len(shorts)} setups — DFC only) ===")
    if not shorts.empty:
        print(shorts[["symbol","close","ema20","ema50","ema200","pivot_low",
                       "bb_width","atr_pct","vol_ratio","rs_rating","rs_score"]
                     ].to_string(index=False))
    elif not longs.empty:
        print("  None")

    print(f"\n=== WATCHLIST     [{date_used}]  ({len(watchlist)} candidates — within 3% of pivot) ===")
    if not watchlist.empty:
        print(watchlist[["symbol","close","pivot_high","bb_width",
                          "atr_pct","vol_ratio","rs_rating"]].to_string(index=False))

    if not args.no_save:
        if not longs.empty:
            longs.to_csv(OUT_DIR / f"longs_{date_used}.csv", index=False)
        if not shorts.empty:
            shorts.to_csv(OUT_DIR / f"shorts_{date_used}.csv", index=False)


if __name__ == "__main__":
    main()
