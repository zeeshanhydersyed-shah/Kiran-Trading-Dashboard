"""
Minervini-Style Breakout Backtest — PSX Version
================================================
Fully vectorized, no forward-look leakage.

Usage:
    python minervini_backtest.py
    python minervini_backtest.py --rs_min 80 --tp 0.10 --sl 0.05 --hold 15
"""

import argparse
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
STOCK_CSV = BASE / "merged_psx_data.csv"
INDEX_CSV  = BASE / "merged_index_data.csv"
OUTPUT_DIR = BASE / "backtest_results"
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── Default Parameters ───────────────────────────────────────────────────────
DEFAULTS = dict(
    tp=0.08,          # take-profit %
    sl=0.04,          # stop-loss %
    hold=10,          # max holding days
    rs_min=80,        # minimum RS Rating (0–100)
    sma_trend=50,     # trend SMA period
    sma_regime=50,    # regime SMA period (KSE-100)
    rs_window=63,     # RS score window (days)
    resist_window=60, # overhead resistance lookback
    pp_vol_window=10, # pocket pivot volume window
)


# ══════════════════════════════════════════════════════════════════════════════
#  1. LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════

def load_data():
    print("Loading data …")
    stocks = pd.read_csv(STOCK_CSV, parse_dates=["date"])
    stocks = stocks.sort_values(["symbol", "date"]).reset_index(drop=True)

    index = pd.read_csv(INDEX_CSV, parse_dates=["date"])
    index = index[index["symbol"] == "KSE-100"][["date", "close"]].copy()
    index = index.sort_values("date").reset_index(drop=True)
    index.rename(columns={"close": "idx_close"}, inplace=True)

    print(f"  Stocks: {stocks['symbol'].nunique()} symbols, "
          f"{stocks['date'].min().date()} → {stocks['date'].max().date()}")
    print(f"  Index:  {len(index)} days")
    return stocks, index


# ══════════════════════════════════════════════════════════════════════════════
#  2. FEATURE ENGINEERING (fully vectorized, per-symbol groupby)
# ══════════════════════════════════════════════════════════════════════════════

