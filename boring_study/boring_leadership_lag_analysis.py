"""
boring_leadership_lag_analysis.py — temporal-direction test for the
Sector RS -> Stock RS -> volatility-signature structure. Predictor-only,
no breakout outcome or forward return touched anywhere in this script.

1. Lag sweep: Stock RS ~ Lagged Sector RS(L), L in [10,20,40,60,90]
2. Incremental info: Model A (current sector_rs) vs Model B (+ lagged)
3. Residual leadership: Stock RS - E[Stock RS | current Sector RS],
   characterized (distribution, vs liquidity, vs up/down vol ratio)
4. Persistence: pooled autocorrelation of sector_rs, stock_rs, residual,
   computed on the FULL DAILY PANEL (not just breakout-occurrence days) --
   autocorrelation on an irregularly-spaced occurrence sample isn't a
   meaningful time-series measure, so this one component uses a different,
   larger population than the rest of the script. Flagged in the output.
5. Effect sizes throughout: R^2, standardized coefficients, partial
   correlation, 95% CI -- not just p-values, per instruction.
"""

import sqlite3
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

DB = "psx_data.db"
WINDOW = 60
LAGS = [10, 20, 40, 60, 90]

print("Loading base occurrence feature set (deduped, already includes up/down vol)...")
base = pd.read_csv("boring_leadership_features_dedup.csv")
print(f"Base rows: {len(base):,}")
print(f"Columns: {base.columns.tolist()}")

con = sqlite3.connect(DB)
prices = pd.read_sql_query("SELECT symbol, date, close FROM prices_adjusted ORDER BY symbol, date", con)
idx = pd.read_sql_query("SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
sectors_df = pd.read_sql_query("SELECT symbol, sector FROM sectors", con)
con.close()
sector_lookup = dict(zip(sectors_df["symbol"], sectors_df["sector"]))

idx = idx.sort_values("date").reset_index(drop=True)
idx["idx_ret60"] = idx["close"].pct_change(WINDOW) * 100
idx_ret_lookup = dict(zip(idx["date"], idx["idx_ret60"]))
master_calendar = idx["date"].to_numpy()  # full trading-day calendar
date_pos = {d: i for i, d in enumerate(master_calendar)}


def lag_date(d, L):
    p = date_pos.get(d)
    if p is None or p - L < 0:
        return None
    return master_calendar[p - L]


print("Rebuilding per-symbol trailing-60d return series (full history, all positions)...")
by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].to_numpy(dtype=float)
    dates = g["date"].to_numpy()
    n = len(close)
    ret60 = np.full(n, np.nan)
    base_c = close[:-WINDOW]
    valid = base_c != 0
    ret60[WINDOW:][valid] = (close[WINDOW:][valid] - base_c[valid]) / base_c[valid] * 100
    by_symbol[sym] = {"dates": dates, "ret60": ret60}

print("Building sector-level trailing-60d return lookup (sector,date) -> value...")
sec_rows = []
for sym, pf in by_symbol.items():
    sec = sector_lookup.get(sym)
    if sec is None:
        continue
    sec_rows.append(pd.DataFrame({"date": pf["dates"], "sector": sec, "ret60": pf["ret60"]}))
sec_long = pd.concat(sec_rows, ignore_index=True).dropna(subset=["ret60"])
sector_ret60_lookup = sec_long.groupby(["sector", "date"])["ret60"].mean().to_dict()

print("Computing lagged sector RS at each occurrence, for each lag horizon...")
for L in LAGS:
    col = f"sector_rs_lag{L}"
    vals = []
    for _, row in base.iterrows():
        sym, d = row["symbol"], row["date"]
        sec = sector_lookup.get(sym)
        ld = lag_date(d, L)
        if sec is None or ld is None:
            vals.append(np.nan)
            continue
        sec_ret = sector_ret60_lookup.get((sec, ld))
        idx_ret = idx_ret_lookup.get(ld)
        if sec_ret is None or idx_ret is None or np.isnan(sec_ret):
            vals.append(np.nan)
            continue
        vals.append(sec_ret - idx_ret)
    base[col] = vals
    print(f"  lag {L}: {base[col].notna().sum():,} / {len(base):,} non-null")

base.to_csv("boring_leadership_lagged.csv", index=False)
print("Saved boring_leadership_lagged.csv\n")

# ══════════════════════════════════════════════════════════════════════
# 1. Lag sweep
# ══════════════════════════════════════════════════════════════════════
print("=" * 90)
print("1. LAG SWEEP: Stock RS ~ Lagged Sector RS(L)")
print("=" * 90)

