"""
market_structure_diagnostic.py — Structural Break Investigation: What Changed
in PSX Around 2023?

DIAGNOSTIC / DESCRIPTIVE ONLY. Not a hypothesis test on fwd_return_10d, not a
new trading signal. Motivated by two independent findings (Phase 4c ROC/
volume, Phase 5 stealth relative strength) both holding through Development
(2015-2019) + Validation (2020-2022) then reversing in OOS (2023-2026) --
this script characterizes whether market structure itself shifted around
2023, using existing tables only.

READ access: market_regime, prices_adjusted, stock_signals, index_prices,
sectors. WRITE access: none.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import research_db  # opt-in Postgres path — DATABASE_URL/SUPABASE_DB_URL env
                     # var set -> Supabase; unset -> local SQLite, unchanged.

DB = str(Path(__file__).parent / "psx_data.db")
YEAR_START = 2015
YEAR_END = 2026
ADVERSE_THRESH = -1.5  # per Section 12's own definition, reused not re-derived
LIQ_GATE = 200_000


def log(msg):
    print(msg, flush=True)


# ══════════════════════════════════════════════════════════════════════════
# 1. Regime distribution shift
# ══════════════════════════════════════════════════════════════════════════

def step1_regime_distribution(con):
    log("\n" + "=" * 100)
    log("STEP 1 — REGIME DISTRIBUTION SHIFT (market_regime table, year-by-year)")
    log("=" * 100)
    df = research_db.read_sql(
        "SELECT date, regime FROM market_regime WHERE regime != 'INSUFFICIENT_DATA' ORDER BY date", con
    )
    df["year"] = df["date"].str[:4].astype(int)
    df = df[(df["year"] >= YEAR_START) & (df["year"] <= YEAR_END)]

    pivot = df.groupby(["year", "regime"]).size().unstack(fill_value=0)
    pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100
    for col in ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]:
        if col not in pivot_pct.columns:
            pivot_pct[col] = 0.0
    pivot_pct = pivot_pct[["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]]
    log("\nAnnual regime % breakdown:")
    log(pivot_pct.round(1).to_string())

    pre2023 = pivot_pct[pivot_pct.index < 2023]["VOLATILE"].mean()
    post2023 = pivot_pct[pivot_pct.index >= 2023]["VOLATILE"].mean()
    log(f"\nVOLATILE regime — mean % of days, 2015-2022: {pre2023:.1f}%  |  2023+: {post2023:.1f}%")
    return pivot_pct


# ══════════════════════════════════════════════════════════════════════════
# 2. Cross-sectional dispersion / correlation
# ══════════════════════════════════════════════════════════════════════════

def step2_dispersion_correlation(con, symbols):
    log("\n" + "=" * 100)
    log("STEP 2 — CROSS-SECTIONAL DISPERSION / CORRELATION")
    log("=" * 100)

    q = """
        SELECT symbol, date, close FROM prices_adjusted
        WHERE symbol IN ({}) ORDER BY symbol, date
    """.format(",".join("?" for _ in symbols))
    df = research_db.read_sql(q, con, params=symbols)
    df["ret"] = df.groupby("symbol")["close"].pct_change() * 100
    df["year"] = df["date"].str[:4].astype(int)
    df = df[(df["year"] >= YEAR_START) & (df["year"] <= YEAR_END)]

    # cross-sectional dispersion: std of daily returns across symbols, per day, averaged per year
    daily_disp = df.groupby("date")["ret"].std()
    daily_disp_df = pd.DataFrame({"date": daily_disp.index, "cross_sec_std": daily_disp.values})
    daily_disp_df["year"] = daily_disp_df["date"].str[:4].astype(int)
    disp_by_year = daily_disp_df.groupby("year")["cross_sec_std"].mean()

    # average pairwise correlation: build wide matrix per year, require >=150 valid days
    corr_by_year = {}
    for yr, g in df.groupby("year"):
        wide = g.pivot(index="date", columns="symbol", values="ret")
        valid_cols = wide.columns[wide.notna().sum() >= 150]
        wide = wide[valid_cols]
        if wide.shape[1] < 10:
            corr_by_year[yr] = np.nan
            continue
        corr_mat = wide.corr(min_periods=100)
        n = corr_mat.shape[0]
        upper = corr_mat.values[np.triu_indices(n, k=1)]
        upper = upper[~np.isnan(upper)]
        corr_by_year[yr] = upper.mean() if len(upper) > 0 else np.nan

    result = pd.DataFrame({
        "cross_sec_daily_std_%": disp_by_year,
        "avg_pairwise_corr": pd.Series(corr_by_year),
    })
    log("\nCross-sectional dispersion (avg daily std of returns across symbols) and "
        "average pairwise correlation of daily returns, by year:")
    log(result.round(4).to_string())

    pre_disp = result.loc[result.index < 2023, "cross_sec_daily_std_%"].mean()
    post_disp = result.loc[result.index >= 2023, "cross_sec_daily_std_%"].mean()
    pre_corr = result.loc[result.index < 2023, "avg_pairwise_corr"].mean()
    post_corr = result.loc[result.index >= 2023, "avg_pairwise_corr"].mean()
    log(f"\n2015-2022 avg: cross-sec std={pre_disp:.4f}%, avg pairwise corr={pre_corr:.4f}")
    log(f"2023+     avg: cross-sec std={post_disp:.4f}%, avg pairwise corr={post_corr:.4f}")
    return result


# ══════════════════════════════════════════════════════════════════════════
# 3. Liquidity profile over time
# ══════════════════════════════════════════════════════════════════════════

def step3_liquidity_profile(con, symbols):
    log("\n" + "=" * 100)
    log("STEP 3 — LIQUIDITY PROFILE OVER TIME")
    log("=" * 100)

    ss = research_db.read_sql(
        "SELECT date, symbol, avg_vol_10d FROM stock_signals WHERE symbol IN ({}) ORDER BY date".format(
            ",".join("?" for _ in symbols)
        ),
        con, params=symbols,
    )
    ss["year"] = ss["date"].str[:4].astype(int)
    ss = ss[(ss["year"] >= YEAR_START) & (ss["year"] <= YEAR_END)]
    ss["eligible"] = ss["avg_vol_10d"] >= LIQ_GATE

    eligible_by_day = ss.groupby("date")["eligible"].sum()
    eligible_by_day_df = pd.DataFrame({"date": eligible_by_day.index, "n_eligible": eligible_by_day.values})
    eligible_by_day_df["year"] = eligible_by_day_df["date"].str[:4].astype(int)
    avg_eligible_by_year = eligible_by_day_df.groupby("year")["n_eligible"].mean()

    vol_df = research_db.read_sql(
        "SELECT date, symbol, volume FROM prices_adjusted WHERE symbol IN ({}) ORDER BY date".format(
            ",".join("?" for _ in symbols)
        ),
        con, params=symbols,
    )
    vol_df["year"] = vol_df["date"].str[:4].astype(int)
    vol_df = vol_df[(vol_df["year"] >= YEAR_START) & (vol_df["year"] <= YEAR_END)]
    total_vol_by_day = vol_df.groupby("date")["volume"].sum()
    total_vol_by_day_df = pd.DataFrame({"date": total_vol_by_day.index, "total_vol": total_vol_by_day.values})
    total_vol_by_day_df["year"] = total_vol_by_day_df["date"].str[:4].astype(int)
    avg_total_vol_by_year = total_vol_by_day_df.groupby("year")["total_vol"].mean()

    # concentration: top-10 symbols' share of total volume, by year
    vol_by_symbol_year = vol_df.groupby(["year", "symbol"])["volume"].sum().reset_index()
    conc_rows = {}
    for yr, g in vol_by_symbol_year.groupby("year"):
        total = g["volume"].sum()
        top10 = g.nlargest(10, "volume")["volume"].sum()
        conc_rows[yr] = (top10 / total * 100) if total > 0 else np.nan
    top10_share = pd.Series(conc_rows)

    result = pd.DataFrame({
        "avg_daily_eligible_symbols": avg_eligible_by_year,
        "avg_daily_total_volume_shares": avg_total_vol_by_year,
        "top10_symbol_vol_share_%": top10_share,
    })
    log("\nLiquidity profile by year:")
    log(result.round(1).to_string())
    return result


# ══════════════════════════════════════════════════════════════════════════
# 4. KSE-100 index-level behavior
# ══════════════════════════════════════════════════════════════════════════

def step4_index_behavior(con):
    log("\n" + "=" * 100)
    log("STEP 4 — KSE-100 INDEX-LEVEL BEHAVIOR")
    log("=" * 100)
    idx = research_db.read_sql(
        "SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con
    )
    idx["ret"] = idx["close"].pct_change() * 100
    idx["year"] = idx["date"].str[:4].astype(int)
    idx = idx[(idx["year"] >= YEAR_START) & (idx["year"] <= YEAR_END)]

    rows = []
    for yr, g in idx.groupby("year"):
        rets = g["ret"].dropna()
        annual_std = rets.std()
        first_close = g["close"].iloc[0]
        last_close = g["close"].iloc[-1]
        annual_return = (last_close - first_close) / first_close * 100
        n_adverse = (rets <= ADVERSE_THRESH).sum()
        rows.append({
            "year": yr, "annual_return_%": annual_return, "daily_std_%": annual_std,
            "n_adverse_days_(<=-1.5%)": n_adverse, "n_trading_days": len(rets),
        })
    result = pd.DataFrame(rows).set_index("year")
    log("\nKSE-100 annual behavior by year:")
    log(result.round(2).to_string())

    pre_std = result.loc[result.index < 2023, "daily_std_%"].mean()
    post_std = result.loc[result.index >= 2023, "daily_std_%"].mean()
    pre_adv = result.loc[result.index < 2023, "n_adverse_days_(<=-1.5%)"].mean()
    post_adv = result.loc[result.index >= 2023, "n_adverse_days_(<=-1.5%)"].mean()
    log(f"\n2015-2022 avg: daily_std={pre_std:.3f}%, adverse_days/yr={pre_adv:.1f}")
    log(f"2023+     avg: daily_std={post_std:.3f}%, adverse_days/yr={post_adv:.1f}")
    return result


# ══════════════════════════════════════════════════════════════════════════
# 5. Sector composition / concentration
# ══════════════════════════════════════════════════════════════════════════

def step5_sector_concentration(con, symbols):
    log("\n" + "=" * 100)
    log("STEP 5 — SECTOR COMPOSITION / CONCENTRATION")
    log("=" * 100)

    vol_df = research_db.read_sql(
        "SELECT date, symbol, volume FROM prices_adjusted WHERE symbol IN ({}) ORDER BY date".format(
            ",".join("?" for _ in symbols)
        ),
        con, params=symbols,
    )
    sectors = research_db.read_sql("SELECT symbol, sector FROM sectors", con)
    vol_df = vol_df.merge(sectors, on="symbol", how="left")
    vol_df["year"] = vol_df["date"].str[:4].astype(int)
    vol_df = vol_df[(vol_df["year"] >= YEAR_START) & (vol_df["year"] <= YEAR_END)]

    sector_year_vol = vol_df.groupby(["year", "sector"])["volume"].sum().reset_index()

    # global top-5 sectors by total volume across the whole period
    global_top5 = (
        sector_year_vol.groupby("sector")["volume"].sum().nlargest(5).index.tolist()
    )
    log(f"\nGlobal top-5 sectors by total traded volume, 2015-2026: {global_top5}")

    rows = []
    for yr, g in sector_year_vol.groupby("year"):
        total = g["volume"].sum()
        # (a) fixed global top-5 share this year
        fixed_top5_vol = g[g["sector"].isin(global_top5)]["volume"].sum()
        fixed_share = (fixed_top5_vol / total * 100) if total > 0 else np.nan
        # (b) annually re-ranked top-5 share this year
        annual_top5_vol = g.nlargest(5, "volume")["volume"].sum()
        annual_share = (annual_top5_vol / total * 100) if total > 0 else np.nan
        top_sector_this_year = g.nlargest(1, "volume")["sector"].iloc[0]
        rows.append({
            "year": yr, "fixed_global_top5_share_%": fixed_share,
            "annual_reranked_top5_share_%": annual_share,
            "top_sector_this_year": top_sector_this_year,
        })
    result = pd.DataFrame(rows).set_index("year")
    log("\nSector concentration by year:")
    log(result.round(1).to_string())

    pre_fixed = result.loc[result.index < 2023, "fixed_global_top5_share_%"].mean()
    post_fixed = result.loc[result.index >= 2023, "fixed_global_top5_share_%"].mean()
    pre_annual = result.loc[result.index < 2023, "annual_reranked_top5_share_%"].mean()
    post_annual = result.loc[result.index >= 2023, "annual_reranked_top5_share_%"].mean()
    log(f"\n2015-2022 avg: fixed-top5 share={pre_fixed:.1f}%, annual-reranked-top5 share={pre_annual:.1f}%")
    log(f"2023+     avg: fixed-top5 share={post_fixed:.1f}%, annual-reranked-top5 share={post_annual:.1f}%")
    return result, global_top5


def main():
    con = research_db.get_connection(DB)
    try:
        log("=" * 100)
        log("MARKET STRUCTURE DIAGNOSTIC — What Changed in PSX Around 2023?")
        log("DIAGNOSTIC / DESCRIPTIVE ONLY. No hypothesis test on fwd_return_10d in this script.")
        log("=" * 100)

        symbols = research_db.read_sql(
            "SELECT DISTINCT symbol FROM pre_breakout_v2_staging_full", con
        )["symbol"].tolist()
        log(f"\nUniverse: {len(symbols)} symbols (from pre_breakout_v2_staging_full)")

        r1 = step1_regime_distribution(con)
        r2 = step2_dispersion_correlation(con, symbols)
        r3 = step3_liquidity_profile(con, symbols)
        r4 = step4_index_behavior(con)
        r5, top5 = step5_sector_concentration(con, symbols)

        out_dir = Path(__file__).parent
        r1.to_csv(out_dir / "diag_regime_by_year.csv")
        r2.to_csv(out_dir / "diag_dispersion_by_year.csv")
        r3.to_csv(out_dir / "diag_liquidity_by_year.csv")
        r4.to_csv(out_dir / "diag_index_by_year.csv")
        r5.to_csv(out_dir / "diag_sector_concentration_by_year.csv")
        log("\nAll diagnostic tables saved as diag_*_by_year.csv")

    finally:
        con.close()


if __name__ == "__main__":
    main()