def add_stock_features(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Add all per-symbol technical features. df is sorted by symbol,date."""

    g = df.groupby("symbol", sort=False)["close"]

    # ── Trend ─────────────────────────────────────────────────────────────────
    df["sma50"]     = g.transform(lambda s: s.rolling(p["sma_trend"], min_periods=p["sma_trend"]).mean())
    df["trend_up"]  = df["close"] > df["sma50"]

    # ── RS Rating components ──────────────────────────────────────────────────
    for w, col in [(21, "ret_21"), (63, "ret_63"), (126, "ret_126"), (252, "ret_252")]:
        df[col] = g.transform(lambda s, w=w: s / s.shift(w) - 1)

    df["rs_raw"] = (
        0.40 * df["ret_252"] +
        0.30 * df["ret_126"] +
        0.20 * df["ret_63"]  +
        0.10 * df["ret_21"]
    )

    # ── Pocket Pivot building blocks ──────────────────────────────────────────
    df["prev_close"]  = g.transform(lambda s: s.shift(1))
    df["down_day"]    = df["close"] < df["prev_close"]

    vol_g = df.groupby("symbol", sort=False)["volume"]

    # max volume of down-days over last N sessions — vectorized
    # Mask volume to 0 on up-days, then rolling max
    w = p["pp_vol_window"]
    down_vol = df["volume"].where(df["down_day"], 0)
    df["max_down_vol"] = (
        df.groupby("symbol", sort=False)
          .apply(lambda g: down_vol.loc[g.index].rolling(w, min_periods=1).max())
          .reset_index(level=0, drop=True)
    )

    df["close_pos"]      = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-9)
    df["strong_close"]   = df["close_pos"] > 0.70
    df["vol_expansion"]  = df["volume"] > df["max_down_vol"]
    df["pocket_pivot"]   = df["trend_up"] & df["strong_close"] & df["vol_expansion"]

    # ── Overhead resistance ───────────────────────────────────────────────────
    rw = p["resist_window"]
    df["resist_60"] = g.transform(
        lambda s: s.rolling(rw, min_periods=rw).max().shift(1)   # shift to avoid fwd leakage
    )
    df["no_overhead"] = df["close"] >= 0.95 * df["resist_60"]

    return df


def add_regime(df: pd.DataFrame, index: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Merge KSE-100 regime flag onto stock dataframe."""
    idx = index.copy()
    idx["idx_sma50"]   = idx["idx_close"].rolling(p["sma_regime"], min_periods=p["sma_regime"]).mean()
    idx["market_up"]   = idx["idx_close"] > idx["idx_sma50"]

    # RS score vs index (63-day)
    idx["idx_ret_63"]  = idx["idx_close"] / idx["idx_close"].shift(p["rs_window"]) - 1
    idx["idx_ret_21"]  = idx["idx_close"] / idx["idx_close"].shift(21) - 1
    idx["idx_ret_126"] = idx["idx_close"] / idx["idx_close"].shift(126) - 1
    idx["idx_ret_252"] = idx["idx_close"] / idx["idx_close"].shift(252) - 1

    df = df.merge(
        idx[["date","market_up","idx_ret_63","idx_ret_21","idx_ret_126","idx_ret_252"]],
        on="date", how="left"
    )
    return df


def add_rs_score_and_rating(df: pd.DataFrame) -> pd.DataFrame:
    """RS score vs index + cross-sectional RS Rating (percentile rank per day)."""
    df["rs_score"] = df["rs_raw"] - (
        0.40 * df["idx_ret_252"] +
        0.30 * df["idx_ret_126"] +
        0.20 * df["idx_ret_63"]  +
        0.10 * df["idx_ret_21"]
    )

    # Percentile rank across all stocks each day
    df["rs_rating"] = (
        df.groupby("date")["rs_raw"]
          .rank(pct=True, method="average") * 100
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  3. SIGNAL GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_signals(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Mark entry signal rows. Entry is at NEXT day open."""
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
#  4. BACKTEST ENGINE (vectorized trade simulation)
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """
    For each signal row, look ahead p['hold'] days and simulate the trade.
    Entry  = next-day open  (shift -1)
    TP     = entry * (1 + tp)
    SL     = entry * (1 - sl)
    TimeEX = close at day hold if neither hit
    """
    tp, sl, hold = p["tp"], p["sl"], p["hold"]

    signals = df[df["signal"]].copy()
    if signals.empty:
        print("No signals generated.")
        return pd.DataFrame()

    # Build a date→row index for fast look-ahead
    df2 = df.set_index(["symbol", "date"])

    trades = []

    # Iterate per symbol — pre-index arrays for speed
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        dates   = grp["date"].values
        opens   = grp["open"].values
        highs   = grp["high"].values
        lows    = grp["low"].values
        closes  = grp["close"].values
        volumes = grp["volume"].values
        signals_arr = grp["signal"].values
        rs_ratings  = grp["rs_rating"].values
        rs_scores   = grp["rs_score"].values
        n = len(grp)

        in_trade_until_idx = -1   # index of exit day

        for i in range(n):
            if not signals_arr[i]:
                continue
            if i <= in_trade_until_idx:
                continue

            # Entry: next day open
            ei = i + 1
            if ei >= n:
                continue

            ep = opens[ei] if not np.isnan(opens[ei]) and opens[ei] > 0 else closes[ei]
            if ep <= 0:
                continue

            tp_p = ep * (1 + tp)
            sl_p = ep * (1 - sl)
            entry_date = pd.Timestamp(dates[ei])

            outcome    = "time"
            exit_price = closes[min(ei + hold - 1, n - 1)]
            exit_idx   = min(ei + hold - 1, n - 1)

            for j in range(ei + 1, min(ei + hold + 1, n)):
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

            in_trade_until_idx = exit_idx
            exit_date = pd.Timestamp(dates[exit_idx])
            ret = exit_price / ep - 1

            trades.append({
                "symbol":       sym,
                "signal_date":  pd.Timestamp(dates[i]),
                "entry_date":   entry_date,
                "entry_price":  round(float(ep), 4),
                "exit_date":    exit_date,
                "exit_price":   round(float(exit_price), 4),
                "outcome":      outcome,
                "return_pct":   round(ret * 100, 4),
                "rs_rating":    round(float(rs_ratings[i]), 1),
                "rs_score":     round(float(rs_scores[i]) * 100, 2),
                "holding_days": (exit_date - entry_date).days,
            })

    return pd.DataFrame(trades)


# ══════════════════════════════════════════════════════════════════════════════
#  5. METRICS & REPORTING
# ══════════════════════════════════════════════════════════════════════════════

def compute_metrics(trades: pd.DataFrame, p: dict) -> dict:
    if trades.empty:
        return {}

    wins   = trades[trades["return_pct"] > 0]
    losses = trades[trades["return_pct"] <= 0]
    n      = len(trades)

    gross_profit = wins["return_pct"].sum()
    gross_loss   = abs(losses["return_pct"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

    tp_count   = (trades["outcome"] == "tp").sum()
    sl_count   = (trades["outcome"] == "sl").sum()
    time_count = (trades["outcome"] == "time").sum()

    # Equity curve (equal capital, 100 start)
    eq = 100.0
    equity_curve = [eq]
    for r in trades.sort_values("entry_date")["return_pct"]:
        eq *= (1 + r / 100)
        equity_curve.append(eq)

    peak = np.maximum.accumulate(equity_curve)
    dd   = (np.array(equity_curve) - peak) / peak * 100
    max_dd = dd.min()

    return {
        "total_trades":    n,
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate_pct":    round(len(wins) / n * 100, 1),
        "avg_return_pct":  round(trades["return_pct"].mean(), 2),
        "avg_win_pct":     round(wins["return_pct"].mean(), 2) if not wins.empty else 0,
        "avg_loss_pct":    round(losses["return_pct"].mean(), 2) if not losses.empty else 0,
        "profit_factor":   round(profit_factor, 2),
        "tp_exits":        int(tp_count),
        "sl_exits":        int(sl_count),
        "time_exits":      int(time_count),
        "max_drawdown_pct":round(max_dd, 2),
        "final_equity":    round(equity_curve[-1], 2),
        "equity_curve":    equity_curve,
        "params":          p,
    }


def print_report(m: dict, trades: pd.DataFrame):
    print("\n" + "═" * 55)
    print("  MINERVINI-STYLE BACKTEST — PSX  |  RESULTS")
    print("═" * 55)
    p = m["params"]
    print(f"  TP={p['tp']*100:.0f}%  SL={p['sl']*100:.0f}%  Hold={p['hold']}d  "
          f"RS≥{p['rs_min']}  Trend SMA={p['sma_trend']}")
    print("─" * 55)
    print(f"  Total trades       : {m['total_trades']}")
    print(f"  Wins / Losses      : {m['wins']} / {m['losses']}")
    print(f"  Win rate           : {m['win_rate_pct']}%")
    print(f"  Avg return/trade   : {m['avg_return_pct']}%")
    print(f"  Avg win            : {m['avg_win_pct']}%")
    print(f"  Avg loss           : {m['avg_loss_pct']}%")
    print(f"  Profit factor      : {m['profit_factor']}")
    print(f"  TP / SL / Time     : {m['tp_exits']} / {m['sl_exits']} / {m['time_exits']}")
    print(f"  Max drawdown       : {m['max_drawdown_pct']}%")
    print(f"  Final equity (100) : {m['final_equity']}")
    print("═" * 55)

    if not trades.empty:
        print("\nTop 10 trades by return:")
        top = trades.nlargest(10, "return_pct")[
            ["symbol","entry_date","exit_date","entry_price","exit_price","return_pct","outcome","rs_rating"]
        ]
        print(top.to_string(index=False))

        print("\nWorst 10 trades by return:")
        bot = trades.nsmallest(10, "return_pct")[
            ["symbol","entry_date","exit_date","entry_price","exit_price","return_pct","outcome","rs_rating"]
        ]
        print(bot.to_string(index=False))

        print("\nOutcome breakdown by year:")
        trades["year"] = trades["entry_date"].dt.year
        ybr = trades.groupby(["year","outcome"]).size().unstack(fill_value=0)
        print(ybr.to_string())

        print("\nRS Rating distribution of signals:")
        bins = [0,70,80,90,95,100]
        labels = ["<70","70-80","80-90","90-95","95-100"]
        trades["rs_bucket"] = pd.cut(trades["rs_rating"], bins=bins, labels=labels, right=True)
        rb = trades.groupby("rs_bucket", observed=True).agg(
            count=("return_pct","count"),
            win_rate=("return_pct", lambda x: (x>0).mean()*100),
            avg_ret=("return_pct","mean")
        ).round(2)
        print(rb.to_string())


def save_outputs(trades: pd.DataFrame, m: dict):
    # Trades CSV
    trades_path = OUTPUT_DIR / "minervini_trades.csv"
    trades.to_csv(trades_path, index=False)
    print(f"\nTrades saved → {trades_path}")

    # Equity curve CSV
    eq_df = pd.DataFrame({"equity": m["equity_curve"]})
    eq_path = OUTPUT_DIR / "minervini_equity.csv"
    eq_df.to_csv(eq_path, index=False)
    print(f"Equity curve → {eq_path}")

    # Summary JSON
    import json
    summary = {k: v for k, v in m.items() if k != "equity_curve"}
    summary_path = OUTPUT_DIR / "minervini_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Summary      → {summary_path}")


# ══════════════════════════════════════════════════════════════════════════════
#  6. MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description="Minervini backtest — PSX")
    parser.add_argument("--tp",        type=float, default=DEFAULTS["tp"])
    parser.add_argument("--sl",        type=float, default=DEFAULTS["sl"])
    parser.add_argument("--hold",      type=int,   default=DEFAULTS["hold"])
    parser.add_argument("--rs_min",    type=float, default=DEFAULTS["rs_min"])
    parser.add_argument("--sma_trend", type=int,   default=DEFAULTS["sma_trend"])
    parser.add_argument("--sma_regime",type=int,   default=DEFAULTS["sma_regime"])
    parser.add_argument("--rs_window", type=int,   default=DEFAULTS["rs_window"])
    parser.add_argument("--no_save",   action="store_true")
    return vars(parser.parse_args())


def main():
    p = {**DEFAULTS, **parse_args()}

    stocks, index = load_data()

    print("Computing features …")
    stocks = add_stock_features(stocks, p)
    stocks = add_regime(stocks, index, p)
    stocks = add_rs_score_and_rating(stocks)
    stocks = generate_signals(stocks, p)

    sig_count = stocks["signal"].sum()
    print(f"  Signals generated: {sig_count:,}")

    print("Running backtest …")
    trades = run_backtest(stocks, p)

    if trades.empty:
        print("No trades executed.")
        return

    m = compute_metrics(trades, p)
    print_report(m, trades)

    if not p.get("no_save"):
        save_outputs(trades, m)


if __name__ == "__main__":
    main()
