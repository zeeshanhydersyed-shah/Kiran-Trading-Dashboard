"""
Screener Audit: Minervini + STM vs confirmed screeners
=======================================================
Step 1  — Gate documentation (from source, not memory)
Step 2  — Overlap analysis: what % of each screener's signals also appear
           as BREAKOUT or PRE_BREAKOUT in setup_log within ±5 trading days
Step 3  — Independent backtests at windows appropriate to each screener's
           holding-period design (STM: 10/20d; Minervini: 20/30d)
Step 4  — Verdict per screener

Signal reconstruction approach:
  Both mv_signals and stm_signals only have 1 week of history (June 2026).
  Proxy signals are reconstructed from stock_signals + sector_signals + market_regime
  using the gates described in the dashboard source code. Proxy is noted where it
  differs from the exact production screener.

Outcome convention (consistent with all session backtests):
  WINNER  >  +6%
  LOSER   < -6%
  BREAKEVEN otherwise
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

DB = str(Path(__file__).parent / 'psx_data.db')


# ── helpers ───────────────────────────────────────────────────────────────────

def outcome(ret, t=6.0):
    if pd.isna(ret): return 'BE'
    return 'WIN' if ret > t else ('LOSS' if ret < -t else 'BE')

def ev_stats(df, col):
    df = df.dropna(subset=[col]).copy()
    df['out'] = df[col].apply(outcome)
    n = len(df)
    if n == 0:
        return dict(n=0, wr=0, lr=0, ev=0, freq=0)
    wins   = (df['out'] == 'WIN').sum()
    losses = (df['out'] == 'LOSS').sum()
    wr = wins / n * 100
    lr = losses / n * 100
    aw = df.loc[df['out'] == 'WIN',  col].mean() if wins   else 0.0
    al = df.loc[df['out'] == 'LOSS', col].mean() if losses else 0.0
    ev = (wins/n * aw) + (losses/n * al)
    yrs = (pd.to_datetime(df['date']).max() - pd.to_datetime(df['date']).min()).days / 365.25
    freq = n / yrs if yrs > 0 else 0
    return dict(n=n, wr=wr, lr=lr, ev=ev, freq=freq)

def dedup_streaks(df, date_col='date'):
    df = df.sort_values(['symbol', date_col]).copy()
    df['_prev'] = df.groupby('symbol')[date_col].shift(1)
    df['_gap']  = (df[date_col] - df['_prev']).dt.days
    df['_new']  = df['_prev'].isna() | (df['_gap'] > 5)
    return df[df['_new']].drop(columns=['_prev', '_gap', '_new'])

def fwd_ret(sym, sig_date, prices_map, n):
    if sym not in prices_map: return np.nan
    px = prices_map[sym]
    future = px[px.index > sig_date]
    if len(future) == 0: return np.nan
    try:
        entry = px.loc[sig_date]
    except KeyError:
        entry = future.iloc[0]
    if len(future) < n: return np.nan
    return (future.iloc[n-1] - entry) / entry * 100

def print_ev(label, stats):
    print(f"  {label:<48} N={stats['n']:>5}  WR={stats['wr']:>5.1f}%  LR={stats['lr']:>5.1f}%  "
          f"EV={stats['ev']:>+6.2f}%  ({stats['freq']:.1f}/yr)")


# ── load base data ─────────────────────────────────────────────────────────────

def load_data():
    conn = sqlite3.connect(DB)

    ss = pd.read_sql_query(
        """SELECT ss.date, ss.symbol, ss.rs_rank, ss.sector_rs_rank,
                  ss.rank_change, ss.rs_score_20, ss.base_tightness,
                  ss.overhead_clear, ss.bos_flag, ss.pivot_distance_pct,
                  ss.avg_vol_10d, ss.stage2_bull,
                  ss.close_above_ema50, ss.ema50_slope_pos,
                  ss.close_above_ema150, ss.ema150_slope_pos,
                  sec.rs_rank AS sec_global_rank, sec.breadth_score AS sec_breadth,
                  sec.sector_stage
           FROM stock_signals ss
           JOIN sectors s ON ss.symbol = s.symbol
           LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
           WHERE ss.date >= '2015-01-01'
           ORDER BY ss.symbol, ss.date""",
        conn,
    )

    mkt = pd.read_sql_query(
        "SELECT date, close, ema_50 FROM market_regime ORDER BY date",
        conn,
    )

    # Market-wide breadth: average breadth_score across all sectors per date
    mbreadth = pd.read_sql_query(
        "SELECT date, AVG(breadth_score) AS mkt_breadth FROM sector_signals GROUP BY date",
        conn,
    )

    setup_log = pd.read_sql_query(
        """SELECT symbol, setup_date, setup_type,
                  fwd_return_5d, fwd_return_10d, fwd_return_20d
           FROM setup_log
           WHERE setup_type IN ('BREAKOUT','PRE_BREAKOUT')
             AND setup_date >= '2015-01-01'""",
        conn,
    )

    prices = pd.read_sql_query(
        "SELECT symbol, date, close FROM prices_adjusted ORDER BY symbol, date",
        conn,
    )
    conn.close()

    for df in [ss, mkt, mbreadth, setup_log, prices]:
        date_col = 'date' if 'date' in df.columns else 'setup_date'
        df[date_col] = pd.to_datetime(df[date_col])

    ss['date'] = pd.to_datetime(ss['date'])
    return ss, mkt, mbreadth, setup_log, prices


def build_prices_map(prices_df):
    pm = {}
    for sym, g in prices_df.groupby('symbol'):
        pm[sym] = g.set_index('date').sort_index()['close']
    return pm


# ── Step 1: Gate documentation ─────────────────────────────────────────────────

def print_gate_docs():
    print("=" * 78)
    print("  STEP 1 -- GATE DOCUMENTATION (from source code, not memory)")
    print("=" * 78)
    print("""
