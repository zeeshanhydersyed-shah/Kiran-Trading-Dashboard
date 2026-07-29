"""
Pre-wiring checks:
  1. Combined gate N and EV (150d EMA + sec_rank<=8 + all stock gates)
  2. Breakeven bucket anatomy
  3. Temporal out-of-sample split (train 2005-2015, test 2016-2026)
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "psx_data.db"

def ema_s(s, span):
    return s.ewm(span=span, adjust=False).mean()

def outcome(ret, t=6.0):
    if pd.isna(ret): return "BE"
    if ret > t:      return "W"
    if ret < -t:     return "L"
    return "BE"

# ── load data ─────────────────────────────────────────────────────────────────
print("Loading data...")
con = sqlite3.connect(DB_PATH)
universe = pd.read_sql("SELECT symbol FROM stock_metadata WHERE is_active=1", con)["symbol"].tolist()
prices_all = pd.read_sql("""
    SELECT p.date, p.symbol, p.close, p.volume
    FROM prices_adjusted p
    JOIN stock_metadata sm ON p.symbol = sm.symbol
    WHERE sm.is_active=1 AND p.close IS NOT NULL AND p.volume IS NOT NULL
    ORDER BY p.symbol, p.date
""", con)
index_df = pd.read_sql(
    "SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
ss_df = pd.read_sql("""
    SELECT ss.date, ss.symbol,
           ss.rank_change, ss.sector_rs_rank,
           ss.close_above_ema50, ss.ema50_slope_pos,
           ss.near_pivot_days, ss.avg_vol_10d,
           sm.sector,
           sect.rs_rank AS sec_rank,
           sect.sector_stage
    FROM stock_signals ss
    JOIN stock_metadata sm ON ss.symbol = sm.symbol
    JOIN sector_signals sect ON sm.sector = sect.sector AND ss.date = sect.date
    ORDER BY ss.symbol, ss.date
