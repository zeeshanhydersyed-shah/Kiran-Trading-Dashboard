"""
boring_heterogeneity_panel.py — builds the stacked breakout+control panel
needed to test whether the ALREADY-ESTABLISHED breakout edge (vs a matched
random control) varies across Stock RS and Directional Volatility Ratio.

Every definition reused verbatim from prior, already-locked work -- nothing
new engineered:
  - Donchian breakout: close[t] > 1.01 * max(high[t-LOOKBACK:t])
  - Matched control: same stock, same regime, random non-breakout day, seed=42
  - Outcome: stop-managed return (-6% capped exit if stopped, else close at
    day 90) -- same as boring_donchian_mechanism_data.py
  - Stock RS: trailing 60d stock return minus trailing 60d KSE-100 return
  - Directional Volatility Ratio: up_semivol / down_semivol (trailing 60d
    semi-deviation of daily returns)
  - Liquidity (negative-control variable): trailing 60d average volume

The only thing new here is STACKING breakout and control rows into one
panel with a Breakout(0/1) indicator, and computing RS/vol-ratio/liquidity
for control rows too (previously only computed for breakout rows) -- a
necessary consolidation to test edge heterogeneity, not new feature
engineering.

Read-only against psx_data.db.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
BUFFER = 1.01
STOP = -0.06
MAX_HORIZON = 90
WINDOW = 60
SEED = 42
REGIMES = ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]


def build_panel(lookback):
    print(f"\n{'='*80}\nBuilding stacked panel for lookback={lookback}d\n{'='*80}")
    con = sqlite3.connect(DB)
    prices = pd.read_sql_query("SELECT symbol, date, high, low, close, volume FROM prices_adjusted ORDER BY symbol, date", con)
    regime_df = pd.read_sql_query("SELECT date, regime FROM market_regime ORDER BY date", con)
    idx = pd.read_sql_query("SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
    con.close()
    regime_lookup = dict(zip(regime_df["date"], regime_df["regime"]))
    idx = idx.sort_values("date").reset_index(drop=True)
    idx["idx_ret60"] = idx["close"].pct_change(WINDOW) * 100
    idx_ret_lookup = dict(zip(idx["date"], idx["idx_ret60"]))

    by_symbol = {}
    for sym, g in prices.groupby("symbol"):
        g = g.sort_values("date").reset_index(drop=True)
        close = g["close"].to_numpy(dtype=float)
        high = g["high"].to_numpy(dtype=float)
        low = g["low"].to_numpy(dtype=float)
        vol = g["volume"].to_numpy(dtype=float)
        dates = g["date"].to_numpy()
        n = len(close)

        ret60 = np.full(n, np.nan)
        base_c = close[:-WINDOW] if n > WINDOW else np.array([])
        if len(base_c):
            valid = base_c != 0
            ret60[WINDOW:][valid] = (close[WINDOW:][valid] - base_c[valid]) / base_c[valid] * 100

        daily_ret = np.full(n, np.nan)
        prev = close[:-1]
        safe = prev != 0
        daily_ret[1:][safe] = (close[1:][safe] - prev[safe]) / prev[safe] * 100
        up_sq = np.where(~np.isnan(daily_ret) & (daily_ret > 0), daily_ret ** 2, np.where(np.isnan(daily_ret), np.nan, 0.0))
        down_sq = np.where(~np.isnan(daily_ret) & (daily_ret < 0), daily_ret ** 2, np.where(np.isnan(daily_ret), np.nan, 0.0))
        up_semivol = np.sqrt(pd.Series(up_sq).rolling(WINDOW, min_periods=WINDOW).mean().to_numpy())
        down_semivol = np.sqrt(pd.Series(down_sq).rolling(WINDOW, min_periods=WINDOW).mean().to_numpy())
        avgvol60 = pd.Series(vol).rolling(WINDOW, min_periods=WINDOW).mean().to_numpy()

        by_symbol[sym] = {
            "dates": dates, "close": close, "high": high, "low": low,
            "ret60": ret60, "up_semivol": up_semivol, "down_semivol": down_semivol,
            "avgvol60": avgvol60,
        }

    def stock_rs_at(sym, pos):
        pf = by_symbol[sym]
        d = pf["dates"][pos]
        r = pf["ret60"][pos]
        idx_r = idx_ret_lookup.get(d)
        if r is None or np.isnan(r) or idx_r is None:
            return np.nan
        return r - idx_r

    def vol_ratio_at(sym, pos):
        pf = by_symbol[sym]
        up, down = pf["up_semivol"][pos], pf["down_semivol"][pos]
        if up is None or down is None or np.isnan(up) or np.isnan(down) or down == 0:
            return np.nan
        return up / down

    def liquidity_at(sym, pos):
        return by_symbol[sym]["avgvol60"][pos]

    def stop_managed_return(sym, entry, t):
        pf = by_symbol[sym]
        high, low, close = pf["high"], pf["low"], pf["close"]
        n = len(high)
        end_j = min(t + MAX_HORIZON, n - 1)
        if end_j <= t:
            return None
        stop_level = entry * (1 + STOP)
        fwd_low = low[t + 1:end_j + 1]
        if np.any(fwd_low <= stop_level):
            return STOP * 100
        exit_close = close[end_j]
        if exit_close is None or np.isnan(exit_close):
            return None
        return (exit_close - entry) / entry * 100

    print("Finding breakout occurrences...")
    occs = []
    for sym, pf in by_symbol.items():
        high, close, dates = pf["high"], pf["close"], pf["dates"]
        n = len(dates)
        if n < lookback + 1:
            continue
        prior_high = pd.Series(high).shift(1).rolling(lookback).max().to_numpy()
        for t in range(lookback, n):
            ph = prior_high[t]
            if np.isnan(ph) or ph <= 0 or np.isnan(close[t]):
                continue
            if close[t] > ph * BUFFER:
                d = dates[t]
                regime = regime_lookup.get(d)
                if regime not in REGIMES:
                    continue
                occs.append((sym, d, close[t], t, regime))
    occ_df = pd.DataFrame(occs, columns=["symbol", "date", "entry_close", "t_idx", "regime"])
    print(f"  {len(occ_df):,} breakout occurrences")
    breakout_days = set(zip(occ_df["symbol"], occ_df["date"]))

    print("Generating matched controls (same stock, same regime, seed=42)...")
    rng = np.random.default_rng(SEED)
    rows = []
    for _, row in occ_df.iterrows():
        sym, d, entry, t, regime = row["symbol"], row["date"], row["entry_close"], row["t_idx"], row["regime"]
        pf = by_symbol[sym]
        dates = pf["dates"]
        n = len(dates)
        candidate_idxs = np.arange(lookback, n)
        valid = [i for i in candidate_idxs
                 if regime_lookup.get(dates[i]) == regime and (sym, dates[i]) not in breakout_days]
        if not valid:
            continue
        t_ctrl = int(rng.choice(valid))
        entry_ctrl = pf["close"][t_ctrl]
        if entry_ctrl is None or np.isnan(entry_ctrl) or entry_ctrl <= 0:
            continue

        bo_outcome = stop_managed_return(sym, entry, t)
        ct_outcome = stop_managed_return(sym, entry_ctrl, t_ctrl)
        if bo_outcome is None or ct_outcome is None:
            continue

        rows.append({"symbol": sym, "date": d, "breakout": 1, "regime": regime,
                      "outcome": bo_outcome, "stock_rs": stock_rs_at(sym, t),
                      "vol_ratio": vol_ratio_at(sym, t), "liquidity": liquidity_at(sym, t)})
        rows.append({"symbol": sym, "date": dates[t_ctrl], "breakout": 0, "regime": regime,
                      "outcome": ct_outcome, "stock_rs": stock_rs_at(sym, t_ctrl),
                      "vol_ratio": vol_ratio_at(sym, t_ctrl), "liquidity": liquidity_at(sym, t_ctrl)})

    panel = pd.DataFrame(rows)
    panel["lookback"] = lookback
    print(f"  Panel rows: {len(panel):,} ({panel['breakout'].sum():,} breakout, "
          f"{(panel['breakout']==0).sum():,} control)")
    return panel


if __name__ == "__main__":
    panel20 = build_panel(20)
    panel20.to_csv("boring_heterogeneity_panel_20d.csv", index=False)
    print("\nSaved boring_heterogeneity_panel_20d.csv")

    panel60 = build_panel(60)
    panel60.to_csv("boring_heterogeneity_panel_60d.csv", index=False)
    print("\nSaved boring_heterogeneity_panel_60d.csv")

    print("\nDone.")
