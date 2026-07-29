"""
boring_leadership_loo_correction.py — leave-one-out (LOO) correction for
sector RS to remove self-inclusion bias, then rerun the contemporaneous
correlation, partial correlations, and mediation comparison that the
"Sector RS -> Stock RS -> Volatility" chain claim was built on.

LOO sector_rs for stock i in sector S on date d:
  = mean(ret60_j for j in S, j != i, valid on d) - idx_ret60(d)

Requires >=2 valid stocks in the sector on that date (else NaN -- a stock
alone in its sector cannot have a leave-one-out sector reading).

Predictor-only, no outcome touched. Read-only against psx_data.db.
"""

import sqlite3
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

DB = "psx_data.db"
WINDOW = 60

base = pd.read_csv("boring_leadership_features_dedup.csv")
print(f"Base occurrences: {len(base):,}")

con = sqlite3.connect(DB)
prices = pd.read_sql_query("SELECT symbol, date, close FROM prices_adjusted ORDER BY symbol, date", con)
idx = pd.read_sql_query("SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
sectors_df = pd.read_sql_query("SELECT symbol, sector FROM sectors", con)
con.close()
sector_lookup = dict(zip(sectors_df["symbol"], sectors_df["sector"]))

idx = idx.sort_values("date").reset_index(drop=True)
idx["idx_ret60"] = idx["close"].pct_change(WINDOW) * 100
idx_ret_lookup = dict(zip(idx["date"], idx["idx_ret60"]))

print("Computing per-symbol trailing-60d return (own_ret60)...")
rows = []
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].to_numpy(dtype=float)
    dates = g["date"].to_numpy()
    n = len(close)
    ret60 = np.full(n, np.nan)
    base_c = close[:-WINDOW]
    valid = base_c != 0
    ret60[WINDOW:][valid] = (close[WINDOW:][valid] - base_c[valid]) / base_c[valid] * 100
    sec = sector_lookup.get(sym)
    if sec is None:
        continue
    rows.append(pd.DataFrame({"symbol": sym, "date": dates, "sector": sec, "own_ret60": ret60}))

long_df = pd.concat(rows, ignore_index=True).dropna(subset=["own_ret60"])
print(f"Long-format valid rows: {len(long_df):,}")

print("Building (sector,date) -> sum, count for LOO subtraction...")
grp = long_df.groupby(["sector", "date"])["own_ret60"].agg(["sum", "count"]).reset_index()
grp_lookup = {(r.sector, r.date): (r.sum, r.count) for r in grp.itertuples()}

print("Building (symbol,date) -> own_ret60 lookup...")
own_ret60_lookup = {(r.symbol, r.date): r.own_ret60 for r in long_df.itertuples()}

print("Computing LOO sector_rs for each base occurrence...")
loo_vals = []
n_single_stock = 0
for _, row in base.iterrows():
    sym, d = row["symbol"], row["date"]
    sec = sector_lookup.get(sym)
    if sec is None:
        loo_vals.append(np.nan)
        continue
    key = (sec, d)
    if key not in grp_lookup:
        loo_vals.append(np.nan)
        continue
    s_sum, s_count = grp_lookup[key]
    own = own_ret60_lookup.get((sym, d))
    if own is None:
        loo_vals.append(np.nan)
        continue
    if s_count < 2:
        n_single_stock += 1
        loo_vals.append(np.nan)
        continue
    loo_mean = (s_sum - own) / (s_count - 1)
    idx_ret = idx_ret_lookup.get(d)
    loo_vals.append(loo_mean - idx_ret if idx_ret is not None else np.nan)

base["sector_rs_loo"] = loo_vals
print(f"LOO sector_rs computed: {base['sector_rs_loo'].notna().sum():,} / {len(base):,} "
      f"(dropped for single-stock-sector: {n_single_stock:,})")
base.to_csv("boring_leadership_loo.csv", index=False)

# ══════════════════════════════════════════════════════════════════════
sub = base.dropna(subset=["stock_rs", "sector_rs", "sector_rs_loo", "realized_vol"]).copy()
print(f"\nComplete-case N for comparison: {len(sub):,}")


