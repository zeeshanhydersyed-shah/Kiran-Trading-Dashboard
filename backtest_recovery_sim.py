"""
Recovery Basis Full-History Simulation 2005-2026
PKR 100,000 starting equity

LOCKED DECISIONS (made before running):
1. Entry   : next trading day's open (EOD signal → next-open; realistic execution)
2. Stop    : 3% below the minimum CLOSE within the base (base_low * 0.97)
             Justification: base low is the structural floor of the base; 3% buffer
             prevents noise-driven stops while keeping risk well-defined.
3. Exit    : close below 21-bar EMA of closes (computed from prices_adjusted history
             available at that point in time). Check at EOD; exit at next open.
             Justification: 21-EMA is the momentum trail used throughout this dashboard.
4. Sizing  : 1% account-equity risk per trade (project standard).
             position_value = 0.01 * equity / stop_distance_pct
             shares = floor(position_value / entry_open)
5. Positions: capital-constrained only; one open position per symbol at a time.
             If cash < required position value → skip permanently.
             If symbol already has open position → skip new signal.
6. Fees    : ZERO (consistent with all prior simulations in this project).
"""

import sqlite3
import numpy as np
import pandas as pd
import sys
import re
from collections import defaultdict

sys.path.insert(0, 'C:/Users/Lenovo/psx_pipeline')
from config import EXCLUDED_SECTORS

DB_PATH        = 'C:/Users/Lenovo/psx_pipeline/psx_data.db'
INITIAL_EQUITY = 100_000.0
RISK_PER_TRADE = 0.01
STOP_BUFFER    = 0.03   # stop = base_low * (1 - STOP_BUFFER)
EMA_PERIOD     = 21

# ──────────────────────────────────────────────────────────────
# 1. Load data
# ──────────────────────────────────────────────────────────────
print("Loading prices_adjusted...")
conn = sqlite3.connect(DB_PATH)
excl = tuple(EXCLUDED_SECTORS)

rows = conn.execute(f"""
    SELECT p.symbol, s.sector, p.date,
           COALESCE(p.open, p.close) AS open,
           COALESCE(p.high, p.close) AS high,
           COALESCE(p.low,  p.close) AS low,
           p.close,
           COALESCE(p.volume, 0)     AS volume
    FROM prices_adjusted p
    JOIN sectors s ON s.symbol = p.symbol
    WHERE s.sector NOT IN ({','.join(['?']*len(excl))})
    ORDER BY p.symbol, p.date
""", list(excl)).fetchall()
conn.close()

cols = ['symbol','sector','date','open','high','low','close','volume']
all_df = pd.DataFrame(rows, columns=cols)
all_df['date'] = pd.to_datetime(all_df['date'])
for c in ('open','high','low','close'):
    all_df[c] = pd.to_numeric(all_df[c], errors='coerce')
all_df['volume'] = pd.to_numeric(all_df['volume'], errors='coerce').fillna(0)

print(f"Loaded {len(all_df):,} rows, {all_df['symbol'].nunique()} symbols")
print(f"Date range: {all_df['date'].min().date()} to {all_df['date'].max().date()}")

# ──────────────────────────────────────────────────────────────
# 2. Universe / data quality report
# ──────────────────────────────────────────────────────────────
# Apply price >= 5.0 and avg_vol_20d >= 800k — these are checked per signal date
# (not pre-filtered globally since they're rolling)

# Check open data availability
open_check = all_df.copy()
open_check['open_is_close'] = (open_check['open'] == open_check['close'])
by_year = open_check.groupby(open_check['date'].dt.year)['open_is_close'].mean()
print("\nFraction of bars where open==close (proxy for NULL open) by year:")
for yr, frac in by_year.items():
    print(f"  {yr}: {frac:.1%}")

# ──────────────────────────────────────────────────────────────
# 3. Signal generation — replicate _run_recovery_screener() exactly
# ──────────────────────────────────────────────────────────────

def _base_scan(c, from_idx, thr=0.20, max_lb=90):
    """Exact replica of signal_engine._base_scan()"""
    hi = lo = c[from_idx]
    start = from_idx
    for i in range(from_idx - 1, max(from_idx - max_lb, 0) - 1, -1):
        nh = max(hi, c[i])
        nl = min(lo, c[i])
        if (nh - nl) / nl >= thr:
            break
        hi, lo, start = nh, nl, i
    return start

