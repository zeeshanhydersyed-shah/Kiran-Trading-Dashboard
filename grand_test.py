"""
grand_test.py — The Grand Test: three validated edges, one engine, net of costs.
================================================================================
Puts the three dashboard edges (DC Breakout, Weinstein Stage 2, Recovery Bases)
on ONE measuring stick for the first time:

  - each screener traded by its OWN validated mechanics (not unified),
  - sized at 1% risk from a SHARED capital pool (they compete for cash),
  - charged the REAL BMA cost model + 15% CGT on net annual realized gains,
  - reported per-edge and combined: net per-trade EV, trades/year, net annual
    expectancy, breakdown by market stage, equity curve, max drawdown,
    Monte-Carlo drawdown/ruin distribution, and capacity ceiling.

DISCIPLINE
  - READ-ONLY on psx_data.db. This script issues SELECT only; it never writes
    to the production database.
  - Each generator is validated against its original script's signal/trade
    counts (zero-cost) BEFORE costs are applied — see validate_generators().

This file is built in phases. Phase A (this commit): data loading + the three
candidate generators + a validation harness. Phase B adds the shared-capital
portfolio + cost/CGT engine. Phase C adds metrics / Monte-Carlo / reporting.
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict

from config import EXCLUDED_SECTORS

DB_PATH = str(Path(__file__).parent / 'psx_data.db')

# ── Cost model (from BMA statement + NCCPL CGT report) ──────────────────────
BROKERAGE_PCT   = 0.0015          # 0.15% of value per side
FED_ON_BROK     = 0.15            # FED = 15% of brokerage
SLIPPAGE_PCT    = 0.0025          # 0.25% per side (assumption, liquid names)
CGT_RATE        = 0.15            # 15% on NET annual realized gain (losses offset)
PER_SIDE_COST   = BROKERAGE_PCT * (1 + FED_ON_BROK) + SLIPPAGE_PCT   # ~0.4225%/side

# ── Portfolio ───────────────────────────────────────────────────────────────
INITIAL_EQUITY  = 100_000.0
RISK_PER_TRADE  = 0.01

# ── Validation window / holdout ─────────────────────────────────────────────
HOLDOUT_START   = '2024-01-01'    # 2024-2026 sealed off as true out-of-sample


# ════════════════════════════════════════════════════════════════════════════
# DATA LOADING (once, read-only)
# ════════════════════════════════════════════════════════════════════════════
def load_all():
    conn = sqlite3.connect(DB_PATH)
    excl = tuple(EXCLUDED_SECTORS)
    qmarks = ','.join('?' * len(excl))

    px = pd.read_sql_query(f"""
        SELECT p.symbol, s.sector, p.date,
               COALESCE(p.high,  p.close) AS high,
               COALESCE(p.low,   p.close) AS low,
               p.close,
               COALESCE(p.volume, 0)      AS volume
        FROM prices_adjusted p
        JOIN sectors s ON s.symbol = p.symbol
        WHERE s.sector NOT IN ({qmarks})
        ORDER BY p.symbol, p.date
    """, conn, params=list(excl))

    ss = pd.read_sql_query("""
        SELECT ss.date, ss.symbol, ss.rank_change, ss.sector_rs_rank,
               ss.near_pivot_days, ss.avg_vol_10d,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.close_above_ema150, ss.ema150_slope_pos,
               sec.rs_rank    AS sec_global_rank,
               sec.sector_stage AS sec_stage
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = ss.date AND sec.sector = s.sector
        WHERE ss.date >= '2015-01-01'
        ORDER BY ss.symbol, ss.date
    """, conn)

    kse = pd.read_sql_query(
        "SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", conn)

    # sector stage over time (for Weinstein stage-exit)
    secstg = pd.read_sql_query(
        "SELECT date, sector, sector_stage FROM sector_signals ORDER BY sector, date", conn)
    conn.close()

    # Drop P\d pattern symbols (futures-ish), matching recovery_backtest_v2
    px = px[~px['symbol'].str.match(r'^P\d', na=False)].copy()
    for c in ('high', 'low', 'close'):
        px[c] = pd.to_numeric(px[c], errors='coerce')
    px['volume'] = pd.to_numeric(px['volume'], errors='coerce').fillna(0)

    return px, ss, kse, secstg


def build_symbol_arrays(px):
    """symbol -> dict of numpy arrays (dates as str, ohlc, volume, ema21, ema150, dti)."""
    sym_data = {}
    for sym, g in px.groupby('symbol', sort=False):
        g = g.sort_values('date').reset_index(drop=True)
        c = g['close'].to_numpy(dtype=float)
        d = g['date'].to_numpy()  # str dates 'YYYY-MM-DD'
        sym_data[sym] = {
            'sector': g['sector'].iloc[0],
            'dates':  d,
            'high':   g['high'].to_numpy(dtype=float),
            'low':    g['low'].to_numpy(dtype=float),
            'close':  c,
            'volume': g['volume'].to_numpy(dtype=float),
            'ema21':  pd.Series(c).ewm(span=21,  adjust=False).mean().to_numpy(),
            'ema150': pd.Series(c).ewm(span=150, adjust=False).mean().to_numpy(),
            'dti':    {dt: i for i, dt in enumerate(d)},
        }
    return sym_data


# ════════════════════════════════════════════════════════════════════════════
# CANDIDATE SCHEMA
# Each generator returns a list of dicts:
#   edge, symbol, signal_date, entry_date, entry_price, init_stop,
#   exit_date, exit_price, gross_ret_pct, hold_days, exit_reason
# Exits are pre-resolved from the price path (capital-independent); the
# portfolio layer later decides which candidates actually get taken.
# ════════════════════════════════════════════════════════════════════════════

# ── Recovery Bases: port of recovery_backtest_v2.py ─────────────────────────
def _base_scan(c, from_idx, thr=0.20, max_lb=90):
    hi = lo = c[from_idx]
    start = from_idx
    for i in range(from_idx - 1, max(from_idx - max_lb, 0) - 1, -1):
        nh, nl = max(hi, c[i]), min(lo, c[i])
        if (nh - nl) / nl >= thr:
            break
        hi, lo, start = nh, nl, i
    return start


def gen_recovery(sym_data):
    cands = []
    for sym, sd in sym_data.items():
        closes, highs, lows = sd['close'], sd['high'], sd['low']
        vols, dates, ema21 = sd['volume'], sd['dates'], sd['ema21']
        n = len(closes)
        if n < 60:
            continue
        vol_ma50 = pd.Series(vols).rolling(50, min_periods=30).mean().to_numpy()

        t = 60
        while t < n:
            avg_vol_20d = vols[max(0, t-19):t+1].mean()
            if avg_vol_20d < 800_000 or closes[t] < 5.0 or np.isnan(vol_ma50[t]) or vol_ma50[t] <= 0:
                t += 1; continue
            prev = t - 1
            if prev < 15:
                t += 1; continue
            bs = _base_scan(closes, prev)
            b_days = prev - bs + 1
            if b_days < 8:
                t += 1; continue
            bc = closes[bs:prev+1]
            b_high, b_low = bc.max(), bc.min()
            if (b_high - b_low) / b_low >= 0.20:
                t += 1; continue
            pre = closes[max(0, bs-90):bs]
            if len(pre) < 5 or (pre.max() - closes[bs]) / pre.max() < 0.30:
                t += 1; continue
            bv = vols[bs:prev+1]
            early = max(1, min(10, b_days // 2))
            bvb = np.median(vols[bs:bs+early])
            if bvb <= 0:
                t += 1; continue
            l5r = bv[-5:] / bvb
            if not (l5r.mean() < 0.50 and (l5r < 0.60).sum() >= 3):
                t += 1; continue
            if (bv / bvb > 1.5).sum() < 2:
                t += 1; continue
            vr = vols[t] / vol_ma50[t]
            day_rng = highs[t] - lows[t]
            if not (vr >= 2.5 and closes[t] > b_high and day_rng > 0
                    and (closes[t] - lows[t]) / day_rng >= 0.40):
                t += 1; continue
            if t + 1 >= n:
                break
            # Fix-3 entry: T+1 stop-order fill at trigger_high = highs[t]
            trig = highs[t]
            stop = round(b_low * 0.97, 4)
            fill_idx = t + 1
            if highs[fill_idx] < trig:
                t += 1; continue                      # never filled -> discard
            entry_price = trig
            entry_idx = fill_idx
            # exit: same-day stop, else trail close<ema21 -> exit next close
            exit_idx = exit_price = None; reason = None
            if closes[fill_idx] <= stop:
                exit_idx, exit_price, reason = fill_idx, stop, 'STOP_SAME_DAY'
            else:
                for d in range(fill_idx + 1, n):
                    if closes[d] < ema21[d] or closes[d] <= stop:
                        reason = 'TRAIL' if closes[d] < ema21[d] else 'STOP'
                        nx = d + 1
                        exit_idx = nx if nx < n else d
                        exit_price = closes[exit_idx]
                        break
                if exit_idx is None:
                    exit_idx, exit_price, reason = n-1, closes[n-1], 'OPEN_END'
            cands.append(dict(
                edge='Recovery', symbol=sym, signal_date=dates[t],
                entry_date=dates[entry_idx], entry_price=float(entry_price),
                init_stop=float(stop), exit_date=dates[exit_idx],
                exit_price=float(exit_price),
                gross_ret_pct=(exit_price-entry_price)/entry_price*100,
                hold_days=int(exit_idx-entry_idx), exit_reason=reason))
            # one-position-per-symbol: resume scanning after this trade exits
            t = max(exit_idx + 1, t + 1)
    return cands


# ── DC Breakout: port of boring_signals.py (HYBRID_TRAIL, top RS-60 decile) ──
HYBRID_FLOOR_PCT = -0.08
RS_WINDOW = 60
LIQ_THRESH = 200_000


def _rs60_series(sd, kse_idx):
    """RS_60 time series aligned to sd['dates'] (NaN where undefined)."""
    c = sd['close']; d = sd['dates']; n = len(c)
    rs = np.full(n, np.nan)
    for i in range(RS_WINDOW, n):
        c0 = c[i-RS_WINDOW]
        if c0 <= 0 or np.isnan(c[i]) or np.isnan(c0):
            continue
        ki = kse_idx['dti'].get(d[i])
        if ki is None or ki < RS_WINDOW:
            continue
        k, k0 = kse_idx['close'][ki], kse_idx['close'][ki-RS_WINDOW]
        if k0 <= 0:
            continue
        rs[i] = ((c[i]/c0 - 1) - (k/k0 - 1)) * 100
    return rs


def gen_dc(sym_data, kse):
    # KSE index arrays
    kse = kse.sort_values('date').reset_index(drop=True)
    kse_idx = {'dates': kse['date'].to_numpy(),
               'close': kse['close'].to_numpy(dtype=float),
               'dti': {dt: i for i, dt in enumerate(kse['date'])}}

    # Precompute per-symbol RS_60, avg_vol_10d (as-of t-1), prior-N highs
    syms = list(sym_data.keys())
    rs_by_sym, av_by_sym = {}, {}
    for sym, sd in sym_data.items():
        rs_by_sym[sym] = _rs60_series(sd, kse_idx)
        av_by_sym[sym] = pd.Series(sd['volume']).rolling(10, min_periods=1).mean().to_numpy()

    # Build per-date cross-sectional RS-60 deciles among liquidity-passers, as of t-1.
    # Collect (date -> list of (sym, rs_asof_tminus1, liq_pass)).
    per_date = defaultdict(list)
    for sym, sd in sym_data.items():
        d = sd['dates']; rs = rs_by_sym[sym]; av = av_by_sym[sym]
        for i in range(1, len(d)):
            r = rs[i-1]           # as of t-1
            if np.isnan(r):
                continue
            liq = av[i-1] > LIQ_THRESH
            per_date[d[i]].append((sym, r, liq))

    # decile lookup: (date, sym) -> decile among liquidity-passers that date
    decile_lu = {}
    for dt, rows in per_date.items():
        passers = [(s, r) for (s, r, liq) in rows if liq]
        if len(passers) < 10:
            continue
        rss = pd.Series([r for _, r in passers])
        dec = pd.qcut(rss, 10, labels=False, duplicates='drop')
        for (s, _), dc in zip(passers, dec):
            decile_lu[(dt, s)] = int(dc) if pd.notna(dc) else -1

    cands = []
    for sym, sd in sym_data.items():
        d, h, lo, c = sd['dates'], sd['high'], sd['low'], sd['close']
        n = len(c)
        open_until = -1   # index; symbol ineligible while a signal is open
        for t in range(RS_WINDOW, n):
            if t <= open_until:
                continue
            # top-decile + liquidity gate as of t-1
            if decile_lu.get((d[t], sym), -1) != 9:
                continue
            # breakout for n in {20,60}: close[t] > 1.01*max(high[t-nn..t-1])
            fired = False
            for nn in (20, 60):
                if t < nn:
                    continue
                prior_high = np.nanmax(h[t-nn:t])
                if not np.isnan(prior_high) and c[t] > prior_high * 1.01:
                    fired = True; break
            if not fired:
                continue
            entry = c[t]
            floor_level = entry * (1 + HYBRID_FLOOR_PCT)
            stop = max(lo[t], floor_level)
            exit_idx = None
            for dd in range(t+1, n):
                stop = max(stop, lo[dd-1])
                if lo[dd] <= stop:
                    exit_idx = dd; break
            if exit_idx is None:
                exit_idx, exit_price, reason = n-1, c[n-1], 'OPEN_END'
            else:
                exit_price, reason = stop, 'HYBRID_STOP'
            cands.append(dict(
                edge='DC', symbol=sym, signal_date=d[t],
                entry_date=d[t], entry_price=float(entry),
                init_stop=float(max(lo[t], floor_level)),
                exit_date=d[exit_idx], exit_price=float(exit_price),
                gross_ret_pct=(exit_price-entry)/entry*100,
                hold_days=int(exit_idx-t), exit_reason=reason))
            open_until = exit_idx
    return cands


# ── Weinstein Stage 2: gates from weinstein_combined_backtest.py + real exit ─
def gen_weinstein(ss, sym_data, secstg, use_ema='ema50', exit_rule='ema150'):
    """
    Signal = full live screener gate (EMA50 = current dashboard version).
    Exit (my a-priori rule, since Weinstein is untraded):
      entry = close(signal_date); initial hard stop -6%;
      exit_rule='ema150' : close < EMA150 (Weinstein 30-week stage-2 sell)
      exit_rule='time90' : 90 trading days
      exit_rule='atr'    : chandelier-style 3*ATR20 trailing stop
    Plus hard stage-exit: sector leaves Stage 2 (sector_stage != 'Stage 2').
    """
    ss = ss.copy()
    ss['date'] = ss['date'].astype(str)
    mask_sec = (ss['sec_stage'] == 'Stage 2') & (ss['sec_global_rank'].fillna(999) <= 8)
    if use_ema == 'ema50':
        mask = mask_sec & (ss['close_above_ema50'].fillna(0) == 1) & (ss['ema50_slope_pos'].fillna(0) == 1)
    else:
        mask = mask_sec & (ss['close_above_ema150'].fillna(0) == 1) & (ss['ema150_slope_pos'].fillna(0) == 1)
    mask = (mask & (ss['rank_change'].fillna(-999) > 0)
                 & (ss['sector_rs_rank'].fillna(999) <= 5)
                 & (ss['near_pivot_days'].fillna(0) >= 7)
                 & (ss['avg_vol_10d'].fillna(0) > 200_000))
    sig = ss[mask].sort_values(['symbol', 'date']).copy()
    # dedup consecutive streaks -> first day
    sig['pd_'] = sig.groupby('symbol')['date'].shift(1)
    sig['gap'] = (pd.to_datetime(sig['date']) - pd.to_datetime(sig['pd_'])).dt.days
    sig = sig[sig['pd_'].isna() | (sig['gap'] > 5)]

    # sector stage lookup: (sector, date) -> stage, plus per-sector sorted dates
    secstg = secstg.copy(); secstg['date'] = secstg['date'].astype(str)
    stage_by_sec = {}
    for sec, g in secstg.groupby('sector'):
        g = g.sort_values('date')
        stage_by_sec[sec] = (g['date'].to_numpy(), g['sector_stage'].to_numpy())

    def stage_at(sector, dt):
        v = stage_by_sec.get(sector)
        if v is None:
            return None
        dts, stg = v
        i = np.searchsorted(dts, dt, side='right') - 1
        return stg[i] if i >= 0 else None

    cands = []
    for _, row in sig.iterrows():
        sym = row['symbol']; sd = sym_data.get(sym)
        if sd is None:
            continue
        idx = sd['dti'].get(row['date'])
        if idx is None:
            continue
        c, lo, d = sd['close'], sd['low'], sd['dates']
        ema150 = sd['ema150']; n = len(c)
        entry = c[idx]
        hard_stop = entry * 0.94
        sector = sd['sector']
        exit_idx = None; reason = None
        for dd in range(idx+1, n):
            if lo[dd] <= hard_stop:
                exit_idx, reason = dd, 'STOP6'; break
            if exit_rule == 'ema150' and c[dd] < ema150[dd]:
                exit_idx, reason = dd, 'EMA150'; break
            if exit_rule == 'time90' and (dd - idx) >= 90:
                exit_idx, reason = dd, 'TIME90'; break
            if stage_at(sector, d[dd]) not in ('Stage 2', None):
                exit_idx, reason = dd, 'STAGE_EXIT'; break
        if exit_idx is None:
            exit_idx, reason = n-1, 'OPEN_END'
        exit_price = c[exit_idx] if reason != 'STOP6' else hard_stop
        cands.append(dict(
            edge='Weinstein', symbol=sym, signal_date=row['date'],
            entry_date=row['date'], entry_price=float(entry),
            init_stop=float(hard_stop), exit_date=d[exit_idx],
            exit_price=float(exit_price),
            gross_ret_pct=(exit_price-entry)/entry*100,
            hold_days=int(exit_idx-idx), exit_reason=reason))
    return cands


# ════════════════════════════════════════════════════════════════════════════
# VALIDATION HARNESS — must reproduce originals (zero-cost) before we trust it
# ════════════════════════════════════════════════════════════════════════════
def _stats(cands, label):
    df = pd.DataFrame(cands)
    if df.empty:
        print(f"  {label:<12} N=0"); return
    w = df[df['gross_ret_pct'] > 0]; l = df[df['gross_ret_pct'] <= 0]
    wr = len(w)/len(df)*100
    aw = w['gross_ret_pct'].mean() if len(w) else 0
    al = l['gross_ret_pct'].mean() if len(l) else 0
    ev = wr/100*aw + (1-wr/100)*al
    yrs = ((pd.to_datetime(df['signal_date']).max() - pd.to_datetime(df['signal_date']).min()).days / 365.25)
    print(f"  {label:<12} N={len(df):>5}  WR={wr:>5.1f}%  avgW={aw:>+6.2f}  avgL={al:>+6.2f}  "
          f"grossEV={ev:>+6.2f}%  ({len(df)/yrs:.0f}/yr)  {df['signal_date'].min()}->{df['signal_date'].max()}")


def main():
    print("Loading data (read-only)...")
    px, ss, kse, secstg = load_all()
    print(f"  prices rows={len(px):,}  symbols={px['symbol'].nunique()}  "
          f"stock_signals rows={len(ss):,}")
    sym_data = build_symbol_arrays(px)

    print("\nGenerating candidates (zero-cost, validation)...")
    rec = gen_recovery(sym_data)
    dc  = gen_dc(sym_data, kse)
    wei = gen_weinstein(ss, sym_data, secstg, use_ema='ema50', exit_rule='ema150')

    print("\nPER-EDGE GROSS (validate against originals):")
    _stats(rec, 'Recovery')
    _stats(dc,  'DC')
    _stats(wei, 'Weinstein')

    print("\nValidation targets:")
    print("  Weinstein FULL EMA50 signals ~1201 streaks (weinstein_combined_backtest)")
    print("  Recovery: compare N + gross expectancy to recovery_backtest_v2 portfolio")
    print("  DC: raw Donchian occurrences in boring_donchian_occurrences.csv (pre-decile)")

    import pickle
    with open('grand_test_candidates.pkl', 'wb') as f:
        pickle.dump({'Recovery': rec, 'DC': dc, 'Weinstein': wei}, f)
    print("\nCandidates cached -> grand_test_candidates.pkl")


if __name__ == '__main__':
    main()
