"""
Recovery Basis Full-History Simulation v2 — 2005 to 2026
=========================================================
Implements three fixes vs the original backtest:

  Fix 1  Gate 8 & 9 denominator changed from vol_ma50 to base_vol_baseline
         (median of first half, capped at 10 bars, of the base itself).
  Fix 2  Green-candle condition (close > open) removed from Gate 10.
         Replaced by the two open-agnostic conditions already present:
         close > base_high  AND  close in upper 40% of day's range.
  Fix 3  Entry changed from "next-day open" (NULL by design in this DB)
         to a stop-order fill rule:
           - On trigger day T, record trigger_high = highs[T].
           - On day T+1 ONLY: if T+1's high >= trigger_high → fill at
             trigger_high exactly.  If not → discard permanently.
           - Same-day stop: if fill occurs on T+1 AND closes[T+1] <=
             stop_price → stopped same-day at stop_price.
           - Trail-exit from T+2 onward: close < 21-bar EMA → exit at
             next day's CLOSE (open is NULL throughout this dataset).

Unchanged from prior backtest
  Stop price   : base_low * 0.97
  Position size: 1% equity risk  (= 0.01 * equity / stop_dist_pct)
  Concurrent   : capital-constrained only; one position per symbol;
                 skip permanently if cash insufficient
  Fees/tax/slip: zero
"""

import sqlite3, numpy as np, pandas as pd, sys, re
from collections import defaultdict

sys.path.insert(0, 'C:/Users/Lenovo/psx_pipeline')
from config import EXCLUDED_SECTORS

DB_PATH        = 'C:/Users/Lenovo/psx_pipeline/psx_data.db'
INITIAL_EQUITY = 100_000.0
RISK_PER_TRADE = 0.01
STOP_BUFFER    = 0.03   # stop = base_low * (1 - STOP_BUFFER)
EMA_SPAN       = 21

# ──────────────────────────────────────────────────────────────
# 1. Load prices_adjusted for the eligible universe
# ──────────────────────────────────────────────────────────────
print("Loading prices_adjusted ...")
conn = sqlite3.connect(DB_PATH)
excl = tuple(EXCLUDED_SECTORS)

rows = conn.execute(f"""
    SELECT p.symbol, s.sector, p.date,
           COALESCE(p.open,   p.close) AS open,
           COALESCE(p.high,   p.close) AS high,
           COALESCE(p.low,    p.close) AS low,
           p.close,
           COALESCE(p.volume, 0)       AS volume
    FROM prices_adjusted p
    JOIN sectors s ON s.symbol = p.symbol
    WHERE s.sector NOT IN ({','.join(['?']*len(excl))})
    ORDER BY p.symbol, p.date
""", list(excl)).fetchall()
conn.close()

cols   = ['symbol','sector','date','open','high','low','close','volume']
all_df = pd.DataFrame(rows, columns=cols)
all_df['date'] = pd.to_datetime(all_df['date'])
for c in ('open','high','low','close'):
    all_df[c] = pd.to_numeric(all_df[c], errors='coerce')
all_df['volume'] = pd.to_numeric(all_df['volume'], errors='coerce').fillna(0)

# Pattern filter (P\d) — applied here, not via DB
mask_pdigt = all_df['symbol'].str.match(r'^P\d', na=False)
all_df     = all_df[~mask_pdigt].copy()

print(f"Loaded {len(all_df):,} rows, {all_df['symbol'].nunique()} symbols, "
      f"{all_df['date'].min().date()} to {all_df['date'].max().date()}")

# ──────────────────────────────────────────────────────────────
# 2. Helper: _base_scan (exact replica of signal_engine.py)
# ──────────────────────────────────────────────────────────────
def _base_scan(c, from_idx, thr=0.20, max_lb=90):
    hi = lo = c[from_idx]
    start   = from_idx
    for i in range(from_idx - 1, max(from_idx - max_lb, 0) - 1, -1):
        nh = max(hi, c[i])
        nl = min(lo, c[i])
        if (nh - nl) / nl >= thr:
            break
        hi, lo, start = nh, nl, i
    return start