print("\nGenerating Recovery Basis signals (walk-forward, no lookahead)...")

signals = []  # list of dicts: {symbol, sector, signal_date, entry_date(idx), b_low, b_high, ...}

n_sym_processed = 0
for sym, grp in all_df.groupby('symbol', sort=False):
    grp = grp.reset_index(drop=True)
    n = len(grp)
    if n < 60:
        continue

    closes  = grp['close'].values.astype(float)
    opens_  = grp['open'].values.astype(float)
    highs   = grp['high'].values.astype(float)
    lows    = grp['low'].values.astype(float)
    volumes = grp['volume'].values.astype(float)
    dates   = grp['date'].values
    sector  = grp['sector'].iloc[0]

    # Precompute rolling 50-bar volume MA (min_periods=30)
    vol_series = pd.Series(volumes)
    vol_ma50_arr = vol_series.rolling(50, min_periods=30).mean().values

    # Precompute 21-bar EMA for exit (used during simulation, stored for lookup)
    ema21_arr = vol_series.copy()  # placeholder
    ema21_arr = pd.Series(closes).ewm(span=EMA_PERIOD, adjust=False).mean().values

    # Walk forward: for each bar t (starting from bar 60 to allow warmup)
    for t in range(60, n):
        # ── Universe filters at date t ──
        avg_vol_20d = volumes[max(0, t-19):t+1].mean()
        if avg_vol_20d < 800_000:
            continue
        if closes[t] < 5.0:
            continue
        if np.isnan(vol_ma50_arr[t]) or vol_ma50_arr[t] <= 0:
            continue

        # ── Base scan on prev bar ──
        prev = t - 1
        if prev < 15:
            continue

        bs = _base_scan(closes, prev)
        b_days = prev - bs + 1
        if b_days < 8:
            continue

        b_closes = closes[bs:prev+1]
        b_high   = b_closes.max()
        b_low    = b_closes.min()
        b_range  = (b_high - b_low) / b_low
        if b_range >= 0.20:
            continue

        # Pre-base decline
        pre = closes[max(0, bs-90):bs]
        if len(pre) < 5:
            continue
        pre_high = pre.max()
        drawdown = (pre_high - closes[bs]) / pre_high
        if drawdown < 0.30:
            continue

        # Volume contraction in last 5 bars of base
        bv   = volumes[bs:prev+1]
        bm50 = vol_ma50_arr[bs:prev+1]
        l5v  = bv[-5:]
        l5m  = bm50[-5:]
        ok   = l5m > 0
        if ok.sum() < 3:
            continue
        l5r = np.where(ok, l5v / np.where(l5m > 0, l5m, 1.0), 1.0)
        if not (l5r[ok].mean() < 0.50 and (l5r[ok] < 0.60).sum() >= 3):
            continue

        # Prior volume surge within base (>=2 bars > 1.5x vol_ma50)
        all_br = np.where(bm50 > 0, bv / bm50, 0.0)
        if (all_br > 1.5).sum() < 2:
            continue

        # ── Trigger bar conditions ──
        if vol_ma50_arr[t] <= 0:
            continue
        vr      = volumes[t] / vol_ma50_arr[t]
        day_rng = highs[t] - lows[t]

        if not (
            vr >= 2.5
            and closes[t] > b_high
            and closes[t] > opens_[t]
            and day_rng > 0
            and (closes[t] - lows[t]) / day_rng >= 0.40
        ):
            continue

        # Signal fires on date t; entry is next bar's open
        if t + 1 >= n:
            continue  # no next bar to enter on

        stop_price  = b_low * (1.0 - STOP_BUFFER)
        entry_bar   = t + 1

        signals.append({
            'symbol'        : sym,
            'sector'        : sector,
            'signal_date'   : pd.Timestamp(dates[t]).date(),
            'entry_bar_idx' : entry_bar,
            'entry_date'    : pd.Timestamp(dates[entry_bar]).date(),
            'entry_open'    : opens_[entry_bar],
            'b_high'        : b_high,
            'b_low'         : b_low,
            'stop_price'    : stop_price,
            'b_days'        : b_days,
            'drawdown_pct'  : round(drawdown * 100, 1),
            'vr'            : round(vr, 2),
            # Store arrays for later use during simulation
            '_closes'   : closes,
            '_opens'    : opens_,
            '_ema21'    : ema21_arr,
            '_dates'    : dates,
        })

    n_sym_processed += 1

