"""
Weinstein Backtest Round 2 — PSX 2005-2026
===========================================
Task 1: MA grid — 50/100/150-day x SMA/EMA (6 variants, point-in-time crossover)
Task 2: Sector gate comparison at 60d/90d/120d windows (not 20d)
Task 3: Short screener audit — book citations, backtest, PSX symmetry check
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "psx_data.db"

# ── helpers ───────────────────────────────────────────────────────────────────

def ema_series(s, span):
    return s.ewm(span=span, adjust=False).mean()

def sma_series(s, window):
    return s.rolling(window, min_periods=window).mean()

def outcome_label(ret, threshold=6.0):
    if pd.isna(ret): return "BE"
    if ret > threshold: return "W"
    if ret < -threshold: return "L"
    return "BE"

def print_stats(label, df, windows=(60, 90, 120), ret_col_prefix="fwd_"):
    n = len(df.dropna(subset=[f"{ret_col_prefix}60d"]))
    if n == 0:
        print(f"  {label}: no valid signals")
        return
    years = (pd.to_datetime(df["signal_date"]).max() -
             pd.to_datetime(df["signal_date"]).min()).days / 365.25
    freq = n / years if years > 0 else 0
    print(f"\n  {'='*56}")
    print(f"  {label}")
    print(f"  N={n}  ({freq:.0f}/yr over {years:.1f} yrs)")
    print(f"  {'Window':>8} {'WR%':>7} {'LR%':>7} {'AvgW':>7} {'AvgL':>7} {'EV':>7} {'AvgRet':>8}")
    for w in windows:
        col = f"{ret_col_prefix}{w}d"
        sub = df.dropna(subset=[col]).copy()
        sub["oc"] = sub[col].apply(outcome_label)
        ns = len(sub)
        if ns == 0:
            continue
        nw = (sub["oc"] == "W").sum()
        nl = (sub["oc"] == "L").sum()
        wr = nw / ns * 100
        lr = nl / ns * 100
        aw = sub.loc[sub["oc"] == "W", col].mean() if nw else 0.0
        al = sub.loc[sub["oc"] == "L", col].mean() if nl else 0.0
        ev = (nw / ns) * aw + (nl / ns) * al
        avg = sub[col].mean()
        print(f"  {w:>7}d {wr:>6.1f}% {lr:>6.1f}% {aw:>6.1f}% {al:>6.1f}% {ev:>6.2f}% {avg:>7.2f}%")


# ── Task 1: MA crossover grid ─────────────────────────────────────────────────

def run_ma_grid(prices_all, index_df, universe):
    """
    Test 6 MA variants: window in (50, 100, 150) x type in (SMA, EMA)
    Signal = price crosses above MA from below, MA slope positive, RS slope positive (10d), vol >= 1.5x 10d avg
    Returns dict of (label -> fwd_return_df)
    """
    prices_map = {}
    for sym, grp in prices_all.groupby("symbol"):
        prices_map[sym] = grp.set_index("date").sort_index()

    idx_series = index_df.set_index("date")["close"].sort_index()

    results = {}
    for window in (50, 100, 150):
        for ma_type in ("SMA", "EMA"):
            label = f"{window}d {ma_type}"
            print(f"  Computing MA signals: {label}...", end="", flush=True)
            sig_rows = []
            for sym in universe:
                if sym not in prices_map:
                    continue
                px = prices_map[sym]
                if len(px) < window + 30:
                    continue
                close = px["close"]
                vol = px["volume"]
                kse = idx_series.reindex(px.index).ffill()

                ma = ema_series(close, window) if ma_type == "EMA" else sma_series(close, window)
                ma_slope = (ma - ma.shift(5)) / ma.shift(5)
                rs = close / kse
                rs_slope = (rs - rs.shift(10)) / rs.shift(10)
                vol_avg10 = vol.rolling(10, min_periods=5).mean().shift(1)
                above = (close > ma).astype(int)
                crossover = (above == 1) & (above.shift(1) == 0)
                liquid = vol_avg10 > 200_000
                sig = crossover & (ma_slope > 0) & (rs_slope > 0) & (vol >= vol_avg10 * 1.5) & liquid
                for d in px.index[sig]:
                    sig_rows.append({"symbol": sym, "signal_date": d,
                                     "entry_close": close.loc[d]})

            sig_df = pd.DataFrame(sig_rows)
            print(f" {len(sig_df)} signals", end="")

            # Forward returns
            fwd_rows = []
            for _, r in sig_df.iterrows():
                sym, d, ec = r["symbol"], r["signal_date"], r["entry_close"]
                future = prices_map[sym][prices_map[sym].index > d]["close"]
                row = {"symbol": sym, "signal_date": d}
                for w in (60, 90, 120):
                    row[f"fwd_{w}d"] = (future.iloc[w - 1] - ec) / ec * 100 if len(future) >= w else np.nan
                fwd_rows.append(row)

            results[label] = pd.DataFrame(fwd_rows)
            print(f"  -> {len(results[label])} with fwd returns")
    return results


# ── Task 2: Sector gate comparison at 60/90/120d ─────────────────────────────

def run_sector_gate_comparison(prices_map, idx_series):
    """
    Uses stock_signals (daily persistent state) as the signal universe.
    For each gate variant, takes ALL days the stock is in that state (deduplicated
    per symbol to first day of a new qualifying streak to avoid double-counting).
    Outcome measured at 60/90/120d forward.
    """
    con = sqlite3.connect(DB_PATH)
    print("  Loading stock_signals + sector_signals...")
    df = pd.read_sql("""
        SELECT ss.date, ss.symbol, ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.close_above_ema50, ss.ema50_slope_pos, ss.near_pivot_days,
               ss.pivot_distance_pct, ss.avg_vol_10d, ss.overhead_clear,
               sm.sector,
               sect.rs_rank         AS sec_rank,
               sect.sector_stage,
               sect.rs_score_20     AS sec_rs_20,
               sect.rs_rank_prev    AS sec_rank_prev
        FROM stock_signals ss
        JOIN stock_metadata sm ON ss.symbol = sm.symbol
        JOIN sector_signals sect ON sm.sector = sect.sector AND ss.date = sect.date
        WHERE ss.avg_vol_10d > 200000
          AND ss.close_above_ema50 = 1
          AND ss.ema50_slope_pos  = 1
          AND ss.near_pivot_days  >= 7
          AND ss.rank_change       > 0
          AND ss.sector_rs_rank   <= 5
          AND sect.sector_stage    = 'Stage 2'
        ORDER BY ss.symbol, ss.date
    """, con)
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])

    # Dedup: keep only the FIRST day of each consecutive qualifying streak per symbol
    # (a new streak starts if the previous day did NOT qualify)
    df["prev_date"] = df.groupby("symbol")["date"].shift(1)
    df["gap"] = (df["date"] - df["prev_date"]).dt.days
    df["new_streak"] = (df["gap"] != 1) | df["gap"].isna()
    df = df[df["new_streak"]].copy()
    print(f"  After dedup (first-day-of-streak): {len(df)} entries")

    # Forward returns
    print("  Computing forward returns (60/90/120d)...")
    fwd_rows = []
    for _, r in df.iterrows():
        sym, d = r["symbol"], r["date"]
        if sym not in prices_map:
            continue
        ec_series = prices_map[sym]["close"]
        try:
            ec = ec_series.loc[d]
        except KeyError:
            continue
        future = ec_series[ec_series.index > d]
        row = {"symbol": sym, "signal_date": d,
               "sec_rank": r["sec_rank"], "sec_rs_20": r["sec_rs_20"],
               "sec_rank_prev": r["sec_rank_prev"]}
        for w in (60, 90, 120):
            row[f"fwd_{w}d"] = (future.iloc[w - 1] - ec) / ec * 100 if len(future) >= w else np.nan
        fwd_rows.append(row)

    fwd = pd.DataFrame(fwd_rows)
    print(f"  Forward return rows: {len(fwd)}")

    gate_variants = [
        ("BASE (no sec rank floor)",
         lambda d: d),
        ("sec_rank <= 15",
         lambda d: d[d["sec_rank"] <= 15]),
        ("sec_rank <= 12",
         lambda d: d[d["sec_rank"] <= 12]),
        ("sec_rank <= 10",
         lambda d: d[d["sec_rank"] <= 10]),
        ("sec_rank <= 8",
         lambda d: d[d["sec_rank"] <= 8]),
        ("sec_rank <= 5",
         lambda d: d[d["sec_rank"] <= 5]),
        ("sec_rs_20 > 0",
         lambda d: d[d["sec_rs_20"] > 0]),
        ("sec_rs_20 > 0 AND sec_rank <= 10",
         lambda d: d[(d["sec_rs_20"] > 0) & (d["sec_rank"] <= 10)]),
        ("sec_rs_20 > 0 AND sec_rank <= 12",
         lambda d: d[(d["sec_rs_20"] > 0) & (d["sec_rank"] <= 12)]),
        ("sec_rank_improving (sec_rank < sec_rank_prev)",
         lambda d: d[d["sec_rank"] < d["sec_rank_prev"]]),
        ("sec_rs_20 > 0 AND rank_improving",
         lambda d: d[(d["sec_rs_20"] > 0) & (d["sec_rank"] < d["sec_rank_prev"])]),
    ]
    return fwd, gate_variants


# ── Task 3: Short screener backtest ──────────────────────────────────────────

def run_short_backtest(prices_map):
    """
    Backtest the current short screener gates on DFC universe.
    Short profit = price FALLS after entry, so fwd_return_short = -fwd_return_stock
    WINNER (short) = stock fell > 6% = fwd_return_stock < -6%
    LOSER  (short) = stock rose > 6% = fwd_return_stock >  +6%
    """
    # Load DFC symbols from config
    import sys
    sys.path.insert(0, ".")
    try:
        from config import DFC_SYMBOLS
        dfc = set(DFC_SYMBOLS)
        print(f"  DFC_SYMBOLS loaded: {len(dfc)} symbols")
    except Exception as e:
        print(f"  WARNING: Could not load DFC_SYMBOLS: {e}")
        dfc = None  # will test without DFC filter too

    con = sqlite3.connect(DB_PATH)
    print("  Loading short screener signal data from stock_signals + sector_signals...")
    df = pd.read_sql("""
        SELECT ss.date, ss.symbol,
               ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.pivot_distance_pct, ss.avg_vol_10d,
               sm.sector,
               sect.rs_rank      AS sec_rank,
               sect.rs_rank_prev AS sec_rank_prev,
               sect.sector_stage,
               sect.rs_score_20  AS sec_rs_20
        FROM stock_signals ss
        JOIN stock_metadata sm ON ss.symbol = sm.symbol
        JOIN sector_signals sect ON sm.sector = sect.sector AND ss.date = sect.date
        ORDER BY ss.symbol, ss.date
    """, con)
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])

    # Apply the CURRENT short gates (excluding DFC first, then with DFC)
    short_base = df[
        (df["sector_stage"].isin(["Stage 3", "Stage 4"])) &
        (df["sec_rank"] > df["sec_rank_prev"]) &            # sector RS rank deteriorating
        (df["close_above_ema50"].fillna(1) == 0) &
        (df["ema50_slope_pos"].fillna(1) == 0) &
        (df["rank_change"].fillna(0) < 0) &
        (df["pivot_distance_pct"].fillna(-99) >= -8) &
        (df["pivot_distance_pct"].fillna(99) <= 2)
    ].copy()

    # Dedup: first day of streak only
    short_base = short_base.sort_values(["symbol", "date"])
    short_base["prev_date"] = short_base.groupby("symbol")["date"].shift(1)
    short_base["gap"] = (short_base["date"] - short_base["prev_date"]).dt.days
    short_base["new_streak"] = (short_base["gap"] != 1) | short_base["gap"].isna()
    short_base = short_base[short_base["new_streak"]].copy()
    print(f"  Short base signals (no DFC filter, dedupd): {len(short_base)}")

    if dfc:
        short_dfc = short_base[short_base["symbol"].isin(dfc)].copy()
        print(f"  Short DFC-filtered signals: {len(short_dfc)}")

    # Weinstein Stage 4 ONLY (not Stage 3) — test separately
    short_stage4_only = short_base[short_base["sector_stage"] == "Stage 4"].copy()
    print(f"  Short signals Stage4 sector only: {len(short_stage4_only)}")

    # Forward returns — short: profit when stock falls
    # fwd_short_N = -(fwd_stock_N) so we just use stock returns and flip sign for outcome
    def compute_short_fwd(sdf, label):
        fwd_rows = []
        for _, r in sdf.iterrows():
            sym, d = r["symbol"], r["date"]
            if sym not in prices_map:
                continue
            ec_series = prices_map[sym]["close"]
            try:
                ec = ec_series.loc[d]
            except KeyError:
                continue
            future = ec_series[ec_series.index > d]
            row = {"symbol": sym, "signal_date": d}
            for w in (20, 60, 90, 120):
                stock_ret = (future.iloc[w - 1] - ec) / ec * 100 if len(future) >= w else np.nan
                row[f"fwd_{w}d"] = stock_ret  # raw stock return
            fwd_rows.append(row)
        return pd.DataFrame(fwd_rows)

    results = {}
    results["short_base_no_dfc"] = (short_base, "Short screener — base gates, no DFC filter")
    if dfc:
        results["short_dfc"] = (short_dfc, "Short screener — DFC-filtered (current implementation)")
    results["short_stage4_only"] = (short_stage4_only, "Short screener — Stage 4 sector only (not Stage 3)")

    fwd_results = {}
    for key, (sdf, lbl) in results.items():
        print(f"  Computing forward returns for: {lbl}...")
        fwd = compute_short_fwd(sdf, lbl)
        fwd_results[key] = (lbl, fwd)

    return fwd_results


def print_short_stats(label, df, windows=(20, 60, 90, 120)):
    """For short trades: WINNER = stock fell > threshold (good for short), LOSER = stock rose > threshold"""
    n = len(df.dropna(subset=["fwd_60d"]))
    if n == 0:
        print(f"  {label}: no data")
        return
    years = (pd.to_datetime(df["signal_date"]).max() -
             pd.to_datetime(df["signal_date"]).min()).days / 365.25
    freq = n / years if years > 0 else 0
    print(f"\n  {'='*56}")
    print(f"  {label}")
    print(f"  N={n}  ({freq:.0f}/yr over {years:.1f} yrs)")
    print(f"  [SHORT: WINNER=stock fell>6%, LOSER=stock rose>6%]")
    print(f"  {'Window':>8} {'WR%':>7} {'LR%':>7} {'AvgW%':>8} {'AvgL%':>8} {'EV':>7} {'AvgFall':>9}")
    for w in windows:
        col = f"fwd_{w}d"
        sub = df.dropna(subset=[col]).copy()
        # For shorts: winner if stock FELL (negative return)
        sub["oc"] = sub[col].apply(lambda r: "W" if r < -6 else ("L" if r > 6 else "BE"))
        ns = len(sub)
        if ns == 0:
            continue
        nw = (sub["oc"] == "W").sum()
        nl = (sub["oc"] == "L").sum()
        wr = nw / ns * 100
        lr = nl / ns * 100
        # avg_win for short = avg fall (negative stock return = positive short profit)
        aw = -sub.loc[sub["oc"] == "W", col].mean() if nw else 0.0
        al = -sub.loc[sub["oc"] == "L", col].mean() if nl else 0.0  # negative (stock rose, short lost)
        ev = (nw / ns) * aw + (nl / ns) * al  # both in "short profit" terms
        avg_fall = -sub[col].mean()  # avg short profit (positive = good)
        print(f"  {w:>7}d {wr:>6.1f}% {lr:>6.1f}% {aw:>7.1f}% {al:>7.1f}% {ev:>6.2f}% {avg_fall:>8.2f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading base data...")
    con = sqlite3.connect(DB_PATH)
    universe = pd.read_sql("SELECT symbol FROM stock_metadata WHERE is_active=1", con)["symbol"].tolist()
    prices_all = pd.read_sql("""
        SELECT p.date, p.symbol, p.close, p.volume
        FROM prices_adjusted p
        JOIN stock_metadata sm ON p.symbol = sm.symbol
        WHERE sm.is_active = 1 AND p.close IS NOT NULL AND p.volume IS NOT NULL
        ORDER BY p.symbol, p.date
    """, con)
    index_df = pd.read_sql(
        "SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
    con.close()

    prices_all["date"] = pd.to_datetime(prices_all["date"])
    index_df["date"] = pd.to_datetime(index_df["date"])
    print(f"  Prices: {len(prices_all):,} rows, {len(universe)} symbols")

    prices_map = {}
    for sym, grp in prices_all.groupby("symbol"):
        prices_map[sym] = grp.set_index("date").sort_index()

    idx_series = index_df.set_index("date")["close"].sort_index()

    # ── TASK 1: MA Grid ──────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("TASK 1 — MA GRID: 50/100/150-day x SMA/EMA")
    print("="*60)
    ma_results = run_ma_grid(prices_all, index_df, universe)

    print("\n\nRESULTS TABLE (sorted by 90d EV):")
    rows = []
    for label, fdf in ma_results.items():
        if fdf.empty:
            continue
        sub = fdf.dropna(subset=["fwd_90d"]).copy()
        sub["oc"] = sub["fwd_90d"].apply(outcome_label)
        n = len(sub)
        nw = (sub["oc"] == "W").sum()
        nl = (sub["oc"] == "L").sum()
        wr = nw / n * 100 if n else 0
        lr = nl / n * 100 if n else 0
        aw = sub.loc[sub["oc"] == "W", "fwd_90d"].mean() if nw else 0
        al = sub.loc[sub["oc"] == "L", "fwd_90d"].mean() if nl else 0
        ev = (nw / n) * aw + (nl / n) * al if n else 0
        avg = sub["fwd_90d"].mean() if n else 0
        yrs = (pd.to_datetime(sub["signal_date"]).max() - pd.to_datetime(sub["signal_date"]).min()).days / 365.25
        freq = n / yrs if yrs > 0 else 0
        rows.append({"MA": label, "N": n, "freq/yr": round(freq, 1),
                     "WR%": round(wr, 1), "LR%": round(lr, 1),
                     "AvgW": round(aw, 1), "AvgL": round(al, 1),
                     "EV_90d": round(ev, 2), "AvgRet_90d": round(avg, 2)})

    rows_df = pd.DataFrame(rows).sort_values("EV_90d", ascending=False)
    print(rows_df.to_string(index=False))

    print("\n\nFULL BREAKDOWN (each variant, all windows):")
    for label, fdf in ma_results.items():
        print_stats(label, fdf)

    # ── TASK 2: Sector Gate Comparison at 60/90/120d ─────────────────────────
    print("\n\n" + "="*60)
    print("TASK 2 — SECTOR GATE COMPARISON AT 60/90/120d")
    print("="*60)
    fwd_base, gate_variants = run_sector_gate_comparison(prices_map, idx_series)

    print("\nRESULTS TABLE (sorted by 90d EV):")
    rows2 = []
    for gate_label, filter_fn in gate_variants:
        sub_full = filter_fn(fwd_base).copy()
        sub = sub_full.dropna(subset=["fwd_90d"])
        n = len(sub)
        if n == 0:
            continue
        sub["oc"] = sub["fwd_90d"].apply(outcome_label)
        nw = (sub["oc"] == "W").sum()
        nl = (sub["oc"] == "L").sum()
        wr = nw / n * 100
        lr = nl / n * 100
        aw = sub.loc[sub["oc"] == "W", "fwd_90d"].mean() if nw else 0
        al = sub.loc[sub["oc"] == "L", "fwd_90d"].mean() if nl else 0
        ev = (nw / n) * aw + (nl / n) * al
        avg = sub["fwd_90d"].mean()
        rows2.append({"Gate": gate_label, "N": n,
                      "WR%": round(wr, 1), "LR%": round(lr, 1),
                      "EV_90d": round(ev, 2), "AvgRet_90d": round(avg, 2)})

    rows2_df = pd.DataFrame(rows2).sort_values("EV_90d", ascending=False)
    print(rows2_df.to_string(index=False))

    print("\n\nFULL BREAKDOWN (each gate, 60/90/120d):")
    for gate_label, filter_fn in gate_variants:
        sub = filter_fn(fwd_base).copy()
        sub.rename(columns={"signal_date": "signal_date"}, inplace=True)
        print_stats(gate_label, sub)

    # ── TASK 3: Short Screener ────────────────────────────────────────────────
    print("\n\n" + "="*60)
    print("TASK 3 — SHORT SCREENER AUDIT")
    print("="*60)
    print("""
