"""
Minervini ATR Trailing Stop Backtest — PSX
==========================================
RS ≥ 95 filter.  Three exit variants compared side-by-side:
  A) Fixed  : TP=8%  SL=4%  Hold=10d  (baseline)
  B) ATR10  : Trailing stop = 10-SMA − ATR14×multiplier  (first exit)
  C) ATR20  : Trailing stop = 20-SMA − ATR14×multiplier  (first exit)

No TP ceiling on trailing variants — let winners run until stop is hit or
hold_max days elapsed.

Usage:
    python minervini_atr_backtest.py
    python minervini_atr_backtest.py --atr_mult 1.5 --hold_max 60 --rs_min 95
"""

import argparse
import json
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

BASE       = Path(__file__).parent
STOCK_CSV  = BASE / "merged_psx_data.csv"
INDEX_CSV  = BASE / "merged_index_data.csv"
OUTPUT_DIR = BASE / "backtest_results"
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULTS = dict(
    rs_min    = 95,
    atr_mult  = 1.0,    # stop = SMA(n) − atr_mult × ATR14
    atr_period= 14,
    hold_max  = 40,     # max bars for trailing stop variants
    sma_trend = 50,
    sma_regime= 50,
    rs_window = 63,
    resist_window = 60,
    pp_vol_window = 10,
    # baseline fixed params
    tp_fixed  = 0.08,
    sl_fixed  = 0.04,
    hold_fixed= 10,
)


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD
# ══════════════════════════════════════════════════════════════════════════════