print(f"Processed {n_sym_processed} symbols")
print(f"Total raw signals generated: {len(signals)}")

# ──────────────────────────────────────────────────────────────
# 4. Portfolio simulation
# ──────────────────────────────────────────────────────────────
print("\nRunning portfolio simulation...")

# Sort signals by entry_date
signals.sort(key=lambda x: x['entry_date'])

# Build a lookup: entry_date → list of signals
from collections import defaultdict
import datetime

signals_by_date = defaultdict(list)
for s in signals:
    signals_by_date[s['entry_date']].append(s)

# All trading dates (sorted)
all_dates_sorted = sorted(all_df['date'].dt.date.unique())

equity         = INITIAL_EQUITY
cash           = INITIAL_EQUITY
open_positions = {}   # symbol → position dict
trades         = []   # completed trades

equity_curve   = []   # (date, equity)
peak_equity    = INITIAL_EQUITY
max_dd         = 0.0
max_dd_peak_dt = None
max_dd_trough_dt = None
max_dd_peak_eq   = INITIAL_EQUITY

n_signals_total    = 0
n_taken            = 0
n_skip_cash        = 0
n_skip_duplicate   = 0

# Build per-symbol bar index lookup for efficient access
# symbol → (closes, opens, ema21, dates) aligned arrays
sym_data = {}
for sym, grp in all_df.groupby('symbol', sort=False):
    grp = grp.reset_index(drop=True)
    closes_ = grp['close'].values.astype(float)
    opens_  = grp['open'].values.astype(float)
    ema21_  = pd.Series(closes_).ewm(span=EMA_PERIOD, adjust=False).mean().values
    dates_  = grp['date'].dt.date.values
    # date → index
    date_to_idx = {d: i for i, d in enumerate(dates_)}
    sym_data[sym] = {
        'closes'      : closes_,
        'opens'       : opens_,
        'ema21'       : ema21_,
        'dates'       : dates_,
        'date_to_idx' : date_to_idx,
    }

