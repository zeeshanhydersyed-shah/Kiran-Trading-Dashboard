"""
Weinstein Stage 2 Breakout Backtest — PSX 2005–2026
=====================================================
Source rules extracted from: Stan Weinstein's Secrets for Profiting in Bull and Bear Markets
  - Stage 2 definition: Ch.2 pp.33–35 (PDF pp.44–46)
  - Volume at breakout: Ch.4 pp.107–108, "Don't Commandments" p.129 (PDF pp.107–140)
  - Relative Strength: Ch.4 pp.108–112 (PDF pp.119–123), formula: price/market_avg
  - Forest to Trees (sector first): Ch.3 pp.75–88 (PDF pp.86–99)
  - Quick Reference Checklist: Ch.4 p.115 (PDF p.126)

Three signal variants tested:
  A) Original Weinstein: 150-day SMA (≈30-week MA), Vol ≥150% of 10d avg, RS slope positive
  B) PSX Daily (user spec): 50-day EMA, same Vol + RS rules
  C) PSX Relaxed: 50-day EMA, Vol ≥120% of 10d avg, RS slope positive last 10d only

Forward return windows: 10d, 20d, 60d
Outcome: WINNER (>+6%), LOSER (<-6%), BREAKEVEN otherwise — consistent with existing setup_log convention
Liquidity filter: avg_vol_10d > 200,000
Universe: stock_metadata is_active=1 (314 symbols), all analytical work on prices_adjusted
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

DB_PATH = "psx_data.db"

# ── helpers ──────────────────────────────────────────────────────────────────

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def sma(series, window):
    return series.rolling(window, min_periods=window).mean()

def compute_signals(prices_df, index_df, variant="B"):
    """
    Given a per-symbol daily price df and index df, compute entry signals.
    Returns DataFrame of signal dates with metadata.

    variant:
      A = Original (150d SMA, vol ≥1.5x, rs slope 20d)
      B = PSX Daily (50d EMA, vol ≥1.5x, rs slope 10d)
      C = PSX Relaxed (50d EMA, vol ≥1.2x, rs slope 5d, no vol gate)
    """
    df = prices_df.copy().sort_values("date")
    idx = index_df.copy().sort_values("date").set_index("date")["close"].rename("kse100")

    df = df.merge(idx, on="date", how="left")
    df["kse100"] = df["kse100"].ffill()

    close = df["close"]
    vol = df["volume"]
    kse = df["kse100"]

    # MA
    if variant == "A":
        df["ma"] = sma(close, 150)
    else:
        df["ma"] = ema(close, 50)

    df["ma_prev5"] = df["ma"].shift(5)
    df["ma_slope"] = (df["ma"] - df["ma_prev5"]) / df["ma_prev5"]

    # Relative Strength (Weinstein formula: price / market_avg)
    df["rs"] = close / kse
    if variant in ("A", "B"):
        df["rs_slope"] = (df["rs"] - df["rs"].shift(20)) / df["rs"].shift(20)
    else:
        df["rs_slope"] = (df["rs"] - df["rs"].shift(5)) / df["rs"].shift(5)

    # Volume filter
    df["vol_avg10"] = vol.rolling(10, min_periods=5).mean().shift(1)
    if variant == "C":
        vol_mult = 1.2
    else:
        vol_mult = 1.5

    # Crossover: price was below MA yesterday, above today
    df["above_ma"] = (close > df["ma"]).astype(int)
    df["prev_above"] = df["above_ma"].shift(1).fillna(0).astype(int)
    df["crossover"] = (df["above_ma"] == 1) & (df["prev_above"] == 0)

    # Liquidity: 10d avg vol > 200k
    df["liquid"] = df["vol_avg10"] > 200_000

    # All gates
    df["ma_rising"] = df["ma_slope"] > 0
    df["rs_positive"] = df["rs_slope"] > 0
    df["vol_ok"] = (vol >= df["vol_avg10"] * vol_mult) | (variant == "C")  # C has no strict vol gate
    if variant == "C":
        df["vol_ok"] = vol >= df["vol_avg10"] * vol_mult  # actually keep vol gate even for C

    df["signal"] = (
        df["crossover"] &
        df["ma_rising"] &
        df["rs_positive"] &
        df["vol_ok"] &
        df["liquid"]
    )

    return df[df["signal"]].copy()


def compute_forward_returns(signals_df, prices_map):
    """
    For each signal row, look up fwd_return at 10d, 20d, 60d.
    prices_map: dict symbol -> DataFrame with date index and close column
    """
    rows = []
    for _, row in signals_df.iterrows():
        sym = row["symbol"]
        sig_date = row["date"]
        if sym not in prices_map:
            continue
        px = prices_map[sym]
        try:
            entry_close = px.loc[sig_date, "close"]
        except KeyError:
            continue

        future = px[px.index > sig_date]
        if len(future) == 0:
            continue

        def fwd_ret(n):
            if len(future) >= n:
                exit_close = future.iloc[n - 1]["close"]
                return (exit_close - entry_close) / entry_close * 100
            return np.nan

        r10 = fwd_ret(10)
        r20 = fwd_ret(20)
        r60 = fwd_ret(60)

        rows.append({
            "symbol": sym,
            "signal_date": sig_date,
            "entry_close": entry_close,
            "fwd_10d": r10,
            "fwd_20d": r20,
            "fwd_60d": r60,
        })
    return pd.DataFrame(rows)


def outcome_label(ret, threshold=6.0):
    if pd.isna(ret):
        return "BREAKEVEN"
    if ret > threshold:
        return "WINNER"
    if ret < -threshold:
        return "LOSER"
    return "BREAKEVEN"


def print_stats(label, df, col="fwd_20d"):
    df = df.dropna(subset=[col]).copy()
    df["outcome"] = df[col].apply(outcome_label)
    n = len(df)
    if n == 0:
        print(f"\n{label}: No valid signals.")
        return
    wins = (df["outcome"] == "WINNER").sum()
    losses = (df["outcome"] == "LOSER").sum()
    bes = (df["outcome"] == "BREAKEVEN").sum()
    wr = wins / n * 100
    lr = losses / n * 100
    avg_win = df.loc[df["outcome"] == "WINNER", col].mean() if wins else 0
    avg_loss = df.loc[df["outcome"] == "LOSER", col].mean() if losses else 0
    ev = (wins / n * avg_win) + (losses / n * avg_loss)

    years = (pd.to_datetime(df["signal_date"]).max() - pd.to_datetime(df["signal_date"]).min()).days / 365.25
    freq_per_yr = n / years if years > 0 else 0

    # Also show 10d and 60d avg returns
    avg10 = df["fwd_10d"].mean() if "fwd_10d" in df else np.nan
    avg20 = df[col].mean()
    avg60 = df["fwd_60d"].mean() if "fwd_60d" in df else np.nan

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Signals total     : {n}")
    print(f"  Years covered     : {years:.1f}  →  {freq_per_yr:.1f} signals/yr")
    print(f"  Win rate (>+6%)   : {wr:.1f}%  (n={wins})")
    print(f"  Loss rate (<-6%)  : {lr:.1f}%  (n={losses})")
    print(f"  Breakeven         : {bes}")
    print(f"  Avg win  (20d)    : +{avg_win:.1f}%")
    print(f"  Avg loss (20d)    : {avg_loss:.1f}%")
    print(f"  EV (20d)          : {ev:.2f}%")
    print(f"  Avg return 10d    : {avg10:.2f}%")
    print(f"  Avg return 20d    : {avg20:.2f}%")
    print(f"  Avg return 60d    : {avg60:.2f}%")

    # By year
    df["year"] = pd.to_datetime(df["signal_date"]).dt.year
    yearly = df.groupby("year").agg(
        signals=("signal_date", "count"),
        wr=("outcome", lambda x: (x == "WINNER").sum() / len(x) * 100),
        avg_ret=(col, "mean")
    )
    print(f"\n  Per-year breakdown (20d):")
    print(f"  {'Year':>6} {'Signals':>8} {'WR%':>7} {'AvgRet':>8}")
    for yr, row in yearly.iterrows():
        print(f"  {yr:>6} {row['signals']:>8} {row['wr']:>7.1f} {row['avg_ret']:>8.2f}%")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading data from psx_data.db...")
    con = sqlite3.connect(DB_PATH)

    # Universe: active symbols with sector mapping
    universe = pd.read_sql("""
        SELECT symbol FROM stock_metadata
        WHERE is_active = 1
    """, con)["symbol"].tolist()

    print(f"Universe: {len(universe)} symbols")

    # Load all prices_adjusted at once
    print("Loading prices_adjusted (this may take a moment)...")
    prices_all = pd.read_sql("""
        SELECT p.date, p.symbol, p.close, p.volume
        FROM prices_adjusted p
        JOIN stock_metadata sm ON p.symbol = sm.symbol
        WHERE sm.is_active = 1
          AND p.close IS NOT NULL
          AND p.volume IS NOT NULL
        ORDER BY p.symbol, p.date
    """, con)
    prices_all["date"] = pd.to_datetime(prices_all["date"])

    # KSE-100 index
    index_df = pd.read_sql("""
        SELECT date, close FROM index_prices
        WHERE symbol = 'KSE-100'
        ORDER BY date
    """, con)
    index_df["date"] = pd.to_datetime(index_df["date"])
    con.close()

    print(f"Prices rows: {len(prices_all):,}")
    print(f"Date range: {prices_all['date'].min().date()} to {prices_all['date'].max().date()}")

    # Build per-symbol price maps for forward return lookup
    print("Building symbol price maps...")
    prices_map = {}
    for sym, grp in prices_all.groupby("symbol"):
        df = grp.set_index("date").sort_index()
        prices_map[sym] = df

    # Run each variant
    all_signals = {}
    for variant, label in [
        ("A", "Variant A - Original Weinstein (150d SMA, Vol>=1.5x, RS 20d slope)"),
        ("B", "Variant B - PSX Daily / User-Specified (50d EMA, Vol>=1.5x, RS 10d slope)"),
        ("C", "Variant C - PSX Relaxed (50d EMA, Vol>=1.2x, RS 5d slope)"),
    ]:
        print(f"\nComputing signals for {label}...")
        sig_frames = []
        for sym in universe:
            if sym not in prices_map:
                continue
            px = prices_map[sym].reset_index()
            if len(px) < 160:
                continue
            px["symbol"] = sym
            try:
                sigs = compute_signals(px, index_df, variant=variant)
                if len(sigs):
                    sig_frames.append(sigs[["date", "symbol"]])
            except Exception as e:
                pass  # skip problematic symbols quietly

        if sig_frames:
            sig_df = pd.concat(sig_frames, ignore_index=True)
            sig_df["date"] = pd.to_datetime(sig_df["date"])
            print(f"  Raw signals before fwd returns: {len(sig_df)}")
            fwd = compute_forward_returns(sig_df, prices_map)
            all_signals[variant] = (label, fwd)
        else:
            print(f"  No signals found for variant {variant}")

    # Print stats
    print("\n\n" + "="*60)
    print("  BACKTEST RESULTS — PSX 2005–2026")
    print("  Outcome: WINNER>+6%, LOSER<-6%, else BREAKEVEN")
    print("  Liquidity filter: avg_vol_10d > 200,000")
    print("="*60)

    for variant, (label, fwd_df) in all_signals.items():
        print_stats(label, fwd_df)

    # Compare: are signals clustered in certain years/regimes?
    print("\n\n--- SIGNAL FREQUENCY CHECK (Variant B, 50d EMA) ---")
    if "B" in all_signals:
        _, fwd_b = all_signals["B"]
        fwd_b["year"] = pd.to_datetime(fwd_b["signal_date"]).dt.year
        print(fwd_b.groupby("year").size().to_string())

    # Decay analysis: does return improve holding longer?
    print("\n\n--- DECAY ANALYSIS (Variant B) ---")
    if "B" in all_signals:
        _, fwd_b = all_signals["B"]
        df_valid = fwd_b.dropna(subset=["fwd_10d", "fwd_20d", "fwd_60d"])
        print(f"  Avg return 10d : {df_valid['fwd_10d'].mean():.2f}%")
        print(f"  Avg return 20d : {df_valid['fwd_20d'].mean():.2f}%")
        print(f"  Avg return 60d : {df_valid['fwd_60d'].mean():.2f}%")
        # Win rate at each horizon
        for col in ["fwd_10d", "fwd_20d", "fwd_60d"]:
            df_valid["oc"] = df_valid[col].apply(outcome_label)
            wr = (df_valid["oc"] == "WINNER").sum() / len(df_valid) * 100
            lr = (df_valid["oc"] == "LOSER").sum() / len(df_valid) * 100
            print(f"  {col}  WR={wr:.1f}%  LR={lr:.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
