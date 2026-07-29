"""
boring_heterogeneity_tp_race.py — repeats the heterogeneity analysis with
the ORIGINAL TP-before-stop race outcome instead of stop-managed return.

Reuses the EXACT same panel rows (same symbol/date/breakout pairs, from
the same seed=42 matched-control generation) already saved in
boring_heterogeneity_panel_20d.csv / _60d.csv -- only the outcome computed
on each row changes. This guarantees the comparison isolates the effect
of the dependent-variable change, not a different random draw.

hit_tp_10 = 1 if the row's own trade (breakout OR control, using its own
entry price and forward path) hits +10% before -6%, tie broken in favor
of the stop (same convention as every race computation this whole study).
0 otherwise (stop-first or neither).
"""

import sqlite3
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

DB = "psx_data.db"
STOP = -0.06
TARGET = 0.10
MAX_HORIZON = 90

con = sqlite3.connect(DB)
prices = pd.read_sql_query("SELECT symbol, date, high, low, close FROM prices_adjusted ORDER BY symbol, date", con)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(), "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float), "close": g["close"].to_numpy(dtype=float),
    }


def race_outcome(sym, date):
    pf = by_symbol.get(sym)
    if pf is None:
        return np.nan
    dates = pf["dates"]
    idx = np.searchsorted(dates, date)
    if idx >= len(dates) or dates[idx] != date:
        return np.nan
    entry = pf["close"][idx]
    if entry is None or np.isnan(entry) or entry <= 0:
        return np.nan
    n = len(dates)
    end_j = min(idx + MAX_HORIZON, n - 1)
    if end_j <= idx:
        return np.nan
    fwd_high = pf["high"][idx + 1:end_j + 1]
    fwd_low = pf["low"][idx + 1:end_j + 1]
    stop_level = entry * (1 + STOP)
    target_level = entry * (1 + TARGET)
    stop_hits = np.where(fwd_low <= stop_level)[0]
    target_hits = np.where(fwd_high >= target_level)[0]
    stop_day = stop_hits[0] if len(stop_hits) else None
    target_day = target_hits[0] if len(target_hits) else None
    if target_day is not None and (stop_day is None or target_day < stop_day):
        return 1
    return 0  # stop-first or neither


def add_race_outcome(panel_path, out_path):
    df = pd.read_csv(panel_path)
    print(f"{panel_path}: {len(df):,} rows")
    df["hit_tp_10"] = [race_outcome(s, d) for s, d in zip(df["symbol"], df["date"])]
    print(f"  hit_tp_10 non-null: {df['hit_tp_10'].notna().sum():,} / {len(df):,}")
    df.to_csv(out_path, index=False)
    return df


df20 = add_race_outcome("boring_heterogeneity_panel_20d.csv", "boring_heterogeneity_panel_20d_race.csv")
df60 = add_race_outcome("boring_heterogeneity_panel_60d.csv", "boring_heterogeneity_panel_60d_race.csv")


def zscore(s):
    return (s - s.mean()) / s.std()


def fit(y, X):
    return sm.OLS(y, sm.add_constant(X), missing="drop").fit()


def report_model(m, label, prev_r2=None):
    print(f"\n{'-'*90}\n{label}\n{'-'*90}")
    print(f"N={int(m.nobs):,}  R^2={m.rsquared:.5f}", end="")
    print(f"   Delta R^2 vs previous={m.rsquared-prev_r2:+.5f}" if prev_r2 is not None else "")
    ci = m.conf_int()
    for name in m.params.index:
        print(f"  {name:<28} coef={m.params[name]:+.5f}  95% CI=[{ci.loc[name,0]:+.5f},{ci.loc[name,1]:+.5f}]  p={m.pvalues[name]:.4g}")
    return m.rsquared


def run_workflow(df, varname, label):
    print(f"\n{'#'*90}\n# WORKFLOW: {label}\n{'#'*90}")
    d = df.dropna(subset=["hit_tp_10", "breakout", varname]).copy()
    print(f"N={len(d):,}  breakout={d['breakout'].sum():,}  control={(d['breakout']==0).sum():,}")
    print(f"Overall hit_tp_10 rate: breakout={d[d['breakout']==1]['hit_tp_10'].mean():.4f}  "
          f"control={d[d['breakout']==0]['hit_tp_10'].mean():.4f}")
    d["z"] = zscore(d[varname])
    d["bo_x_z"] = d["breakout"] * d["z"]
    m1 = fit(d["hit_tp_10"], d[["breakout"]])
    r1 = report_model(m1, "MODEL 1: hit_tp_10 ~ breakout")
    m2 = fit(d["hit_tp_10"], d[["breakout", "z", "bo_x_z"]])
    r2 = report_model(m2, f"MODEL 2: hit_tp_10 ~ breakout + {varname}(z) + breakout*{varname}(z)", r1)
    return d, m1, m2