# ──────────────────────────────────────────────────────────────
# 3. SANITY CHECK — 4 known cases from prior diagnostic
# ──────────────────────────────────────────────────────────────
print("\n" + "="*68)
print("SECTION 1: SANITY CHECK — 4 KNOWN CASES (post-fix)")
print("="*68)

SANITY_CASES = [
    ('TRG',   '2026-04-02'),
    ('DCL',   '2026-04-08'),
    ('TPLP',  '2026-04-08'),
    ('PIBTL', '2026-04-08'),
    ('PIBTL', '2026-04-10'),
]

for sym, trig_date_str in SANITY_CASES:
    print(f"\n--- {sym}  |  {trig_date_str} ---")
    grp = all_df[(all_df['symbol'] == sym) &
                 (all_df['date'] <= trig_date_str)].sort_values('date').reset_index(drop=True)
    if len(grp) == 0:
        print("  NO DATA"); continue

    n       = len(grp)
    closes  = grp['close'].values.astype(float)
    opens_  = grp['open'].values.astype(float)
    highs   = grp['high'].values.astype(float)
    lows    = grp['low'].values.astype(float)
    volumes = grp['volume'].values.astype(float)
    dates   = grp['date'].values

    vol_ma50_arr = pd.Series(volumes).rolling(50, min_periods=30).mean().values

    t    = n - 1
    prev = t - 1

    # Gates 1-7 (unchanged)
    avg_vol_20d = volumes[max(0, t-19):t+1].mean()
    g1 = avg_vol_20d >= 800_000
    g2 = closes[t] >= 5.0
    g3 = n >= 60
    g4 = not (np.isnan(vol_ma50_arr[t]) or vol_ma50_arr[t] <= 0)
    g5 = prev >= 15
    if not all([g1,g2,g3,g4,g5]):
        print(f"  Early gates fail: G1={g1} G2={g2} G3={g3} G4={g4} G5={g5}"); continue

    bs       = _base_scan(closes, prev)
    b_days   = prev - bs + 1
    b_closes = closes[bs:prev+1]
    b_high   = b_closes.max()
    b_low    = b_closes.min()
    b_range  = (b_high - b_low) / b_low
    g6a = b_days >= 8
    g6b = b_range < 0.20
    pre = closes[max(0, bs-90):bs]
    g7a = len(pre) >= 5
    drawdown = (pre.max() - closes[bs]) / pre.max() if g7a else 0
    g7b = drawdown >= 0.30
    if not all([g6a,g6b,g7a,g7b]):
        print(f"  G6/G7 fail: b_days={b_days} b_range={b_range*100:.1f}% dd={drawdown*100:.1f}%"); continue

    print(f"  G1-G7: all PASS  |  base {pd.Timestamp(dates[bs]).date()} to "
          f"{pd.Timestamp(dates[prev]).date()}, {b_days} bars, b_high={b_high:.2f}, b_low={b_low:.2f}")

    # Fix 1: Gate 8 & 9 with base_vol_baseline
    bv         = volumes[bs:prev+1]
    half_len   = min(10, b_days // 2)
    early_bars = max(1, half_len)
    bvb        = np.median(volumes[bs:bs+early_bars])
    low_conf   = early_bars < 4
    print(f"  base_vol_baseline={bvb:,.0f} (median of first {early_bars} bars) low_conf={low_conf}")

    l5v  = bv[-5:]
    l5r  = l5v / bvb
    mean_r  = l5r.mean()
    blow60  = (l5r < 0.60).sum()
    g8b = mean_r < 0.50
    g8c = blow60 >= 3
    g8  = g8b and g8c
    print(f"  G8 (contraction): mean_ratio={mean_r:.4f} (need<0.50)={'PASS' if g8b else 'FAIL'}, "
          f"count<0.60={blow60} (need>=3)={'PASS' if g8c else 'FAIL'}  =>  G8={'PASS' if g8 else 'FAIL'}")

    all_br  = bv / bvb
    surge_n = (all_br > 1.5).sum()
    g9      = surge_n >= 2
    print(f"  G9 (prior surge): bars>1.5x={surge_n} (need>=2)  =>  G9={'PASS' if g9 else 'FAIL'}")

    if not (g8 and g9):
        print("  Gate 10 not evaluated (G8 or G9 failed)"); continue

    # Fix 2: Gate 10 without green-candle
    vm50_t    = vol_ma50_arr[t]
    vr_t      = volumes[t] / vm50_t if vm50_t > 0 else float('nan')
    day_rng   = highs[t] - lows[t]
    close_pos = (closes[t] - lows[t]) / day_rng if day_rng > 0 else float('nan')
    g10a = vr_t >= 2.5
    g10b = closes[t] > b_high
    g10c = day_rng > 0
    g10d = (not np.isnan(close_pos)) and close_pos >= 0.40
    g10  = g10a and g10b and g10c and g10d
    print(f"  G10 (trigger): vr={vr_t:.2f}(≥2.5)={'P' if g10a else 'F'}, "
          f"close>b_high={'P' if g10b else 'F'}, rng>0={'P' if g10c else 'F'}, "
          f"close_pos={close_pos:.2f}(≥0.40)={'P' if g10d else 'F'}  =>  "
          f"G10={'*** SIGNAL FIRES ***' if g10 else 'FAIL'}")

# ──────────────────────────────────────────────────────────────
# 4. SIGNAL GENERATION — walk-forward, all history
# ──────────────────────────────────────────────────────────────
print("\n" + "="*68)
print("SECTION 2: SIGNAL GENERATION (walk-forward 2005-2026)")
print("="*68)
print("Running gate-pass funnel across all symbols and all dates ...")

# Funnel counters
cnt = {
    'total_bars'    : 0,
    'pass_liquidity': 0,
    'pass_vol_ma50' : 0,
    'pass_b_days'   : 0,
    'pass_drawdown' : 0,
    'pass_g8'       : 0,
    'pass_g9'       : 0,
    'pass_g10'      : 0,   # = raw TRIGGERED signals
}

signals = []   # list of signal dicts

n_sym = 0
for sym, grp in all_df.groupby('symbol', sort=False):
    grp = grp.sort_values('date').reset_index(drop=True)
    n   = len(grp)
    if n < 60:
        continue

    closes  = grp['close'].values.astype(float)
    highs_s = grp['high'].values.astype(float)
    lows_s  = grp['low'].values.astype(float)
    volumes = grp['volume'].values.astype(float)
    dates   = grp['date'].dt.date.values
    sector  = grp['sector'].iloc[0]

    # vol_ma50 still needed for Gate 10 trigger-bar vr
    vol_ma50_arr = pd.Series(volumes).rolling(50, min_periods=30).mean().values
    # EMA21 for exits (precomputed)
    ema21_arr    = pd.Series(closes).ewm(span=EMA_SPAN, adjust=False).mean().values

    for t in range(60, n):
        # ── Basic filters ──────────────────────────
        cnt['total_bars'] += 1
        avg_vol_20d = volumes[max(0, t-19):t+1].mean()
        if avg_vol_20d < 800_000 or closes[t] < 5.0:
            continue
        cnt['pass_liquidity'] += 1

        if np.isnan(vol_ma50_arr[t]) or vol_ma50_arr[t] <= 0:
            continue
        cnt['pass_vol_ma50'] += 1

        prev = t - 1
        if prev < 15:
            continue

        # ── Base detection ─────────────────────────
        bs     = _base_scan(closes, prev)
        b_days = prev - bs + 1
        if b_days < 8:
            continue
        b_closes = closes[bs:prev+1]
        b_high   = b_closes.max()
        b_low    = b_closes.min()
        b_range  = (b_high - b_low) / b_low
        if b_range >= 0.20:
            continue
        cnt['pass_b_days'] += 1

        # ── Pre-base decline ────────────────────────
        pre = closes[max(0, bs-90):bs]
        if len(pre) < 5:
            continue
        pre_high = pre.max()
        drawdown = (pre_high - closes[bs]) / pre_high
        if drawdown < 0.30:
            continue
        cnt['pass_drawdown'] += 1

        # ── FIX 1: base_vol_baseline ────────────────
        bv         = volumes[bs:prev+1]
        half_len   = min(10, b_days // 2)
        early_bars = max(1, half_len)
        bvb        = np.median(volumes[bs:bs+early_bars])
        if bvb <= 0:
            continue

        # Gate 8: contraction in last 5 base bars
        l5v = bv[-5:]
        l5r = l5v / bvb
        if not (l5r.mean() < 0.50 and (l5r < 0.60).sum() >= 3):
            continue
        cnt['pass_g8'] += 1

        # Gate 9: prior surge within base
        all_br = bv / bvb
        if (all_br > 1.5).sum() < 2:
            continue
        cnt['pass_g9'] += 1

        # ── FIX 2: Gate 10 (no green-candle) ────────
        if vol_ma50_arr[t] <= 0:
            continue
        vr_t    = volumes[t] / vol_ma50_arr[t]
        day_rng = highs_s[t] - lows_s[t]
        if not (
            vr_t >= 2.5
            and closes[t] > b_high
            and day_rng > 0
            and (closes[t] - lows_s[t]) / day_rng >= 0.40
        ):
            continue
        cnt['pass_g10'] += 1

        # ── FIX 3: record trigger_high for stop-order entry ──
        if t + 1 >= n:
            continue   # no next bar to attempt fill on

        signals.append({
            'symbol'       : sym,
            'sector'       : sector,
            'signal_date'  : dates[t],
            'attempt_date' : dates[t+1],
            'trigger_high' : float(highs_s[t]),
            'b_high'       : round(b_high, 4),
            'b_low'        : round(b_low,  4),
            'stop_price'   : round(b_low * (1.0 - STOP_BUFFER), 4),
            'b_days'       : b_days,
            'drawdown_pct' : round(drawdown * 100, 1),
            'vr'           : round(vr_t, 2),
            # arrays for later use in sim
            '_dates'       : dates,
            '_closes'      : closes,
            '_highs'       : highs_s,
            '_lows'        : lows_s,
            '_ema21'       : ema21_arr,
            '_n'           : n,
            '_t'           : t,
        })

    n_sym += 1

raw_signals = len(signals)

# ── Gate-pass funnel ───────────────────────────────────────────
print("\nGATE-PASS FUNNEL (2005-2026, all eligible symbols):")
print(f"{'Gate':<38} {'Bars':>9}  {'Elim %':>8}")
print("-" * 60)

prev_n = cnt['total_bars']
labels = [
    ('total_bars',     'Eligible bars (n≥60, sector, P\\d filter)'),
    ('pass_liquidity', 'Pass liquidity (avg_vol20d≥800K, close≥5)'),
    ('pass_vol_ma50',  'Pass vol_ma50 validity (for G10 trigger vr)'),
    ('pass_b_days',    'Pass base detection (≥8 bars, range<20%)'),
    ('pass_drawdown',  'Pass drawdown ≥30% from pre-base high'),
    ('pass_g8',        'Pass Gate 8 (vol contraction, base-relative)'),
    ('pass_g9',        'Pass Gate 9 (prior surge, base-relative)'),
    ('pass_g10',       'Pass Gate 10 = raw TRIGGERED signals'),
]
for key, label in labels:
    n_now = cnt[key]
    if key == 'total_bars':
        elim_pct = 0.0
    else:
        elim_pct = (1 - n_now / prev_n) * 100 if prev_n > 0 else 0
    print(f"  {label:<36} {n_now:>9,}  {elim_pct:>7.1f}%")
    prev_n = n_now

print(f"\nRaw TRIGGERED signals generated: {raw_signals}")
print(f"(Note: raw_signals may differ slightly from pass_g10 because")
print(f" signals without a T+1 bar are excluded; same-date signals on")
print(f" same symbol are ALL retained here — portfolio sim will de-dup)")

# ──────────────────────────────────────────────────────────────
# 5. PORTFOLIO SIMULATION (Fix 3 entry mechanics)
# ──────────────────────────────────────────────────────────────
print("\n" + "="*68)
print("SECTION 3: PORTFOLIO SIMULATION")
print("="*68)

# Sort signals by attempt_date, then by signal_date
signals.sort(key=lambda x: (x['attempt_date'], x['signal_date']))

# Build lookup: attempt_date → list of signals
sigs_by_attempt = defaultdict(list)
for s in signals:
    sigs_by_attempt[s['attempt_date']].append(s)

# All trading dates (unique, sorted)
all_dates = sorted(all_df['date'].dt.date.unique())

# Per-symbol quick-access arrays
sym_data = {}
for sym, grp in all_df.groupby('symbol', sort=False):
    grp = grp.sort_values('date').reset_index(drop=True)
    d   = grp['date'].dt.date.values
    c   = grp['close'].values.astype(float)
    h   = grp['high'].values.astype(float)
    lo  = grp['low'].values.astype(float)
    e21 = pd.Series(c).ewm(span=EMA_SPAN, adjust=False).mean().values
    dti = {dt: i for i, dt in enumerate(d)}
    sym_data[sym] = {'dates':d,'closes':c,'highs':h,'lows':lo,'ema21':e21,'dti':dti}

equity = INITIAL_EQUITY
cash   = INITIAL_EQUITY
open_positions = {}   # sym → position dict
trades         = []   # completed trades

equity_curve = []
peak_eq      = INITIAL_EQUITY
max_dd       = 0.0
max_dd_pk_dt = None
max_dd_tr_dt = None

# Counters for Fix 3 fill/discard tracking
n_signals_attempted = 0
n_filled            = 0
n_discarded         = 0
n_same_day_stop     = 0
n_skip_cash         = 0
n_skip_dup          = 0

# Track which pending signals were added for attempted fill today
# (signals are keyed by attempt_date in sigs_by_attempt)

for current_date in all_dates:

    # ── A. Check open positions for EXITS (EOD of current_date) ──
    # Hard stop: close <= stop_price → exit at next close
    # Trail-exit: close < EMA21     → exit at next close
    to_close = []
    for sym, pos in open_positions.items():
        sd  = sym_data.get(sym)
        if sd is None: continue
        idx = sd['dti'].get(current_date)
        if idx is None: continue

        close_today = sd['closes'][idx]
        ema21_today = sd['ema21'][idx]

        # Trail exit (checked first; stop also flagged)
        if close_today < ema21_today:
            exit_reason = 'TRAIL_EXIT'
        elif close_today <= pos['stop_price']:
            exit_reason = 'STOP'
        else:
            continue   # hold

        # Exit price = NEXT day's close
        if idx + 1 < len(sd['dates']):
            exit_price = sd['closes'][idx + 1]
            exit_date  = sd['dates'][idx + 1]
        else:
            exit_price = close_today   # last bar — use EOD close
            exit_date  = current_date
            exit_reason += '_EOD'

        to_close.append((sym, exit_price, exit_date, exit_reason))

    for sym, exit_price, exit_date, exit_reason in to_close:
        pos   = open_positions.pop(sym)
        sh    = pos['shares']
        ep    = pos['entry_price']
        pl    = (exit_price - ep) * sh
        cash += exit_price * sh
        trades.append({
            'symbol'      : sym,
            'entry_date'  : pos['entry_date'],
            'exit_date'   : exit_date,
            'entry_price' : round(ep, 4),
            'exit_price'  : round(exit_price, 4),
            'shares'      : sh,
            'pl_pct'      : round((exit_price - ep) / ep * 100, 2),
            'pl_pkr'      : round(pl, 2),
            'exit_reason' : exit_reason,
            'signal_date' : pos['signal_date'],
        })

    # ── B. Mark-to-market equity ─────────────────────────────────
    pos_val = sum(
        sd['closes'][sd['dti'][current_date]] * p['shares']
        if (sd := sym_data.get(sym)) and current_date in sd['dti'] else p['entry_price'] * p['shares']
        for sym, p in open_positions.items()
    )
    equity = cash + pos_val
    equity_curve.append((current_date, equity))

    if equity > peak_eq:
        peak_eq      = equity
        max_dd_pk_dt = current_date
    dd = (peak_eq - equity) / peak_eq
    if dd > max_dd:
        max_dd       = dd
        max_dd_tr_dt = current_date

    # ── C. FIX 3: Attempt fills for signals with attempt_date=today ──
    todays_sigs = sigs_by_attempt.get(current_date, [])
    for sig in todays_sigs:
        sym = sig['symbol']
        n_signals_attempted += 1

        # Get today's data for the symbol
        sd  = sym_data.get(sym)
        if sd is None:
            n_discarded += 1; continue
        idx = sd['dti'].get(current_date)
        if idx is None:
            n_discarded += 1; continue

        high_today = sd['highs'][idx]
        trigger_h  = sig['trigger_high']

        # Fix 3: fill only if today's high reaches trigger_high
        if high_today < trigger_h:
            n_discarded += 1
            continue

        n_filled += 1
        entry_price = trigger_h
        stop_price  = sig['stop_price']

        # Skip duplicate position (already holding this symbol)
        if sym in open_positions:
            n_skip_dup += 1
            n_filled   -= 1   # not really filled — was blocked
            n_discarded += 1
            continue

        # Position sizing
        stop_dist_pct = (entry_price - stop_price) / entry_price
        if stop_dist_pct <= 0:
            n_skip_cash += 1; continue

        pos_val_req = RISK_PER_TRADE * equity / stop_dist_pct
        shares      = int(pos_val_req / entry_price)
        if shares < 1:
            n_skip_cash += 1; continue

        cost = shares * entry_price
        if cost > cash:
            n_skip_cash += 1; continue

        # Check same-day stop (Fix 3)
        close_today = sd['closes'][idx]
        if close_today <= stop_price:
            # Stopped same-day — never actually opens as a live position
            n_same_day_stop += 1
            pl   = (stop_price - entry_price) * shares
            # Note: no cash actually moved since the fill and stop are
            # treated as simultaneous for accounting purposes
            trades.append({
                'symbol'      : sym,
                'entry_date'  : current_date,
                'exit_date'   : current_date,
                'entry_price' : round(entry_price, 4),
                'exit_price'  : round(stop_price, 4),
                'shares'      : shares,
                'pl_pct'      : round((stop_price - entry_price) / entry_price * 100, 2),
                'pl_pkr'      : round(pl, 2),
                'exit_reason' : 'STOP_SAME_DAY',
                'signal_date' : sig['signal_date'],
            })
            continue

        # Normal fill — open position
        cash -= cost
        open_positions[sym] = {
            'shares'      : shares,
            'entry_price' : entry_price,
            'entry_date'  : current_date,
            'stop_price'  : stop_price,
            'signal_date' : sig['signal_date'],
        }

# ── Force-close remaining open positions at last available close ──
final_date = all_dates[-1]
for sym, pos in list(open_positions.items()):
    sd = sym_data.get(sym)
    ep = pos['entry_price']
    exit_price = ep
    if sd:
        last_idx   = len(sd['dates']) - 1
        exit_price = sd['closes'][last_idx]
    cash += exit_price * pos['shares']
    trades.append({
        'symbol'      : sym,
        'entry_date'  : pos['entry_date'],
        'exit_date'   : final_date,
        'entry_price' : round(ep, 4),
        'exit_price'  : round(exit_price, 4),
        'shares'      : pos['shares'],
        'pl_pct'      : round((exit_price - ep) / ep * 100, 2),
        'pl_pkr'      : round((exit_price - ep) * pos['shares'], 2),
        'exit_reason' : 'FORCE_CLOSE',
        'signal_date' : pos['signal_date'],
    })
equity = cash

# ──────────────────────────────────────────────────────────────
# 6. RESULTS
# ──────────────────────────────────────────────────────────────
trades_df = pd.DataFrame(trades)
eq_df     = pd.DataFrame(equity_curve, columns=['date','equity'])
eq_df['date'] = pd.to_datetime(eq_df['date'])

years = (pd.Timestamp(all_dates[-1]) - pd.Timestamp(all_dates[0])).days / 365.25
cagr  = (equity / INITIAL_EQUITY) ** (1 / years) - 1

DIV = "=" * 68
print(f"\n{DIV}")
print("GATE-PASS FUNNEL SUMMARY (comparison to prior run)")
print(DIV)
print(f"  Prior backtest TRIGGERED signals : 3")
print(f"  This backtest TRIGGERED signals  : {cnt['pass_g10']}")
print(f"  Change                           : {cnt['pass_g10'] - 3:+d}")

print(f"\n{DIV}")
print("SIGNAL & FILL STATISTICS (Fix 3 entry mechanics)")
print(DIV)
print(f"  Raw TRIGGERED signals generated  : {raw_signals}")
print(f"  Signals attempted on T+1         : {n_signals_attempted}")
print(f"  Filled (T+1 high >= trigger_high): {n_filled}")
print(f"    Of which: same-day stop on fill: {n_same_day_stop}")
print(f"    Of which: survived to normal   : {n_filled - n_same_day_stop}")
print(f"  Discarded (T+1 high < trigger_h) : {n_discarded}")
print(f"  Skipped — insufficient cash      : {n_skip_cash}")
print(f"  Skipped — duplicate symbol       : {n_skip_dup}")

print(f"\n{DIV}")
print(f"PERFORMANCE SUMMARY")
print(DIV)
print(f"  Start date     : {all_dates[0]}")
print(f"  End date       : {all_dates[-1]}")
print(f"  Years          : {years:.1f}")
print(f"  Starting equity: PKR {INITIAL_EQUITY:>12,.0f}")
print(f"  Final equity   : PKR {equity:>12,.0f}")
print(f"  Overall CAGR   : {cagr:.2%}")

if len(trades_df) > 0:
    wins   = trades_df[trades_df['pl_pct'] > 0]
    losses = trades_df[trades_df['pl_pct'] <= 0]
    wr     = len(wins) / len(trades_df) * 100
    avg_w  = wins['pl_pct'].mean()   if len(wins)   > 0 else 0.0
    avg_l  = losses['pl_pct'].mean() if len(losses) > 0 else 0.0
    expct  = (len(wins)/len(trades_df)) * avg_w + (len(losses)/len(trades_df)) * avg_l

    print(f"\n  Total trades closed  : {len(trades_df)}")
    print(f"  Win rate             : {wr:.1f}%")
    print(f"  Avg win              : {avg_w:.2f}%")
    print(f"  Avg loss             : {avg_l:.2f}%")
    print(f"  Expectancy           : {expct:.2f}% per trade")
    print(f"\n  Max drawdown         : {max_dd:.2%}")
    print(f"    Peak date          : {max_dd_pk_dt}")
    print(f"    Trough date        : {max_dd_tr_dt}")

    print(f"\n  Exit reason breakdown:")
    for reason, cnt_r in trades_df['exit_reason'].value_counts().items():
        print(f"    {reason:<22}: {cnt_r:>4}  ({cnt_r/len(trades_df)*100:.1f}%)")

# Year-by-year equity curve
print(f"\n{DIV}")
print("YEAR-BY-YEAR EQUITY CURVE")
print(DIV)
eq_df['year'] = eq_df['date'].dt.year
print(f"  {'Year':<6} {'Start Equity':>14} {'End Equity':>14} {'Return':>9}")
print(f"  {'-'*46}")
for yr in sorted(eq_df['year'].unique()):
    yr_rows = eq_df[eq_df['year'] == yr]
    s_eq    = yr_rows['equity'].iloc[0]
    e_eq    = yr_rows['equity'].iloc[-1]
    ret     = (e_eq - s_eq) / s_eq * 100
    print(f"  {yr:<6} {s_eq:>14,.0f} {e_eq:>14,.0f} {ret:>8.1f}%")

# Trade-by-trade log
if len(trades_df) > 0:
    print(f"\n{DIV}")
    print("ALL TRADES")
    print(DIV)
    print(f"  {'Entry':>12} {'Sym':<8} {'Exit':>12}  "
          f"{'Entry_P':>8} {'Exit_P':>8} {'PL%':>7}  Reason")
    print(f"  {'-'*74}")
    for _, r in trades_df.sort_values('entry_date').iterrows():
        print(f"  {str(r['entry_date']):>12} {r['symbol']:<8} {str(r['exit_date']):>12}  "
              f"{r['entry_price']:>8.2f} {r['exit_price']:>8.2f} {r['pl_pct']:>+7.2f}%  "
              f"{r['exit_reason']}")

print(f"\n{DIV}")
print(f"Unique symbols ever eligible: {all_df['symbol'].nunique()}")
print("Done.")