def effect_size_report(y, x, label):
    sub = pd.DataFrame({"y": y, "x": x}).dropna()
    n = len(sub)
    r, p = stats.pearsonr(sub["x"], sub["y"])
    X = sm.add_constant(sub["x"])
    m = sm.OLS(sub["y"], X).fit()
    beta = m.params["x"] * sub["x"].std() / sub["y"].std()  # standardized coef
    ci = m.conf_int().loc["x"]
    r_ci_lo, r_ci_hi = _corr_ci(r, n)
    print(f"  {label}: N={n:,}  r={r:.4f} [{r_ci_lo:.4f},{r_ci_hi:.4f}]  R^2={m.rsquared:.4f}  "
          f"std.coef(beta)={beta:.4f}  raw coef 95% CI=[{ci[0]:.5f},{ci[1]:.5f}]  p={p:.3g}")
    return {"label": label, "n": n, "r": r, "r2": m.rsquared, "beta": beta, "p": p}


def _corr_ci(r, n, alpha=0.05):
    z = np.arctanh(r)
    se = 1 / np.sqrt(n - 3)
    zcrit = stats.norm.ppf(1 - alpha / 2)
    lo, hi = z - zcrit * se, z + zcrit * se
    return np.tanh(lo), np.tanh(hi)


lag_results = []
print("\nContemporaneous baseline (lag 0):")
r0 = effect_size_report(base["stock_rs"], base["sector_rs"], "sector_rs (lag 0, current)")
lag_results.append(r0)
print("\nLagged:")
for L in LAGS:
    r = effect_size_report(base["stock_rs"], base[f"sector_rs_lag{L}"], f"sector_rs (lag {L})")
    lag_results.append(r)

print("\nShape summary (R^2 by lag, lag 0 = contemporaneous):")
for r in lag_results:
    print(f"  {r['label']:<28} R^2={r['r2']:.4f}  beta={r['beta']:.4f}")

# ══════════════════════════════════════════════════════════════════════
# 2. Incremental information: Model A vs Model B
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("2. INCREMENTAL INFORMATION: current sector_rs alone vs + lagged sector_rs")
print("=" * 90)

subA = base.dropna(subset=["stock_rs", "sector_rs"])
XA = sm.add_constant(subA[["sector_rs"]])
mA = sm.OLS(subA["stock_rs"], XA).fit()
print(f"\nModel A: stock_rs ~ current sector_rs   N={int(mA.nobs):,}  R^2={mA.rsquared:.4f}")

for L in LAGS:
    subB = base.dropna(subset=["stock_rs", "sector_rs", f"sector_rs_lag{L}"])
    XB = sm.add_constant(subB[["sector_rs", f"sector_rs_lag{L}"]])
    mB = sm.OLS(subB["stock_rs"], XB).fit()
    # refit Model A on the SAME subsample for a fair delta
    XA_same = sm.add_constant(subB[["sector_rs"]])
    mA_same = sm.OLS(subB["stock_rs"], XA_same).fit()
    delta_r2 = mB.rsquared - mA_same.rsquared
    beta_lag = mB.params[f"sector_rs_lag{L}"] * subB[f"sector_rs_lag{L}"].std() / subB["stock_rs"].std()
    ci_lag = mB.conf_int().loc[f"sector_rs_lag{L}"]
    print(f"\nModel B (lag {L}): stock_rs ~ current sector_rs + sector_rs_lag{L}   "
          f"N={int(mB.nobs):,}  R^2={mB.rsquared:.4f}  "
          f"Delta R^2 vs Model A (same N)={delta_r2:+.5f}")
    print(f"  lagged-term std.coef(beta)={beta_lag:.4f}  raw coef 95% CI=[{ci_lag[0]:.5f},{ci_lag[1]:.5f}]  "
          f"p={mB.pvalues[f'sector_rs_lag{L}']:.3g}")

# ══════════════════════════════════════════════════════════════════════
# 3. Residual leadership
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("3. RESIDUAL LEADERSHIP: Stock RS - E[Stock RS | current Sector RS]")
print("=" * 90)

subR = base.dropna(subset=["stock_rs", "sector_rs", "liquidity", "up_semivol", "down_semivol"]).copy()
Xr = sm.add_constant(subR[["sector_rs"]])
mr = sm.OLS(subR["stock_rs"], Xr).fit()
subR["residual_stock_rs"] = mr.resid
subR["updown_ratio"] = subR["up_semivol"] / subR["down_semivol"].replace(0, np.nan)

