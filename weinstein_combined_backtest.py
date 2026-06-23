"""
Weinstein Combined-Gate Persistent-State Backtest
==================================================
Tests the Weinstein watchlist screener as it actually runs on the dashboard:
a daily state scan, not a point-in-time crossover event.

Signal definition: a stock_signals row meets ALL active gates on a given date.
Dedup: only the FIRST day of each consecutive qualifying streak per symbol counts
(avoids double-counting the same trade setup on adjacent days).

Gates tested (building sequentially):
  Base:   sec_stage='Stage 2' AND sec_global_rank <= 8
  +EMA50: base + close_above_ema50=1 AND ema50_slope_pos=1
  +EMA150:base + close_above_ema150=1 AND ema150_slope_pos=1  [the proposed change]
  +RS:    previous + rank_change > 0
  +Sec5:  previous + sector_rs_rank <= 5
  +Coil:  previous + near_pivot_days >= 7
  +Vol:   previous + avg_vol_10d > 200000                     [full Weinstein screener]

Forward return: 90 trading days from signal date using prices_adjusted.
Outcome: WINNER >+6%, LOSER <-6%, BREAKEVEN otherwise.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

DB = str(Path(__file__).parent / 'psx_data.db')
WINDOW = 90


def load_data():
    conn = sqlite3.connect(DB)

    ss = pd.read_sql_query(
        """
        SELECT ss.date, ss.symbol, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.near_pivot_days, ss.avg_vol_10d,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.close_above_ema150, ss.ema150_slope_pos,
               sec.rs_rank AS sec_global_rank,
               sec.sector_stage AS sec_stage
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        WHERE ss.date >= '2015-01-01'
        ORDER BY ss.symbol, ss.date
        """,
        conn,
    )

    prices = pd.read_sql_query(
        """
        SELECT symbol, date, close
        FROM prices_adjusted
        WHERE symbol IN (SELECT DISTINCT symbol FROM stock_signals)
        ORDER BY symbol, date
        """,
        conn,
    )
    conn.close()

    ss['date'] = pd.to_datetime(ss['date'])
    prices['date'] = pd.to_datetime(prices['date'])
    return ss, prices


def build_prices_map(prices_df):
    pm = {}
    for sym, grp in prices_df.groupby('symbol'):
        pm[sym] = grp.set_index('date').sort_index()['close']
    return pm


def fwd_return(sym, sig_date, prices_map, n=WINDOW):
    if sym not in prices_map:
        return np.nan
    px = prices_map[sym]
    try:
        entry = px.loc[sig_date]
    except KeyError:
        future_all = px[px.index >= sig_date]
        if len(future_all) == 0:
            return np.nan
        entry = future_all.iloc[0]
    future = px[px.index > sig_date]
    if len(future) < n:
        return np.nan
    exit_px = future.iloc[n - 1]
    return (exit_px - entry) / entry * 100


def outcome(ret, threshold=6.0):
    if pd.isna(ret):
        return 'BE'
    if ret > threshold:
        return 'WIN'
    if ret < -threshold:
        return 'LOSS'
    return 'BE'


def dedup_streaks(df):
    """Keep only the first row of each consecutive qualifying streak per symbol.

    NOTE on N behaviour: adding more restrictive gates can fragment long continuous
    streaks into multiple shorter streaks, so deduped N can *increase* as gates are
    added. This is not a data error — each fragment is a genuinely new setup entry
    within the combined condition set — but it makes the funnel non-monotonic in N.
    Raw row count (pre-dedup) is always monotonically decreasing with more gates.
    Both are reported so the reader can distinguish the two effects.
    """
    df = df.sort_values(['symbol', 'date']).copy()
    df['prev_date'] = df.groupby('symbol')['date'].shift(1)
    df['gap'] = (df['date'] - df['prev_date']).dt.days
    # New streak if no prior row or gap > 1 trading day (use 5 to allow weekends/holidays)
    df['new_streak'] = (df['prev_date'].isna()) | (df['gap'] > 5)
    return df[df['new_streak']].drop(columns=['prev_date', 'gap', 'new_streak'])


def run_gate(ss, prices_map, mask, label):
    raw_n = mask.sum()  # monotonically decreasing with more gates
    sigs = ss[mask].copy()
    sigs = dedup_streaks(sigs)  # first day of each streak; can be non-monotonic
    dedup_n = len(sigs)

    rows = []
    for _, row in sigs.iterrows():
        r = fwd_return(row['symbol'], row['date'], prices_map)
        rows.append({'date': row['date'], 'symbol': row['symbol'], 'ret': r})

    if not rows:
        print(f"  {label}: no signals")
        return

    df = pd.DataFrame(rows).dropna(subset=['ret'])
    n = len(df)
    if n == 0:
        print(f"  {label}: N=0 after fwd-return filter")
        return

    df['out'] = df['ret'].apply(outcome)
    wins = (df['out'] == 'WIN').sum()
    losses = (df['out'] == 'LOSS').sum()
    wr = wins / n * 100
    lr = losses / n * 100
    avg_win = df.loc[df['out'] == 'WIN', 'ret'].mean() if wins else 0
    avg_loss = df.loc[df['out'] == 'LOSS', 'ret'].mean() if losses else 0
    ev = (wins / n * avg_win) + (losses / n * avg_loss)

    yrs = (df['date'].max() - df['date'].min()).days / 365.25
    freq = n / yrs if yrs > 0 else 0

    print(
        f"  {label:<52} raw={raw_n:>6}  streaks={n:>5}  "
        f"WR={wr:>5.1f}%  LR={lr:>5.1f}%  EV={ev:>+6.2f}%  ({freq:.1f}/yr)"
    )


def main():
    print("Loading stock_signals + sector_signals...")
    ss, prices = load_data()
    print(f"  stock_signals rows: {len(ss):,}  |  price rows: {len(prices):,}")

    print("Building prices map...")
    pm = build_prices_map(prices)

    # Check EMA150 coverage
    ema150_filled = ss['close_above_ema150'].notna().sum()
    print(f"  close_above_ema150 non-null rows: {ema150_filled:,} / {len(ss):,}")
    if ema150_filled == 0:
        print("  ERROR: close_above_ema150 is all NULL — backfill has not run yet.")
        return

    print(f"\nResults at {WINDOW}d forward window  (deduped to first day of streak)\n")
    print("  " + "-" * 80)

    # 1. Sector gate only
    mask_sec = (
        (ss['sec_stage'] == 'Stage 2') &
        (ss['sec_global_rank'].fillna(999) <= 8)
    )
    run_gate(ss, pm, mask_sec, "Sector only (Stage2 + rank<=8)")

    # 2. + EMA50 (current screener MA)
    mask_ema50 = mask_sec & (
        (ss['close_above_ema50'].fillna(0) == 1) &
        (ss['ema50_slope_pos'].fillna(0) == 1)
    )
    run_gate(ss, pm, mask_ema50, "+ EMA50 above & slope (current)")

    # 3. + EMA150 (proposed change)
    mask_ema150 = mask_sec & (
        (ss['close_above_ema150'].fillna(0) == 1) &
        (ss['ema150_slope_pos'].fillna(0) == 1)
    )
    run_gate(ss, pm, mask_ema150, "+ EMA150 above & slope (proposed)")

    # 4. EMA150 + RS improving
    mask_ema150_rs = mask_ema150 & (ss['rank_change'].fillna(-999) > 0)
    run_gate(ss, pm, mask_ema150_rs, "+ EMA150 + rank_change>0")

    # 5. EMA150 + RS + sector_rs_rank <= 5
    mask_ema150_rs_sec5 = mask_ema150_rs & (ss['sector_rs_rank'].fillna(999) <= 5)
    run_gate(ss, pm, mask_ema150_rs_sec5, "+ EMA150 + rank_chg>0 + sec_rs_rank<=5")

    # 6. EMA150 + RS + sec5 + coiling
    mask_ema150_coil = mask_ema150_rs_sec5 & (ss['near_pivot_days'].fillna(0) >= 7)
    run_gate(ss, pm, mask_ema150_coil, "+ EMA150 + rank_chg>0 + sec5 + coil>=7d")

    # 7. Full Weinstein (EMA150 version) + volume
    mask_full150 = mask_ema150_coil & (ss['avg_vol_10d'].fillna(0) > 200_000)
    run_gate(ss, pm, mask_full150, "FULL EMA150 Weinstein + vol>200k")

    print()

    # Reference: full Weinstein with EMA50 (current live screener)
    mask_ema50_rs = mask_ema50 & (ss['rank_change'].fillna(-999) > 0)
    mask_ema50_sec5 = mask_ema50_rs & (ss['sector_rs_rank'].fillna(999) <= 5)
    mask_ema50_coil = mask_ema50_sec5 & (ss['near_pivot_days'].fillna(0) >= 7)
    mask_full50 = mask_ema50_coil & (ss['avg_vol_10d'].fillna(0) > 200_000)
    run_gate(ss, pm, mask_full50, "FULL EMA50 Weinstein + vol>200k  [CURRENT]")

    print("\n  " + "-" * 80)
    print("  Key: EV = (WR * avg_win) + (LR * avg_loss)  |  freq = signals/year")
    print("  Dedup: first day of each consecutive qualifying streak per symbol")
    print(f"  Window: {WINDOW} calendar trading days forward")


if __name__ == '__main__':
    main()
