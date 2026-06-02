"""
sector_flows_engine.py — Kiran Sector Flows Intelligence Engine
================================================================
Correlates FIPI/LIPI investor flows with subsequent sector price performance.
Hunts for statistically validated patterns that predict sector moves.

Run daily after market close:
    python sector_flows_engine.py

Outputs:
    • Prints daily intelligence brief to console
    • Appends validated signals to sector_flows_log.csv
    • Appends signal outcomes (validation) to sector_flows_log.csv

Author: Kiran AI Brain — auto-runs from daily_evening.bat
"""

import sqlite3
import os
import json
import warnings
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")

LOG_PATH = os.path.join(os.path.dirname(__file__), "sector_flows_log.csv")

# Minimum thresholds before calling a pattern "real"
MIN_OCCURRENCES  = 10
MIN_WIN_RATE     = 0.65
MIN_P_VALUE      = 0.05   # two-sided t-test on forward returns

# Map flows DB sector names → PSX sector names in the prices/sectors tables
FLOW_SECTOR_MAP = {
    "CEMENT":           "CEMENT",
    "COMM. BANKS":      "COMMERCIAL BANKS",
    "FERTILIZER":       "FERTILIZER",
    "FOOD & PERSON.":   "FOOD & PERSONAL CARE PRODUCTS",
    "OIL & GAS EXP.":   "OIL & GAS EXPLORATION COMPANIES",
    "OIL & GAS MKTG.":  "OIL & GAS MARKETING COMPANIES",
    "POWER GEN.":       "POWER GENERATION & DISTRIBUTION",
    "TECH. & COMM.":    "TECHNOLOGY & COMMUNICATION",
    "TEXTILE COMP.":    "TEXTILE COMPOSITE",
}

# "Smart money" client types (institutional / principal capital)
SMART_CLIENTS = {
    "FOREIGN CORPORATES", "OVERSEAS PAKISTANI",
    "BANKS / DFI", "COMPANIES", "INSURANCE COMPANIES", "BROKER PROPRIETARY TRADING",
}

TODAY = date.today().isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (flows_raw, prices_with_sector, sector_daily_returns)."""
    conn = sqlite3.connect(DB_PATH)

    # --- flows ---
    flows = pd.read_sql("""
        SELECT date, sector, flow_type, client_type, market_type,
               buy_volume, sell_volume, net_volume, buy_value, sell_value, net_value
        FROM market_flows
        WHERE sector NOT IN ('ALL OTHER SECTORS', 'DEBT MARKET')
          AND market_type = 'REGULAR'
        ORDER BY date, sector
    """, conn)
    flows["date"] = pd.to_datetime(flows["date"])

    # --- prices + sector mapping ---
    prices = pd.read_sql("""
        SELECT p.symbol, p.date, p.close, p.volume
        FROM prices p
        JOIN sectors s ON p.symbol = s.symbol
        WHERE s.sector IN (
            'CEMENT','COMMERCIAL BANKS','FERTILIZER',
            'FOOD & PERSONAL CARE PRODUCTS','OIL & GAS EXPLORATION COMPANIES',
            'OIL & GAS MARKETING COMPANIES','POWER GENERATION & DISTRIBUTION',
            'TECHNOLOGY & COMMUNICATION','TEXTILE COMPOSITE'
        )
        AND p.date >= '2026-01-01'
    """, conn)
    prices["date"] = pd.to_datetime(prices["date"])

    # Attach PSX sector name
    sectors_df = pd.read_sql("SELECT symbol, sector FROM sectors", conn)
    conn.close()

    prices = prices.merge(sectors_df, on="symbol", how="left")

    # --- sector-level daily returns ---
    # Equal-weight median close per sector per day
    sect_price = (
        prices.groupby(["date", "sector"])["close"]
        .median()
        .reset_index()
        .sort_values(["sector", "date"])
    )
    sect_price["ret_1d"] = sect_price.groupby("sector")["close"].pct_change()

    return flows, prices, sect_price


# ══════════════════════════════════════════════════════════════════════════════
# 2. FLOWS AGGREGATION
# ══════════════════════════════════════════════════════════════════════════════

def aggregate_flows(flows: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse raw client-level rows into one row per (date, sector).

    Computed fields:
        total_buy_vol, total_sell_vol, total_net_vol
        smart_buy_vol, smart_sell_vol, smart_net_vol
        buy_ratio         = total_buy / (total_buy + |total_sell|)
        smart_buy_ratio   = smart_buy / (smart_buy + |smart_sell|)
        total_value_pkr   = abs(buy_value) + abs(sell_value)   [activity proxy]
    """
    flows = flows.copy()
    flows["is_smart"] = flows["client_type"].isin(SMART_CLIENTS)

    # Absolute volumes (sell_volume stored as negative in DB)
    flows["abs_buy"]  = flows["buy_volume"].clip(lower=0)
    flows["abs_sell"] = flows["sell_volume"].abs()

    # --- totals ---
    grp = flows.groupby(["date", "sector"])
    agg = grp.agg(
        total_buy_vol  =("abs_buy",   "sum"),
        total_sell_vol =("abs_sell",  "sum"),
        total_net_vol  =("net_volume","sum"),
        total_buy_val  =("buy_value", "sum"),
        total_sell_val =("sell_value","sum"),
        total_net_val  =("net_value", "sum"),   # oops — this would sum net_value; recalc below
    ).reset_index()

    # --- smart money sub-totals ---
    smart = (
        flows[flows["is_smart"]]
        .groupby(["date", "sector"])
        .agg(
            smart_buy_vol  =("abs_buy",  "sum"),
            smart_sell_vol =("abs_sell", "sum"),
            smart_net_vol  =("net_volume","sum"),
        )
        .reset_index()
    )

    agg = agg.merge(smart, on=["date","sector"], how="left")
    agg[["smart_buy_vol","smart_sell_vol","smart_net_vol"]] = \
        agg[["smart_buy_vol","smart_sell_vol","smart_net_vol"]].fillna(0)

    # --- derived ratios ---
    total_activity = agg["total_buy_vol"] + agg["total_sell_vol"]
    agg["buy_ratio"] = np.where(
        total_activity > 0, agg["total_buy_vol"] / total_activity, np.nan
    )

    smart_activity = agg["smart_buy_vol"] + agg["smart_sell_vol"]
    agg["smart_buy_ratio"] = np.where(
        smart_activity > 0, agg["smart_buy_vol"] / smart_activity, np.nan
    )

    agg["total_value_pkr"] = agg["total_buy_val"].abs() + agg["total_sell_val"].abs()

    # Map flows sector → PSX sector name
    agg["psx_sector"] = agg["sector"].map(FLOW_SECTOR_MAP)

    return agg.sort_values(["sector", "date"]).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# 3. MERGE FLOWS WITH FORWARD RETURNS
