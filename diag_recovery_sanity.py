"""
Sanity check: gates 8, 9, 10 (post-fix) for the 4 known real cases.
Reports PASS/FAIL with actual computed numbers.
"""
import sqlite3, numpy as np, pandas as pd, sys, re
sys.path.insert(0, 'C:/Users/Lenovo/psx_pipeline')
from config import EXCLUDED_SECTORS

DB_PATH = 'C:/Users/Lenovo/psx_pipeline/psx_data.db'
conn    = sqlite3.connect(DB_PATH)

CASES = [
    ('TRG',   '2026-04-02'),
    ('DCL',   '2026-04-08'),
    ('TPLP',  '2026-04-08'),
    ('PIBTL', '2026-04-08'),
    ('PIBTL', '2026-04-10'),
]

def _base_scan(c, from_idx, thr=0.20, max_lb=90):
    hi = lo = c[from_idx]
    start = from_idx
    for i in range(from_idx - 1, max(from_idx - max_lb, 0) - 1, -1):
        nh = max(hi, c[i])
        nl = min(lo, c[i])
        if (nh - nl) / nl >= thr:
            break
        hi, lo, start = nh, nl, i
    return start

DIV = '=' * 68

for sym, trig_date_str in CASES:
    print(f'\n{DIV}')
    print(f'SANITY CHECK: {sym}  |  {trig_date_str}')
    print(DIV)

    rows = conn.execute('''
        SELECT date,
               COALESCE(open, close)  AS open,
               COALESCE(high, close)  AS high,
               COALESCE(low,  close)  AS low,
               close,
               COALESCE(volume, 0)    AS volume
        FROM prices_adjusted
        WHERE symbol=? AND date <= ?
        ORDER BY date
    ''', (sym, trig_date_str)).fetchall()

    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
    df['date'] = pd.to_datetime(df['date'])
    for c2 in ('open','high','low','close','volume'):
        df[c2] = pd.to_numeric(df[c2], errors='coerce')
    df['volume'] = df['volume'].fillna(0)

    n       = len(df)
    closes  = df['close'].values.astype(float)
    opens_  = df['open'].values.astype(float)
    highs   = df['high'].values.astype(float)
    lows    = df['low'].values.astype(float)
    volumes = df['volume'].values.astype(float)
    dates   = df['date'].values

    vol_ma50_arr = pd.Series(volumes).rolling(50, min_periods=30).mean().values

    t    = n - 1
    prev = t - 1

    # ── Gates 1-7 (unchanged) — just verify they pass ──
    avg_vol_20d = volumes[max(0, t-19):t+1].mean()
    g1 = avg_vol_20d >= 800_000
    g2 = closes[t] >= 5.0
    g3 = n >= 60
    g4 = not (np.isnan(vol_ma50_arr[t]) or vol_ma50_arr[t] <= 0)
    g5 = prev >= 15
    print(f'Gates 1-5 (unchanged): G1={g1}, G2={g2}, G3={g3}, G4={g4}, G5={g5}')

    bs     = _base_scan(closes, prev)
    b_days = prev - bs + 1
    b_closes = closes[bs:prev+1]
    b_high = b_closes.max()
    b_low  = b_closes.min()
    b_range = (b_high - b_low) / b_low
    g6a = b_days >= 8
    g6b = b_range < 0.20
    pre = closes[max(0, bs-90):bs]
    g7a = len(pre) >= 5
    drawdown = (pre.max() - closes[bs]) / pre.max() if g7a else 0
    g7b = drawdown >= 0.30
    print(f'Gates 6-7 (unchanged): G6a(b_days={b_days}>=8)={g6a}, '
          f'G6b(b_range={b_range*100:.1f}%<20%)={g6b}, '
          f'G7b(drawdown={drawdown*100:.1f}%>=30%)={g7b}')

    if not all([g1,g2,g3,g4,g5,g6a,g6b,g7a,g7b]):
        print('>>> A gate before G8 fails — cannot evaluate G8/G9/G10')
        continue

    # ── Gate 8 (FIX 1) ──
    print(f'\nBase: idx {bs} ({pd.Timestamp(dates[bs]).date()}) -> '
          f'idx {prev} ({pd.Timestamp(dates[prev]).date()}), {b_days} bars')
    bv        = volumes[bs:prev+1]
    half_len  = min(10, b_days // 2)
    early_bars = max(1, half_len)
    base_vol_baseline = np.median(volumes[bs:bs + early_bars])
    low_conf  = early_bars < 4
    print(f'\n--- GATE 8 (FIX 1): vol contraction vs base_vol_baseline ---')
    print(f'  half_len={half_len}, early_bars={early_bars}, '
          f'low_confidence={low_conf}')
    print(f'  Early base volumes (bars {bs} to {bs+early_bars-1}):')
    for bi in range(early_bars):
        print(f'    {pd.Timestamp(dates[bs+bi]).date()}  '
              f'V={volumes[bs+bi]:>10,.0f}')
    print(f'  base_vol_baseline (median of first {early_bars} bars) = '
          f'{base_vol_baseline:,.0f}')
    l5v  = bv[-5:]
    l5r  = l5v / base_vol_baseline
    mean_r   = l5r.mean()
    below60  = (l5r < 0.60).sum()
    g8b = mean_r < 0.50
    g8c = below60 >= 3
    print(f'  Last 5 base bars:')
    for bi_off in range(len(l5v)):
        bar_abs = bs + len(bv) - 5 + bi_off
        print(f'    {pd.Timestamp(dates[bar_abs]).date()}  '
              f'V={l5v[bi_off]:>10,.0f}  ratio={l5r[bi_off]:.4f}')
    print(f'  mean ratio = {mean_r:.4f}  (need < 0.50) => {"PASS" if g8b else "FAIL"}')
    print(f'  count<0.60 = {below60}       (need >= 3)  => {"PASS" if g8c else "FAIL"}')
    g8 = g8b and g8c
    print(f'  Gate 8 overall: {"PASS" if g8 else "FAIL"}')

    # ── Gate 9 (FIX 1) ──
    print(f'\n--- GATE 9 (FIX 1): prior surge vs base_vol_baseline ---')
    all_br   = bv / base_vol_baseline
    surge_n  = (all_br > 1.5).sum()
    g9       = surge_n >= 2
    print(f'  Bars in base with ratio > 1.5: {surge_n}  (need >= 2) => {"PASS" if g9 else "FAIL"}')
    print(f'  All base ratios:')
    for bi_off in range(len(bv)):
        bar_abs = bs + bi_off
        flag    = '  <<< SURGE' if all_br[bi_off] > 1.5 else ''
        print(f'    {pd.Timestamp(dates[bar_abs]).date()}  '
              f'ratio={all_br[bi_off]:.4f}{flag}')

    if not (g8 and g9):
        print('\n>>> G8 or G9 still fails — Gate 10 not evaluated')
        continue

    # ── Gate 10 (FIX 2) ──
    print(f'\n--- GATE 10 (FIX 2): trigger bar conditions (close>open REMOVED) ---')
    vm50_t    = vol_ma50_arr[t]
    vr_t      = volumes[t] / vm50_t if vm50_t > 0 else float('nan')
    day_rng   = highs[t] - lows[t]
    close_pos = (closes[t] - lows[t]) / day_rng if day_rng > 0 else float('nan')
    open_eq_close = opens_[t] == closes[t]
    print(f'  Trigger bar: O={opens_[t]:.4f} H={highs[t]:.4f} '
          f'L={lows[t]:.4f} C={closes[t]:.4f} V={volumes[t]:,.0f}')
    print(f'  open==close (NULL open): {open_eq_close}')
    print(f'  [REMOVED] close>open check — was unconditionally False, now not evaluated')
    g10a = vr_t >= 2.5
    g10b = closes[t] > b_high
    g10c = day_rng > 0
    g10d = (not np.isnan(close_pos)) and close_pos >= 0.40
    print(f'  vol/vm50   = {vr_t:.4f}  (need >= 2.5) => {"PASS" if g10a else "FAIL"}')
    print(f'  close>b_high: {closes[t]:.4f} > {b_high:.4f} => {"PASS" if g10b else "FAIL"}')
    print(f'  day_rng    = {day_rng:.4f}  (need > 0)   => {"PASS" if g10c else "FAIL"}')
    print(f'  close_pos  = {close_pos:.4f}  (need>=0.40) => {"PASS" if g10d else "FAIL"}')
    all_g10 = g10a and g10b and g10c and g10d
    print(f'\n  Gate 10 overall: {"*** PASS — SIGNAL FIRES ***" if all_g10 else "FAIL"}')

print(f'\n{DIV}\nDONE')
conn.close()
