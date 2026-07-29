"""
boring_leadership_pca.py — unsupervised PCA/correlation diagnostic on the 5
candidate Leadership Quality indicators. Predictor variables ONLY, no
response/outcome touched at any point -- this is pure dimensionality
discovery, not a hindsight-biased fit.

Variables, all computed fresh from prices_adjusted (+ sectors, +
stock_metadata for listing_date only) -- NOT read from stock_signals /
stock_market_cap, per the coverage audit:
  - stock_rs: trailing 60d stock return minus trailing 60d KSE-100 return
  - sector_rs: trailing 60d sector return (equal-weighted) minus trailing
    60d KSE-100 return
  - liquidity: trailing 60d average daily volume
  - realized_vol: trailing 60d std of daily returns
  - listing_age_days: breakout date minus listing_date (stock_metadata)

60-day window used consistently across all trailing measures for this
diagnostic stage -- a single, un-tuned, round-number choice, not yet the
locked window for the final test (per the conversation: window-length
decisions come after the construct is defined).
"""

import sqlite3
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

DB = "psx_data.db"
WINDOW = 60

occ = pd.read_csv("boring_donchian_mechanism_dataset.csv")[["symbol", "date", "lookback"]]
print(f"Occurrence rows: {len(occ):,}")

con = sqlite3.connect(DB)
prices = pd.read_sql_query("SELECT symbol, date, close, volume FROM prices_adjusted ORDER BY symbol, date", con)
idx = pd.read_sql_query("SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
sectors_df = pd.read_sql_query("SELECT symbol, sector FROM sectors", con)
meta = pd.read_sql_query("SELECT symbol, listing_date FROM stock_metadata", con)
con.close()

sector_lookup = dict(zip(sectors_df["symbol"], sectors_df["sector"]))
listing_lookup = dict(zip(meta["symbol"], meta["listing_date"]))

idx = idx.sort_values("date").reset_index(drop=True)
idx["idx_ret_60d"] = idx["close"].pct_change(WINDOW) * 100
idx_ret_lookup = dict(zip(idx["date"], idx["idx_ret_60d"]))

print("Computing per-symbol trailing return / volume / volatility series...")
by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].to_numpy(dtype=float)
    vol = g["volume"].to_numpy(dtype=float)
    dates = g["date"].to_numpy()
    n = len(close)

    ret60 = np.full(n, np.nan)
    valid_base = close[:-WINDOW] != 0
    ret60[WINDOW:][valid_base] = (close[WINDOW:][valid_base] - close[:-WINDOW][valid_base]) / close[:-WINDOW][valid_base] * 100

    daily_ret = np.full(n, np.nan)
    prev = close[:-1]
    safe = prev != 0
    daily_ret[1:][safe] = (close[1:][safe] - prev[safe]) / prev[safe] * 100
    rvol60 = pd.Series(daily_ret).rolling(WINDOW).std().to_numpy()

    avgvol60 = pd.Series(vol).rolling(WINDOW).mean().to_numpy()

    by_symbol[sym] = {"dates": dates, "ret60": ret60, "rvol60": rvol60, "avgvol60": avgvol60}

print("Building sector-level trailing return series (equal-weighted)...")
sec_ret_rows = []
for sym, pf in by_symbol.items():
    sec = sector_lookup.get(sym)
    if sec is None:
        continue
    sec_ret_rows.append(pd.DataFrame({"date": pf["dates"], "sector": sec, "ret60": pf["ret60"]}))
sec_ret_long = pd.concat(sec_ret_rows, ignore_index=True).dropna(subset=["ret60"])
sector_ret60 = sec_ret_long.groupby(["sector", "date"])["ret60"].mean().reset_index()
sector_ret60_lookup = {(r.sector, r.date): r.ret60 for r in sector_ret60.itertuples()}

