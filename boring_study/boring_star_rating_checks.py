"""
boring_star_rating_checks.py -- two bounded, directly-scoped checks needed
before designing the Star Rating system, NOT a new mechanism search:

(A) Within-top-decile granularity: does hit_tp_10 keep rising if you slice
    decile 9 itself into finer sub-bins (quintiles), or does it plateau?
    This determines whether "top 1% vs top 10%" is a real, gradeable signal
    or an extrapolation past what the decile-level analysis established.

(B) Sector-clustering: do top-decile-RS breakouts that fire on the same
    date, same sector, alongside N other such breakouts, have a different
    hit_tp_10 rate than isolated ones? This was flagged as a plausible,
    UNTESTED risk in the trading-rulebook review -- checking it now rather
    than encoding an unfounded penalty into the star rating.

Both panels (20d, 60d), breakout=1 rows only (real trades).
"""

import sqlite3
import numpy as np
import pandas as pd
from scipy import stats

DB = "psx_data.db"

con = sqlite3.connect(DB)
sectors = pd.read_sql_query("SELECT symbol, sector FROM sectors", con)
con.close()


def analyze(panel_path, label):
    print(f"\n{'#'*90}\n# {label}\n{'#'*90}")
    df = pd.read_csv(panel_path)
    d = df.dropna(subset=["hit_tp_10", "breakout", "stock_rs"]).copy()
    d["rs_decile"] = pd.qcut(d["stock_rs"], 10, labels=False, duplicates="drop")
    top = d[d["rs_decile"] == d["rs_decile"].max()].copy()

    # ---- (A) granularity within the top decile ----
    print(f"\n--- (A) Within-top-decile granularity ---")
    bo = top[top["breakout"] == 1].copy()
    bo["subq"] = pd.qcut(bo["stock_rs"], 5, labels=False, duplicates="drop")
    tab = bo.groupby("subq").agg(n=("hit_tp_10", "size"), hit_rate=("hit_tp_10", "mean"),
                                  rs_min=("stock_rs", "min"), rs_max=("stock_rs", "max"))
    tab["hit_rate"] = (tab["hit_rate"] * 100).round(2)
    print(tab.to_string())
    rho, p = stats.spearmanr(tab.index.to_numpy(), tab["hit_rate"].to_numpy())
    print(f"Spearman rank correlation (sub-quintile vs hit rate, within top decile): rho={rho:.3f}, p={p:.4g}")

    # ---- (B) sector clustering ----
    print(f"\n--- (B) Same-day, same-sector clustering ---")
    bo2 = bo.merge(sectors, on="symbol", how="left")
    missing_sector = bo2["sector"].isna().sum()
    bo2 = bo2.dropna(subset=["sector"])
    print(f"Rows with sector mapped: {len(bo2):,} (dropped {missing_sector:,} with no sector match)")

    cluster_size = bo2.groupby(["date", "sector"])["symbol"].transform("count") - 1
    bo2["cluster_size"] = cluster_size

    bins = [-0.5, 0.5, 2.5, 5.5, 1000]
    labels = ["0 (isolated)", "1-2", "3-5", "6+"]
    bo2["cluster_bin"] = pd.cut(bo2["cluster_size"], bins=bins, labels=labels)

    tab2 = bo2.groupby("cluster_bin", observed=True).agg(
        n=("hit_tp_10", "size"), hit_rate=("hit_tp_10", "mean"), avg_rs=("stock_rs", "mean")
    )
    tab2["hit_rate"] = (tab2["hit_rate"] * 100).round(2)
    tab2["avg_rs"] = tab2["avg_rs"].round(2)
    print(tab2.to_string())

    rho2, p2 = stats.spearmanr(bo2["cluster_size"], bo2["hit_tp_10"])
    print(f"Spearman rank correlation (cluster_size vs hit_tp_10, row-level): rho={rho2:.3f}, p={p2:.4g}")

    # crude control for RS level within the check (cluster could just correlate with RS itself)
    z_rs = (bo2["stock_rs"] - bo2["stock_rs"].mean()) / bo2["stock_rs"].std()
    rho3, p3 = stats.spearmanr(bo2["cluster_size"], z_rs)
    print(f"(diagnostic) Spearman corr(cluster_size, RS itself): rho={rho3:.3f}, p={p3:.4g} -- "
          f"if high, cluster size may just be re-deriving RS, not adding new info")

    return tab, tab2


analyze("boring_heterogeneity_panel_20d_race.csv", "20d panel")
analyze("boring_heterogeneity_panel_60d_race.csv", "60d panel")

print("\n\nDone.")
