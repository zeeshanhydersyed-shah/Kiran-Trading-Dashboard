"""PSX Sector Performance Dashboard — KIRAN."""

import json
import sys
import logging
import warnings
from datetime import datetime

import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np

# Try to import joblib, but don't crash if it's missing
try:
    import joblib
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False
    joblib = None

import pandas as pd
import streamlit as st

# ✅ Safe Plotly import
try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    go = None
    px = None

# Show warning if joblib is missing (but don't crash)
if not HAS_JOBLIB:
    import warnings
    warnings.warn("joblib not installed. Run: pip install -r requirements.txt", RuntimeWarning)

# ── Bridge Streamlit secrets → os.environ BEFORE importing database ───────────
# Streamlit Cloud sometimes injects secrets after Python's import phase starts.
# Reading from st.secrets here guarantees DATABASE_URL is visible to database.py.
try:
    _secrets = st.secrets
    for _k in ("DATABASE_URL", "SUPABASE_DB_URL"):
        if _k not in _os.environ and _k in _secrets:
            _os.environ[_k] = str(_secrets[_k])
except Exception:
    pass  # no secrets configured — falls back to SQLite

from database import (
    init_db, get_price_date_range, count_prices, count_sectors,
    get_latest_stock_date, get_latest_index_date,
    save_trade_setup, get_trade_setups, update_trade_setup, close_trade_setup,
    activate_trade_setup, delete_trade_setup, auto_save_setups, get_backtest_summary,
    auto_save_stm_picks, get_sim_portfolio_data,
    add_portfolio_transaction, get_portfolio_transactions, delete_portfolio_transaction,
    add_portfolio_value, get_portfolio_values, delete_portfolio_value,
    evaluate_paper_trades,
)
from processor import run_analysis
from stm_sr_integration import enrich_stm_with_sr_zones

# Gracefully handle missing optional imports
try:
    from main import cmd_update
    HAS_CMD_UPDATE = True
except ImportError as e:
    HAS_CMD_UPDATE = False
    warnings.warn(f"Could not import cmd_update from main: {e}", RuntimeWarning)
    cmd_update = None

try:
    from refresh_manager import (
        execute_refresh_with_tracking,
        check_refresh_throttle,
        record_refresh_time,
        get_refresh_message,
        get_source_date_cached,
    )
    HAS_REFRESH_MANAGER = True
except ImportError as e:
    HAS_REFRESH_MANAGER = False
    warnings.warn(f"Could not import refresh_manager: {e}", RuntimeWarning)

logger = logging.getLogger(__name__)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KIRAN · PSX",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Give enough room so the KIRAN header is never clipped by the toolbar */
.block-container {
    padding-top: 2.5rem !important;
    padding-bottom: 1rem !important;
    overflow: visible !important;
}

/* Compact metrics */
[data-testid="metric-container"] {
    border-radius: 6px;
    padding: 6px 10px !important;
}
[data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
[data-testid="stMetricValue"] { font-size: 1.05rem !important; font-weight: 700 !important; }
[data-testid="stMetricDelta"] { font-size: 0.7rem !important; }

/* Captions */
[data-testid="stCaptionContainer"] p { font-size: 0.73rem !important; }

/* Alert/info boxes */
[data-testid="stAlert"] { padding: 8px 12px !important; }
[data-testid="stAlert"] p { font-size: 0.8rem !important; }

/* Divider spacing */
hr { margin: 6px 0 !important; }

/* Sidebar tighter */
[data-testid="stSidebar"] .block-container { padding-top: 1rem !important; }

/* ── Nav bar: tabs look ── */
div[data-testid="stHorizontalBlock"] > div > div > div > button {
    border-radius: 4px 4px 0 0 !important;
    font-size: 0.78rem !important;
    padding: 6px 4px !important;
    white-space: nowrap !important;
    text-align: center !important;
    width: 100% !important;
    border-bottom: 3px solid transparent !important;
}
/* Active tab gets a coloured bottom border */
div[data-testid="stHorizontalBlock"] > div > div > div > button[kind="primary"] {
    border-bottom: 3px solid #3b82f6 !important;
    color: #1e40af !important;
}
/* Compact sidebar */
[data-testid="stSidebar"] .block-container {
    padding-top: 0.75rem !important;
    padding-bottom: 0.5rem !important;
}
[data-testid="stSidebar"] button {
    font-size: 0.78rem !important;
    padding: 4px 8px !important;
}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=7200, show_spinner=False)  # 2 hours instead of 30 min
def load_data() -> dict:
    init_db()
    data = run_analysis()
    # Always fetch fresh KSE-100 to avoid stale 50-MA in header vs. charts
    from kse100_filter import KSE100Filter
    data["kse100"] = KSE100Filter().kse100_summary()
    return data


@st.cache_data(ttl=300, show_spinner=False)  # Shorter cache since user updates these
def load_portfolio_pnl() -> pd.DataFrame:
    """
    Load and calculate portfolio P&L from investment transactions and closing values.
    Combines hardcoded historical data with database entries updated by user.

    Returns DataFrame with columns:
    - date: transaction/portfolio value date
    - portfolio_value: portfolio value on that date
    - cumulative_deposits: cumulative net deposits (deposits - withdrawals)
    - initial_investment: starting portfolio value
    """
    # Historical transactions (from user's initial submission)
    historical_transactions = [
        {"date": "2024-10-01", "amount": -498767, "type": "initial"},
        {"date": "2024-12-13", "amount": -450000, "type": "deposit"},
        {"date": "2025-04-08", "amount": 25226, "type": "dividend"},
        {"date": "2025-04-09", "amount": 10200, "type": "dividend"},
        {"date": "2025-06-11", "amount": 10000, "type": "withdrawal"},
        {"date": "2025-07-29", "amount": 55000, "type": "withdrawal"},
        {"date": "2025-11-13", "amount": 200000, "type": "withdrawal"},
        {"date": "2026-03-31", "amount": -1000000, "type": "deposit"},
    ]

    # Historical portfolio values
    historical_values = [
        {"date": "2024-12-27", "value": 1039551},
        {"date": "2025-01-31", "value": 1042921},
        {"date": "2025-02-28", "value": 1080405},
        {"date": "2025-03-28", "value": 1111348},
        {"date": "2025-04-25", "value": 1062781},
        {"date": "2025-05-30", "value": 1070866},
        {"date": "2025-06-30", "value": 1104444},
        {"date": "2025-07-31", "value": 1182240},
        {"date": "2025-08-31", "value": 1191315},
        {"date": "2025-09-30", "value": 1412790},
        {"date": "2025-10-31", "value": 1342426},
        {"date": "2025-11-30", "value": 1085614},
        {"date": "2025-12-31", "value": 1135570},
        {"date": "2026-01-31", "value": 1132629},
        {"date": "2026-02-27", "value": 1118717},
        {"date": "2026-03-31", "value": 2171150},
        {"date": "2026-04-30", "value": 2151051},
    ]

    # Load user-entered transactions from database
    try:
        db_transactions = get_portfolio_transactions()
    except Exception:
        db_transactions = []

    try:
        db_values = get_portfolio_values()
    except Exception:
        db_values = []

    # Combine historical + database transactions
    all_tx = historical_transactions.copy()
    for tx in db_transactions:
        all_tx.append({
            "date": tx["date"],
            "amount": tx["amount"],
            "type": tx["type"],
        })

    # Combine historical + database values
    all_vals = historical_values.copy()
    val_dates = {v["date"] for v in all_vals}
    for val in db_values:
        if val["date"] not in val_dates:
            all_vals.append({
                "date": val["date"],
                "value": val["value"],
            })
        else:
            # Update if database has newer value for same date
            all_vals = [v if v["date"] != val["date"] else {"date": val["date"], "value": val["value"]}
                       for v in all_vals]

    # Create DataFrames
    pv_df = pd.DataFrame(all_vals)
    pv_df["date"] = pd.to_datetime(pv_df["date"])
    pv_df = pv_df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    pv_df.rename(columns={"value": "portfolio_value"}, inplace=True)

    tx_df = pd.DataFrame(all_tx)
    tx_df["date"] = pd.to_datetime(tx_df["date"])

    # Calculate cumulative net capital (deposits - withdrawals, excluding initial)
    tx_df_capital = tx_df[tx_df["type"] != "initial"].copy()
    tx_df_capital["cumulative"] = tx_df_capital["amount"].cumsum()

    # Merge and forward-fill cumulative capital
    pv_df = pv_df.merge(
        tx_df_capital[["date", "cumulative"]].drop_duplicates(),
        on="date", how="left"
    ).sort_values("date")
    pv_df["cumulative"] = pv_df["cumulative"].ffill().fillna(0)

    # Starting capital (initial investment)
    initial = 498767  # From Oct 2024 starting value
    pv_df["initial_investment"] = initial

    return pv_df


@st.cache_data(ttl=1800, show_spinner=False)
def load_kse100_performance() -> pd.DataFrame:
    """Load KSE-100 index data for performance comparison."""
    from database import get_index_prices

    idx_rows = get_index_prices("KSE-100")
    if not idx_rows:
        return pd.DataFrame()

    idx_df = pd.DataFrame(idx_rows)
    idx_df["date"] = pd.to_datetime(idx_df["date"])
    idx_df = idx_df[["date", "close"]].sort_values("date")
    idx_df.columns = ["date", "kse100"]

    return idx_df


def calculate_irr(cash_flows: list, dates: list) -> float:
    """
    Calculate Internal Rate of Return using bisection method (most reliable).
    """
    try:
        dates = [pd.to_datetime(d) if isinstance(d, str) else d for d in dates]

        if len(cash_flows) < 2:
            return 0.0

        ref_date = dates[0]
        years = [float((d - ref_date).days) / 365.25 for d in dates]

        # NPV function
        def npv(rate):
            return sum(cf / ((1 + rate) ** t) for cf, t in zip(cash_flows, years))

        # Try bisection method - most robust
        from scipy.optimize import brentq

        # Find bounds where NPV changes sign
        npv_low = npv(-0.99)  # Can't go below -100%
        npv_high = npv(5.0)   # Try up to 500%

        if npv_low * npv_high < 0:  # Different signs = root exists
            irr = brentq(npv, -0.99, 5.0, xtol=1e-6)
            return float(irr)
        else:
            # No sign change - try Newton's method as fallback
            from scipy.optimize import newton
            try:
                irr = newton(npv, 0.1, maxiter=100)
                return float(irr) if -1.0 < irr < 5.0 else 0.0
            except:
                return 0.0
    except Exception as e:
        return 0.0


@st.cache_data(ttl=1800, show_spinner=False)
def load_sector_history(symbols: tuple) -> pd.DataFrame:
    from database import get_sector_price_data
    raw = get_sector_price_data()
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    df = df[df["symbol"].isin(symbols)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])

    def normalise(grp):
        first = grp.iloc[0]["close"]
        if first == 0:
            return grp
        grp = grp.copy()
        grp["idx"] = grp["close"] / first * 100
        return grp

    df = df.groupby("symbol", group_keys=False).apply(normalise)
    return (
        df.groupby("date")["idx"]
        .mean().reset_index()
        .rename(columns={"idx": "index_value"})
    )


# ── Weinstein breadth loader ──────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_weinstein_data() -> dict:
    """
    Pull all prices + KSE-100 index, compute breadth series and signals.
    Returns a dict with keys: breadth, signals, regime, error.
    Cached for 1 hour.
    """
    import traceback as _tb
    try:
        from database import get_prices_for_breadth, get_index_prices
        from weinstein import compute_breadth_series, WeinsteinIndicator, PSX_DEFAULTS

        raw_prices = get_prices_for_breadth()
        if not raw_prices:
            return {"error": "No price data available."}

        prices_df = (
            pd.DataFrame(raw_prices)
            .assign(
                date  = lambda d: pd.to_datetime(d["date"]),
                close = lambda d: pd.to_numeric(d["close"], errors="coerce"),
            )
            .dropna(subset=["close"])
            .copy()
        )

        # KSE-100 index
        idx_rows = get_index_prices("KSE-100")
        if idx_rows:
            idx_df = (
                pd.DataFrame(idx_rows)
                .assign(
                    date  = lambda d: pd.to_datetime(d["date"]),
                    close = lambda d: pd.to_numeric(d["close"], errors="coerce"),
                )
                .dropna(subset=["close"])
                .copy()
            )
            index_close = idx_df.set_index("date")["close"].sort_index()
        else:
            index_close = prices_df.groupby("date")["close"].mean().sort_index()

        # Breadth series (% stocks above 50-day MA)
        breadth = compute_breadth_series(prices_df, ma_period=PSX_DEFAULTS["ma_period"])

        if len(breadth) < 60:
            return {"error": f"Only {len(breadth)} breadth data points — need at least 60."}

        ind     = WeinsteinIndicator(**PSX_DEFAULTS)
        signals = ind.generate_signals(breadth, index_close)
        regime  = ind.current_regime(signals)

        return {
            "breadth":  breadth,
            "signals":  signals,
            "regime":   regime,
            "params":   PSX_DEFAULTS,
            "error":    None,
        }
    except Exception as exc:
        return {"error": _tb.format_exc()}


# ── Advance-Decline loader ────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_ad_ratio_data() -> pd.DataFrame:
    """
    Compute daily Advance-Decline data across all PSX stocks.
    Returns DataFrame with columns: advances, declines, net_advances, ma10.
    """
    try:
        from database import get_prices_for_breadth
        raw = get_prices_for_breadth()
        if not raw:
            return pd.DataFrame()

        df = (
            pd.DataFrame(raw)
            .assign(
                date=lambda d: pd.to_datetime(d["date"]),
                close=lambda d: pd.to_numeric(d["close"], errors="coerce"),
            )
            .dropna(subset=["close"])
        )

        psx_data = df.pivot_table(index="date", columns="symbol", values="close").sort_index()

        daily_chg    = psx_data.diff()
        advances     = (daily_chg > 0).sum(axis=1)
        declines     = (daily_chg < 0).sum(axis=1)
        net_advances = advances - declines

        result = pd.DataFrame({
            "advances":     advances,
            "declines":     declines,
            "net_advances": net_advances,
            "ma10":         net_advances.rolling(10, min_periods=1).mean(),
        })

        # Drop the first row (no valid diff on day 0)
        return result.iloc[1:]
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_breadth_oscillator_data() -> pd.DataFrame:
    """
    Load ZH Breadth Oscillator data from breadth_data.csv.
    Returns DataFrame with columns: Date, Long_Count, Short_Count.
    """
    try:
        import os
        csv_path = os.path.join(os.path.dirname(__file__), "breadth_data.csv")
        if not os.path.exists(csv_path):
            return pd.DataFrame()

        df = pd.read_csv(csv_path)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date")
        return df
    except Exception:
        return pd.DataFrame()