print("Assembling occurrence-level feature matrix...")
rows = []
for _, row in occ.iterrows():
    sym, d = row["symbol"], row["date"]
    pf = by_symbol.get(sym)
    if pf is None:
        continue
    dpos = np.searchsorted(pf["dates"], d)
    if dpos >= len(pf["dates"]) or pf["dates"][dpos] != d:
        continue

    stock_ret = pf["ret60"][dpos]
    idx_ret = idx_ret_lookup.get(d)
    stock_rs = stock_ret - idx_ret if (stock_ret is not None and not np.isnan(stock_ret) and idx_ret is not None) else np.nan

    sec = sector_lookup.get(sym)
    sec_ret = sector_ret60_lookup.get((sec, d)) if sec else None
    sector_rs = sec_ret - idx_ret if (sec_ret is not None and idx_ret is not None) else np.nan

    liquidity = pf["avgvol60"][dpos]
    realized_vol = pf["rvol60"][dpos]

    ldate = listing_lookup.get(sym)
    listing_age = None
    if ldate:
        try:
            listing_age = (pd.Timestamp(d) - pd.Timestamp(ldate)).days
        except Exception:
            listing_age = None

    rows.append({
        "symbol": sym, "date": d,
        "stock_rs": stock_rs, "sector_rs": sector_rs,
        "liquidity": liquidity, "realized_vol": realized_vol,
        "listing_age_days": listing_age,
    })

feat = pd.DataFrame(rows)
feat.to_csv("boring_leadership_features.csv", index=False)
print(f"\nFeature matrix: {len(feat):,} rows")
for c in ["stock_rs", "sector_rs", "liquidity", "realized_vol", "listing_age_days"]:
    print(f"  {c}: {feat[c].notna().sum():,} non-null ({feat[c].notna().mean()*100:.1f}%)")

# ── PCA on 4-variable set (excl listing_age, best coverage) ──
print("\n" + "=" * 80)
print("PCA #1 — 4 variables (stock_rs, sector_rs, liquidity, realized_vol), excl. listing_age")
print("=" * 80)
sub4 = feat.dropna(subset=["stock_rs", "sector_rs", "liquidity", "realized_vol"])
print(f"Complete-case N: {len(sub4):,} ({len(sub4)/len(feat)*100:.1f}% of feature matrix)")
X4 = sub4[["stock_rs", "sector_rs", "liquidity", "realized_vol"]].to_numpy()
X4z = StandardScaler().fit_transform(X4)
pca4 = PCA().fit(X4z)
print("\nEigenvalues:", np.round(pca4.explained_variance_, 3))
print("Explained variance ratio:", np.round(pca4.explained_variance_ratio_, 3))
print("\nLoadings (rows=components, cols=variables):")
loadings4 = pd.DataFrame(pca4.components_, columns=["stock_rs", "sector_rs", "liquidity", "realized_vol"],
                          index=[f"PC{i+1}" for i in range(4)])
print(loadings4.round(3).to_string())

print("\nCorrelation matrix (4 vars):")
print(sub4[["stock_rs", "sector_rs", "liquidity", "realized_vol"]].corr().round(3).to_string())

# ── PCA on 5-variable set (incl listing_age, complete case) ──
print("\n" + "=" * 80)
print("PCA #2 — 5 variables, incl. listing_age_days (complete case)")
print("=" * 80)
sub5 = feat.dropna(subset=["stock_rs", "sector_rs", "liquidity", "realized_vol", "listing_age_days"])
print(f"Complete-case N: {len(sub5):,} ({len(sub5)/len(feat)*100:.1f}% of feature matrix)")
X5 = sub5[["stock_rs", "sector_rs", "liquidity", "realized_vol", "listing_age_days"]].to_numpy()
X5z = StandardScaler().fit_transform(X5)
pca5 = PCA().fit(X5z)
print("\nEigenvalues:", np.round(pca5.explained_variance_, 3))
print("Explained variance ratio:", np.round(pca5.explained_variance_ratio_, 3))
print("\nLoadings (rows=components, cols=variables):")
loadings5 = pd.DataFrame(pca5.components_,
                          columns=["stock_rs", "sector_rs", "liquidity", "realized_vol", "listing_age_days"],
                          index=[f"PC{i+1}" for i in range(5)])
print(loadings5.round(3).to_string())

print("\nCorrelation matrix (5 vars):")
print(sub5[["stock_rs", "sector_rs", "liquidity", "realized_vol", "listing_age_days"]].corr().round(3).to_string())

print("\nDone.")
