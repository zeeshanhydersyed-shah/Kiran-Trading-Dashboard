"""
Recovery Bases Screener — Full Historical Audit
================================================
Steps 1-5 audit per the session brief.

Step 1 summary (from code, not from memory):
─────────────────────────────────────────────
STOCK CONDITION ("long beaten getting a chance to enter"):
  A stock that:
  (a) Had a prior decline of ≥30% from its highest close in the 90 bars before
      the base started  →  "post-capitulation"
  (b) After declining, entered a tight consolidation: price range (max-min)/min < 20%
      over at least 8 and up to 90 consecutive bars  →  "base forming"
  (c) Within that base, volume showed institutional accumulation (≥2 bars with vol >
      1.5× early-base median) then contracted to near-zero (last 5 bars avg < 0.50×
      early-base median, ≥3 bars individually below 0.60×)  →  "coiling"
  (d) Liquidity: 20d average volume ≥ 800k shares; close ≥ Rs.5

WATCHLIST state  →  conditions (a)-(c) met as of today; breakout NOT yet confirmed.
  Base is still forming. Price is below the base high (the trigger level).
  The stock is watched; no entry yet.

TRIGGERED state  →  on breakout day t, ALL of (a)-(c) were met for the base ending at
  t-1, AND the breakout condition fired:
    vol_t ≥ 2.5 × vol_ma50  (massive volume surge — trigger uses vol_ma50, not early-base)
    close_t > base_high      (price closed above the base's ceiling)
    close_t in upper 40% of day's range  (bullish close, not a wick reversal)
  The stock moves from WATCHLIST to TRIGGERED when this fires.

THREE STRUCTURAL FIXES applied in the code (FIX comments in signal_engine.py):
  FIX 1: Volume baseline for contraction/accumulation gates uses the median of the
         first ≤10 bars of the base ("early-base median"), NOT vol_ma50.
         Rationale: the 50-day MA includes the high-volume decline period, inflating
         the denominator and making contraction appear more extreme than it is. The
         early-base median reflects volume levels after the selling pressure stopped.
         (The trigger itself still uses vol_ma50 because we want absolute volume
         magnitude, not base-relative — a 2.5× signal vs an already-depressed baseline
         would be meaningless.)
  FIX 2: close > open (green candle) was removed. PSX prices have structurally NULL
         opens (backfilled with close), making close > open trivially true and useless.
         Replaced by: close in upper 40% of day's H-L range — a real condition.
  FIX 3: TRIGGERED scan uses bv = volumes[bs : prev+1]  (base ends at t-1, not at t).
         This excludes the breakout day itself from the base's volume pattern analysis.
         Without this, the massive breakout-day volume would corrupt the "prior surge"
         count and potentially the contraction baseline.

Steps 2-5 are the quantitative audit below.
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

DB = str(Path(__file__).parent / 'psx_data.db')

# ── Tuneable parameters (matching production exactly) ──────────────────────────
MIN_AVG_VOL      = 800_000    # 20d avg volume floor
MIN_PRICE        = 5.0        # price floor Rs.
MIN_BARS         = 60         # warmup bars required before any signal
DRAWDOWN_MIN     = 0.30       # prior decline ≥ 30%
BASE_RANGE_MAX   = 0.20       # base tight < 20%
BASE_DAYS_MIN    = 8          # base at least 8 bars
BASE_DAYS_MAX    = 90         # base scan lookback cap
PRE_HIGH_BARS    = 90         # how far back to look for the pre-base high
CONTRACTION_MEAN = 0.50       # last 5 bars avg < 50% of baseline
CONTRACTION_N    = 3          # ≥3 of last 5 bars individually < 60%
CONTRACTION_IND  = 0.60
SURGE_THR        = 1.5        # surge = bar > 1.5× baseline
SURGE_MIN        = 2          # ≥2 surge bars within base
TRIGGER_VOL      = 2.5        # trigger: vol ≥ 2.5× vol_ma50
TRIGGER_RANGE    = 0.40       # trigger: close in upper 40% of range
WIN_THR          = 6.0        # ±6% WIN / LOSS threshold
SIGNAL_START     = '2015-01-01'   # aligned with stock_signals coverage


def load_data():
    conn = sqlite3.connect(DB)

    # OHLCV from prices (production uses this table for screener logic)
    print("Loading prices (OHLCV)...")
    prices = pd.read_sql_query(
        """
        SELECT p.symbol, s.sector, p.date,
               p.open, p.high, p.low, p.close,
               COALESCE(p.volume, 0) AS volume
        FROM prices p
        JOIN sectors s ON s.symbol = p.symbol
        WHERE p.date >= '2014-01-01'
        ORDER BY p.symbol, p.date
        """,
        conn,
    )

    # Adjusted closes for forward returns
    print("Loading prices_adjusted (forward returns)...")
    adj = pd.read_sql_query(
        """
        SELECT symbol, date, close AS adj_close
        FROM prices_adjusted
        WHERE date >= '2014-01-01'
        ORDER BY symbol, date
        """,
        conn,
    )

    # Excluded sectors (match production config)
    try:
        from config import EXCLUDED_SECTORS
    except Exception:
        EXCLUDED_SECTORS = []

    conn.close()

    prices['date'] = pd.to_datetime(prices['date'])
    adj['date']    = pd.to_datetime(adj['date'])
    for col in ('open', 'high', 'low', 'close', 'volume'):
        prices[col] = pd.to_numeric(prices[col], errors='coerce').fillna(0)
    adj['adj_close'] = pd.to_numeric(adj['adj_close'], errors='coerce')

    if EXCLUDED_SECTORS:
        prices = prices[~prices['sector'].isin(EXCLUDED_SECTORS)]
    prices = prices[~prices['symbol'].str.match(r'^P\d', na=False)]

    print(f"  prices rows: {len(prices):,}  symbols: {prices['symbol'].nunique()}")
    print(f"  adj rows:    {len(adj):,}")
    return prices, adj


def build_adj_map(adj_df):
    am = {}
    for sym, grp in adj_df.groupby('symbol'):
        am[sym] = grp.set_index('date').sort_index()['adj_close']
    return am


def fwd_return(sym, sig_date, adj_map, n):
    """Forward return n trading days from sig_date using adjusted prices."""
    if sym not in adj_map:
        return np.nan
    px = adj_map[sym]
    try:
        entry = px.loc[sig_date]
    except KeyError:
        future_all = px[px.index >= sig_date]
        if len(future_all) == 0:
            return np.nan
        entry = future_all.iloc[0]
    if entry == 0 or pd.isna(entry):
        return np.nan
    future = px[px.index > sig_date]
    if len(future) < n:
        return np.nan
    return (future.iloc[n - 1] - entry) / entry * 100


def outcome(ret):
    if pd.isna(ret):
        return 'BE'
    return 'WIN' if ret > WIN_THR else ('LOSS' if ret < -WIN_THR else 'BE')


# ── Core base-scan (identical to production) ──────────────────────────────────
def _base_scan(c, from_idx, thr=BASE_RANGE_MAX, max_lb=BASE_DAYS_MAX):
    hi = lo = c[from_idx]
    start = from_idx
    for i in range(from_idx - 1, max(from_idx - max_lb, 0) - 1, -1):
        nh = max(hi, c[i])
        nl = min(lo, c[i])
        if nl == 0 or (nh - nl) / nl >= thr:
            break
        hi, lo, start = nh, nl, i
    return start


def _check_base_gates(closes, volumes, bs, end_idx):
    """
    Check gates 1-3 (decline, base tightness, vol pattern) for base [bs..end_idx].
    Returns (ok, b_high, drawdown_pct, b_range_pct, base_days, base_vol_baseline)
    or (False, ...) if any gate fails.
    """
    b_days = end_idx - bs + 1
    if b_days < BASE_DAYS_MIN:
        return False, 0, 0, 0, 0, 0

    b_closes = closes[bs : end_idx + 1]
    b_high   = b_closes.max()
    b_low    = b_closes.min()
    if b_low == 0:
        return False, 0, 0, 0, 0, 0
    b_range = (b_high - b_low) / b_low
    if b_range >= BASE_RANGE_MAX:
        return False, 0, 0, 0, 0, 0

    pre = closes[max(0, bs - PRE_HIGH_BARS) : bs]
    if len(pre) < 5:
        return False, 0, 0, 0, 0, 0
    pre_high = pre.max()
    if pre_high == 0:
        return False, 0, 0, 0, 0, 0
    drawdown = (pre_high - closes[bs]) / pre_high
    if drawdown < DRAWDOWN_MIN:
        return False, 0, 0, 0, 0, 0

    # FIX 1: base-relative baseline
    half_len  = min(10, b_days // 2)
    early_bars = max(1, half_len)
    bv = volumes[bs : end_idx + 1]
    base_vol_baseline = np.median(volumes[bs : bs + early_bars])
    if base_vol_baseline <= 0:
        return False, 0, 0, 0, 0, 0

    # Gate 8: contraction
    l5v = bv[-5:]
    if len(l5v) < 5:
        return False, 0, 0, 0, 0, 0
    l5r = l5v / base_vol_baseline
    if not (l5r.mean() < CONTRACTION_MEAN and (l5r < CONTRACTION_IND).sum() >= CONTRACTION_N):
        return False, 0, 0, 0, 0, 0

    # Gate 9: prior surge
    all_br = bv / base_vol_baseline
    if (all_br > SURGE_THR).sum() < SURGE_MIN:
        return False, 0, 0, 0, 0, 0

    return True, b_high, round(drawdown * 100, 1), round(b_range * 100, 1), b_days, base_vol_baseline


def scan_symbol(sym, grp, adj_map, windows):
    """
    Scan one symbol's full history for TRIGGERED and WATCHLIST signals.
    Returns list of dicts: {type, date, sym, drawdown_pct, base_range_pct, base_days,
                             ret_Xd, ...}
    """
    grp = grp.reset_index(drop=True)
    n   = len(grp)
    if n < MIN_BARS:
        return [], []

    closes  = grp['close'].values.astype(float)
    highs   = grp['high'].values.astype(float)
    lows    = grp['low'].values.astype(float)
    volumes = grp['volume'].values.astype(float)
    dates   = grp['date'].values

    # Liquidity pre-filter: 20d avg vol must be ≥ 800k at most dates
    vol_s    = pd.Series(volumes)
    vol_ma20 = vol_s.rolling(20, min_periods=10).mean().values
    vol_ma50 = vol_s.rolling(50, min_periods=30).mean().values

    triggered_sigs = []
    watchlist_sigs = []
    triggered_dates_seen = set()   # dedup: one trigger per (sym, date)
    watchlist_streak = None        # track watchlist streaks for dedup

    for t in range(MIN_BARS, n):
        date_t = pd.Timestamp(dates[t])

        # Skip if stock doesn't meet liquidity or price floor on this date
        if vol_ma20[t] < MIN_AVG_VOL:
            continue
        if closes[t] < MIN_PRICE:
            continue

        # ── Check TRIGGERED: day t is the potential breakout day ──────────────
        if date_t >= pd.Timestamp(SIGNAL_START):
            if np.isnan(vol_ma50[t]) or vol_ma50[t] <= 0:
                pass
            else:
                prev = t - 1
                if prev >= 15:
                    bs = _base_scan(closes, prev)
                    ok, b_high, dd_pct, br_pct, b_days, bvb = _check_base_gates(
                        closes, volumes, bs, prev
                    )
                    if ok:
                        day_rng = highs[t] - lows[t]
                        vr = volumes[t] / vol_ma50[t]
                        if (
                            vr >= TRIGGER_VOL
                            and closes[t] > b_high
                            and day_rng > 0
                            and (closes[t] - lows[t]) / day_rng >= TRIGGER_RANGE
                            and date_t not in triggered_dates_seen
                        ):
                            triggered_dates_seen.add(date_t)
                            rets = {f'ret_{w}d': fwd_return(sym, date_t, adj_map, w)
                                    for w in windows}
                            triggered_sigs.append({
                                'type': 'TRIGGERED',
                                'symbol': sym,
                                'date': date_t,
                                'trigger_close': closes[t],
                                'vol_x_ma50': round(vr, 2),
                                'drawdown_pct': dd_pct,
                                'base_range_pct': br_pct,
                                'base_days': b_days,
                                **rets,
                            })

        # ── Check WATCHLIST: day t is "today" (base still forming) ───────────
        if date_t >= pd.Timestamp(SIGNAL_START):
            # Only record first day of consecutive watchlist streak (dedup)
            bs = _base_scan(closes, t)
            ok, b_high, dd_pct, br_pct, b_days, bvb = _check_base_gates(
                closes, volumes, bs, t
            )
            if ok:
                if watchlist_streak is None or (date_t - watchlist_streak).days > 5:
                    watchlist_streak = date_t
                    rets = {f'ret_{w}d': fwd_return(sym, date_t, adj_map, w)
                            for w in windows}
                    watchlist_sigs.append({
                        'type': 'WATCHLIST',
                        'symbol': sym,
                        'date': date_t,
                        'close': closes[t],
                        'base_high': round(b_high, 2),
                        'dist_to_trigger_pct': round((b_high - closes[t]) / closes[t] * 100, 1),
                        'drawdown_pct': dd_pct,
                        'base_range_pct': br_pct,
                        'base_days': b_days,
                        **rets,
                    })
                # else: same streak — skip
            else:
                watchlist_streak = None  # streak broken

    return triggered_sigs, watchlist_sigs


def stats(df, col):
    """Compute WR, LR, EV, N for one forward-return column."""
    sub = df.dropna(subset=[col])
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=0, lr=0, ev=0, freq=0)
    sub = sub.copy()
    sub['out'] = sub[col].apply(outcome)
    wins   = (sub['out'] == 'WIN').sum()
    losses = (sub['out'] == 'LOSS').sum()
    wr     = wins / n * 100
    lr     = losses / n * 100
    aw     = sub.loc[sub['out'] == 'WIN',  col].mean() if wins   else 0
    al     = sub.loc[sub['out'] == 'LOSS', col].mean() if losses else 0
    ev     = (wins / n * aw) + (losses / n * al)
    yrs    = (sub['date'].max() - sub['date'].min()).days / 365.25
    freq   = n / yrs if yrs > 0 else 0
    return dict(n=n, wr=wr, lr=lr, ev=ev, freq=freq)


def print_table(label, df, windows):
    print(f"\n  {label}")
    print(f"  {'Window':<10} {'N':>6}  {'WR':>6}  {'LR':>6}  {'EV':>7}  {'Freq/yr':>8}")
    print(f"  {'-'*50}")
    for w in windows:
        col = f'ret_{w}d'
        if col not in df.columns:
            continue
        s = stats(df, col)
        print(
            f"  @{w:<9d} {s['n']:>6}  {s['wr']:>5.1f}%  {s['lr']:>5.1f}%  "
            f"{s['ev']:>+6.2f}%  {s['freq']:>7.1f}/yr"
        )


# ── Funnel analysis ────────────────────────────────────────────────────────────
def funnel_analysis(prices_df):
    """
    Step 4: count candidates at each gate to diagnose the frequency problem.
    Runs on the full history — counts (symbol, date) pairs passing each stage.
    """
    print("\n" + "=" * 60)
    print("STEP 4 — FUNNEL ANALYSIS (gate-by-gate drop-off)")
    print("=" * 60)

    counts = {
        'universe':          0,
        'liq_filter':        0,  # vol_ma20 >= 800k AND price >= 5
        'min_bars':          0,  # >= 60 bars in history
        'base_found':        0,  # _base_scan found a base >= 8 days
        'range_pass':        0,  # base range < 20%
        'decline_pass':      0,  # prior decline >= 30%
        'vol_baseline':      0,  # baseline > 0
        'contraction_pass':  0,  # Gate 8 volume contraction
        'surge_pass':        0,  # Gate 9 prior surge (= full WATCHLIST)
        'trigger_pass':      0,  # TRIGGERED
    }

    for sym, grp in prices_df.groupby('symbol'):
        grp = grp.reset_index(drop=True)
        n   = len(grp)
        counts['universe'] += 1
        if n < MIN_BARS:
            continue
        counts['min_bars'] += 1

        closes  = grp['close'].values.astype(float)
        highs   = grp['high'].values.astype(float)
        lows    = grp['low'].values.astype(float)
        volumes = grp['volume'].values.astype(float)
        dates   = grp['date'].values

        vol_s    = pd.Series(volumes)
        vol_ma20 = vol_s.rolling(20, min_periods=10).mean().values
        vol_ma50 = vol_s.rolling(50, min_periods=30).mean().values

        sym_liq = False
        for t in range(MIN_BARS, n):
            date_t = pd.Timestamp(dates[t])
            if date_t < pd.Timestamp(SIGNAL_START):
                continue

            if vol_ma20[t] < MIN_AVG_VOL or closes[t] < MIN_PRICE:
                continue
            if not sym_liq:
                sym_liq = True
                counts['liq_filter'] += 1  # count symbol (not date)

    # Reset and do date-level counts
    date_counts = {k: 0 for k in counts if k != 'universe' and k != 'min_bars' and k != 'liq_filter'}

    for sym, grp in prices_df.groupby('symbol'):
        grp = grp.reset_index(drop=True)
        n   = len(grp)
        if n < MIN_BARS:
            continue

        closes  = grp['close'].values.astype(float)
        highs   = grp['high'].values.astype(float)
        lows    = grp['low'].values.astype(float)
        volumes = grp['volume'].values.astype(float)
        dates   = grp['date'].values

        vol_s    = pd.Series(volumes)
        vol_ma20 = vol_s.rolling(20, min_periods=10).mean().values
        vol_ma50 = vol_s.rolling(50, min_periods=30).mean().values

        for t in range(MIN_BARS, n):
            date_t = pd.Timestamp(dates[t])
            if date_t < pd.Timestamp(SIGNAL_START):
                continue
            if vol_ma20[t] < MIN_AVG_VOL or closes[t] < MIN_PRICE:
                continue

            prev = t - 1
            if prev < 15:
                continue
            bs = _base_scan(closes, prev)
            b_days = prev - bs + 1
            date_counts['base_found'] = date_counts.get('base_found', 0)

            if b_days < BASE_DAYS_MIN:
                continue
            date_counts['base_found'] = date_counts.get('base_found', 0) + 1

            b_closes = closes[bs : prev + 1]
            b_high   = b_closes.max()
            b_low    = b_closes.min()
            if b_low == 0:
                continue
            b_range = (b_high - b_low) / b_low
            if b_range >= BASE_RANGE_MAX:
                continue
            date_counts['range_pass'] = date_counts.get('range_pass', 0) + 1

            pre = closes[max(0, bs - PRE_HIGH_BARS) : bs]
            if len(pre) < 5:
                continue
            pre_high = pre.max()
            if pre_high == 0:
                continue
            drawdown = (pre_high - closes[bs]) / pre_high
            if drawdown < DRAWDOWN_MIN:
                continue
            date_counts['decline_pass'] = date_counts.get('decline_pass', 0) + 1

            half_len  = min(10, b_days // 2)
            early_bars = max(1, half_len)
            bv = volumes[bs : prev + 1]
            base_vol_baseline = np.median(volumes[bs : bs + early_bars])
            if base_vol_baseline <= 0:
                continue
            date_counts['vol_baseline'] = date_counts.get('vol_baseline', 0) + 1

            l5v = bv[-5:]
            if len(l5v) < 5:
                continue
            l5r = l5v / base_vol_baseline
            if not (l5r.mean() < CONTRACTION_MEAN and (l5r < CONTRACTION_IND).sum() >= CONTRACTION_N):
                continue
            date_counts['contraction_pass'] = date_counts.get('contraction_pass', 0) + 1

            all_br = bv / base_vol_baseline
            if (all_br > SURGE_THR).sum() < SURGE_MIN:
                continue
            date_counts['surge_pass'] = date_counts.get('surge_pass', 0) + 1

            # Check trigger on day t
            if np.isnan(vol_ma50[t]) or vol_ma50[t] <= 0:
                continue
            day_rng = highs[t] - lows[t]
            vr = volumes[t] / vol_ma50[t]
            if (
                vr >= TRIGGER_VOL
                and closes[t] > b_high
                and day_rng > 0
                and (closes[t] - lows[t]) / day_rng >= TRIGGER_RANGE
            ):
                date_counts['trigger_pass'] = date_counts.get('trigger_pass', 0) + 1

    print(f"\n  Gate                         (symbol,date) pairs")
    print(f"  {'-'*50}")
    for gate, cnt in date_counts.items():
        print(f"  {gate:<30} {cnt:>8,}")

    return date_counts


def main():
    print("=" * 60)
    print("RECOVERY BASES SCREENER — HISTORICAL AUDIT")
    print("=" * 60)

    prices_df, adj_df = load_data()

    print("\nBuilding adjusted price map...")
    adj_map = build_adj_map(adj_df)

    # Test at multiple windows
    trig_windows = [10, 20, 30, 60]
    wl_windows   = [20, 30, 60, 90]
    all_windows  = sorted(set(trig_windows + wl_windows))

    print(f"\nScanning {prices_df['symbol'].nunique()} symbols for signals...")
    print(f"Signal window: {SIGNAL_START} onwards\n")

    all_triggered = []
    all_watchlist = []
    n_sym = prices_df['symbol'].nunique()
    done  = 0

    for sym, grp in prices_df.groupby('symbol'):
        trig, wl = scan_symbol(sym, grp, adj_map, all_windows)
        all_triggered.extend(trig)
        all_watchlist.extend(wl)
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{n_sym} symbols scanned...")

    trig_df = pd.DataFrame(all_triggered) if all_triggered else pd.DataFrame()
    wl_df   = pd.DataFrame(all_watchlist) if all_watchlist else pd.DataFrame()

    if not trig_df.empty:
        trig_df['date'] = pd.to_datetime(trig_df['date'])
    if not wl_df.empty:
        wl_df['date'] = pd.to_datetime(wl_df['date'])

    print("\n" + "=" * 60)
    print("STEP 3 — BACKTEST RESULTS BY STAGE")
    print("=" * 60)

    if trig_df.empty:
        print("\n  TRIGGERED: no signals found")
    else:
        print_table("TRIGGERED (entry on breakout day close)", trig_df, trig_windows)
        yr_range = (trig_df['date'].max() - trig_df['date'].min()).days / 365.25
        print(f"\n  Triggered signals found: {len(trig_df)}  "
              f"({len(trig_df)/yr_range:.1f}/yr over {yr_range:.1f} years)")

    if wl_df.empty:
        print("\n  WATCHLIST: no signals found")
    else:
        print_table("WATCHLIST (first day of basing streak)", wl_df, wl_windows)
        yr_range_wl = (wl_df['date'].max() - wl_df['date'].min()).days / 365.25
        print(f"\n  Watchlist signals found: {len(wl_df)}  "
              f"({len(wl_df)/yr_range_wl:.1f}/yr over {yr_range_wl:.1f} years)")

    print("\n" + "=" * 60)
    print("STEP 3b — TRIGGERED signal profile (distribution of key metrics)")
    print("=" * 60)
    if not trig_df.empty:
        print(f"\n  drawdown_pct:   mean={trig_df['drawdown_pct'].mean():.0f}%  "
              f"median={trig_df['drawdown_pct'].median():.0f}%  "
              f"min={trig_df['drawdown_pct'].min():.0f}%  max={trig_df['drawdown_pct'].max():.0f}%")
        print(f"  base_range_pct: mean={trig_df['base_range_pct'].mean():.1f}%  "
              f"median={trig_df['base_range_pct'].median():.1f}%")
        print(f"  base_days:      mean={trig_df['base_days'].mean():.0f}  "
              f"median={trig_df['base_days'].median():.0f}  "
              f"min={trig_df['base_days'].min()}  max={trig_df['base_days'].max()}")
        print(f"  vol_x_ma50:     mean={trig_df['vol_x_ma50'].mean():.1f}x  "
              f"median={trig_df['vol_x_ma50'].median():.1f}x")

    # ── Step 2: window selection reasoning ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2 — WINDOW SELECTION REASONING")
    print("=" * 60)
    if not trig_df.empty:
        print("\n  Mean base duration:", round(trig_df['base_days'].mean()), "trading days")
        print("  The base formed over that many days. The breakout (trigger) is the")
        print("  entry signal. A recovery from ≥30% decline typically plays out")
        print("  over 1-3 months. Testing 10/20/30/60d to find peak EV window.")
        print("\n  EV by window (TRIGGERED):")
        for w in trig_windows:
            col = f'ret_{w}d'
            s = stats(trig_df, col)
            if s['n'] > 0:
                print(f"    @{w}d: EV={s['ev']:+.2f}%  WR={s['wr']:.1f}%  LR={s['lr']:.1f}%  N={s['n']}")
        best_w = max(trig_windows,
                     key=lambda w: stats(trig_df, f'ret_{w}d')['ev']
                     if stats(trig_df, f'ret_{w}d')['n'] > 10 else -999)
        print(f"\n  Recommended window: @{best_w}d (highest EV with N > 10)")

    # ── Step 4: funnel ─────────────────────────────────────────────────────────
    gate_counts = funnel_analysis(prices_df)

    # ── Step 5: loosening experiment if contraction or decline is the bottleneck ─
    bottleneck = None
    if gate_counts:
        ordered = ['base_found', 'range_pass', 'decline_pass', 'vol_baseline',
                   'contraction_pass', 'surge_pass']
        drops = {}
        prev_val = None
        for k in ordered:
            val = gate_counts.get(k, 0)
            if prev_val is not None and prev_val > 0:
                drops[k] = (prev_val - val) / prev_val * 100
            prev_val = val
        bottleneck = max(drops, key=drops.get) if drops else None
        print(f"\n  Biggest single drop: {bottleneck} ({drops.get(bottleneck, 0):.0f}% of candidates lost)")

    # Step 5: test loosening the bottleneck if it's decline threshold
    if bottleneck == 'decline_pass':
        print("\n" + "=" * 60)
        print("STEP 5 — VARIANT TEST: drawdown threshold 20% vs 30%")
        print("=" * 60)
        global DRAWDOWN_MIN
        DRAWDOWN_MIN_ORIG = DRAWDOWN_MIN
        DRAWDOWN_MIN = 0.20

        all_trig_loose = []
        for sym, grp in prices_df.groupby('symbol'):
            trig, _ = scan_symbol(sym, grp, adj_map, trig_windows)
            all_trig_loose.extend(trig)
        tl_df = pd.DataFrame(all_trig_loose) if all_trig_loose else pd.DataFrame()
        if not tl_df.empty:
            tl_df['date'] = pd.to_datetime(tl_df['date'])
            print_table("TRIGGERED (drawdown >= 20% variant)", tl_df, trig_windows)
            yr2 = (tl_df['date'].max() - tl_df['date'].min()).days / 365.25
            print(f"\n  N={len(tl_df)} ({len(tl_df)/yr2:.1f}/yr)")
        DRAWDOWN_MIN = DRAWDOWN_MIN_ORIG

    elif bottleneck == 'contraction_pass':
        print("\n" + "=" * 60)
        print("STEP 5 — VARIANT TEST: contraction MEAN 0.60 vs 0.50")
        print("=" * 60)
        global CONTRACTION_MEAN
        CONTRACTION_MEAN_ORIG = CONTRACTION_MEAN
        CONTRACTION_MEAN = 0.60

        all_trig_loose = []
        for sym, grp in prices_df.groupby('symbol'):
            trig, _ = scan_symbol(sym, grp, adj_map, trig_windows)
            all_trig_loose.extend(trig)
        tl_df = pd.DataFrame(all_trig_loose) if all_trig_loose else pd.DataFrame()
        if not tl_df.empty:
            tl_df['date'] = pd.to_datetime(tl_df['date'])
            print_table("TRIGGERED (contraction mean <= 60% variant)", tl_df, trig_windows)
            yr2 = (tl_df['date'].max() - tl_df['date'].min()).days / 365.25
            print(f"\n  N={len(tl_df)} ({len(tl_df)/yr2:.1f}/yr)")
        CONTRACTION_MEAN = CONTRACTION_MEAN_ORIG

    print("\n" + "=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