for current_date in all_dates_sorted:
    # ── 1. Check open positions for exit ──
    to_close = []
    for sym, pos in open_positions.items():
        sd = sym_data.get(sym)
        if sd is None:
            continue
        idx = sd['date_to_idx'].get(current_date)
        if idx is None:
            continue  # no price data for this symbol today — hold

        close_today = sd['closes'][idx]
        ema21_today = sd['ema21'][idx]

        # Exit condition: close < 21-bar EMA
        if close_today < ema21_today:
            # Find next bar's open for exit
            if idx + 1 < len(sd['dates']):
                exit_price = sd['opens'][idx + 1]
                exit_date  = sd['dates'][idx + 1]
                exit_reason = 'EMA21_TRAIL'
            else:
                # Last bar — exit at today's close
                exit_price  = close_today
                exit_date   = current_date
                exit_reason = 'END_OF_DATA'
            to_close.append((sym, exit_price, exit_date, exit_reason))

        # Stop-loss: if today's low <= stop_price (intraday stop)
        # Since we don't have reliable intraday data pre-2020, and for
        # consistency we check end-of-day: if close <= stop_price
        elif close_today <= pos['stop_price']:
            if idx + 1 < len(sd['dates']):
                exit_price  = sd['opens'][idx + 1]
                exit_date   = sd['dates'][idx + 1]
                exit_reason = 'STOP'
            else:
                exit_price  = close_today
                exit_date   = current_date
                exit_reason = 'STOP_END'
            to_close.append((sym, exit_price, exit_date, exit_reason))

    for sym, exit_price, exit_date, exit_reason in to_close:
        pos = open_positions.pop(sym)
        shares       = pos['shares']
        entry_price  = pos['entry_open']
        entry_date   = pos['entry_date']
        pl_pct       = (exit_price - entry_price) / entry_price * 100
        pl_pkr       = (exit_price - entry_price) * shares
        cash        += exit_price * shares

        trades.append({
            'symbol'      : sym,
            'entry_date'  : entry_date,
            'exit_date'   : exit_date,
            'entry_price' : round(entry_price, 2),
            'exit_price'  : round(exit_price, 2),
            'shares'      : shares,
            'pl_pct'      : round(pl_pct, 2),
            'pl_pkr'      : round(pl_pkr, 2),
            'exit_reason' : exit_reason,
            'signal_date' : pos['signal_date'],
        })

    # ── 2. Mark-to-market equity ──
    pos_value = 0.0
    for sym, pos in open_positions.items():
        sd = sym_data.get(sym)
        if sd:
            idx = sd['date_to_idx'].get(current_date)
            if idx is not None:
                pos_value += sd['closes'][idx] * pos['shares']
            else:
                pos_value += pos['entry_open'] * pos['shares']  # carry last known

    equity = cash + pos_value
    equity_curve.append((current_date, equity))

    # Drawdown tracking
    if equity > peak_equity:
        peak_equity    = equity
        max_dd_peak_dt = current_date
        max_dd_peak_eq = equity
    dd = (peak_equity - equity) / peak_equity
    if dd > max_dd:
        max_dd           = dd
        max_dd_trough_dt = current_date

    # ── 3. Enter new positions ──
    todays_signals = signals_by_date.get(current_date, [])

    for sig in todays_signals:
        n_signals_total += 1
        sym = sig['symbol']

        if sym in open_positions:
            n_skip_duplicate += 1
            continue

        entry_open  = sig['entry_open']
        stop_price  = sig['stop_price']

        if np.isnan(entry_open) or entry_open <= 0:
            n_skip_cash += 1
            continue

        stop_dist_pct = (entry_open - stop_price) / entry_open
        if stop_dist_pct <= 0:
            # stop above entry (happens if base_low > entry after gap-up)
            n_skip_cash += 1
            continue

        position_value = RISK_PER_TRADE * equity / stop_dist_pct
        shares = int(position_value / entry_open)
        if shares < 1:
            n_skip_cash += 1
            continue

        cost = shares * entry_open
        if cost > cash:
            n_skip_cash += 1
            continue

        cash -= cost
        n_taken += 1
        open_positions[sym] = {
            'shares'      : shares,
            'entry_open'  : entry_open,
            'entry_date'  : current_date,
            'stop_price'  : stop_price,
            'signal_date' : sig['signal_date'],
        }

# ── Force-close remaining open positions at last available close ──
final_date = all_dates_sorted[-1]
for sym, pos in list(open_positions.items()):
    sd = sym_data.get(sym)
    exit_price = pos['entry_open']
    exit_date  = final_date
    if sd:
        last_idx = sd['date_to_idx'].get(final_date)
        if last_idx is None and len(sd['dates']) > 0:
            last_idx = len(sd['dates']) - 1
        if last_idx is not None:
            exit_price = sd['closes'][last_idx]
            exit_date  = sd['dates'][last_idx]

    shares      = pos['shares']
    entry_price = pos['entry_open']
    pl_pct      = (exit_price - entry_price) / entry_price * 100
    pl_pkr      = (exit_price - entry_price) * shares
    cash       += exit_price * shares

    trades.append({
        'symbol'      : sym,
        'entry_date'  : pos['entry_date'],
        'exit_date'   : exit_date,
        'entry_price' : round(entry_price, 2),
        'exit_price'  : round(exit_price, 2),
        'shares'      : shares,
        'pl_pct'      : round(pl_pct, 2),
        'pl_pkr'      : round(pl_pkr, 2),
        'exit_reason' : 'FORCE_CLOSE',
        'signal_date' : pos['signal_date'],
    })

equity = cash  # all positions closed

# ──────────────────────────────────────────────────────────────
# 5. Results
# ──────────────────────────────────────────────────────────────
trades_df = pd.DataFrame(trades)
eq_df     = pd.DataFrame(equity_curve, columns=['date','equity'])
eq_df['date'] = pd.to_datetime(eq_df['date'])

