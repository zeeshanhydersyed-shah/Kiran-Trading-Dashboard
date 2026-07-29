"""
boring_structure_flow_test.py -- the pre-registered Technical Market
Structure test, plus the two still-open Persistent Directional Flow
components (volume-steadiness-by-RS pattern, low-volume subsample
robustness). Final locked design, run after Momentum Crowding's rejection.

All structure/volume proxies are computed from a window STRICTLY BEFORE
the entry day t (indices [t-252, t-1] or [t-60, t-1], never including t
or anything forward of it) -- identical computation for breakout=1 and
breakout=0 (control) rows, since both are just entry days with a forward
path. This keeps every proxy pre-treatment and outcome-independent; no
post-treatment conditioning, no collider.

Technical Structure decision rule (locked, boring_study_mechanism_prereg
Sec 6): structure proxies must (a) carry independent predictive power on
hit_tp_10, (b) shrink the breakout*z(RS) interaction more than an
equivalent volume-steadiness control does -- shrinkage alone, without that
comparison, does not uniquely implicate Class 2 (entanglement risk, Sec 5).

Persistent Flow: (a) is volume pattern steadier (lower CV, not just
non-accelerating -- acceleration already tested null in the Crowding run)
for high-RS breakouts; (b) does the RS-edge interaction survive restricted
to the lowest volume-level tercile specifically.

Reuses the exact matched panels (seed=42) with hit_tp_10 already computed:
boring_heterogeneity_panel_20d_race.csv / _60d_race.csv.
"""

import sqlite3
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

DB = "psx_data.db"
DIST_WINDOW = 252
CONSOL_WINDOW = 60

con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, high, low, close, volume FROM prices_adjusted ORDER BY symbol, date", con
)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
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

    high, low, close, vol = pf["high"], pf["low"], pf["close"], pf["volume"]

    dist_from_high = np.nan
    if t >= DIST_WINDOW:
        window_high = high[t - DIST_WINDOW:t]
        prior_high = np.nanmax(window_high)
        anchor = close[t - 1]
        if prior_high > 0 and not np.isnan(anchor):
            dist_from_high = (prior_high - anchor) / prior_high * 100

    consolidation = np.nan
    vol_cv = np.nan
    vol_level = np.nan
    if t >= CONSOL_WINDOW:
        wh = high[t - CONSOL_WINDOW:t]
        wl = low[t - CONSOL_WINDOW:t]
        anchor = close[t - 1]
        if not np.isnan(anchor) and anchor > 0:
            consolidation = (np.nanmax(wh) - np.nanmin(wl)) / anchor * 100

        wv = vol[t - CONSOL_WINDOW:t]
        wv = wv[~np.isnan(wv)]
        if len(wv) > 0 and wv.mean() > 0:
            vol_cv = wv.std() / wv.mean()
            vol_level = wv.mean()

    return dist_from_high, consolidation, vol_cv, vol_level


def build(panel_path):
    df = pd.read_csv(panel_path)
    print(f"{panel_path}: {len(df):,} rows")
    results = df.apply(lambda r: compute_row(r["symbol"], r["date"]), axis=1)
    valid = results.notna()
    df = df[valid].copy()
    vals = np.array(results[valid].tolist())
    df["dist_from_high"] = vals[:, 0]
    df["consolidation"] = vals[:, 1]
    df["vol_cv"] = vals[:, 2]
    df["vol_level"] = vals[:, 3]
    print(f"  proxies computed for {len(df):,} rows")
    return df


def zscore(s):
    return (s - s.mean()) / s.std()


def fit(y, X):
    return sm.OLS(y, sm.add_constant(X), missing="drop").fit()


def report(m, label, prev_r2=None):
    print(f"\n{'-'*90}\n{label}\n{'-'*90}")
    print(f"N={int(m.nobs):,}  R^2={m.rsquared:.5f}", end="")
    print(f"   Delta R^2 vs prior={m.rsquared-prev_r2:+.5f}" if prev_r2 is not None else "")
    ci = m.conf_int()
    for name in m.params.index:
        print(f"  {name:<28} coef={m.params[name]:+.5f}  95% CI=[{ci.loc[name,0]:+.5f},{ci.loc[name,1]:+.5f}]  p={m.pvalues[name]:.4g}")
    return m.rsquared