Book citations (Ch.7, Selling Short):
  1. Market first: short primarily in bear market (all averages below 30w MA, Stage 4).
     Exception: hedge against longs in bull market. [PDF p.231-232]
  2. Group: sector must be broken below 30w MA. RS line trending lower.
     Several stocks technically weak. [PDF p.232-233]
  3. Individual: must have had SIGNIFICANT prior Stage 2 advance.
     "If top unfolds after mediocre Stage 2, expect minor drop back to base only." [PDF p.234]
  4. RS: must be trending LOWER. Ideal: RS drops INTO negative territory on breakdown.
     "Never short a stock with very positive RS." [PDF p.235-236]
  5. VOLUME ASYMMETRY (CRITICAL): "The short side is 100% different. Volume is NOT a
     necessary ingredient for a winning short sale. It takes power to make a stock rise,
     but a stock can truly fall of its own weight." [PDF p.237]
  6. Support below: minimal support below breakout. Best = straight-up Stage 2 advance
     with no congestion along the way. [PDF pp.237-239]
  7. Entry: at breakdown OR first pullback/bounce back toward breakdown level. [PDF p.230]

Current PSX short screener vs book:
  + sec_stage in (Stage3, Stage4)  — PARTIAL: Stage 3 is risky (could still break up)
  + sec_rank > sec_rank_prev       — captures RS deteriorating
  + close_above_ema50 = 0          — below MA (correct)
  + ema50_slope_pos = 0            — MA declining (correct)
  + rank_change < 0                — RS falling (correct)
  + pivot_distance_pct -8 to 2    — bounce entry (correct, from book p.230)
  + DFC only                       — PSX constraint
  - NO volume gate                 — CORRECT per Weinstein (no volume required for shorts)
  - NO "significant prior advance" check  — missing Weinstein filter
  - NO support-below check         — missing Weinstein filter
  ? Stage 3 included               — Weinstein says wait for Stage 4 break
