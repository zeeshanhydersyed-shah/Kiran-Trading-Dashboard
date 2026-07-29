"""
boring_donchian_mechanism_data.py — Stage 1: build the full analysis
dataset for the "what explains breakout edge beyond rarity" investigation.

Produces boring_donchian_mechanism_dataset.csv, one row per breakout
occurrence (pooled across all 5 lookbacks x 4 regimes), with:
  - response: paired stop-managed return difference (breakout - control)
  - rarity: -log2(same-day, same-lookback breakout density)
  - 7 market/environment variables (computed once per date, joined)
  - 2 setup-quality variables (base_duration, breakout_magnitude_pct)

Per pre-registered plan (see conversation). Read-only against psx_data.db.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
LOOKBACKS = [10, 20, 40, 60, 120]
BUFFER = 1.01
STOP = -0.06
MAX_HORIZON = 90
SEED = 42
REGIMES = ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]
BASE_DURATION_BAND = 0.10  # within 10% of eventual breakout level

print("Loading prices_adjusted, market_regime, sectors...")
con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, high, low, close FROM prices_adjusted ORDER BY symbol, date", con
)
regime_df = pd.read_sql_query("SELECT date, regime, atr_pct FROM market_regime ORDER BY date", con)
sectors_df = pd.read_sql_query("SELECT symbol, sector FROM sectors", con)
con.close()
regime_lookup = dict(zip(regime_df["date"], regime_df["regime"]))
atr_lookup = dict(zip(regime_df["date"], regime_df["atr_pct"]))
sector_lookup = dict(zip(sectors_df["symbol"], sectors_df["sector"]))
print(f"Loaded {len(prices):,} price rows, {prices['symbol'].nunique():,} symbols, "
      f"{len(regime_df):,} regime days\n")

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }
all_dates_sorted = sorted(regime_df["date"].tolist())
date_to_pos = {d: i for i, d in enumerate(all_dates_sorted)}

# ══════════════════════════════════════════════════════════════════════
# Stage A: daily market-environment table (once per date, ~5,320 rows)
# ══════════════════════════════════════════════════════════════════════
print("Building daily market-environment table (breadth, dispersion, "
      "participation, correlation)...")

# daily return per symbol, and 50d MA flag, and 252d-high flag
sym_daily = {}
for sym, pf in by_symbol.items():
    close = pf["close"]
    dates = pf["dates"]
    n = len(close)
    ret = np.full(n, np.nan)
    prev_close = close[:-1]
    safe = prev_close != 0
    ret[1:][safe] = (close[1:][safe] - prev_close[safe]) / prev_close[safe] * 100
    ma50 = pd.Series(close).rolling(50).mean().to_numpy()
    above_ma50 = close > ma50
    high252 = pd.Series(pf["high"]).rolling(252).max().to_numpy()
    new_high_252 = pf["high"] >= high252  # today's high == rolling max incl. today -> new high
    sym_daily[sym] = pd.DataFrame({
        "date": dates, "ret": ret, "above_ma50": above_ma50, "new_high_252": new_high_252,
    })

daily_long = pd.concat(sym_daily.values(), ignore_index=True)
daily_long = daily_long.dropna(subset=["ret"])

env = daily_long.groupby("date").agg(
    breadth=("above_ma50", "mean"),
    dispersion=("ret", "std"),
    participation=("new_high_252", "mean"),
    mkt_ret=("ret", "mean"),
    n_stocks=("ret", "count"),
).reset_index()
env["breadth"] *= 100
env["participation"] *= 100
print(f"  Daily environment table: {len(env):,} dates")

# average correlation: trailing-20d correlation of each stock's return with
# the equal-weighted market return (mkt_ret), averaged across the universe,
# per date. Cheaper O(n) proxy for full pairwise correlation.
print("  Computing average correlation (20d trailing, vs equal-weighted market)...")
mkt_ret_by_date = dict(zip(env["date"], env["mkt_ret"]))
corr_rows = []
for sym, pf in by_symbol.items():
    d = sym_daily[sym]
    d = d.dropna(subset=["ret"]).reset_index(drop=True)
    d["mkt_ret"] = d["date"].map(mkt_ret_by_date)
    d = d.dropna(subset=["mkt_ret"])
    if len(d) < 25:
        continue
    roll_corr = d["ret"].rolling(20).corr(d["mkt_ret"])
    corr_rows.append(pd.DataFrame({"date": d["date"].to_numpy(), "corr": roll_corr.to_numpy()}))
corr_long = pd.concat(corr_rows, ignore_index=True).dropna()
avg_corr = corr_long.groupby("date")["corr"].mean().reset_index().rename(columns={"corr": "avg_correlation"})
env = env.merge(avg_corr, on="date", how="left")
print(f"  Correlation merged. Environment table columns: {env.columns.tolist()}")

# trend persistence: days since last regime transition (recomputed fresh
# from the raw regime label sequence, NOT the flagged-unreliable regime_days
# column -- same reasoning as the earlier regime work in this thread)
reg_sorted = regime_df.sort_values("date").reset_index(drop=True)
days_since = np.zeros(len(reg_sorted), dtype=int)
for i in range(1, len(reg_sorted)):
    if reg_sorted["regime"].iat[i] == reg_sorted["regime"].iat[i - 1]:
        days_since[i] = days_since[i - 1] + 1
reg_sorted["trend_persistence"] = days_since
env = env.merge(reg_sorted[["date", "regime", "atr_pct", "trend_persistence"]],
                 on="date", how="left")
env = env.rename(columns={"atr_pct": "volatility_level"})
env.to_csv("boring_donchian_daily_environment.csv", index=False)
print(f"  Saved daily environment table: {len(env):,} rows\n")

env_lookup = env.set_index("date")[
    ["breadth", "dispersion", "participation", "avg_correlation",
     "trend_persistence", "volatility_level"]
].to_dict("index")

print("Stage A complete.\n")
print("=" * 80)
print("Stage B: breakout occurrences x 5 lookbacks, per-(lookback,date) rarity "
      "and sector concentration, matched controls, stop-managed returns, "
      "base duration, breakout magnitude")
print("=" * 80)


def find_breakouts(lookback):
    occs = []
    for sym, pf in by_symbol.items():
        high, close, dates = pf["high"], pf["close"], pf["dates"]
        n = len(dates)
        if n < lookback + 1:
            continue
        prior_high = pd.Series(high).shift(1).rolling(lookback).max().to_numpy()
        c_ok = ~np.isnan(close)
        for t in range(lookback, n):
            ph = prior_high[t]
            if np.isnan(ph) or ph <= 0 or not c_ok[t]:
                continue
            if close[t] > ph * BUFFER:
                d = dates[t]
                occs.append((sym, d, close[t], ph, t, regime_lookup.get(d)))
    return pd.DataFrame(occs, columns=["symbol", "date", "entry_close", "prior_high", "t_idx", "regime"])


def stop_managed_return(sym, entry, t):
    pf = by_symbol.get(sym)
    if pf is None:
        return None
    high, low, close = pf["high"], pf["low"], pf["close"]
    n = len(high)
    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j <= t:
        return None
    stop_level = entry * (1 + STOP)
    fwd_low = low[t + 1:end_j + 1]
    stop_hits = np.where(fwd_low <= stop_level)[0]
    if len(stop_hits):
        return STOP * 100  # capped exit at exactly -6%
    exit_close = close[end_j]
    if exit_close is None or np.isnan(exit_close):
        return None
    return (exit_close - entry) / entry * 100


def base_duration(sym, t, breakout_level):
    pf = by_symbol.get(sym)
    close = pf["close"]
    band_lo = breakout_level * (1 - BASE_DURATION_BAND)
    cnt = 0
    i = t - 1
    while i >= 0:
        c = close[i]
        if c is None or np.isnan(c) or c < band_lo or c > breakout_level:
            break
        cnt += 1
        i -= 1
    return cnt


all_rows = []
for lb in LOOKBACKS:
    print(f"\nLookback {lb}d...")
    occ = find_breakouts(lb)
    print(f"  {len(occ):,} occurrences")
    breakout_days = set(zip(occ["symbol"], occ["date"]))

    # rarity + sector concentration, per (lookback, date)
    occ_by_date = occ.groupby("date")
    # eligible universe size per date for this lookback (for rarity denominator)
    elig_count_per_date = {}
    for sym, pf in by_symbol.items():
        dates = pf["dates"]
        n = len(dates)
        if n <= lb:
            continue
        for d in dates[lb:]:
            elig_count_per_date[d] = elig_count_per_date.get(d, 0) + 1

    rarity_per_date = {}
    sector_conc_per_date = {}
    for d, g in occ_by_date:
        n_bo = len(g)
        n_elig = elig_count_per_date.get(d, n_bo)
        rate = n_bo / n_elig if n_elig else np.nan
        rarity_per_date[d] = -np.log2(rate) if rate and rate > 0 else np.nan
        secs = g["symbol"].map(sector_lookup)
        vc = secs.value_counts(normalize=True)
        sector_conc_per_date[d] = float((vc ** 2).sum())  # Herfindahl

    # control group: same stock, same regime, random non-breakout day
    rng = np.random.default_rng(SEED)
    eligible_pool = {}
    for sym, pf in by_symbol.items():
        dates = pf["dates"]
        n = len(dates)
        idxs = np.arange(lb, n)
        eligible_pool[sym] = idxs  # filtered per-occurrence below (regime + not-breakout)

    n_dropped = 0
    for _, row in occ.iterrows():
        sym, d, entry, prior_high, t, regime = (
            row["symbol"], row["date"], row["entry_close"], row["prior_high"],
            row["t_idx"], row["regime"],
        )
        if regime not in REGIMES:
            continue

        pf = by_symbol[sym]
        dates = pf["dates"]
        candidate_idxs = eligible_pool[sym]
        # filter: same regime, not itself a breakout day for this lookback
        valid = [i for i in candidate_idxs
                 if regime_lookup.get(dates[i]) == regime and (sym, dates[i]) not in breakout_days]
        if not valid:
            n_dropped += 1
            continue
        t_ctrl = int(rng.choice(valid))
        entry_ctrl = pf["close"][t_ctrl]
        if entry_ctrl is None or np.isnan(entry_ctrl) or entry_ctrl <= 0:
            n_dropped += 1
            continue

        bo_ret = stop_managed_return(sym, entry, t)
        ct_ret = stop_managed_return(sym, entry_ctrl, t_ctrl)
        if bo_ret is None or ct_ret is None:
            n_dropped += 1
            continue

        env_vals = env_lookup.get(d)
        if env_vals is None:
            n_dropped += 1
            continue

        bd = base_duration(sym, t, prior_high)
        magnitude = (entry / prior_high - 1) * 100

        all_rows.append({
            "lookback": lb, "symbol": sym, "date": d, "regime": regime,
            "response": bo_ret - ct_ret,
            "rarity": rarity_per_date.get(d, np.nan),
            "sector_concentration": sector_conc_per_date.get(d, np.nan),
            "breadth": env_vals["breadth"], "dispersion": env_vals["dispersion"],
            "participation": env_vals["participation"],
            "avg_correlation": env_vals["avg_correlation"],
            "trend_persistence": env_vals["trend_persistence"],
            "volatility_level": env_vals["volatility_level"],
            "base_duration": bd, "breakout_magnitude_pct": magnitude,
        })
    print(f"  Matched + computed: {len(all_rows):,} cumulative rows, dropped this lookback: {n_dropped:,}")

df = pd.DataFrame(all_rows)
df.to_csv("boring_donchian_mechanism_dataset.csv", index=False)
print(f"\n\nFinal dataset: {len(df):,} rows")
print(df.isna().sum())
print("\nSaved to boring_donchian_mechanism_dataset.csv")
print("Stage 1 done.")