--- STM Screener (_run_stm_screener in dashboard.py) ---
Design intent: Short-Term Momentum -- stocks in a confirmed uptrend that are
outperforming the market. No base/pivot requirement. Fires on stocks already
in motion, not stocks coiling for a breakout.

MARKET GATES (all three must pass before any stock scan):
  [1] KSE-100 close > 50 MA                    (trend direction)
  [2] Z-histogram > 0                           (MACD-style momentum on KSE-100)
  [3] Market breadth score >= 70/100            (broad participation)

STOCK GATES:
  [4] Sector in top 35% by RS-20                (sector tailwind)
  [5] 5-day price range <= 10%                  (recent volatility not excessive)
  [6] 10-day avg volume >= 500,000              (high liquidity -- 2.5x Weinstein)
  [7] Close > 10                                (price floor)
  [8] Stock 30d return > KSE-100 30d return     (outperforming market)
  [9] Close > 21 SMA > 50 SMA                   (uptrend stack)

PROXY USED HERE: close_above_ema50=1 AND ema50_slope_pos=1 proxies gates [9].
rs_score_20 > 0 proxies gate [8]. Breadth gate uses avg(sector breadth_scores).
Z-histogram not available historically -- omitted (makes proxy LOOSER than actual).

--- Minervini Setup Screener (mv_signals, dashboard PAGES[17]) ---
Design intent: High-quality breakout setups from stocks in confirmed Stage 2
uptrends, coiling in a tight base, with clear overhead and strong relative
strength. More filters than the raw BREAKOUT signal.

MARKET GATES:
  [1] KSE-100 above EMA50                       (bull regime only)
  [2] Market breadth >= 60%                      (broad participation)

SECTOR GATES:
  [3] Sector rank <= 6 (top 6 sectors)
  [4] Sector breadth >= 70%

STOCK GATES:
  [5] Stage 2: close > EMA20 > EMA50 > EMA200   (full bull stack)
  [6] Base tightness: BBW <= 12%                 (coiling, not extended)
  [7] Overhead clear: 200d high <= pivot * 1.05  (clear air above)
  [8] RS Rank <= 50                              (top leader in PSX)
  [9] Sector RS rank <= 5                        (leader within sector)
  [10] RS Rating >= 60th percentile              (multi-period momentum)
  [11] ATR 14d: 1%% to 6%% of price              (controlled volatility)
  [12] 20d avg volume >= 100,000                 (liquidity -- looser than STM)

BREAKOUT ONLY: vol ratio >= 2x 20d avg          (institutional conviction)
WATCHLIST: bos_flag=0, stock within 3%% below pivot (near but not broken out)

PROXY USED HERE: Omits RS Rating percentile (multi-period, complex to reconstruct),
ATR range, sector breadth. Gate [7] uses overhead_clear=1 (code uses pivot*1.15,
dashboard doc says pivot*1.05 -- using DB column as-is). Makes proxy LOOSER.

