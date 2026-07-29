"""Gate-by-gate trace for Recovery Basis false negatives."""
import sqlite3, numpy as np, pandas as pd, sys, re
sys.path.insert(0, 'C:/Users/Lenovo/psx_pipeline')
from config import EXCLUDED_SECTORS

DB_PATH = 'C:/Users/Lenovo/psx_pipeline/psx_data.db'
conn = sqlite3.connect(DB_PATH)

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

DIV = '=' * 72

for sym, trig_date_str in CASES:
    print(f'\n{DIV}')
    print(f'SYMBOL: {sym}   TRIGGER DATE: {trig_date_str}')
    print(DIV)

    # Sector/universe eligibility
    sec_row = conn.execute('SELECT sector FROM sectors WHERE symbol=?', (sym,)).fetchone()
    sector  = sec_row[0] if sec_row else None
    excl_flag = sector in EXCLUDED_SECTORS if sector else True
    pdigt     = bool(re.match(r'^P\d', sym))
    print(f'Sector: {sector}  |  In EXCLUDED_SECTORS: {excl_flag}  |  P\\d pattern: {pdigt}')
    if excl_flag or pdigt:
        print('>>> FAILS universe filter (excluded sector or P-digit pattern)')
        continue

    # Load all adjusted data up to and including trigger date
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

    if not rows:
        print('NO DATA')
        continue

    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
    df['date'] = pd.to_datetime(df['date'])
    for c2 in ('open','high','low','close','volume'):
        df[c2] = pd.to_numeric(df[c2], errors='coerce')
    df['volume'] = df['volume'].fillna(0)

    n       = len(df)
    dates   = df['date'].values
    closes  = df['close'].values.astype(float)
    opens_  = df['open'].values.astype(float)
    highs   = df['high'].values.astype(float)
    lows    = df['low'].values.astype(float)
    volumes = df['volume'].values.astype(float)

    print(f'Data loaded: {n} bars  {df["date"].iloc[0].date()} -> {df["date"].iloc[-1].date()}')

    # vol_ma50: rolling 50-bar, min_periods=30
    vol_ma50_arr = pd.Series(volumes).rolling(50, min_periods=30).mean().values

    t       = n - 1
    prev    = t - 1

    print(f'Trigger bar: idx={t}  date={pd.Timestamp(dates[t]).date()}')
    print(f'  O={opens_[t]:.4f}  H={highs[t]:.4f}  L={lows[t]:.4f}  C={closes[t]:.4f}  V={volumes[t]:,.0f}')
    print(f'  open==close (NULL open coalesced): {opens_[t] == closes[t]}')

    # ── GATE 1: avg_vol_20d ──────────────────────────────────────
    print('\n--- GATE 1: avg_vol_20d >= 800,000 ---')
    avg_vol_20d = volumes[max(0, t-19):t+1].mean()
    g1 = avg_vol_20d >= 800_000
    print(f'  avg_vol_20d = {avg_vol_20d:,.0f}  |  800,000  |  {"PASS" if g1 else "FAIL"}')

    # ── GATE 2: close >= 5 ───────────────────────────────────────
    print('--- GATE 2: close >= 5.0 ---')
    g2 = closes[t] >= 5.0
    print(f'  close = {closes[t]:.4f}  |  {"PASS" if g2 else "FAIL"}')

    # ── GATE 3: n >= 60 ──────────────────────────────────────────
    print('--- GATE 3: n >= 60 ---')
    g3 = n >= 60
    print(f'  n = {n}  |  {"PASS" if g3 else "FAIL"}')

    # ── GATE 4: vol_ma50 valid ───────────────────────────────────
    print('--- GATE 4: vol_ma50[t] valid (not NaN, > 0) ---')
    vm50_t = vol_ma50_arr[t]
    g4 = not (np.isnan(vm50_t) or vm50_t <= 0)
    print(f'  vol_ma50[t] = {vm50_t:,.0f}  |  {"PASS" if g4 else "FAIL (NaN or <=0)"}')

    # ── GATE 5: prev >= 15 ───────────────────────────────────────
    print('--- GATE 5: prev >= 15 ---')
    g5 = prev >= 15
    print(f'  prev = {prev}  |  {"PASS" if g5 else "FAIL"}')

    if not all([g1, g2, g3, g4, g5]):
        print('>>> STOPPED: early gate failure')
        continue

    # ── GATE 6: _base_scan from prev ────────────────────────────
    print('--- GATE 6: _base_scan(closes, prev) ---')
    bs     = _base_scan(closes, prev)
    b_days = prev - bs + 1
    b_closes = closes[bs:prev+1]
    b_high   = b_closes.max()
    b_low    = b_closes.min()
    b_range  = (b_high - b_low) / b_low
    bs_date  = pd.Timestamp(dates[bs]).date()
    pv_date  = pd.Timestamp(dates[prev]).date()
    print(f'  Base: idx {bs} ({bs_date}) -> idx {prev} ({pv_date}),  {b_days} bars')
    print(f'  b_high (max close in base): {b_high:.4f}')
    print(f'  b_low  (min close in base): {b_low:.4f}')
    print(f'  b_range = {b_range:.4f} ({b_range*100:.2f}%)  |  need < 20%  |  {"PASS" if b_range < 0.20 else "FAIL"}')
    print(f'  b_days = {b_days}  |  need >= 8  |  {"PASS" if b_days >= 8 else "FAIL"}')
    print(f'  [NOTE: _base_scan guarantees b_range < 20% by construction — check is redundant]')

    # Print all base bars
    print(f'  Close-by-close within base:')
    for bi in range(bs, prev+1):
        br = volumes[bi]/vol_ma50_arr[bi] if vol_ma50_arr[bi] > 0 else float('nan')
        print(f'    {pd.Timestamp(dates[bi]).date()}  C={closes[bi]:.4f}  '
              f'V={volumes[bi]:>12,.0f}  vm50={vol_ma50_arr[bi]:>10,.0f}  v/vm50={br:.4f}')

    g6a = b_days >= 8
    g6b = b_range < 0.20
    if not (g6a and g6b):
        # Debug: what does the base scan find if we search further back?
        print(f'  [DEBUG] _base_scan found only {b_days}-bar base. '
              f'Checking what max_lb=180 would find...')
        bs2 = _base_scan(closes, prev, max_lb=180)
        b2_days = prev - bs2 + 1
        b2_cl   = closes[bs2:prev+1]
        b2_rng  = (b2_cl.max()-b2_cl.min())/b2_cl.min()
        print(f'  With max_lb=180: bs={bs2} ({pd.Timestamp(dates[bs2]).date()}), '
              f'b_days={b2_days}, b_range={b2_rng:.4f}')
        print(f'>>> GATE 6 FAILS: b_days={b_days}, b_range={b_range:.4f}')
        continue

    # ── GATE 7: pre-base decline >= 30% ─────────────────────────
    print('--- GATE 7: drawdown from pre-base high >= 30% ---')
    pre_start = max(0, bs - 90)
    pre       = closes[pre_start:bs]
    pre_len   = len(pre)
    g7a = pre_len >= 5
    print(f'  Pre window: closes[{pre_start}:{bs}], {pre_len} bars  |  need >= 5  |  {"PASS" if g7a else "FAIL"}')

    if g7a:
        pre_high     = pre.max()
        pre_high_idx = pre_start + int(np.argmax(pre))
        pre_high_dt  = pd.Timestamp(dates[pre_high_idx]).date()
        base_start_c = closes[bs]
        drawdown     = (pre_high - base_start_c) / pre_high
        g7b = drawdown >= 0.30
        print(f'  pre-base high  = {pre_high:.4f} on {pre_high_dt} (closes[{pre_high_idx}])')
        print(f'  base_start_close = closes[{bs}] = {base_start_c:.4f} ({bs_date})')
        print(f'  drawdown = ({pre_high:.4f} - {base_start_c:.4f}) / {pre_high:.4f}')
        print(f'           = {drawdown:.4f} ({drawdown*100:.2f}%)  |  need >= 30%  |  {"PASS" if g7b else "FAIL"}')

        if not g7b:
            # Find where >= 30% drawdown IS reached
            for look_back in range(bs-1, max(0, bs-200)-1, -1):
                d2 = (closes[look_back] - base_start_c) / closes[look_back]
                if d2 >= 0.30:
                    print(f'  [INFO] 30% drawdown IS reached if pre-window extended to '
                          f'closes[{look_back}]={closes[look_back]:.4f} on '
                          f'{pd.Timestamp(dates[look_back]).date()} (d={d2*100:.1f}%)')
                    break

    if not (g7a and g7b):
        print('>>> GATE 7 FAILS')
        continue

    # ── GATE 8: volume contraction last 5 base bars ──────────────
    print('--- GATE 8: Volume contraction in last 5 base bars ---')
    bv   = volumes[bs:prev+1]
    bm50 = vol_ma50_arr[bs:prev+1]
    l5v  = bv[-5:]
    l5m  = bm50[-5:]
    ok   = l5m > 0

    print(f'  Last 5 base bars:')
    for bi_off in range(len(l5v)):
        bar_abs = bs + len(bv) - 5 + bi_off
        vr_val  = (l5v[bi_off] / l5m[bi_off]) if (l5m[bi_off] > 0) else float('nan')
        print(f'    [{bi_off}] {pd.Timestamp(dates[bar_abs]).date()}  '
              f'V={l5v[bi_off]:>10,.0f}  vm50={l5m[bi_off]:>10,.0f}  '
              f'ratio={vr_val:.4f}  ok={bool(ok[bi_off])}')

    ok_cnt = ok.sum()
    g8a = ok_cnt >= 3
    print(f'  ok.sum() = {ok_cnt}  |  need >= 3  |  {"PASS" if g8a else "FAIL"}')

    if g8a:
        l5r = np.where(ok, l5v / np.where(l5m > 0, l5m, 1.0), 1.0)
        mean_r    = l5r[ok].mean()
        below60_n = (l5r[ok] < 0.60).sum()
        g8b = mean_r < 0.50
        g8c = below60_n >= 3
        print(f'  Ratios (ok bars): {[round(float(x),4) for x in l5r[ok]]}')
        print(f'  Mean ratio  = {mean_r:.4f}  |  need < 0.50  |  {"PASS" if g8b else "FAIL"}')
        print(f'  Count<0.60  = {below60_n}   |  need >= 3    |  {"PASS" if g8c else "FAIL"}')

    if not (g8a and (g8b if g8a else False) and (g8c if g8a else False)):
        print('>>> GATE 8 FAILS')
        continue

    # ── GATE 9: prior surge within base ──────────────────────────
    print('--- GATE 9: Prior volume surge in base (>= 2 bars > 1.5x vm50) ---')
    all_br = np.where(bm50 > 0, bv / bm50, 0.0)
    surge_n = (all_br > 1.5).sum()
    print(f'  surge bars (ratio>1.5): {surge_n}  |  need >= 2  |  {"PASS" if surge_n >= 2 else "FAIL"}')
    print(f'  Volume ratios for all {len(bv)} base bars:')
    for bi_off in range(len(bv)):
        bar_abs = bs + bi_off
        flag    = '  <<< SURGE' if all_br[bi_off] > 1.5 else ''
        print(f'    {pd.Timestamp(dates[bar_abs]).date()}  C={closes[bar_abs]:.4f}  '
              f'V={volumes[bar_abs]:>10,.0f}  vm50={bm50[bi_off]:>10,.0f}  '
              f'ratio={all_br[bi_off]:.4f}{flag}')

    g9 = surge_n >= 2
    if not g9:
        print('>>> GATE 9 FAILS')
        continue

    # ── GATE 10: trigger bar ─────────────────────────────────────
    print('--- GATE 10: Trigger bar conditions ---')
    vr_t      = volumes[t] / vm50_t if vm50_t > 0 else float('nan')
    day_rng   = highs[t] - lows[t]
    close_pos = (closes[t] - lows[t]) / day_rng if day_rng > 0 else float('nan')
    green     = closes[t] > opens_[t]

    g10a = vr_t >= 2.5
    g10b = closes[t] > b_high
    g10c = green
    g10d = day_rng > 0
    g10e = (not np.isnan(close_pos)) and close_pos >= 0.40

    print(f'  vol/vm50   = {vr_t:.4f}        |  need >= 2.5   |  {"PASS" if g10a else "FAIL"}')
    print(f'  close>b_high: {closes[t]:.4f} > {b_high:.4f}  |  {"PASS" if g10b else "FAIL"}')
    print(f'  green (C>O): {closes[t]:.4f} > {opens_[t]:.4f}  |  {"PASS" if g10c else "FAIL"}')
    print(f'  day_rng    = {day_rng:.4f}        |  need > 0      |  {"PASS" if g10d else "FAIL"}')
    print(f'  close_pos  = {close_pos:.4f}        |  need >= 0.40  |  {"PASS" if g10e else "FAIL"}')

    all_pass = g10a and g10b and g10c and g10d and g10e
    print(f'\n  Gate 10: {"*** ALL PASS — SIGNAL WOULD FIRE ***" if all_pass else "FAILS"}')
    if not all_pass:
        fails = []
        if not g10a: fails.append(f'vol/vm50={vr_t:.2f}<2.5')
        if not g10b: fails.append(f'close={closes[t]:.4f}<=b_high={b_high:.4f}')
        if not g10c: fails.append(f'green=False (open={opens_[t]:.4f}==close={closes[t]:.4f})')
        if not g10d: fails.append(f'day_rng={day_rng:.4f}=0')
        if not g10e: fails.append(f'close_pos={close_pos:.4f}<0.40')
        print(f'  Failing sub-conditions: {", ".join(fails)}')

print(f'\n{DIV}')
print('DONE')
conn.close()