start_date = all_dates_sorted[0]
end_date   = all_dates_sorted[-1]
years = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days / 365.25
cagr  = (equity / INITIAL_EQUITY) ** (1 / years) - 1

print("\n" + "="*70)
print("RECOVERY BASIS SIMULATION RESULTS — 2005 to 2026")
print("="*70)

print(f"\nStart date : {start_date}")
print(f"End date   : {end_date}")
print(f"Years      : {years:.1f}")
print(f"\nStarting equity : PKR {INITIAL_EQUITY:,.0f}")
print(f"Final equity    : PKR {equity:,.0f}")
print(f"Overall CAGR    : {cagr:.1%}")

print(f"\nTotal signals generated    : {n_signals_total}")
print(f"Trades taken               : {n_taken}")
print(f"Skipped — insufficient cash: {n_skip_cash}")
print(f"Skipped — duplicate symbol : {n_skip_duplicate}")

if len(trades_df) > 0:
    wins   = trades_df[trades_df['pl_pct'] > 0]
    losses = trades_df[trades_df['pl_pct'] <= 0]
    wr     = len(wins) / len(trades_df) * 100
    avg_w  = wins['pl_pct'].mean()   if len(wins)   > 0 else 0
    avg_l  = losses['pl_pct'].mean() if len(losses) > 0 else 0
    expct  = (len(wins)/len(trades_df)) * avg_w + (len(losses)/len(trades_df)) * avg_l

    print(f"\nTotal trades closed        : {len(trades_df)}")
    print(f"Win rate                   : {wr:.1f}%")
    print(f"Average win                : {avg_w:.1f}%")
    print(f"Average loss               : {avg_l:.1f}%")
    print(f"Expectancy                 : {expct:.2f}%")

print(f"\nMax drawdown               : {max_dd:.1%}")
print(f"  Peak date                : {max_dd_peak_dt}")
print(f"  Trough date              : {max_dd_trough_dt}")

# Exit reason breakdown
if len(trades_df) > 0:
    print("\nExit reason breakdown:")
    for reason, cnt in trades_df['exit_reason'].value_counts().items():
        print(f"  {reason}: {cnt} ({cnt/len(trades_df)*100:.1f}%)")

# Year-by-year equity curve
print("\nYear-by-year equity curve:")
print(f"{'Year':<6} {'Start Equity':>14} {'End Equity':>14} {'Return':>10}")
print("-" * 48)
eq_df['year'] = eq_df['date'].dt.year
for yr in sorted(eq_df['year'].unique()):
    yr_df = eq_df[eq_df['year'] == yr]
    s_eq  = yr_df['equity'].iloc[0]
    e_eq  = yr_df['equity'].iloc[-1]
    ret   = (e_eq - s_eq) / s_eq * 100
    print(f"{yr:<6} {s_eq:>14,.0f} {e_eq:>14,.0f} {ret:>9.1f}%")

# Unique symbols ever eligible
n_eligible_syms = all_df['symbol'].nunique()
print(f"\nUnique symbols ever eligible : {n_eligible_syms}")

# Signal count by year
if len(trades_df) > 0:
    trades_df['entry_year'] = pd.to_datetime(trades_df['entry_date']).dt.year
    print("\nTrades by year:")
    by_yr = trades_df.groupby('entry_year').agg(
        count=('symbol','count'),
        win_rate=('pl_pct', lambda x: (x>0).mean()*100),
        avg_pl=('pl_pct','mean')
    )
    for yr, row in by_yr.iterrows():
        print(f"  {yr}: {int(row['count'])} trades, {row['win_rate']:.0f}% WR, avg {row['avg_pl']:+.1f}%")

    # All individual trades
    print("\nAll trades (entry_date, symbol, entry, exit, pl_pct, exit_reason):")
    for _, r in trades_df.sort_values('entry_date').iterrows():
        print(f"  {r['entry_date']}  {r['symbol']:<8} entry={r['entry_price']:>8.2f}  "
              f"exit={r['exit_price']:>8.2f}  {r['pl_pct']:>+7.1f}%  [{r['exit_reason']}]  "
              f"exit={r['exit_date']}")