""")

    short_results = run_short_backtest(prices_map)

    print("\nRESULTS TABLE (90d window, sorted by EV):")
    srows = []
    for key, (lbl, fdf) in short_results.items():
        sub = fdf.dropna(subset=["fwd_90d"]).copy()
        n = len(sub)
        if n == 0:
            continue
        sub["oc"] = sub["fwd_90d"].apply(lambda r: "W" if r < -6 else ("L" if r > 6 else "BE"))
        nw = (sub["oc"] == "W").sum()
        nl = (sub["oc"] == "L").sum()
        wr = nw / n * 100
        lr = nl / n * 100
        aw = -sub.loc[sub["oc"] == "W", "fwd_90d"].mean() if nw else 0
        al = -sub.loc[sub["oc"] == "L", "fwd_90d"].mean() if nl else 0
        ev = (nw / n) * aw + (nl / n) * al
        avg_fall = -sub["fwd_90d"].mean()
        yrs = (pd.to_datetime(sub["signal_date"]).max() - pd.to_datetime(sub["signal_date"]).min()).days / 365.25
        freq = n / yrs if yrs > 0 else 0
        srows.append({"Variant": lbl[:50], "N": n, "freq/yr": round(freq, 1),
                      "WR%": round(wr, 1), "LR%": round(lr, 1),
                      "EV_90d": round(ev, 2), "AvgFall_90d": round(avg_fall, 2)})

    srows_df = pd.DataFrame(srows).sort_values("EV_90d", ascending=False)
    print(srows_df.to_string(index=False))

    print("\nFULL SHORT BREAKDOWN (all windows):")
    for key, (lbl, fdf) in short_results.items():
        print_short_stats(lbl, fdf)

    # Symmetry test: compare long vs short EV at 90d
    print("\n\n--- SYMMETRY CHECK: Long Stage 2 vs Short Stage 4 (90d EV) ---")
    print("Using 50d EMA long signals vs short base (no DFC) at 90d horizon:")
    if "50d EMA" in ma_results:
        long_sub = ma_results["50d EMA"].dropna(subset=["fwd_90d"])
        long_sub = long_sub.copy()
        long_sub["oc"] = long_sub["fwd_90d"].apply(outcome_label)
        nw = (long_sub["oc"] == "W").sum()
        nl = (long_sub["oc"] == "L").sum()
        n = len(long_sub)
        long_ev = ((nw / n) * long_sub.loc[long_sub["oc"] == "W", "fwd_90d"].mean() +
                   (nl / n) * long_sub.loc[long_sub["oc"] == "L", "fwd_90d"].mean()) if n else 0
        print(f"  Long  50d EMA:  N={n}  WR={nw/n*100:.1f}%  LR={nl/n*100:.1f}%  EV={long_ev:.2f}%")

    if "short_base_no_dfc" in short_results:
        _, sdf = short_results["short_base_no_dfc"]
        sub = sdf.dropna(subset=["fwd_90d"]).copy()
        sub["oc"] = sub["fwd_90d"].apply(lambda r: "W" if r < -6 else ("L" if r > 6 else "BE"))
        n = len(sub)
        nw = (sub["oc"] == "W").sum()
        nl = (sub["oc"] == "L").sum()
        aw = -sub.loc[sub["oc"] == "W", "fwd_90d"].mean() if nw else 0
        al = -sub.loc[sub["oc"] == "L", "fwd_90d"].mean() if nl else 0
        short_ev = (nw / n) * aw + (nl / n) * al if n else 0
        print(f"  Short base:     N={n}  WR={nw/n*100:.1f}%  LR={nl/n*100:.1f}%  EV={short_ev:.2f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