--- Reference screeners (confirmed, from setup_log) ---
BREAKOUT:     bos_flag=1 AND avg_vol_10d > 200k
PRE_BREAKOUT: pivot_dist 0-3%% AND base_tightness < 8 AND avg_vol_10d > 200k
""")


# ── Step 2: Overlap analysis ───────────────────────────────────────────────────

def overlap_analysis(signals_df, setup_log, label, ref_types=('BREAKOUT', 'PRE_BREAKOUT')):
    """
    For each signal, check if same symbol appears in setup_log for any ref_type
    within ±5 TRADING DAYS. Uses vectorized date proximity check.
    """
    if signals_df.empty:
        print(f"  {label}: no signals to compare")
        return

    ref = setup_log[setup_log['setup_type'].isin(ref_types)][['symbol', 'setup_date']].copy()
    ref = ref.rename(columns={'setup_date': 'ref_date'})

    # Cross-join on symbol, then filter by date proximity
    merged = signals_df[['date', 'symbol']].merge(ref, on='symbol', how='inner')
    merged['day_diff'] = (merged['date'] - merged['ref_date']).dt.days.abs()
    close_matches = merged[merged['day_diff'] <= 7]  # ~5 trading days

    n_total   = len(signals_df)
    n_overlap = close_matches['symbol'].nunique()
    # count signals (not symbols) that had any close match
    sig_with_match = close_matches[['date', 'symbol']].drop_duplicates()
    n_sig_overlap  = len(sig_with_match.merge(signals_df[['date', 'symbol']], on=['date', 'symbol']))

    pct = n_sig_overlap / n_total * 100 if n_total > 0 else 0

    # By type breakdown
    for rt in ref_types:
        rt_ref = setup_log[setup_log['setup_type'] == rt][['symbol', 'setup_date']].rename(columns={'setup_date': 'ref_date'})
        m2 = signals_df[['date', 'symbol']].merge(rt_ref, on='symbol', how='inner')
        m2['day_diff'] = (m2['date'] - m2['ref_date']).dt.days.abs()
        m2c = m2[m2['day_diff'] <= 7][['date', 'symbol']].drop_duplicates()
        n2  = len(m2c.merge(signals_df[['date', 'symbol']], on=['date', 'symbol']))
        print(f"    vs {rt:<15}: {n2:>5} of {n_total} signals ({n2/n_total*100:.1f}%)")

    print(f"  {label}: {n_sig_overlap}/{n_total} signals ({pct:.1f}%) overlap with "
          f"BREAKOUT or PRE_BREAKOUT within +-5 trading days")


# ── Step 3: Backtests ──────────────────────────────────────────────────────────

def run_backtest(sigs_df, prices_map, label, windows=(10, 20, 30)):
    sigs = dedup_streaks(sigs_df.copy())
    rows = []
    for _, row in sigs.iterrows():
        r = {w: fwd_ret(row['symbol'], row['date'], prices_map, w) for w in windows}
        r['date'] = row['date']
        r['symbol'] = row['symbol']
        rows.append(r)
    if not rows:
        print(f"  {label}: no signals")
        return
    df = pd.DataFrame(rows)
    for w in windows:
        s = ev_stats(df.rename(columns={w: 'ret'}).dropna(subset=['ret']), 'ret')
        print_ev(f"{label} @ {w}d", s)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print_gate_docs()

    print("Loading data...")
    ss, mkt, mbreadth, setup_log, prices = load_data()
    pm = build_prices_map(prices)

    # Merge market gate (KSE > EMA50)
    mkt['mkt_up'] = (mkt['close'] > mkt['ema_50']).astype(int)
    ss = ss.merge(mkt[['date', 'mkt_up']], on='date', how='left')
    ss = ss.merge(mbreadth.rename(columns={'date': 'date'}), on='date', how='left')

    # total sectors per date for 35% cutoff
    sec_counts = pd.read_sql_query(
        "SELECT date, COUNT(DISTINCT sector) AS n_sectors FROM sector_signals GROUP BY date",
        sqlite3.connect(DB),
    )
    sec_counts['date'] = pd.to_datetime(sec_counts['date'])
    ss = ss.merge(sec_counts, on='date', how='left')
    ss['n_sectors'] = ss['n_sectors'].fillna(23)
    ss['sec_cutoff_35pct'] = (ss['n_sectors'] * 0.35).round().astype(int)

    print(f"\nstock_signals rows loaded: {len(ss):,}")
    print(f"setup_log BREAKOUT rows: {(setup_log['setup_type']=='BREAKOUT').sum():,}")
    print(f"setup_log PRE_BREAKOUT rows: {(setup_log['setup_type']=='PRE_BREAKOUT').sum():,}")
    print(f"prices_adjusted: {len(prices):,} rows\n")

    # ── Build signal sets ──────────────────────────────────────────────────────

    # STM proxy
    stm_mask = (
        (ss['mkt_up'].fillna(0) == 1) &
        (ss['mkt_breadth'].fillna(0) >= 70) &
        (ss['sec_global_rank'].fillna(999) <= ss['sec_cutoff_35pct']) &
        (ss['close_above_ema50'].fillna(0) == 1) &
        (ss['ema50_slope_pos'].fillna(0) == 1) &
        (ss['rs_score_20'].fillna(-999) > 0) &
        (ss['avg_vol_10d'].fillna(0) >= 500_000)
    )
    stm_sigs = ss[stm_mask][['date', 'symbol']].copy()

    # Minervini BREAKOUT proxy
    mv_bo_mask = (
        (ss['mkt_up'].fillna(0) == 1) &
        (ss['mkt_breadth'].fillna(0) >= 60) &
        (ss['stage2_bull'].fillna(0) == 1) &
        (ss['base_tightness'].fillna(99) <= 12) &
        (ss['overhead_clear'].fillna(0) == 1) &
        (ss['rs_rank'].fillna(999) <= 50) &
        (ss['sector_rs_rank'].fillna(999) <= 5) &
        (ss['sec_global_rank'].fillna(999) <= 6) &
        (ss['avg_vol_10d'].fillna(0) >= 100_000) &
        (ss['bos_flag'].fillna(0) == 1)
    )
    mv_bo_sigs = ss[mv_bo_mask][['date', 'symbol']].copy()

    # Minervini WATCHLIST proxy
    mv_wl_mask = (
        (ss['mkt_up'].fillna(0) == 1) &
        (ss['mkt_breadth'].fillna(0) >= 60) &
        (ss['stage2_bull'].fillna(0) == 1) &
        (ss['base_tightness'].fillna(99) <= 12) &
        (ss['overhead_clear'].fillna(0) == 1) &
        (ss['rs_rank'].fillna(999) <= 50) &
        (ss['sector_rs_rank'].fillna(999) <= 5) &
        (ss['sec_global_rank'].fillna(999) <= 6) &
        (ss['avg_vol_10d'].fillna(0) >= 100_000) &
        (ss['bos_flag'].fillna(0) == 0) &
        (ss['pivot_distance_pct'].fillna(99) >= 0) &
        (ss['pivot_distance_pct'].fillna(99) <= 3)
    )
    mv_wl_sigs = ss[mv_wl_mask][['date', 'symbol']].copy()

    # Reference: setup_log BREAKOUT and PRE_BREAKOUT as signals (for backtest comparison)
    bo_sigs  = setup_log[setup_log['setup_type'] == 'BREAKOUT'][['setup_date', 'symbol', 'fwd_return_10d', 'fwd_return_20d']].rename(columns={'setup_date': 'date'})
    pbo_sigs = setup_log[setup_log['setup_type'] == 'PRE_BREAKOUT'][['setup_date', 'symbol', 'fwd_return_10d', 'fwd_return_20d']].rename(columns={'setup_date': 'date'})

    print(f"Signal counts (raw, before dedup):")
    print(f"  STM proxy:                {len(stm_sigs):>6}")
    print(f"  Minervini BREAKOUT proxy: {len(mv_bo_sigs):>6}")
    print(f"  Minervini WATCHLIST proxy:{len(mv_wl_sigs):>6}")
    print(f"  setup_log BREAKOUT:       {len(bo_sigs):>6}")
    print(f"  setup_log PRE_BREAKOUT:   {len(pbo_sigs):>6}")

    dedup_stm   = dedup_streaks(stm_sigs)
    dedup_mv_bo = dedup_streaks(mv_bo_sigs)
    dedup_mv_wl = dedup_streaks(mv_wl_sigs)

    print(f"\nSignal counts (deduped to first day of streak):")
    print(f"  STM proxy:                {len(dedup_stm):>6}  ({len(dedup_stm)/11:.0f}/yr est)")
    print(f"  Minervini BREAKOUT proxy: {len(dedup_mv_bo):>6}  ({len(dedup_mv_bo)/11:.0f}/yr est)")
    print(f"  Minervini WATCHLIST proxy:{len(dedup_mv_wl):>6}  ({len(dedup_mv_wl)/11:.0f}/yr est)")
    print(f"  setup_log BREAKOUT:       {len(bo_sigs):>6}  ({len(bo_sigs)/11:.0f}/yr est)")
    print(f"  setup_log PRE_BREAKOUT:   {len(pbo_sigs):>6}  ({len(pbo_sigs)/11:.0f}/yr est)")

    # ── Step 2: Overlap ────────────────────────────────────────────────────────
    print("""