# ══════════════════════════════════════════════════════════════════════════════

def build_analysis_frame(
    agg: pd.DataFrame,
    sect_price: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each (date, psx_sector) in flows, attach:
        ret_fwd_5d, ret_fwd_10d, ret_fwd_20d
        ret_prior_5d  (context: was sector already moving?)
    Also attach rolling flow metrics (3d, 5d):
        buy_ratio_3d_avg, consec_buy_days (days in a row buy_ratio > 0.55)
    """
    # Sector returns keyed on psx_sector
    sp = sect_price.rename(columns={"sector": "psx_sector"})

    # Forward returns: look-ahead on sector price series
    sp_fwd = sp.copy().sort_values(["psx_sector", "date"])
    for lag in [5, 10, 20]:
        sp_fwd[f"ret_fwd_{lag}d"] = (
            sp_fwd.groupby("psx_sector")["close"]
            .transform(lambda x: x.shift(-lag) / x - 1)
        )
    # Backward return (prior 5d context)
    sp_fwd["ret_prior_5d"] = (
        sp_fwd.groupby("psx_sector")["close"]
        .transform(lambda x: x / x.shift(5) - 1)
    )

    # Merge flows with forward returns
    df = agg.merge(
        sp_fwd[["date","psx_sector","ret_1d","ret_prior_5d",
                "ret_fwd_5d","ret_fwd_10d","ret_fwd_20d"]],
        on=["date","psx_sector"],
        how="left",
    )

    # Rolling flow metrics per sector
    df = df.sort_values(["sector", "date"])

    df["buy_ratio_3d_avg"] = (
        df.groupby("sector")["buy_ratio"]
        .transform(lambda x: x.rolling(3, min_periods=1).mean())
    )
    df["buy_ratio_5d_avg"] = (
        df.groupby("sector")["buy_ratio"]
        .transform(lambda x: x.rolling(5, min_periods=1).mean())
    )

    # Consecutive days above 0.55 buy ratio
    def consec_above(series, threshold=0.55):
        result = []
        count = 0
        for v in series:
            if pd.notna(v) and v > threshold:
                count += 1
            else:
                count = 0
            result.append(count)
        return result

    for sector, grp in df.groupby("sector"):
        idx = grp.index
        df.loc[idx, "consec_buy_days"] = consec_above(grp["buy_ratio"].values)

    # Volume z-score vs 20d rolling mean
    df["vol_zscore"] = (
        df.groupby("sector")["total_buy_vol"]
        .transform(lambda x: (x - x.rolling(20, min_periods=5).mean())
                              / (x.rolling(20, min_periods=5).std() + 1))
    )

    return df


# ══════════════════════════════════════════════════════════════════════════════
# 4. PATTERN HUNTERS
# ══════════════════════════════════════════════════════════════════════════════

def _test_pattern(df: pd.DataFrame, mask: pd.Series, horizon: str = "ret_fwd_5d") -> dict:
    """
    Given a boolean mask of pattern occurrences, compute stats against forward return.
    Returns dict with n, win_rate, avg_fwd_ret, p_value, is_significant.
    """
    sub = df[mask & df[horizon].notna()][horizon]
    if len(sub) < 5:
        return {"n": len(sub), "win_rate": None, "avg_fwd_ret": None,
                "p_value": None, "is_significant": False}

    win_rate = (sub > 0).mean()
    avg_ret  = sub.mean()
    # t-test: is mean return different from 0?
    _, p = stats.ttest_1samp(sub, 0)

    return {
        "n":              len(sub),
        "win_rate":       round(win_rate, 3),
        "avg_fwd_ret":    round(avg_ret * 100, 2),   # in %
        "p_value":        round(p, 4),
        "is_significant": (p < MIN_P_VALUE and win_rate >= MIN_WIN_RATE and len(sub) >= MIN_OCCURRENCES),
    }


def hunt_accumulation_divergence(df: pd.DataFrame) -> list[dict]:
    """
    Pattern 1 — ACCUMULATION DIVERGENCE
    Strong buying + flat/declining price → breakout incoming?
    Condition: buy_ratio_3d_avg > 0.62 AND ret_prior_5d < 0.02 (flat or down)
    """
    mask = (df["buy_ratio_3d_avg"] > 0.62) & (df["ret_prior_5d"] < 0.02)
    stats5  = _test_pattern(df, mask, "ret_fwd_5d")
    stats10 = _test_pattern(df, mask, "ret_fwd_10d")

    return [{
        "pattern":     "ACCUMULATION_DIVERGENCE",
        "description": "3d avg buy_ratio > 62% + sector flat/down in prior 5d",
        "horizon_5d":  stats5,
        "horizon_10d": stats10,
        "occurrences_today": int(mask.sum()),
    }]


def hunt_flow_momentum_transition(df: pd.DataFrame) -> list[dict]:
    """
    Pattern 2 — FLOW MOMENTUM TRANSITION
    Flows shift from selling → buying over 2-3 days.
    Proxy: today buy_ratio > 0.60, but 3 days ago buy_ratio < 0.45.
    """
    df = df.sort_values(["sector","date"])
    df["buy_ratio_lag3"] = df.groupby("sector")["buy_ratio"].shift(3)
    mask = (df["buy_ratio"] > 0.60) & (df["buy_ratio_lag3"] < 0.45)
    stats5  = _test_pattern(df, mask, "ret_fwd_5d")
    stats10 = _test_pattern(df, mask, "ret_fwd_10d")

    return [{
        "pattern":     "FLOW_MOMENTUM_TRANSITION",
        "description": "buy_ratio flipped from <45% to >60% in 3 days",
        "horizon_5d":  stats5,
        "horizon_10d": stats10,
        "occurrences_today": int(mask.sum()),
    }]


def hunt_smart_money_divergence(df: pd.DataFrame) -> list[dict]:
    """
    Pattern 3 — SMART MONEY VS RETAIL DIVERGENCE
    Smart money buying while retail sells (contrarian signal).
    Condition: smart_buy_ratio > 0.60 AND overall buy_ratio < 0.50
    """
    mask = (df["smart_buy_ratio"] > 0.60) & (df["buy_ratio"] < 0.50)
    stats5  = _test_pattern(df, mask, "ret_fwd_5d")
    stats10 = _test_pattern(df, mask, "ret_fwd_10d")

    return [{
        "pattern":     "SMART_MONEY_DIVERGENCE",
        "description": "Smart money buy_ratio > 60% while total buy_ratio < 50%",
        "horizon_5d":  stats5,
        "horizon_10d": stats10,
        "occurrences_today": int(mask.sum()),
    }]


def hunt_sustained_accumulation(df: pd.DataFrame) -> list[dict]:
    """
    Pattern 4 — SUSTAINED ACCUMULATION
    3+ consecutive days of buy_ratio > 0.55 → momentum continuation?
    """
    mask = df["consec_buy_days"] >= 3
    stats5  = _test_pattern(df, mask, "ret_fwd_5d")
    stats10 = _test_pattern(df, mask, "ret_fwd_10d")
    stats20 = _test_pattern(df, mask, "ret_fwd_20d")

    return [{
        "pattern":     "SUSTAINED_ACCUMULATION",
        "description": "3+ consecutive days with buy_ratio > 55%",
        "horizon_5d":  stats5,
        "horizon_10d": stats10,
        "horizon_20d": stats20,
        "occurrences_today": int(mask.sum()),
    }]


def hunt_volume_spike_with_buying(df: pd.DataFrame) -> list[dict]:
    """
    Pattern 5 — VOLUME SPIKE + BUYING PRESSURE
    Buy volume z-score > 1.5 AND buy_ratio > 0.60
    """
    mask = (df["vol_zscore"] > 1.5) & (df["buy_ratio"] > 0.60)
    stats5  = _test_pattern(df, mask, "ret_fwd_5d")
    stats10 = _test_pattern(df, mask, "ret_fwd_10d")

    return [{
        "pattern":     "VOLUME_SPIKE_BUYING",
        "description": "Buy volume z-score > 1.5 AND buy_ratio > 60%",
        "horizon_5d":  stats5,
        "horizon_10d": stats10,
        "occurrences_today": int(mask.sum()),
    }]


def run_all_pattern_hunters(df: pd.DataFrame) -> list[dict]:
    results = []
    for fn in [
        hunt_accumulation_divergence,
        hunt_flow_momentum_transition,
        hunt_smart_money_divergence,
        hunt_sustained_accumulation,
        hunt_volume_spike_with_buying,
    ]:
        results.extend(fn(df))
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 5. TODAY'S SNAPSHOT — CURRENT SECTOR SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def get_todays_sector_snapshot(agg: pd.DataFrame, sect_price: pd.DataFrame,
                               enriched_df: pd.DataFrame = None) -> pd.DataFrame:
    """Return a per-sector summary for the most recent flow date."""
    latest_date = agg["date"].max()
    # Use enriched df (with rolling metrics) if provided; else fall back to plain agg
    source = enriched_df if enriched_df is not None else agg
    today_flows = source[source["date"] == latest_date].copy()

    # Attach current 5d performance
    sp = sect_price.rename(columns={"sector": "psx_sector"})
    sp_latest = sp[sp["date"] == sp["date"].max()]

    # 5d return for each sector
    def get_ret(psx_sec, days=5):
        s = sp[sp["psx_sector"] == psx_sec].sort_values("date")
        if len(s) < days + 1:
            return None
        return round((s["close"].iloc[-1] / s["close"].iloc[-1 - days] - 1) * 100, 2)

    today_flows["ret_5d_pct"] = today_flows["psx_sector"].apply(lambda x: get_ret(x) if pd.notna(x) else None)
    today_flows["ret_1d_pct"] = today_flows["psx_sector"].apply(
        lambda x: round(sp[sp["psx_sector"] == x].sort_values("date")["ret_1d"].iloc[-1] * 100, 2)
        if pd.notna(x) and len(sp[sp["psx_sector"] == x]) > 0 else None
    )

    cols = ["sector", "date", "buy_ratio", "smart_buy_ratio",
            "buy_ratio_3d_avg", "consec_buy_days",
            "total_net_vol", "smart_net_vol",
            "vol_zscore", "ret_1d_pct", "ret_5d_pct"]
    available = [c for c in cols if c in today_flows.columns]
    return today_flows[available].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# 6. SIGNAL GENERATION (for today's sector readings)
# ══════════════════════════════════════════════════════════════════════════════

SIGNAL_DEFINITIONS = [
    {
        "name":        "ACCUMULATION_DIVERGENCE",
        "condition":   lambda r: r.get("buy_ratio_3d_avg", 0) > 0.62 and r.get("ret_5d_pct", 100) is not None and r.get("ret_5d_pct", 100) < 2,
        "strength":    lambda r: "STRONG" if r.get("buy_ratio_3d_avg", 0) > 0.70 else "MODERATE",
        "description": "Smart accumulation into flat/falling sector",
    },
    {
        "name":        "SUSTAINED_ACCUMULATION",
        "condition":   lambda r: r.get("consec_buy_days", 0) >= 3,
        "strength":    lambda r: "STRONG" if r.get("consec_buy_days", 0) >= 5 else "MODERATE",
        "description": "3+ consecutive buy-dominant days",
    },
    {
        "name":        "VOLUME_SPIKE_BUYING",
        "condition":   lambda r: r.get("vol_zscore", 0) > 1.5 and r.get("buy_ratio", 0) > 0.60,
        "strength":    lambda r: "STRONG" if r.get("vol_zscore", 0) > 2.5 else "MODERATE",
        "description": "Unusual volume surge with buying dominance",
    },
    {
        "name":        "DISTRIBUTION_WARNING",
        "condition":   lambda r: r.get("buy_ratio_3d_avg", 1) < 0.40,
        "strength":    lambda r: "STRONG" if r.get("buy_ratio_3d_avg", 1) < 0.35 else "MODERATE",
        "description": "Persistent selling pressure — avoid or watch for short",
    },
]


def generate_signals_today(snapshot: pd.DataFrame, patterns: list[dict]) -> list[dict]:
    """
    For each sector in today's snapshot, check which signal definitions fire.
    Attach historical win rate from pattern analysis if available.
    """
    pattern_lookup = {p["pattern"]: p for p in patterns}
    signals = []

    for _, row in snapshot.iterrows():
        r = row.to_dict()
        for sig_def in SIGNAL_DEFINITIONS:
            try:
                if not sig_def["condition"](r):
                    continue
            except Exception:
                continue

            # Pull historical confidence from pattern analysis
            hist = pattern_lookup.get(sig_def["name"], {})
            h5   = hist.get("horizon_5d", {})
            confidence_note = (
                f"Historical: n={h5.get('n','?')}, "
                f"win%={int(h5.get('win_rate',0)*100) if h5.get('win_rate') else '?'}%, "
                f"avg_fwd5d={h5.get('avg_fwd_ret','?')}%"
                if h5 else "Insufficient historical data — building baseline"
            )

            sig = {
                "date":            TODAY,
                "sector":          r.get("sector", "?"),
                "signal_type":     sig_def["name"],
                "strength":        sig_def["strength"](r),
                "description":     sig_def["description"],
                "buy_ratio":       round(r.get("buy_ratio", 0), 3),
                "buy_ratio_3d":    round(r.get("buy_ratio_3d_avg", 0), 3),
                "consec_buy_days": r.get("consec_buy_days", 0),
                "vol_zscore":      round(r.get("vol_zscore", 0), 2) if r.get("vol_zscore") else None,
                "ret_5d_pct":      r.get("ret_5d_pct"),
                "smart_net_vol":   r.get("smart_net_vol"),
                "confidence_note": confidence_note,
                "outcome":         "PENDING",
                "fwd_5d_actual":   None,
                "fwd_10d_actual":  None,
            }
            signals.append(sig)

    return signals


# ══════════════════════════════════════════════════════════════════════════════
# 7. SIGNAL JOURNAL — LOG + VALIDATE
# ══════════════════════════════════════════════════════════════════════════════

def load_signal_journal() -> pd.DataFrame:
    if os.path.exists(LOG_PATH):
        return pd.read_csv(LOG_PATH, parse_dates=["date"])
    return pd.DataFrame()


def save_signals_to_journal(signals: list[dict]):
    if not signals:
        return
    new = pd.DataFrame(signals)
    journal = load_signal_journal()

    if journal.empty:
        combined = new
    else:
        # Avoid duplicating same date+sector+signal_type
        existing_keys = set(zip(
            journal["date"].astype(str),
            journal["sector"],
            journal["signal_type"],
        ))
        to_add = [s for s in signals
                  if (s["date"], s["sector"], s["signal_type"]) not in existing_keys]
        if not to_add:
            return
        combined = pd.concat([journal, pd.DataFrame(to_add)], ignore_index=True)

    combined.to_csv(LOG_PATH, index=False)


def validate_past_signals(agg: pd.DataFrame, sect_price: pd.DataFrame):
    """
    Look back at PENDING signals that are now >= 5 or 10 days old.
    Fill in fwd_5d_actual, fwd_10d_actual, and mark WIN/LOSS/BREAKEVEN.
    """
    journal = load_signal_journal()
    if journal.empty:
        return journal, []

    sp = sect_price.rename(columns={"sector": "psx_sector"})
    updated_rows = []
    outcomes = []

    for idx, row in journal.iterrows():
        if row.get("outcome") != "PENDING":
            continue
        sig_date = pd.to_datetime(row["date"])
        days_since = (pd.Timestamp.today() - sig_date).days

        # Try to fill 5d return
        if days_since >= 5 and pd.isna(row.get("fwd_5d_actual")):
            psx_sec  = agg[agg["sector"] == row["sector"]]["psx_sector"].iloc[0] \
                       if not agg[agg["sector"] == row["sector"]].empty else None
            if psx_sec:
                s = sp[sp["psx_sector"] == psx_sec].sort_values("date")
                base = s[s["date"] <= sig_date]
                fwd  = s[s["date"] > sig_date]
                if len(base) > 0 and len(fwd) >= 5:
                    ret5 = round((fwd["close"].iloc[4] / base["close"].iloc[-1] - 1) * 100, 2)
                    journal.at[idx, "fwd_5d_actual"] = ret5
                    if days_since >= 10 and len(fwd) >= 10:
                        ret10 = round((fwd["close"].iloc[9] / base["close"].iloc[-1] - 1) * 100, 2)
                        journal.at[idx, "fwd_10d_actual"] = ret10

        # Mark outcome when 10d return is available
        if pd.notna(journal.at[idx, "fwd_5d_actual"]):
            ret = journal.at[idx, "fwd_5d_actual"]
            if row["signal_type"] == "DISTRIBUTION_WARNING":
                outcome = "WIN" if ret < 0 else ("LOSS" if ret > 1 else "BREAKEVEN")
            else:
                outcome = "WIN" if ret > 1 else ("LOSS" if ret < -1 else "BREAKEVEN")
            journal.at[idx, "outcome"] = outcome
            outcomes.append({
                "date": row["date"], "sector": row["sector"],
                "signal": row["signal_type"], "fwd_5d": ret, "outcome": outcome,
            })

    journal.to_csv(LOG_PATH, index=False)
    return journal, outcomes


# ══════════════════════════════════════════════════════════════════════════════
# 8. CORRELATION ANALYSIS (rolling windows)
# ══════════════════════════════════════════════════════════════════════════════

def rolling_correlations(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each sector compute Pearson correlation between buy_ratio and ret_fwd_5d
    over the full available window, and also 14d / 30d rolling.
    """
    results = []
    for sector, grp in df.dropna(subset=["buy_ratio","ret_fwd_5d"]).groupby("sector"):
        grp = grp.sort_values("date")
        full_corr  = grp["buy_ratio"].corr(grp["ret_fwd_5d"])
        last30     = grp.tail(30)
        corr_30d   = last30["buy_ratio"].corr(last30["ret_fwd_5d"]) if len(last30) >= 10 else None
        last14     = grp.tail(14)
        corr_14d   = last14["buy_ratio"].corr(last14["ret_fwd_5d"]) if len(last14) >= 7 else None

        # Lag test: does buy_ratio today predict +2d more than +1d?
        grp["ret_lag1"] = grp["ret_fwd_5d"].shift(-1)   # already 5d, shift by 1 more
        corr_lag1 = grp["buy_ratio"].corr(grp["ret_lag1"])

        results.append({
            "sector":       sector,
            "n":            len(grp),
            "corr_full":    round(full_corr, 3) if pd.notna(full_corr) else None,
            "corr_30d":     round(corr_30d,  3) if corr_30d and pd.notna(corr_30d)  else None,
            "corr_14d":     round(corr_14d,  3) if corr_14d and pd.notna(corr_14d)  else None,
            "corr_lag1":    round(corr_lag1, 3) if pd.notna(corr_lag1) else None,
        })
    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# 9. DAILY INTELLIGENCE BRIEF
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_stat(s: dict) -> str:
    if not s or s["n"] < 5:
        return f"  n={s['n'] if s else 0} — insufficient data"
    sig = "✅ SIGNIFICANT" if s["is_significant"] else ("⚠️  building" if s["n"] >= 5 else "🔸 too few")
    return (f"  n={s['n']} | win%={int(s['win_rate']*100)}% | "
            f"avg_fwd={s['avg_fwd_ret']}% | p={s['p_value']} {sig}")


def generate_brief(
    snapshot: pd.DataFrame,
    patterns: list[dict],
    signals: list[dict],
    corr_df: pd.DataFrame,
    validated_outcomes: list[dict],
    flows_date: str,
) -> str:
    lines = []
    divider = "═" * 65

    lines.append(divider)
    lines.append(f"📊  SECTOR FLOWS INTELLIGENCE BRIEF — {flows_date}")
    lines.append(divider)

    # ── Section 1: Today's Sector Snapshot ──
    lines.append("\n🗂️  TODAY'S SECTOR SNAPSHOT")
    lines.append("─" * 65)
    lines.append(f"{'Sector':<22} {'BuyR':>6} {'SmBR':>6} {'3dAvg':>6} "
                 f"{'Consec':>6} {'VolZ':>6} {'1d%':>6} {'5d%':>6}")
    lines.append("─" * 65)
    for _, r in snapshot.sort_values("buy_ratio", ascending=False).iterrows():
        br   = f"{r.get('buy_ratio',0):.1%}"   if pd.notna(r.get('buy_ratio'))   else "  —"
        sbr  = f"{r.get('smart_buy_ratio',0):.1%}" if pd.notna(r.get('smart_buy_ratio')) else "  —"
        avg3 = f"{r.get('buy_ratio_3d_avg',0):.1%}" if pd.notna(r.get('buy_ratio_3d_avg')) else "  —"
        cbd  = f"{int(r.get('consec_buy_days',0))}d"
        vz   = f"{r.get('vol_zscore',0):+.1f}"   if pd.notna(r.get('vol_zscore')) else "  —"
        r1d  = f"{r.get('ret_1d_pct',0):+.1f}%" if pd.notna(r.get('ret_1d_pct')) else "  —"
        r5d  = f"{r.get('ret_5d_pct',0):+.1f}%" if pd.notna(r.get('ret_5d_pct')) else "  —"
        lines.append(f"{str(r['sector']):<22} {br:>6} {sbr:>6} {avg3:>6} "
                     f"{cbd:>6} {vz:>6} {r1d:>6} {r5d:>6}")

    # ── Section 2: New Signals ──
    lines.append(f"\n\n🚦  NEW SIGNALS GENERATED TODAY ({len(signals)} total)")
    lines.append("─" * 65)
    if not signals:
        lines.append("  None fired today.")
    for s in signals:
        action = "🔴 WATCH (short)" if "DISTRIBUTION" in s["signal_type"] else "🟢 ALERT (long bias)"
        lines.append(
            f"\n  {action}  {s['sector']}  [{s['strength']}]"
            f"\n  Type      : {s['signal_type']}"
            f"\n  Trigger   : {s['description']}"
            f"\n  Buy Ratio : {s['buy_ratio']:.1%}  |  3d avg: {s['buy_ratio_3d']:.1%}"
            f"\n  Consec    : {s['consec_buy_days']}d  |  VolZ: {s['vol_zscore']}"
            f"\n  Sector 5d : {s['ret_5d_pct']}%"
            f"\n  Confidence: {s['confidence_note']}"
        )

    # ── Section 3: Pattern Status (all patterns) ──
    lines.append(f"\n\n🔬  PATTERN ANALYSIS (full history)")
    lines.append("─" * 65)
    for p in patterns:
        h5  = p.get("horizon_5d",  {})
        h10 = p.get("horizon_10d", {})
        h20 = p.get("horizon_20d", {})
        lines.append(f"\n  [{p['pattern']}]")
        lines.append(f"  Desc    : {p['description']}")
        lines.append(f"  5d fwd  :{_fmt_stat(h5)}")
        lines.append(f"  10d fwd :{_fmt_stat(h10)}")
        if h20:
            lines.append(f"  20d fwd :{_fmt_stat(h20)}")

    # ── Section 4: Rolling Correlations ──
    lines.append(f"\n\n📈  ROLLING BUY_RATIO → FWD_5D CORRELATIONS")
    lines.append("─" * 65)
    lines.append(f"{'Sector':<22} {'Full':>7} {'30d':>7} {'14d':>7}  Note")
    lines.append("─" * 65)
    for _, r in corr_df.sort_values("corr_full", ascending=False, key=lambda x: x.abs()).iterrows():
        full = f"{r['corr_full']:+.3f}" if pd.notna(r['corr_full']) else "   —"
        c30  = f"{r['corr_30d']:+.3f}"  if pd.notna(r['corr_30d'])  else "   —"
        c14  = f"{r['corr_14d']:+.3f}"  if pd.notna(r['corr_14d'])  else "   —"
        note = ""
        if pd.notna(r['corr_full']) and abs(r['corr_full']) > 0.25:
            note = "← meaningful"
        lines.append(f"{r['sector']:<22} {full:>7} {c30:>7} {c14:>7}  {note}")

    lines.append("\n  Interpretation: +ve = buying flows → positive fwd returns.")
    lines.append("  |corr| > 0.20 considered worth tracking.")

    # ── Section 5: Validation Results ──
    lines.append(f"\n\n✅  SIGNAL VALIDATION RESULTS")
    lines.append("─" * 65)
    if not validated_outcomes:
        lines.append("  No past signals have matured yet (need ≥5 days).")
    else:
        for o in validated_outcomes:
            icon = "✅" if o["outcome"] == "WIN" else ("❌" if o["outcome"] == "LOSS" else "➡️")
            lines.append(f"  {icon} {o['date']}  {o['sector']:<22}  "
                         f"{o['signal']:<28}  fwd5d={o['fwd_5d']:+.1f}%  {o['outcome']}")

    # ── Section 6: Overall journal stats ──
    journal = load_signal_journal()
    if not journal.empty and "outcome" in journal.columns:
        closed = journal[journal["outcome"].isin(["WIN","LOSS","BREAKEVEN"])]
        if len(closed) > 0:
            wr = (closed["outcome"] == "WIN").sum() / len(closed)
            lines.append(f"\n  Journal total: {len(journal)} signals | "
                         f"{len(closed)} resolved | Win rate: {wr:.1%}")

    # ── Section 7: Key observations / story ──
    lines.append(f"\n\n💡  PATTERN INSIGHTS & STORY")
    lines.append("─" * 65)

    # Auto-generate narrative from snapshot
    top_buy   = snapshot.nlargest(2, "buy_ratio")
    top_sell  = snapshot.nsmallest(2, "buy_ratio")
    smart_top = snapshot.nlargest(1, "smart_buy_ratio") if "smart_buy_ratio" in snapshot.columns else None

    if not top_buy.empty:
        lines.append(f"  Strongest buying  : {', '.join(top_buy['sector'].tolist())}")
    if not top_sell.empty:
        lines.append(f"  Strongest selling : {', '.join(top_sell['sector'].tolist())}")
    if smart_top is not None and not smart_top.empty:
        lines.append(f"  Smart money top   : {smart_top['sector'].iloc[0]} "
                     f"(smart_buy_ratio={smart_top['smart_buy_ratio'].iloc[0]:.1%})")

    # Data coverage note
    lines.append(f"\n  ⚠️  DATA NOTE: Only {flows_date} available for flows correlation.")
    lines.append(f"  With ~22 days of history, most patterns will show 'building baseline'.")
    lines.append(f"  Statistical significance requires 10+ occurrences — expect that by ~2026-07-15.")

    # ── Section 8: Next watch points ──
    lines.append(f"\n\n🔭  NEXT WATCH POINTS")
    lines.append("─" * 65)
    watch = []
    for _, r in snapshot.iterrows():
        cbd = r.get("consec_buy_days", 0)
        br3 = r.get("buy_ratio_3d_avg", 0)
        if cbd >= 2 and br3 > 0.58:
            watch.append(f"  → {r['sector']}: {int(cbd)}d buy streak, avg {br3:.1%} — watch for continuation")
        elif r.get("buy_ratio", 0) < 0.38:
            watch.append(f"  → {r['sector']}: sustained selling ({r.get('buy_ratio',0):.1%}) — avoid longs")

    if watch:
        lines.extend(watch)
    else:
        lines.append("  No extreme setups. Normal rotation day.")

    lines.append(f"\n{divider}")
    lines.append(f"Engine run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  "
                 f"Flows date: {flows_date}  |  Sectors tracked: {len(snapshot)}")
    lines.append(divider)

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 10. MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run():
    print("Loading data…")
    flows_raw, prices, sect_price = load_data()

    print("Aggregating flows…")
    agg = aggregate_flows(flows_raw)

    print("Building analysis frame (flows + forward returns)…")
    df = build_analysis_frame(agg, sect_price)

    print("Running pattern hunters…")
    patterns = run_all_pattern_hunters(df)

    print("Generating today's snapshot…")
    snapshot = get_todays_sector_snapshot(agg, sect_price, enriched_df=df)

    print("Generating today's signals…")
    signals = generate_signals_today(snapshot, patterns)

    print("Validating past signals…")
    _, validated_outcomes = validate_past_signals(agg, sect_price)

    print("Computing correlations…")
    corr_df = rolling_correlations(df)

    # Save new signals
    save_signals_to_journal(signals)

    # Generate brief
    flows_date = agg["date"].max().date().isoformat()
    brief = generate_brief(snapshot, patterns, signals, corr_df, validated_outcomes, flows_date)
    print(brief)

    # Also save brief to file
    brief_path = os.path.join(os.path.dirname(__file__), "sector_flows_brief.txt")