print(f"N={len(subR):,}")
print(f"\nDistribution of residual_stock_rs:")
print(subR["residual_stock_rs"].describe(percentiles=[.01,.05,.25,.5,.75,.95,.99]).round(3).to_string())
print(f"Skew={stats.skew(subR['residual_stock_rs']):.3f}  Kurtosis={stats.kurtosis(subR['residual_stock_rs']):.3f}")

print("\nRelationship with liquidity:")
r_liq, p_liq = stats.pearsonr(subR["residual_stock_rs"], np.log1p(subR["liquidity"]))
print(f"  corr(residual_stock_rs, log(liquidity)) = {r_liq:.4f} (p={p_liq:.3g})")

print("\nRelationship with up/down volatility ratio:")
subR2 = subR.dropna(subset=["updown_ratio"])
r_ratio, p_ratio = stats.pearsonr(subR2["residual_stock_rs"], subR2["updown_ratio"])
print(f"  corr(residual_stock_rs, up/down ratio) = {r_ratio:.4f} (p={p_ratio:.3g})  N={len(subR2):,}")

print("\nResidual leadership decile vs up/down ratio (median):")
subR2["resid_decile"] = pd.qcut(subR2["residual_stock_rs"], 10, labels=False, duplicates="drop")
print(subR2.groupby("resid_decile")["updown_ratio"].median().round(3).to_string())

subR.to_csv("boring_leadership_residuals.csv", index=False)

# ══════════════════════════════════════════════════════════════════════
# 4. Persistence -- FULL DAILY PANEL (not occurrence-conditional)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("4. PERSISTENCE (autocorrelation) -- full daily panel, all trading days,")
print("   NOT restricted to breakout-occurrence days (irregular spacing there")
print("   makes autocorrelation meaningless -- flagged per methodology note)")
print("=" * 90)

print("Building full daily stock_rs / sector_rs series per symbol...")
panel_rows = []
for sym, pf in by_symbol.items():
    sec = sector_lookup.get(sym)
    if sec is None:
        continue
    dates = pf["dates"]
    stock_rs_series = np.full(len(dates), np.nan)
    for i, d in enumerate(dates):
        idx_ret = idx_ret_lookup.get(d)
        if idx_ret is not None and not np.isnan(pf["ret60"][i]):
            stock_rs_series[i] = pf["ret60"][i] - idx_ret
    sector_rs_series = np.array([
        (sector_ret60_lookup.get((sec, d), np.nan) - idx_ret_lookup.get(d, np.nan))
        if d in date_pos else np.nan
        for d in dates
    ])
    panel_rows.append(pd.DataFrame({
        "symbol": sym, "date": dates,
        "stock_rs": stock_rs_series, "sector_rs": sector_rs_series,
    }))

panel = pd.concat(panel_rows, ignore_index=True)
panel = panel.dropna(subset=["stock_rs", "sector_rs"])
print(f"Full daily panel (valid rows): {len(panel):,}")

Xp = sm.add_constant(panel[["sector_rs"]])
mp = sm.OLS(panel["stock_rs"], Xp).fit()
panel["residual_stock_rs"] = mp.resid
print(f"Panel-level stock_rs ~ sector_rs: R^2={mp.rsquared:.4f} (reference, full panel)")


def pooled_autocorr(df, col, lag, date_pos_map):
    frames = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("date").reset_index(drop=True)
        pos = g["date"].map(date_pos_map)
        g = g.assign(pos=pos).dropna(subset=["pos"])
        g["pos"] = g["pos"].astype(int)
        g = g.set_index("pos")
        shifted = g[col].reindex(g.index - lag)
        shifted.index = g.index
        frames.append(pd.DataFrame({"x": g[col].to_numpy(), "x_lag": shifted.to_numpy()}))
    allf = pd.concat(frames, ignore_index=True).dropna()
    if len(allf) < 30:
        return None, None
    r, p = stats.pearsonr(allf["x"], allf["x_lag"])
    return r, len(allf)


print("\nPooled autocorrelation (panel-wide, position-based lag on the trading calendar):")
for series_name in ["sector_rs", "stock_rs", "residual_stock_rs"]:
    print(f"\n  {series_name}:")
    for L in LAGS:
        r, n = pooled_autocorr(panel, series_name, L, date_pos)
        if r is None:
            print(f"    lag {L}: insufficient data")
        else:
            lo, hi = _corr_ci(r, n)
            print(f"    lag {L}: autocorr={r:.4f} [{lo:.4f},{hi:.4f}]  N={n:,}")

print("\n\nDone.")