def partial_corr(x, y, z):
    rxy, _ = stats.pearsonr(x, y); rxz, _ = stats.pearsonr(x, z); ryz, _ = stats.pearsonr(y, z)
    return (rxy - rxz * ryz) / np.sqrt((1 - rxz ** 2) * (1 - ryz ** 2))


print("\n" + "=" * 90)
print("1. CONTEMPORANEOUS CORRELATION: self-inclusive vs leave-one-out sector_rs")
print("=" * 90)
r_orig, p_orig = stats.pearsonr(sub["stock_rs"], sub["sector_rs"])
r_loo, p_loo = stats.pearsonr(sub["stock_rs"], sub["sector_rs_loo"])
abs_change = r_orig - r_loo
pct_reduction = abs_change / r_orig * 100
print(f"Original (self-inclusive)  corr(stock_rs, sector_rs)     = {r_orig:.4f}")
print(f"Corrected (leave-one-out)  corr(stock_rs, sector_rs_loo) = {r_loo:.4f}")
print(f"Absolute change = {abs_change:.4f}   Percent reduction = {pct_reduction:.1f}%")
print(f"R^2: original={r_orig**2:.4f}  corrected={r_loo**2:.4f}")

print("\n" + "=" * 90)
print("2. PARTIAL CORRELATIONS (mediation test) -- self-inclusive vs LOO")
print("=" * 90)

r_sec_vol = stats.pearsonr(sub["sector_rs"], sub["realized_vol"])[0]
pc_sec_vol_orig = partial_corr(sub["sector_rs"], sub["realized_vol"], sub["stock_rs"])
r_secloo_vol = stats.pearsonr(sub["sector_rs_loo"], sub["realized_vol"])[0]
pc_sec_vol_loo = partial_corr(sub["sector_rs_loo"], sub["realized_vol"], sub["stock_rs"])

print("ORIGINAL (self-inclusive sector_rs):")
print(f"  Raw corr(sector_rs, vol) = {r_sec_vol:.4f}   Partial corr(sector_rs, vol | stock_rs) = {pc_sec_vol_orig:.4f}")

print("\nCORRECTED (LOO sector_rs):")
print(f"  Raw corr(sector_rs_loo, vol) = {r_secloo_vol:.4f}   Partial corr(sector_rs_loo, vol | stock_rs) = {pc_sec_vol_loo:.4f}")

r_stk_vol = stats.pearsonr(sub["stock_rs"], sub["realized_vol"])[0]
pc_stk_vol_given_secorig = partial_corr(sub["stock_rs"], sub["realized_vol"], sub["sector_rs"])
pc_stk_vol_given_secloo = partial_corr(sub["stock_rs"], sub["realized_vol"], sub["sector_rs_loo"])
print(f"\nstock_rs vs vol, partial on ORIGINAL sector_rs  = {pc_stk_vol_given_secorig:.4f}")
print(f"stock_rs vs vol, partial on LOO sector_rs       = {pc_stk_vol_given_secloo:.4f}")

print("\n" + "=" * 90)
print("3. OLS mediation model: vol ~ stock_rs + sector_rs (original vs LOO)")
print("=" * 90)
X_orig = sm.add_constant(sub[["stock_rs", "sector_rs"]])
m_orig = sm.OLS(sub["realized_vol"], X_orig).fit()
X_loo = sm.add_constant(sub[["stock_rs", "sector_rs_loo"]])
m_loo = sm.OLS(sub["realized_vol"], X_loo).fit()
print("ORIGINAL:")
print(f"  stock_rs coef={m_orig.params['stock_rs']:.5f}  sector_rs coef={m_orig.params['sector_rs']:.5f}  R^2={m_orig.rsquared:.4f}")
print("LOO-CORRECTED:")
print(f"  stock_rs coef={m_loo.params['stock_rs']:.5f}  sector_rs_loo coef={m_loo.params['sector_rs_loo']:.5f}  R^2={m_loo.rsquared:.4f}")

print("\nDone.")