def load_data():
    print("Loading data …")
    stocks = pd.read_csv(STOCK_CSV, parse_dates=["date"])
    stocks = stocks.sort_values(["symbol", "date"]).reset_index(drop=True)

    index = pd.read_csv(INDEX_CSV, parse_dates=["date"])
    index = index[index["symbol"] == "KSE-100"][["date", "close"]].copy()
    index = index.sort_values("date").reset_index(drop=True)
    index.rename(columns={"close": "idx_close"}, inplace=True)

    print(f"  Stocks : {stocks['symbol'].nunique()} symbols  "
          f"{stocks['date'].min().date()} → {stocks['date'].max().date()}")
    print(f"  Index  : {len(index)} days")
    return stocks, index


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def add_features(df: pd.DataFrame, index: pd.DataFrame, p: dict) -> pd.DataFrame:
    g = df.groupby("symbol", sort=False)

    # ── Trend / SMA ───────────────────────────────────────────────────────────
    df["sma50"] = g["close"].transform(
        lambda s: s.rolling(p["sma_trend"], min_periods=p["sma_trend"]).mean()
    )
    df["sma10"] = g["close"].transform(
        lambda s: s.rolling(10, min_periods=10).mean()
    )
    df["sma20"] = g["close"].transform(
        lambda s: s.rolling(20, min_periods=20).mean()
    )
    df["trend_up"] = df["close"] > df["sma50"]

    # ── ATR14 ─────────────────────────────────────────────────────────────────
    prev_close = g["close"].transform(lambda s: s.shift(1))
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = g["close"].transform(
        lambda s: tr.loc[s.index].rolling(p["atr_period"], min_periods=p["atr_period"]).mean()
    )

    # ── Trailing stop levels (computed per bar for use in simulation) ─────────
    df["trail_stop10"] = df["sma10"] - p["atr_mult"] * df["atr14"]
    df["trail_stop20"] = df["sma20"] - p["atr_mult"] * df["atr14"]

    # ── RS Rating ─────────────────────────────────────────────────────────────
    for w, col in [(21,"ret_21"),(63,"ret_63"),(126,"ret_126"),(252,"ret_252")]:
        df[col] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["rs_raw"] = (
        0.40*df["ret_252"] + 0.30*df["ret_126"] +
        0.20*df["ret_63"]  + 0.10*df["ret_21"]
    )
    df["rs_rating"] = (
        df.groupby("date")["rs_raw"]
          .rank(pct=True, method="average") * 100
    )

    # ── Index RS ──────────────────────────────────────────────────────────────
    idx = index.copy()
    idx["idx_sma50"]  = idx["idx_close"].rolling(p["sma_regime"], min_periods=p["sma_regime"]).mean()
    idx["market_up"]  = idx["idx_close"] > idx["idx_sma50"]
    for w,c in [(21,"ir21"),(63,"ir63"),(126,"ir126"),(252,"ir252")]:
        idx[c] = idx["idx_close"] / idx["idx_close"].shift(w) - 1
    df = df.merge(idx[["date","market_up","ir21","ir63","ir126","ir252"]], on="date", how="left")
    df["rs_score"] = df["rs_raw"] - (
        0.40*df["ir252"] + 0.30*df["ir126"] + 0.20*df["ir63"] + 0.10*df["ir21"]
    )

    # ── Pocket Pivot ─────────────────────────────────────────────────────────
    df["prev_close"] = g["close"].transform(lambda s: s.shift(1))
    df["down_day"]   = df["close"] < df["prev_close"]
    w = p["pp_vol_window"]
    down_vol = df["volume"].where(df["down_day"], 0)
    df["max_down_vol"] = (
        df.groupby("symbol", sort=False)
          .apply(lambda grp: down_vol.loc[grp.index].rolling(w, min_periods=1).max())
          .reset_index(level=0, drop=True)
    )
    df["close_pos"]    = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-9)
    df["strong_close"] = df["close_pos"] > 0.70
    df["vol_exp"]      = df["volume"] > df["max_down_vol"]
    df["pocket_pivot"] = df["trend_up"] & df["strong_close"] & df["vol_exp"]

    # ── Overhead resistance ───────────────────────────────────────────────────
    rw = p["resist_window"]
    df["resist_60"]   = g["close"].transform(
        lambda s: s.rolling(rw, min_periods=rw).max().shift(1)
    )
    df["no_overhead"] = df["close"] >= 0.95 * df["resist_60"]

    # ── Entry signal ──────────────────────────────────────────────────────────
    df["signal"] = (
        df["market_up"]     &
        df["trend_up"]      &
        df["pocket_pivot"]  &
        (df["rs_score"] > 0)&
        df["no_overhead"]   &
        (df["rs_rating"] >= p["rs_min"])
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST CORE
# ══════════════════════════════════════════════════════════════════════════════

def simulate_trades(df: pd.DataFrame, p: dict, exit_mode: str) -> pd.DataFrame:
    """
    exit_mode: 'fixed' | 'atr10' | 'atr20'

    fixed  → TP=tp_fixed, SL=sl_fixed, max hold_fixed bars
    atr10  → trailing stop = max(trail_stop10 each day), max hold_max bars
    atr20  → trailing stop = max(trail_stop20 each day), max hold_max bars
    """
    tp_f   = p["tp_fixed"]
    sl_f   = p["sl_fixed"]
    hf     = p["hold_fixed"]
    hmax   = p["hold_max"]

    trades = []

    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        n   = len(grp)

        dates     = grp["date"].values
        opens     = grp["open"].values
        highs     = grp["high"].values
        lows      = grp["low"].values
        closes    = grp["close"].values
        sigs      = grp["signal"].values
        rs_rat    = grp["rs_rating"].values
        rs_sc     = grp["rs_score"].values
        stop10    = grp["trail_stop10"].values
        stop20    = grp["trail_stop20"].values

        in_trade_until = -1

        for i in range(n):
            if not sigs[i]:
                continue
            if i <= in_trade_until:
                continue

            ei = i + 1
            if ei >= n:
                continue

            ep = float(opens[ei]) if not np.isnan(opens[ei]) and opens[ei] > 0 else float(closes[ei])
            if ep <= 0:
                continue

            entry_date = pd.Timestamp(dates[ei])
            outcome    = "time"
            exit_price = float(closes[min(ei + (hf if exit_mode=="fixed" else hmax) - 1, n-1)])
            exit_idx   = min(ei + (hf if exit_mode=="fixed" else hmax) - 1, n-1)

            if exit_mode == "fixed":
                tp_p = ep * (1 + tp_f)
                sl_p = ep * (1 - sl_f)
                for j in range(ei+1, min(ei+hf+1, n)):
                    if lows[j] <= sl_p:
                        outcome    = "sl"
                        exit_price = sl_p
                        exit_idx   = j
                        break
                    if highs[j] >= tp_p:
                        outcome    = "tp"
                        exit_price = tp_p
                        exit_idx   = j
                        break

            else:
                # Trailing ATR stop
                stop_arr = stop10 if exit_mode == "atr10" else stop20
                # Initial hard stop on entry day (use stop level or -8% hard floor)
                hard_floor = ep * 0.92
                trail = max(float(stop_arr[ei]) if not np.isnan(stop_arr[ei]) else hard_floor, hard_floor)

                for j in range(ei+1, min(ei+hmax+1, n)):
                    # Update trailing stop (only move up, never down)
                    s_now = float(stop_arr[j]) if not np.isnan(stop_arr[j]) else trail
                    trail = max(trail, s_now)

                    # Check if stop hit intra-day
                    if lows[j] <= trail:
                        outcome    = "sl"
                        exit_price = trail          # assume filled at stop level
                        exit_idx   = j
                        break

                if exit_price is None or (outcome == "time"):
                    exit_idx   = min(ei + hmax - 1, n-1)
                    exit_price = float(closes[exit_idx])

            in_trade_until = exit_idx
            exit_date = pd.Timestamp(dates[exit_idx])
            ret = exit_price / ep - 1

            trades.append({
                "symbol":       sym,
                "signal_date":  pd.Timestamp(dates[i]),
                "entry_date":   entry_date,
                "entry_price":  round(ep, 4),
                "exit_date":    exit_date,
                "exit_price":   round(exit_price, 4),
                "outcome":      outcome,
                "return_pct":   round(ret * 100, 4),
                "holding_days": (exit_date - entry_date).days,
                "rs_rating":    round(float(rs_rat[i]), 1),
                "rs_score":     round(float(rs_sc[i]) * 100, 2),
            })

    return pd.DataFrame(trades)


# ══════════════════════════════════════════════════════════════════════════════
#  METRICS
# ══════════════════════════════════════════════════════════════════════════════

def metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    wins   = trades[trades["return_pct"] > 0]
    losses = trades[trades["return_pct"] <= 0]
    n      = len(trades)
    gp     = wins["return_pct"].sum()
    gl     = abs(losses["return_pct"].sum())

    eq = 100.0
    curve = [eq]
    for r in trades.sort_values("entry_date")["return_pct"]:
        eq *= (1 + r/100)
        curve.append(eq)
    peak  = np.maximum.accumulate(curve)
    dd    = (np.array(curve) - peak) / peak * 100

    return dict(
        n           = n,
        wins        = len(wins),
        losses      = len(losses),
        win_rate    = round(len(wins)/n*100, 1),
        avg_ret     = round(trades["return_pct"].mean(), 2),
        avg_win     = round(wins["return_pct"].mean(), 2)   if not wins.empty   else 0,
        avg_loss    = round(losses["return_pct"].mean(), 2) if not losses.empty else 0,
        pf          = round(gp/gl, 2) if gl > 0 else float("inf"),
        tp_exits    = int((trades["outcome"]=="tp").sum()),
        sl_exits    = int((trades["outcome"]=="sl").sum()),
        time_exits  = int((trades["outcome"]=="time").sum()),
        max_dd      = round(dd.min(), 2),
        final_eq    = round(curve[-1], 2),
        med_hold    = round(trades["holding_days"].median(), 1),
        avg_hold    = round(trades["holding_days"].mean(), 1),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PRINT COMPARISON TABLE
# ══════════════════════════════════════════════════════════════════════════════

def print_comparison(results: dict):
    keys = [
        ("n",           "Total trades"),
        ("wins",        "Wins"),
        ("losses",      "Losses"),
        ("win_rate",    "Win rate %"),
        ("avg_ret",     "Avg return %"),
        ("avg_win",     "Avg win %"),
        ("avg_loss",    "Avg loss %"),
        ("pf",          "Profit factor"),
        ("tp_exits",    "TP exits"),
        ("sl_exits",    "SL exits"),
        ("time_exits",  "Time exits"),
        ("med_hold",    "Median hold (d)"),
        ("avg_hold",    "Avg hold (d)"),
        ("max_dd",      "Max drawdown %"),
        ("final_eq",    "Final equity (100)"),
    ]
    labels = list(results.keys())
    width  = 22

    print("\n" + "═"*74)
    print("  MINERVINI RS≥95  |  EXIT MODE COMPARISON")
    print("═"*74)
    header = f"  {'Metric':<{width}}" + "".join(f"{l:>16}" for l in labels)
    print(header)
    print("─"*74)
    for k, label in keys:
        row = f"  {label:<{width}}" + "".join(f"{results[l].get(k, '—'):>16}" for l in labels)
        print(row)
    print("═"*74)


def print_yearly(results: dict):
    print("\n── Win rate by year ─────────────────────────────────────────────────")
    for label, trades in results.items():
        if trades.empty:
            continue
        trades = trades.copy()
        trades["year"] = trades["entry_date"].dt.year
        yr = trades.groupby("year").apply(
            lambda g: pd.Series({
                "trades": len(g),
                "win%":   round((g["return_pct"]>0).mean()*100, 1),
                "avg%":   round(g["return_pct"].mean(), 2),
            })
        )
        print(f"\n  {label}")
        print(yr.to_string())


def print_rs_buckets(results: dict):
    print("\n── RS Rating buckets ────────────────────────────────────────────────")
    bins   = [94, 97, 100]
    labels = ["95-97", "97-100"]
    for label, trades in results.items():
        if trades.empty:
            continue
        trades = trades.copy()
        trades["rs_bucket"] = pd.cut(trades["rs_rating"], bins=bins, labels=labels, right=True)
        rb = trades.groupby("rs_bucket", observed=True).agg(
            count  = ("return_pct","count"),
            win_rt = ("return_pct", lambda x: round((x>0).mean()*100,1)),
            avg_r  = ("return_pct","mean"),
        ).round(2)
        print(f"\n  {label}")
        print(rb.to_string())


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rs_min",    type=float, default=DEFAULTS["rs_min"])
    ap.add_argument("--atr_mult",  type=float, default=DEFAULTS["atr_mult"])
    ap.add_argument("--atr_period",type=int,   default=DEFAULTS["atr_period"])
    ap.add_argument("--hold_max",  type=int,   default=DEFAULTS["hold_max"])
    ap.add_argument("--tp_fixed",  type=float, default=DEFAULTS["tp_fixed"])
    ap.add_argument("--sl_fixed",  type=float, default=DEFAULTS["sl_fixed"])
    ap.add_argument("--hold_fixed",type=int,   default=DEFAULTS["hold_fixed"])
    ap.add_argument("--no_save",   action="store_true")
    return vars(ap.parse_args())


def main():
    p = {**DEFAULTS, **parse_args()}
    print(f"\nParams: RS≥{p['rs_min']}  ATR{p['atr_period']}×{p['atr_mult']}  "
          f"HoldMax={p['hold_max']}d  Fixed(TP={p['tp_fixed']*100:.0f}%/SL={p['sl_fixed']*100:.0f}%/H={p['hold_fixed']}d)")

    stocks, index = load_data()

    print("Computing features …")
    stocks = add_features(stocks, index, p)
    sig_count = stocks["signal"].sum()
    print(f"  Signals: {sig_count:,}")

    modes = {
        f"Fixed (TP{p['tp_fixed']*100:.0f}%/SL{p['sl_fixed']*100:.0f}%/H{p['hold_fixed']}d)": "fixed",
        f"ATR{p['atr_period']} Trail (SMA10−{p['atr_mult']}×ATR)":                            "atr10",
        f"ATR{p['atr_period']} Trail (SMA20−{p['atr_mult']}×ATR)":                            "atr20",
    }

    all_trades = {}
    all_metrics = {}
    for label, mode in modes.items():
        print(f"Running: {label} …")
        t = simulate_trades(stocks, p, mode)
        all_trades[label]  = t
        all_metrics[label] = metrics(t)
        print(f"  → {len(t)} trades")

    print_comparison(all_metrics)
    print_yearly(all_trades)
    print_rs_buckets(all_trades)

    if not p.get("no_save"):
        for label, t in all_trades.items():
            safe = label.replace("/","_").replace(" ","_").replace("(","").replace(")","").replace("%","pct")
            path = OUTPUT_DIR / f"atr_trades_{safe}.csv"
            t.to_csv(path, index=False)
            print(f"  Saved: {path.name}")

        summary_path = OUTPUT_DIR / "atr_comparison_summary.json"
        with open(summary_path, "w") as f:
            json.dump(all_metrics, f, indent=2, default=str)
        print(f"  Saved: {summary_path.name}")


if __name__ == "__main__":
    main()