STEP 2 -- OVERLAP ANALYSIS (same symbol within +-5 trading days)
""")
    overlap_analysis(dedup_stm,   setup_log, "STM proxy")
    print()
    overlap_analysis(dedup_mv_bo, setup_log, "Minervini BREAKOUT proxy")
    print()
    overlap_analysis(dedup_mv_wl, setup_log, "Minervini WATCHLIST proxy")

    # Also: STM vs Weinstein overlap
    wein_mask = (
        (ss['sector_stage'] == 'Stage 2') &
        (ss['sec_global_rank'].fillna(999) <= 8) &
        (ss['close_above_ema150'].fillna(0) == 1) &
        (ss['ema150_slope_pos'].fillna(0) == 1) &
        (ss['rank_change'].fillna(-999) > 0) &
        (ss['sector_rs_rank'].fillna(999) <= 5) &
        (ss['avg_vol_10d'].fillna(0) > 200_000)
    )
    wein_sigs = ss[wein_mask][['date', 'symbol']].copy()

    # Build Weinstein reference in same format as setup_log
    wein_ref = wein_sigs.rename(columns={'date': 'setup_date'}).copy()
    wein_ref['setup_type'] = 'WEINSTEIN'
    wein_ref['fwd_return_5d'] = np.nan
    wein_ref['fwd_return_10d'] = np.nan
    wein_ref['fwd_return_20d'] = np.nan
    full_ref = pd.concat([setup_log, wein_ref[setup_log.columns]], ignore_index=True)

    print()
    overlap_analysis(dedup_stm,   full_ref,
                     "STM proxy vs ALL (BREAKOUT + PRE_BO + Weinstein)", ref_types=('BREAKOUT','PRE_BREAKOUT','WEINSTEIN'))
    overlap_analysis(dedup_mv_bo, full_ref,
                     "Minervini BO proxy vs ALL", ref_types=('BREAKOUT','PRE_BREAKOUT','WEINSTEIN'))

    # ── Step 3: Backtests ──────────────────────────────────────────────────────
    print("""
