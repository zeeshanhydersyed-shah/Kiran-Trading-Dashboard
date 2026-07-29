"""
boring_crowding_test.py — the pre-registered Momentum Crowding falsification
test, final locked design.

Speed and Protection: parallel, independent regressions on the SAME
winners-only (hit_tp_10=1) population, identical specification, both panels
(20d, 60d). Primary interpretation compares interaction magnitudes; neither
outcome is conditioned on the other in the primary analysis.

Volume acceleration: second half vs first half of the same 60d RS window
(days [-30,-1] vs [-60,-31] relative to entry), tested on the full panel
(not winners-restricted -- pre-entry, outcome-unconditional).

Tail saturation: pre-specified rule, edge(decile9) <= mean(edge(decile7),
edge(decile8)), applied to Speed.

Exploratory appendix only: MAE ~ Breakout + z(RS) + Breakout*z(RS) +
day_to_target -- NOT part of the decision rules.
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
prices = pd.read_sql_query("SELECT symbol, date, high, low, close, volume FROM prices_adjusted ORDER BY symbol, date", con)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(), "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float), "close": g["close"].to_numpy(dtype=float),
        "volume": g["volume"].to_numpy(dtype=float),
    }


def compute_row(sym, date):
    pf = by_symbol.get(sym)
    if pf is None:
        return None
    dates = pf["dates"]
    t = np.searchsorted(dates, date)
    if t >= len(dates) or dates[t] != date:
        return None
    entry = pf["close"][t]
    if entry is None or np.isnan(entry) or entry <= 0:
        return None
    n = len(dates)
    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j <= t:
        return None

    high, low, vol = pf["high"], pf["low"], pf["volume"]
    fwd_high = high[t + 1:end_j + 1]
    fwd_low = low[t + 1:end_j + 1]
    stop_level = entry * (1 + STOP)
    target_level = entry * (1 + TARGET)
    stop_hits = np.where(fwd_low <= stop_level)[0]
    target_hits = np.where(fwd_high >= target_level)[0]
    stop_day = stop_hits[0] if len(stop_hits) else None
    target_day = target_hits[0] if len(target_hits) else None

    hit_tp = 0
    day_to_target = np.nan
    race_mae = np.nan
    if target_day is not None and (stop_day is None or target_day < stop_day):
        hit_tp = 1
        day_to_target = target_day + 1  # +1 since fwd arrays are 0-indexed from t+1
        race_low = fwd_low[:target_day + 1]
        race_mae = (race_low.min() - entry) / entry * 100

    # volume acceleration: days [-30,-1] vs [-60,-31] relative to entry (t)
    vol_accel = np.nan
    if t >= 60:
        first_half = vol[t - 60:t - 30]
        second_half = vol[t - 30:t]
        fh_valid = first_half[~np.isnan(first_half)]
        sh_valid = second_half[~np.isnan(second_half)]
        if len(fh_valid) > 0 and fh_valid.mean() > 0 and len(sh_valid) > 0:
            vol_accel = sh_valid.mean() / fh_valid.mean()

    return hit_tp, day_to_target, race_mae, vol_accel


def build(panel_path):
    df = pd.read_csv(panel_path)
    print(f"{panel_path}: {len(df):,} rows")
    results = df.apply(lambda r: compute_row(r["symbol"], r["date"]), axis=1)
    valid = results.notna()
    df = df[valid].copy()
    vals = np.array(results[valid].tolist())
    df["hit_tp_10"] = vals[:, 0]
    df["day_to_target"] = vals[:, 1]
    df["race_mae"] = vals[:, 2]
    df["vol_accel"] = vals[:, 3]
    print(f"  computed for {len(df):,} rows; hit_tp_10 rate: {df['hit_tp_10'].mean():.4f}")
    return df


def zscore(s):
    return (s - s.mean()) / s.std()


def fit(y, X):
    return sm.OLS(y, sm.add_constant(X), missing="drop").fit()


def report(m, label, prev_r2=None):
    print(f"\n{'-'*90}\n{label}\n{'-'*90}")
    print(f"N={int(m.nobs):,}  R^2={m.rsquared:.5f}", end="")
    print(f"   Delta R^2 vs breakout-only={m.rsquared-prev_r2:+.5f}" if prev_r2 is not None else "")
    ci = m.conf_int()
    for name in m.params.index:
        print(f"  {name:<28} coef={m.params[name]:+.5f}  95% CI=[{ci.loc[name,0]:+.5f},{ci.loc[name,1]:+.5f}]  p={m.pvalues[name]:.4g}")
    return m.rsquared


def run_panel(panel_path, label):
    print(f"\n{'#'*90}\n# {label}\n{'#'*90}")
    df = build(panel_path)

    # ── Volume acceleration: full panel, outcome-unconditional ──
    dv = df.dropna(subset=["vol_accel"]).copy()
    dv["z_rs"] = zscore(dv["stock_rs"])
    dv["bo_x_rs"] = dv["breakout"] * dv["z_rs"]
    m1v = fit(dv["vol_accel"], dv[["breakout"]])
    r1v = report(m1v, "VOLUME: vol_accel ~ breakout")
    m2v = fit(dv["vol_accel"], dv[["breakout", "z_rs", "bo_x_rs"]])
    report(m2v, "VOLUME: vol_accel ~ breakout + z(RS) + breakout*z(RS)", r1v)

    # ── Winners-only subsample for Speed and Protection ──
    dw = df[df["hit_tp_10"] == 1].dropna(subset=["day_to_target", "race_mae", "stock_rs"]).copy()
    dw["z_rs"] = zscore(dw["stock_rs"])
    dw["bo_x_rs"] = dw["breakout"] * dw["z_rs"]
    print(f"\nWinners subsample: N={len(dw):,} (breakout={dw['breakout'].sum():,}, control={(dw['breakout']==0).sum():,})")

    # SPEED
    m1s = fit(dw["day_to_target"], dw[["breakout"]])
    r1s = report(m1s, "SPEED: day_to_target ~ breakout")
    m2s = fit(dw["day_to_target"], dw[["breakout", "z_rs", "bo_x_rs"]])
    report(m2s, "SPEED: day_to_target ~ breakout + z(RS) + breakout*z(RS)  [negative interaction = faster with RS]", r1s)

    # PROTECTION (parallel, uncontrolled)
    m1p = fit(dw["race_mae"], dw[["breakout"]])
    r1p = report(m1p, "PROTECTION: race_mae ~ breakout")
    m2p = fit(dw["race_mae"], dw[["breakout", "z_rs", "bo_x_rs"]])
    report(m2p, "PROTECTION: race_mae ~ breakout + z(RS) + breakout*z(RS)  [positive interaction = shallower drawdown with RS]", r1p)

    # EXPLORATORY APPENDIX ONLY -- not part of decision rules
    print("\n--- EXPLORATORY APPENDIX (not decisive, not part of decision rules) ---")
    m3p = fit(dw["race_mae"], dw[["breakout", "z_rs", "bo_x_rs", "day_to_target"]])
    report(m3p, "EXPLORATORY: race_mae ~ breakout + z(RS) + breakout*z(RS) + day_to_target")

    # Tail saturation: Speed edge by RS decile, pre-specified rule
    print(f"\n{'='*90}\nTail saturation check (pre-specified rule): edge(decile9) <= mean(edge(decile7),edge(decile8))\n{'='*90}")
    dw["rs_decile"] = pd.qcut(dw["stock_rs"], 10, labels=False, duplicates="drop")
    dec = dw.groupby(["rs_decile", "breakout"])["day_to_target"].mean().unstack()
    dec.columns = ["control_days", "breakout_days"]
    dec["speed_edge"] = dec["control_days"] - dec["breakout_days"]  # positive = breakout faster
    print(dec.round(3).to_string())
    if len(dec) >= 10:
        e9 = dec["speed_edge"].iloc[9]
        e78 = dec["speed_edge"].iloc[7:9].mean()
        saturation = e9 <= e78
        print(f"\nedge(decile9)={e9:.3f}  mean(edge(decile7,8))={e78:.3f}  -> SATURATION/REVERSAL: {saturation}")
    mono, mono_p = stats.spearmanr(np.arange(len(dec)), dec["speed_edge"].to_numpy())
    print(f"Spearman rank correlation (decile vs speed edge): rho={mono:.3f}, p={mono_p:.4g}")

    return {"m2s": m2s, "m2p": m2p, "m2v": m2v}


results_20d = run_panel("boring_heterogeneity_panel_20d.csv", "20d panel — PRIMARY")
results_60d = run_panel("boring_heterogeneity_panel_60d.csv", "60d panel — REPLICATION")

print(f"\n\n{'='*90}\nSUMMARY — interaction term comparison across panels\n{'='*90}")
for label, res in [("20d", results_20d), ("60d", results_60d)]:
    speed_int = res["m2s"].params["bo_x_rs"]
    speed_p = res["m2s"].pvalues["bo_x_rs"]
    prot_int = res["m2p"].params["bo_x_rs"]
    prot_p = res["m2p"].pvalues["bo_x_rs"]
    vol_int = res["m2v"].params["bo_x_rs"]
    vol_p = res["m2v"].pvalues["bo_x_rs"]
    print(f"\n{label}: Speed interaction={speed_int:+.4f} (p={speed_p:.4g})  "
          f"Protection interaction={prot_int:+.4f} (p={prot_p:.4g})  "
          f"Volume interaction={vol_int:+.4f} (p={vol_p:.4g})")

print("\n\nDone.")