# PRIMARY: 20d, Stock RS
d20, m1_20, m2_20 = run_workflow(df20, "stock_rs", "Primary (TP-race outcome) — Stock RS, 20d")

print(f"\n{'='*90}\nANALYSIS 1 — Functional form: P(hit TP before stop) by RS decile\n{'='*90}")
d20["rs_decile"] = pd.qcut(d20["stock_rs"], 10, labels=False, duplicates="drop")
dec = d20.groupby(["rs_decile", "breakout"])["hit_tp_10"].mean().unstack()
dec.columns = ["control_rate", "breakout_rate"]
dec["edge"] = dec["breakout_rate"] - dec["control_rate"]
print((dec * 100).round(2).to_string())
mono, mono_p = stats.spearmanr(np.arange(len(dec)), dec["edge"].to_numpy())
print(f"Spearman rank correlation (decile vs edge): rho={mono:.3f}, p={mono_p:.4g}")

print(f"\n{'='*90}\nANALYSIS 2/3 — add Directional Volatility Ratio; independence from RS\n{'='*90}")
d20v = d20.dropna(subset=["vol_ratio"]).copy()
d20v["z_rs"] = zscore(d20v["stock_rs"])
d20v["z_vr"] = zscore(d20v["vol_ratio"])
d20v["bo_x_rs"] = d20v["breakout"] * d20v["z_rs"]
d20v["bo_x_vr"] = d20v["breakout"] * d20v["z_vr"]
m2s = fit(d20v["hit_tp_10"], d20v[["breakout", "z_rs", "bo_x_rs"]])
r_m2 = report_model(m2s, "MODEL 2 (refit on vol_ratio-complete subsample)")
m3 = fit(d20v["hit_tp_10"], d20v[["breakout", "z_rs", "bo_x_rs", "z_vr", "bo_x_vr"]])
report_model(m3, "MODEL 3: + Directional Volatility Ratio (z) + breakout*ratio(z)", r_m2)

bo_only = d20v[d20v["breakout"] == 1]
def partial_corr(x, y, z):
    rxy,_ = stats.pearsonr(x,y); rxz,_ = stats.pearsonr(x,z); ryz,_ = stats.pearsonr(y,z)
    return (rxy - rxz*ryz) / np.sqrt((1-rxz**2)*(1-ryz**2))
raw_r = stats.pearsonr(bo_only["vol_ratio"], bo_only["hit_tp_10"])[0]
pc = partial_corr(bo_only["vol_ratio"], bo_only["hit_tp_10"], bo_only["stock_rs"])
print(f"\nRaw corr(vol_ratio, hit_tp_10 | breakout rows) = {raw_r:.4f}")
print(f"Partial corr(vol_ratio, hit_tp_10 | stock_rs, breakout rows) = {pc:.4f}")

print(f"\n{'='*90}\nANALYSIS 4 — Robustness: decile check, Directional Volatility Ratio\n{'='*90}")
d20v["vr_decile"] = pd.qcut(d20v["vol_ratio"], 10, labels=False, duplicates="drop")
decvr = d20v.groupby(["vr_decile", "breakout"])["hit_tp_10"].mean().unstack()
decvr.columns = ["control_rate", "breakout_rate"]
decvr["edge"] = decvr["breakout_rate"] - decvr["control_rate"]
print((decvr * 100).round(2).to_string())
monovr, monovr_p = stats.spearmanr(np.arange(len(decvr)), decvr["edge"].to_numpy())
print(f"Spearman rank correlation (vol_ratio decile vs edge): rho={monovr:.3f}, p={monovr_p:.4g}")

# NEGATIVE CONTROL: liquidity
d20_liq, m1liq, m2liq = run_workflow(df20, "liquidity", "NEGATIVE CONTROL (TP-race outcome) — Liquidity, 20d")

# CROSS-DEFINITION: 60d
d60, m1_60, m2_60 = run_workflow(df60, "stock_rs", "Cross-definition check (TP-race outcome) — Stock RS, 60d")
d60["rs_decile"] = pd.qcut(d60["stock_rs"], 10, labels=False, duplicates="drop")
dec60 = d60.groupby(["rs_decile", "breakout"])["hit_tp_10"].mean().unstack()
dec60.columns = ["control_rate", "breakout_rate"]
dec60["edge"] = dec60["breakout_rate"] - dec60["control_rate"]
print(f"\n{'='*90}\n60d panel (TP-race outcome) — edge by RS decile\n{'='*90}")
print((dec60 * 100).round(2).to_string())
mono60, mono60_p = stats.spearmanr(np.arange(len(dec60)), dec60["edge"].to_numpy())
print(f"Spearman rank correlation (60d, TP-race): rho={mono60:.3f}, p={mono60_p:.4g}")

print("\n\nDone.")