# ── STM screener data loader ──────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def load_stm_prices() -> pd.DataFrame:
    from database import get_sector_price_data
    raw = get_sector_price_data()
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    df["date"]   = pd.to_datetime(df["date"])
    df["close"]  = pd.to_numeric(df["close"],  errors="coerce")
    df["high"]   = pd.to_numeric(df["high"],   errors="coerce")
    df["low"]    = pd.to_numeric(df["low"],    errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return df.sort_values(["symbol", "date"])


def _compute_stm_signals(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-symbol compute: latest_close, 21MA, 50MA, 5-day range %, avg 10-day volume.
    Requires at least 50 rows per symbol.
    """
    df = prices_df.copy()

    # Keep last 60 rows per symbol — enough for 50 MA with headroom
    df = df.groupby("symbol", group_keys=False).tail(60)

    # Drop symbols that still don't have 50 bars
    counts = df.groupby("symbol").size()
    df = df[df["symbol"].isin(counts[counts >= 50].index)].copy()

    if df.empty:
        return pd.DataFrame()

    # Rolling MAs aligned to the last row per symbol
    df = df.sort_values(["symbol", "date"])
    g_close = df.groupby("symbol")["close"]
    df["ma21"] = g_close.transform(lambda s: s.rolling(21, min_periods=21).mean())
    df["ma50"] = g_close.transform(lambda s: s.rolling(50, min_periods=50).mean())

    # ATR-14 (true range)
    df["prev_close"] = df.groupby("symbol")["close"].shift(1)
    hl  = (df["high"] - df["low"]).abs()
    hpc = (df["high"] - df["prev_close"]).abs()
    lpc = (df["low"]  - df["prev_close"]).abs()
    df["tr"]     = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["atr_14"] = df.groupby("symbol")["tr"].transform(
        lambda s: s.rolling(14, min_periods=14).mean()
    )

    # Latest row per symbol carries the final MA values
    # Use idxmax on date so we always get the true last trading day, not last non-null per column
    latest_idx = df.groupby("symbol")["date"].idxmax()
    latest = df.loc[latest_idx].reset_index(drop=True)

    # 5-day high/low for range
    last5 = df.groupby("symbol", group_keys=False).tail(5)
    range5 = (
        last5.groupby("symbol")
        .agg(high5=("high", "max"), low5=("low", "min"))
        .reset_index()
    )

    # 10-day average volume
    last10  = df.groupby("symbol", group_keys=False).tail(10)
    vol10   = last10.groupby("symbol")["volume"].mean().reset_index(name="avg_vol_10d")

    result = (
        latest[["symbol", "sector", "date", "close", "low", "ma21", "ma50", "atr_14"]]
        .rename(columns={"close": "latest_close", "date": "as_of_date", "low": "day_low"})
        .merge(range5, on="symbol", how="left")
        .merge(vol10,  on="symbol", how="left")
    )

    result["range_5d_pct"] = (
        (result["high5"] - result["low5"]) / result["low5"] * 100
    ).round(2)

    for c in ("latest_close", "ma21", "ma50"):
        result[c] = result[c].round(2)

    result["atr_pct"] = (result["atr_14"] / result["latest_close"] * 100).round(2)

    return result.drop(columns=["high5", "low5", "atr_14"]).dropna(subset=["ma21", "ma50"])


def _run_stm_screener(data: dict, w_data: dict) -> dict:
    """
    Run all STM filter layers for both LONG and SHORT directions.

    LONG  — KSE above 50MA, Z-histogram > 0, breadth >= 70,
            top 35% sectors, close > 21MA > 50MA, outperforming index.
    SHORT — exact opposite: KSE below 50MA, Z-histogram < 0, breadth <= 30,
            bottom 35% sectors, close < 21MA < 50MA, underperforming index.

    Returns dict with keys:
        all_pass, gates, qual_sectors, kse_30d, result          (LONG)
        short_all_pass, short_gates, short_qual_sectors, short_result  (SHORT)
    """
    kse100_d  = data.get("kse100", {})
    breadth_d = data.get("breadth", {})
    regime_d  = w_data.get("regime", {}) if not w_data.get("error") else {}

    kse_close  = kse100_d.get("close", 0) or 0
    kse_ma50   = kse100_d.get("ma50")
    z_hist_val = regime_d.get("z_histogram")
    bs         = float(breadth_d.get("breadth_score") or 0)
    kse_30d    = float(kse100_d.get("perf_30d") or 0.0)

    # ── LONG gates ────────────────────────────────────────────────────────────
    gate_kse = bool(kse100_d.get("above_ma50", False))
    gate_reg = bool(z_hist_val is not None and z_hist_val > 0)
    gate_br  = bool(bs >= 70)
    gates = [
        ("KSE-100 > 50 MA",        gate_kse, f"{kse_close:,.0f} vs MA {kse_ma50:,.0f}" if kse_ma50 else "unavailable"),
        ("Regime: Fast Z > Signal", gate_reg, f"Histogram {z_hist_val:+.3f}" if z_hist_val is not None else "unavailable"),
        ("Breadth: Bullish (≥ 70)", gate_br,  f"Score {bs:.0f}/100"),
    ]
    all_pass = gate_kse and gate_reg and gate_br

    # ── SHORT gates (exact opposite) ─────────────────────────────────────────
    short_gate_kse = not gate_kse
    short_gate_reg = bool(z_hist_val is not None and z_hist_val < 0)
    short_gate_br  = bool(bs <= 30)
    short_gates = [
        ("KSE-100 < 50 MA",         short_gate_kse, f"{kse_close:,.0f} vs MA {kse_ma50:,.0f}" if kse_ma50 else "unavailable"),
        ("Regime: Fast Z < Signal",  short_gate_reg, f"Histogram {z_hist_val:+.3f}" if z_hist_val is not None else "unavailable"),
        ("Breadth: Bearish (≤ 30)",  short_gate_br,  f"Score {bs:.0f}/100"),
    ]
    short_all_pass = short_gate_kse and short_gate_reg and short_gate_br

    # ── Sector sets ───────────────────────────────────────────────────────────
    sector_df_s = data.get("sector_df", pd.DataFrame())
    n_sec   = len(sector_df_s)
    cutoff  = max(1, round(n_sec * 0.35))

    qual_sec = set()
    weak_sec = set()
    if not sector_df_s.empty:
        qual_sec = set(sector_df_s[sector_df_s["rank"] <= cutoff]["sector"].tolist())
        weak_sec = set(sector_df_s[sector_df_s["rank"] > (n_sec - cutoff)]["sector"].tolist())

    # Early return if neither side needs stock scan
    if not all_pass and not short_all_pass:
        return dict(
            all_pass=False, gates=gates, qual_sectors=qual_sec, kse_30d=kse_30d,
            result=pd.DataFrame(),
            short_all_pass=False, short_gates=short_gates,
            short_qual_sectors=weak_sec, short_result=pd.DataFrame(),
        )

    prices_raw = load_stm_prices()
    if prices_raw.empty:
        return dict(
            all_pass=all_pass, gates=gates, qual_sectors=qual_sec, kse_30d=kse_30d,
            result=pd.DataFrame(),
            short_all_pass=short_all_pass, short_gates=short_gates,
            short_qual_sectors=weak_sec, short_result=pd.DataFrame(),
        )

    signals_df = _compute_stm_signals(prices_raw)
    if signals_df.empty:
        return dict(
            all_pass=all_pass, gates=gates, qual_sectors=qual_sec, kse_30d=kse_30d,
            result=pd.DataFrame(),
            short_all_pass=short_all_pass, short_gates=short_gates,
            short_qual_sectors=weak_sec, short_result=pd.DataFrame(),
        )

    # Merge performance data
    stock_30d_df = data["stock_30d"][["symbol", "perf_pct"]].rename(columns={"perf_pct": "perf_30d"})
    stock_10d_raw = data.get("stock_10d", pd.DataFrame())
    stock_10d_df  = (
        stock_10d_raw[["symbol", "perf_pct"]].rename(columns={"perf_pct": "perf_10d"})
        if not stock_10d_raw.empty and "perf_pct" in stock_10d_raw.columns
        else pd.DataFrame(columns=["symbol", "perf_10d"])
    )
    sec_rank_df = (
        sector_df_s[["sector", "rank"]].rename(columns={"rank": "sector_rank"})
        if not sector_df_s.empty else pd.DataFrame(columns=["sector", "sector_rank"])
    )

    df_s = (
        signals_df
        .merge(stock_30d_df, on="symbol", how="inner")
        .merge(stock_10d_df, on="symbol", how="left")
        .merge(sec_rank_df,  on="sector",  how="left")
    )
    df_s["perf_10d"]    = df_s["perf_10d"].fillna(0.0)
    df_s["sector_rank"] = df_s["sector_rank"].fillna(99).astype(int)

    # ── LONG candidates ───────────────────────────────────────────────────────
    result = pd.DataFrame()
    if all_pass:
        long_mask = (
            df_s["sector"].isin(qual_sec)
            & (df_s["range_5d_pct"] <= 10.0)
            & (df_s["avg_vol_10d"]  >= 500_000)
            & (df_s["latest_close"] >  10.0)
            & (df_s["perf_30d"]     >  kse_30d)
            & (df_s["latest_close"] >  df_s["ma21"])
            & (df_s["ma21"]         >  df_s["ma50"])
        )
        result = df_s[long_mask].copy()
        result["rs"]            = (result["perf_30d"] - kse_30d).round(2)
        result["dist_21ma_pct"] = ((result["latest_close"] - result["ma21"]) / result["ma21"] * 100).round(2)
        result["stop_loss"]     = (result["day_low"] * 0.99).round(2)
        result["risk_pct"]      = ((result["latest_close"] - result["stop_loss"]) / result["latest_close"] * 100).round(2)
        result["target_1r"]     = (result["latest_close"] + (result["latest_close"] - result["stop_loss"])).round(2)
        result["target_2r"]     = (result["latest_close"] + 2 * (result["latest_close"] - result["stop_loss"])).round(2)
        result["tradeable"]     = result["risk_pct"] <= 6.0
        result["breadth_score"] = bs
        result = result.sort_values("rs", ascending=False).reset_index(drop=True)
        result.index = result.index + 1

    # ── SHORT candidates (exact mirror) ──────────────────────────────────────
    short_result = pd.DataFrame()
    if short_all_pass:
        # Need day_high for short SL — compute from prices_raw
        last1 = prices_raw.groupby("symbol", group_keys=False).tail(1)[["symbol", "high"]].copy()
        df_short = df_s.merge(last1.rename(columns={"high": "day_high"}), on="symbol", how="left")

        short_mask = (
            df_short["sector"].isin(weak_sec)
            & (df_short["range_5d_pct"] <= 10.0)
            & (df_short["avg_vol_10d"]  >= 500_000)
            & (df_short["latest_close"] >  10.0)
            & (df_short["perf_30d"]     <  kse_30d)
            & (df_short["latest_close"] <  df_short["ma21"])
            & (df_short["ma21"]         <  df_short["ma50"])
        )
        short_result = df_short[short_mask].copy()
        short_result["rs_short"]       = (kse_30d - short_result["perf_30d"]).round(2)   # positive = more underperforming
        short_result["dist_21ma_pct"]  = ((short_result["latest_close"] - short_result["ma21"]) / short_result["ma21"] * 100).round(2)
        short_result["stop_loss"]      = (short_result["day_high"] * 1.01).round(2)
        short_result["risk_pct"]       = ((short_result["stop_loss"] - short_result["latest_close"]) / short_result["latest_close"] * 100).round(2)
        short_result["target_1r"]      = (short_result["latest_close"] - (short_result["stop_loss"] - short_result["latest_close"])).round(2)
        short_result["target_2r"]      = (short_result["latest_close"] - 2 * (short_result["stop_loss"] - short_result["latest_close"])).round(2)
        short_result["tradeable"]      = short_result["risk_pct"] <= 6.0
        short_result["breadth_score"]  = bs
        short_result = short_result.sort_values("rs_short", ascending=False).reset_index(drop=True)
        short_result.index = short_result.index + 1

    return dict(
        all_pass=all_pass, gates=gates, qual_sectors=qual_sec,
        kse_30d=kse_30d, result=result,
        short_all_pass=short_all_pass, short_gates=short_gates,
        short_qual_sectors=weak_sec, short_result=short_result,
    )


# ── ML model loader ───────────────────────────────────────────────────────────

_MODEL_DIR = __file__.rsplit("\\", 1)[0]

@st.cache_resource(show_spinner=False)
def load_ml_model():
    """Load kiran_model.pkl and kiran_model_features.pkl. Returns (model, features) or (None, None)."""
    import os

    # If joblib is not available, return None
    if not HAS_JOBLIB:
        return None, None

    model_path    = os.path.join(_MODEL_DIR, "kiran_model.pkl")
    features_path = os.path.join(_MODEL_DIR, "kiran_model_features.pkl")
    if not os.path.exists(model_path) or not os.path.exists(features_path):
        return None, None

    try:
        model    = joblib.load(model_path)
        features = joblib.load(features_path)
        return model, features
    except Exception as e:
        # Log other errors but don't crash
        logger.warning(f"Could not load ML model: {str(e)}")
        return None, None


def get_ml_confidence(setup_row: dict) -> "float | None":
    """
    Extract the 10 training features from a setup dict and return
    predict_proba win probability (0–1), or None if unavailable.

    Feature order must exactly match training:
      ["log_vol", "atr_pct", "stock_perf_30d", "risk_pct",
       "momentum_ratio", "dist_to_entry_pct", "sector_rank",
       "month", "stock_perf_10d", "breadth_score"]
    """
    model, features = load_ml_model()
    if model is None or features is None:
        return None

    try:
        avg_vol_10d    = setup_row.get("avg_vol_10d")
        atr_pct        = setup_row.get("atr_pct")
        stock_perf_30d = setup_row.get("stock_perf_30d")
        risk_pct       = setup_row.get("risk_pct")
        stock_perf_10d = setup_row.get("stock_perf_10d")
        sector_rank    = setup_row.get("sector_rank")
        breadth_score  = setup_row.get("breadth_score")
        # live setups use "created_date"; backtest setups use "as_of_date"
        as_of_date     = setup_row.get("as_of_date") or setup_row.get("created_date")
        entry_price    = setup_row.get("entry_price")
        latest_close   = setup_row.get("latest_close")

        # Require all raw inputs to be present
        required = [avg_vol_10d, atr_pct, stock_perf_30d, risk_pct,
                    stock_perf_10d, sector_rank, breadth_score,
                    as_of_date, entry_price, latest_close]
        if any(v is None for v in required):
            return None

        # Derived features (must match phase4_train.py exactly)
        log_vol = float(np.log1p(float(avg_vol_10d)))

        perf_30d_abs = abs(float(stock_perf_30d))
        if perf_30d_abs > 0.1:
            momentum_ratio = float(np.clip(
                float(stock_perf_10d) / float(stock_perf_30d), -3.0, 3.0
            ))
        else:
            momentum_ratio = 0.0

        dist_to_entry_pct = abs(
            (float(entry_price) - float(latest_close)) / float(latest_close) * 100
        )

        # Month from as_of_date (string or datetime)
        if isinstance(as_of_date, str):
            month = int(as_of_date[5:7])
        else:
            month = int(pd.Timestamp(as_of_date).month)

        row_values = [
            log_vol,
            float(atr_pct),
            float(stock_perf_30d),
            float(risk_pct),
            momentum_ratio,
            dist_to_entry_pct,
            float(sector_rank),
            float(month),
            float(stock_perf_10d),
            float(breadth_score),
        ]

        X = np.array(row_values, dtype=float).reshape(1, -1)
        prob = float(model.predict_proba(X)[0][1])
        return prob

    except Exception:
        return None


MOMENTUM_COLORS = {
    "Heating Up":   "#22c55e",
    "Recovering":   "#86efac",
    "Stabilising":  "#fbbf24",
    "Cooling Down": "#fbbf24",
    "Rolling Over": "#fca5a5",
    "Falling":      "#ef4444",
    "—":            "#94a3b8",
}

MOMENTUM_DESC = {
    "Heating Up":   "10d outpacing 30d, both positive — strong upward momentum.",
    "Cooling Down": "10d lagging 30d, both still positive — momentum fading.",
    "Rolling Over": "10d negative while 30d still positive — watch for breakdown.",
    "Recovering":   "10d positive while 30d still negative — early reversal.",
    "Falling":      "Both negative and worsening — confirmed downtrend.",
    "Stabilising":  "Both negative but 10d improving — possible floor.",
}

GUIDANCE = {
    "Bullish":         "Most sectors advancing. Favour longs in leading sectors.",
    "Leaning Bullish": "Breadth improving. Prioritise longs. Wait before shorting.",
    "Ranging":         "Market mixed. Reduce size, wait for directional break.",
    "Leaning Bearish": "Breadth weakening. Protect longs, look for short setups.",
    "Bearish":         "Most sectors declining. Short setups carry highest probability.",
}

PAGES = ["🎯 Market Gates Dashboard", "🧭 Regime", "📊 Market", "🔍 Explorer", "📈 History", "📋 Trade Log", "📉 Analytics", "💡 Setups", "🔎 STM", "🔄 Recovery Bases", "🎯 Setup Perf", "🤖 Backtest", "🗂️ Portfolio", "🏥 Model Health", "🤖 Agent", "💰 Valuation", "📡 Flows", "🏹 Minervini Setup"]


def fmt_date(d) -> str:
    """Format a date-like value as DD/MM/YY, or '—' if null/empty."""
    try:
        if d is None or d == "" or d != d:  # None, empty, or NaN
            return "—"
        return pd.to_datetime(str(d)).strftime("%d/%m/%y")
    except Exception:
        return str(d) if d else "—"


def pct_color(val):
    if val > 0:   return "color:#22c55e; font-weight:bold"
    if val < 0:   return "color:#ef4444; font-weight:bold"
    return "color:#94a3b8"

def style_pct_cols(series):  return [pct_color(v) for v in series]
def style_momentum(series):  return [f"color:{MOMENTUM_COLORS.get(v,'#94a3b8')}; font-weight:bold" for v in series]
def style_direction(series): return ["color:#ef4444;font-weight:bold" if v=="SHORT" else "color:#22c55e;font-weight:bold" for v in series]
def style_outcome(series):
    c = {"Win":"#22c55e","Loss":"#ef4444","Breakeven":"#fbbf24"}
    return [f"color:{c.get(v,'#94a3b8')};font-weight:bold" for v in series]


def gc(val, good_above=0):
    return "#22c55e" if val >= good_above else "#ef4444"


def kpi(label, value, sub, color):
    bg = "#f0fdf4" if color == "#22c55e" else "#fff5f5" if color == "#ef4444" else "#eff6ff"
    return (
        f'<div style="background:{bg}; border:1px solid {color}22; border-top:3px solid {color};'
        f'border-radius:8px; padding:12px 10px; text-align:center; height:88px; '
        f'display:flex; flex-direction:column; justify-content:center; gap:2px;">'
        f'<div style="font-size:0.62rem; color:#64748b; text-transform:uppercase; '
        f'letter-spacing:.07em; white-space:nowrap; overflow:hidden;">{label}</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:{color}; '
        f'line-height:1.15; white-space:nowrap;">{value}</div>'
        f'<div style="font-size:0.60rem; color:#94a3b8; white-space:nowrap; '
        f'overflow:hidden; text-overflow:ellipsis;">{sub}</div>'
        f'</div>'
    )


BLUE = "#3b82f6"


# ── Session state — active page ───────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = PAGES[0]

# ── Session state — refresh tracking ──────────────────────────────────────────
if "last_refresh_time" not in st.session_state:
    st.session_state.last_refresh_time = None
# Source-date cache (populated by get_source_date_cached; 30-min TTL)
if "_ksestocks_source_date" not in st.session_state:
    st.session_state["_ksestocks_source_date"] = None
if "_ksestocks_source_date_fetched_at" not in st.session_state:
    st.session_state["_ksestocks_source_date_fetched_at"] = None

# ── Auto-log today's predictions once per calendar day ───────────────────────
import datetime as _dt, os as _auto_os, subprocess as _auto_sp, sys as _auto_sys
_today_key = f"predictions_logged_{_dt.date.today()}"
if _today_key not in st.session_state:
    st.session_state[_today_key] = False

if not st.session_state[_today_key]:
    try:
        _log_script = _auto_os.path.join(_MODEL_DIR, "part7_prediction_log.py")
        if _auto_os.path.exists(_log_script):
            _auto_sp.run(
                [_auto_sys.executable, _log_script, "log-today"],
                capture_output=True, text=True, timeout=30,
            )
            _auto_sp.run(
                [_auto_sys.executable, _log_script, "update-outcomes"],
                capture_output=True, text=True, timeout=30,
            )
    except Exception:
        pass
    finally:
        st.session_state[_today_key] = True

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<span style='font-size:0.9rem; font-weight:700;'>📈 KIRAN · PSX</span>",
        unsafe_allow_html=True,
    )

    # ── Page selector ──────────────────────────────────────────────────────────────
    if "page" not in st.session_state:
        st.session_state.page = PAGES[0]

    selected_page = st.selectbox(
        "📍 Navigate",
        options=PAGES,
        index=PAGES.index(st.session_state.page),
        key="page_selector"
    )
    if selected_page != st.session_state.page:
        st.session_state.page = selected_page
        st.rerun()

    st.divider()

    # ── Source-date status (cached, 30-min TTL) ────────────────────────────────
    # Shows what trading date ksestocks.com is currently publishing so the user
    # knows whether new data is available before clicking Refresh.
    # _src_fetched_at is None  → never attempted this session (show neutral)
    # _src_fetched_at is set, _src_date_str is None  → tried and FAILED (show red)
    # _src_fetched_at is set, _src_date_str is set   → success (show status)
    _src_date_str  = None
    _src_fetched_at = None
    if HAS_REFRESH_MANAGER:
        try:
            _src_date_str, _src_fetched_at = get_source_date_cached(st.session_state)
        except Exception:
            _src_date_str   = None
            _src_fetched_at = None  # treat as never-tried; Refresh button will surface the error

    latest_stock_date = get_latest_stock_date()

    if _src_date_str:
        if latest_stock_date and latest_stock_date >= _src_date_str:
            st.caption(f"✅ ksestocks: {fmt_date(_src_date_str)} · DB up to date")
        else:
            st.caption(f"📥 ksestocks: {fmt_date(_src_date_str)} · new data available")
    elif _src_fetched_at is not None:
        # We attempted a fetch this session but got no date — site structure changed
        # or the site is unreachable.  Show a red warning so the user knows immediately.
        st.error(
            "⚠️ Could not read source date from ksestocks.com — "
            "scrape aborted. Check the page manually or try again later."
        )
    else:
        # Session just started; haven't tried yet (first render before cache warms)
        st.caption("📡 ksestocks: checking…")

    if st.button("🔄 Refresh Data", type="primary", key="sb_refresh", use_container_width=True):
        with st.spinner("Checking ksestocks.com for new data…"):
            try:
                if not HAS_CMD_UPDATE or cmd_update is None:
                    st.error("Data update not available in this environment.")
                elif HAS_REFRESH_MANAGER:
                    throttle_result = check_refresh_throttle(st.session_state)
                    if throttle_result:
                        msg, msg_type = get_refresh_message(throttle_result)
                        if msg_type == "warning":
                            st.warning(msg)
                        else:
                            st.info(msg)
                    else:
                        result = execute_refresh_with_tracking(cmd_update)
                        msg, msg_type = get_refresh_message(result)

                        if msg_type == "success":
                            st.success(msg)
                        elif msg_type == "info":
                            st.info(msg)
                        elif msg_type == "warning":
                            st.warning(msg)
                        else:
                            st.error(msg)

                        # Invalidate source-date cache so the caption refreshes
                        st.session_state["_ksestocks_source_date"] = None
                        record_refresh_time(st.session_state)
                else:
                    # Fallback (no refresh_manager)
                    cmd_update()
                    st.success("Done!")

                st.cache_data.clear()
                st.rerun()

            except Exception as exc:
                st.error(f"Refresh failed: {str(exc)}")

    if st.button("⚡ Clear Cache", key="sb_clear_cache", use_container_width=True):
        st.cache_data.clear()
        st.success("Cache cleared!")
        st.rerun()

    mn, mx = get_price_date_range()
    latest_index_date = get_latest_index_date()

    st.markdown("---")
    st.markdown("**📊 Data Status**")

    if latest_stock_date:
        st.write(f"**Stocks latest:** {fmt_date(latest_stock_date)}")
    else:
        st.write("**Stocks latest:** No data")

    if latest_index_date:
        st.write(f"**Index latest:** {fmt_date(latest_index_date)}")
    else:
        st.write("**Index latest:** No data")

    # Gap alert: if source shows a newer date than the DB, flag it
    if _src_date_str and latest_stock_date and _src_date_str > latest_stock_date:
        st.warning(
            f"⚠️ DB is missing data for {fmt_date(_src_date_str)} "
            f"(ksestocks source). Click Refresh to update."
        )

    st.caption(
        f"📅 Range: {fmt_date(mn)} → {fmt_date(mx)}  \n"
        f"**{count_prices():,}** prices · **{count_sectors():,}** symbols  \n"
        f"Source: ksestocks.com  |  dates derived from database"
    )


# ── Load data ─────────────────────────────────────────────────────────────────
data = load_data()

if not data or data.get("sector_df", pd.DataFrame()).empty:
    st.warning("No data. Run: `python main.py --init`")
    st.stop()

stock_30d   = data["stock_30d"]
stock_10d   = data["stock_10d"]
sector_df   = data["sector_df"]
breadth     = data["breadth"]
kse100      = data.get("kse100", {})
long_cands  = data["long_candidates"]
short_cands = data["short_candidates"]
raw_setups  = data.get("trade_setups", [])

# Auto-save new system setups once per data-load (idempotent but DB-intensive)
_data_key = id(data)  # changes only when cache invalidates and load_data() re-runs
if st.session_state.get("_last_autosave_key") != _data_key:
    auto_save_setups(raw_setups)
    st.session_state["_last_autosave_key"] = _data_key

# ── KIRAN Header ──────────────────────────────────────────────────────────────
st.markdown(
    """<div style="margin-top:2px; margin-bottom:4px; line-height:1.5; overflow:visible;">
        <span style="font-size:1.85rem; font-weight:800; letter-spacing:-0.5px; display:inline-block;">
            KIRAN
        </span>
        <span style="font-size:0.78rem; font-weight:400; color:#94a3b8; margin-left:10px; vertical-align:middle;">
            PSX Intelligence Platform &nbsp;·&nbsp; Pakistan Stock Exchange
        </span>
    </div>""",
    unsafe_allow_html=True,
)

# ── Market Gates header banner (3-state logic: Bullish/Bearish/Ranging) ───────
try:
    wd_header = load_weinstein_data()
    if not wd_header.get("error"):
        regime = wd_header.get("regime", {})
        signals = wd_header.get("signals", pd.DataFrame())
        breadth_osc = load_breadth_oscillator_data()

        # ── Determine 4 gate states ────────────────────────────────────────
        # Gate 1: KSE > 50MA
        gate1 = kse100.get("above_ma50", False) if kse100.get("available") else False

        # Gate 2: % above 50MA >= 70%
        pct_above_ma = regime.get("pct_above_ma", 0)
        gate2 = pct_above_ma >= 70

        # Gate 3: Histogram >= 0
        hist_val = regime.get("z_histogram")
        gate3 = hist_val is not None and hist_val >= 0

        # Gate 4: Long > Short
        if not breadth_osc.empty:
            latest_long = breadth_osc["Long_Count"].iloc[-1]
            latest_short = breadth_osc["Short_Count"].iloc[-1]
            gate4 = latest_long > latest_short
        else:
            gate4 = None

        # ── Determine 3-state logic ────────────────────────────────────────
        all_gates_pass = gate1 and gate2 and gate3 and (gate4 is True)
        all_gates_fail = (not gate1) and (not gate2) and (not gate3) and (gate4 is False)

        if all_gates_pass:
            cond, color, emoji = "Bullish", "#22c55e", "🟢"
            guidance = "All gates green. Look for LONG trades only."
        elif all_gates_fail:
            cond, color, emoji = "Bearish", "#ef4444", "🔴"
            guidance = "All gates red. Look for SHORT trades only."
        else:
            cond, color, emoji = "Ranging", "#fbbf24", "🟡"
            guidance = "Mixed signals. Sit out — wait for clarity."
    else:
        raise Exception("Weinstein data error")
except Exception:
    # Fallback to breadth-based logic if Weinstein fails
    cond = breadth.get("condition", "Ranging") if breadth else "Ranging"
    color = breadth.get("color", "#fbbf24") if breadth else "#fbbf24"
    emoji = breadth.get("emoji", "🟡") if breadth else "🟡"
    guidance = GUIDANCE.get(cond, "")

# ── KSE-100 50-day MA pill ────────────────────────────────────────────────
if kse100.get("available") and kse100.get("ma50") is not None:
    above   = kse100["above_ma50"]
    kse_c   = kse100["close"]
    kse_m   = kse100["ma50"]
    kse_pct = kse100.get("pct_vs_ma50", 0)
    kse_col = "#22c55e" if above else "#ef4444"
    kse_lbl = "▲ ABOVE" if above else "▼ BELOW"
    kse_p30   = kse100.get("perf_30d")
    p30_col   = "#22c55e" if (kse_p30 is not None and kse_p30 >= 0) else "#ef4444"
    p30_txt   = (f"&nbsp;·&nbsp; 30d <span style='color:{p30_col};font-weight:700;'>"
                 f"{kse_p30:+.1f}%</span>"
                 if kse_p30 is not None else "")
    kse_txt = (f"KSE-100 <b>{kse_c:,.0f}</b> &nbsp;·&nbsp; "
               f"50-MA <b>{kse_m:,.0f}</b> &nbsp;·&nbsp; "
               f"<span style='color:{kse_col};font-weight:700;'>{kse_lbl} 50MA "
               f"({kse_pct:+.1f}%)</span>{p30_txt}")
    kse_note = ("&nbsp;·&nbsp; <b>LONGs active</b>" if above
                else "&nbsp;·&nbsp; <b>LONGs suppressed — index below 50MA</b>")
else:
    kse_txt  = "KSE-100 50MA: <i>data loading…</i>"
    kse_note = ""

st.markdown(
    f"""<div style="background:{color}18; border-left:4px solid {color};
        padding:7px 14px; border-radius:6px; margin-bottom:4px;
        display:flex; align-items:center; gap:16px;">
        <span style="font-size:0.95rem; font-weight:700; color:{color}; white-space:nowrap;">
            {emoji} {cond}
        </span>
        <span style="font-size:0.72rem; color:#64748b;">
            {guidance}
        </span>
    </div>
    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px;
        padding:5px 14px; margin-bottom:8px; font-size:0.72rem; color:#64748b;">
        📈 {kse_txt}{kse_note}
    </div>""",
    unsafe_allow_html=True,
)

cur = st.session_state.page


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 0 — MARKET GATES DASHBOARD (4-GATES OVERVIEW)
# ═══════════════════════════════════════════════════════════════════════════════
if cur == PAGES[0]:  # Market Gates Dashboard
    from weinstein import WeinsteinIndicator, PSX_DEFAULTS, PSX_KNOWN_BOTTOMS, PSX_KNOWN_TOPS

    # ── Load Weinstein data ────────────────────────────────────────────────────────
    with st.spinner("🔄 Loading market gates…"):
        wd = load_weinstein_data()

    if wd.get("error"):
        st.error("Weinstein data error")
    else:
        breadth  = wd["breadth"]
        signals  = wd["signals"]
        regime   = wd["regime"]
        w_params = wd["params"]

        # ── Extract regime values ──────────────────────────────────────────────────
        pct_val     = regime["pct_above_ma"]
        fz_val      = regime["fast_z"]
        sl_val      = regime["signal_line"]
        hist_val    = regime.get("z_histogram")
        zone_color  = regime["zone_color"]

        # ── Get KSE-100 data ──────────────────────────────────────────────────────
        try:
            kse_current = float(signals["index_close"].iloc[-1]) if len(signals) > 0 else 0
            kse_ma50 = float(signals["index_close"].tail(50).mean()) if len(signals) >= 50 else 0
            kse_above_ma = kse_current > kse_ma50
            kse_pct_diff = ((kse_current - kse_ma50) / kse_ma50 * 100) if kse_ma50 > 0 else 0
        except:
            kse_current, kse_ma50, kse_above_ma, kse_pct_diff = 0, 0, False, 0

        # ── Store Gate values in session state for screeners to read ────────────────
        st.session_state.gate1_bullish = kse_above_ma
        st.session_state.gate1_kse = kse_current
        st.session_state.gate2_pct = pct_val
        st.session_state.gate3_histogram = hist_val
        st.session_state.gate4_ready = True

        # ── Render 4-GATES ──────────────────────────────────────────────────────────
        st.markdown(
            """<h1 style="text-align:center; font-size:2.2rem; font-weight:900;
               color:#1e293b; margin-bottom:0.5rem; letter-spacing:-0.02em;">
               📊 MARKET GATES</h1>""",
            unsafe_allow_html=True,
        )
        st.markdown(
            """<p style="text-align:center; font-size:0.9rem; color:#64748b; margin-bottom:2rem;">
               Four pillars of market regime. A layman's instant market read in 2 seconds.</p>""",
            unsafe_allow_html=True,
        )

        # ── GATE 1: MACRO REGIME ───────────────────────────────────────────────────
        g1_col, g2_col = st.columns(2, gap="medium")

        with g1_col:
            gate1_badge = "▲ ABOVE 50MA" if kse_above_ma else "▼ BELOW 50MA"
            gate1_color = "#10b981" if kse_above_ma else "#ef4444"
            gate1_sign = "+" if kse_above_ma else ""
            gate1_html = f"""
            <div style="background:linear-gradient(135deg, {gate1_color}11, {gate1_color}05);
                        border:2px solid {gate1_color}; border-radius:12px; padding:24px; text-align:center;">
                <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; font-weight:600; letter-spacing:0.08em;">Gate 1 — Macro Regime</div>
                <div style="font-size:2.4rem; font-weight:900; color:{gate1_color}; margin:12px 0;">{kse_current:,.0f}</div>
                <div style="font-size:0.9rem; color:{gate1_color}; font-weight:700; margin-bottom:8px;">{gate1_badge} ({gate1_sign}{kse_pct_diff:.1f}%)</div>
                <div style="font-size:0.75rem; color:#94a3b8;">KSE-100 vs 50-MA</div>
            </div>"""
            st.markdown(gate1_html, unsafe_allow_html=True)

        # ── GATE 2: ABSOLUTE PARTICIPATION ────────────────────────────────────────
        with g2_col:
            breadth_color = "#10b981" if pct_val >= 70 else "#f59e0b" if pct_val >= 50 else "#ef4444"
            breadth_strength = "HEALTHY BREADTH" if pct_val >= 70 else "NEUTRAL PARTICIPATION" if pct_val >= 50 else "WEAK BREADTH"
            breadth_html = f"""
            <div style="background:linear-gradient(135deg, {breadth_color}11, {breadth_color}05);
                        border:2px solid {breadth_color}; border-radius:12px; padding:24px; text-align:center;">
                <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; font-weight:600; letter-spacing:0.08em;">Gate 2 — Absolute Participation</div>
                <div style="font-size:2.4rem; font-weight:900; color:{breadth_color}; margin:12px 0;">{pct_val:.1f}%</div>
                <div style="font-size:0.9rem; color:{breadth_color}; font-weight:700; margin-bottom:8px;">📈 {breadth_strength}</div>
                <div style="font-size:0.75rem; color:#94a3b8;">Stocks Above 50-MA</div>
            </div>"""
            st.markdown(breadth_html, unsafe_allow_html=True)

        # ── GATE 3 & 4 (Bottom row) ────────────────────────────────────────────────
        st.markdown("")  # spacer
        g3_col, g4_col = st.columns(2, gap="medium")

        with g3_col:
            # GATE 3: TACTICAL MOMENTUM — Weinstein Histogram + Fast Z vs Signal
            hist_color = "#10b981" if (hist_val is not None and hist_val >= 0) else "#ef4444"

            gate3_html = f"""
            <div style="background:linear-gradient(135deg, {hist_color}08, {hist_color}04); border:2px solid {hist_color}33; border-radius:14px; padding:24px; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
                <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; letter-spacing:0.12em; font-weight:600; margin-bottom:16px;">⚡ Gate 3: Tactical Momentum</div>
                <div style="text-align:center; margin-bottom:20px;">
                    <div style="font-size:2.5rem; font-weight:900; color:{hist_color}; line-height:1;">{hist_val:+.3f}</div>
                    <div style="font-size:0.8rem; color:#64748b; margin-top:4px;">Weinstein Histogram (Fast Z − Signal)</div>
                </div>
            </div>
            """
            st.markdown(gate3_html, unsafe_allow_html=True)

            # Mini Weinstein chart (Fast Z vs Signal Line)
            if HAS_PLOTLY:
                try:
                    tail_mini = min(120, len(signals))
                    sig_mini = signals.tail(tail_mini).copy()

                    fig_gate3 = go.Figure()

                    fig_gate3.add_trace(go.Scatter(
                        x=sig_mini.index, y=sig_mini["fast_z"].round(3),
                        mode="lines", name="Fast Z",
                        line={"color": "#3b82f6", "width": 2.5},
                        hovertemplate="Fast Z: %{y:.2f}<extra></extra>",
                    ))
                    fig_gate3.add_trace(go.Scatter(
                        x=sig_mini.index, y=sig_mini["signal_line"].round(3),
                        mode="lines", name="Signal Line",
                        line={"color": "#f59e0b", "width": 2, "dash": "dot"},
                        hovertemplate="Sig Line: %{y:.2f}<extra></extra>",
                    ))

                    fig_gate3.add_hline(y=0, line_dash="dot", line_color="#94a3b8", line_width=1)
                    fig_gate3.update_layout(
                        height=200, margin={"l": 0, "r": 0, "t": 0, "b": 0},
                        hovermode="x", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"size": 9}},
                        showlegend=True,
                    )
                    fig_gate3.update_xaxes(tickfont={"size": 8}, showticklabels=False)
                    fig_gate3.update_yaxes(tickfont={"size": 8})

                    st.plotly_chart(fig_gate3, use_container_width=True, key="gate3_chart")
                except Exception as e:
                    st.markdown(
                        '<div style="background:#e0e7ff; border:1px solid #818cf8; border-radius:8px; padding:20px; text-align:center; color:#4f46e5;"><p style="margin:0; font-size:0.9rem;">Chart data available • Visualization pending</p></div>',
                        unsafe_allow_html=True
                    )
            else:
                st.info("⚠️ Plotly library not available. Charts disabled. Install: pip install plotly")

        with g4_col:
            # GATE 4: EXECUTION FILTER — ZH Breadth Oscillator (Long vs Short Counts)
            with st.spinner("Loading Gate 4…"):
                breadth_osc = load_breadth_oscillator_data()

            if breadth_osc.empty:
                st.warning("⚠️ ZH breadth oscillator data unavailable")
            else:
                osc_tail = min(120, len(breadth_osc))
                osc_plot = breadth_osc.tail(osc_tail).copy()

                # Determine gate color based on long vs short
                latest_long = osc_plot["Long_Count"].iloc[-1] if not osc_plot.empty else 0
                latest_short = osc_plot["Short_Count"].iloc[-1] if not osc_plot.empty else 0
                osc_color = "#10b981" if latest_long > latest_short else "#ef4444"

                gate4_html = f"""
                <div style="background:linear-gradient(135deg, {osc_color}08, {osc_color}04); border:2px solid {osc_color}33; border-radius:14px; padding:24px; box-shadow:0 4px 20px rgba(0,0,0,0.08); margin-bottom:12px;">
                    <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; letter-spacing:0.12em; font-weight:600; margin-bottom:4px;">✅ Gate 4: Execution Filter</div>
                    <div style="font-size:0.8rem; color:#64748b;">Long vs Short Stock Alignment</div>
                </div>
                """
                st.markdown(gate4_html, unsafe_allow_html=True)

                if HAS_PLOTLY:
                    try:
                        fig_gate4 = go.Figure()

                        fig_gate4.add_trace(go.Scatter(
                            x=osc_plot["Date"], y=osc_plot["Long_Count"],
                            mode="lines", name="Long Count",
                            line={"color": "#10b981", "width": 2.5},
                            hovertemplate="Long: %{y:.0f}<extra></extra>",
                            fill="tozeroy", fillcolor="rgba(16,185,129,0.1)",
                        ))

                        fig_gate4.add_trace(go.Scatter(
                            x=osc_plot["Date"], y=osc_plot["Short_Count"],
                            mode="lines", name="Short Count",
                            line={"color": "#ef4444", "width": 2.5},
                            hovertemplate="Short: %{y:.0f}<extra></extra>",
                            fill="tozeroy", fillcolor="rgba(239,68,68,0.1)",
                        ))

                        fig_gate4.add_hline(y=0, line_dash="dot", line_color="#94a3b8", line_width=1)

                        fig_gate4.update_layout(
                            height=200, margin={"l": 0, "r": 0, "t": 0, "b": 0},
                            hovermode="x", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"size": 9}},
                            showlegend=True,
                        )
                        fig_gate4.update_xaxes(tickfont={"size": 8}, showticklabels=False)
                        fig_gate4.update_yaxes(tickfont={"size": 8})

                        st.plotly_chart(fig_gate4, use_container_width=True, key="gate4_chart")
                    except Exception as e:
                        st.info("Gate 4 chart: Data available but visualization pending")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — MARKET (shifted from PAGES[1])
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[2]:  # Market

    # Bar chart
    if HAS_PLOTLY:
        try:
            chart_df = sector_df.sort_values("avg_perf_pct")
            fig = px.bar(
                chart_df, x="avg_perf_pct", y="sector", orientation="h",
                color="avg_perf_pct",
                color_continuous_scale=["#ef4444", "#fbbf24", "#22c55e"],
                color_continuous_midpoint=0,
                labels={"avg_perf_pct": "30d Perf (%)", "sector": ""},
                text=chart_df["avg_perf_pct"].apply(lambda v: f"{v:+.2f}%"),
            )
            fig.update_traces(textposition="outside", textfont_size=11)
            fig.update_layout(
                height=max(340, len(sector_df) * 24),
                showlegend=False, coloraxis_showscale=False,
                yaxis={"categoryorder": "total ascending", "tickfont": {"size": 11}},
                xaxis={"tickfont": {"size": 10}},
                margin={"l": 4, "r": 70, "t": 8, "b": 8},
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.warning("Market chart visualization failed.")
    else:
        st.info("⚠️ Plotly not available. Install: pip install plotly")

    st.divider()

    # Sector table
    st.markdown("**Sector Rankings**")
    disp = sector_df[[
        "rank", "sector", "avg_perf_pct", "avg_10d_pct",
        "momentum", "stock_count", "best_stock", "best_perf_pct",
        "worst_stock", "worst_perf_pct",
    ]].copy()
    disp.columns = [
        "#", "Sector", "30d %", "10d %",
        "Momentum", "N", "Best", "Best %", "Worst", "Worst %",
    ]
    st.dataframe(
        disp.style
        .apply(style_pct_cols, subset=["30d %", "10d %", "Best %", "Worst %"])
        .apply(style_momentum,  subset=["Momentum"])
        .format({"30d %": "{:.2f}", "10d %": "{:.2f}", "Best %": "{:.2f}", "Worst %": "{:.2f}"}),
        use_container_width=True, hide_index=True,
        height=max(880, (len(disp) + 1) * 38),
    )

    st.markdown(
        """<div style="font-size:0.7rem; color:#64748b; line-height:2;">
        <b>Momentum</b> &nbsp;
        <span style="color:#22c55e">■ Heating Up</span> both +, 10d &gt; 30d &nbsp;
        <span style="color:#fbbf24">■ Cooling Down</span> both +, 10d &lt; 30d &nbsp;
        <span style="color:#fca5a5">■ Rolling Over</span> 10d negative, 30d still + &nbsp;
        <span style="color:#86efac">■ Recovering</span> 10d positive, 30d still − &nbsp;
        <span style="color:#ef4444">■ Falling</span> both −, worsening &nbsp;
        <span style="color:#fbbf24">■ Stabilising</span> both −, improving
        </div>""",
        unsafe_allow_html=True,
    )



# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[4]:  # History
    st.markdown("**Sector Performance History** — equal-weighted index per sector (base = 100)")

    try:
        import plotly.graph_objects as go

        sector_list   = sorted(sector_df["sector"].tolist())
        selected_hist = st.multiselect(
            "Compare sectors",
            options=sector_list,
            default=sector_list[:5],
        )

        if selected_hist:
            fig_hist = go.Figure()
            colors_pool = [
                "#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6",
                "#06b6d4","#f97316","#84cc16","#ec4899","#14b8a6",
            ]
            for i, sec in enumerate(selected_hist):
                syms = tuple(stock_30d.loc[stock_30d["sector"] == sec, "symbol"].tolist())
                if not syms:
                    continue
                h = load_sector_history(syms)
                if h.empty:
                    continue
                lc = colors_pool[i % len(colors_pool)]
                fig_hist.add_trace(go.Scatter(
                    x=h["date"], y=h["index_value"].round(2),
                    mode="lines", name=sec,
                    line={"width": 2, "color": lc},
                    # Show ONLY this sector's value on hover (no cross-trace tooltip)
                    hovertemplate=f"<b>{sec}</b><br>%{{x|%d %b %Y}}: %{{y:.1f}}<extra></extra>",
                ))
            fig_hist.add_hline(y=100, line_dash="dot", line_color="#94a3b8",
                               annotation_text="Base", annotation_position="bottom right")
            fig_hist.update_layout(
                height=480,
                # "closest" → only the hovered trace tooltip is shown
                hovermode="closest",
                xaxis_title="", yaxis_title="Index (Base = 100)",
                legend={"orientation": "h", "y": 1.08, "x": 0, "font": {"size": 11}},
                margin={"l": 4, "r": 4, "t": 32, "b": 8},
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_hist, width='stretch')
        else:
            st.info("Select at least one sector.")
    except ImportError:
        st.warning("Plotly visualization library is not available.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — SETUPS
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[7]:  # Setups
    st.markdown(
        "**Trade Setups** — entry above/below latest close · "
        "SL at recent swing low · max risk 12% · shorts DFC-eligible only"
    )

    if not raw_setups:
        st.info("No qualifying setups today.")
    else:
        today_str    = datetime.now().strftime("%Y-%m-%d")
        short_setups = [s for s in raw_setups if s["direction"] == "SHORT"]
        long_setups  = [s for s in raw_setups if s["direction"] == "LONG"]

        # Build lookup: (symbol, direction, date) → saved DB record
        # Used by each card to find its existing system row ID.
        _all_saved = get_trade_setups()
        _saved_lookup: dict[tuple, dict] = {
            (r["symbol"], r["direction"], r["created_date"][:10]): r
            for r in _all_saved
            if r.get("source", "System") == "System"
        }

        def render_setup_card(s: dict):
            is_short     = s["direction"] == "SHORT"
            card_bg      = "#fff5f5" if is_short else "#f0fdf4"
            border_color = "#ef4444" if is_short else "#22c55e"
            arrow        = "▼" if is_short else "▲"

            q_score  = s.get("quality_score", 0)
            q_checks = s.get("quality_checks", {})
            if isinstance(q_checks, str):
                try:    q_checks = json.loads(q_checks)
                except: q_checks = {}
            max_q = len(q_checks) if q_checks else 4
            stars = "★" * q_score + "☆" * (max_q - q_score)

            checklist_html = "&nbsp;&nbsp;".join(
                f"{'✅' if ok else '❌'} <span style='color:#374151'>{k}</span>"
                for k, ok in q_checks.items()
            ) if q_checks else ""

            # ML confidence badge
            ml_prob = get_ml_confidence(s)
            if ml_prob is not None:
                ml_pct = int(round(ml_prob * 100))
                if ml_pct >= 65:
                    ml_bg, ml_fg = "#dcfce7", "#16a34a"
                elif ml_pct >= 50:
                    ml_bg, ml_fg = "#fef9c3", "#b45309"
                else:
                    ml_bg, ml_fg = "#fee2e2", "#dc2626"
                ml_badge_html = (
                    f"<span style='background:{ml_bg}; color:{ml_fg}; "
                    f"font-size:0.68rem; font-weight:700; padding:2px 7px; "
                    f"border-radius:999px; border:1px solid {ml_fg}44; "
                    f"margin-left:8px; white-space:nowrap;' "
                    f"title='ML win probability'>ML: {ml_pct}%</span>"
                )
            else:
                ml_badge_html = ""

            st.markdown(
                f"""<div style="background:{card_bg}; border:1px solid {border_color}40;
                    border-left:3px solid {border_color}; border-radius:6px;
                    padding:8px 12px; margin-bottom:8px;">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>
                      <b style="color:{border_color}; font-size:0.92rem;">
                        {arrow} {s['direction']} &nbsp; {s['symbol']}
                      </b>
                      <span style="color:#64748b; font-size:0.72rem; margin-left:8px;">
                        {s['sector']} &nbsp;·&nbsp; {s.get('sector_momentum','—')}
                        &nbsp;·&nbsp; Range&nbsp;<b>{s.get('range_width_pct',0):.1f}%</b>/{s.get('range_window','?')}d
                        &nbsp;·&nbsp; 30d&nbsp;<b>{f"{s['stock_perf_30d']:+.1f}%" if s.get('stock_perf_30d') is not None else "—"}</b>
                        {f"&nbsp;·&nbsp; 60d&nbsp;<b>{s['stock_perf_60d']:+.1f}%</b>" if s.get('stock_perf_60d') is not None else ""}
                        &nbsp;·&nbsp; 10d&nbsp;<b>{f"{s['stock_perf_10d']:+.1f}%" if s.get('stock_perf_10d') is not None else "—"}</b>
                        &nbsp;·&nbsp; Breadth&nbsp;<b>{s.get('breadth_score',0):.0f}</b>
                      </span>
                    </span>
                    <span style="display:flex; align-items:center; gap:6px;">
                      {ml_badge_html}
                      <span style="color:#f59e0b; font-size:0.88rem; letter-spacing:1px;"
                            title="Quality {q_score}/{max_q}">
                        {stars} <span style="color:#94a3b8; font-size:0.68rem;">{q_score}/{max_q}</span>
                      </span>
                    </span>
                  </div>
                  <div style="font-size:0.7rem; color:#475569; margin-top:4px;">
                    {checklist_html}
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Entry",  f"{s['entry_price']:.2f}")
            c2.metric("SL",     f"{s['stop_loss']:.2f}", delta=f"−{s['risk_pct']:.1f}%", delta_color="inverse")
            c3.metric("T1R",    f"{s['target_1r']:.2f}")
            c4.metric("T2R",    f"{s['target_2r']:.2f}")
            c5.metric("ATR%",   f"{s['atr_pct']:.2f}%")
            c6.metric("Risk%",  f"{s['risk_pct']:.2f}%")
            st.markdown(
                f"<div style='font-size:0.7rem;color:#64748b;margin-bottom:4px;'>"
                f"Close&nbsp;<b>{s['latest_close']:.2f}</b> &nbsp;·&nbsp; "
                f"Support&nbsp;<b>{s['support_level']:.2f}</b> &nbsp;·&nbsp; "
                f"Resistance&nbsp;<b>{s['resistance_level']:.2f}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # ── "I Took This" inline action ───────────────────────────────
            db_key  = (s["symbol"], s["direction"], s.get("created_date", today_str)[:10])
            db_rec  = _saved_lookup.get(db_key)
            rec_id  = db_rec["id"]    if db_rec else None
            rec_st  = db_rec.get("status", "Pending") if db_rec else "Pending"
            rec_ae  = db_rec.get("actual_entry")      if db_rec else None

            # Status badge
            if rec_st == "Active":
                ae_txt = f"  ·  filled @ **{rec_ae:.2f}**" if rec_ae else ""
                st.markdown(
                    f"<div style='font-size:0.7rem; color:#16a34a; font-weight:600; "
                    f"margin-bottom:6px;'>✅ You are in this trade{ae_txt}</div>",
                    unsafe_allow_html=True,
                )
            elif rec_st == "Closed":
                outcome_col = "#22c55e" if rec_oc == "Win" else (
                    "#ef4444" if rec_oc == "Loss" else "#94a3b8")
                st.markdown(
                    f"<div style='font-size:0.7rem; color:{outcome_col}; font-weight:600; "
                    f"margin-bottom:6px;'>⬛ Closed — {rec_oc}</div>",
                    unsafe_allow_html=True,
                )
            else:
                # Show expander only for Pending / not-yet-taken setups
                card_key = f"took_{s['symbol']}_{s['direction']}"
                with st.expander("✏️ I took this trade", expanded=False):
                    if rec_id is None:
                        st.warning("Setup not yet saved to log — refresh the page and try again.")
                    else:
                        tf1, tf2, tf3 = st.columns([2, 2, 3])
                        tf_entry = tf1.number_input(
                            "My actual fill price",
                            min_value=0.0, step=0.01, format="%.2f",
                            value=float(s["entry_price"]),
                            key=f"{card_key}_entry",
                            help="Leave as KIRAN's level if you haven't filled yet, or enter your actual fill.",
                        )
                        tf_sl = tf2.number_input(
                            "My actual SL",
                            min_value=0.0, step=0.01, format="%.2f",
                            value=float(s["stop_loss"]),
                            key=f"{card_key}_sl",
                            help="Your actual stop-loss placement.",
                        )
                        tf_notes = tf3.text_input(
                            "Notes (optional)",
                            placeholder="e.g. partial fill, adjusted SL…",
                            key=f"{card_key}_notes",
                        )
                        if st.button("✅ Confirm — mark as Active", key=f"{card_key}_confirm",
                                     type="primary"):
                            note_str = tf_notes.strip() or None
                            activate_trade_setup(
                                setup_id     = int(rec_id),
                                actual_entry = float(tf_entry) if tf_entry > 0 else None,
                                notes        = note_str,
                            )
                            st.success(
                                f"{s['symbol']} {s['direction']} marked Active "
                                f"@ {tf_entry:.2f}. Find it in Trade Log to close later."
                            )
                            st.rerun()

            st.markdown("<div style='margin-bottom:10px'></div>", unsafe_allow_html=True)

        if long_setups:
            st.markdown("##### 🟢 Long Setups")
            for s in long_setups:
                render_setup_card(s)

        if short_setups:
            st.markdown("##### 🔴 Short Setups")
            for s in short_setups:
                render_setup_card(s)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — TRADE LOG
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[5]:  # Trade Log
    st.markdown("**Trade Log — Your Real Trades**")
    st.caption(
        "Your personal trading journal — discretionary trades from ASSET ALLOCATION.XLSX. "
        "Synced automatically each day. System/paper screener records are tracked separately and do not appear here."
    )

    all_saved = get_trade_setups()

    # ── Filter to Actual trades only ──────────────────────────────────────────
    actual_trades = [t for t in all_saved if t.get("source") == "Actual"] if all_saved else []

    # ── Log table ─────────────────────────────────────────────────────────────
    if not actual_trades:
        st.info("No actual trades yet. Trades sync automatically from your Excel journal each day, or log one below.")
    else:
        log_df = pd.DataFrame(actual_trades)

        flt1, flt2 = st.columns([2, 2])
        sf       = flt1.selectbox("Status", ["All", "Active", "Closed", "Pending"], key="log_sf")
        sym_srch = flt2.text_input("Symbol search", placeholder="e.g. BAFL", key="log_sym").strip().upper()

        if sf != "All":
            log_df = log_df[log_df["status"] == sf]
        if sym_srch:
            log_df = log_df[log_df["symbol"].str.upper().str.contains(sym_srch, na=False)]

        # Ensure columns exist
        for col in ["exit_date", "actual_exit", "actual_pl_pct", "holding_days", "actual_entry"]:
            if col not in log_df.columns:
                log_df[col] = None

        display_log = log_df[[
            "id", "created_date", "exit_date", "direction", "symbol",
            "entry_price", "stop_loss", "actual_exit",
            "risk_pct", "actual_pl_pct", "holding_days",
            "status", "outcome", "notes",
        ]].copy()
        display_log.columns = [
            "ID", "Entry Date", "Exit Date", "Dir", "Symbol",
            "Entry", "SL", "Exit",
            "Risk%", "P&L%", "Days",
            "Status", "Outcome", "Notes",
        ]
        display_log["Entry Date"] = display_log["Entry Date"].apply(fmt_date)
        display_log["Exit Date"]  = display_log["Exit Date"].apply(fmt_date)

        fmt_map = {
            "Entry": "{:.2f}", "SL": "{:.2f}", "Exit": "{:.2f}",
            "Risk%": "{:.2f}", "P&L%": "{:.2f}", "Days": "{:.0f}",
        }
        st.dataframe(
            display_log.style
            .apply(style_direction, subset=["Dir"])
            .apply(style_outcome,   subset=["Outcome"])
            .apply(style_pct_cols,  subset=["P&L%"])
            .format(fmt_map, na_rep="—"),
            use_container_width=True, hide_index=True,
            height=min(900, max(200, (len(display_log) + 1) * 38)),
        )

    # ── Partial close ─────────────────────────────────────────────────────────
    if actual_trades:
        partial_trades = [t for t in actual_trades if t.get("status") in ("Active", "Pending")]
        if partial_trades:
            st.divider()
            st.markdown("**Partially close a position**")
            st.caption("Close part of an Actual trade and keep the rest open. Creates a partial exit record.")

            partial_opts = {
                f"#{t['id']} · {t['symbol']} {t['direction']} @ {t['entry_price']:.2f}"
                f"  (entry {fmt_date(t['created_date'])})": t
                for t in partial_trades
            }
            partial_label = st.selectbox(
                "Position", list(partial_opts.keys()), key="partial_sel",
                label_visibility="collapsed"
            )
            partial_trade = partial_opts[partial_label]

            pc1, pc2, pc3, pc4, pc5 = st.columns([1.2, 1.2, 1.2, 2, 1])
            pc_px     = pc1.number_input("Exit Price", min_value=0.0, step=0.01,
                                         format="%.2f", key="pc_px", label_visibility="collapsed")
            pc_dt     = pc2.date_input("Exit Date", value=datetime.now().date(),
                                       key="pc_dt", label_visibility="collapsed")
            pc_pct    = pc3.number_input("% Closed", min_value=0.1, max_value=99.9, value=50.0,
                                         step=0.1, format="%.1f", key="pc_pct", label_visibility="collapsed")
            pc_notes  = pc4.text_input("Notes", placeholder="e.g. took 50%, holding 50%", key="pc_notes",
                                       label_visibility="collapsed")
            pc1.caption("Exit Price"); pc2.caption("Exit Date"); pc3.caption("% Closed"); pc4.caption("Notes")

            with pc5:
                st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
                if st.button("📊 Partial Close", key="btn_partial", type="primary"):
                    if pc_px <= 0:
                        st.error("Enter a valid exit price.")
                    else:
                        entry = float(partial_trade["entry_price"])
                        dirn  = partial_trade["direction"]
                        if entry > 0:
                            pl = (pc_px - entry) / entry * 100 if dirn == "LONG" else (entry - pc_px) / entry * 100

                        # Create new position for the remaining amount
                        remainder_notes = f"Partial close recorded. {pc_pct:.1f}% closed at {pc_px:.2f} on {pc_dt.isoformat()}. Remainder open. {pc_notes.strip()}"

                        # Close the original position marked as partial
                        close_trade_setup(
                            setup_id               = int(partial_trade["id"]),
                            exit_price             = float(pc_px),
                            exit_date              = pc_dt.isoformat(),
                            status                 = "Closed",
                            outcome                = "Breakeven",
                            notes                  = f"Partial close: {pc_pct:.1f}% @ {pc_px:.2f}. {pc_notes.strip()}",
                            actual_pl_pkr_override = None,
                        )
                        st.success(f"#{partial_trade['id']} · {pc_pct:.1f}% closed at {pc_px:.2f}  ·  P&L {pl:+.2f}%")
                        st.rerun()

    # ── Close an open position ────────────────────────────────────────────────
    if actual_trades:
        active_trades = [t for t in actual_trades if t.get("status") in ("Active", "Pending")]
        if active_trades:
            st.divider()
            st.markdown("**Close a position**")
            st.caption("Select an open trade, enter exit price and date to close it and record P&L.")

            active_opts = {
                f"#{t['id']} · {t['symbol']} {t['direction']} @ {t['entry_price']:.2f}"
                f"  (entry {fmt_date(t['created_date'])})": t
                for t in active_trades
            }
            chosen_label = st.selectbox(
                "Open trade", list(active_opts.keys()), key="close_sel",
                label_visibility="collapsed"
            )
            chosen_trade = active_opts[chosen_label]

            cl1, cl2, cl3, cl4, cl5, cl6 = st.columns([1.5, 1.5, 1.5, 2, 2, 1])
            cl1.caption("Exit Price")
            cl2.caption("Exit Date")
            cl3.caption("P&L (PKR)")
            cl4.caption("Result")
            cl5.caption("Notes")

            exit_px   = cl1.number_input("Exit Price", min_value=0.0, step=0.01,
                                          format="%.2f", key="cl_px", label_visibility="collapsed")
            exit_dt   = cl2.date_input("Exit Date", value=datetime.now().date(),
                                       key="cl_dt", label_visibility="collapsed")
            cl_pkr    = cl3.number_input("P&L PKR", step=100.0, format="%.0f",
                                          key="cl_pkr", label_visibility="collapsed",
                                          help="Your actual profit/loss in PKR (e.g. −15000). Leave 0 to auto-calculate.")
            cl_result = cl4.selectbox("Result", ["Win", "Loss", "Breakeven", "Cancelled"],
                                      key="cl_result", label_visibility="collapsed")
            cl_notes  = cl5.text_input("Notes", placeholder="e.g. trailed stop", key="cl_notes",
                                       label_visibility="collapsed")

            with cl6:
                st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
                if st.button("✅ Close", key="btn_close", type="primary"):
                    if exit_px <= 0:
                        st.error("Enter a valid exit price.")
                    else:
                        pkr_override = float(cl_pkr) if cl_pkr != 0 else None
                        close_trade_setup(
                            setup_id               = int(chosen_trade["id"]),
                            exit_price             = float(exit_px),
                            exit_date              = exit_dt.isoformat(),
                            status                 = "Closed",
                            outcome                = cl_result,
                            notes                  = cl_notes.strip() or None,
                            actual_pl_pkr_override = pkr_override,
                        )
                        entry = float(chosen_trade["entry_price"])
                        dirn  = chosen_trade["direction"]
                        if entry > 0:
                            pl = (exit_px - entry) / entry * 100 if dirn == "LONG" else (entry - exit_px) / entry * 100
                            pkr_str = f"  ·  PKR {float(cl_pkr):+,.0f}" if cl_pkr != 0 else ""
                            st.success(f"#{chosen_trade['id']} closed  ·  P&L {pl:+.2f}%{pkr_str}")
                        else:
                            st.success(f"#{chosen_trade['id']} closed.")
                        st.rerun()




# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[3]:  # Explorer
    ex_left, ex_right = st.columns([1, 2])

    with ex_left:
        st.markdown("**Stock Explorer**")
        all_sectors_list = ["All sectors"] + sorted(sector_df["sector"].tolist())
        selected_sector  = st.selectbox("Sector", all_sectors_list, key="exp_sector", label_visibility="collapsed")

        filtered = (
            stock_30d if selected_sector == "All sectors"
            else stock_30d[stock_30d["sector"] == selected_sector]
        )

        sc1, sc2 = st.columns([2, 1])
        sort_col = sc1.selectbox("Sort", ["perf_pct", "symbol", "latest_close"], key="exp_sort", label_visibility="collapsed")
        sort_asc = sc2.checkbox("Asc", value=(sort_col == "symbol"), key="exp_asc")

        total = len(filtered)
        top_n = st.slider("Show top N", 1, max(1, total), min(50, total), key="exp_n") if total > 1 else total

        disp_stocks = (
            filtered.sort_values(sort_col, ascending=sort_asc)
            .head(top_n)[["symbol","sector","perf_pct","latest_close","base_close","latest_date","base_date"]]
            .copy()
        )
        disp_stocks.columns = ["Symbol","Sector","30d%","Close","Base","From","To"]

        st.dataframe(
            disp_stocks.style
            .apply(style_pct_cols, subset=["30d%"])
            .format({"30d%":"{:.2f}","Close":"{:.2f}","Base":"{:.2f}"}),
            width='stretch', hide_index=True, height=480,
        )

    with ex_right:
        st.markdown("**Price History**")
        from database import get_prices_df

        all_symbols   = sorted(stock_30d["symbol"].tolist())
        chosen_symbol = st.selectbox("Symbol", all_symbols, key="exp_sym", label_visibility="collapsed")

        if chosen_symbol:
            row_30 = stock_30d[stock_30d["symbol"] == chosen_symbol]
            row_10 = stock_10d[stock_10d["symbol"] == chosen_symbol]

            if not row_30.empty and not row_10.empty:
                p30 = row_30.iloc[0]["perf_pct"]
                p10 = row_10.iloc[0]["perf_pct"]

                if   p30 >= 0 and p10 >= 0: mom = "Heating Up"   if p10 > p30 else "Cooling Down"
                elif p30 < 0 and p10 >= 0:  mom = "Recovering"
                elif p30 >= 0 and p10 < 0:  mom = "Rolling Over"
                else:                        mom = "Falling"      if p10 < p30 else "Stabilising"

                mc = MOMENTUM_COLORS.get(mom, "#94a3b8")
                st.markdown(
                    f"""<div style="background:{mc}18; border-left:3px solid {mc};
                        padding:6px 12px; border-radius:4px; margin-bottom:8px;
                        display:flex; align-items:center; gap:12px;">
                        <b style="color:{mc}; font-size:0.85rem;">{mom}</b>
                        <span style="font-size:0.72rem; color:#64748b;">
                            {MOMENTUM_DESC.get(mom,'')}
                            &nbsp;·&nbsp; 30d <b>{p30:+.2f}%</b>
                            &nbsp;·&nbsp; 10d <b>{p10:+.2f}%</b>
                        </span>
                    </div>""",
                    unsafe_allow_html=True,
                )

            hist = get_prices_df(chosen_symbol, limit=90)
            if hist:
                h_df = pd.DataFrame(hist).sort_values("date")
                h_df["date"] = pd.to_datetime(h_df["date"])
                try:
                    import plotly.graph_objects as go
                    sec_name = stock_30d.loc[stock_30d["symbol"] == chosen_symbol, "sector"].values
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(
                        x=h_df["date"], y=h_df["close"],
                        mode="lines+markers", name=chosen_symbol,
                        line={"color": "#3b82f6", "width": 2},
                        marker={"size": 3},
                    ))
                    fig2.update_layout(
                        title={"text": f"{chosen_symbol} — {sec_name[0] if len(sec_name) else ''}", "font": {"size": 13}},
                        xaxis_title="", yaxis_title="Close (PKR)",
                        height=400,
                        margin={"l": 4, "r": 4, "t": 36, "b": 8},
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        xaxis={"gridcolor": "#f1f5f9"},
                        yaxis={"gridcolor": "#f1f5f9"},
                    )
                    st.plotly_chart(fig2, width='stretch')
                except ImportError:
                    st.dataframe(h_df, width='stretch', hide_index=True)
            else:
                st.info(f"No price data for {chosen_symbol}.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[6]:  # Analytics
    from config import BENCHMARK, SUPPORT_REVERSAL_STATS

    # Ensure portfolio tables exist
    init_db()

    # ── Pull all closed trades (System-taken + Actual) ────────────────────────
    all_trades = get_trade_setups()
    adf = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    closed = pd.DataFrame()
    if not adf.empty:
        if "source" not in adf.columns:
            adf["source"] = "System"
        adf["source"] = adf["source"].fillna("System")

        # Calculate execution type: Actual if source="Actual", Paper&Actual if has actual_entry, else Paper
        adf["execution_type"] = adf.apply(
            lambda row: "Actual" if row.get("source") == "Actual"
            else "Paper & Actual" if row.get("actual_entry") is not None and row.get("actual_entry") > 0
            else "Paper",
            axis=1
        )

        # Include only Actual or Paper & Actual trades with resolved outcomes
        closed = adf[
            adf["outcome"].isin(["Win", "Loss", "Breakeven"]) &
            adf["execution_type"].isin(["Actual", "Paper & Actual"])
        ].copy()
        for col in ["actual_pl_pkr", "actual_pl_pct", "actual_rr", "holding_days", "exit_date"]:
            if col not in closed.columns:
                closed[col] = None

        # Backfill actual_pl_pkr for trades closed before the fix (where it is NULL).
        # PKR P&L per share = pl_pct/100 * effective_entry (same formula used in close_trade_setup).
        missing_pkr = closed["actual_pl_pkr"].isna() & closed["actual_pl_pct"].notna()
        if missing_pkr.any():
            ref_entry = closed["actual_entry"].where(
                closed["actual_entry"].notna() & (closed["actual_entry"] > 0),
                closed["entry_price"]
            )
            closed.loc[missing_pkr, "actual_pl_pkr"] = (
                closed.loc[missing_pkr, "actual_pl_pct"] / 100
                * ref_entry[missing_pkr]
            ).round(2)

    if closed.empty:
        st.info("No closed actual trades yet. Trades sync from your Excel journal daily.")
        st.stop()

    # ── Core calculations ──────────────────────────────────────────────────────
    wins   = closed[closed["outcome"] == "Win"]
    losses = closed[closed["outcome"] == "Loss"]
    n_total   = len(closed)
    n_wins    = len(wins)
    n_losses  = len(losses)
    win_rate  = n_wins  / n_total if n_total else 0
    loss_rate = n_losses / n_total if n_total else 0

    gross_win  = wins["actual_pl_pkr"].fillna(0).sum()
    gross_loss = losses["actual_pl_pkr"].fillna(0).sum()
    # Guard: gross_loss should be negative (losses); if 0 or positive use inf
    if gross_loss < 0:
        profit_factor = gross_win / abs(gross_loss)
    elif gross_win > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    total_pl_pkr   = closed["actual_pl_pkr"].fillna(0).sum()
    avg_win_pct    = wins["actual_pl_pct"].fillna(0).mean()   if n_wins   else 0
    avg_loss_pct   = losses["actual_pl_pct"].fillna(0).mean() if n_losses else 0
    expectancy_pct = (avg_win_pct * win_rate) + (avg_loss_pct * loss_rate)
    ev_per_trade   = total_pl_pkr / n_total if n_total else 0

    total_rr      = closed["actual_rr"].fillna(0).sum()
    avg_rr        = closed["actual_rr"].fillna(0).mean()
    avg_hold_win  = wins["holding_days"].fillna(0).mean()   if n_wins   else 0
    avg_hold_loss = losses["holding_days"].fillna(0).mean() if n_losses else 0

    # ── Row 1 — 4 headline KPIs ───────────────────────────────────────────────
    st.markdown("### Performance Summary")
    st.caption(f"{n_total} closed trades  ·  {n_wins} wins  ·  {n_losses} losses  "
               f"·  Oct 2024 – present")
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    r1 = st.columns(4)
    r1[0].markdown(kpi("Win Rate",      f"{win_rate*100:.1f}%",
                       f"{n_wins}W / {n_losses}L",         gc(win_rate - 0.5)), unsafe_allow_html=True)
    r1[1].markdown(kpi("Profit Factor", f"{profit_factor:.2f}x",
                       "gross wins ÷ gross losses",         gc(profit_factor - 1)), unsafe_allow_html=True)
    r1[2].markdown(kpi("Total P&L",     f"PKR {total_pl_pkr:+,.0f}",
                       "net realised",                      gc(total_pl_pkr)), unsafe_allow_html=True)
    r1[3].markdown(kpi("Expectancy",    f"{expectancy_pct:+.2f}%",
                       "avg return per trade",              gc(expectancy_pct)), unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Row 2 — 4 secondary KPIs ─────────────────────────────────────────────
    r2 = st.columns(4)
    r2[0].markdown(kpi("EV / Trade",   f"PKR {ev_per_trade:+,.0f}",
                       "expected value per trade",          gc(ev_per_trade)), unsafe_allow_html=True)
    r2[1].markdown(kpi("Total R",      f"{total_rr:+.1f} R",
                       f"avg {avg_rr:.2f} R per trade",    BLUE), unsafe_allow_html=True)
    r2[2].markdown(kpi("Avg Win %",    f"{avg_win_pct:+.2f}%",
                       f"vs loss {avg_loss_pct:.2f}%",     "#22c55e"), unsafe_allow_html=True)
    r2[3].markdown(kpi("Avg Hold",     f"{avg_hold_win:.0f}d W · {avg_hold_loss:.0f}d L",
                       "days held: wins · losses",          BLUE), unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── BENCHMARK COMPARISON ──────────────────────────────────────────────────
    st.markdown("### 📊 vs Benchmark")
    st.caption(
        f"Compare your current performance (from {n_total} closed trades) "
        f"to your benchmark ({BENCHMARK['sample_size']}) and Support Reversal pattern ({SUPPORT_REVERSAL_STATS['sample_size']})"
    )

    comp_cols = st.columns(3)

    # Build comparison dataframe
    metrics_list = [
        ("Win Rate %", f"{win_rate*100:.1f}%", f"{BENCHMARK['win_rate_pct']:.1f}%", f"{SUPPORT_REVERSAL_STATS['win_rate_pct']:.1f}%"),
        ("Profit Factor", f"{profit_factor:.2f}x", f"{BENCHMARK['profit_factor']:.2f}x", f"{SUPPORT_REVERSAL_STATS['profit_factor']:.2f}x"),
        ("Risk:Reward", f"{avg_rr:.2f}x", f"{BENCHMARK['risk_reward']:.2f}x", f"{SUPPORT_REVERSAL_STATS['risk_reward']:.2f}x"),
        ("Expectancy %", f"{expectancy_pct:+.2f}%", f"{BENCHMARK['expectancy_pct']:+.2f}%", f"{SUPPORT_REVERSAL_STATS['expectancy_pct']:+.2f}%"),
    ]

    comp_df = pd.DataFrame(
        metrics_list,
        columns=["Metric", "Your Current", f"{BENCHMARK['name']}", f"{SUPPORT_REVERSAL_STATS['name']}"]
    )

    with comp_cols[0]:
        st.markdown("**Current Performance**")
        st.metric("Win Rate", f"{win_rate*100:.1f}%", delta=f"{win_rate*100 - BENCHMARK['win_rate_pct']:.1f}pp vs benchmark")
        st.metric("Expectancy %", f"{expectancy_pct:+.2f}%", delta=f"{expectancy_pct - BENCHMARK['expectancy_pct']:+.2f}pp vs benchmark")

    with comp_cols[1]:
        st.markdown(f"**{BENCHMARK['name']}**")
        st.metric("Win Rate", f"{BENCHMARK['win_rate_pct']:.1f}%", label_visibility="collapsed")
        st.metric("Expectancy %", f"{BENCHMARK['expectancy_pct']:+.2f}%", label_visibility="collapsed")

    with comp_cols[2]:
        st.markdown(f"**{SUPPORT_REVERSAL_STATS['name']}**")
        st.metric("Win Rate", f"{SUPPORT_REVERSAL_STATS['win_rate_pct']:.1f}%", label_visibility="collapsed")
        st.metric("Expectancy %", f"{SUPPORT_REVERSAL_STATS['expectancy_pct']:+.2f}%", label_visibility="collapsed")

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.dataframe(comp_df, use_container_width=True, hide_index=True)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Long vs Short side panels ─────────────────────────────────────────────
    st.markdown("**Long vs Short**")
    l_col, s_col, _ = st.columns([5, 5, 2])

    for col, dirn, label in [(l_col, "LONG", "🟢 Long"), (s_col, "SHORT", "🔴 Short")]:
        d  = closed[closed["direction"] == dirn]
        dw = d[d["outcome"] == "Win"]
        dl = d[d["outcome"] == "Loss"]
        nd = len(d)
        wr = len(dw) / nd * 100 if nd else 0
        pl = d["actual_pl_pkr"].fillna(0).sum()
        gw = dw["actual_pl_pkr"].fillna(0).sum()
        gl = dl["actual_pl_pkr"].fillna(0).sum()
        pf = gw / abs(gl) if gl < 0 else float("inf")
        ex = d["actual_pl_pct"].fillna(0).mean()
        c  = "#22c55e" if dirn == "LONG" else "#ef4444"
        col.markdown(
            f'<div style="border:1px solid {c}25; border-left:4px solid {c}; '
            f'border-radius:8px; padding:11px 14px;">'
            f'<div style="font-weight:700; font-size:0.82rem; color:{c}; margin-bottom:7px;">'
            f'{label} &nbsp;·&nbsp; {nd} trades</div>'
            f'<table style="width:100%; font-size:0.75rem; border-collapse:collapse;">'
            f'<tr><td style="color:#64748b;padding:2px 0;">Win Rate</td>'
            f'<td style="text-align:right;font-weight:700;">{wr:.1f}% &nbsp;({len(dw)}W/{len(dl)}L)</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Profit Factor</td>'
            f'<td style="text-align:right;font-weight:700;">{pf:.2f}x</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Net P&L</td>'
            f'<td style="text-align:right;font-weight:700;color:{"#22c55e" if pl>=0 else "#ef4444"};">'
            f'PKR {pl:+,.0f}</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Avg P&L %</td>'
            f'<td style="text-align:right;font-weight:700;color:{"#22c55e" if ex>=0 else "#ef4444"};">'
            f'{ex:+.2f}%</td></tr>'
            f'</table></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Monthly P&L pivot table — rows: Year, cols: Jan–Dec ──────────────────
    st.markdown("**Monthly P&L  (PKR)**")

    ref_date = pd.to_datetime(
        closed["exit_date"].fillna(closed["created_date"]), errors="coerce"
    )
    closed = closed.copy()
    closed["_yr"]  = ref_date.dt.year.astype("Int64")
    closed["_mo"]  = ref_date.dt.month.astype("Int64")

    # Drop rows where date parsing failed (no valid year/month)
    pivot_df = closed.dropna(subset=["_yr", "_mo"]).copy()

    MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]

    if pivot_df.empty:
        st.info("No dated closed trades to build monthly P&L table.")
        pivot = pd.DataFrame()
    else:
        pivot = (
            pivot_df.groupby(["_yr","_mo"])["actual_pl_pkr"]
            .sum()
            .reset_index()
            .pivot(index="_yr", columns="_mo", values="actual_pl_pkr")
        )
    if not pivot.empty:
        pivot.columns = [MONTH_NAMES[m-1] for m in pivot.columns]
        pivot.index.name = "Year"

        all_months = MONTH_NAMES
        for m in all_months:
            if m not in pivot.columns:
                pivot[m] = float("nan")
        pivot = pivot[all_months]
        pivot["Total"] = pivot.sum(axis=1, skipna=True, min_count=1)

    # ── Colour-coded HTML table ───────────────────────────────────────────────
    if pivot.empty:
        st.info("No P&L data with valid dates to display.")
    else:
        def cell(v, bold=False):
            if pd.isna(v):
                return '<td style="text-align:right;padding:4px 8px;color:#94a3b8;font-size:0.72rem;">—</td>'
            color  = "#22c55e" if v > 0 else ("#ef4444" if v < 0 else "#94a3b8")
            weight = "800" if bold else "600"
            return (f'<td style="text-align:right;padding:4px 8px;font-size:0.72rem;'
                    f'color:{color};font-weight:{weight};">{v:+,.0f}</td>')

        hdr_cells = "".join(
            f'<th style="text-align:right;padding:4px 8px;font-size:0.70rem;'
            f'color:#64748b;font-weight:600;">{m}</th>'
            for m in all_months + ["Total"]
        )
        header = (
            f'<tr><th style="text-align:left;padding:4px 8px;font-size:0.70rem;'
            f'color:#64748b;font-weight:600;">Year</th>{hdr_cells}</tr>'
        )

        body_rows = []
        for yr in sorted(pivot.index):
            yr_cell = (f'<td style="text-align:left;padding:4px 8px;font-size:0.72rem;'
                       f'font-weight:700;color:#1e293b;">{yr}</td>')
            month_cells = "".join(cell(pivot.loc[yr, m]) for m in all_months)
            total_cell  = cell(pivot.loc[yr, "Total"], bold=True)
            body_rows.append(f"<tr>{yr_cell}{month_cells}{total_cell}</tr>")

        # Grand total row
        grand_cells = "".join(
            cell(pivot[m].sum(skipna=True, min_count=1)) for m in all_months
        )
        grand_total = cell(pivot["Total"].sum(skipna=True, min_count=1), bold=True)
        grand_row = (
            f'<tr style="border-top:1px solid #e2e8f0;">'
            f'<td style="text-align:left;padding:4px 8px;font-size:0.72rem;font-weight:700;'
            f'color:#1e293b;">Total</td>{grand_cells}{grand_total}</tr>'
        )

        table_html = (
            '<div style="overflow-x:auto;">'
            '<table style="width:100%;border-collapse:collapse;'
            'border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">'
            f'<thead style="background:#f8fafc;">{header}</thead>'
            f'<tbody>{"".join(body_rows)}{grand_row}</tbody>'
            '</table></div>'
        )
        st.markdown(table_html, unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Portfolio MWR vs KSE-100 Return ────────────────────────────────────────
    st.markdown("**Money-Weighted Return vs KSE-100**")

    try:
        pf_df = load_portfolio_pnl()
        kse_df = load_kse100_performance()

        if not pf_df.empty and not kse_df.empty:
            pf_df = pf_df.sort_values("date")
            kse_df = kse_df.sort_values("date")

            # FIXED: Start date should be first cash flow (Oct 1, 2024), not first portfolio value (Dec 27, 2024)
            measurement_start_date = pd.to_datetime("2024-10-01")  # First investment date
            pf_end_date = pf_df.iloc[-1]["date"]
            final_pf_value = pf_df.iloc[-1]["portfolio_value"]

            # Find KSE-100 values on actual measurement dates (robust slice)
            _kse_start_slice = kse_df[kse_df["date"] <= measurement_start_date]
            _kse_end_slice   = kse_df[kse_df["date"] <= pf_end_date]
            kse_on_start = _kse_start_slice.iloc[-1]["kse100"] if not _kse_start_slice.empty else (kse_df.iloc[0]["kse100"] if not kse_df.empty else 0)
            kse_on_end   = _kse_end_slice.iloc[-1]["kse100"]   if not _kse_end_slice.empty   else (kse_df.iloc[-1]["kse100"] if not kse_df.empty else 0)

            # Calculate KSE-100 simple return
            kse_return = ((kse_on_end - kse_on_start) / kse_on_start) * 100 if kse_on_start > 0 else 0

            # Build cash flows for IRR - use fixed known values
            cash_flows = [
                -498767,      # Oct 1, 2024 - Initial investment
                -450000,      # Dec 13, 2024 - Deposit
                25226,        # Apr 8, 2025 - Dividend
                10200,        # Apr 9, 2025 - Dividend
                10000,        # Jun 11, 2025 - Withdrawal
                55000,        # Jul 29, 2025 - Withdrawal
                200000,       # Nov 13, 2025 - Withdrawal
                -1000000,     # Mar 31, 2026 - Deposit
                final_pf_value,  # Apr 30, 2026 - Final portfolio value
            ]

            dates_cf = [
                pd.to_datetime("2024-10-01"),
                pd.to_datetime("2024-12-13"),
                pd.to_datetime("2025-04-08"),
                pd.to_datetime("2025-04-09"),
                pd.to_datetime("2025-06-11"),
                pd.to_datetime("2025-07-29"),
                pd.to_datetime("2025-11-13"),
                pd.to_datetime("2026-03-31"),
                pf_end_date,
            ]

            # Calculate IRR
            portfolio_mwr = calculate_irr(cash_flows, dates_cf) * 100

            # Display metrics side by side
            col1, col2, col3 = st.columns([1.5, 1.5, 1])

            with col1:
                st.metric(
                    "Portfolio MWR",
                    f"{portfolio_mwr:+.2f}%",
                    delta=f"{measurement_start_date.strftime('%d %b %Y')} → {pf_end_date.strftime('%d %b %Y')}",
                    delta_color="off"
                )

            with col2:
                st.metric(
                    "KSE-100 Return",
                    f"{kse_return:+.2f}%",
                    delta=f"{measurement_start_date.strftime('%d %b %Y')} → {pf_end_date.strftime('%d %b %Y')}",
                    delta_color="off"
                )

            with col3:
                outperformance = portfolio_mwr - kse_return
                st.metric(
                    "Outperformance",
                    f"{outperformance:+.2f}%",
                    delta="MWR vs Index",
                    delta_color="off"
                )

            st.caption(
                "📊 **MWR** = Internal Rate of Return accounting for all deposits, withdrawals & dividends. "
                "**KSE-100** = Simple index return. Both measured over same period from your portfolio start date."
            )

        else:
            st.info("Portfolio or KSE-100 data not available yet.")
    except Exception as e:
        st.warning(f"Could not calculate portfolio MWR vs KSE-100: {e}")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Portfolio Value Growth Chart ───────────────────────────────────────────
    st.markdown("**Portfolio Growth  (PKR)**")

    try:
        pf_df = load_portfolio_pnl()
        if not pf_df.empty:
            pf_df = pf_df.sort_values("date").reset_index(drop=True)

            fig_pf = go.Figure()

            # Simple portfolio value line
            fig_pf.add_trace(go.Scatter(
                x=pf_df["date"],
                y=pf_df["portfolio_value"],
                mode="lines+markers",
                name="Portfolio Value",
                line={"color": "#3b82f6", "width": 2.5},
                marker={"size": 5},
                fill="tozeroy",
                fillcolor="rgba(59, 130, 246, 0.1)",
                hovertemplate="<b>%{x|%d %b %Y}</b><br>PKR %{y:,.0f}<extra></extra>",
            ))

            fig_pf.update_layout(
                height=280,
                margin={"l": 4, "r": 4, "t": 8, "b": 8},
                xaxis={"tickfont": {"size": 9}},
                yaxis={"tickfont": {"size": 9}, "tickformat": ",.0f"},
                hovermode="x unified",
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_pf, width='stretch')
        else:
            st.info("Portfolio data not available yet.")
    except Exception as e:
        st.warning(f"Could not generate portfolio growth chart: {e}")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Portfolio Management Section ───────────────────────────────────────────
    st.markdown("### 📊 Portfolio Management")
    st.caption("Update portfolio transactions and values at the end of each month")

    with st.expander("➕ Add Portfolio Entry", expanded=False):
        mgmt_tab1, mgmt_tab2 = st.tabs(["Transaction", "Portfolio Value"])

        with mgmt_tab1:
            st.markdown("**Add Deposit, Withdrawal, or Dividend**")
            col1, col2, col3 = st.columns(3)
            with col1:
                tx_date = st.date_input("Date", key="tx_date")
            with col2:
                tx_type = st.selectbox("Type", ["deposit", "withdrawal", "dividend"], key="tx_type")
            with col3:
                tx_amount = st.number_input("Amount (PKR)", min_value=0.0, step=1000.0, key="tx_amount")

            tx_notes = st.text_input("Notes (optional)", key="tx_notes")

            if st.button("✅ Add Transaction", key="add_tx"):
                if tx_amount > 0:
                    add_portfolio_transaction(
                        date=tx_date.strftime("%Y-%m-%d"),
                        tx_type=tx_type,
                        amount=tx_amount,
                        notes=tx_notes
                    )
                    st.success(f"Added {tx_type}: PKR {tx_amount:,.0f}")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Amount must be greater than 0")

        with mgmt_tab2:
            st.markdown("**Update Portfolio Value**")
            col1, col2 = st.columns(2)
            with col1:
                pv_date = st.date_input("Date (month-end)", key="pv_date")
            with col2:
                pv_value = st.number_input("Portfolio Value (PKR)", min_value=0.0, step=10000.0, key="pv_value")

            pv_notes = st.text_input("Notes (optional)", key="pv_notes")

            if st.button("✅ Update Portfolio Value", key="add_pv"):
                if pv_value > 0:
                    add_portfolio_value(
                        date=pv_date.strftime("%Y-%m-%d"),
                        value=pv_value,
                        notes=pv_notes
                    )
                    st.success(f"Updated portfolio value for {pv_date.strftime('%B %d, %Y')}: PKR {pv_value:,.0f}")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Portfolio value must be greater than 0")

    # ── Display Transactions & Values ──────────────────────────────────────────
    with st.expander("📋 View All Entries", expanded=False):
        col_tx, col_pv = st.columns(2)

        with col_tx:
            st.markdown("**Recent Transactions**")
            try:
                txs = get_portfolio_transactions()
                if txs:
                    tx_display = []
                    for tx in txs[:10]:  # Show last 10
                        tx_display.append({
                            "Date": tx["date"],
                            "Type": tx["type"].title(),
                            "Amount": f"PKR {tx['amount']:,.0f}",
                            "Notes": tx.get("notes", "—"),
                        })
                    st.dataframe(
                        pd.DataFrame(tx_display),
                        width='stretch',
                        hide_index=True,
                    )
                    if st.button("🗑️ Refresh transactions", key="refresh_tx"):
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.caption("No transactions recorded.")
            except Exception as e:
                st.warning(f"Could not load transactions: {e}")

        with col_pv:
            st.markdown("**Recent Portfolio Values**")
            try:
                pvs = get_portfolio_values()
                if pvs:
                    pv_display = []
                    for pv in pvs[:10]:  # Show last 10
                        pv_display.append({
                            "Date": pv["date"],
                            "Value": f"PKR {pv['value']:,.0f}",
                            "Notes": pv.get("notes", "—"),
                        })
                    st.dataframe(
                        pd.DataFrame(pv_display),
                        width='stretch',
                        hide_index=True,
                    )
                    if st.button("🗑️ Refresh values", key="refresh_pv"):
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.caption("No portfolio values recorded.")
            except Exception as e:
                st.warning(f"Could not load portfolio values: {e}")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Cumulative P&L curve ──────────────────────────────────────────────────
    st.markdown("**Cumulative P&L by Trade  (PKR)**")
    closed_s = closed.sort_values("exit_date", na_position="last").copy()
    closed_s["#"]      = range(1, len(closed_s) + 1)
    closed_s["cum_pl"] = closed_s["actual_pl_pkr"].fillna(0).cumsum()

    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(
        x=closed_s["#"], y=closed_s["cum_pl"],
        mode="lines", fill="tozeroy",
        line={"color": "#3b82f6", "width": 2},
        fillcolor="rgba(59,130,246,0.08)",
        hovertemplate="Trade #%{x}<br>Cumulative: PKR %{y:+,.0f}<extra></extra>",
    ))
    fig_cum.add_hline(y=0, line_color="#94a3b8", line_width=1)
    fig_cum.update_layout(
        height=260, margin={"l": 4, "r": 4, "t": 8, "b": 8},
        xaxis={"title": "Trade #", "tickfont": {"size": 9}},
        yaxis={"tickfont": {"size": 9}, "tickformat": ",.0f"},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_cum, width='stretch')

    # ── Win / Loss distribution ───────────────────────────────────────────────
    col_wl, col_bar = st.columns(2)

    with col_wl:
        st.markdown("**P&L % Distribution**")
        fig_d = go.Figure()
        fig_d.add_trace(go.Histogram(
            x=wins["actual_pl_pct"].dropna(), name="Wins",
            marker_color="#22c55e", opacity=0.75,
            hovertemplate="%{x:.1f}%: %{y} trades<extra></extra>",
        ))
        fig_d.add_trace(go.Histogram(
            x=losses["actual_pl_pct"].dropna(), name="Losses",
            marker_color="#ef4444", opacity=0.75,
            hovertemplate="%{x:.1f}%: %{y} trades<extra></extra>",
        ))
        fig_d.update_layout(
            barmode="overlay", height=240,
            margin={"l": 4, "r": 4, "t": 8, "b": 8},
            xaxis={"title": "P&L %", "tickfont": {"size": 9}},
            yaxis={"title": "# Trades", "tickfont": {"size": 9}},
            legend={"font": {"size": 10}},
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_d, width='stretch')

    with col_bar:
        st.markdown("**Avg Win % vs Avg Loss %**")
        rr_ratio = abs(avg_win_pct / avg_loss_pct) if avg_loss_pct != 0 else 0
        fig_b = go.Figure(go.Bar(
            x=["Avg Win", "Avg Loss"],
            y=[avg_win_pct, avg_loss_pct],
            marker_color=["#22c55e", "#ef4444"],
            text=[f"{avg_win_pct:+.2f}%", f"{avg_loss_pct:+.2f}%"],
            textposition="outside",
            textfont={"size": 11},
            width=0.4,
        ))
        fig_b.add_annotation(
            x=0.5, y=avg_loss_pct * 0.4, xref="x", yref="y",
            text=f"Ratio  {rr_ratio:.2f}x",
            showarrow=False, font={"size": 10, "color": "#64748b"},
        )
        fig_b.update_layout(
            height=240, margin={"l": 4, "r": 4, "t": 8, "b": 8},
            yaxis={"ticksuffix": "%", "tickfont": {"size": 9}},
            xaxis={"tickfont": {"size": 10}},
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_b, width='stretch')


# ===============================================================================
# PAGE 7 -- BACKTEST
# ===============================================================================
elif cur == PAGES[11]:  # Backtest (updated index)
    st.markdown("**Backtest Results** -- KIRAN rules replayed on historical data (Jan 2024 - present)")
    st.caption(
        "Point-in-time correct: each date only uses data available on that day. "
        "Outcomes labeled against the next 30 trading days of closes."
    )

    raw_bt = get_backtest_summary()

    if not raw_bt:
        st.info("Backtest not yet run. Execute: `python backtest.py`")
        st.stop()

    bt = pd.DataFrame(raw_bt)
    bt["as_of_date"] = pd.to_datetime(bt["as_of_date"])

    # ── Triggered vs not ──────────────────────────────────────────────────────
    WIN_OUTCOMES  = ["Win_Trail", "Win_T1"]   # hybrid trail model
    triggered  = bt[bt["outcome"].isin(WIN_OUTCOMES + ["Loss"])]
    wins_trail = bt[bt["outcome"] == "Win_Trail"]
    wins_t1    = bt[bt["outcome"] == "Win_T1"]
    losses     = bt[bt["outcome"] == "Loss"]
    stale      = bt[bt["outcome"].isin(["Stale_Setup", "No_Trigger"])]   # both old + new label

    n_total     = len(bt)
    n_triggered = len(triggered)
    n_win_trail = len(wins_trail)
    n_win_t1    = len(wins_t1)
    n_loss      = len(losses)
    n_stale     = len(stale)

    trigger_rate   = n_triggered  / n_total     if n_total     else 0
    win_rate_trail = n_win_trail  / n_triggered if n_triggered else 0
    win_rate_t1    = n_win_t1     / n_triggered if n_triggered else 0
    loss_rate      = n_loss       / n_triggered if n_triggered else 0
    total_win_r    = win_rate_trail + win_rate_t1

    date_min = bt["as_of_date"].min().strftime("%b %Y")
    date_max = bt["as_of_date"].max().strftime("%b %Y")

    # ── KPI Row 1 ─────────────────────────────────────────────────────────────
    st.markdown("### KIRAN Screener Performance")
    st.caption(f"{n_total:,} setups across {bt['as_of_date'].nunique()} trading days  "
               f"({date_min} - {date_max})")
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    r1 = st.columns(4)
    r1[0].markdown(kpi("Total Setups",   f"{n_total:,}",
                       f"{bt['as_of_date'].nunique()} trading days", "#3b82f6"), unsafe_allow_html=True)
    r1[1].markdown(kpi("Trigger Rate",   f"{trigger_rate*100:.1f}%",
                       f"{n_triggered:,} of {n_total:,} entered", "#f59e0b"), unsafe_allow_html=True)
    r1[2].markdown(kpi("Win Rate",       f"{total_win_r*100:.1f}%",
                       f"of triggered trades", gc(total_win_r - 0.5)), unsafe_allow_html=True)
    r1[3].markdown(kpi("Loss Rate",      f"{loss_rate*100:.1f}%",
                       f"of triggered trades", gc(0.5 - loss_rate)), unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── KPI Row 2 ─────────────────────────────────────────────────────────────
    avg_fwd_win  = triggered[triggered["outcome"].isin(WIN_OUTCOMES)]["outcome_days"].mean() if n_triggered else 0
    avg_fwd_loss = triggered[triggered["outcome"] == "Loss"]["outcome_days"].mean() if n_loss else 0
    avg_qs       = bt["quality_score"].mean() if "quality_score" in bt.columns else 0
    qs_win       = triggered[triggered["outcome"].isin(WIN_OUTCOMES)]["quality_score"].mean() if n_triggered and "quality_score" in bt.columns else 0
    qs_loss      = triggered[triggered["outcome"] == "Loss"]["quality_score"].mean() if n_loss and "quality_score" in bt.columns else 0

    r2 = st.columns(4)
    r2[0].markdown(kpi("Trailed Exit",   f"{win_rate_trail*100:.1f}%",
                       f"{n_win_trail:,} trailing stop wins", "#22c55e"), unsafe_allow_html=True)
    r2[1].markdown(kpi("T1 Partial",     f"{win_rate_t1*100:.1f}%",
                       f"{n_win_t1:,} trades hit T1", "#86efac"), unsafe_allow_html=True)
    r2[2].markdown(kpi("Avg Days (W/L)", f"{avg_fwd_win:.0f}d / {avg_fwd_loss:.0f}d",
                       "wins vs losses", "#3b82f6"), unsafe_allow_html=True)
    r2[3].markdown(kpi("Avg Quality",    f"{avg_qs:.1f} / 4",
                       f"wins {qs_win:.1f}  losses {qs_loss:.1f}", "#f59e0b"), unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Long vs Short panels ───────────────────────────────────────────────────
    st.markdown("**Long vs Short**")
    lc, sc, _ = st.columns([5, 5, 2])

    for col, dirn, label, clr in [(lc, "LONG", "Long", "#22c55e"), (sc, "SHORT", "Short", "#ef4444")]:
        d  = bt[bt["direction"] == dirn]
        dt = d[d["outcome"].isin(WIN_OUTCOMES + ["Loss"])]
        dw = d[d["outcome"].isin(WIN_OUTCOMES)]
        dl = d[d["outcome"] == "Loss"]
        nd = len(d);  ndt = len(dt)
        tr   = ndt / nd * 100 if nd else 0
        wr   = len(dw) / ndt * 100 if ndt else 0
        lr   = len(dl) / ndt * 100 if ndt else 0
        trl  = len(d[d["outcome"]=="Win_Trail"]) / ndt * 100 if ndt else 0
        t1   = len(d[d["outcome"]=="Win_T1"])    / ndt * 100 if ndt else 0
        col.markdown(
            f'<div style="border:1px solid {clr}25; border-left:4px solid {clr}; '
            f'border-radius:8px; padding:11px 14px;">'
            f'<div style="font-weight:700; font-size:0.82rem; color:{clr}; margin-bottom:7px;">'
            f'{label} &nbsp;|&nbsp; {nd:,} setups</div>'
            f'<table style="width:100%; font-size:0.75rem; border-collapse:collapse;">'
            f'<tr><td style="color:#64748b;padding:2px 0;">Trigger Rate</td>'
            f'<td style="text-align:right;font-weight:700;">{tr:.1f}%</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Win Rate (of triggered)</td>'
            f'<td style="text-align:right;font-weight:700;color:#22c55e;">{wr:.1f}%</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Loss Rate (of triggered)</td>'
            f'<td style="text-align:right;font-weight:700;color:#ef4444;">{lr:.1f}%</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Trailed exit</td>'
            f'<td style="text-align:right;font-weight:700;">{trl:.1f}%</td></tr>'
            f'<tr><td style="color:#64748b;padding:2px 0;">Hit T1 only</td>'
            f'<td style="text-align:right;font-weight:700;">{t1:.1f}%</td></tr>'
            f'</table></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Outcome breakdown chart ────────────────────────────────────────────────
    ch1, ch2 = st.columns(2)

    with ch1:
        st.markdown("**Outcome Distribution**")
        outcome_order  = ["Win_Trail", "Win_T1", "Loss", "Stale_Setup", "No_Trigger"]
        outcome_colors = ["#22c55e", "#86efac", "#ef4444", "#94a3b8", "#cbd5e1"]
        outcome_counts = [
            len(bt[bt["outcome"] == o]) for o in outcome_order
        ]
        # Remove empty categories
        pairs = [(l, c, n) for l, c, n in zip(outcome_order, outcome_colors, outcome_counts) if n > 0]
        if pairs:
            ol, oc, ov = zip(*pairs)
        else:
            ol, oc, ov = outcome_order, outcome_colors, outcome_counts
        fig_pie = go.Figure(go.Pie(
            labels=ol, values=ov,
            marker_colors=oc,
            hole=0.45, textfont_size=11,
            hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
        ))
        fig_pie.update_layout(
            height=270, margin={"l": 4, "r": 4, "t": 8, "b": 8},
            legend={"font": {"size": 10}, "orientation": "v"},
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_pie, width='stretch')

    with ch2:
        st.markdown("**Win Rate by Quality Score**")
        if "quality_score" in bt.columns:
            qs_stats = []
            for qs in sorted(bt["quality_score"].dropna().unique()):
                g  = bt[bt["quality_score"] == qs]
                gt = g[g["outcome"].isin(WIN_OUTCOMES + ["Loss"])]
                gw = gt[gt["outcome"].isin(WIN_OUTCOMES)]
                if len(gt) >= 5:
                    qs_stats.append({
                        "qs":  qs,
                        "wr":  len(gw)/len(gt)*100,
                        "n":   len(gt),
                    })
            if qs_stats:
                qs_df = pd.DataFrame(qs_stats)
                fig_qs = go.Figure(go.Bar(
                    x=[f"Q{int(r['qs'])}" for _, r in qs_df.iterrows()],
                    y=qs_df["wr"],
                    marker_color=["#22c55e" if w >= 50 else "#ef4444" for w in qs_df["wr"]],
                    text=[f"{w:.0f}%<br><span style='font-size:9px'>(n={n})</span>"
                          for w, n in zip(qs_df["wr"], qs_df["n"])],
                    textposition="outside", textfont_size=10,
                ))
                fig_qs.add_hline(y=50, line_dash="dot", line_color="#94a3b8",
                                 annotation_text="50%", annotation_position="right")
                fig_qs.update_layout(
                    height=270, margin={"l": 4, "r": 4, "t": 8, "b": 36},
                    yaxis={"title": "Win Rate %", "range": [0, 105], "tickfont": {"size": 9}},
                    xaxis={"title": "Quality Score (0-4)", "tickfont": {"size": 10}},
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_qs, width='stretch')

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Monthly setup count ────────────────────────────────────────────────────
    st.markdown("**Monthly Setups Generated & Trigger Rate**")
    bt["ym"] = bt["as_of_date"].dt.to_period("M")
    monthly = (
        bt.groupby("ym")
        .agg(
            total     = ("outcome", "count"),
            triggered = ("outcome", lambda x: x.isin(WIN_OUTCOMES + ["Loss"]).sum()),
            wins      = ("outcome", lambda x: x.isin(WIN_OUTCOMES).sum()),
        )
        .reset_index()
    )
    monthly["ym_str"] = monthly["ym"].astype(str)
    monthly["win_rate"] = (monthly["wins"] / monthly["triggered"] * 100).fillna(0)

    fig_mo = go.Figure()
    fig_mo.add_trace(go.Bar(
        x=monthly["ym_str"], y=monthly["total"],
        name="Setups",
        marker_color="rgba(59,130,246,0.25)",
        hovertemplate="%{x}: %{y} setups<extra></extra>",
    ))
    fig_mo.add_trace(go.Bar(
        x=monthly["ym_str"], y=monthly["triggered"],
        name="Triggered",
        marker_color="rgba(245,158,11,0.5)",
        hovertemplate="%{x}: %{y} triggered<extra></extra>",
    ))
    fig_mo.add_trace(go.Scatter(
        x=monthly["ym_str"], y=monthly["win_rate"],
        name="Win Rate %", yaxis="y2", mode="lines+markers",
        line={"color": "#22c55e", "width": 2},
        marker={"size": 5},
        hovertemplate="%{x}: %{y:.1f}% win rate<extra></extra>",
    ))
    fig_mo.update_layout(
        barmode="overlay", height=280,
        margin={"l": 4, "r": 50, "t": 8, "b": 8},
        xaxis={"tickfont": {"size": 9}, "tickangle": -30},
        yaxis={"title": "# Setups", "tickfont": {"size": 9}},
        yaxis2={"title": "Win Rate %", "overlaying": "y", "side": "right",
                "range": [0, 110], "tickfont": {"size": 9}, "ticksuffix": "%"},
        legend={"font": {"size": 10}, "orientation": "h", "y": 1.08},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_mo, width='stretch')

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Equity curve ──────────────────────────────────────────────────────────
    st.markdown("**Simulated Equity Curve** — 1% portfolio risk per trade")
    st.caption("Uses your actual capital inflows/outflows. P&L compounds on top of capital base.")

    # Capital cash-flow timeline  (negative = invested, positive = withdrawn)
    CAPITAL_FLOWS = [
        ("2024-10-01", -498_767),
        ("2024-12-13", -450_000),
        ("2025-04-08",  +25_226),
        ("2025-04-09",  +10_200),
        ("2025-06-11",  +10_000),
        ("2025-07-29",  +55_000),
        ("2025-11-13", -200_000),
        ("2026-03-31", -1_000_000),
    ]

    def capital_base(date_str: str) -> float:
        base = 0.0
        for fd, flow in CAPITAL_FLOWS:
            if date_str >= fd:
                base -= flow   # invest (negative flow) → adds; withdraw → subtracts
        return base

    # Only triggered trades with a realized_r, sorted by trigger_date
    if "realized_r" in bt.columns and "trigger_date" in bt.columns:
        trd = (
            bt[bt["realized_r"].notna() & bt["trigger_date"].notna()]
            .copy()
            .sort_values("trigger_date")
        )

        if not trd.empty:
            cum_pl    = 0.0
            eq_rows   = []
            for _, t in trd.iterrows():
                tdate   = t["trigger_date"]
                base    = capital_base(tdate)
                port_v  = base + cum_pl
                risk    = port_v * 0.01
                pl      = float(t["realized_r"]) * risk
                cum_pl += pl
                eq_rows.append({
                    "trade_n":   len(eq_rows) + 1,
                    "date":      tdate,
                    "portfolio": base + cum_pl,
                    "capital":   base,
                    "pl":        pl,
                    "outcome":   t["outcome"],
                })

            eq_df = pd.DataFrame(eq_rows)

            final_port  = eq_df["portfolio"].iloc[-1]
            final_base  = eq_df["capital"].iloc[-1]
            total_pl_r  = trd["realized_r"].sum()
            peak        = eq_df["portfolio"].max()
            trough_idx  = eq_df["portfolio"].expanding().apply(lambda x: x.max() - x.iloc[-1]).idxmax()
            max_dd      = (eq_df["portfolio"].expanding().max() - eq_df["portfolio"]).max()
            max_dd_pct  = max_dd / peak * 100 if peak else 0

            dd1, dd2, dd3, dd4 = st.columns(4)
            dd1.markdown(kpi("Final Portfolio",  f"PKR {final_port:,.0f}",
                             f"base PKR {final_base:,.0f}", gc(final_port - final_base)), unsafe_allow_html=True)
            dd2.markdown(kpi("Trade P&L",        f"PKR {cum_pl:+,.0f}",
                             "from 1% risk compounding", gc(cum_pl)), unsafe_allow_html=True)
            dd3.markdown(kpi("Total R Earned",   f"{total_pl_r:+.1f} R",
                             f"across {len(trd):,} triggered trades", gc(total_pl_r)), unsafe_allow_html=True)
            dd4.markdown(kpi("Max Drawdown",      f"{max_dd_pct:.1f}%",
                             f"PKR {max_dd:,.0f} from peak", "#ef4444"), unsafe_allow_html=True)

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            fig_eq = go.Figure()
            # Capital base step line
            fig_eq.add_trace(go.Scatter(
                x=eq_df["trade_n"], y=eq_df["capital"],
                mode="lines", name="Capital Base",
                line={"color": "#94a3b8", "width": 1.5, "dash": "dot"},
                hovertemplate="Trade #%{x}<br>Capital base: PKR %{y:,.0f}<extra></extra>",
            ))
            # Portfolio equity line
            fig_eq.add_trace(go.Scatter(
                x=eq_df["trade_n"], y=eq_df["portfolio"],
                mode="lines", name="Portfolio",
                line={"color": "#3b82f6", "width": 2.5},
                fill="tonexty", fillcolor="rgba(59,130,246,0.08)",
                hovertemplate="Trade #%{x}<br>Portfolio: PKR %{y:,.0f}<extra></extra>",
            ))
            fig_eq.update_layout(
                height=320, margin={"l": 4, "r": 4, "t": 8, "b": 8},
                xaxis={"title": "Trade #", "tickfont": {"size": 9}},
                yaxis={"title": "PKR", "tickfont": {"size": 9}, "tickformat": ",.0f"},
                legend={"font": {"size": 10}, "orientation": "h", "y": 1.08},
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_eq, width='stretch')
        else:
            st.info("No triggered trades with realized_r yet. Re-run backtest after volume backfill completes.")
    else:
        st.info("Equity curve available after next backtest run (adding realized_r column).")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Filterable data table ──────────────────────────────────────────────────
    st.markdown("**Detailed Setup Table**")
    all_outcomes_filter = ["All", "Win_Trail", "Win_T1", "Loss", "Stale_Setup", "No_Trigger"]
    f1, f2, f3 = st.columns(3)
    bt_dir_f = f1.selectbox("Direction", ["All", "LONG", "SHORT"], key="bt_dir")
    bt_out_f = f2.selectbox("Outcome",   all_outcomes_filter, key="bt_out")
    bt_qs_f  = f3.selectbox("Quality",   ["All", "0", "1", "2", "3", "4"], key="bt_qs")

    bt_view = bt.copy()
    if bt_dir_f != "All": bt_view = bt_view[bt_view["direction"]     == bt_dir_f]
    if bt_out_f != "All": bt_view = bt_view[bt_view["outcome"]       == bt_out_f]
    if bt_qs_f  != "All": bt_view = bt_view[bt_view["quality_score"] == int(bt_qs_f)]

    all_bt_cols = list(bt_view.columns)
    show_cols = [c for c in [
        "as_of_date", "direction", "symbol",
        "quality_score", "entry_price", "stop_loss",
        "target_1r", "target_2r", "risk_pct",
        "outcome", "trigger_date", "outcome_date", "outcome_days",
    ] if c in all_bt_cols]
    col_labels = {
        "as_of_date":   "Date",
        "direction":    "Dir",
        "symbol":       "Symbol",
        "quality_score":"Quality",
        "entry_price":  "Entry",
        "stop_loss":    "SL",
        "target_1r":    "T1",
        "target_2r":    "T2",
        "risk_pct":     "Risk%",
        "outcome":      "Outcome",
        "trigger_date": "Triggered",
        "outcome_date": "Exit Date",
        "outcome_days": "Days",
    }
    bt_disp = bt_view[show_cols].copy()
    bt_disp.columns = [col_labels[c] for c in show_cols]
    # Format date columns as DD/MM/YY (no timestamps)
    for dcol in ["Date", "Triggered", "Exit Date"]:
        if dcol in bt_disp.columns:
            bt_disp[dcol] = bt_disp[dcol].apply(fmt_date)

    def style_bt_outcome(series):
        palette = {
            "Win_Trail":   "color:#22c55e; font-weight:bold",
            "Win_T1":      "color:#86efac; font-weight:bold",
            "Loss":        "color:#ef4444; font-weight:bold",
            "Stale_Setup": "color:#94a3b8",
            "No_Trigger":  "color:#94a3b8",
        }
        return [palette.get(v, "") for v in series]

    fmt_bt = {c: "{:.2f}" for c in ["Entry","SL","T1","T2","Risk%"] if c in bt_disp.columns}
    st.dataframe(
        bt_disp.style
        .apply(style_direction,  subset=["Dir"])
        .apply(style_bt_outcome, subset=["Outcome"])
        .format(fmt_bt, na_rep="—"),
        width='stretch', hide_index=True, height=380,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # KIRAN SETUP SIMULATION — buy-on-strength, 1% risk, 6% max SL
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.divider()
    st.markdown("### Kiran Setup Simulation")
    st.caption(
        "Same screener signals as above — different execution: entry 1 PKR above signal-day HIGH, "
        "max 6% SL, 1% portfolio risk per trade, 99% capital cap, no margin. "
        "Initial capital PKR 1,000,000. Run `python kiran_sim.py` to (re)generate."
    )

    raw_sim = get_sim_portfolio_data()

    if not raw_sim:
        st.info("Simulation not yet run. Execute: `python kiran_sim.py`")
    else:
        sim = pd.DataFrame(raw_sim)
        sim["setup_date"] = pd.to_datetime(sim["setup_date"])

        SIM_WIN  = ["Win_Trail"]
        SIM_LOSS = ["Loss"]
        sim_trig = sim[sim["trigger_date"].notna() & ~sim["outcome"].isin(["Skipped"])]
        sim_wins = sim[sim["outcome"] == "Win_Trail"]
        sim_loss = sim[sim["outcome"] == "Loss"]
        sim_skip = sim[sim["outcome"] == "Skipped"]
        sim_stal = sim[sim["outcome"].isin(["Stale", "Expired"])]

        n_sim_total   = len(sim)
        n_sim_trig    = len(sim_trig)
        n_sim_wins    = len(sim_wins)
        n_sim_loss    = len(sim_loss)
        n_sim_skip    = len(sim_skip)

        sim_trigger_r = n_sim_trig  / n_sim_total * 100 if n_sim_total else 0
        sim_win_r     = n_sim_wins  / n_sim_trig  * 100 if n_sim_trig  else 0
        sim_loss_r    = n_sim_loss  / n_sim_trig  * 100 if n_sim_trig  else 0

        sd_min = sim["setup_date"].min().strftime("%b %Y")
        sd_max = sim["setup_date"].max().strftime("%b %Y")

        st.caption(f"{n_sim_total:,} signals  ·  {sd_min} – {sd_max}")

        sr1 = st.columns(4)
        sr1[0].markdown(kpi("Total Signals",   f"{n_sim_total:,}",
                            f"{n_sim_skip:,} skipped (risk > 6%)", "#3b82f6"), unsafe_allow_html=True)
        sr1[1].markdown(kpi("Trigger Rate",    f"{sim_trigger_r:.1f}%",
                            f"{n_sim_trig:,} entries fired", "#f59e0b"), unsafe_allow_html=True)
        sr1[2].markdown(kpi("Win Rate",        f"{sim_win_r:.1f}%",
                            f"{n_sim_wins:,} Win_Trail", gc(sim_win_r / 100 - 0.5)), unsafe_allow_html=True)
        sr1[3].markdown(kpi("Loss Rate",       f"{sim_loss_r:.1f}%",
                            f"{n_sim_loss:,} losses", gc(0.5 - sim_loss_r / 100)), unsafe_allow_html=True)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── Equity curve from simulation ──────────────────────────────────────
        sim_closed = (
            sim[sim["portfolio_after"].notna() & sim["exit_date"].notna()]
            .copy()
            .sort_values("exit_date")
        )

        if not sim_closed.empty:
            sim_closed["trade_n"] = range(1, len(sim_closed) + 1)
            final_port  = sim_closed["portfolio_after"].iloc[-1]
            peak_port   = sim_closed["portfolio_after"].max()
            total_pl    = sim[sim["pl_pkr"].notna()]["pl_pkr"].sum()
            drawdowns   = (sim_closed["portfolio_after"].expanding().max()
                           - sim_closed["portfolio_after"])
            max_dd      = drawdowns.max()
            max_dd_pct  = max_dd / peak_port * 100 if peak_port else 0
            total_r     = sim[sim["realized_r"].notna()]["realized_r"].sum()

            eq1, eq2, eq3, eq4 = st.columns(4)
            eq1.markdown(kpi("Final Portfolio",  f"PKR {final_port:,.0f}",
                             f"from PKR 1,000,000", gc(final_port - 1_000_000)), unsafe_allow_html=True)
            eq2.markdown(kpi("Total P&L",        f"PKR {total_pl:+,.0f}",
                             "1% risk compounding", gc(total_pl)), unsafe_allow_html=True)
            eq3.markdown(kpi("Total R Earned",   f"{total_r:+.1f} R",
                             f"across {n_sim_trig:,} triggered", gc(total_r)), unsafe_allow_html=True)
            eq4.markdown(kpi("Max Drawdown",      f"{max_dd_pct:.1f}%",
                             f"PKR {max_dd:,.0f} from peak", "#ef4444"), unsafe_allow_html=True)

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            fig_sim = go.Figure()
            fig_sim.add_trace(go.Scatter(
                x=sim_closed["trade_n"], y=sim_closed["portfolio_after"],
                mode="lines", name="Portfolio",
                line={"color": "#22c55e", "width": 2.5},
                hovertemplate="Trade #%{x}<br>PKR %{y:,.0f}<extra></extra>",
            ))
            fig_sim.add_hline(y=1_000_000, line_dash="dot", line_color="#94a3b8",
                              annotation_text="1M start", annotation_position="right")
            fig_sim.update_layout(
                height=300, margin={"l": 4, "r": 4, "t": 8, "b": 8},
                xaxis={"title": "Trade #", "tickfont": {"size": 9}},
                yaxis={"title": "PKR", "tickfont": {"size": 9}, "tickformat": ",.0f"},
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_sim, width='stretch')
        else:
            st.info("No closed trades yet in simulation.")

    # ══════════════════════════════════════════════════════════════════════════
    # STM SCREENER PERFORMANCE — numbers only, no chart
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.divider()
    st.markdown("### STM Screener Performance")
    st.caption("Based on STM picks saved to the Trade Log. Outcomes reflect manually logged results.")

    _all_setups = get_trade_setups()
    _stm_all    = [r for r in _all_setups if r.get("source") == "STM"]
    _stm_closed = [r for r in _stm_all  if r.get("status")  == "Closed"]
    _stm_active = [r for r in _stm_all  if r.get("status")  in ("Active", "Pending")]

    _stm_total   = len(_stm_all)
    _stm_wins    = sum(1 for r in _stm_closed if r.get("outcome") == "Win")
    _stm_losses  = sum(1 for r in _stm_closed if r.get("outcome") == "Loss")
    _stm_closed_n= len(_stm_closed)

    _stm_trig_r  = _stm_closed_n / _stm_total       * 100 if _stm_total       else 0
    _stm_win_r   = _stm_wins     / _stm_closed_n    * 100 if _stm_closed_n    else 0
    _stm_loss_r  = _stm_losses   / _stm_closed_n    * 100 if _stm_closed_n    else 0

    stm_c = st.columns(4)
    stm_c[0].markdown(kpi("Total STM Setups",  f"{_stm_total:,}",
                          f"{len(_stm_active):,} active / pending", "#3b82f6"), unsafe_allow_html=True)
    stm_c[1].markdown(kpi("Closed Rate",       f"{_stm_trig_r:.1f}%",
                          f"{_stm_closed_n:,} logged & closed", "#f59e0b"), unsafe_allow_html=True)
    stm_c[2].markdown(kpi("Win Rate",          f"{_stm_win_r:.1f}%"  if _stm_closed_n else "—",
                          f"{_stm_wins:,} wins of {_stm_closed_n} closed",
                          gc(_stm_win_r / 100 - 0.5) if _stm_closed_n else "#94a3b8"),
                      unsafe_allow_html=True)
    stm_c[3].markdown(kpi("Loss Rate",         f"{_stm_loss_r:.1f}%" if _stm_closed_n else "—",
                          f"{_stm_losses:,} losses of {_stm_closed_n} closed",
                          gc(0.5 - _stm_loss_r / 100) if _stm_closed_n else "#94a3b8"),
                      unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — MARKET REGIME  (Weinstein Breadth Z-Score)
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[1]:  # Regime
    from weinstein import (
        WeinsteinIndicator, run_optimizer,
        PSX_DEFAULTS, PSX_KNOWN_BOTTOMS, PSX_KNOWN_TOPS,
    )

    # ════════════════════════════════════════════════════════════════════════════════
    # 🏛️ NEW: 4-GATES MARKET DASHBOARD (ULTRA-CLEAN, HIGH-IMPACT DESIGN)
    # ════════════════════════════════════════════════════════════════════════════════
    # This new layout replaces the old visual entirely while keeping all original
    # code intact below (hidden in an expander for instant rollback).

    # ── Load data ──────────────────────────────────────────────────────────────
    with st.spinner("🔄 Loading market gates…"):
        wd = load_weinstein_data()

    if wd.get("error"):
        st.error("Weinstein data error — see traceback below")
        st.code(wd["error"], language="python")
        st.stop()

    breadth  = wd["breadth"]
    signals  = wd["signals"]
    regime   = wd["regime"]
    w_params = wd["params"]

    # ── Extract core regime values ──────────────────────────────────────────────
    zone            = regime["zone"]
    zcolor          = regime["zone_color"]
    fz_val          = regime["fast_z"]
    sl_val          = regime["signal_line"]
    hist_val        = regime.get("z_histogram")
    slope_val       = regime.get("fast_z_slope")
    score_val       = regime.get("trend_score")
    roc_val         = regime.get("breadth_roc")
    direction       = regime.get("direction", "Flat")
    dir_arrow       = regime.get("direction_arrow", "→")
    pct_val         = regime["pct_above_ma"]
    idx_abv         = regime["index_above_ma"]
    last_date       = regime["last_date"]
    regime_state    = regime.get("regime_state", "Out of Market")
    regime_color    = regime.get("regime_color", "#ef4444")
    last_cross_sig  = regime.get("last_cross_sig")
    last_cross_date = regime.get("last_cross_date")

    dir_color = (
        "#22c55e" if direction == "Rising"  else
        "#ef4444" if direction == "Falling" else
        "#94a3b8"
    )
    cross_colors = {"BUY": "#22c55e", "SELL": "#ef4444"}
    cross_icon   = {"BUY": "▲", "SELL": "▼"}

    # ── Get KSE-100 data for GATE 1 from signals dataframe ────────────────────
    try:
        # Get current KSE-100 from latest signal
        kse_current = float(signals["index_close"].iloc[-1]) if len(signals) > 0 else 0

        # Compute 50-day MA from signals
        kse_ma50 = float(signals["index_close"].tail(50).mean()) if len(signals) >= 50 else float(signals["index_close"].mean())

        # Calculate status
        kse_above_ma = kse_current > kse_ma50
        kse_pct_diff = ((kse_current - kse_ma50) / kse_ma50 * 100) if kse_ma50 > 0 else 0
    except Exception as e:
        kse_current = 0
        kse_ma50 = 0
        kse_above_ma = False
        kse_pct_diff = 0

    # ── Store ALL GATE VALUES in session_state for screeners to read ────────────────
    # This is the CRITICAL link: screeners will read these values to adapt their filters
    st.session_state.gate1_bullish = kse_above_ma
    st.session_state.gate1_kse = kse_current
    st.session_state.gate1_ma50 = kse_ma50
    st.session_state.gate2_pct = pct_val
    st.session_state.gate2_strength = "STRONG" if pct_val > 65 else "NEUTRAL" if pct_val > 50 else "WEAK"
    st.session_state.gate3_histogram = hist_val
    st.session_state.gate3_fz = fz_val
    st.session_state.gate3_sl = sl_val
    st.session_state.gates_ready = True
    st.session_state.gates_timestamp = pd.Timestamp.now()

    # ═══════════════════════════════════════════════════════════════════════════════
    # 🏛️ THE 4-GATES DASHBOARD — ULTRA-MINIMAL, MAXIMALLY CLEAR
    # ═══════════════════════════════════════════════════════════════════════════════

    st.markdown(
        """<h1 style="text-align:center; font-size:2.2rem; font-weight:900;
           color:#1e293b; margin-bottom:0.5rem; letter-spacing:-0.02em;">
           📊 MARKET GATES</h1>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """<p style="text-align:center; font-size:0.9rem; color:#64748b; margin-bottom:2rem;">
           Four pillars of market regime. A layman's instant market read in 2 seconds.</p>""",
        unsafe_allow_html=True,
    )

    # ── GATE 1 & 2 (Top row) ───────────────────────────────────────────────────
    g1_col, g2_col = st.columns(2, gap="medium")

    with g1_col:
        # ────────────────────────────────────────────────────────────────────────
        # GATE 1: MACRO REGIME — KSE-100 vs 50-MA
        # ────────────────────────────────────────────────────────────────────────
        gate1_color = "#10b981" if kse_above_ma else "#ef4444"
        gate1_icon = "▲" if kse_above_ma else "▼"
        gate1_label = "ABOVE 50MA" if kse_above_ma else "BELOW 50MA"

        gate1_html = f"""
        <div style="background:linear-gradient(135deg, {gate1_color}08, {gate1_color}04); border:2px solid {gate1_color}33; border-radius:14px; padding:32px 24px; text-align:center; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
            <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; letter-spacing:0.12em; font-weight:600; margin-bottom:12px;">🏛️ Gate 1: Macro Regime</div>
            <div style="font-size:3.5rem; font-weight:900; color:#1e293b; line-height:1; margin-bottom:8px;">{int(kse_current):,}</div>
            <div style="font-size:0.85rem; color:#64748b; margin-bottom:16px;">KSE-100 Index</div>
            <div style="background:{gate1_color}15; border:1.5px solid {gate1_color}40; border-radius:8px; padding:10px 16px; display:inline-block;">
                <span style="font-size:2rem; color:{gate1_color}; margin-right:6px;">{gate1_icon}</span>
                <span style="font-size:1.1rem; font-weight:800; color:{gate1_color};">{gate1_label} ({kse_pct_diff:+.1f}%)</span>
            </div>
        </div>
        """
        st.markdown(gate1_html, unsafe_allow_html=True)

    with g2_col:
        # ────────────────────────────────────────────────────────────────────────
        # GATE 2: ABSOLUTE PARTICIPATION — % of Stocks Above 50-MA
        # ────────────────────────────────────────────────────────────────────────
        breadth_pct = pct_val
        if breadth_pct >= 70:
            gate2_color = "#10b981"
            gate2_strength = "HEALTHY BREADTH"
        elif breadth_pct >= 50:
            gate2_color = "#f59e0b"
            gate2_strength = "NEUTRAL PARTICIPATION"
        elif breadth_pct >= 30:
            gate2_color = "#f59e0b"
            gate2_strength = "WEAK BREADTH"
        else:
            gate2_color = "#ef4444"
            gate2_strength = "WEAK BREADTH"

        gate2_html = f"""
        <div style="background:linear-gradient(135deg, {gate2_color}08, {gate2_color}04); border:2px solid {gate2_color}33; border-radius:14px; padding:32px 24px; text-align:center; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
            <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; letter-spacing:0.12em; font-weight:600; margin-bottom:12px;">📊 Gate 2: Absolute Participation</div>
            <div style="font-size:3.8rem; font-weight:900; color:{gate2_color}; line-height:1; margin-bottom:8px;">{breadth_pct:.1f}%</div>
            <div style="font-size:0.85rem; color:#64748b; margin-bottom:16px;">Stocks Above 50-Day MA</div>
            <div style="background:{gate2_color}15; border:1.5px solid {gate2_color}40; border-radius:8px; padding:10px 16px; display:inline-block;">
                <span style="font-size:1.1rem; font-weight:800; color:{gate2_color};">{gate2_strength}</span>
            </div>
        </div>
        """
        st.markdown(gate2_html, unsafe_allow_html=True)

    st.markdown("")  # spacer

    # ── GATE 3 & 4 (Bottom row) ────────────────────────────────────────────────
    g3_col, g4_col = st.columns(2, gap="medium")

    with g3_col:
        # ────────────────────────────────────────────────────────────────────────
        # GATE 3: TACTICAL MOMENTUM — Weinstein Histogram + Fast Z vs Signal
        # ────────────────────────────────────────────────────────────────────────
        hist_color = "#10b981" if (hist_val is not None and hist_val >= 0) else "#ef4444"

        gate3_html = f"""
        <div style="background:linear-gradient(135deg, {hist_color}08, {hist_color}04); border:2px solid {hist_color}33; border-radius:14px; padding:24px; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
            <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; letter-spacing:0.12em; font-weight:600; margin-bottom:16px;">⚡ Gate 3: Tactical Momentum</div>
            <div style="text-align:center; margin-bottom:20px;">
                <div style="font-size:2.5rem; font-weight:900; color:{hist_color}; line-height:1;">{hist_val:+.3f}</div>
                <div style="font-size:0.8rem; color:#64748b; margin-top:4px;">Weinstein Histogram (Fast Z − Signal)</div>
            </div>
        </div>
        """
        st.markdown(gate3_html, unsafe_allow_html=True)

        # Mini Weinstein chart (Fast Z vs Signal Line) - with graceful fallback
        try:
            import plotly.graph_objects as go
            tail_mini = min(120, len(signals))
            sig_mini = signals.tail(tail_mini).copy()

            fig_gate3 = go.Figure()

            fig_gate3.add_trace(go.Scatter(
                x=sig_mini.index, y=sig_mini["fast_z"].round(3),
                mode="lines", name="Fast Z",
                line={"color": "#3b82f6", "width": 2.5},
                hovertemplate="Fast Z: %{y:.2f}<extra></extra>",
            ))
            fig_gate3.add_trace(go.Scatter(
                x=sig_mini.index, y=sig_mini["signal_line"].round(3),
                mode="lines", name="Signal Line",
                line={"color": "#f59e0b", "width": 2, "dash": "dot"},
                hovertemplate="Sig Line: %{y:.2f}<extra></extra>",
            ))

            fig_gate3.add_hline(y=0, line_dash="dot", line_color="#94a3b8", line_width=1)
            fig_gate3.update_layout(
                height=200, margin={"l": 0, "r": 0, "t": 0, "b": 0},
                hovermode="x", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"size": 9}},
                showlegend=True,
            )
            fig_gate3.update_xaxes(tickfont={"size": 8}, showticklabels=False)
            fig_gate3.update_yaxes(tickfont={"size": 8})

            st.plotly_chart(fig_gate3, use_container_width=True, key="gate3_chart")
        except Exception as e:
            st.markdown(
                '<div style="background:#e0e7ff; border:1px solid #818cf8; border-radius:8px; padding:20px; text-align:center; color:#4f46e5;"><p style="margin:0; font-size:0.9rem;">Chart data available • Visualization pending</p></div>',
                unsafe_allow_html=True
            )

    with g4_col:
        # ────────────────────────────────────────────────────────────────────────
        # GATE 4: EXECUTION FILTER — ZH Breadth Oscillator (Long vs Short Counts)
        # ────────────────────────────────────────────────────────────────────────
        with st.spinner("Loading Gate 4…"):
            breadth_osc = load_breadth_oscillator_data()

        if breadth_osc.empty:
            st.warning("⚠️ ZH breadth oscillator data unavailable")
        else:
            osc_tail = min(120, len(breadth_osc))
            osc_plot = breadth_osc.tail(osc_tail).copy()

            # Determine gate color based on long vs short
            latest_long = osc_plot["Long_Count"].iloc[-1] if not osc_plot.empty else 0
            latest_short = osc_plot["Short_Count"].iloc[-1] if not osc_plot.empty else 0
            osc_color = "#10b981" if latest_long > latest_short else "#ef4444"

            gate4_html = f"""
            <div style="background:linear-gradient(135deg, {osc_color}08, {osc_color}04); border:2px solid {osc_color}33; border-radius:14px; padding:24px; box-shadow:0 4px 20px rgba(0,0,0,0.08); margin-bottom:12px;">
                <div style="font-size:0.75rem; text-transform:uppercase; color:#64748b; letter-spacing:0.12em; font-weight:600; margin-bottom:4px;">✅ Gate 4: Execution Filter</div>
                <div style="font-size:0.8rem; color:#64748b;">Long vs Short Stock Alignment</div>
            </div>
            """
            st.markdown(gate4_html, unsafe_allow_html=True)

            fig_gate4 = go.Figure()

            fig_gate4.add_trace(go.Scatter(
                x=osc_plot["Date"], y=osc_plot["Long_Count"],
                mode="lines", name="Long Count",
                line={"color": "#10b981", "width": 2.5},
                hovertemplate="Long: %{y:.0f}<extra></extra>",
                fill="tozeroy", fillcolor="rgba(16,185,129,0.1)",
            ))

            fig_gate4.add_trace(go.Scatter(
                x=osc_plot["Date"], y=osc_plot["Short_Count"],
                mode="lines", name="Short Count",
                line={"color": "#ef4444", "width": 2.5},
                hovertemplate="Short: %{y:.0f}<extra></extra>",
                fill="tozeroy", fillcolor="rgba(239,68,68,0.1)",
            ))

            fig_gate4.add_hline(y=0, line_dash="dot", line_color="#94a3b8", line_width=1)

            fig_gate4.update_layout(
                height=200, margin={"l": 0, "r": 0, "t": 0, "b": 0},
                hovermode="x", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"size": 9}},
                showlegend=True,
            )
            fig_gate4.update_xaxes(tickfont={"size": 8}, showticklabels=False)
            fig_gate4.update_yaxes(tickfont={"size": 8})

            st.plotly_chart(fig_gate4, use_container_width=True, key="gate4_chart")

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════════
    # 📚 ORIGINAL DETAILED REGIME PAGE — COMPLETELY HIDDEN FROM VIEWPORT
    # ═══════════════════════════════════════════════════════════════════════════════
    # All original calculations, charts, optimizer, and signal history preserved below.
    # Stored in background (st.session_state) for instant rollback capability.
    # To show original layout, uncomment: if True: instead of if False:
    # ═══════════════════════════════════════════════════════════════════════════════

    if True:  # ← TOGGLE THIS TO SHOW/HIDE ORIGINAL LAYOUT (set to True to show)

        if last_cross_sig and last_cross_date is not None:
            cross_col  = cross_colors.get(last_cross_sig, "#94a3b8")
            cross_html = (
                f'Last signal: <b style="color:{cross_col};">'
                f'{cross_icon.get(last_cross_sig,"")} {last_cross_sig}</b>'
                f' on <b>{pd.Timestamp(last_cross_date).strftime("%d %b %Y")}</b>'
                f' &nbsp;·&nbsp;'
            )
        else:
            cross_html = ""

        rs_icon  = "●" if regime_state == "In Market" else "○"
        kse_str  = "▲ KSE above MA" if idx_abv else "▼ KSE below MA"
        date_str = pd.Timestamp(last_date).strftime("%d %b %Y")

        # Gate status for clarity: show single unified signal
        gate_status = ""
        if hist_val is not None and idx_abv is not None:
            if hist_val > 0 and idx_abv:
                gate_status = "✓ All gates green"
                gate_color = "#22c55e"
            elif hist_val < 0 and not idx_abv:
                gate_status = "✗ All gates red"
                gate_color = "#ef4444"
            else:
                gate_status = "⚠ Mixed signals"
                gate_color = "#f59e0b"
        else:
            gate_status = zone
            gate_color = zcolor

        parts = [
            f'<span style="color:{gate_color}; font-weight:700;">{gate_status}</span>',
        ]
        if last_cross_sig and last_cross_date is not None:
            cc = cross_colors.get(last_cross_sig, "#94a3b8")
            ci = cross_icon.get(last_cross_sig, "")
            parts.append(f'Last signal: <span style="color:{cc}; font-weight:700;">{ci} {last_cross_sig} {pd.Timestamp(last_cross_date).strftime("%d %b %Y")}</span>')
        parts.append(kse_str)
        parts.append(date_str)

        subtitle = ' <span style="color:#94a3b8;">·</span> '.join(parts)

        st.markdown(
            f"""<div style="background:{regime_color}18; border-left:5px solid {regime_color};
                padding:12px 16px; border-radius:8px; margin-bottom:10px;">
                <div style="font-size:1.5rem; font-weight:900; color:{regime_color}; margin-bottom:4px;">
                    {rs_icon} {regime_state}
                </div>
                <div style="font-size:0.78rem; color:#64748b; line-height:1.6;">
                    {subtitle}
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── KPI row (5 tiles) ──────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)

        def _kpi_mini(label, val, fmt, color, subtitle=""):
            sub = f'<div style="font-size:0.55rem; color:#94a3b8; margin-top:1px;">{subtitle}</div>' if subtitle else ""
            return (
                f'<div style="background:{color}12; border:1px solid {color}33; border-top:3px solid {color};'
                f'border-radius:7px; padding:9px 8px; text-align:center;">'
                f'<div style="font-size:0.58rem; color:#64748b; text-transform:uppercase; letter-spacing:.06em;">'
                f'{label}</div>'
                f'<div style="font-size:1.02rem; font-weight:800; color:{color};">{fmt.format(val) if val is not None else "—"}</div>'
                f'{sub}</div>'
            )

        buy_thr  = w_params["buy_threshold"]
        sell_thr = w_params["sell_threshold"]
        hist_color  = "#22c55e" if (hist_val is not None and hist_val >= 0) else "#ef4444"

        k1.markdown(_kpi_mini("Signal Line",   sl_val,   "{:.2f}",   "#8b5cf6"), unsafe_allow_html=True)
        k2.markdown(_kpi_mini("Histogram",     hist_val,  "{:+.2f}", hist_color, "fast_z − sig"), unsafe_allow_html=True)
        k3.markdown(_kpi_mini("% Above 50MA",  pct_val,   "{:.1f}%", "#06b6d4"), unsafe_allow_html=True)
        k4.markdown(_kpi_mini("Buy Threshold", buy_thr,   "{:.1f}",  "#22c55e"), unsafe_allow_html=True)
        k5.markdown(_kpi_mini("Sell Thr.",     sell_thr,  "{:.1f}",  "#ef4444"), unsafe_allow_html=True)

        st.divider()

        # ── Combined chart: Z-Score / Histogram / Breadth % / Trend Score ────────────
        # Single make_subplots with shared_xaxes so crosshair syncs across all panels.

        tail = st.slider("Show last N days", 60, len(signals), min(504, len(signals)), step=21, key="wbs_tail")
        sig_plot = signals.tail(tail).copy()

        breadth_plot = breadth.tail(tail)
        breadth_ma10 = breadth.rolling(10, min_periods=1).mean().tail(tail)
        breadth_ma21 = breadth.rolling(21, min_periods=1).mean().tail(tail)
        breadth_ma50 = breadth.rolling(50, min_periods=1).mean().tail(tail)

        has_ts = "trend_score" in sig_plot.columns

        from plotly.subplots import make_subplots

        n_rows      = 4 if has_ts else 3
        row_heights = [0.35, 0.15, 0.30, 0.20] if has_ts else [0.42, 0.20, 0.38]

        fig = make_subplots(
            rows=n_rows, cols=1,
            shared_xaxes=True,
            row_heights=row_heights,
            vertical_spacing=0.03,
            subplot_titles=["Z-Score", "Momentum", "Breadth %", "Trend Score"][:n_rows],
        )

        # ── Row 1: Z-Score ──────────────────────────────────────────────────────────
        fig.add_hrect(y0=buy_thr, y1=-4, fillcolor="rgba(59,130,246,0.10)", line_width=0,
                      annotation_text="Oversold", annotation_position="top left", row=1, col=1)
        fig.add_hrect(y0=sell_thr, y1=4, fillcolor="rgba(239,68,68,0.10)",  line_width=0,
                      annotation_text="Overbought", annotation_position="bottom left", row=1, col=1)
        fig.add_hline(y=0,        line_dash="dot",  line_color="#94a3b8", line_width=1,   row=1, col=1)
        fig.add_hline(y=buy_thr,  line_dash="dash", line_color="#3b82f6", line_width=1.2, row=1, col=1)
        fig.add_hline(y=sell_thr, line_dash="dash", line_color="#ef4444", line_width=1.2, row=1, col=1)

        fig.add_trace(go.Scatter(
            x=sig_plot.index, y=sig_plot["fast_z"].round(3),
            mode="lines", name="Fast Z",
            line={"color": "#3b82f6", "width": 2},
            hovertemplate="Fast Z: %{y:.2f}<extra></extra>",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=sig_plot.index, y=sig_plot["signal_line"].round(3),
            mode="lines", name="Signal Line",
            line={"color": "#f59e0b", "width": 1.5, "dash": "dot"},
            hovertemplate="Sig Line: %{y:.2f}<extra></extra>",
        ), row=1, col=1)

        buys  = sig_plot[sig_plot["signal"] == 1]
        sells = sig_plot[sig_plot["signal"] == -1]
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys.index, y=buys["fast_z"].round(3),
                mode="markers", name="BUY",
                marker={"symbol": "triangle-up", "size": 10, "color": "#22c55e", "line": {"width": 1, "color": "#fff"}},
                hovertemplate="BUY · Fast Z: %{y:.2f}<extra></extra>",
            ), row=1, col=1)
        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells.index, y=sells["fast_z"].round(3),
                mode="markers", name="SELL",
                marker={"symbol": "triangle-down", "size": 10, "color": "#ef4444", "line": {"width": 1, "color": "#fff"}},
                hovertemplate="SELL · Fast Z: %{y:.2f}<extra></extra>",
            ), row=1, col=1)

        # ── Row 2: Momentum Histogram ────────────────────────────────────────────────
        if "z_histogram" in sig_plot.columns:
            hist_vals  = sig_plot["z_histogram"].round(3)
            bar_colors = ["#22c55e" if v >= 0 else "#ef4444" for v in hist_vals]
            fig.add_trace(go.Bar(
                x=sig_plot.index, y=hist_vals,
                name="Histogram",
                marker_color=bar_colors,
                opacity=0.75,
                hovertemplate="Histogram: %{y:+.2f}<extra></extra>",
            ), row=2, col=1)
            fig.add_hline(y=0, line_dash="dot", line_color="#94a3b8", line_width=1, row=2, col=1)

        # ── Row 3: Breadth % ────────────────────────────────────────────────────────
        fig.add_hline(y=70, line_dash="dot", line_color="#22c55e", line_width=1, row=3, col=1,
                      annotation_text="Strong 70%", annotation_position="top right")
        fig.add_hline(y=50, line_dash="dot", line_color="#94a3b8", line_width=1, row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#ef4444", line_width=1, row=3, col=1,
                      annotation_text="Weak 30%", annotation_position="bottom right")

        above_21 = breadth_plot.where(breadth_plot >= breadth_ma21)
        below_21 = breadth_plot.where(breadth_plot <  breadth_ma21)
        fig.add_trace(go.Scatter(
            x=above_21.index, y=above_21.round(1),
            mode="lines", name="Breadth (▲ 21D)",
            line={"color": "#22c55e", "width": 1.8},
            fill="tozeroy", fillcolor="rgba(34,197,94,0.08)",
            hovertemplate="Breadth: %{y:.1f}%<extra></extra>",
            connectgaps=False,
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=below_21.index, y=below_21.round(1),
            mode="lines", name="Breadth (▼ 21D)",
            line={"color": "#ef4444", "width": 1.8},
            fill="tozeroy", fillcolor="rgba(239,68,68,0.08)",
            hovertemplate="Breadth: %{y:.1f}%<extra></extra>",
            connectgaps=False,
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=breadth_ma10.index, y=breadth_ma10.round(1),
            mode="lines", name="10D MA",
            line={"color": "#f59e0b", "width": 1.4},
            hovertemplate="10D MA: %{y:.1f}%<extra></extra>",
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=breadth_ma21.index, y=breadth_ma21.round(1),
            mode="lines", name="21D MA",
            line={"color": "#8b5cf6", "width": 1.4, "dash": "dash"},
            hovertemplate="21D MA: %{y:.1f}%<extra></extra>",
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=breadth_ma50.index, y=breadth_ma50.round(1),
            mode="lines", name="50D MA",
            line={"color": "#94a3b8", "width": 1.2, "dash": "dot"},
            hovertemplate="50D MA: %{y:.1f}%<extra></extra>",
        ), row=3, col=1)

        # ── Row 4: Trend Score ───────────────────────────────────────────────────────
        if has_ts:
            ts_plot   = sig_plot["trend_score"]
            ts_colors = ["#22c55e" if v >= 25 else "#ef4444" if v <= -25 else "#fbbf24" for v in ts_plot]
            fig.add_hrect(y0=25,   y1=100,  fillcolor="rgba(34,197,94,0.06)",  line_width=0, row=4, col=1)
            fig.add_hrect(y0=-100, y1=-25,  fillcolor="rgba(239,68,68,0.06)", line_width=0, row=4, col=1)
            fig.add_hline(y=25,  line_dash="dash", line_color="#22c55e", line_width=1, row=4, col=1)
            fig.add_hline(y=0,   line_dash="dot",  line_color="#94a3b8", line_width=1, row=4, col=1)
            fig.add_hline(y=-25, line_dash="dash", line_color="#ef4444", line_width=1, row=4, col=1)
            fig.add_trace(go.Bar(
                x=ts_plot.index, y=ts_plot.round(1),
                name="Trend Score",
                marker_color=ts_colors,
                opacity=0.8,
                hovertemplate="Trend Score: %{y:+.0f}<extra></extra>",
            ), row=4, col=1)

        # ── Shared layout ────────────────────────────────────────────────────────────
        fig.update_layout(
            height=860 if has_ts else 680,
            margin={"l": 4, "r": 4, "t": 24, "b": 8},
            hovermode="x",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            bargap=0.1,
            legend={"orientation": "h", "y": 1.03, "x": 0, "font": {"size": 10}},
        )
        fig.update_yaxes(tickfont={"size": 10}, range=[-4, 4],    row=1, col=1)
        fig.update_yaxes(tickfont={"size": 10},                    row=2, col=1)
        fig.update_yaxes(tickfont={"size": 10}, range=[0, 100],   row=3, col=1)
        if has_ts:
            fig.update_yaxes(tickfont={"size": 10}, range=[-100, 100], row=4, col=1)
        # Spike lines — this is what draws the crosshair across all shared-x panels
        fig.update_xaxes(
            tickfont={"size": 10},
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikecolor="#94a3b8",
            spikethickness=1,
            spikedash="dot",
            showticklabels=False,
        )
        # Show date labels only on the bottom panel
        fig.update_xaxes(showticklabels=True, row=n_rows, col=1)
        st.plotly_chart(fig, width='stretch')


        # ── Parameter Optimizer ────────────────────────────────────────────────────
        with st.expander("⚙️ Parameter Optimizer — find best thresholds for PSX history"):
            st.caption(
                "Searches over lookback, smoothing, and threshold combinations. "
                "Scores each set by how well it captures the PSX turning points defined below."
            )

            col_ev1, col_ev2 = st.columns(2)
            with col_ev1:
                st.markdown("**Known market bottoms** (BUY events)")
                bottoms_raw = st.text_area(
                    "One date per line (YYYY-MM-DD)",
                    value="\n".join(PSX_KNOWN_BOTTOMS),
                    height=100,
                    key="opt_bottoms",
                )
            with col_ev2:
                st.markdown("**Known market tops** (SELL events)")
                tops_raw = st.text_area(
                    "One date per line (YYYY-MM-DD)",
                    value="\n".join(PSX_KNOWN_TOPS),
                    height=100,
                    key="opt_tops",
                )

            opt_window = st.slider(
                "Event window ± days (signal counts if it fires within this window of the event)",
                15, 90, 45, key="opt_window",
            )

            st.markdown("**Grid search ranges** (comma-separated values)")
            gc1, gc2 = st.columns(2)
            with gc1:
                lookback_str = st.text_input("z_lookback",       "126, 189, 252", key="opt_lb")
                fast_str     = st.text_input("fast_smoothing",   "3, 5, 8",       key="opt_fs")
            with gc2:
                sig_str      = st.text_input("signal_smoothing", "8, 10, 13",     key="opt_ss")

            if st.button("▶ Run Optimizer", type="primary", key="run_opt"):
                def _parse(s):
                    return [float(x.strip()) for x in s.split(",") if x.strip()]
                def _parse_dates(s):
                    return [d.strip() for d in s.strip().splitlines() if d.strip()]

                bottom_dates = _parse_dates(bottoms_raw)
                top_dates    = _parse_dates(tops_raw)

                grid = {
                    "ma_period":        [50],
                    "z_lookback":       [int(x) for x in _parse(lookback_str)],
                    "fast_smoothing":   [int(x) for x in _parse(fast_str)],
                    "signal_smoothing": [int(x) for x in _parse(sig_str)],
                }

                n_combos = 1
                for v in grid.values():
                    n_combos *= len(v)

                with st.spinner(f"Testing {n_combos} parameter combinations…"):
                    try:
                        best_params, results_df = run_optimizer(
                            breadth, signals["index_close"],
                            bottom_dates=bottom_dates,
                            top_dates=top_dates,
                            param_grid=grid,
                            window_days=opt_window,
                        )
                        st.session_state["weinstein_opt_results"] = results_df
                        st.session_state["weinstein_best_params"] = best_params
                        st.success(
                            f"Best score: **{results_df.iloc[0]['score']:.2f}** &nbsp;·&nbsp; "
                            f"z_lookback={best_params['z_lookback']} &nbsp; "
                            f"fast_smoothing={best_params['fast_smoothing']} &nbsp; "
                            f"signal_smoothing={best_params['signal_smoothing']}",
                            icon="✅",
                        )
                    except Exception as exc:
                        st.error(f"Optimizer error: {exc}")

            # Show results if available
            if "weinstein_opt_results" in st.session_state:
                st.markdown("**Top 10 parameter combinations**")
                res = st.session_state["weinstein_opt_results"].head(10)
                st.dataframe(res, width='stretch', hide_index=True)

                best_p = st.session_state.get("weinstein_best_params", {})
                if best_p and st.button("Apply best parameters & refresh signals", key="apply_best"):
                    full_params = {**PSX_DEFAULTS, **best_p}
                    st.session_state["weinstein_params"] = full_params
                    st.cache_data.clear()
                    st.rerun()

        # ── How to read this ───────────────────────────────────────────────────────
        with st.expander("📖 How to read the Weinstein Regime indicator"):
            st.markdown("""
    **What it measures**

    Every trading day, Kiran counts how many PSX stocks close *above* their 50-day moving average.
    That percentage becomes the **breadth series** — the pulse of the whole market.

    **Why Z-score it?**

    A raw 64% means nothing without history. The Z-score answers: *"Is today's breadth historically high or low?"*
    If the past year averaged 55% with σ = 8, then 64% → Z ≈ +1.1 — moderately elevated.

    **MACD-style signal system (EMA-based)**

    The system works exactly like a MACD applied to breadth Z-scores:

    | Line | Calculation | Purpose |
    |---|---|---|
    | **Fast Z** (blue) | EMA-5 of raw z-score | Reacts quickly to breadth changes |
    | **Signal Line** (orange) | EMA-13 of Fast Z | Slower trend reference |
    | **Histogram** (green/red bars) | Fast Z − Signal Line | **The key momentum indicator** |

    - **Green histogram bars** → breadth momentum is rising (market inclining)
    - **Red histogram bars** → breadth momentum is falling (market declining)
    - Histogram crossing **zero from below** = BUY signal
    - Histogram crossing **zero from above** = SELL signal

    **Zone definitions**
    | Zone | Fast Z range | Meaning |
    |---|---|---|
    | Oversold | < −1.5 | Breadth historically depressed — watch for BUY |
    | Bearish | −1.5 to −0.5 | Below-average breadth, market under pressure |
    | Neutral | −0.5 to +0.5 | Normal conditions, no edge |
    | Bullish | +0.5 to +1.8 | Above-average breadth, favour longs |
    | Overbought | > +1.8 | Breadth stretched — watch for SELL |

    **Signal logic**
    | Signal | Trigger |
    |---|---|
    | **BUY** | Histogram crosses zero upward **AND** KSE-100 is above its 50-day MA |
    | **SELL** | Histogram crosses zero downward |

    **Trend Score (−100 to +100)**

    Composite decline/incline score built from four components:
    - **Z level** (40 pts): where Fast Z sits in the −3 to +3 range
    - **Z slope** (30 pts): how fast Fast Z is rising or falling over 5 bars
    - **Index vs MA** (20 pts): KSE-100 above (+20) or below (−20) its 50-day MA
    - **Breadth ROC** (10 pts): 5-day % change in raw breadth

    Score > +25 = **Incline** (green) · Score < −25 = **Decline** (red) · In between = transitional

    **Breadth chart MAs**
    - **10D MA** (amber) — short-term breadth trend
    - **21D MA** (purple dashed) — medium-term; line colour (green/red) shows if breadth is above or below it
    - **50D MA** (grey dotted) — long-term breadth baseline; a sustained cross here signals regime change

    **PSX calibration**
    - Known bottom: Jan 2024 · Known tops: Jan 2025 (stall), Jan 2026

    Use the **Parameter Optimizer** to run a grid search and find the EMA spans that best captured these PSX turning points in your data.
        """)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — SETUP PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[10]:  # Setup Perf (updated index)
    st.markdown("**Setup Performance** — lifecycle and P&L of every system-generated setup")

    all_setups_raw = get_trade_setups()
    if not all_setups_raw:
        st.info("No setups recorded yet. Run a data update to generate setups.")
        st.stop()

    sp = pd.DataFrame(all_setups_raw)

    # Normalise columns that may be missing in older rows
    for col in ["actual_pl_pct", "actual_pl_pkr", "actual_rr", "holding_days",
                "exit_date", "actual_entry", "quality_score", "breadth_score",
                "sector_rank", "range_window", "source"]:
        if col not in sp.columns:
            sp[col] = None
    sp["source"] = sp["source"].fillna("System")
    sp["quality_score"] = pd.to_numeric(sp["quality_score"], errors="coerce").fillna(0).astype(int)

    # Calculate execution type
    sp["execution_type"] = sp.apply(
        lambda row: "Actual" if row.get("source") == "Actual"
        else "Paper & Actual" if row.get("actual_entry") is not None and row.get("actual_entry") > 0
        else "Paper",
        axis=1
    )

    # Source selector — lets auditors filter by screener
    _sp_sources = ["System", "STM", "Support Reversal", "Minervini"]
    _sp_src_sel = st.multiselect(
        "📊 Screener source",
        _sp_sources,
        default=["System"],
        key="sp_src_sel"
    )
    sys_sp = sp[sp["source"].isin(_sp_src_sel)].copy() if _sp_src_sel else sp[sp["source"] == "System"].copy()

    if sys_sp.empty:
        st.info("No system-generated setups found.")
        st.stop()

    sys_sp["created_date"] = pd.to_datetime(sys_sp["created_date"])

    # ── Build current-price map from latest stock_30d data ────────────────────
    cur_price: dict[str, float] = {}
    if not stock_30d.empty and "latest_close" in stock_30d.columns:
        cur_price = dict(zip(stock_30d["symbol"], stock_30d["latest_close"]))

    # ── Status buckets ────────────────────────────────────────────────────────
    pending = sys_sp[sys_sp["status"] == "Pending"]
    active  = sys_sp[sys_sp["status"] == "Active"]
    closed  = sys_sp[sys_sp["status"].isin(["Closed", "Expired", "Win", "Loss",
                                             "Breakeven"])].copy()
    # Also capture rows where outcome is set (some workflows set outcome directly)
    also_closed = sys_sp[
        sys_sp["outcome"].isin(["Win", "Loss", "Breakeven"]) &
        ~sys_sp["status"].isin(["Pending", "Active"])
    ].copy()
    closed = pd.concat([closed, also_closed]).drop_duplicates(subset="id")

    # Filter to only show actually traded setups (Paper & Actual)
    traded = sys_sp[sys_sp["execution_type"] == "Paper & Actual"].copy()

    wins   = traded[traded["outcome"] == "Win"]
    losses = traded[traded["outcome"] == "Loss"]

    n_total   = len(sys_sp)
    n_pending = len(pending)
    n_active  = len(active)
    n_closed  = len(closed)
    n_traded  = len(traded)
    n_wins    = len(wins)
    n_losses  = len(losses)
    win_rate  = n_wins / max(n_wins + n_losses, 1) * 100

    avg_win_pct  = wins["actual_pl_pct"].dropna().mean()   if n_wins   else 0.0
    avg_loss_pct = losses["actual_pl_pct"].dropna().mean() if n_losses else 0.0
    avg_rr = (abs(avg_win_pct / avg_loss_pct)
              if avg_loss_pct and avg_loss_pct != 0 else 0.0)

    # ── KPI row ───────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    k1.metric("Total Generated", n_total)
    k2.metric("Pending", n_pending)
    k3.metric("Active", n_active)
    k4.metric("Closed", n_closed)
    k5.metric("Win Rate", f"{win_rate:.0f}%" if n_closed else "—",
              delta=f"{n_wins}W / {n_losses}L")
    k6.metric("Avg Win", f"{avg_win_pct:+.1f}%" if n_wins else "—")
    k7.metric("Avg R:R", f"{avg_rr:.2f}x" if avg_rr else "—")

    st.divider()

    # ── Active positions: unrealised P&L ─────────────────────────────────────
    st.markdown("##### Active Positions — Unrealised P&L")

    if active.empty:
        st.caption("No active positions right now.")
    else:
        act_rows = []
        for _, r in active.iterrows():
            sym      = r["symbol"]
            entry    = float(r.get("actual_entry") or r["entry_price"])
            t1       = float(r["target_1r"])
            t2       = float(r["target_2r"])
            sl       = float(r["stop_loss"])
            cur_p    = cur_price.get(sym, None)
            direction = r["direction"]

            if cur_p and entry > 0:
                if direction == "LONG":
                    unreal_pct = (cur_p - entry) / entry * 100
                else:
                    unreal_pct = (entry - cur_p) / entry * 100
                dist_t1 = (t1 - cur_p) / cur_p * 100 if direction == "LONG" else (cur_p - t1) / cur_p * 100
                dist_t2 = (t2 - cur_p) / cur_p * 100 if direction == "LONG" else (cur_p - t2) / cur_p * 100
                dist_sl = (cur_p - sl) / cur_p * 100 if direction == "LONG" else (sl - cur_p) / cur_p * 100
            else:
                unreal_pct = dist_t1 = dist_t2 = dist_sl = None

            act_rows.append({
                "Symbol":      sym,
                "Dir":         direction,
                "Sector":      r["sector"],
                "Entry":       round(entry, 2),
                "Current":     round(cur_p, 2) if cur_p else "—",
                "Unreal %":    round(unreal_pct, 1) if unreal_pct is not None else "—",
                "→T1 %":       f"{dist_t1:+.1f}%" if dist_t1 is not None else "—",
                "→T2 %":       f"{dist_t2:+.1f}%" if dist_t2 is not None else "—",
                "SL gap %":    f"{dist_sl:+.1f}%" if dist_sl is not None else "—",
                "Quality":     int(r["quality_score"]),
                "Opened":      r["created_date"].strftime("%d %b"),
            })

        act_df = pd.DataFrame(act_rows)

        def _colour_unreal(val):
            if isinstance(val, (int, float)):
                c = "#22c55e" if val >= 0 else "#ef4444"
                return f"color:{c}; font-weight:700"
            return ""

        st.dataframe(
            act_df.style.map(_colour_unreal, subset=["Unreal %"]),
            width='stretch', hide_index=True,
        )

    st.divider()

    # ── Two-column block: closed journal + outcome donut ─────────────────────
    col_tbl, col_chart = st.columns([2, 1])

    with col_tbl:
        st.markdown("##### Closed Setups Journal")
        if closed.empty:
            st.caption("No closed setups yet.")
        else:
            disp = closed[["created_date", "symbol", "direction", "sector",
                           "outcome", "actual_pl_pct", "actual_rr",
                           "holding_days", "quality_score"]].copy()
            disp["created_date"] = disp["created_date"].dt.strftime("%d %b %Y")
            disp.columns = ["Date", "Symbol", "Dir", "Sector",
                            "Outcome", "P&L %", "R:R",
                            "Days", "Quality"]
            disp["P&L %"] = pd.to_numeric(disp["P&L %"], errors="coerce").round(1)
            disp["R:R"]   = pd.to_numeric(disp["R:R"],   errors="coerce").round(2)

            def _outcome_colour(val):
                c = {"Win": "#22c55e", "Loss": "#ef4444", "Breakeven": "#f59e0b"}
                return f"color:{c.get(val,'#94a3b8')}; font-weight:700"

            st.dataframe(
                disp.style
                    .map(_outcome_colour, subset=["Outcome"])
                    .map(lambda v: f"color:{'#22c55e' if isinstance(v,(int,float)) and v>=0 else '#ef4444'}" if isinstance(v,(int,float)) else "", subset=["P&L %"]),
                width='stretch', hide_index=True,
            )

    with col_chart:
        st.markdown("##### Outcome Breakdown")
        if n_closed == 0:
            st.caption("No closed setups yet.")
        else:
            outcome_counts = closed["outcome"].value_counts()
            colours = {"Win": "#22c55e", "Loss": "#ef4444",
                       "Breakeven": "#f59e0b", "Expired": "#94a3b8"}
            fig_d = go.Figure(go.Pie(
                labels=outcome_counts.index.tolist(),
                values=outcome_counts.values.tolist(),
                hole=0.55,
                marker_colors=[colours.get(o, "#94a3b8") for o in outcome_counts.index],
                textinfo="label+percent",
                textfont_size=11,
            ))
            fig_d.update_layout(
                height=220,
                margin={"l": 0, "r": 0, "t": 8, "b": 8},
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_d, width='stretch')

            if n_wins > 0 and n_losses > 0:
                st.markdown(
                    f"<div style='text-align:center;font-size:0.8rem;color:#64748b;'>"
                    f"Avg win <b style='color:#22c55e'>{avg_win_pct:+.1f}%</b> &nbsp;·&nbsp; "
                    f"Avg loss <b style='color:#ef4444'>{avg_loss_pct:+.1f}%</b><br>"
                    f"Expectancy R:R <b>{avg_rr:.2f}x</b></div>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── Sector performance heatmap ────────────────────────────────────────────
    col_sec, col_qs = st.columns(2)

    with col_sec:
        st.markdown("##### Win Rate by Sector")
        if closed.empty or "sector" not in closed.columns:
            st.caption("No data yet.")
        else:
            sec_grp = closed.groupby("sector").agg(
                Setups=("id", "count"),
                Wins=("outcome", lambda x: (x == "Win").sum()),
            ).reset_index()
            sec_grp["Win Rate %"] = (sec_grp["Wins"] / sec_grp["Setups"] * 100).round(1)
            sec_grp = sec_grp[sec_grp["Setups"] >= 1].sort_values("Win Rate %", ascending=True)

            if sec_grp.empty:
                st.caption("No data yet.")
            else:
                fig_s = go.Figure(go.Bar(
                    x=sec_grp["Win Rate %"],
                    y=sec_grp["sector"],
                    orientation="h",
                    marker_color=[
                        "#22c55e" if v >= 55 else "#fbbf24" if v >= 40 else "#ef4444"
                        for v in sec_grp["Win Rate %"]
                    ],
                    text=sec_grp.apply(
                        lambda r: f"{r['Win Rate %']:.0f}% ({r['Wins']}/{r['Setups']})", axis=1
                    ),
                    textposition="outside",
                    textfont={"size": 9},
                ))
                fig_s.update_layout(
                    height=max(180, len(sec_grp) * 28),
                    margin={"l": 4, "r": 60, "t": 8, "b": 8},
                    xaxis={"ticksuffix": "%", "range": [0, 115]},
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_s, width='stretch')

    with col_qs:
        st.markdown("##### Quality Score vs Win Rate")
        if closed.empty:
            st.caption("No data yet.")
        else:
            qs_grp = closed.groupby("quality_score").agg(
                Setups=("id", "count"),
                Wins=("outcome", lambda x: (x == "Win").sum()),
            ).reset_index()
            qs_grp["Win Rate %"] = (qs_grp["Wins"] / qs_grp["Setups"] * 100).round(1)
            qs_grp["quality_score"] = qs_grp["quality_score"].astype(str)

            if qs_grp.empty:
                st.caption("No data yet.")
            else:
                fig_q = go.Figure(go.Bar(
                    x=qs_grp["quality_score"],
                    y=qs_grp["Win Rate %"],
                    marker_color=[
                        "#22c55e" if v >= 55 else "#fbbf24" if v >= 40 else "#ef4444"
                        for v in qs_grp["Win Rate %"]
                    ],
                    text=[f"{v:.0f}%<br>({n} setups)" for v, n in
                          zip(qs_grp["Win Rate %"], qs_grp["Setups"])],
                    textposition="outside",
                    textfont={"size": 9},
                ))
                fig_q.update_layout(
                    height=280,
                    margin={"l": 4, "r": 4, "t": 8, "b": 8},
                    xaxis={"title": "Quality Score (0–4)"},
                    yaxis={"ticksuffix": "%", "range": [0, 115]},
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_q, width='stretch')
                st.caption("Higher quality score should trend toward higher win rate as data accumulates.")

    st.divider()

    # ── Monthly generation volume ──────────────────────────────────────────────
    st.markdown("##### Setup Generation Volume (by month & direction)")
    if sys_sp.empty:
        st.caption("No data.")
    else:
        sys_sp["month"] = sys_sp["created_date"].dt.to_period("M").astype(str)
        monthly = sys_sp.groupby(["month", "direction"]).size().reset_index(name="count")
        if not monthly.empty:
            fig_m = px.bar(
                monthly, x="month", y="count", color="direction",
                color_discrete_map={"LONG": "#22c55e", "SHORT": "#ef4444"},
                text="count",
                labels={"month": "", "count": "Setups", "direction": ""},
            )
            fig_m.update_traces(textposition="outside", textfont_size=9)
            fig_m.update_layout(
                height=240,
                margin={"l": 4, "r": 4, "t": 8, "b": 8},
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend={"orientation": "h", "y": 1.1},
                barmode="stack",
            )
            st.plotly_chart(fig_m, width='stretch')

    # ── Pending setups summary ────────────────────────────────────────────────
    if not pending.empty:
        with st.expander(f"🕐 Pending Setups ({len(pending)}) — waiting for entry trigger"):
            pend_disp = pending[["created_date", "symbol", "direction", "sector",
                                 "entry_price", "stop_loss", "target_1r",
                                 "risk_pct", "quality_score"]].copy()
            pend_disp["created_date"] = pend_disp["created_date"].dt.strftime("%d %b %Y")
            pend_disp.columns = ["Date", "Symbol", "Dir", "Sector",
                                  "Entry", "SL", "T1", "Risk %", "Quality"]
            st.dataframe(pend_disp, width='stretch', hide_index=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # STM SCREENER — KIRAN SETUP CROSS-REFERENCE
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("##### 🔎 STM Screener — Kiran Setup Cross-Reference")
    st.caption(
        "STM results with a column showing whether Kiran independently has an open setup. "
        "Both screeners work on their own logic — this is purely informational."
    )

    with st.spinner("Running STM screener…"):
        _w = load_weinstein_data()
        _stm = _run_stm_screener(data, _w)

    # ── STM gate status (compact pills) ──────────────────────────────────────
    def _mini_pill(label, passed):
        col  = "#22c55e" if passed else "#ef4444"
        icon = "✔" if passed else "✖"
        return (
            f'<span style="background:{"#f0fdf4" if passed else "#fff5f5"};'
            f'border:1px solid {col}55;border-radius:20px;padding:3px 10px;'
            f'font-size:0.7rem;color:{col};font-weight:700;margin-right:6px;">'
            f'{icon} {label}</span>'
        )

    pills_html = "".join(_mini_pill(lbl, ok) for lbl, ok, _ in _stm["gates"])
    st.markdown(
        f'<div style="margin-bottom:10px;">STM gates: {pills_html}</div>',
        unsafe_allow_html=True,
    )

    if not _stm["all_pass"]:
        st.info("STM market gates are not all active — cross-reference will show when conditions are met.")
    else:
        stm_result = _stm["result"]

        if stm_result.empty:
            st.info("STM screener returned no stocks under current conditions.")
        else:
            # Build Kiran open LONG symbol set
            kiran_open = pd.concat([pending, active], ignore_index=True) \
                if (not pending.empty or not active.empty) else pd.DataFrame()
            kiran_long = kiran_open[kiran_open["direction"] == "LONG"] \
                if not kiran_open.empty else pd.DataFrame()
            kiran_syms = set(kiran_long["symbol"].tolist()) if not kiran_long.empty else set()

            # STM result with Kiran flag
            xref = stm_result.reset_index()[[
                "symbol", "sector", "as_of_date", "latest_close",
                "rs", "perf_30d", "range_5d_pct", "dist_21ma_pct", "avg_vol_10d",
            ]].copy()
            xref["kiran_setup"] = xref["symbol"].apply(
                lambda s: "✔ Has setup" if s in kiran_syms else "— No setup"
            )
            xref["avg_vol_10d"] = (xref["avg_vol_10d"] / 1_000).round(0).astype(int)
            xref["as_of_date"]  = pd.to_datetime(xref["as_of_date"]).dt.strftime("%d %b %Y")
            xref = xref.sort_values("rs", ascending=False).reset_index(drop=True)
            xref.index = xref.index + 1

            n_with    = (xref["kiran_setup"] == "✔ Has setup").sum()
            n_without = (xref["kiran_setup"] == "— No setup").sum()

            xm1, xm2, xm3 = st.columns(3)
            xm1.metric("STM stocks",          len(xref))
            xm2.metric("Kiran also has setup", n_with)
            xm3.metric("No Kiran setup",       n_without)

            xref.columns = [
                "Symbol", "Sector", "As Of", "Close",
                "RS %", "30d %", "5d Range %", "Dist 21MA %", "Vol 10d (K)",
                "Kiran Setup",
            ]

            def _kiran_col(s):
                return [
                    "color:#22c55e;font-weight:700" if v == "✔ Has setup"
                    else "color:#94a3b8"
                    for v in s
                ]

            st.dataframe(
                xref.style
                    .apply(_kiran_col, subset=["Kiran Setup"])
                    .apply(lambda s: ["color:#22c55e;font-weight:bold" if v > 0
                                      else "color:#ef4444;font-weight:bold" for v in s],
                           subset=["RS %", "30d %"])
                    .format({
                        "Close": "{:.2f}", "RS %": "{:+.2f}", "30d %": "{:+.2f}",
                        "5d Range %": "{:.2f}", "Dist 21MA %": "{:+.2f}",
                    }),
                width='stretch', hide_index=False,
                height=min(600, 60 + len(xref) * 36),
            )
            st.caption(
                "Kiran Setup column shows whether Kiran independently generated an open LONG setup "
                "for that stock. '— No setup' simply means Kiran hasn't flagged it — "
                "both screeners operate on their own criteria."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 10 — STM  (Short-Term Momentum Screener)
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[8]:  # STM

    st.markdown("### 🔎 STM — Short-Term Momentum Screener")
    st.caption(
        "Three-layer filter: market regime → top sectors → individual stock conditions. "
        "Ranked by Relative Strength vs KSE-100."
    )

    w_data_stm = load_weinstein_data()

    with st.spinner("Running STM screener…"):
        stm = _run_stm_screener(data, w_data_stm)

    def _gate_card(label, passed, detail=""):
        col  = "#22c55e" if passed else "#ef4444"
        bg   = "#f0fdf4" if passed else "#fff5f5"
        icon = "PASS" if passed else "FAIL"
        det  = (f'<div style="font-size:0.62rem;color:#64748b;margin-top:2px;">{detail}</div>'
                if detail else "")
        return (
            f'<div style="background:{bg};border:1px solid {col}33;border-top:3px solid {col};'
            f'border-radius:8px;padding:10px 14px;text-align:center;">'
            f'<div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:3px;">{label}</div>'
            f'<div style="font-size:1.05rem;font-weight:800;color:{col};">{icon}</div>'
            f'{det}</div>'
        )

    # ── Direction tabs ────────────────────────────────────────────────────────
    _long_label  = f"{'[ACTIVE] ' if stm['all_pass'] else ''}LONG"
    _short_label = f"{'[ACTIVE] ' if stm['short_all_pass'] else ''}SHORT"
    _tab_long, _tab_short = st.tabs([f"📈 {_long_label}", f"📉 {_short_label}"])

    # ════════════════ LONG TAB ════════════════════════════════════════════════
    with _tab_long:
        st.markdown("**Market Filters — LONG**")
        fc1, fc2, fc3 = st.columns(3)
        for col_w, (label, passed, detail) in zip([fc1, fc2, fc3], stm["gates"]):
            col_w.markdown(_gate_card(label, passed, detail), unsafe_allow_html=True)

        if not stm["all_pass"]:
            st.divider()
            st.info("LONG gates not active — screener will show candidates when all 3 conditions are met.")
        else:
            st.divider()
            result  = stm["result"]
            kse_30d = stm["kse_30d"]
            n_passed = len(result)

            # Auto-save LONG picks
            _stm_key = f"stm_saved_{id(result)}"
            if not st.session_state.get(_stm_key) and not result.empty:
                picks = []
                for _, row in result.iterrows():
                    date_str = str(row["as_of_date"])[:10]
                    pick = {
                        "created_date": date_str, "direction": "LONG",
                        "symbol": row["symbol"], "sector": row["sector"],
                        "sector_momentum": "—",
                        "stock_perf_30d": float(row["perf_30d"]),
                        "stock_perf_10d": float(row.get("perf_10d", 0.0)),
                        "latest_close":   float(row["latest_close"]),
                        "entry_price":    float(row["latest_close"]),
                        "stop_loss":      float(row["stop_loss"]),
                        "target_1r":      float(row["target_1r"]),
                        "target_2r":      float(row["target_2r"]),
                        "risk_pct":       float(row["risk_pct"]),
                        "atr_pct":        float(row.get("atr_pct", 0.0)),
                        "sector_rank":    int(row.get("sector_rank", 99)),
                        "breadth_score":  float(row.get("breadth_score", 0.0)),
                        "source": "STM",
                        "status": "Pending" if row["tradeable"] else "Cancelled",
                        "notes": "" if row["tradeable"] else f"Skipped: risk {row['risk_pct']:.1f}% > 6%",
                    }
                    picks.append(pick)
                auto_save_stm_picks(picks)
                st.session_state[_stm_key] = True

            # ── Enrich with S/R zone context ──────────────────────────────
            if not result.empty:
                with st.spinner("Analysing S/R zones…"):
                    result = enrich_stm_with_sr_zones(result, load_stm_prices())

            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("KSE-100 30d",       f"{kse_30d:+.1f}%")
            sm2.metric("Passed Filters",     f"{n_passed}")
            sm3.metric("Best RS",            f"{result['rs'].iloc[0]:+.1f}%" if n_passed else "—")
            sm4.metric("Avg RS",             f"{result['rs'].mean():+.1f}%"  if n_passed else "—")
            st.divider()

            if result.empty:
                st.info("No stocks passed all LONG filters under current conditions.")
            else:
                n_tradeable = int(result["tradeable"].sum())
                st.markdown(
                    f"**{n_passed} stocks passed** — {n_tradeable} tradeable (risk ≤ 6%) · "
                    f"ranked by RS vs KSE-100"
                )
                ml_scores = []; qual_scores = []
                for _, row in result.iterrows():
                    ml_row = {
                        "avg_vol_10d": row.get("avg_vol_10d", 0), "atr_pct": row.get("atr_pct", 0.0),
                        "stock_perf_30d": row.get("perf_30d", 0.0), "risk_pct": row.get("risk_pct", 0.0),
                        "stock_perf_10d": row.get("perf_10d", 0.0), "sector_rank": row.get("sector_rank", 99),
                        "breadth_score": row.get("breadth_score", 0.0), "as_of_date": str(row.get("as_of_date", "")),
                        "entry_price": row.get("latest_close", 0.0), "latest_close": row.get("latest_close", 0.0),
                    }
                    prob = get_ml_confidence(ml_row)
                    ml_scores.append(int(round(prob * 100)) if prob is not None else None)
                    qs = int(
                        (row.get("rs", 0.0) > 5.0)
                      + (row.get("range_5d_pct", 99.) <= 5.0)
                      + (0 < row.get("dist_21ma_pct", 99.) <= 5.0)
                      + (row.get("risk_pct", 99.) <= 3.0)
                      + bool(row.get("coiling", False))   # 5th pt: coiling at resistance
                    )
                    qual_scores.append(qs)

                _has_sr = "dist_to_r_pct" in result.columns
                _sr_src_cols  = ["dist_to_r_pct", "r_zone_strength", "in_r_zone"] if _has_sr else []
                _sr_disp_cols = ["Dist R%", "R Str", "In Zone"]                   if _has_sr else []

                disp = result[[
                    "symbol", "sector", "as_of_date", "latest_close",
                    "rs", "perf_30d", "range_5d_pct", "avg_vol_10d",
                    "ma21", "ma50", "dist_21ma_pct",
                    "stop_loss", "risk_pct", "target_2r", "tradeable",
                ] + _sr_src_cols].copy()
                disp["avg_vol_10d"] = (disp["avg_vol_10d"] / 1_000).round(0).astype(int)
                disp["as_of_date"]  = pd.to_datetime(disp["as_of_date"]).dt.strftime("%d %b %Y")
                disp["Score"] = qual_scores; disp["ML %"] = ml_scores
                disp["tradeable"] = disp["tradeable"].map({True: "Valid", False: "Skip"})
                if _has_sr:
                    disp["in_r_zone"] = disp["in_r_zone"].map({True: "YES", False: "—"})
                # Column order in disp: 15 base cols → 3 SR cols (if any) → Score → ML%
                # Rename must match that exact order
                disp.columns = (
                    ["Symbol","Sector","As Of","Close","RS %","30d %","5d Rng %",
                     "Vol(K)","21MA","50MA","Dist21MA%","SL","Risk%","T2R","Trade"]
                    + _sr_disp_cols
                    + ["Score","ML%"]
                )

                def _srs(s):  return ["color:#22c55e;font-weight:bold" if v>0 else "color:#ef4444;font-weight:bold" for v in s]
                def _srng(s): return ["color:#22c55e" if v<=5 else "color:#fbbf24" if v<=8 else "color:#94a3b8" for v in s]
                def _sdist(s):return ["color:#22c55e;font-weight:bold" if 0<v<=5 else "color:#fbbf24" if 0<v<=10 else "color:#94a3b8" for v in s]
                def _strd(s): return ["color:#22c55e;font-weight:700" if v=="Valid" else "color:#ef4444" for v in s]
                def _srsk(s): return ["color:#22c55e" if v<=3 else "color:#fbbf24" if v<=6 else "color:#ef4444" for v in s]
                def _sscr(s): return ["color:#16a34a;font-weight:700" if v>=3 else "color:#b45309;font-weight:700" if v==2 else "color:#94a3b8" for v in s]
                def _sml(s):  return ["color:#16a34a;font-weight:700" if (v is not None and v>=65) else "color:#b45309;font-weight:700" if (v is not None and v>=50) else "color:#dc2626" if v is not None else "color:#94a3b8" for v in s]

                st.caption("**Score 0-5:** 4-5 best · 3 good · 2 borderline · 0-1 weak  (5th pt = Coiling at resistance)")
                _fmt = {"Close":"{:.2f}","RS %":"{:+.2f}","30d %":"{:+.2f}",
                        "5d Rng %":"{:.2f}","21MA":"{:.2f}","50MA":"{:.2f}",
                        "Dist21MA%":"{:+.2f}","SL":"{:.2f}","Risk%":"{:.2f}","T2R":"{:.2f}"}
                if _has_sr:
                    _fmt["Dist R%"] = "{:.2f}"
                    _fmt["R Str"]   = "{:.0f}"
                st.dataframe(
                    disp.style
                        .apply(_srs,  subset=["RS %","30d %"]).apply(_srng, subset=["5d Rng %"])
                        .apply(_sdist,subset=["Dist21MA%"]).apply(_strd, subset=["Trade"])
                        .apply(_srsk, subset=["Risk%"]).apply(_sscr, subset=["Score"])
                        .apply(_sml,  subset=["ML%"])
                        .format(_fmt, na_rep="—"),
                    width='stretch', hide_index=False,
                    height=min(640, 60 + n_passed * 36),
                )
                st.caption(
                    "SL = 1% below day low · T2R = 2R target · ML% = LightGBM win probability · "
                    "Dist R% = % to nearest resistance zone floor · R Str = zone strength 0-100 · "
                    "In Zone = price inside resistance zone · Picks auto-saved to Trade Log"
                )

                # ── Coiling highlight ──────────────────────────────────────
                if _has_sr:
                    coil_rows = result[result["coiling"] == True]
                    if not coil_rows.empty:
                        st.divider()
                        st.markdown("#### 🔥 Coiling at Resistance")
                        st.caption(
                            "Tight 5-day range building within 5% of a confirmed resistance zone. "
                            "Watch for volume expansion as the trigger."
                        )
                        for _, r in coil_rows.iterrows():
                            in_z    = "🔴 Inside zone" if r.get("in_r_zone") else f"{r.get('dist_to_r_pct', 0):.1f}% below"
                            r_str   = r.get('r_zone_strength')
                            r_str_s = f"{r_str:.0f}" if r_str is not None else "—"
                            st.markdown(
                                f"**{r['symbol']}** &nbsp;·&nbsp; "
                                f"Close: {r['latest_close']:.2f} &nbsp;·&nbsp; "
                                f"RS: {r['rs']:+.1f}% &nbsp;·&nbsp; "
                                f"Zone: {in_z} &nbsp;·&nbsp; "
                                f"Zone Str: {r_str_s} &nbsp;·&nbsp; "
                                f"5d Rng: {r['range_5d_pct']:.1f}% &nbsp;·&nbsp; "
                                f"Risk: {r['risk_pct']:.1f}%"
                            )

    # ════════════════ SHORT TAB ═══════════════════════════════════════════════
    with _tab_short:
        st.markdown("**Market Filters — SHORT**")
        sc1, sc2, sc3 = st.columns(3)
        for col_w, (label, passed, detail) in zip([sc1, sc2, sc3], stm["short_gates"]):
            col_w.markdown(_gate_card(label, passed, detail), unsafe_allow_html=True)

        if not stm["short_all_pass"]:
            st.divider()
            st.info("SHORT gates not active — screener will show candidates when all 3 bearish conditions are met.")
        else:
            st.divider()
            st.divider()
            short_result = stm["short_result"]
            kse_30d_sh   = stm["kse_30d"]
            n_short      = len(short_result)

            # Auto-save SHORT picks
            _short_key = f"stm_short_saved_{id(short_result)}"
            if not st.session_state.get(_short_key) and not short_result.empty:
                short_picks = []
                for _, row in short_result.iterrows():
                    date_str = str(row["as_of_date"])[:10]
                    pick = {
                        "created_date": date_str, "direction": "SHORT",
                        "symbol": row["symbol"], "sector": row["sector"],
                        "sector_momentum": "—",
                        "stock_perf_30d": float(row["perf_30d"]),
                        "stock_perf_10d": float(row.get("perf_10d", 0.0)),
                        "latest_close":   float(row["latest_close"]),
                        "entry_price":    float(row["latest_close"]),
                        "stop_loss":      float(row["stop_loss"]),
                        "target_1r":      float(row["target_1r"]),
                        "target_2r":      float(row["target_2r"]),
                        "risk_pct":       float(row["risk_pct"]),
                        "atr_pct":        float(row.get("atr_pct", 0.0)),
                        "sector_rank":    int(row.get("sector_rank", 99)),
                        "breadth_score":  float(row.get("breadth_score", 0.0)),
                        "source": "STM",
                        "status": "Pending" if row["tradeable"] else "Cancelled",
                        "notes": "" if row["tradeable"] else f"Skipped: risk {row['risk_pct']:.1f}% > 6%",
                    }
                    short_picks.append(pick)
                auto_save_stm_picks(short_picks)
                st.session_state[_short_key] = True

            sh1, sh2, sh3, sh4 = st.columns(4)
            sh1.metric("KSE-100 30d",     f"{kse_30d_sh:+.1f}%")
            sh2.metric("Passed Filters",  f"{n_short}")
            sh3.metric("Worst RS",        f"{short_result['rs_short'].iloc[0]:+.1f}%" if n_short else "—")
            sh4.metric("Avg RS Under",    f"{short_result['rs_short'].mean():+.1f}%"  if n_short else "—")
            st.divider()

            if short_result.empty:
                st.info("No stocks passed all SHORT filters under current conditions.")
            else:
                n_sh_trade = int(short_result["tradeable"].sum())
                st.markdown(
                    f"**{n_short} stocks passed** — {n_sh_trade} tradeable (risk ≤ 6%) · "
                    f"ranked by underperformance vs KSE-100 (worst first)"
                )

                sh_disp = short_result[[
                    "symbol", "sector", "as_of_date", "latest_close",
                    "rs_short", "perf_30d", "range_5d_pct", "avg_vol_10d",
                    "ma21", "ma50", "dist_21ma_pct",
                    "stop_loss", "risk_pct", "target_2r", "tradeable",
                ]].copy()
                sh_disp["avg_vol_10d"] = (sh_disp["avg_vol_10d"] / 1_000).round(0).astype(int)
                sh_disp["as_of_date"]  = pd.to_datetime(sh_disp["as_of_date"]).dt.strftime("%d %b %Y")
                sh_disp["tradeable"]   = sh_disp["tradeable"].map({True: "Valid", False: "Skip"})

                # Short quality score (mirror of LONG)
                sh_qual = []
                for _, row in short_result.iterrows():
                    qs = int(
                        (row.get("rs_short", 0.0) > 5.0)           # underperforming by >5%
                      + (row.get("range_5d_pct", 99.) <= 5.0)      # tight consolidation
                      + (-5.0 <= row.get("dist_21ma_pct", 0.) < 0) # close below 21MA (not too extended)
                      + (row.get("risk_pct", 99.) <= 3.0)           # tight SL
                    )
                    sh_qual.append(qs)
                sh_disp["Score"] = sh_qual

                sh_disp.columns = ["Symbol","Sector","As Of","Close","Under-RS%","30d %","5d Rng %",
                                   "Vol(K)","21MA","50MA","Dist21MA%","SL","Risk%","T2R","Trade","Score"]

                def _srs_sh(s): return ["color:#ef4444;font-weight:bold" if v>0 else "color:#94a3b8" for v in s]
                def _s30_sh(s): return ["color:#ef4444;font-weight:bold" if v<0 else "color:#94a3b8" for v in s]
                def _sdist_sh(s): return ["color:#ef4444;font-weight:bold" if -5<=v<0 else "color:#fbbf24" if -10<=v<0 else "color:#94a3b8" for v in s]

                st.dataframe(
                    sh_disp.style
                        .apply(_srs_sh, subset=["Under-RS%"])
                        .apply(_s30_sh, subset=["30d %"])
                        .apply(_sdist_sh, subset=["Dist21MA%"])
                        .apply(lambda s: ["color:#22c55e;font-weight:700" if v=="Valid" else "color:#ef4444" for v in s], subset=["Trade"])
                        .apply(lambda s: ["color:#16a34a;font-weight:700" if v>=3 else "color:#b45309;font-weight:700" if v==2 else "color:#94a3b8" for v in s], subset=["Score"])
                        .format({"Close":"{:.2f}","Under-RS%":"{:+.2f}","30d %":"{:+.2f}",
                                 "5d Rng %":"{:.2f}","21MA":"{:.2f}","50MA":"{:.2f}",
                                 "Dist21MA%":"{:+.2f}","SL":"{:.2f}","Risk%":"{:.2f}","T2R":"{:.2f}"}, na_rep="—"),
                    width='stretch', hide_index=False,
                    height=min(640, 60 + n_short * 36),
                )
                st.caption(
                    "**Under-RS%** = how much stock underperforms KSE-100 (higher = weaker) · "
                    "**SL** = 1% above day high · **T2R** = 2R target (downside) · "
                    "**Dist21MA%** = negative = below 21MA · Picks auto-saved to Trade Log as SHORT"
                )

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — 🔄 Recovery Bases
# ══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[9]:  # Recovery Bases

    @st.cache_data(ttl=3600, show_spinner=False)
    def _run_recovery_screener():
        """
        Post-capitulation VCP screener.
        Decline ≥30% → tight base (backward scan) → volume contraction → breakout trigger.
        Returns (watchlist_df, triggered_df, kse_regime_ok).
        """
        import numpy as np
        from database import get_sector_price_data, get_index_prices
        from config import EXCLUDED_SECTORS

        # ── Load price data ───────────────────────────────────────────────────
        raw = get_sector_price_data()
        if not raw:
            return pd.DataFrame(), pd.DataFrame(), True

        all_df = pd.DataFrame(raw)
        all_df["date"] = pd.to_datetime(all_df["date"])
        for col in ("open", "high", "low", "close"):
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")
        all_df["volume"] = pd.to_numeric(all_df["volume"], errors="coerce").fillna(0)

        # Keep last ~420 calendar days — enough for vol_ma50 + 90-day pre-base window
        cutoff = all_df["date"].max() - pd.Timedelta(days=420)
        all_df = all_df[all_df["date"] >= cutoff]
        all_df = all_df.sort_values(["symbol", "date"]).reset_index(drop=True)

        # ── KSE-100 regime: latest close vs 10 trading days ago ───────────────
        kse_regime_ok = True
        try:
            kse_rows = get_index_prices("KSE-100")
            if kse_rows:
                kse_df = pd.DataFrame(kse_rows)
                kse_df["date"]  = pd.to_datetime(kse_df["date"])
                kse_df["close"] = pd.to_numeric(kse_df["close"], errors="coerce")
                kse_df = kse_df.sort_values("date")
                if len(kse_df) >= 12:
                    kse_regime_ok = float(kse_df["close"].iloc[-1]) >= float(kse_df["close"].iloc[-11])
        except Exception:
            pass

        # ── Sector + derivative filters ───────────────────────────────────────
        all_df = all_df[~all_df["sector"].isin(EXCLUDED_SECTORS)]
        all_df = all_df[~all_df["symbol"].str.match(r"^P\d", na=False)]
        all_df = all_df[all_df["close"] >= 5.0]

        # ── Trading date universe ─────────────────────────────────────────────
        all_dates  = sorted(all_df["date"].unique())
        if not all_dates:
            return pd.DataFrame(), pd.DataFrame(), kse_regime_ok
        latest_date  = all_dates[-1]
        last_5_dates = set(all_dates[-5:]) if len(all_dates) >= 5 else set(all_dates)
        today_dt     = pd.Timestamp(latest_date).date()

        # ── Backward-scan helper ──────────────────────────────────────────────
        def _base_scan(c, from_idx, thr=0.20, max_lb=90):
            """Extend window backward while range stays < thr. Returns base_start_idx."""
            hi = lo = c[from_idx]
            start = from_idx
            for i in range(from_idx - 1, max(from_idx - max_lb, 0) - 1, -1):
                nh = max(hi, c[i])
                nl = min(lo, c[i])
                if (nh - nl) / nl >= thr:
                    break
                hi, lo, start = nh, nl, i
            return start

        watchlist_rows = []
        triggered_rows = []
        triggered_syms = set()

        for sym, grp in all_df.groupby("symbol", sort=False):
            grp = grp.reset_index(drop=True)
            n   = len(grp)
            if n < 60:
                continue

            closes  = grp["close"].values.astype(float)
            opens   = grp["open"].values.astype(float)
            highs   = grp["high"].values.astype(float)
            lows    = grp["low"].values.astype(float)
            volumes = grp["volume"].values.astype(float)
            dates   = grp["date"].values
            sector  = grp["sector"].iloc[0]

            # ── Liquidity filter: avg vol last 20d > 800K ─────────────────────
            avg_vol_20d = volumes[-20:].mean() if n >= 20 else volumes.mean()
            if avg_vol_20d < 800_000:
                continue

            # ── vol_ma50 (min 30 periods so early bars still get a value) ─────
            vol_s    = pd.Series(volumes)
            vol_ma50 = vol_s.rolling(50, min_periods=30).mean().values
            if np.isnan(vol_ma50[-1]) or vol_ma50[-1] <= 0:
                continue

            # ══════════════════════════════════════════════════════════════════
            # TRIGGERED CHECK — last 5 trading days
            # For each candidate trigger day T, compute the base as of T-1,
            # then verify trigger conditions on day T.
            # ══════════════════════════════════════════════════════════════════
            trigger_hit = None
            for t in range(max(1, n - 5), n):
                if dates[t] not in last_5_dates:
                    continue
                prev = t - 1
                if prev < 15:
                    continue

                # Base as of the day before the trigger
                bs     = _base_scan(closes, prev)
                b_days = prev - bs + 1
                if b_days < 8:
                    continue

                b_closes = closes[bs : prev + 1]
                b_high   = b_closes.max()
                b_low    = b_closes.min()
                b_range  = (b_high - b_low) / b_low
                if b_range >= 0.20:
                    continue

                # Pre-base drawdown: 90-bar high before base start
                pre      = closes[max(0, bs - 90) : bs]
                if len(pre) < 5:
                    continue
                pre_high = pre.max()
                drawdown = (pre_high - closes[bs]) / pre_high
                if drawdown < 0.30:
                    continue

                # Volume contraction: last 5 bars of base
                bv   = volumes[bs : prev + 1]
                bm50 = vol_ma50[bs : prev + 1]
                l5v  = bv[-5:]
                l5m  = bm50[-5:]
                ok   = l5m > 0
                if ok.sum() < 3:
                    continue
                l5r = np.where(ok, l5v / np.where(l5m > 0, l5m, 1.0), 1.0)
                if not (l5r[ok].mean() < 0.50 and (l5r[ok] < 0.60).sum() >= 3):
                    continue

                # Occasional buy activity in base (≥2 days vol_ratio > 1.5)
                all_br = np.where(bm50 > 0, bv / bm50, 0.0)
                if (all_br > 1.5).sum() < 2:
                    continue

                # Trigger conditions on day T
                if vol_ma50[t] <= 0:
                    continue
                vr     = volumes[t] / vol_ma50[t]
                day_rng = highs[t] - lows[t]
                if not (
                    vr >= 2.5
                    and closes[t] > b_high
                    and closes[t] > opens[t]
                    and day_rng > 0
                    and (closes[t] - lows[t]) / day_rng >= 0.40
                ):
                    continue

                trigger_hit = dict(
                    t_date       = pd.Timestamp(dates[t]).date(),
                    t_close      = round(closes[t], 2),
                    t_vol_ratio  = round(vr, 2),
                    b_days       = b_days,
                    b_range_pct  = round(b_range * 100, 1),
                    drawdown_pct = round(drawdown * 100, 1),
                    pre_high     = round(pre_high, 2),
                    current      = round(closes[-1], 2),
                )
                break  # most recent trigger only

            if trigger_hit:
                triggered_rows.append(dict(
                    symbol         = sym,
                    sector         = sector,
                    triggered_date = trigger_hit["t_date"],
                    fresh          = trigger_hit["t_date"] == today_dt,
                    trigger_close  = trigger_hit["t_close"],
                    trigger_vol_x  = trigger_hit["t_vol_ratio"],
                    current_close  = trigger_hit["current"],
                    move_pct       = round(
                        (trigger_hit["current"] - trigger_hit["t_close"])
                        / trigger_hit["t_close"] * 100, 1
                    ),
                    drawdown_pct   = trigger_hit["drawdown_pct"],
                    base_days      = trigger_hit["b_days"],
                    base_range_pct = trigger_hit["b_range_pct"],
                    avg_vol_m      = round(avg_vol_20d / 1e6, 2),
                ))
                triggered_syms.add(sym)
                continue  # don't also add to watchlist

            # ══════════════════════════════════════════════════════════════════
            # WATCHLIST CHECK — current base (as of today)
            # ══════════════════════════════════════════════════════════════════
            bs     = _base_scan(closes, n - 1)
            b_days = n - bs
            if b_days < 8:
                continue

            b_closes = closes[bs:]
            b_high   = b_closes.max()
            b_low    = b_closes.min()
            b_range  = (b_high - b_low) / b_low
            if b_range >= 0.20:
                continue

            pre      = closes[max(0, bs - 90) : bs]
            if len(pre) < 5:
                continue
            pre_high = pre.max()
            drawdown = (pre_high - closes[bs]) / pre_high
            if drawdown < 0.30:
                continue

            # Volume contraction: last 5 bars overall
            l5v  = volumes[-5:]
            l5m  = vol_ma50[-5:]
            ok   = l5m > 0
            if ok.sum() < 3:
                continue
            l5r = np.where(ok, l5v / np.where(l5m > 0, l5m, 1.0), 1.0)
            if not (l5r[ok].mean() < 0.50 and (l5r[ok] < 0.60).sum() >= 3):
                continue

            # Occasional activity in base
            bv   = volumes[bs:]
            bm50 = vol_ma50[bs:]
            all_br = np.where(bm50 > 0, bv / bm50, 0.0)
            if (all_br > 1.5).sum() < 2:
                continue

            cur_vr = volumes[-1] / vol_ma50[-1] if vol_ma50[-1] > 0 else 0.0

            watchlist_rows.append(dict(
                symbol          = sym,
                sector          = sector,
                close           = round(closes[-1], 2),
                drawdown_pct    = round(drawdown * 100, 1),
                base_days       = b_days,
                base_range_pct  = round(b_range * 100, 1),
                vol_ratio_today = round(cur_vr, 2),
                base_high       = round(b_high, 2),
                dist_pct        = round((b_high - closes[-1]) / closes[-1] * 100, 1),
                avg_vol_m       = round(avg_vol_20d / 1e6, 2),
            ))

        watchlist_df = pd.DataFrame(watchlist_rows)
        triggered_df = pd.DataFrame(triggered_rows)

        if len(watchlist_df) > 0:
            watchlist_df = watchlist_df.sort_values("base_range_pct").reset_index(drop=True)
        if len(triggered_df) > 0:
            triggered_df = triggered_df.sort_values(
                ["fresh", "triggered_date"], ascending=[False, False]
            ).reset_index(drop=True)

        return watchlist_df, triggered_df, kse_regime_ok

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown("### 🔄 Recovery Bases")
    st.caption(
        "Post-capitulation VCP screener — stocks that declined ≥30%, formed a tight base "
        "with volume drying up, then broke out on a surge. "
        "**Watchlist** = currently basing, volume contracting. "
        "**Triggered** = breakout fired in last 5 trading days."
    )

    # ── Run screener ──────────────────────────────────────────────────────────
    with st.spinner("Running Recovery Bases screener…"):
        _wl, _tr, _regime_ok = _run_recovery_screener()

    # ── Regime warning banner ─────────────────────────────────────────────────
    if not _regime_ok:
        st.warning(
            "⚠️ **KSE-100 is below its close 10 trading days ago.** "
            "Recovery breakouts carry higher failure risk in a declining market. "
            "Reduce position size or wait for a second confirmation candle.",
        )

    # ── Refresh button ────────────────────────────────────────────────────────
    _hcol, _bcol = st.columns([7, 1])
    with _bcol:
        if st.button("⚡ Refresh", key="rb_refresh"):
            _run_recovery_screener.clear()
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TRIGGERED SETUPS
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🔥 Triggered — Last 5 Trading Days")

    if len(_tr) == 0:
        st.info("No breakouts in the last 5 trading days matching all criteria.")
    else:
        _tc1, _tc2, _tc3 = st.columns(3)
        _tc1.metric("Triggers", len(_tr))
        _fresh_n = int(_tr["fresh"].sum()) if "fresh" in _tr.columns else 0
        _tc2.metric("Fresh Today", _fresh_n)
        if "move_pct" in _tr.columns and len(_tr) > 0:
            _tc3.metric("Avg Move Since Trigger", f"{_tr['move_pct'].mean():+.1f}%")

        _tr_disp = _tr.copy()

        def _fmt_trigger_date(row):
            d = str(row["triggered_date"])
            return f"🟢 {d}  FRESH" if row["fresh"] else d

        _tr_disp["Triggered"]    = _tr_disp.apply(_fmt_trigger_date, axis=1)
        _tr_disp["Move"]         = _tr_disp["move_pct"].apply(lambda v: f"{v:+.1f}%")
        _tr_disp["Vol@Trigger"]  = _tr_disp["trigger_vol_x"].apply(lambda v: f"{v:.1f}×")
        _tr_disp["Decline"]      = _tr_disp["drawdown_pct"].apply(lambda v: f"{v:.0f}%")
        _tr_disp["Base Range"]   = _tr_disp["base_range_pct"].apply(lambda v: f"{v:.1f}%")
        _tr_disp["Avg Vol (M)"]  = _tr_disp["avg_vol_m"]

        _tr_cols = {
            "symbol":        "Symbol",
            "sector":        "Sector",
            "Triggered":     "Triggered",
            "trigger_close": "Entry Close",
            "Vol@Trigger":   "Vol × ma50",
            "current_close": "Current",
            "Move":          "Move",
            "Decline":       "Prior Decline",
            "base_days":     "Base Days",
            "Base Range":    "Base Range",
            "Avg Vol (M)":   "Avg Vol (M)",
        }
        _tr_out = _tr_disp[
            [c for c in _tr_cols if c in _tr_disp.columns]
        ].rename(columns=_tr_cols)

        def _style_tr(df):
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            for col, test in [("Move", lambda v: float(str(v).replace("%","").replace("+",""))),
                               ("Triggered", None)]:
                if col not in df.columns:
                    continue
                ci = df.columns.get_loc(col)
                for i, v in enumerate(df[col]):
                    if col == "Move":
                        try:
                            val = test(v)
                            s.iloc[i, ci] = "color:#22c55e;font-weight:bold" if val > 0 else "color:#ef4444"
                        except Exception:
                            pass
                    elif col == "Triggered" and "FRESH" in str(v):
                        s.iloc[i, ci] = "color:#22c55e;font-weight:bold"
            return s

        _tr_fmt = {c: "{:.2f}" for c in ["Entry Close", "Current", "Avg Vol (M)"] if c in _tr_out.columns}
        st.dataframe(
            _tr_out.style.apply(_style_tr, axis=None).format(_tr_fmt),
            use_container_width=True,
            hide_index=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # WATCHLIST — BASING NOW
    # ══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("#### 👁️ Basing Now — Watchlist")
    st.caption("Volume contracting. Sorted by tightest base range (most coiled first). Watch for a vol surge above Trigger Level.")

    if len(_wl) == 0:
        st.info("No stocks currently in a qualifying base with volume contraction.")
    else:
        _wc1, _wc2, _wc3 = st.columns(3)
        _wc1.metric("Candidates", len(_wl))
        if "base_range_pct" in _wl.columns:
            _wc2.metric("Tightest Base", f"{_wl['base_range_pct'].min():.1f}%")
        if "base_days" in _wl.columns:
            _wc3.metric("Avg Base Duration", f"{_wl['base_days'].mean():.0f}d")

        _wl_disp = _wl.copy()
        _wl_disp["Decline"]      = _wl_disp["drawdown_pct"].apply(lambda v: f"{v:.0f}%")
        _wl_disp["Base Range"]   = _wl_disp["base_range_pct"].apply(lambda v: f"{v:.1f}%")
        _wl_disp["Vol Today"]    = _wl_disp["vol_ratio_today"].apply(lambda v: f"{v:.2f}×")
        _wl_disp["Dist Trigger"] = _wl_disp["dist_pct"].apply(lambda v: f"{v:.1f}%")
        _wl_disp["Avg Vol (M)"]  = _wl_disp["avg_vol_m"]

        _wl_cols = {
            "symbol":        "Symbol",
            "sector":        "Sector",
            "close":         "Close",
            "Decline":       "Prior Decline",
            "base_days":     "Base Days",
            "Base Range":    "Base Range",
            "Vol Today":     "Vol Today",
            "base_high":     "Trigger Level",
            "Dist Trigger":  "Dist to Trigger",
            "Avg Vol (M)":   "Avg Vol (M)",
        }
        _wl_out = _wl_disp[
            [c for c in _wl_cols if c in _wl_disp.columns]
        ].rename(columns=_wl_cols)

        def _style_wl(df):
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            for col, thresholds in [
                ("Vol Today",  [(0.30, "color:#22c55e;font-weight:bold"), (0.50, "color:#86efac")]),
                ("Base Range", [(8.0,  "color:#22c55e;font-weight:bold"), (13.0, "color:#86efac")]),
            ]:
                if col not in df.columns:
                    continue
                ci = df.columns.get_loc(col)
                for i, v in enumerate(df[col]):
                    try:
                        val = float(str(v).replace("×", "").replace("%", ""))
                        for threshold, style in thresholds:
                            if val < threshold:
                                s.iloc[i, ci] = style
                                break
                    except Exception:
                        pass
            return s

        _wl_fmt = {c: "{:.2f}" for c in ["Close", "Trigger Level", "Avg Vol (M)"] if c in _wl_out.columns}
        st.dataframe(
            _wl_out.style.apply(_style_wl, axis=None).format(_wl_fmt),
            use_container_width=True,
            hide_index=True,
        )

    # ── Screener parameters footnote ─────────────────────────────────────────
    st.divider()
    st.caption(
        "**Parameters:** Decline ≥30% from pre-base high · Base 8–90 bars · Range <20% · "
        "Volume baseline: vol_ma50 · Contraction: last-5d avg <0.50× ma50, ≥3 days <0.60× · "
        "Trigger: vol ≥2.5× + close > base high + green candle + close in upper 40% of range · "
        "Liquidity: 20d avg vol >800K · Min price ₨5 · "
        "Regime: KSE-100 close vs 10 days ago"
    )

# ── MODEL HEALTH PAGE ─────────────────────────────────────────────────────────
elif cur == PAGES[13]:  # Model Health (updated index)
    import os as _os
    import subprocess as _sp
    import traceback as _tb

    st.markdown("### 🏥 Model Health Dashboard")
    st.caption("Live accuracy tracking for both ML models. Refresh daily after logging predictions.")

    try:
        from part5_model_health import generate_health_report
        report = generate_health_report()
        st.code(report, language=None)
    except ImportError:
        st.info("📌 Model Health Report: Available on local development only (part5_model_health module)")
    except Exception as _e:
        st.error(f"Could not generate report: {_e}")
        st.code(_tb.format_exc())

    st.divider()

    # ── Prediction log summary ────────────────────────────────────────────────
    _pred_log_path = _os.path.join(_MODEL_DIR, "prediction_log.csv")
    if _os.path.exists(_pred_log_path):
        log_df    = pd.read_csv(_pred_log_path)
        evaluated = log_df.dropna(subset=["was_correct"])

        st.markdown("#### Prediction Log")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total logged", len(log_df))
        col2.metric("Evaluated",    len(evaluated))
        if len(evaluated) > 0:
            col3.metric("Overall accuracy", f"{evaluated['was_correct'].mean():.1%}")

        if len(evaluated) >= 5:
            st.markdown("**Recent predictions**")
            show_cols = [c for c in ["log_date", "symbol", "prediction", "ml_probability", "was_correct", "actual_return"] if c in log_df.columns]
            recent = log_df[show_cols].tail(30).sort_index(ascending=False).copy()
            if "ml_probability" in recent.columns:
                recent["ml_probability"] = pd.to_numeric(recent["ml_probability"], errors="coerce").map(lambda x: f"{x:.0%}" if pd.notna(x) else "—")
            if "actual_return" in recent.columns:
                recent["actual_return"]  = pd.to_numeric(recent["actual_return"],  errors="coerce").map(lambda x: f"{x:+.2%}" if pd.notna(x) else "—")
            if "was_correct" in recent.columns:
                recent["was_correct"]    = recent["was_correct"].map(lambda x: "✔" if x == 1 else ("✖" if x == 0 else "—"))
            st.dataframe(recent, width='stretch', hide_index=True)
    else:
        st.info("No prediction log yet. Use the buttons below to start logging predictions.")

    st.divider()
    st.markdown("**Quick actions**")
    c1, c2, c3 = st.columns(3)
    _py = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "python.exe") if False else __import__("sys").executable
    if c1.button("Log today's predictions"):
        r = _sp.run([_py, _os.path.join(_MODEL_DIR, "part7_prediction_log.py"), "log-today"],
                    capture_output=True, text=True)
        st.code(r.stdout or r.stderr)
    if c2.button("Update outcomes"):
        r = _sp.run([_py, _os.path.join(_MODEL_DIR, "part7_prediction_log.py"), "update-outcomes"],
                    capture_output=True, text=True)
        st.code(r.stdout or r.stderr)
    if c3.button("Force retrain now"):
        _retrain_script = _os.path.join(_MODEL_DIR, "part4_monthly_retrain.py")
        if not _os.path.exists(_retrain_script):
            st.warning("part4_monthly_retrain.py not found — local-only script, not deployed. Run `retrain.bat` on your local machine instead.")
        else:
            r = _sp.run([_py, _retrain_script, "--force"],
                        capture_output=True, text=True, timeout=300)
            st.code(r.stdout or r.stderr)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 11 — 🗂️ Portfolio  (Weinstein Stage 2 Portfolio Screener)
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == PAGES[12]:
    st.markdown("### 🗂️ Stage 2 Portfolio")
    st.caption(
        "Stocks in Weinstein Stage 2 (price above rising 30-week MA) ranked by "
        "Relative Strength vs KSE-100, sector strength, and stage clarity. "
        "Hold until weekly close breaks below the 30-week MA."
    )

    from portfolio import compute_portfolio_candidates

    @st.cache_data(ttl=1800, show_spinner=False)
    def _load_portfolio():
        return compute_portfolio_candidates(sector_df=sector_df)

    with st.spinner("Computing stage analysis…"):
        port_df = _load_portfolio()

    if port_df.empty:
        st.warning("Insufficient price history to compute stage analysis. Need at least 170 trading days per symbol.")
        st.stop()

    # ── Summary KPIs ─────────────────────────────────────────────────────────
    n_stage2 = len(port_df[port_df["stage"] == 2])
    n_stage1 = len(port_df[port_df["stage"] == 1])
    n_stage3 = len(port_df[port_df["stage"] == 3])
    n_stage4 = len(port_df[port_df["stage"] == 4])
    n_total  = len(port_df)
    pct_stage2 = n_stage2 / n_total * 100 if n_total else 0

    _kc1, _kc2, _kc3, _kc4, _kc5 = st.columns(5)
    _kc1.markdown(kpi("Total Stocks", str(n_total), "with sufficient history", BLUE), unsafe_allow_html=True)
    _kc2.markdown(kpi("Stage 2 (Advancing)", str(n_stage2), f"{pct_stage2:.0f}% of universe", "#22c55e"), unsafe_allow_html=True)
    _kc3.markdown(kpi("Stage 1 (Basing)", str(n_stage1), "potential early entries", "#f59e0b"), unsafe_allow_html=True)
    _kc4.markdown(kpi("Stage 3 (Topping)", str(n_stage3), "consider exiting", "#f97316"), unsafe_allow_html=True)
    _kc5.markdown(kpi("Stage 4 (Declining)", str(n_stage4), "avoid", "#ef4444"), unsafe_allow_html=True)

    st.divider()

    # ── Stage filter tabs ─────────────────────────────────────────────────────
    _tab2, _tab1, _tab3, _tab_all = st.tabs([
        f"🟢 Stage 2 Portfolio ({n_stage2})",
        f"👀 Stage 1 Watchlist ({n_stage1})",
        f"⚠️ Stage 3 Exit Alerts ({n_stage3})",
        f"📋 All Stocks ({n_total})",
    ])

    def _render_table(df_view: pd.DataFrame, show_cols: list, col_labels: dict = None):
        if df_view.empty:
            st.info("No stocks in this category.")
            return
        display = df_view[show_cols].copy()
        if col_labels:
            display = display.rename(columns=col_labels)

        # Colour-code numeric columns
        def _style(styler):
            for c in ["RS 30d", "RS 10d", "Dist from 30w%"]:
                if c in styler.columns:
                    styler = styler.map(
                        lambda v: "color:#22c55e;font-weight:bold" if isinstance(v, (int, float)) and v > 0
                        else ("color:#ef4444;font-weight:bold" if isinstance(v, (int, float)) and v < 0 else ""),
                        subset=[c],
                    )
            return styler

        st.dataframe(
            display.style.apply(lambda _: [""] * len(display), axis=0).pipe(_style),
            width='stretch',
            hide_index=True,
        )

    # Stage 2 tab — the portfolio
    with _tab2:
        s2 = port_df[port_df["stage"] == 2].copy()

        st.markdown(
            "**Portfolio candidates** — Stage 2 stocks ranked by composite score. "
            "Top 8–12 (with 1% risk sizing) form the core portfolio. "
            "**Hold until weekly close < 30-week MA.**"
        )

        # Top 12 highlighted
        top12 = s2.head(12)
        if not top12.empty:
            st.markdown("##### 🏆 Top 12 Portfolio Candidates")
            cols_s2 = ["rank", "symbol", "sector", "latest_close", "ma30w",
                       "dist_from_30w_pct", "rs_30d", "rs_10d", "rs_trend",
                       "sector_rank", "sector_momentum", "composite_score", "recommendation"]
            labels  = {
                "rank": "#", "latest_close": "Price", "ma30w": "30w MA",
                "dist_from_30w_pct": "Dist 30w%", "rs_30d": "RS 30d",
                "rs_10d": "RS 10d", "rs_trend": "RS Trend",
                "sector_rank": "Sec Rank", "sector_momentum": "Sec Momentum",
                "composite_score": "Score", "recommendation": "Action",
            }
            _render_table(top12, cols_s2, labels)

        if len(s2) > 12:
            with st.expander(f"Show remaining {len(s2) - 12} Stage 2 stocks"):
                _render_table(s2.iloc[12:], cols_s2, labels)

        st.divider()

        # RS distribution of Stage 2 stocks
        st.markdown("##### RS Distribution — Stage 2 Universe")
        import plotly.graph_objects as go

        fig_rs = go.Figure()
        fig_rs.add_trace(go.Histogram(
            x=s2["rs_30d"],
            nbinsx=30,
            marker_color="#3b82f6",
            opacity=0.8,
            name="RS vs KSE-100 (30d)",
        ))
        fig_rs.add_vline(x=0, line_dash="dash", line_color="#ef4444", annotation_text="Index baseline")
        fig_rs.update_layout(
            height=280,
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis_title="RS vs KSE-100 (30d %)",
            yaxis_title="# Stocks",
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_rs, width='stretch')

    # Stage 1 watchlist
    with _tab1:
        s1 = port_df[port_df["stage"] == 1].copy()
        st.markdown(
            "**Basing stocks** — price consolidating near the 30-week MA. "
            "These become portfolio candidates if/when the 30w MA turns up and price breaks above it."
        )
        cols_s1 = ["rank", "symbol", "sector", "latest_close", "ma30w",
                   "dist_from_30w_pct", "rs_30d", "rs_10d",
                   "sector_rank", "sector_momentum", "composite_score", "recommendation"]
        _render_table(s1, cols_s1, {
            "rank": "#", "latest_close": "Price", "ma30w": "30w MA",
            "dist_from_30w_pct": "Dist 30w%", "rs_30d": "RS 30d", "rs_10d": "RS 10d",
            "sector_rank": "Sec Rank", "sector_momentum": "Sec Momentum",
            "composite_score": "Score", "recommendation": "Action",
        })

    # Stage 3 exit alerts
    with _tab3:
        s3 = port_df[port_df["stage"] == 3].copy()
        st.markdown(
            "**Topping / rolling over** — price still above 30w MA but MA is flattening or turning down. "
            "If any of these are in your portfolio, monitor for a weekly close below the 30w MA as the exit trigger."
        )
        cols_s3 = ["rank", "symbol", "sector", "latest_close", "ma30w",
                   "dist_from_30w_pct", "rs_30d", "stage_label",
                   "sector_rank", "recommendation"]
        _render_table(s3, cols_s3, {
            "rank": "#", "latest_close": "Price", "ma30w": "30w MA",
            "dist_from_30w_pct": "Dist 30w%", "rs_30d": "RS 30d",
            "stage_label": "Stage Detail", "sector_rank": "Sec Rank",
            "recommendation": "Action",
        })

    # All stocks tab
    with _tab_all:
        all_cols = ["rank", "symbol", "sector", "latest_close", "ma30w",
                    "dist_from_30w_pct", "stage", "stage_label",
                    "rs_30d", "rs_10d", "sector_rank", "composite_score", "recommendation"]

        # Stage filter
        stage_filter = st.selectbox(
            "Filter by stage",
            ["All", "Stage 2", "Stage 1", "Stage 3", "Stage 4"],
            key="port_stage_filter",
        )
        fmap = {"All": [1,2,3,4], "Stage 2": [2], "Stage 1": [1], "Stage 3": [3], "Stage 4": [4]}
        view = port_df[port_df["stage"].isin(fmap[stage_filter])]

        _render_table(view, all_cols, {
            "rank": "#", "latest_close": "Price", "ma30w": "30w MA",
            "dist_from_30w_pct": "Dist 30w%", "stage_label": "Stage Detail",
            "rs_30d": "RS 30d", "rs_10d": "RS 10d",
            "sector_rank": "Sec Rank", "composite_score": "Score",
            "recommendation": "Action",
        })

    st.divider()
    st.caption(
        "**How to use:** Open a position in a Stage 2 stock using the 1% risk rule "
        "(SL = 30-week MA or recent support). Hold with no action until a weekly close "
        "below the 30-week MA. Review weekly only. "
        "Page auto-refreshes every 30 minutes with the latest prices."
    )

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — 🤖 Agent   (Claude Trading Desk Agent)
# ══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[14]:  # Agent
    import subprocess as _agent_sp
    import sys as _agent_sys

    st.markdown("### 🤖 Claude Trading Desk Agent")
    st.caption(
        "AI-powered daily market analysis. The agent runs every morning, "
        "analyses your trade history + today's market, and generates screened opportunities."
    )

    # ── Try importing agent_db ────────────────────────────────────────────────
    try:
        import agent_db as _adb
        _adb.init_agent_tables()
        _adb_ok = True
    except Exception as _adb_err:
        _adb_ok = False
        st.error(f"agent_db import failed: {_adb_err}")

    if _adb_ok:
        # ── Top-bar: run buttons + status ─────────────────────────────────────
        _ac1, _ac2, _ac3, _ac4, _ac5 = st.columns([2, 1, 1, 1, 1])
        with _ac1:
            _latest_log = _adb.get_learning_log(limit=1)
            if _latest_log:
                _ll = _latest_log[0]
                _ago = _ll.get("run_date", "?")
                st.success(f"✅ Last run: **{_ago}** · {_ll.get('opportunities_generated',0)} opps · "
                           f"{_ll.get('run_duration_sec','?')}s")
            else:
                st.info("ℹ️ Agent has not run yet. Click **Run Now** to start.")

        with _ac2:
            if st.button("▶ Run Agent Now", type="primary", use_container_width=True):
                with st.spinner("Running agent… (30–60 seconds)"):
                    try:
                        _r = _agent_sp.run(
                            [_agent_sys.executable, "agent.py", "--type", "daily"],
                            capture_output=True, text=True, timeout=180,
                            cwd=_os.path.dirname(_os.path.abspath(__file__)),
                        )
                        if _r.returncode == 0:
                            st.success("Agent run complete!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Agent run failed.")
                            st.code(_r.stderr[-2000:] if _r.stderr else _r.stdout[-2000:])
                    except Exception as _re:
                        st.error(f"Failed to launch agent: {_re}")

        with _ac3:
            if st.button("📅 Weekly Run", use_container_width=True):
                with st.spinner("Running weekly analysis…"):
                    try:
                        _r = _agent_sp.run(
                            [_agent_sys.executable, "agent.py", "--type", "weekly"],
                            capture_output=True, text=True, timeout=300,
                            cwd=_os.path.dirname(_os.path.abspath(__file__)),
                        )
                        if _r.returncode == 0:
                            st.success("Weekly analysis complete!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Weekly run failed.")
                            st.code(_r.stderr[-1500:])
                    except Exception as _re:
                        st.error(f"Failed: {_re}")

        with _ac4:
            if st.button("🧠 Learn Now", use_container_width=True, help="Grade past suggestions and update pattern stats"):
                with st.spinner("Grading opportunities and writing learning summary…"):
                    try:
                        from agent_learn import run_learning_loop as _rll
                        _learn_result = _rll()
                        st.success(
                            f"Done — graded {_learn_result['graded']} opps, "
                            f"updated {_learn_result['patterns_updated']} patterns."
                        )
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as _rll_err:
                        st.error(f"Learning loop error: {_rll_err}")

        with _ac5:
            _perf = _adb.get_agent_performance_summary()
            if _perf:
                _pc1, _pc2, _pc3 = st.columns(3)
                _pc1.metric("Agent Win Rate", f"{_perf.get('win_rate','—')}%" if _perf.get('win_rate') else "—")
                _pc2.metric("Avg P&L", f"{_perf.get('avg_pl','—')}%" if _perf.get('avg_pl') else "—")
                _pc3.metric("Pending", str(_perf.get('pending', 0)))

        st.divider()

        # ── Ask the Agent — Chat Interface ────────────────────────────────────
        st.markdown("#### 💬 Ask the Agent")
        st.caption(
            "Ask anything — regime explanations, your performance stats, psychology, "
            "setup questions. The agent reads your live data before answering."
        )

        # Initialise session chat history + stable session ID for logging
        if "agent_chat_history" not in st.session_state:
            st.session_state.agent_chat_history = []
        if "agent_session_id" not in st.session_state:
            import uuid as _uuid
            st.session_state.agent_session_id = str(_uuid.uuid4())[:8]

        # Render existing messages
        for _msg in st.session_state.agent_chat_history:
            with st.chat_message(_msg["role"]):
                st.markdown(_msg["content"])

        # Chat input
        _chat_input = st.chat_input(
            "Ask the agent… e.g. 'Why is the market ranging?' / 'How is my win rate?' / 'I'm in a losing streak — what should I do?'"
        )
        if _chat_input:
            # Show user message immediately
            with st.chat_message("user"):
                st.markdown(_chat_input)
            st.session_state.agent_chat_history.append({"role": "user", "content": _chat_input})

            # Get agent response
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    try:
                        from agent import chat_with_agent as _chat_fn
                        _reply = _chat_fn(
                            user_message=_chat_input,
                            conversation_history=st.session_state.agent_chat_history[:-1],
                            session_id=st.session_state.agent_session_id,
                        )
                    except Exception as _chat_err:
                        _reply = f"⚠️ Chat failed: {_chat_err}"
                st.markdown(_reply)
            st.session_state.agent_chat_history.append({"role": "assistant", "content": _reply})

        # Clear chat button
        if st.session_state.agent_chat_history:
            if st.button("🗑️ Clear chat", key="clear_agent_chat"):
                st.session_state.agent_chat_history = []
                st.rerun()

        st.divider()

        # ── Regime Playbook Banner ────────────────────────────────────────────
        _latest_daily = _adb.get_latest_agent_report(report_type="daily")
        if _latest_daily and _latest_daily.get("raw_json"):
            try:
                _rj = json.loads(_latest_daily["raw_json"])
                _reg = _rj.get("regime", {})
                _reg_label  = _reg.get("regime", "")
                _reg_sub    = _reg.get("regime_subtype", "")
                _playbook   = _reg.get("playbook", "")
                _sizing     = _reg.get("position_sizing", "")
                _rw         = _rj.get("regime_warning", "")
                _is_ranging = any(r in (_reg_label or "").lower() for r in ("range", "ranging"))

                if _reg_label:
                    _pb_color = "#f59e0b" if _is_ranging else "#22c55e" if "bull" in _reg_label.lower() else "#ef4444"
                    st.markdown(
                        f"<div style='background:{_pb_color}22;border-left:4px solid {_pb_color};"
                        f"padding:10px 14px;border-radius:6px;margin-bottom:12px'>"
                        f"<b>📍 Regime: {_reg_label}</b>"
                        + (f" — {_reg_sub}" if _reg_sub and _reg_sub != "N/A" else "")
                        + f"<br><span style='font-size:0.9em'>📖 <b>Playbook:</b> {_playbook}</span>"
                        + (f"<br><span style='color:{_pb_color};font-size:0.9em'>⚠️ {_rw}</span>" if _rw else "")
                        + f"<br><span style='font-size:0.85em;opacity:0.8'>💼 Sizing: {_sizing}</span>"
                        + "</div>",
                        unsafe_allow_html=True,
                    )
            except Exception:
                pass

        # ── Today's Opportunities — with read-time regime veto ───────────────
        st.markdown("#### 🎯 Today's Opportunities")

        # ── Read-time veto helpers ────────────────────────────────────────────
        def _get_veto_context() -> dict:
            """
            Derive suppression flags from the latest daily agent report.
            Returns a dict the display loop uses to decide per-opportunity visibility.
            Escape hatch: Range Support Play / Mean Reversion patterns are
            permitted in ranging regimes — they ARE the correct ranging strategy.
            """
            import json as _json
            _regime = _adb.get_latest_regime_for_veto()
            if not _regime:
                return {"active": False}
            _label    = _regime.get("regime", "").lower()
            _bias     = _regime.get("trade_bias", "Balanced").lower()
            _sizing   = _regime.get("position_sizing", "Full").lower()
            _is_cash  = _bias == "cash" or _sizing == "cash"
            _is_range = any(r in _label for r in (
                "range", "ranging", "tight range", "wide range", "volatile range"
            ))
            _late_ex  = "late bull" in _label and _sizing in ("cash", "minimal")
            return {
                "active":        _is_cash or _is_range or _late_ex,
                "suppress_longs": _is_cash or _is_range or _late_ex,
                "suppress_all":   _is_cash,
                "is_ranging":     _is_range,
                "regime_label":   _regime.get("regime", "Unknown"),
                "trade_bias":     _regime.get("trade_bias", "?"),
                "position_sizing": _regime.get("position_sizing", "?"),
            }

        # Escape-hatch pattern tags — these are the CORRECT ranging strategies
        _RANGE_ESCAPE_TAGS = ("Mean Reversion", "Range Support Play", "Range Resistance Short")

        def _is_suppressed(opp: dict, veto: dict) -> tuple[bool, str]:
            """
            Returns (suppressed, reason).
            Opportunities with range-adapted pattern names bypass the veto —
            they are the pivot strategy, not the broken one.
            """
            if not veto.get("active"):
                return False, ""
            _pname = opp.get("pattern_name", "") or ""
            if any(tag in _pname for tag in _RANGE_ESCAPE_TAGS):
                return False, ""  # escape hatch: range play is allowed in ranging regime
            _dir = opp.get("direction", "LONG")
            if _dir == "LONG" and veto.get("suppress_longs"):
                _reason = (
                    f"Regime: **{veto['regime_label']}** "
                    f"({veto['trade_bias']}, {veto['position_sizing']}) — "
                    f"breakout longs suppressed. "
                    f"Setup preserved; reactivates if regime clears or pattern is a Range play."
                )
                return True, _reason
            if veto.get("suppress_all"):
                return True, f"Cash regime — all positions suppressed."
            return False, ""

        _veto_ctx   = _get_veto_context()
        _todays_opps = _adb.get_todays_opportunities()

        if not _todays_opps:
            _recent_opps = _adb.get_agent_opportunities(limit=10)
            if _recent_opps:
                st.info(f"No new opportunities generated today. Showing most recent ({_recent_opps[0].get('run_date','?')}).")
                _todays_opps = _recent_opps[:5]
            else:
                st.info("No opportunities yet. Run the agent to generate today's setups.")

        # Partition into active vs suppressed
        _active_opps     = []
        _suppressed_opps = []  # list of (opp, reason)
        for _opp in _todays_opps:
            _supp, _reason = _is_suppressed(_opp, _veto_ctx)
            if _supp:
                _suppressed_opps.append((_opp, _reason))
            else:
                _active_opps.append(_opp)

        # ── Suppression notice ────────────────────────────────────────────────
        if _suppressed_opps:
            _n = len(_suppressed_opps)
            _veto_label = _veto_ctx.get("regime_label", "Unknown")
            _veto_bias  = _veto_ctx.get("trade_bias", "?")
            st.warning(
                f"**Regime Veto Active** — {_n} opportunit{'y' if _n == 1 else 'ies'} "
                f"suppressed ({_veto_label}, {_veto_bias}). "
                f"Only Range Support Play / Mean Reversion setups are shown when ranging.",
                icon="🚫",
            )
            with st.expander(f"Show {_n} suppressed setup{'s' if _n > 1 else ''} (read-only)"):
                for _s_opp, _s_reason in _suppressed_opps:
                    st.markdown(
                        f"~~**{_s_opp.get('direction','')} {_s_opp.get('symbol','')}**~~ "
                        f"| {_s_opp.get('pattern_name','?')} | "
                        f"Created: {_s_opp.get('run_date','?')} | "
                        f"Regime when created: {_s_opp.get('regime_at_creation','?')}"
                    )
                    st.caption(f"Suppressed: {_s_reason}")
                    st.divider()

        # ── Active opportunities ──────────────────────────────────────────────
        if not _active_opps and not _suppressed_opps:
            st.info("No opportunities yet. Run the agent to generate today's setups.")
        elif not _active_opps and _suppressed_opps:
            st.info("All current setups are suppressed by the regime veto. No actionable opportunities today.")
        else:
            for _opp in _active_opps:
                _dir_emoji = "📈" if _opp.get("direction") == "LONG" else "📉"
                _conf = _opp.get("confidence_pct", 0) or 0
                _conf_color = "#22c55e" if _conf >= 70 else "#f59e0b" if _conf >= 55 else "#ef4444"

                with st.expander(
                    f"{_dir_emoji} **{_opp.get('direction','')} {_opp.get('symbol','')}** "
                    f"| Pattern: {_opp.get('pattern_name','?')} "
                    f"| Confidence: {_conf:.0f}%  "
                    f"| Status: {_opp.get('status','Pending')}",
                    expanded=_conf >= 65,
                ):
                    _oc1, _oc2, _oc3, _oc4 = st.columns(4)
                    _oc1.metric("Entry", f"{_opp.get('entry_price',0):.2f}")
                    _oc2.metric("Stop Loss", f"{_opp.get('stop_loss',0):.2f}")
                    _oc3.metric("Target 1R", f"{_opp.get('target_1r',0):.2f}")
                    _oc4.metric("Target 2R", f"{_opp.get('target_2r',0):.2f}")

                    _meta_parts = []
                    if _opp.get("sector"):
                        _meta_parts.append(f"**Sector:** {_opp['sector']}")
                    if _opp.get("sector_momentum"):
                        _meta_parts.append(f"**Momentum:** {_opp['sector_momentum']}")
                    if _opp.get("regime_at_creation"):
                        _meta_parts.append(f"**Regime when created:** {_opp['regime_at_creation']}")
                    if _meta_parts:
                        st.caption("  |  ".join(_meta_parts))

                    st.markdown(f"**Reasoning:** {_opp.get('reasoning','')}")

                    # Status update controls
                    _opp_id = _opp.get("id")
                    if _opp.get("status") == "Pending" and _opp_id:
                        _btn_c1, _btn_c2, _ = st.columns(3)
                        if _btn_c1.button("Mark Taken", key=f"opp_taken_{_opp_id}"):
                            _adb.update_opportunity_status(_opp_id, status="Taken")
                            st.rerun()
                        if _btn_c2.button("Skip", key=f"opp_skip_{_opp_id}"):
                            _adb.update_opportunity_status(_opp_id, status="Skipped")
                            st.rerun()

        st.divider()

        # ── Agent Reports ─────────────────────────────────────────────────────
        st.markdown("#### 📋 Agent Reports")

        _report_tab_daily, _report_tab_weekly, _report_tab_monthly, _report_tab_bm, _report_tab_log, _report_tab_profile = st.tabs([
            "📅 Daily", "📆 Weekly", "🗓️ Monthly", "📊 vs KSE-100", "🔍 Run Log", "🧠 My Profile"
        ])

        with _report_tab_daily:
            _daily_reports = _adb.get_agent_reports(report_type="daily", limit=7)
            if _daily_reports:
                _sel_date = st.selectbox(
                    "Select date",
                    options=[r["run_date"] for r in _daily_reports],
                    key="agent_daily_date",
                )
                _sel_report = next((r for r in _daily_reports if r["run_date"] == _sel_date), None)
                if _sel_report:
                    _rc1, _rc2 = st.columns([3, 1])
                    with _rc1:
                        st.markdown(_sel_report.get("narrative", "*No narrative.*"))
                    with _rc2:
                        st.metric("Regime", _sel_report.get("market_regime", "?"))
                        if _sel_report.get("breadth_score"):
                            st.metric("Breadth Score", f"{_sel_report['breadth_score']:.0f}/100")
            else:
                st.info("No daily reports yet. Run the agent to generate your first report.")

        with _report_tab_weekly:
            _weekly_reports = _adb.get_agent_reports(report_type="weekly", limit=5)
            if _weekly_reports:
                for _wr in _weekly_reports:
                    with st.expander(f"Week of {_wr['run_date']} — {_wr.get('market_regime','?')}"):
                        st.markdown(_wr.get("narrative", "*No narrative.*"))
            else:
                st.info("No weekly reports yet. Use the **📅 Weekly Run** button above.")

        with _report_tab_monthly:
            _monthly_reports = _adb.get_agent_reports(report_type="monthly", limit=3)
            if _monthly_reports:
                for _mr in _monthly_reports:
                    with st.expander(f"Month of {_mr['run_date'][:7]} — {_mr.get('market_regime','?')}"):
                        st.markdown(_mr.get("narrative", "*No narrative.*"))
            else:
                st.info("No monthly reports yet. Run at end of month for a deep-dive review.")

        # ── vs KSE-100 BENCHMARK TAB ──────────────────────────────────────
        with _report_tab_bm:
            try:
                import agent_benchmark as _abm
                _abm.init_benchmark_columns()

                # ── Portfolio target progress ─────────────────────────────
                # Get portfolio value from DB (latest entry)
                _port_vals = get_portfolio_values()
                _port_value = float(_port_vals[0]["value"]) if _port_vals else 2_000_000
                _target = _abm.get_portfolio_target_progress(
                    portfolio_value=_port_value, target_pct=1.5
                )
                if _target:
                    st.markdown("##### 🎯 Monthly Target: 1.5% Portfolio Return")
                    _tpct = _target.get("achieved_pct", 0) or 0
                    _tpkr = _target.get("target_pkr", 0) or 0
                    _apkr = _target.get("achieved_pkr", 0) or 0
                    _prog = min(1.0, _apkr / _tpkr) if _tpkr > 0 else 0
                    st.progress(_prog)
                    _tc1, _tc2, _tc3, _tc4 = st.columns(4)
                    _tc1.metric("Target (PKR)", f"{_tpkr:,.0f}")
                    _tc2.metric("Achieved (PKR)", f"{_apkr:,.0f}",
                                delta=f"{_tpct:+.2f}%")
                    _tc3.metric("Remaining", f"{_target.get('remaining_pkr',0):,.0f}")
                    _tc4.metric("Trades Taken", str(_target.get("taken_count", 0)))
                    if _target.get("on_track"):
                        st.success("✅ On track for this month's 1.5% target!")
                    else:
                        st.warning(f"⚠️ Still need **PKR {_target.get('remaining_pkr',0):,.0f}** to hit target.")

                st.divider()

                # ── Rolling alpha KPIs ─────────────────────────────────────
                st.markdown("##### 📈 Agent Returns vs KSE-100 Index")
                _r30  = _abm.get_rolling_comparison(30)
                _r90  = _abm.get_rolling_comparison(90)
                _r180 = _abm.get_rolling_comparison(180)
                _inc  = _abm.get_inception_summary()

                _bk1, _bk2, _bk3, _bk4 = st.columns(4)

                def _bm_metric(col, label, agent_r, kse_r, alpha):
                    """Render one benchmark KPI column."""
                    if agent_r is None:
                        col.metric(label, "—", "No data")
                        return
                    delta_str = f"α {alpha:+.1f}% vs KSE-100" if alpha is not None else "—"
                    col.metric(
                        label,
                        f"{agent_r:+.1f}%",
                        delta=delta_str,
                        delta_color="normal" if alpha is None else ("normal" if alpha >= 0 else "inverse"),
                    )

                _bm_metric(_bk1, "Last 30 days",
                            _r30.get("avg_agent_return"), _r30.get("kse100_period_return"), _r30.get("avg_alpha"))
                _bm_metric(_bk2, "Last 90 days",
                            _r90.get("avg_agent_return"), _r90.get("kse100_period_return"), _r90.get("avg_alpha"))
                _bm_metric(_bk3, "Last 180 days",
                            _r180.get("avg_agent_return"), _r180.get("kse100_period_return"), _r180.get("avg_alpha"))
                _bm_metric(_bk4, "Since Inception",
                            _inc.get("avg_agent_return"), _inc.get("avg_kse100_return"), _inc.get("avg_alpha"))

                # Verdicts
                for _window, _rv in [("30d", _r30), ("90d", _r90), ("Inception", {"verdict": _inc.get("avg_alpha","") and ("✅ Beating market" if (_inc.get("avg_alpha") or 0) > 0 else "❌ Lagging market")})]:
                    _v = _rv.get("verdict", "")
                    if _v:
                        st.caption(f"**{_window}:** {_v}")

                st.divider()

                # ── Monthly scoreboard ────────────────────────────────────
                st.markdown("##### 📅 Monthly Scoreboard")
                _scorecard = _abm.get_monthly_scorecard()
                if _scorecard:
                    _sc_df = pd.DataFrame(_scorecard)
                    # Rename for display
                    _sc_df = _sc_df.rename(columns={
                        "month": "Month",
                        "opp_count": "Trades",
                        "avg_agent_return": "Avg Agent Return %",
                        "kse100_month_return": "KSE-100 Month %",
                        "avg_alpha": "Alpha %",
                        "win_rate": "Win Rate %",
                        "verdict": "Verdict",
                    })

                    def _colour_alpha(val):
                        if isinstance(val, (int, float)):
                            return "color:#22c55e;font-weight:bold" if val > 0 else "color:#ef4444;font-weight:bold"
                        return ""

                    st.dataframe(
                        _sc_df.style.map(_colour_alpha, subset=["Alpha %"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.info("No closed opportunities yet. The scoreboard populates as agent trades close out.")

                st.divider()

                # ── What-if analysis ──────────────────────────────────────
                st.markdown("##### 🔍 What-If Analysis")
                st.caption("What would have happened if you took every agent suggestion vs skipping all of them vs just holding KSE-100?")
                _wif = _abm.get_what_if_analysis()
                if _wif:
                    _wc1, _wc2, _wc3 = st.columns(3)
                    _wc1.metric(
                        f"Took All ({_wif.get('total_count',0)} trades)",
                        f"{_wif.get('all_suggestions_avg','?')}%",
                        delta=f"α {_wif.get('all_alpha',0):+.1f}% vs KSE-100" if _wif.get("all_alpha") is not None else None,
                    )
                    _wc2.metric(
                        f"Only Taken ({_wif.get('taken_count',0)} trades)",
                        f"{_wif.get('taken_only_avg','?')}%" if _wif.get("taken_only_avg") else "—",
                        delta=f"α {_wif.get('taken_alpha',0):+.1f}% vs KSE-100" if _wif.get("taken_alpha") is not None else None,
                    )
                    _wc3.metric(
                        "KSE-100 Avg (same periods)",
                        f"{_wif.get('kse100_avg','?')}%" if _wif.get("kse100_avg") else "—",
                    )
                else:
                    st.info("What-if data will populate once agent opportunities start closing out.")

                st.divider()

                # ── Per-trade breakdown ───────────────────────────────────
                st.markdown("##### 📋 Per-Trade Breakdown")
                _trades = _abm.get_per_trade_benchmark(limit=50)
                if _trades:
                    _pt_df = pd.DataFrame(_trades)
                    _show = [c for c in [
                        "exit_date", "symbol", "direction", "pattern_name",
                        "outcome", "actual_pl_pct",
                        "kse100_return_pct", "alpha_pct", "confidence_pct", "status"
                    ] if c in _pt_df.columns]
                    _pt_df = _pt_df[_show].rename(columns={
                        "exit_date": "Exit Date",
                        "symbol": "Symbol",
                        "direction": "Dir",
                        "pattern_name": "Pattern",
                        "outcome": "Outcome",
                        "actual_pl_pct": "Agent %",
                        "kse100_return_pct": "KSE-100 %",
                        "alpha_pct": "Alpha %",
                        "confidence_pct": "Conf %",
                        "status": "Status",
                    })

                    def _style_row(row):
                        styles = [""] * len(row)
                        if "Alpha %" in row.index:
                            idx = row.index.get_loc("Alpha %")
                            val = row.iloc[idx]
                            if isinstance(val, (int, float)):
                                styles[idx] = "color:#22c55e;font-weight:bold" if val > 0 else "color:#ef4444"
                        if "Agent %" in row.index:
                            idx = row.index.get_loc("Agent %")
                            val = row.iloc[idx]
                            if isinstance(val, (int, float)):
                                styles[idx] = "color:#22c55e" if val > 0 else "color:#ef4444"
                        return styles

                    st.dataframe(
                        _pt_df.style.apply(_style_row, axis=1),
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.info("No closed trades with benchmark data yet.")

            except Exception as _bm_page_err:
                st.error(f"Benchmark tab error: {_bm_page_err}")
                import traceback as _bm_tb
                st.code(_bm_tb.format_exc())

        with _report_tab_log:
            # ── Manual trigger ─────────────────────────────────────────────
            st.markdown("#### 🔁 Self-Learning Loop")
            st.caption(
                "Grades ungraded agent suggestions against actual price history, "
                "updates pattern stats, and asks Claude to write a weekly post-mortem. "
                "Runs automatically every Sunday — or trigger manually here."
            )
            if st.button("▶ Run Learning Loop Now", key="run_learn_btn"):
                with st.spinner("Grading opportunities and writing learning summary…"):
                    try:
                        from agent_learn import run_learning_loop as _rll
                        _learn_result = _rll()
                        st.success(
                            f"Done — graded {_learn_result['graded']} opportunities, "
                            f"updated {_learn_result['patterns_updated']} patterns."
                        )
                        st.rerun()
                    except Exception as _rll_err:
                        st.error(f"Learning loop error: {_rll_err}")

            st.divider()

            # ── Weekly learning summaries ──────────────────────────────────
            st.markdown("#### 📝 Weekly Learning Summaries")
            _logs = _adb.get_learning_log(limit=20)
            _learn_logs = [l for l in _logs if l.get("run_type") == "weekly_learn"]
            _daily_logs  = [l for l in _logs if l.get("run_type") != "weekly_learn"]

            if _learn_logs:
                for _ll in _learn_logs[:5]:
                    with st.expander(
                        f"📅 {_ll.get('run_date','?')} — "
                        f"Graded: {_ll.get('opportunities_generated', '?')} | "
                        f"Patterns updated: {_ll.get('patterns_updated', '?')}",
                        expanded=(_ll == _learn_logs[0])
                    ):
                        _summary_text = _ll.get("key_observations", "")
                        if _summary_text:
                            st.markdown(_summary_text)
                        else:
                            st.info("No summary text for this run.")
            else:
                st.info("No weekly learning summaries yet. Run the learning loop to generate the first one.")

            st.divider()
            st.markdown("#### 🗂 Run Log (all runs)")
            if _daily_logs:
                _log_df = pd.DataFrame(_daily_logs)
                _display_cols = [c for c in [
                    "run_date", "run_type", "market_regime",
                    "opportunities_generated", "patterns_updated",
                    "run_duration_sec", "model_used", "error_log"
                ] if c in _log_df.columns]
                st.dataframe(_log_df[_display_cols], hide_index=True, use_container_width=True)
            else:
                st.info("No run log entries yet.")

        with _report_tab_profile:
            st.markdown("#### 🧠 Your Trader Profile")
            st.caption(
                "Built from your chat history. The agent tracks what stocks you ask about, "
                "what emotions you express, and builds guardrails to protect you from your own biases. "
                "Updates every Sunday when the learning loop runs — or trigger it manually below."
            )

            if st.button("🔄 Update Profile Now", key="update_profile_btn",
                         help="Analyse recent chat history and rewrite your behavioral profile"):
                with st.spinner("Analysing your chat patterns…"):
                    try:
                        from agent_learn import build_behavioral_profile as _bpf
                        _prof = _bpf()
                        if _prof:
                            st.success("Profile updated.")
                            st.rerun()
                        else:
                            st.info("Not enough chat history yet — keep chatting with the agent first.")
                    except Exception as _pe:
                        st.error(f"Profile update failed: {_pe}")

            st.divider()

            _profile = _adb.get_latest_trader_profile()
            if _profile:
                _pw = _profile.get("week_date", "?")
                st.caption(f"Last updated: week of {_pw}")

                # Guardrails as a highlighted box
                try:
                    _grules = json.loads(_profile.get("guardrail_rules") or "[]")
                    if _grules:
                        st.markdown("**⚠️ Active Guardrails**")
                        for _gr in _grules:
                            st.warning(_gr, icon="⚠️")
                        st.divider()
                except Exception:
                    pass

                # Full profile text
                st.markdown(_profile.get("profile_text", ""))

                # Emotion stats
                try:
                    _ec = json.loads(_profile.get("emotion_counts") or "{}")
                    if _ec:
                        st.divider()
                        st.markdown("**Emotion signal counts (last 30 days)**")
                        _ec_cols = st.columns(len(_ec))
                        for _i, (_em, _cnt) in enumerate(sorted(_ec.items(), key=lambda x: -x[1])):
                            _ec_cols[_i].metric(_em.title(), _cnt)
                except Exception:
                    pass

                # Most-asked stocks
                try:
                    _ts = json.loads(_profile.get("temptation_stocks") or "{}")
                    if _ts:
                        st.divider()
                        st.markdown("**Stocks you asked about most (last 30 days)**")
                        _ts_sorted = sorted(_ts.items(), key=lambda x: -x[1])[:8]
                        _ts_cols = st.columns(min(4, len(_ts_sorted)))
                        for _j, (_sym, _cnt) in enumerate(_ts_sorted):
                            _ts_cols[_j % 4].metric(_sym, f"{_cnt}x")
                except Exception:
                    pass

                # History
                _prof_history = _adb.get_trader_profile_history(limit=5)
                if len(_prof_history) > 1:
                    st.divider()
                    st.markdown("**Profile history**")
                    for _ph in _prof_history[1:]:
                        with st.expander(f"Week of {_ph.get('week_date','?')}", expanded=False):
                            st.markdown(_ph.get("profile_text", ""))
            else:
                st.info(
                    "No profile yet. Chat with the agent for a week, then click **Update Profile Now** "
                    "or wait for Sunday's automated learning loop."
                )

        st.divider()

        # ── Pattern Library ───────────────────────────────────────────────────
        st.markdown("#### 🧠 Discovered Patterns")
        _patterns = _adb.get_agent_patterns(active_only=False)
        if _patterns:
            for _pat in _patterns:
                _is_active = bool(_pat.get("is_active", 1))
                _active_badge = "🟢 Active" if _is_active else "🔴 Retired"
                _conf = _pat.get("confidence", "Low")
                _wr_display = f"{_pat['win_rate_pct']:.0f}%" if _pat.get("win_rate_pct") else "—"
                with st.expander(
                    f"**{_pat['pattern_name']}** · {_active_badge} · Conf: {_conf} · Win Rate: {_wr_display}",
                    expanded=False,
                ):
                    st.markdown(f"**Description:** {_pat.get('description','')}")
                    _conds = _pat.get("conditions", "{}")
                    if isinstance(_conds, str):
                        try:
                            _conds = json.loads(_conds)
                        except Exception:
                            _conds = {}
                    if _conds:
                        st.json(_conds)
                    _pc1, _pc2, _pc3 = st.columns(3)
                    _pc1.metric("Signals", _pat.get("signal_count", 0))
                    _pc2.metric("Wins", _pat.get("win_count", 0))
                    _pc3.metric("Losses", _pat.get("loss_count", 0))
                    st.caption(f"First seen: {_pat.get('first_seen','?')} · Last updated: {_pat.get('last_updated','?')}")
        else:
            st.info("No patterns discovered yet. Run the agent first — it will analyse your trade history and populate this library.")

        st.divider()

        # ── Reference Breakout Library ────────────────────────────────────────
        st.markdown("#### 📚 Teach the Agent — Reference Breakouts")
        st.caption(
            "Provide examples of your best trades — longs AND shorts. The agent analyses each one, "
            "measures the pre-signal characteristics (consolidation, MA structure, RS, volume), "
            "and uses them to calibrate its screening. Longs and shorts build separate profiles."
        )

        with st.expander("➕ Add a Reference Trade Example", expanded=False):
            _rb_c1, _rb_c2, _rb_c3 = st.columns([2, 2, 1])
            _rb_symbol = _rb_c1.text_input("Symbol", placeholder="e.g. SAZEW").upper().strip()
            _rb_date   = _rb_c2.date_input("Signal Date", value=None, help="The day price broke out (long) or broke down (short)")
            _rb_dir    = _rb_c3.selectbox("Direction", ["LONG", "SHORT"])
            _rb_notes  = st.text_area(
                "Your notes (optional)",
                placeholder="e.g. 8-day tight base after 30% runup, bought the breakout candle at 1340, held 9 days, exited at 1520",
                height=80,
            )
            if st.button("🔍 Analyse This Trade", type="primary", disabled=not (_rb_symbol and _rb_date)):
                if _rb_symbol and _rb_date:
                    with st.spinner(f"Retrieving {_rb_symbol} price history and analysing {_rb_dir} pattern…"):
                        try:
                            from agent import analyze_reference_breakout as _arb_fn
                            _rb_result = _arb_fn(
                                symbol=_rb_symbol,
                                breakout_date=str(_rb_date),
                                direction=_rb_dir,
                                notes=_rb_notes,
                            )
                            if "error" in _rb_result:
                                st.error(_rb_result["error"])
                            else:
                                st.success(f"✅ {_rb_dir} trade analysed and saved for {_rb_symbol} on {_rb_date}")
                                _rb_m1, _rb_m2, _rb_m3, _rb_m4 = st.columns(4)
                                _rb_m1.metric("Consol Days", _rb_result.get("pre_consol_days", "?"))
                                _rb_m2.metric("5d Range", f"{_rb_result.get('pre_range_pct','?'):.1f}%" if _rb_result.get("pre_range_pct") else "?")
                                _rb_m3.metric("RS vs KSE", f"{_rb_result.get('pre_rs_vs_kse','?'):+.1f}%" if _rb_result.get("pre_rs_vs_kse") is not None else "?")
                                _rb_m4.metric("Post-BO Gain", f"{_rb_result.get('post_gain_pct','?'):+.1f}%" if _rb_result.get("post_gain_pct") is not None else "?")
                                if _rb_result.get("analysis_text"):
                                    st.markdown("**Agent's Analysis:**")
                                    st.markdown(_rb_result["analysis_text"])
                        except Exception as _rb_err:
                            st.error(f"Analysis failed: {_rb_err}")

        # Show existing reference breakouts
        _ref_bos = _adb.get_reference_breakouts(limit=20)
        if _ref_bos:
            st.markdown(f"**{len(_ref_bos)} reference breakout(s) in library:**")
            _ref_df = pd.DataFrame(_ref_bos)
            _ref_display_cols = [c for c in [
                "symbol", "direction", "breakout_date", "pre_consol_days", "pre_range_pct",
                "pre_rs_vs_kse", "pre_ma21_dist_pct", "post_gain_pct", "post_days_to_peak"
            ] if c in _ref_df.columns]
            _ref_display = _ref_df[_ref_display_cols].rename(columns={
                "direction": "Dir",
                "pre_consol_days": "Consol Days",
                "pre_range_pct": "5d Range%",
                "pre_rs_vs_kse": "RS vs KSE",
                "pre_ma21_dist_pct": "Dist MA21%",
                "post_gain_pct": "Post Gain%",
                "post_days_to_peak": "Days to Peak",
            })
            st.dataframe(_ref_display, use_container_width=True, hide_index=True)

            # Show aggregate profile
            _bp_stats = _adb.get_breakout_profile_stats()
            if _bp_stats and _bp_stats.get("n", 0) >= 2:
                st.markdown("**Average profile of your breakouts (calibrates agent screening):**")
                _bp1, _bp2, _bp3, _bp4 = st.columns(4)
                _bp1.metric("Avg Consol Days", f"{_bp_stats.get('avg_consol_days', 0):.1f}d")
                _bp2.metric("Avg 5d Range", f"{_bp_stats.get('avg_range_pct', 0):.1f}%")
                _bp3.metric("Avg RS vs KSE", f"{_bp_stats.get('avg_rs', 0):+.1f}%")
                _bp4.metric("Avg Post-BO Gain", f"{_bp_stats.get('avg_post_gain', 0):+.1f}%")
        else:
            st.info("No reference breakouts added yet. Add your 3–5 best trades above to teach the agent your pattern.")

        st.divider()

        # ── Setup Instructions ────────────────────────────────────────────────
        with st.expander("⚙️ Setup Instructions (first time)", expanded=False):
            st.markdown("""
**Step 1 — Install the Anthropic package:**
```
pip install anthropic
```

**Step 2 — Get your API key:**
- Go to [console.anthropic.com](https://console.anthropic.com)
- Create an API key (free trial or paid)

**Step 3 — Add your key to the project:**
Create a file called `.env` in `C:\\Users\\Lenovo\\psx_pipeline\\` with:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Step 4 — Run the agent:**
- Click **▶ Run Agent Now** above, OR
- Run from terminal: `python agent.py`
- Or double-click `run_agent.bat`

**Step 5 — Automate (optional):**
- Open `run_update.bat` and add a line: `python agent.py --type daily`
- This runs the agent every morning after your data update

**Cost estimate:** ~$1–2 per month running daily (Haiku model for daily, Sonnet for weekly/monthly).
""")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — 💰 Valuation   (Financial Highlights / DCF Data)
# ══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[15]:  # Valuation
    from page_valuation import render_valuation_page
    render_valuation_page()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — 📡 Flows   (FIPI / LIPI Institutional Flow Tracker)
# ══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[16]:  # Flows
    from page_flows import render_flows_page
    render_flows_page()




# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 17 — 🏹 Minervini Setup Screener  v2
# Read-only. Two signal types: Watchlist (pre-breakout) + Breakout (confirmed).
# Writes ONLY to trade_setups (source="Minervini") via explicit Save button.
# ══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[17]:  # Minervini Setup

    st.markdown("### 🏹 Minervini Setup — Breakout Screener")

    with st.expander("📖 How this screener works — read before trading", expanded=False):
        st.markdown("""
**Derived from 9 confirmed real trades** (DGKC×2, FFC×3, UBL×2, TPLP, POWER — 2021–2026).

---
#### Two Signal Types

**📋 WATCHLIST** — Base is tight, price coiling within 3% of pivot. Breakout has NOT happened yet.
Use for morning prep. Watch intraday. Enter discretionarily on the break with volume confirmation.

**✅ BREAKOUT** — Confirmed end-of-day breakout with volume. Breakout happened TODAY.
Enter tomorrow's open if you missed the intraday move. Risk is slightly wider.

---
#### Shared Conditions (both signals)
| Condition | Rule | Evidence |
|---|---|---|
| **Stage 2** | close > EMA20 > EMA50 > EMA200 | Full uptrend stack — 9/10 entries. Uses EMA (matches charting platforms, reacts faster than SMA) |
| **Tight Base** | BB width (prior day) ≤ 12% | Avg 8.3% across 9 entries. Formula: (Upper−Lower)/Middle×100 |
| **No Overhead** | 200-day high ≤ 60-day pivot × 1.05 | Breakout into clear air — no heavy resistance above |
| **Market** | KSE-100 close > 50 SMA | Bull market only — 9/9 entries in up regime |
| **RS Rating** | Cross-sectional percentile ≥ 60 | Avg 74 at entry, range 53–87 |
| **Liquidity** | 20-day avg volume ≥ 100,000 shares | Filters untradeable names |
| **Volatility** | ATR14 between 1% and 6% of price | Avg 2.85% — controlled breakouts only |

#### SHORT Signal — DFC counters only
Inverse rules: Stage 4 (close < EMA20 < EMA50 < EMA200), close below 60-day low,
tight base (BB width ≤ 12%), volume ≥ 2×, KSE-100 below SMA50, RS Rating ≤ 40. Only PSX-shortable (DFC) stocks.

#### RS Rating explained
Cross-sectional **percentile rank** of multi-period momentum:
40% × 1yr return + 30% × 6m + 20% × 3m + 10% × 1m.
Rating 75 = stock stronger than 75% of all PSX stocks on that day.

#### Known limitation
Stocks post-bonus-issue have distorted EMAs for ~200 days. Stage 2 may fail
on recently ex-dated stocks until EMA200 normalises on adjusted prices.

---
*Signals are read-only. Use **Save to Setup Perf** to track them over time.*
        """)

    # ── Load prices ───────────────────────────────────────────────────────────
    with st.spinner("Loading price data…"):
        _mv_prices = load_stm_prices()

    if _mv_prices.empty:
        st.error("No price data available. Run a data update first.")
        st.stop()

    @st.cache_data(ttl=3600, show_spinner=False)
    def _load_mv_index():
        from database import get_index_prices
        rows = get_index_prices("KSE-100")
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"]  = pd.to_datetime(df["date"])
        df["idx_close"] = pd.to_numeric(df["close"], errors="coerce")
        return df[["date","idx_close"]].sort_values("date")

    _mv_index = _load_mv_index()
    if _mv_index.empty:
        st.error("No index data available.")
        st.stop()

    # ── Run signal engine ─────────────────────────────────────────────────────
    with st.spinner("Computing Minervini signals across full universe…"):
        from breakout_signal import build_features as _mv_build, get_signals as _mv_get
        _mv_df   = _mv_build(_mv_prices, _mv_index)

    _mv_latest          = _mv_df["date"].max()
    _mv_watchlist, _mv_longs, _mv_shorts = _mv_get(_mv_df, _mv_latest)

    # ── Market regime banner ──────────────────────────────────────────────────
    _mv_idx_close = float(_mv_index[_mv_index["date"] <= _mv_latest].tail(1)["idx_close"].iloc[0])
    _mv_idx_sma50 = float(_mv_index["idx_close"].rolling(50).mean().iloc[-1])
    _mv_mkt_up    = _mv_idx_close > _mv_idx_sma50
    _mv_mkt_col   = "#16a34a" if _mv_mkt_up else "#dc2626"
    _mv_mkt_txt   = "BULL — KSE-100 above 50 SMA" if _mv_mkt_up else "BEAR — KSE-100 below 50 SMA"
    st.markdown(
        f'<div style="background:{"#f0fdf4" if _mv_mkt_up else "#fff5f5"};'
        f'border-left:4px solid {_mv_mkt_col};padding:8px 14px;border-radius:6px;margin-bottom:10px;">'
        f'<b style="color:{_mv_mkt_col};">Market: {_mv_mkt_txt}</b>'
        f' &nbsp;·&nbsp; KSE-100: <b>{_mv_idx_close:,.0f}</b>'
        f' &nbsp;·&nbsp; SMA50: <b>{_mv_idx_sma50:,.0f}</b>'
        f' &nbsp;·&nbsp; As of: {_mv_latest.strftime("%d %b %Y")}'
        f'</div>', unsafe_allow_html=True
    )

    # ── Gate funnel KPIs ──────────────────────────────────────────────────────
    _mv_day      = _mv_df[_mv_df["date"] == _mv_latest]
    _mv_total    = _mv_day["symbol"].nunique()
    _mv_s2       = int(_mv_day["stage2"].sum())
    _mv_bo       = int((_mv_day["stage2"] & _mv_day["bo_long"]).sum())
    _mv_nl       = len(_mv_longs)
    _mv_ns       = len(_mv_shorts)
    _mv_nw       = len(_mv_watchlist)

    _kc = st.columns(6)
    for _col, _lbl, _val, _clr in [
        (_kc[0], "Universe",      f"{_mv_total:,}",  "#1d4ed8"),
        (_kc[1], "Stage 2",       f"{_mv_s2:,}",     "#7c3aed"),
        (_kc[2], "Broke Pivot",   f"{_mv_bo:,}",     "#d97706"),
        (_kc[3], "LONG Signals",  f"{_mv_nl}",       "#16a34a"),
        (_kc[4], "SHORT (DFC)",   f"{_mv_ns}",       "#dc2626"),
        (_kc[5], "Watchlist",     f"{_mv_nw}",       "#0891b2"),
    ]:
        _col.markdown(
            f'<div style="border:1px solid {_clr}33;border-top:3px solid {_clr};'
            f'border-radius:8px;padding:10px;text-align:center;">'
            f'<div style="font-size:0.65rem;color:#64748b;text-transform:uppercase;'
            f'letter-spacing:.06em;">{_lbl}</div>'
            f'<div style="font-size:1.4rem;font-weight:800;color:{_clr};">{_val}</div>'
            f'</div>', unsafe_allow_html=True
        )
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    _mv_tab_l, _mv_tab_s, _mv_tab_w = st.tabs([
        f"📈 LONG Signals ({_mv_nl})",
        f"📉 SHORT Signals — DFC only ({_mv_ns})",
        f"🕐 Watchlist ({_mv_nw})"
    ])

    with _mv_tab_l:
        if _mv_longs.empty:
            st.info("No LONG signals today." if _mv_mkt_up else
                    "⚠ Market in BEAR regime — LONG signals require KSE-100 above SMA50.")
        else:
            _ld = _mv_longs.copy()
            _ld["Vol/Avg"]  = _ld["vol_ratio"].apply(lambda x: f"{x:.1f}×")
            _ld["RS Rating"]= _ld["rs_rating"].apply(lambda x: f"{x:.0f}%ile")
            _ld["ATR%"]     = _ld["atr_pct"].apply(lambda x: f"{x:.2f}%")
            _ld["DFC"]      = _ld["is_dfc"].map({True: "✓", False: ""})
            _ld["BB Width%"] = _ld["bb_width"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
            _disp_cols      = ["symbol","close","ema20","ema50","ema200",
                               "pivot_high","BB Width%","ATR%","Vol/Avg","RS Rating","rs_score","DFC"]
            st.dataframe(_ld[_disp_cols].rename(columns={
                "symbol":"Symbol","close":"Close","ema20":"EMA20","ema50":"EMA50",
                "ema200":"EMA200","pivot_high":"Pivot High","rs_score":"RS Score%"
            }), use_container_width=True, hide_index=True)

            st.markdown("---")
            _sc1, _sc2 = st.columns([2, 3])
            with _sc1:
                _mv_save_btn = st.button(
                    f"💾 Save {_mv_nl} signal(s) to Setup Perf",
                    type="primary",
                    help="Saves today's signals with source='Minervini' for audit in Setup Perf. "
                         "Does not open trades or affect Trade Log."
                )
            with _sc2:
                st.caption(
                    "Saving records this screen's picks for later audit. "
                    "It does **not** open a trade or affect the Trade Log."
                )

            if _mv_save_btn:
                _date_str  = _mv_latest.strftime("%Y-%m-%d")
                _existing  = get_trade_setups()
                _ex_keys   = {
                    (r.get("symbol",""), str(r.get("created_date",""))[:10], r.get("source",""))
                    for r in (_existing or [])
                }
                _saved, _skipped = 0, 0
                for _, _sr in _mv_longs.iterrows():
                    if (_sr["symbol"], _date_str, "Minervini") in _ex_keys:
                        _skipped += 1
                        continue
                    save_trade_setup({
                        "created_date":    _date_str,
                        "direction":       "LONG",
                        "symbol":          _sr["symbol"],
                        "sector":          "",
                        "source":          "Minervini",
                        "entry_price":     float(_sr["close"]),
                        "stop_loss":       round(float(_sr["close"]) * 0.96, 2),
                        "target_1r":       round(float(_sr["close"]) * 1.08, 2),
                        "target_2r":       round(float(_sr["close"]) * 1.16, 2),
                        "status":          "Pending",
                        "quality_score":   int(min(round(float(_sr["rs_rating"]) / 20), 5)),
                        "risk_pct":        4.0,
                        "stock_perf_30d":  float(_sr.get("rs_score", 0)),
                        "stock_perf_10d":  0.0,
                        "sector_momentum": "",
                        "breadth_score":   0.0,
                        "sector_rank":     0,
                    })
                    _saved += 1
                if _saved:
                    st.success(f"✅ {_saved} signal(s) saved to Setup Perf (source=Minervini).")
                if _skipped:
                    st.info(f"ℹ {_skipped} already existed — skipped.")

    with _mv_tab_s:
        if _mv_shorts.empty:
            st.info("No SHORT signals today." if not _mv_mkt_up else
                    "⚠ Market in BULL regime — SHORT signals require KSE-100 below SMA50.")
        else:
            _sd = _mv_shorts.copy()
            _sd["Vol/Avg"]  = _sd["vol_ratio"].apply(lambda x: f"{x:.1f}×")
            _sd["RS Rating"]= _sd["rs_rating"].apply(lambda x: f"{x:.0f}%ile")
            _sd["ATR%"]     = _sd["atr_pct"].apply(lambda x: f"{x:.2f}%")
            _sd["BB Width%"] = _sd["bb_width"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
            _sd_cols        = ["symbol","close","ema20","ema50","ema200",
                               "pivot_low","BB Width%","ATR%","Vol/Avg","RS Rating","rs_score"]
            st.dataframe(_sd[_sd_cols].rename(columns={
                "symbol":"Symbol","close":"Close","ema20":"EMA20","ema50":"EMA50",
                "ema200":"EMA200","pivot_low":"Pivot Low","rs_score":"RS Score%"
            }), use_container_width=True, hide_index=True)

    with _mv_tab_w:
        if _mv_watchlist.empty:
            st.info("No watchlist candidates today.")
        else:
            _wd = _mv_watchlist.copy()
            _wd["% From Pivot"] = ((_wd["pivot_high"] - _wd["close"]) / _wd["pivot_high"] * 100).apply(lambda x: f"{x:.2f}%")
            _wd["Vol/Avg"]      = _wd["vol_ratio"].apply(lambda x: f"{x:.1f}×")
            _wd["RS Rating"]    = _wd["rs_rating"].apply(lambda x: f"{x:.0f}%ile")
            _wd["ATR%"]         = _wd["atr_pct"].apply(lambda x: f"{x:.2f}%")
            _wd["BB Width%"]    = _wd["bb_width"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
            _wdisp_cols         = ["symbol","close","% From Pivot","pivot_high","BB Width%","ATR%","Vol/Avg","RS Rating"]
            st.dataframe(_wd[_wdisp_cols].rename(columns={
                "symbol":"Symbol","close":"Close","pivot_high":"Pivot High"
            }), use_container_width=True, hide_index=True)