""", con)
con.close()

prices_all["date"] = pd.to_datetime(prices_all["date"])
index_df["date"]   = pd.to_datetime(index_df["date"])
ss_df["date"]      = pd.to_datetime(ss_df["date"])

prices_map = {sym: grp.set_index("date").sort_index()
              for sym, grp in prices_all.groupby("symbol")}
idx = index_df.set_index("date")["close"].sort_index()

# ── 150d EMA crossover signals (full universe) ─────────────────────────────
print("Computing 150d EMA crossover signals...")
ema_sigs = []
for sym in universe:
    if sym not in prices_map:
        continue
    px = prices_map[sym]
    if len(px) < 180:
        continue
    c, v = px["close"], px["volume"]
    kse  = idx.reindex(px.index).ffill()
    ma   = ema_s(c, 150)
    ma_s5 = ma.shift(5)
    ma_slope = (ma - ma_s5) / ma_s5
    rs = c / kse
    rs_slope = (rs - rs.shift(10)) / rs.shift(10)
    va10 = v.rolling(10, min_periods=5).mean().shift(1)
    above = (c > ma).astype(int)
    cross = (above == 1) & (above.shift(1) == 0)
    sig = cross & (ma_slope > 0) & (rs_slope > 0) & (v >= va10 * 1.5) & (va10 > 200_000)
    for d in px.index[sig]:
        ema_sigs.append({"symbol": sym, "signal_date": d, "entry_close": c.loc[d]})

ema_df = pd.DataFrame(ema_sigs)
ema_df["signal_date"] = pd.to_datetime(ema_df["signal_date"])
print(f"  150d EMA crossover signals: {len(ema_df)}")

# ── attach sector rank on signal date ──────────────────────────────────────
# join ss_df (which has sec_rank) on symbol+date
sec_lookup = ss_df[["date","symbol","sec_rank","sector_stage",
                     "rank_change","sector_rs_rank",
                     "close_above_ema50","ema50_slope_pos",
                     "near_pivot_days","avg_vol_10d"]].copy()
sec_lookup = sec_lookup.rename(columns={"date":"signal_date"})

ema_joined = ema_df.merge(sec_lookup, on=["symbol","signal_date"], how="left")
print(f"  After joining sector data: {len(ema_joined)} rows, "
      f"{ema_joined['sec_rank'].isna().sum()} missing sec_rank")

# Drop rows with no sector data
ema_joined = ema_joined.dropna(subset=["sec_rank"])
print(f"  After dropping missing sector: {len(ema_joined)}")

# ── CHECK 1: combined gate N ────────────────────────────────────────────────
print("\n" + "="*60)
print("CHECK 1 — COMBINED GATE SAMPLE SIZE")
print("="*60)

# Stock gates from stock_signals (not recomputed — using stored values as proxy)
# Note: 150d EMA crossover is the entry trigger; stock gates below are additional filters
gates = {
    "150d EMA only (base)": ema_joined,
    "+ sec_rank <= 8": ema_joined[ema_joined["sec_rank"] <= 8],
    "+ sec_rank<=8 + ema50_slope": ema_joined[
        (ema_joined["sec_rank"] <= 8) &
        (ema_joined["ema50_slope_pos"].fillna(0) == 1)],
    "+ sec_rank<=8 + ema50_slope + rank_chg>0": ema_joined[
        (ema_joined["sec_rank"] <= 8) &
        (ema_joined["ema50_slope_pos"].fillna(0) == 1) &
        (ema_joined["rank_change"].fillna(-999) > 0)],
    "+ sec_rank<=8 + ema50_slope + rank_chg>0 + sec_rs_rank<=5": ema_joined[
        (ema_joined["sec_rank"] <= 8) &
        (ema_joined["ema50_slope_pos"].fillna(0) == 1) &
        (ema_joined["rank_change"].fillna(-999) > 0) &
        (ema_joined["sector_rs_rank"].fillna(999) <= 5)],
    "FULL (all gates)": ema_joined[
        (ema_joined["sec_rank"] <= 8) &
        (ema_joined["ema50_slope_pos"].fillna(0) == 1) &
        (ema_joined["rank_change"].fillna(-999) > 0) &
        (ema_joined["sector_rs_rank"].fillna(999) <= 5) &
        (ema_joined["near_pivot_days"].fillna(0) >= 7) &
        (ema_joined["avg_vol_10d"].fillna(0) > 200_000)],
}

def fwd_returns(sdf):
    rows = []
    for _, r in sdf.iterrows():
        sym, d, ec = r["symbol"], r["signal_date"], r["entry_close"]
        if sym not in prices_map: continue
        fut = prices_map[sym]["close"][prices_map[sym]["close"].index > d]
        row = {"symbol": sym, "signal_date": d}
        for w in (60, 90, 120):
            row[f"fwd_{w}d"] = (fut.iloc[w-1] - ec) / ec * 100 if len(fut) >= w else np.nan
        rows.append(row)
    return pd.DataFrame(rows)

print("\nBuilding forward returns for each gate stage...")
results_c1 = {}
for label, sub in gates.items():
    print(f"  {label}: N={len(sub)}", end="", flush=True)
    fwd = fwd_returns(sub)
    results_c1[label] = fwd
    sub90 = fwd.dropna(subset=["fwd_90d"])
    n = len(sub90)
    if n == 0:
        print(f" -> 0 with 90d fwd")
        continue
    sub90 = sub90.copy()
    sub90["oc"] = sub90["fwd_90d"].apply(outcome)
    nw = (sub90["oc"]=="W").sum(); nl = (sub90["oc"]=="L").sum()
    wr = nw/n*100; lr = nl/n*100
    aw = sub90.loc[sub90["oc"]=="W","fwd_90d"].mean() if nw else 0
    al = sub90.loc[sub90["oc"]=="L","fwd_90d"].mean() if nl else 0
    ev = (nw/n)*aw + (nl/n)*al
    yrs = (sub90["signal_date"].max()-sub90["signal_date"].min()).days/365.25
    freq = n/yrs if yrs>0 else 0
    print(f" -> {n} with 90d  WR={wr:.1f}%  LR={lr:.1f}%  EV={ev:.2f}%  ({freq:.1f}/yr)")

# ── CHECK 2: breakeven bucket anatomy ─────────────────────────────────────
print("\n" + "="*60)
print("CHECK 2 — BREAKEVEN BUCKET ANATOMY (150d EMA, 90d window)")
print("="*60)

base_fwd = results_c1["150d EMA only (base)"]
sub90 = base_fwd.dropna(subset=["fwd_90d"]).copy()
sub90["oc"] = sub90["fwd_90d"].apply(outcome)
be = sub90[sub90["oc"]=="BE"]["fwd_90d"]

print(f"\n  Total 90d signals: {len(sub90)}")
print(f"  WINNER (>+6%):     {(sub90['oc']=='W').sum()} ({(sub90['oc']=='W').sum()/len(sub90)*100:.1f}%)")
print(f"  LOSER  (<-6%):     {(sub90['oc']=='L').sum()} ({(sub90['oc']=='L').sum()/len(sub90)*100:.1f}%)")
print(f"  BREAKEVEN:         {len(be)} ({len(be)/len(sub90)*100:.1f}%)")

print(f"\n  Breakeven bucket distribution:")
print(f"    Min:     {be.min():.1f}%")
print(f"    p5:      {be.quantile(0.05):.1f}%")
print(f"    p25:     {be.quantile(0.25):.1f}%")
print(f"    Median:  {be.median():.1f}%")
print(f"    p75:     {be.quantile(0.75):.1f}%")
print(f"    p95:     {be.quantile(0.95):.1f}%")
print(f"    Max:     {be.max():.1f}%")
print(f"    Mean:    {be.mean():.1f}%")
print(f"    Std:     {be.std():.1f}%")

# Bin breakdown
bins = [-6, -4, -2, 0, 2, 4, 6]
labels_b = ["-6 to -4%", "-4 to -2%", "-2 to 0%", "0 to +2%", "+2 to +4%", "+4 to +6%"]
counts = pd.cut(be, bins=bins, labels=labels_b).value_counts().sort_index()
print(f"\n  Distribution inside breakeven band:")
for lbl, cnt in counts.items():
    bar = "#" * int(cnt/2)
    print(f"    {lbl:>12}: {cnt:>4}  {bar}")

print(f"\n  Skew: {be.skew():.2f}  (positive = right-skewed, more near +6 than -6)")
print(f"  % of BE that are positive (0 to +6%): {(be > 0).sum()/len(be)*100:.1f}%")
print(f"  % of BE that are negative (-6 to 0%): {(be < 0).sum()/len(be)*100:.1f}%")

# Also check combined gate BE bucket
full_fwd = results_c1["FULL (all gates)"]
sub90_full = full_fwd.dropna(subset=["fwd_90d"]).copy()
if len(sub90_full) > 0:
    sub90_full["oc"] = sub90_full["fwd_90d"].apply(outcome)
    be_full = sub90_full[sub90_full["oc"]=="BE"]["fwd_90d"]
    print(f"\n  Combined-gate BE bucket (full gates):")
    print(f"    N={len(be_full)}  median={be_full.median():.1f}%  mean={be_full.mean():.1f}%  "
          f"std={be_full.std():.1f}%  pos={( be_full>0).sum()/len(be_full)*100:.1f}%")

# ── CHECK 3: out-of-sample temporal split ─────────────────────────────────
print("\n" + "="*60)
print("CHECK 3 — TEMPORAL OUT-OF-SAMPLE SPLIT")
print("="*60)
print("  Train: 2005-01-01 to 2015-12-31 (PSX pre-bull-run, mixed regime)")
print("  Test:  2016-01-01 to 2026-06-22 (includes 2016-17 bull, 2018-19 bear, 2020+ recovery)\n")

SPLIT_DATE = pd.Timestamp("2016-01-01")

def period_stats(fwd_df, label, period_name):
    sub = fwd_df.copy()
    if period_name == "train":
        sub = sub[sub["signal_date"] < SPLIT_DATE]
    else:
        sub = sub[sub["signal_date"] >= SPLIT_DATE]
    sub90 = sub.dropna(subset=["fwd_90d"])
    n = len(sub90)
    if n == 0:
        print(f"    {label} [{period_name}]: N=0")
        return
    sub90 = sub90.copy()
    sub90["oc"] = sub90["fwd_90d"].apply(outcome)
    nw = (sub90["oc"]=="W").sum(); nl = (sub90["oc"]=="L").sum()
    wr = nw/n*100; lr = nl/n*100
    aw = sub90.loc[sub90["oc"]=="W","fwd_90d"].mean() if nw else 0
    al = sub90.loc[sub90["oc"]=="L","fwd_90d"].mean() if nl else 0
    ev = (nw/n)*aw + (nl/n)*al
    avg = sub90["fwd_90d"].mean()
    yrs = (sub90["signal_date"].max()-sub90["signal_date"].min()).days/365.25
    freq_str = f"{n/yrs:.0f}/yr" if yrs > 0 else "n/a"
    print(f"    {label:55} [{period_name:5}] N={n:>4} ({freq_str})  WR={wr:.1f}%  LR={lr:.1f}%  EV={ev:.2f}%  AvgRet={avg:.2f}%")

variants_to_test = [
    ("150d EMA only", results_c1["150d EMA only (base)"]),
    ("150d EMA + sec_rank<=8", results_c1["+ sec_rank <= 8"]),
    ("150d EMA + full gates", results_c1["FULL (all gates)"]),
]

print("  Variant comparison across periods:")
for label, fdf in variants_to_test:
    period_stats(fdf, label, "train")
    period_stats(fdf, label, "test")
    print()

# Also compare 50d EMA vs 150d EMA across periods for reference
print("  50d EMA crossover (reference — prior implementation):")
ema50_sigs = []
for sym in universe:
    if sym not in prices_map: continue
    px = prices_map[sym]
    if len(px) < 60: continue
    c, v = px["close"], px["volume"]
    kse = idx.reindex(px.index).ffill()
    ma = ema_s(c, 50)
    ma_slope = (ma - ma.shift(5)) / ma.shift(5)
    rs = c / kse
    rs_slope = (rs - rs.shift(10)) / rs.shift(10)
    va10 = v.rolling(10, min_periods=5).mean().shift(1)
    above = (c > ma).astype(int)
    cross = (above==1) & (above.shift(1)==0)
    sig = cross & (ma_slope>0) & (rs_slope>0) & (v>=va10*1.5) & (va10>200_000)
    for d in px.index[sig]:
        ema50_sigs.append({"symbol": sym, "signal_date": d, "entry_close": c.loc[d]})

ema50_df = pd.DataFrame(ema50_sigs)
ema50_df["signal_date"] = pd.to_datetime(ema50_df["signal_date"])
ema50_fwd = fwd_returns(ema50_df)
period_stats(ema50_fwd, "50d EMA only (reference)", "train")
period_stats(ema50_fwd, "50d EMA only (reference)", "test")

# Bull/bear regime breakdown for context
print("\n  PSX regime context for the two periods:")
con2 = sqlite3.connect(DB_PATH)
reg = pd.read_sql("SELECT date, regime FROM market_regime", con2)
con2.close()
reg["date"] = pd.to_datetime(reg["date"])
for period_name, mask in [
    ("train (2005-2015)", reg["date"] < SPLIT_DATE),
    ("test  (2016-2026)", reg["date"] >= SPLIT_DATE),
]:
    sub = reg[mask]
    dist = sub["regime"].value_counts(normalize=True)*100
    td = dist.get("TRENDING_DOWN", 0)
    tu = dist.get("TRENDING_UP", 0)
    rg = dist.get("RANGING", 0)
    vl = dist.get("VOLATILE", 0)
    print(f"    {period_name}: TU={tu:.0f}%  TD={td:.0f}%  RG={rg:.0f}%  VL={vl:.0f}%")

print("\nDone.")