def partial_corr(x, y, z):
    rxy, _ = stats.pearsonr(x, y)
    rxz, _ = stats.pearsonr(x, z)
    ryz, _ = stats.pearsonr(y, z)
    return (rxy - rxz * ryz) / np.sqrt((1 - rxz**2) * (1 - ryz**2))


def run_panel(panel_path, label):
    print(f"\n{'#'*90}\n# {label}\n{'#'*90}")
    df = build(panel_path)

    # ================= TECHNICAL STRUCTURE =================
    ds = df.dropna(subset=["hit_tp_10", "stock_rs", "dist_from_high", "consolidation", "vol_cv"]).copy()
    ds["z_rs"] = zscore(ds["stock_rs"])
    ds["z_dist"] = zscore(ds["dist_from_high"])
    ds["z_consol"] = zscore(ds["consolidation"])
    ds["z_volcv"] = zscore(ds["vol_cv"])
    ds["bo_x_rs"] = ds["breakout"] * ds["z_rs"]
    ds["bo_x_dist"] = ds["breakout"] * ds["z_dist"]
    ds["bo_x_consol"] = ds["breakout"] * ds["z_consol"]
    ds["bo_x_volcv"] = ds["breakout"] * ds["z_volcv"]
    print(f"\nSTRUCTURE test subsample: N={len(ds):,} (breakout={ds['breakout'].sum():,}, control={(ds['breakout']==0).sum():,})")

    m0 = fit(ds["hit_tp_10"], ds[["breakout"]])
    r0 = report(m0, "MODEL 0: hit_tp_10 ~ breakout")

    m1 = fit(ds["hit_tp_10"], ds[["breakout", "z_rs", "bo_x_rs"]])
    r1 = report(m1, "MODEL 1 (baseline, this subsample): hit_tp_10 ~ breakout + z(RS) + breakout*z(RS)", r0)
    rs_int_baseline = m1.params["bo_x_rs"]

    m2 = fit(ds["hit_tp_10"], ds[["breakout", "z_rs", "bo_x_rs", "z_dist", "z_consol", "bo_x_dist", "bo_x_consol"]])
    r2 = report(m2, "MODEL 2: + z(dist_from_high) + z(consolidation) + breakout*each  [structure-controlled]", r1)
    rs_int_structure = m2.params["bo_x_rs"]

    m3 = fit(ds["hit_tp_10"], ds[["breakout", "z_rs", "bo_x_rs", "z_volcv", "bo_x_volcv"]])
    r3 = report(m3, "MODEL 3: + z(volume_cv) + breakout*z(volume_cv)  [volume-controlled, comparison arm]", r1)
    rs_int_volume = m3.params["bo_x_rs"]

    shrink_structure = 1 - (rs_int_structure / rs_int_baseline) if rs_int_baseline != 0 else np.nan
    shrink_volume = 1 - (rs_int_volume / rs_int_baseline) if rs_int_baseline != 0 else np.nan
    print(f"\nbreakout*z(RS) interaction: baseline={rs_int_baseline:+.5f}  "
          f"structure-controlled={rs_int_structure:+.5f} (shrink={shrink_structure:+.2%})  "
          f"volume-controlled={rs_int_volume:+.5f} (shrink={shrink_volume:+.2%})")
    print(f"Delta R^2: structure model={r2-r1:+.5f}  volume-comparison model={r3-r1:+.5f}")

    bo_only = ds[ds["breakout"] == 1]
    print(f"\nEntanglement check (breakout rows only, N={len(bo_only):,}):")
    print(f"  corr(RS, dist_from_high) = {stats.pearsonr(bo_only['stock_rs'], bo_only['dist_from_high'])[0]:+.4f}")
    print(f"  corr(RS, consolidation)  = {stats.pearsonr(bo_only['stock_rs'], bo_only['consolidation'])[0]:+.4f}")
    print(f"  corr(RS, volume_cv)      = {stats.pearsonr(bo_only['stock_rs'], bo_only['vol_cv'])[0]:+.4f}")

    print(f"\nStructure proxy decile check (breakout rows, dist_from_high, lower=closer to prior high=less overhead):")
    bo_only = bo_only.copy()
    bo_only["dist_decile"] = pd.qcut(bo_only["dist_from_high"], 10, labels=False, duplicates="drop")
    dec = bo_only.groupby("dist_decile")["hit_tp_10"].mean()
    print((dec * 100).round(2).to_string())
    mono, mono_p = stats.spearmanr(dec.index.to_numpy(), dec.to_numpy())
    print(f"Spearman rank correlation (dist_from_high decile vs hit rate): rho={mono:.3f}, p={mono_p:.4g}")

    # ================= PERSISTENT FLOW =================
    print(f"\n{'='*90}\nPERSISTENT FLOW -- (a) volume steadiness pattern by RS\n{'='*90}")
    dv = df.dropna(subset=["vol_cv", "stock_rs"]).copy()
    dv["z_rs"] = zscore(dv["stock_rs"])
    dv["bo_x_rs"] = dv["breakout"] * dv["z_rs"]
    mv1 = fit(dv["vol_cv"], dv[["breakout"]])
    rv1 = report(mv1, "VOL STEADINESS: vol_cv ~ breakout")
    mv2 = fit(dv["vol_cv"], dv[["breakout", "z_rs", "bo_x_rs"]])
    report(mv2, "VOL STEADINESS: vol_cv ~ breakout + z(RS) + breakout*z(RS)  [negative interaction = steadier (lower CV) with RS]", rv1)

    print(f"\n{'='*90}\nPERSISTENT FLOW -- (b) RS-edge interaction restricted to lowest volume-level tercile\n{'='*90}")
    df_terc = df.dropna(subset=["vol_level", "hit_tp_10", "stock_rs"]).copy()
    df_terc["vol_tercile"] = pd.qcut(df_terc["vol_level"], 3, labels=["low", "mid", "high"], duplicates="drop")
    print(df_terc.groupby("vol_tercile", observed=True)["vol_level"].agg(["count", "min", "max"]))

    for terc in ["low", "mid", "high"]:
        dt = df_terc[df_terc["vol_tercile"] == terc].copy()
        dt["z_rs"] = zscore(dt["stock_rs"])
        dt["bo_x_rs"] = dt["breakout"] * dt["z_rs"]
        m = fit(dt["hit_tp_10"], dt[["breakout", "z_rs", "bo_x_rs"]])
        report(m, f"hit_tp_10 ~ breakout + z(RS) + breakout*z(RS)  [{terc}-volume tercile, N={len(dt):,}]")

    return {
        "rs_int_baseline": rs_int_baseline, "rs_int_structure": rs_int_structure, "rs_int_volume": rs_int_volume,
        "shrink_structure": shrink_structure, "shrink_volume": shrink_volume,
        "m2": m2, "vol_cv_interaction": mv2.params["bo_x_rs"], "vol_cv_p": mv2.pvalues["bo_x_rs"],
    }


results_20d = run_panel("boring_heterogeneity_panel_20d_race.csv", "20d panel -- PRIMARY")
results_60d = run_panel("boring_heterogeneity_panel_60d_race.csv", "60d panel -- REPLICATION")

print(f"\n\n{'='*90}\nSUMMARY -- cross-panel comparison\n{'='*90}")
for label, res in [("20d", results_20d), ("60d", results_60d)]:
    print(f"\n{label}:")
    print(f"  RS interaction: baseline={res['rs_int_baseline']:+.4f}  "
          f"structure-controlled={res['rs_int_structure']:+.4f} (shrink {res['shrink_structure']:+.1%})  "
          f"volume-controlled={res['rs_int_volume']:+.4f} (shrink {res['shrink_volume']:+.1%})")
    for term in ["z_dist", "z_consol", "bo_x_dist", "bo_x_consol"]:
        print(f"  structure model term {term:<12} coef={res['m2'].params[term]:+.5f}  p={res['m2'].pvalues[term]:.4g}")
    print(f"  vol_cv-by-RS interaction={res['vol_cv_interaction']:+.4f}  p={res['vol_cv_p']:.4g}")

print("\n\nDone.")