STEP 3 -- INDEPENDENT BACKTESTS
  Outcome: WINNER >+6%, LOSER <-6%, BREAKEVEN otherwise
  Deduped to first day of streak per symbol
""")
    print("  STM — design implies short-term momentum (10-20d):")
    run_backtest(stm_sigs, pm, "STM proxy", windows=(10, 20, 30, 60))

    print()
    print("  Minervini — design implies breakout with target/stop (20-30d):")
    run_backtest(mv_bo_sigs, pm, "Minervini BREAKOUT proxy", windows=(10, 20, 30, 60))
    run_backtest(mv_wl_sigs, pm, "Minervini WATCHLIST proxy", windows=(10, 20, 30, 60))

    print()
    print("  Reference (setup_log, at their stored windows):")
    # setup_log has precomputed fwd returns — use them directly
    for label, sdf in [("BREAKOUT (setup_log)", bo_sigs), ("PRE_BREAKOUT (setup_log)", pbo_sigs)]:
        for col, w in [('fwd_return_10d', 10), ('fwd_return_20d', 20)]:
            sub = sdf.dropna(subset=[col]).copy()
            sub = sub.rename(columns={col: 'ret'})
            s = ev_stats(sub, 'ret')
            print_ev(f"{label} @ {w}d", s)

    print()
    print("  Weinstein Stage 2 (confirmed, for context):")
    run_backtest(wein_sigs, pm, "Weinstein proxy", windows=(30, 60, 90))


if __name__ == '__main__':
    main()
