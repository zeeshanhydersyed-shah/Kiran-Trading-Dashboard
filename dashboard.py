"""PSX Sector Performance Dashboard — KIRAN."""

import json
import sqlite3
import sys
import logging
import warnings
from datetime import datetime

import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np

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

_PG_URL = _os.environ.get("DATABASE_URL") or _os.environ.get("SUPABASE_DB_URL")

from database import (
    init_db, get_price_date_range, count_prices, count_sectors,
    get_latest_stock_date, get_latest_index_date,
    save_trade_setup, get_trade_setups, update_trade_setup, close_trade_setup,
    activate_trade_setup, delete_trade_setup, get_backtest_summary,
    auto_save_stm_picks, get_sim_portfolio_data,
    add_portfolio_transaction, get_portfolio_transactions, delete_portfolio_transaction,
    add_portfolio_value, get_portfolio_values, delete_portfolio_value,
    evaluate_paper_trades,
)
from processor import run_analysis
# from stm_sr_integration import enrich_stm_with_sr_zones  # dead — STM page removed
from config import DB_PATH, DFC_SYMBOLS

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

@st.cache_data(ttl=7200, show_spinner="Loading market data...")  # 2 hours instead of 30 min
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
    from database import get_sector_price_data_1y
    raw = get_sector_price_data_1y()
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
        from database import get_prices_for_breadth_recent, get_index_prices
        from weinstein import compute_breadth_series, WeinsteinIndicator, PSX_DEFAULTS

        raw_prices = get_prices_for_breadth_recent()
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


# ── STM screener functions — DEAD CODE (screener killed; pages removed below)
# Quality logic (uptrend + outperforming + 500k vol) folded into Explorer filter.

@st.cache_data(ttl=1800, show_spinner=False)
def load_stm_prices() -> pd.DataFrame:
    from database import get_sector_price_data_60d
    raw = get_sector_price_data_60d()
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

    # ── Read pre-computed STM base signals ────────────────────────
    import sqlite3 as _stm_sq
    from config import DB_PATH as _stm_db

    @st.cache_data(ttl=300, show_spinner=False)
    def _load_stm_signals():
        conn = _stm_sq.connect(_stm_db)
        conn.execute("PRAGMA cache_size=-32000")
        latest = conn.execute(
            "SELECT MAX(as_of_date) FROM stm_signals"
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM stm_signals
               WHERE as_of_date = ?""",
            (latest,)
        ).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM stm_signals LIMIT 0"
        ).description]
        conn.close()
        df = pd.DataFrame(rows, columns=cols)
        df["as_of_date"] = pd.to_datetime(df["as_of_date"])
        for col in ("latest_close","day_low","ma21","ma50",
                    "avg_vol_10d","range_5d_pct","atr_pct"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df, latest

    _stm_base, _stm_date = _load_stm_signals()

    if _stm_base.empty:
        return dict(
            all_pass=all_pass, gates=gates, qual_sectors=qual_sec, kse_30d=kse_30d,
            result=pd.DataFrame(),
            short_all_pass=short_all_pass, short_gates=short_gates,
            short_qual_sectors=weak_sec, short_result=pd.DataFrame(),
        )

    signals_df = _stm_base.copy()
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

PAGES = ["🎯 Market Gates Dashboard", "🧭 Regime", "📊 Market", "🔍 Explorer", "📈 History", "📋 Trade Log", "📉 Analytics", "🔄 Recovery Bases", "🎯 Setup Perf", "🤖 Backtest", "🗂️ Portfolio", "🏥 Model Health", "🤖 Agent", "💰 Valuation", "🏆 Leaders", "📋 Setup History", "🏥 Data Health"]


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


@st.cache_data(ttl=300)
def _get_regime_status():
    """Shared data-fetch for the sidebar regime widget and the global regime
    header (E10.2 merge — both independently ran the identical query and
    days-since-transition algorithm before this).

    Returns (current_regime, latest_date, days_since) or None if
    market_regime has no data.

    Deliberately recomputes from full history every call rather than
    reading market_regime.regime_days — that column is currently
    non-idempotent across same-date re-runs (confirmed ~2x inflated on both
    Supabase and local as of 2026-07-08) and must not be trusted until
    regime.py's increment logic is fixed separately.
    """
    if _PG_URL:
        from dashboard_pg import get_regime_status_pg
        return get_regime_status_pg()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, regime FROM market_regime ORDER BY date"
    ).fetchall()
    conn.close()

    if not rows:
        return None

    dates   = [r[0] for r in rows]
    regimes = [r[1] for r in rows]
    last_transition_idx = None
    for i in range(len(regimes) - 1, 0, -1):
        if regimes[i] != regimes[i - 1]:
            last_transition_idx = i
            break
    days_since = (
        len(dates) - 1 - last_transition_idx
        if last_transition_idx is not None else len(dates) - 1
    )
    return regimes[-1], dates[-1], days_since


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

    # ── Live regime widget (global — visible on every page) ───────────────────
    # E10.2: shared, cached data-fetch (_get_regime_status) — was a standalone
    # uncached query here, now merged with the header's identical query below.
    try:
        _regime_status = _get_regime_status()
    except Exception:
        _regime_status = None

    if _regime_status:
        _r_current, _r_latest_d, _r_days_since = _regime_status
        _r_regime_color = {
            "TRENDING_UP":   "#22c55e",
            "VOLATILE":      "#f59e0b",
            "RANGING":       "#94a3b8",
            "TRENDING_DOWN": "#ef4444",
        }.get(_r_current, "#94a3b8")
        # Amber warning if within 0-2 days of last transition (risk zone)
        _r_days_style = (
            "background:#fef3c7; color:#92400e; padding:1px 5px; border-radius:3px; font-weight:bold"
            if _r_days_since <= 2
            else "font-weight:bold"
        )
        st.markdown(
            f"<div style='font-size:0.78rem; margin-bottom:2px; color:#94a3b8;'>Market Regime</div>"
            f"<div style='font-size:0.88rem; font-weight:700; color:{_r_regime_color}; "
            f"margin-bottom:1px;'>{_r_current.replace('_', ' ')}</div>"
            f"<div style='font-size:0.78rem;'>"
            f"<span style='{_r_days_style}'>{_r_days_since}d</span>"
            f" since last change &nbsp;·&nbsp; as of {fmt_date(_r_latest_d)}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

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

# ── Corporate action suspects warning pill ────────────────────────────────
@st.cache_data(ttl=300)
def _get_corporate_action_count():
    if _PG_URL:
        from dashboard_pg import get_corporate_action_count_pg
        return get_corporate_action_count_pg()
    import sqlite3 as _sq
    from config import DB_PATH as _banner_db
    conn = _sq.connect(_banner_db)
    conn.execute("PRAGMA cache_size=-32000")
    count = conn.execute(
        "SELECT COUNT(*) FROM corporate_action_suspects WHERE status = 'PENDING'"
    ).fetchone()[0]
    conn.close()
    return count

try:
    _pending_count = _get_corporate_action_count()
    if _pending_count > 0:
        st.warning(f"⚠️ {_pending_count} corporate action(s) need review — see 🏥 Data Health page.")
except Exception:
    pass

# ── Regime conditions header (global — every page, no exceptions) ─────────────
# E10.2: shared, cached data-fetch (_get_regime_status) — was a standalone
# uncached query here, now merged with the sidebar widget's identical query above.
try:
    _rh_status = _get_regime_status()

    if _rh_status:
        _rh_regime, _rh_latest_date, _rh_days_since = _rh_status

        if _rh_regime == "TRENDING_UP":
            if _rh_days_since >= 6:
                _rh_label    = "Stable uptrend — favorable conditions"
                _rh_bg       = "#f0fdf4"
                _rh_border   = "#22c55e"
                _rh_color    = "#166534"
                _rh_extra    = ""
            elif _rh_days_since >= 3:
                _rh_label    = "Uptrend settling — moderate caution"
                _rh_bg       = "#f8fafc"
                _rh_border   = "#64748b"
                _rh_color    = "#334155"
                _rh_extra    = ""
            else:
                _rh_label    = "Uptrend just started — proceed carefully"
                _rh_bg       = "#fef3c7"
                _rh_border   = "#f59e0b"
                _rh_color    = "#92400e"
                _rh_extra    = " ⚠️"
        elif _rh_regime == "VOLATILE":
            _rh_label  = "Choppy conditions — selective only"
            _rh_bg     = "#fffbeb"
            _rh_border = "#fbbf24"
            _rh_color  = "#78350f"
            _rh_extra  = ""
        elif _rh_regime == "RANGING":
            _rh_label  = "Narrow range — low activity expected"
            _rh_bg     = "#f8fafc"
            _rh_border = "#94a3b8"
            _rh_color  = "#475569"
            _rh_extra  = ""
        elif _rh_regime == "TRENDING_DOWN":
            # Distinct blue-grey — total unknown, not a quantified warning
            _rh_label  = "Downtrend — untested in your history"
            _rh_bg     = "#e8edf2"
            _rh_border = "#64748b"
            _rh_color  = "#334155"
            _rh_extra  = " ℹ️"
        else:
            _rh_label = _rh_regime
            _rh_bg = "#f8fafc"; _rh_border = "#94a3b8"; _rh_color = "#475569"; _rh_extra = ""

        # ── Kelly pill (computed once, appended to header) ────────────────────
        try:
            from kelly import build_kelly_snapshot
            @st.cache_data(ttl=600, show_spinner=False)
            def _cached_kelly():
                return build_kelly_snapshot()
            _kl = _cached_kelly()
            _kl_full = f"{_kl.full_kelly_pct:+.2f}%"
            _kl_half = f"{_kl.half_kelly_pct:+.2f}%"
            if _kl.negative_edge:
                _kl_pill_bg    = "#fef2f2"
                _kl_pill_color = "#991b1b"
                _kl_label      = "No Edge"
            else:
                _kl_pill_bg    = "#f0fdf4"
                _kl_pill_color = "#166534"
                _kl_label      = "Kelly"
            _kelly_html = (
                f"<span style='margin-left:4px; border-left:1px solid #e2e8f0; "
                f"padding-left:12px; display:inline-flex; align-items:center; gap:8px; white-space:nowrap;'>"
                f"<span style='font-size:0.68rem; color:#94a3b8; letter-spacing:0.04em; text-transform:uppercase;'>"
                f"Kelly (30T)</span>"
                f"<span style='font-size:0.75rem; font-weight:600; "
                f"background:{_kl_pill_bg}; color:{_kl_pill_color}; "
                f"padding:1px 7px; border-radius:4px;'>"
                f"Full {_kl_full}</span>"
                f"<span style='font-size:0.75rem; font-weight:600; "
                f"background:{_kl_pill_bg}; color:{_kl_pill_color}; "
                f"padding:1px 7px; border-radius:4px;'>"
                f"Half {_kl_half}</span>"
                f"</span>"
            )
        except Exception:
            _kelly_html = ""

        st.markdown(
            f"<div style='background:{_rh_bg}; border-left:4px solid {_rh_border}; "
            f"padding:6px 14px; border-radius:6px; margin-bottom:6px; "
            f"display:flex; align-items:center; gap:12px; flex-wrap:wrap;'>"
            f"<span style='font-size:0.85rem; font-weight:700; color:{_rh_color}; white-space:nowrap;'>"
            f"{_rh_label}{_rh_extra}</span>"
            f"<span style='font-size:0.72rem; color:#94a3b8; white-space:nowrap;'>"
            f"{_rh_days_since}d since last regime change &nbsp;·&nbsp; as of {fmt_date(_rh_latest_date)}"
            f"</span>"
            f"{_kelly_html}"
            f"</div>",
            unsafe_allow_html=True,
        )
except Exception:
    pass  # never crashes the dashboard

# ── Kiran's Voice panel ───────────────────────────────────────────────────────
try:
    _kv_row = _kv_latest()

    with st.expander(
        "\U0001f9e0 Kiran's Voice"
        + (f"  ·  {_kv_row['stance'][:80] if _kv_row and _kv_row['stance'] else 'No entry yet'}" if _kv_row else "  ·  No entry yet"),
        expanded=False,
    ):
        if _kv_row:
            _kv_ts   = _kv_row["ts"][:16] if _kv_row["ts"] else ""
            _kv_date = _kv_row["market_date"] or ""
            _kv_trig = _kv_row["trigger_type"] or ""
            st.markdown(
                f"<div style='font-size:0.7rem; color:#94a3b8; margin-bottom:6px;'>"
                f"{_kv_ts} &nbsp;·&nbsp; {_kv_date} &nbsp;·&nbsp; {_kv_trig}"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:0.88rem; line-height:1.6; color:#e2e8f0;"
                f" background:#1e293b; border-left:3px solid #6366f1;"
                f" padding:10px 14px; border-radius:4px;'>"
                f"{_kv_row['response']}"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Kiran hasn't spoken yet. Run: `python kiran_voice.py scheduled`")

        st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

        _kv_input = st.text_input(
            "Ask Kiran",
            placeholder="What do you see in ASTL? Is this market worth trading?",
            key="kiran_voice_input",
            label_visibility="collapsed",
        )
        _kv_col1, _kv_col2 = st.columns([1, 4])
        with _kv_col1:
            _kv_send = st.button("Ask", key="kiran_voice_send", type="primary")
        with _kv_col2:
            _kv_brief = st.button("Morning Brief", key="kiran_voice_brief")

        if _kv_send and _kv_input and _kv_input.strip():
            with st.spinner("Kiran is thinking..."):
                try:
                    from kiran_voice import run_kiran as _kv_run
                    _kv_reply = _kv_run("conversational", _kv_input.strip())
                    st.markdown(
                        f"<div style='font-size:0.88rem; line-height:1.6; color:#e2e8f0;"
                        f" background:#1e293b; border-left:3px solid #22c55e;"
                        f" padding:10px 14px; border-radius:4px; margin-top:8px;'>"
                        f"{_kv_reply}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.rerun()
                except Exception as _kv_err:
                    st.error(f"Kiran error: {_kv_err}")

        if _kv_brief:
            with st.spinner("Building morning brief..."):
                try:
                    from kiran_voice import run_kiran as _kv_run
                    _kv_reply = _kv_run("morning_open")
                    st.markdown(
                        f"<div style='font-size:0.88rem; line-height:1.6; color:#e2e8f0;"
                        f" background:#1e293b; border-left:3px solid #fbbf24;"
                        f" padding:10px 14px; border-radius:4px; margin-top:8px;'>"
                        f"{_kv_reply}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.rerun()
                except Exception as _kv_err:
                    st.error(f"Kiran error: {_kv_err}")

except Exception as _kv_panel_err:
    pass  # panel never crashes the dashboard

cur = st.session_state.page


# ── Module-level cached functions (moved from page blocks) ────────────────────

@st.cache_data(ttl=300)
def _kv_latest():
    if _PG_URL:
        from dashboard_pg import get_kv_latest_pg
        return get_kv_latest_pg()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT ts, market_date, trigger_type, stance, response "
        "FROM agent_memory ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    return dict(row) if row else None


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


@st.cache_data(ttl=3600, show_spinner=False)
def _sh_load_filter_opts():
    if _PG_URL:
        from dashboard_pg import get_sh_filter_opts_pg
        return get_sh_filter_opts_pg()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size=-32000")
    regimes = [r[0] for r in conn.execute(
        "SELECT DISTINCT regime FROM setup_log "
        "WHERE regime IS NOT NULL ORDER BY regime"
    ).fetchall()]
    sectors = [s[0] for s in conn.execute(
        "SELECT DISTINCT sector FROM setup_log "
        "WHERE sector IS NOT NULL ORDER BY sector"
    ).fetchall()]
    conn.close()
    return regimes, sectors


@st.cache_data(ttl=3600, show_spinner=False)
def _sh_load_perf(regime, sector, setup_type):
    if _PG_URL:
        from dashboard_pg import get_sh_perf_pg
        return get_sh_perf_pg(regime, sector, setup_type)
    q = """
        SELECT
            setup_type, regime, sector,
            COUNT(*) AS total,
            SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END) AS winners,
            SUM(CASE WHEN outcome_label='LOSER'  THEN 1 ELSE 0 END) AS losers,
            SUM(CASE WHEN outcome_label='BREAKEVEN' THEN 1 ELSE 0 END) AS breakevens,
            ROUND(AVG(fwd_return_5d), 2)  AS avg_5d,
            ROUND(AVG(fwd_return_10d), 2) AS avg_10d,
            ROUND(AVG(fwd_return_20d), 2) AS avg_20d,
            ROUND(
                SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END)
                * 100.0 / COUNT(*), 1
            ) AS win_pct
        FROM setup_log
        WHERE outcome_label IS NOT NULL
    """
    params = []
    if regime != 'All':
        q += " AND regime = ?"
        params.append(regime)
    if sector != 'All':
        q += " AND sector = ?"
        params.append(sector)
    if setup_type != 'All':
        q += " AND setup_type = ?"
        params.append(setup_type)
    q += " GROUP BY setup_type, regime, sector ORDER BY win_pct DESC"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size=-32000")
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _sh_load_symbol(symbol):
    if _PG_URL:
        from dashboard_pg import get_sh_symbol_pg
        return get_sh_symbol_pg(symbol)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size=-32000")
    summary = conn.execute(
        """
        SELECT
            COUNT(*) AS total_appearances,
            SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END) AS winners,
            SUM(CASE WHEN outcome_label='LOSER'  THEN 1 ELSE 0 END) AS losers,
            SUM(CASE WHEN outcome_label='BREAKEVEN' THEN 1 ELSE 0 END) AS breakevens,
            ROUND(AVG(fwd_return_10d), 2) AS avg_10d,
            ROUND(
                SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END)
                * 100.0 /
                NULLIF(COUNT(CASE WHEN outcome_label IS NOT NULL THEN 1 END), 0),
                1
            ) AS win_pct
        FROM setup_log
        WHERE symbol = ? AND outcome_label IS NOT NULL
        """,
        (symbol,)
    ).fetchone()
    rows = conn.execute(
        """
        SELECT
            setup_date, setup_type, regime, sector,
            rs_rank, sector_rs_rank, rank_change,
            rs_score_20, base_tightness, pivot_distance_pct,
            bos_flag, fwd_return_5d, fwd_return_10d,
            fwd_return_20d, outcome_label
        FROM setup_log
        WHERE symbol = ?
        ORDER BY setup_date DESC
        LIMIT 500
        """,
        (symbol,)
    ).fetchall()
    conn.close()
    return summary, rows


# ── E10.3: extracted data-fetch functions (were inline in page-render code) ───

def _get_market_gates_sectors():
    if _PG_URL:
        from dashboard_pg import get_market_gates_sectors_pg
        return get_market_gates_sectors_pg()
    conn = sqlite3.connect(DB_PATH)
    latest = pd.read_sql_query(
        "SELECT MAX(date) AS d FROM sector_signals", conn
    ).iloc[0]["d"]
    sectors = pd.read_sql_query(
        """
        SELECT sector, rs_rank, rs_score_20, composite_score,
               breadth_score, rs_inflection
        FROM sector_signals
        WHERE date = ?
          AND rs_rank IS NOT NULL
        ORDER BY rs_rank ASC
        """,
        conn,
        params=(latest,),
    )
    conn.close()
    return latest, sectors


def _get_rotation_radar_data():
    if _PG_URL:
        from dashboard_pg import get_rotation_radar_data_pg
        return get_rotation_radar_data_pg()
    conn = sqlite3.connect(DB_PATH)

    latest_rr = pd.read_sql_query(
        "SELECT MAX(date) as d FROM sector_signals", conn
    ).iloc[0]["d"]

    rr_df = pd.read_sql_query("""
        SELECT
            ss.sector,
            ss.rs_score_20, ss.rs_score_50, ss.rs_rank,
            ss.breadth_score, ss.adv_dec_ratio, ss.vol_ratio,
            ss.rs_inflection, ss.composite_score, ss.regime,
            ss.sector_stage, ss.sector_above_ema,
            ss.sector_ema_slope, ss.sector_pivot_dist_pct
        FROM sector_signals ss
        WHERE ss.date = ?
        ORDER BY ss.composite_score DESC
    """, conn, params=(latest_rr,))

    # rr_hist: fetched for a 30-day RS sparkline that no longer exists in the
    # render code -- kept for parity with the pre-extraction behavior (dead
    # data, not dead query cost; flagged, not removed, since that's a separate
    # cleanup decision from this port).
    rr_hist = pd.read_sql_query("""
        SELECT date, sector, rs_score_20, rs_rank
        FROM sector_signals
        WHERE date >= date(?, '-30 days')
        ORDER BY sector, date
    """, conn, params=(latest_rr,))

    rank_10d_ago = pd.read_sql_query("""
        SELECT sector, rs_rank as rank_10d
        FROM sector_signals
        WHERE date = (
            SELECT date FROM sector_signals
            WHERE date <= date(?, '-10 days')
            ORDER BY date DESC LIMIT 1
        )
    """, conn, params=(latest_rr,))

    conn.close()
    return latest_rr, latest_flow, rr_df, rr_hist, rank_10d_ago


def _get_history_sector_ranks():
    if _PG_URL:
        from dashboard_pg import get_history_sector_ranks_pg
        return get_history_sector_ranks_pg()
    conn = sqlite3.connect(DB_PATH)
    latest = pd.read_sql_query(
        "SELECT MAX(date) AS d FROM sector_signals", conn
    ).iloc[0]["d"]
    ranks = pd.read_sql_query(
        """
        SELECT sector, rs_rank, composite_score
        FROM sector_signals
        WHERE date = ? AND rs_rank IS NOT NULL
        ORDER BY rs_rank ASC
        """,
        conn,
        params=(latest,),
    )
    conn.close()
    return latest, ranks


def _get_history_symbol_sectors():
    if _PG_URL:
        from dashboard_pg import get_history_symbol_sectors_pg
        return get_history_symbol_sectors_pg()
    conn = sqlite3.connect(DB_PATH)
    syms = pd.read_sql_query(
        "SELECT symbol, sector FROM sectors WHERE sector IS NOT NULL",
        conn,
    )
    conn.close()
    return syms


def _get_regime_analysis():
    if _PG_URL:
        from dashboard_pg import get_regime_analysis_pg
        return get_regime_analysis_pg()
    sql = """
        WITH labeled AS (
            SELECT
                CASE
                    WHEN regime_at_entry = 'TRENDING_UP'
                         AND (days_since_last_transition IS NULL OR days_since_last_transition >= 6)
                         THEN 'Stable uptrend — favorable conditions'
                    WHEN regime_at_entry = 'TRENDING_UP'
                         AND days_since_last_transition BETWEEN 3 AND 5
                         THEN 'Uptrend settling — moderate caution'
                    WHEN regime_at_entry = 'TRENDING_UP'
                         AND days_since_last_transition <= 2
                         THEN 'Uptrend just started — proceed carefully'
                    WHEN regime_at_entry = 'VOLATILE'
                         THEN 'Choppy conditions — selective only'
                    WHEN regime_at_entry = 'RANGING'
                         THEN 'Narrow range — low activity expected'
                    WHEN regime_at_entry = 'TRENDING_DOWN'
                         THEN 'Down / Short setups only'
                END AS condition_label,
                outcome,
                actual_pl_pct,
                actual_pl_pkr
            FROM trade_setups
            WHERE source = 'Actual'
              AND outcome IN ('Win', 'Loss', 'Breakeven')
        )
        SELECT
            condition_label                                                              AS "Conditions",
            COUNT(*)                                                                     AS "Trades",
            SUM(CASE WHEN outcome = 'Win'  THEN 1 ELSE 0 END)                           AS "Wins",
            SUM(CASE WHEN outcome = 'Loss' THEN 1 ELSE 0 END)                           AS "Losses",
            ROUND(
                100.0 * SUM(CASE WHEN outcome = 'Win' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN outcome IN ('Win','Loss') THEN 1 ELSE 0 END), 0),
                1
            )                                                                            AS "Win Rate %",
            ROUND(AVG(actual_pl_pct), 2)                                                AS "Avg Return %",
            ROUND(SUM(COALESCE(actual_pl_pkr, 0)), 0)                                   AS "Net PnL (PKR)"
        FROM labeled
        WHERE condition_label IS NOT NULL
        GROUP BY condition_label
        ORDER BY "Trades" DESC
    """
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df


def _get_regime_definitions():
    if _PG_URL:
        from dashboard_pg import get_regime_definitions_pg
        return get_regime_definitions_pg()
    sql = """
        WITH labeled AS (
            SELECT
                CASE
                    WHEN ts.regime_at_entry = 'TRENDING_UP'
                         AND (ts.days_since_last_transition IS NULL
                              OR ts.days_since_last_transition >= 6)
                         THEN 'Stable uptrend — favorable conditions'
                    WHEN ts.regime_at_entry = 'TRENDING_UP'
                         AND ts.days_since_last_transition BETWEEN 3 AND 5
                         THEN 'Uptrend settling — moderate caution'
                    WHEN ts.regime_at_entry = 'TRENDING_UP'
                         AND ts.days_since_last_transition <= 2
                         THEN 'Uptrend just started — proceed carefully'
                    WHEN ts.regime_at_entry = 'VOLATILE'
                         THEN 'Choppy conditions — selective only'
                    WHEN ts.regime_at_entry = 'RANGING'
                         THEN 'Narrow range — low activity expected'
                    WHEN ts.regime_at_entry = 'TRENDING_DOWN'
                         THEN 'Down / Short setups only'
                END                           AS condition_label,
                ts.regime_at_entry,
                ts.days_since_last_transition,
                mr.ema_20,
                mr.ema_50,
                mr.ema_200,
                mr.atr_pct,
                mr.return_20d
            FROM trade_setups ts
            LEFT JOIN market_regime mr ON ts.created_date = mr.date
            WHERE ts.source = 'Actual'
              AND ts.regime_at_entry IS NOT NULL
        )
        SELECT
            condition_label,
            regime_at_entry,
            MIN(CASE WHEN days_since_last_transition IS NOT NULL
                     THEN days_since_last_transition END)                AS min_days,
            MAX(days_since_last_transition)                               AS max_days,
            SUM(CASE WHEN days_since_last_transition IS NULL
                     THEN 1 ELSE 0 END)                                  AS null_days_n,
            ROUND(AVG(CASE WHEN ema_20 IS NOT NULL AND ema_50 IS NOT NULL
                           THEN (ema_20 - ema_50) / ema_50 * 100 END), 2) AS avg_ema20_vs_50_pct,
            ROUND(AVG(CASE WHEN ema_50 IS NOT NULL AND ema_200 IS NOT NULL
                           THEN (ema_50 - ema_200) / ema_200 * 100 END), 2) AS avg_ema50_vs_200_pct,
            ROUND(AVG(atr_pct),    2)                                    AS avg_atr_pct,
            ROUND(AVG(return_20d), 2)                                    AS avg_return_20d,
            COUNT(*)                                                      AS n
        FROM labeled
        WHERE condition_label IS NOT NULL
        GROUP BY condition_label, regime_at_entry
    """
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df


# ── Stealth RS (Exploratory — Not Validated) ─────────────────────────────────
# Locked definition (PRE_BREAKOUT_Specification_v1.0.md Section 12/13) now
# lives in stealth_rs.py — single source of truth for both backends
# (compute_stealth_rs() branches internally on _PG_URL; no separate table or
# batch job — Cloud follows exactly what local SQLite does). Do not
# re-implement here. Status: DEAD on the locked confirmatory Validation+OOS
# test (Section 12.8-12.13); a follow-up exploratory (non-confirmatory)
# re-test found the effect recovers outside "runaway bull" regime (Section
# 13) — watch-only, not a validated signal, not scheduled for re-test until
# fresh post-2026-07 data accrues
# (PI target: year-end).
from stealth_rs import compute_stealth_rs as _compute_stealth_rs_live


def _get_explorer_data():
    if _PG_URL:
        from dashboard_pg import get_explorer_data_pg
        return get_explorer_data_pg()
    conn = sqlite3.connect(DB_PATH)
    latest = conn.execute(
        "SELECT MAX(date) FROM stock_signals"
    ).fetchone()[0]

    ex_df = pd.read_sql_query(
        """
        WITH date_5ago AS (
            SELECT date FROM sector_signals
            WHERE date < ?
            ORDER BY date DESC
            LIMIT 1 OFFSET 4
        ),
        sec_5d AS (
            SELECT sector, rs_rank AS rs_rank_5d
            FROM sector_signals
            WHERE date = (SELECT date FROM date_5ago)
        )
        SELECT ss.symbol, s.sector,
               ss.rs_score_20, ss.rs_rank, ss.rs_rank_prev, ss.rank_change,
               ss.sector_rs_rank, ss.base_tightness, ss.pivot_distance_pct,
               ss.bos_flag, ss.avg_vol_10d, ss.vol_contraction, ss.pivot_high,
               ss.stage2_bull,
               ss.close_above_ema50, ss.ema50_slope_pos,
               ss.close_above_ema150, ss.ema150_slope_pos,
               ss.base_duration, ss.overhead_clear, ss.near_pivot_days,
               p.close AS current_close,
               sec.rs_rank              AS sec_global_rank,
               sec.sector_stage         AS sec_stage,
               sec.sector_above_ema     AS sec_above_ema,
               sec.sector_ema_slope     AS sec_ema_slope,
               sec.sector_pivot_dist_pct AS sec_pivot_dist,
               sec.rs_inflection        AS sec_rs_inflection,
               sec.sector_rs_new_high   AS sec_rs_new_high,
               sec5.rs_rank_5d          AS sec_rs_rank_5d
        FROM stock_signals ss
        JOIN sectors s ON ss.symbol = s.symbol
        LEFT JOIN prices p
            ON p.symbol = ss.symbol AND p.date = ss.date
        LEFT JOIN sector_signals sec
            ON sec.date = ss.date AND sec.sector = s.sector
        LEFT JOIN sec_5d sec5 ON sec5.sector = s.sector
        WHERE ss.date = ?
        ORDER BY ss.rs_rank ASC
        """,
        conn,
        params=(latest, latest),
    )
    conn.close()
    return latest, ex_df


# ── E10.5 batch A: extracted data-fetch function (was inline in page-render code) ─

def _get_leaders_rs_data():
    if _PG_URL:
        from dashboard_pg import get_leaders_rs_data_pg
        return get_leaders_rs_data_pg()
    conn = sqlite3.connect(DB_PATH)
    latest = conn.execute(
        "SELECT MAX(date) FROM stock_signals"
    ).fetchone()[0]
    rs_df = pd.read_sql_query("""
        SELECT ss.symbol, sm.sector,
               ss.rs_score_20, ss.rs_score_50,
               ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
               ss.avg_vol_10d
        FROM stock_signals ss
        JOIN stock_metadata sm ON ss.symbol = sm.symbol
        WHERE ss.date = ?
          AND ss.avg_vol_10d > 200000
          AND ss.rs_rank IS NOT NULL
        ORDER BY ss.rs_rank ASC
    """, conn, params=(latest,))
    conn.close()
    return latest, rs_df


def _get_leaders_unified_data():
    """Returns (scan_date, watchlist_df, breakout_date_by_symbol).

    breakout_date_by_symbol replaces the old per-symbol 3-query loop (N+1 --
    3 queries x however many BREAKOUT rows exist) with one query using the
    same two-step "last non-breakout date, then earliest breakout date after
    it" logic, run once for all BREAKOUT symbols via a CTE instead of once
    per symbol. Verified byte-for-byte identical to the original loop's
    output against local SQLite (21/21 symbols matched, including the
    resulting BROKE OUT TODAY / ACTIVE BREAKOUT classification)."""
    if _PG_URL:
        from dashboard_pg import get_leaders_unified_data_pg
        return get_leaders_unified_data_pg()
    conn = sqlite3.connect(DB_PATH)
    scan_date = conn.execute(
        "SELECT MAX(scan_date) FROM leaders_scan"
    ).fetchone()[0]
    if not scan_date:
        conn.close()
        return scan_date, pd.DataFrame(), {}

    df = pd.read_sql_query("""
        SELECT ls.symbol, ls.setup_type, ls.sector, ls.sector_rank,
               ls.rs_rank, ls.rs_score_20, ls.avg_vol_10d,
               ls.base_tightness, ls.pivot_high, ls.pivot_distance_pct,
               ls.vol_ratio_today, ls.vol_contraction, ls.final_score, ls.flag,
               ls.entry_trigger, ls.stop_loss, ls.sl_pct
        FROM leaders_scan ls
        WHERE ls.scan_date = ?
        ORDER BY ls.setup_type DESC, ls.final_score DESC
    """, conn, params=(scan_date,))

    bo_dates_df = pd.read_sql_query("""
        WITH bo_symbols AS (
            SELECT symbol FROM leaders_scan
            WHERE scan_date = ? AND setup_type = 'BREAKOUT'
        ),
        last_zero AS (
            SELECT ss.symbol, MAX(ss.date) AS last_zero_date
            FROM stock_signals ss
            WHERE ss.symbol IN (SELECT symbol FROM bo_symbols)
              AND ss.bos_flag = 0
              AND ss.date <= ?
            GROUP BY ss.symbol
        )
        SELECT b.symbol, MIN(ss.date) AS breakout_date
        FROM bo_symbols b
        LEFT JOIN last_zero lz ON lz.symbol = b.symbol
        JOIN stock_signals ss
            ON ss.symbol = b.symbol
           AND ss.bos_flag = 1
           AND (lz.last_zero_date IS NULL OR ss.date > lz.last_zero_date)
        GROUP BY b.symbol
    """, conn, params=(scan_date, scan_date))
    conn.close()

    bo_dates = dict(zip(bo_dates_df['symbol'], bo_dates_df['breakout_date']))
    return scan_date, df, bo_dates


def _get_leaders_deepscan_data():
    """Returns (scan_date, picks_df, audit_df) for the Deep Scan tab."""
    if _PG_URL:
        from dashboard_pg import get_leaders_deepscan_data_pg
        return get_leaders_deepscan_data_pg()
    conn = sqlite3.connect(DB_PATH)
    scan_date = conn.execute(
        "SELECT MAX(scan_date) FROM leaders_scan"
    ).fetchone()[0]
    if not scan_date:
        conn.close()
        return scan_date, pd.DataFrame(), pd.DataFrame()

    # Join top_picks with scan detail + sector breadth
    picks_df = pd.read_sql_query("""
        SELECT lp.rank, lp.setup_type, lp.symbol, lp.sector, lp.sector_rank,
               lp.entry_trigger, lp.stop_loss, lp.sl_pct,
               lp.vol_ratio_today, lp.key_reason, lp.flag,
               ls.rs_score_20, ls.rs_score_50, ls.rank_change,
               ls.base_tightness, ls.rs_inflection, ls.vol_rejection_flag,
               ls.nearest_overhead_pct, ls.avg_vol_10d,
               ls.pivot_distance_pct, ls.final_score,
               sec.breadth_score
        FROM leaders_top_picks lp
        JOIN leaders_scan ls
            ON ls.scan_date = lp.scan_date
           AND ls.setup_type = lp.setup_type
           AND ls.symbol = lp.symbol
        LEFT JOIN sector_signals sec
            ON sec.sector = lp.sector AND sec.date = lp.scan_date
        WHERE lp.scan_date = ?
        ORDER BY lp.setup_type DESC, lp.rank ASC
    """, conn, params=(scan_date,))

    audit_df = pd.read_sql_query("""
        SELECT scan_date, setup_type, rank, symbol, sector,
               entry_trigger, sl_pct,
               triggered, trigger_date,
               fwd_return_5d, fwd_return_10d, fwd_return_20d,
               outcome_label, key_reason, flag
        FROM leaders_top_picks
        WHERE scan_date <= date('now', '-10 days')
        ORDER BY scan_date DESC, setup_type, rank
    """, conn)
    conn.close()
    return scan_date, picks_df, audit_df


def _get_leaders_radar_data():
    """Returns (rd_date, cands_df, bos_df, sec_rows_df, top_picks_df) for the
    Radar tab. sec_rows_df is unfiltered here -- the .isin(all_sectors)
    filter stays inline at the call site since it depends on candidate data
    computed after this returns. _rd_trajectory()'s own 30-day-history query
    is intentionally NOT included -- that's batch E, reviewed on its own."""
    if _PG_URL:
        from dashboard_pg import get_leaders_radar_data_pg
        return get_leaders_radar_data_pg()
    conn = sqlite3.connect(DB_PATH)
    rd_date = conn.execute(
        "SELECT MAX(scan_date) FROM leaders_scan"
    ).fetchone()[0]
    if not rd_date:
        conn.close()
        return rd_date, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    cands_df = pd.read_sql_query("""
        SELECT ls.symbol, ls.sector, ls.sector_rank, ls.rs_rank,
               ls.sector_rs_rank, ls.rs_score_20, ls.rs_score_50,
               ls.rank_change, ls.avg_vol_10d, ls.base_tightness,
               ls.pivot_distance_pct, ls.pivot_high, ls.vol_ratio_today,
               ls.vol_rejection_flag, ls.rs_inflection, ls.nearest_overhead_pct,
               ls.sector_composite, ls.raw_score, ls.penalty, ls.final_score,
               ls.flag, ls.entry_trigger, ls.stop_loss, ls.sl_pct,
               sec.breadth_score, sec.regime
        FROM leaders_scan ls
        LEFT JOIN sector_signals sec
            ON sec.sector = ls.sector AND sec.date = ls.scan_date
        WHERE ls.scan_date = ? AND ls.setup_type = 'PRE_BREAKOUT'
        ORDER BY ls.final_score DESC
    """, conn, params=(rd_date,))

    bos_df = pd.read_sql_query("""
        SELECT ls.symbol, ls.sector, ls.sector_rank, ls.rs_rank,
               ls.rs_score_20, ls.rs_score_50, ls.rank_change,
               ls.avg_vol_10d, ls.base_tightness, ls.pivot_distance_pct,
               ls.pivot_high, ls.vol_ratio_today, ls.vol_rejection_flag,
               ls.rs_inflection, ls.nearest_overhead_pct,
               ls.sector_composite, ls.final_score, ls.flag,
               ls.entry_trigger, ls.stop_loss, ls.sl_pct,
               sec.breadth_score, sec.regime
        FROM leaders_scan ls
        LEFT JOIN sector_signals sec
            ON sec.sector = ls.sector AND sec.date = ls.scan_date
        WHERE ls.scan_date = ? AND ls.setup_type = 'BREAKOUT'
        ORDER BY ls.final_score DESC
    """, conn, params=(rd_date,))

    sec_rows_df = pd.read_sql_query("""
        SELECT ss.sector, ss.composite_score AS composite, ss.breadth_score, ss.rs_rank,
               ss.rs_inflection, ss.regime,
               RANK() OVER (ORDER BY ss.composite_score DESC) AS rank_today
        FROM sector_signals ss
        WHERE ss.date = ?
        ORDER BY rank_today
    """, conn, params=(rd_date,))

    top_picks_df = pd.read_sql_query("""
        SELECT lp.rank, lp.setup_type, lp.symbol, lp.sector, lp.sector_rank,
               lp.entry_trigger, lp.stop_loss, lp.sl_pct,
               lp.vol_ratio_today, lp.key_reason, lp.flag,
               ls.rs_score_20, ls.rs_score_50, ls.rank_change,
               ls.base_tightness, ls.rs_inflection, ls.vol_rejection_flag,
               ls.nearest_overhead_pct, ls.avg_vol_10d,
               ls.pivot_distance_pct, ls.final_score,
               sec.breadth_score
        FROM leaders_top_picks lp
        JOIN leaders_scan ls
            ON ls.scan_date = lp.scan_date
           AND ls.setup_type = lp.setup_type
           AND ls.symbol = lp.symbol
        LEFT JOIN sector_signals sec
            ON sec.sector = lp.sector AND sec.date = lp.scan_date
        WHERE lp.scan_date = ?
        ORDER BY lp.setup_type DESC, lp.rank ASC
    """, conn, params=(rd_date,))
    conn.close()
    return rd_date, cands_df, bos_df, sec_rows_df, top_picks_df


def _get_sector_composite_history(sector, before_date):
    """30-day trailing composite_score history for one sector, called once
    per sector from _rd_trajectory() (Radar tab, Step 2). Returns the same
    shape sqlite3's .fetchall() always has -- a list of 1-tuples -- so
    _rd_trajectory()'s own unwrapping line (`[r[0] for r in hist ...]`)
    needs no change on either backend.

    This is the fix for the confirmed Decimal - numpy.float64 TypeError:
    composite_score is NUMERIC in Postgres, so an uncast raw-cursor fetch
    returns Decimal while composite_today (fed from
    _get_leaders_radar_data()'s sec_rows_df, already coerced to float64 by
    batch D) is a plain float. Casting composite_score to DOUBLE PRECISION
    in the query itself makes psycopg2 return a native float directly, no
    Decimal involved at any point -- verified identical to the existing
    convention in database_pg.py's get_sector_signals_latest(), not just
    assumed to match it."""
    if _PG_URL:
        from dashboard_pg import get_sector_composite_history_pg
        return get_sector_composite_history_pg(sector, before_date)
    conn = sqlite3.connect(DB_PATH)
    hist = conn.execute("""
        SELECT composite_score FROM sector_signals
        WHERE sector=? AND date < ?
        ORDER BY date DESC LIMIT 30
    """, (sector, before_date)).fetchall()
    conn.close()
    return hist


def _render_boring_breakouts_section():
    """
    'Boring Breakouts' toggle content — RS_60-conditioned Donchian breakout,
    manual-execution workflow. Locked spec:
    boring_study/boring_study_trading_rulebook_v1_2026-07-11.md (Addenda A-C
    applied). Columns and badge logic are locked; do not add a graded score
    here (Addendum C: a star rating was investigated and explicitly rejected
    — granular RS depth and sector-clustering both failed to survive scrutiny).
    """
    if _PG_URL:
        # Hard-blocked on purpose, same reasoning and same pattern as the
        # Data Health Confirm button (see CLAUDE.md "Known Gaps"):
        # boring_signals.py is 100% SQLite (sqlite3.connect(DB_PATH)
        # hardcoded, no _PG_URL branch anywhere in it), and it depends on
        # stock_metadata/sectors/prices_adjusted being fully populated,
        # which on Streamlit Cloud they aren't (no local SQLite file exists
        # there at all -- see CLAUDE.md "Streamlit Cloud constraints").
        # Letting this through would throw a raw connection error the
        # moment a user reaches this section. Nothing is written or read
        # below -- boring_signals is never imported on this path.
        st.error(
            "🎯 Boring Breakouts is not available on Streamlit Cloud yet. "
            "`boring_signals.py` is SQLite-only (no Postgres port) and depends on local "
            "tables (`stock_metadata`, `sectors`, `prices_adjusted`) that don't exist on "
            "Cloud's ephemeral filesystem. This section only works when run locally against "
            "`psx_data.db`. See CLAUDE.md 'Known Gaps' for the Postgres port needed to close this."
        )
        return

    from boring_signals import get_boring_signals, mark_executed

    st.caption(
        "Locked table: Ticker · RS_60 Decile · Breakout Level · Entry Price · "
        "Stop (trailing) · Status · Action. Breakout Level (1.01× prior high) is the threshold "
        "that had to be cleared — Entry Price (the close) is often above it, not equal to it. "
        "Exit is a live HYBRID trailing stop (prior-day low, floored at -8% from entry, "
        "recomputed daily) — there is no fixed take-profit target in this system. "
        "Both N=20 and N=60 Donchian definitions are shown (never merged — see rulebook §2). "
        "This is a watch-and-manually-execute list, not an auto-trader."
    )

    _bo_df = get_boring_signals()
    if _bo_df.empty:
        st.info("No Boring Breakout signals yet. Signals populate via the daily `main.py --update` hook.")
        return

    _bo_col1, _bo_col2 = st.columns([2, 1])
    _bo_status_filter = _bo_col1.multiselect(
        "Status", ["Pending", "Executed", "Target Hit", "Stopped", "Expired"],
        default=["Pending", "Executed"], key="boring_status_filter",
    )
    _bo_confirmed_only = _bo_col2.checkbox(
        "Strategy Confirmed only", value=True, key="boring_confirmed_only",
        help="Off shows every Donchian breakout in the eligible universe, including ones that "
             "fail the RS_60 top-decile or liquidity gate — off by default because those aren't "
             "trade candidates, just raw scan output.",
    )
    _bo_show = _bo_df[_bo_df["status"].isin(_bo_status_filter)].copy() if _bo_status_filter else _bo_df.copy()
    if _bo_confirmed_only:
        _bo_show = _bo_show[_bo_show["strategy_confirmed"] == 1]

    if _bo_show.empty:
        st.info("No signals match the current filters.")
    else:
        # Collapse N=20/N=60 rows for the SAME symbol+signal_date into one
        # displayed row -- both use the identical Close(t) entry and the same
        # trailing-stop walk (RS_60, decile, and liquidity too; N only
        # changes which Donchian window confirmed the breakout), so two rows
        # here would just be the same real-world trade shown twice.
        # Underlying rows stay separate in the database (each keeps its own
        # id) for research/audit fidelity; only the display and the Execute
        # action are collapsed.
        _bo_show["confirmed_badge"] = _bo_show["strategy_confirmed"].apply(
            lambda v: "✅ Confirmed" if v == 1 else "❌ No Fit"
        )
        _bo_grouped = (
            _bo_show.groupby(["symbol", "signal_date"], as_index=False)
            .agg(
                ids=("id", list),
                lookback_n=("lookback_n", lambda s: "+".join(str(int(x)) for x in sorted(s))),
                rs_60_decile=("rs_60_decile", "first"),
                confirmed_badge=("confirmed_badge", "first"),
                # breakout_level CAN differ between N=20/N=60 (each has its own prior-high
                # window) even though trigger_price/current_stop can't (those only depend
                # on Close(t) and the shared trailing-stop walk) -- take the higher
                # (stricter) threshold when they differ.
                breakout_level=("breakout_level", "max"),
                trigger_price=("trigger_price", "first"),
                current_stop=("current_stop", "first"),
                status=("status", "first"),
            )
        )

        # current_stop is NULL until update_open_signal_statuses() has
        # successfully processed this row at least once (a brand-new row
        # from the same run cycle, or a row whose symbol hit a data gap) --
        # render that explicitly rather than letting a NULL silently show
        # as blank or coerce to 0, which would look like "stop = 0", not
        # "not computed yet."
        _bo_grouped["stop_display"] = _bo_grouped["current_stop"].apply(
            lambda v: f"{v:.2f}" if pd.notna(v) else "Not yet computed"
        )

        _bo_editor_cols = [
            "symbol", "signal_date", "lookback_n", "rs_60_decile", "confirmed_badge",
            "breakout_level", "trigger_price", "stop_display", "status",
        ]
        _bo_editor_names = [
            "Ticker", "Fire Date", "N", "RS_60 Decile", "Strategy Fit",
            "Breakout Level", "Entry Price", "Stop (trailing)", "Status",
        ]
        _bo_disp = _bo_grouped[_bo_editor_cols].copy()
        _bo_disp.columns = _bo_editor_names
        _bo_disp["Mark Executed"] = False  # action column -- checked rows get executed on submit

        _bo_edited = st.data_editor(
            _bo_disp,
            column_config={
                "Breakout Level": st.column_config.NumberColumn(
                    format="%.2f", help="1.01 x prior N-day high -- the level that had to be "
                                         "cleared. Entry Price (the close) is often above this, "
                                         "not equal to it -- that's expected, not a contradiction."),
                "Entry Price": st.column_config.NumberColumn(format="%.2f"),
                "Stop (trailing)": st.column_config.TextColumn(
                    help="Live HYBRID trailing stop: prior-day low, ratcheting up, floored at "
                         "-8% from entry. Updates daily via update_open_signal_statuses() -- "
                         "not a fixed entry-day level. 'Not yet computed' means this row hasn't "
                         "been processed by that function yet, not that there's no stop."),
                "Mark Executed": st.column_config.CheckboxColumn(
                    help="Check and press Execute Marked below to record this trade as taken."
                ),
            },
            disabled=["Ticker", "Fire Date", "N", "RS_60 Decile", "Strategy Fit", "Breakout Level",
                      "Entry Price", "Stop (trailing)", "Status"],
            hide_index=True, use_container_width=True, height=360, key="boring_editor",
        )

        if st.button("Execute Marked", key="boring_execute_btn"):
            _to_execute_rows = _bo_edited[_bo_edited["Mark Executed"] == True]
            _n_signals = 0
            for _pos in _to_execute_rows.index:
                for _sig_id in _bo_grouped.loc[_pos, "ids"]:
                    mark_executed(int(_sig_id))
                    _n_signals += 1
            if _n_signals:
                st.success(f"Marked {len(_to_execute_rows)} trade(s) ({_n_signals} underlying signal row(s)) as Executed.")
                st.rerun()
            else:
                st.info("No rows checked.")

    # Resolved (Stopped) history -- deliberately outside/after the open-positions
    # if/else above, so it renders regardless of whether the main table is empty.
    # Read-only: nothing here is actionable on an already-resolved trade, so no
    # Mark Executed checkbox, no data_editor, no Execute button.
    with st.expander("Resolved (Stopped)", expanded=False):
        _bo_stopped = get_boring_signals(status="Stopped")
        if _bo_confirmed_only:
            _bo_stopped = _bo_stopped[_bo_stopped["strategy_confirmed"] == 1]

        if _bo_stopped.empty:
            st.info("No resolved (Stopped) signals yet.")
        else:
            _bo_stopped_grouped = (
                _bo_stopped.groupby(["symbol", "signal_date"], as_index=False)
                .agg(
                    lookback_n=("lookback_n", lambda s: "+".join(str(int(x)) for x in sorted(s))),
                    trigger_price=("trigger_price", "first"),
                    current_stop=("current_stop", "first"),
                    status=("status", "first"),
                    resolution_date=("resolution_date", "first"),
                )
                # groupby re-sorts by the group keys -- re-apply the "most recent
                # fire date first" order the underlying query already had before
                # capping, rather than assuming groupby preserved it.
                .sort_values("signal_date", ascending=False)
                .head(30)
            )
            _res_cols = ["symbol", "signal_date", "lookback_n", "trigger_price",
                         "current_stop", "status", "resolution_date"]
            _res_names = ["Ticker", "Fire Date", "N", "Entry Price",
                          "Stop (final)", "Status", "Resolution Date"]
            _res_disp = _bo_stopped_grouped[_res_cols].copy()
            _res_disp.columns = _res_names
            st.dataframe(_res_disp, hide_index=True, use_container_width=True)


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

        # ── Top-Down View — Index → Sector → Stock ───────────────────────────
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        st.divider()
        st.markdown("### 🔭 Top-Down View — Index → Sector → Stock")
        st.caption("Gate 1 must be green before looking at sectors. Sectors sorted by RS Rank; score ≥ 0.50 confirms.")

        try:
            _td_latest, _td_sectors = _get_market_gates_sectors()

            _td_gate_color  = "#22c55e" if kse_above_ma else "#ef4444"
            _td_gate_label  = "OPEN — index above 50MA" if kse_above_ma else "CLOSED — index below 50MA"
            _td_gate_advice = "Look at top sectors below." if kse_above_ma else "Do not go long. Sit out or short only."
            st.markdown(
                f"<div style='background:{_td_gate_color}15; border-left:4px solid {_td_gate_color}; "
                f"padding:8px 16px; border-radius:6px; margin-bottom:12px; "
                f"display:flex; align-items:center; gap:16px;'>"
                f"<span style='font-size:0.9rem; font-weight:800; color:{_td_gate_color}; white-space:nowrap;'>"
                f"{'✅' if kse_above_ma else '🚫'} Gate 1: {_td_gate_label}</span>"
                f"<span style='font-size:0.78rem; color:#64748b;'>{_td_gate_advice}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            if not _td_sectors.empty:
                _td_top = _td_sectors.head(8).copy()
                _td_html_rows = ""
                for _, _r in _td_top.iterrows():
                    _rank  = int(_r["rs_rank"])
                    _rs    = _r["rs_score_20"]
                    _score = _r["composite_score"]
                    _bread = _r["breadth_score"]
                    _infl  = int(_r["rs_inflection"]) if pd.notna(_r["rs_inflection"]) else 0

                    if _score is not None and _score >= 0.50:
                        _sc = "#22c55e"; _sc_bg = "#f0fdf4"
                    elif _score is not None and _score >= 0.35:
                        _sc = "#f59e0b"; _sc_bg = "#fffbeb"
                    else:
                        _sc = "#94a3b8"; _sc_bg = "#f8fafc"

                    _rs_str = f"+{_rs:.1f}" if _rs is not None and _rs >= 0 else (f"{_rs:.1f}" if _rs is not None else "—")
                    _rs_col = "#22c55e" if (_rs is not None and _rs >= 0) else "#ef4444"
                    _infl_badge = " <span style='font-size:0.65rem; background:#dbeafe; color:#1d4ed8; border-radius:3px; padding:1px 5px; font-weight:700;'>↑ NEW</span>" if _infl else ""

                    _td_html_rows += (
                        f"<tr style='border-bottom:1px solid #f1f5f9;'>"
                        f"<td style='padding:7px 10px; font-weight:800; color:#334155; font-size:0.82rem;'>#{_rank}</td>"
                        f"<td style='padding:7px 10px; font-size:0.82rem; color:#1e293b; font-weight:600;'>{_r['sector']}{_infl_badge}</td>"
                        f"<td style='padding:7px 10px; font-size:0.82rem; color:{_rs_col}; font-weight:700;'>{_rs_str}</td>"
                        f"<td style='padding:7px 10px;'><span style='background:{_sc_bg}; color:{_sc}; font-weight:700; font-size:0.78rem; border-radius:4px; padding:2px 8px;'>{_score:.2f}</span></td>"
                        f"<td style='padding:7px 10px; font-size:0.78rem; color:#64748b;'>{_bread:.0f}%</td>"
                        f"</tr>"
                    )

                st.markdown(
                    f"<table style='width:100%; border-collapse:collapse; font-family:inherit;'>"
                    f"<thead><tr style='background:#f8fafc; border-bottom:2px solid #e2e8f0;'>"
                    f"<th style='padding:6px 10px; text-align:left; font-size:0.72rem; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;'>Rank</th>"
                    f"<th style='padding:6px 10px; text-align:left; font-size:0.72rem; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;'>Sector</th>"
                    f"<th style='padding:6px 10px; text-align:left; font-size:0.72rem; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;'>RS vs Index</th>"
                    f"<th style='padding:6px 10px; text-align:left; font-size:0.72rem; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;'>Score</th>"
                    f"<th style='padding:6px 10px; text-align:left; font-size:0.72rem; color:#64748b; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;'>Breadth</th>"
                    f"</tr></thead>"
                    f"<tbody>{_td_html_rows}</tbody>"
                    f"</table>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "<div style='font-size:0.7rem; color:#94a3b8; margin-top:8px;'>"
                    "RS vs Index = sector 20d return minus KSE-100 20d return. "
                    "Score ≥ 0.50 = strong (green), 0.35–0.50 = moderate (amber). "
                    "↑ NEW = sector just moved up in rank with positive RS. "
                    f"As of {fmt_date(_td_latest)}.</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.info("Sector data not yet available for today.")

        except Exception as _td_err:
            st.warning(f"Top-down panel error: {_td_err}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — MARKET (shifted from PAGES[1])
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[2]:  # Market

    tab1, tab2 = st.tabs(["📊 Sector Performance", "🔄 Rotation Radar"])

    with tab1:
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

    with tab2:
        # ── Rotation Radar ──────────────────────────────────────────
        try:
            latest_rr, latest_flow, rr_df, rr_hist, rank_10d_ago = _get_rotation_radar_data()

            # ── Header ──────────────────────────────────────────────
            regime_val = rr_df["regime"].iloc[0] if not rr_df.empty else "—"
            regime_colors = {
                "TRENDING_UP":   "#22c55e",
                "TRENDING_DOWN": "#ef4444",
                "VOLATILE":      "#fbbf24",
                "RANGING":       "#94a3b8",
            }
            rc = regime_colors.get(regime_val, "#94a3b8")

            st.markdown(
                f"**Rotation Radar** &nbsp;&nbsp;"
                f"<span style='font-size:0.8rem; color:{rc}; "
                f"background:#1e293b; padding:2px 8px; border-radius:4px;'>"
                f"● {regime_val}</span>"
                f"<span style='font-size:0.75rem; color:#64748b;'>"
                f" &nbsp; as of {latest_rr}</span>",
                unsafe_allow_html=True,
            )

            st.divider()

            # ── Composite Score Bar Chart ────────────────────────────
            if HAS_PLOTLY:
                rr_chart = rr_df.sort_values("composite_score")
                fig_rr = px.bar(
                    rr_chart,
                    x="composite_score",
                    y="sector",
                    orientation="h",
                    color="composite_score",
                    color_continuous_scale=["#ef4444", "#fbbf24", "#22c55e"],
                    color_continuous_midpoint=0.5,
                    labels={"composite_score": "Composite Score", "sector": ""},
                    text=rr_chart["composite_score"].apply(
                        lambda v: f"{v:.2f}" if v is not None else ""
                    ),
                )
                fig_rr.update_traces(textposition="outside", textfont_size=11)
                fig_rr.update_layout(
                    height=max(340, len(rr_chart) * 24),
                    showlegend=False, coloraxis_showscale=False,
                    yaxis={
                        "categoryorder": "total ascending",
                        "tickfont": {"size": 11},
                    },
                    xaxis={"tickfont": {"size": 10}, "range": [0, 1.15]},
                    margin={"l": 4, "r": 70, "t": 8, "b": 8},
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_rr, use_container_width=True)

            st.divider()

            # ── Rotation Radar Table ─────────────────────────────────
            st.markdown("**Sector Signal Table**")

            rr_display = rr_df.copy()

            rr_display = rr_display.merge(rank_10d_ago, on="sector", how="left")
            rr_display["trend"] = rr_display.apply(
                lambda r: "▲" if (
                    pd.notna(r["rank_10d"]) and r["rs_rank"] < r["rank_10d"]
                ) else ("▼" if (
                    pd.notna(r["rank_10d"]) and r["rs_rank"] > r["rank_10d"]
                ) else "─"),
                axis=1,
            )

            # Inflection flag display
            rr_display["signal"] = rr_display["rs_inflection"].apply(
                lambda v: "🔥" if v == 1 else ""
            )

            # Stage display with colour emoji
            _stage_icons = {
                "Stage 2": "🟢 Stage 2",
                "Stage 3": "🟡 Stage 3",
                "Stage 4": "🔴 Stage 4",
                "Stage 1": "⚪ Stage 1",
            }
            rr_display["Stage"] = rr_display["sector_stage"].map(_stage_icons).fillna("—")

            # Pivot distance (how close to breakout)
            rr_display["Pivot%"] = rr_display["sector_pivot_dist_pct"].apply(
                lambda v: f"{v:.1f}%" if pd.notna(v) else "—"
            )

            # Format columns
            rr_display["rs_score_20"] = rr_display["rs_score_20"].apply(
                lambda v: f"{v:+.2f}" if pd.notna(v) else "—"
            )
            rr_display["breadth_score"] = rr_display["breadth_score"].apply(
                lambda v: f"{v:.1f}%" if pd.notna(v) else "—"
            )
            rr_display["vol_ratio"] = rr_display["vol_ratio"].apply(
                lambda v: f"{v:.2f}x" if pd.notna(v) else "—"
            )
            rr_display["composite_score"] = rr_display["composite_score"].apply(
                lambda v: f"{v:.3f}" if pd.notna(v) else "—"
            )

            table_cols = {
                "rs_rank":         "#",
                "sector":          "Sector",
                "Stage":           "Stage",
                "Pivot%":          "→Pivot",
                "signal":          "🔥",
                "trend":           "RS Trend",
                "rs_score_20":     "RS-20",
                "breadth_score":   "Breadth",
                "vol_ratio":       "Vol Ratio",
                "composite_score": "Score",
            }

            st.dataframe(
                rr_display[list(table_cols.keys())].rename(columns=table_cols),
                use_container_width=True,
                hide_index=True,
                height=max(600, (len(rr_display) + 1) * 38),
            )

            # ── Legend ───────────────────────────────────────────────
            st.markdown(
                """<div style="font-size:0.7rem; color:#64748b; line-height:2;">
                <b>Stage</b> Weinstein stage from sector price index vs 50 EMA (🟢=2 🟡=3 🔴=4 ⚪=1) &nbsp;|&nbsp;
                <b>→Pivot</b> % below sector's 20-day high — 0% = at pivot &nbsp;|&nbsp;
                <b>RS-20</b> sector return vs KSE-100 over 20 days (%) &nbsp;|&nbsp;
                <b>Breadth</b> % stocks above 20d EMA &nbsp;|&nbsp;
                <b>Vol Ratio</b> today vs 20d avg volume &nbsp;|&nbsp;
                <b>Score</b> composite (RS 50% + Breadth 30% + Vol 20%) &nbsp;|&nbsp;
                <b>🔥</b> RS inflection — sector turning up
                </div>""",
                unsafe_allow_html=True,
            )

        except Exception as e:
            st.warning(f"Rotation Radar unavailable: {e}")



# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[4]:  # History
    st.markdown("**Sector Price Chart** — market-cap weighted sector index with 50-day EMA (base = 100 at window start)")
    st.caption(
        "🟢 Price above rising EMA = Stage 2 · 🟡 Price above flat/falling EMA = Stage 3 · "
        "🔴 Price below falling EMA = Stage 4 · ⚪ Price below rising EMA = Stage 1. "
        "Sectors ordered by current RS Rank (strongest first)."
    )

    try:
        import plotly.graph_objects as go

        # ── Load sector RS ranks from sector_signals ──────────────────────────
        _hist_latest, _hist_ranks = _get_history_sector_ranks()

        # ── Build ordered sector list with rank label ──────────────────────────
        if not _hist_ranks.empty:
            _hist_ordered = _hist_ranks["sector"].tolist()
            _hist_label_map = {
                row["sector"]: f"{row['sector']}  (#{int(row['rs_rank'])})"
                for _, row in _hist_ranks.iterrows()
            }
        else:
            # Fallback: alphabetical with no rank labels
            _hist_ordered = sorted(sector_df["sector"].tolist())
            _hist_label_map = {s: s for s in _hist_ordered}

        _hist_labels    = [_hist_label_map[s] for s in _hist_ordered]
        _hist_label_inv = {v: k for k, v in _hist_label_map.items()}  # label → sector name

        default_labels = _hist_labels[:5]
        selected_labels = st.multiselect(
            "Compare sectors (ordered by RS Rank — strongest first)",
            options=_hist_labels,
            default=default_labels,
        )
        selected_hist = [_hist_label_inv[lbl] for lbl in selected_labels]

        # ── Get sector membership from sectors table ───────────────────────────
        _hist_syms_df = _get_history_symbol_sectors()

        colors_pool = [
            "#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6",
            "#06b6d4","#f97316","#84cc16","#ec4899","#14b8a6",
        ]

        if selected_hist:
            fig_hist = go.Figure()
            for i, sec in enumerate(selected_hist):
                syms = tuple(_hist_syms_df.loc[_hist_syms_df["sector"] == sec, "symbol"].tolist())
                if not syms:
                    continue
                h = load_sector_history(syms)
                if h.empty:
                    continue
                rank_lbl = _hist_label_map.get(sec, sec)
                lc = colors_pool[i % len(colors_pool)]
                # Sector price index
                fig_hist.add_trace(go.Scatter(
                    x=h["date"], y=h["index_value"].round(2),
                    mode="lines", name=rank_lbl,
                    line={"width": 2, "color": lc},
                    hovertemplate=f"<b>{rank_lbl}</b><br>%{{x|%d %b %Y}}: %{{y:.1f}}<extra></extra>",
                ))
                # EMA50 overlay — same colour, dashed, thinner
                _ema50_vals = h["index_value"].ewm(span=50, adjust=False).mean().round(2)
                fig_hist.add_trace(go.Scatter(
                    x=h["date"], y=_ema50_vals,
                    mode="lines", name=f"{rank_lbl} EMA50",
                    line={"width": 1.2, "color": lc, "dash": "dash"},
                    hovertemplate=f"<b>{rank_lbl} EMA50</b><br>%{{x|%d %b %Y}}: %{{y:.1f}}<extra></extra>",
                ))
            fig_hist.add_hline(y=100, line_dash="dot", line_color="#94a3b8",
                               annotation_text="Base (1yr ago)", annotation_position="bottom right")
            fig_hist.update_layout(
                height=520,
                hovermode="closest",
                xaxis_title="", yaxis_title="Index (Base = 100)",
                legend={"orientation": "h", "y": 1.08, "x": 0, "font": {"size": 10}},
                margin={"l": 4, "r": 4, "t": 32, "b": 8},
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis={"gridcolor": "#1e293b"},
                yaxis={"gridcolor": "#1e293b"},
            )
            st.plotly_chart(fig_hist, use_container_width=True)

            # ── RS rank table below chart ──────────────────────────────────────
            if not _hist_ranks.empty:
                _hist_shown = _hist_ranks[_hist_ranks["sector"].isin(selected_hist)].copy()
                _hist_shown = _hist_shown.rename(columns={
                    "sector": "Sector", "rs_rank": "RS Rank", "composite_score": "Composite Score"
                })
                _hist_shown["Composite Score"] = _hist_shown["Composite Score"].apply(
                    lambda v: f"{v:.2f}" if pd.notna(v) else "—"
                )
                st.dataframe(_hist_shown, use_container_width=True, hide_index=True)
        else:
            st.info("Select at least one sector.")
    except ImportError:
        st.warning("Plotly visualization library is not available.")
    except Exception as _hist_err:
        st.warning(f"History page error: {_hist_err}")


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
        for col in ["exit_date", "actual_exit", "actual_pl_pct", "holding_days", "actual_entry",
                    "regime_at_entry", "days_since_last_transition"]:
            if col not in log_df.columns:
                log_df[col] = None

        def _regime_label(regime, days_since):
            """Map regime + days_since_last_transition to locked plain-language label."""
            try:
                d = int(days_since) if days_since is not None and days_since == days_since else None
            except (TypeError, ValueError):
                d = None
            if regime == "TRENDING_UP":
                if d is None:        return "Stable uptrend — favorable conditions"
                elif d >= 6:         return "Stable uptrend — favorable conditions"
                elif d >= 3:         return "Uptrend settling — moderate caution"
                else:                return "Uptrend just started — proceed carefully"
            elif regime == "VOLATILE":      return "Choppy conditions — selective only"
            elif regime == "RANGING":       return "Narrow range — low activity expected"
            elif regime == "TRENDING_DOWN": return "Downtrend — untested in your history"
            return "—"

        display_log = log_df[[
            "id", "created_date", "regime_at_entry", "days_since_last_transition",
            "exit_date", "direction", "symbol",
            "entry_price", "stop_loss", "actual_exit",
            "risk_pct", "actual_pl_pct", "holding_days",
            "status", "outcome", "notes",
        ]].copy()
        display_log.columns = [
            "ID", "Entry Date", "Regime", "Days▲",
            "Exit Date", "Dir", "Symbol",
            "Entry", "SL", "Exit",
            "Risk%", "P&L%", "Days",
            "Status", "Outcome", "Notes",
        ]
        display_log.insert(
            2, "Conditions",
            display_log.apply(
                lambda r: _regime_label(r["Regime"], r["Days▲"]), axis=1
            ),
        )
        display_log["Entry Date"] = display_log["Entry Date"].apply(fmt_date)
        display_log["Exit Date"]  = display_log["Exit Date"].apply(fmt_date)

        _LABEL_PROCEED   = "Uptrend just started — proceed carefully"
        _LABEL_DOWNTREND = "Downtrend — untested in your history"

        def style_conditions(series):
            out = []
            for v in series:
                if v == _LABEL_PROCEED:
                    # Amber warning — quantified risk zone
                    out.append("background-color:#fef3c7; color:#92400e; font-weight:600")
                elif v == _LABEL_DOWNTREND:
                    # Blue-grey neutral — total unknown, visually distinct from amber
                    out.append("background-color:#e8edf2; color:#475569; font-style:italic")
                else:
                    out.append("")
            return out

        def style_transition_proximity(series):
            """Amber background on Days▲ values 0-2 (quantified risk zone)."""
            out = []
            for v in series:
                try:
                    if v is not None and not pd.isna(v) and int(v) <= 2:
                        out.append("background-color:#fef3c7; color:#92400e; font-weight:bold")
                    else:
                        out.append("")
                except (TypeError, ValueError):
                    out.append("")
            return out

        fmt_map = {
            "Entry": "{:.2f}", "SL": "{:.2f}", "Exit": "{:.2f}",
            "Risk%": "{:.2f}", "P&L%": "{:.2f}", "Days": "{:.0f}",
            "Days▲": "{:.0f}",
        }
        st.dataframe(
            display_log.style
            .apply(style_direction,            subset=["Dir"])
            .apply(style_outcome,              subset=["Outcome"])
            .apply(style_pct_cols,             subset=["P&L%"])
            .apply(style_conditions,           subset=["Conditions"])
            .apply(style_transition_proximity, subset=["Days▲"])
            .format(fmt_map, na_rep="—"),
            use_container_width=True, hide_index=True,
            height=min(900, max(200, (len(display_log) + 1) * 38)),
        )
        st.caption(
            "**Conditions** = market regime context at entry  ·  "
            "**Regime** = raw classification  ·  "
            "**Days▲** = trading days since last regime transition  ·  "
            "Amber = proceed carefully (0–2 days)  ·  "
            "Grey-blue = untested regime (no history)"
        )

    # ── Regime Performance Analysis ───────────────────────────────────────────
    if actual_trades:
        st.divider()
        st.markdown("**Regime Performance Analysis**")
        st.caption(
            "Win rate and returns for your Actual closed trades, grouped by the 6 market conditions. "
            "Only trades with a recorded Win / Loss / Breakeven outcome are counted."
        )
        try:
            ra_df = _get_regime_analysis()
        except Exception as _ra_err:
            ra_df = pd.DataFrame()
            st.warning(f"Regime analysis query failed: {_ra_err}")

        if not ra_df.empty:
            # ── Condition ordering (fixed, most to least favorable) ───────────
            _COND_ORDER = [
                "Stable uptrend — favorable conditions",
                "Uptrend settling — moderate caution",
                "Uptrend just started — proceed carefully",
                "Choppy conditions — selective only",
                "Narrow range — low activity expected",
                "Down / Short setups only",
            ]
            ra_df["_sort"] = ra_df["Conditions"].apply(
                lambda x: _COND_ORDER.index(x) if x in _COND_ORDER else 99
            )
            ra_df = ra_df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

            # ── Cell styling ──────────────────────────────────────────────────
            def _style_win_rate(series):
                styles = []
                for v in series:
                    try:
                        f = float(v)
                        if f >= 55:
                            styles.append("color:#16a34a; font-weight:700")
                        elif f >= 45:
                            styles.append("color:#92400e; font-weight:600")
                        else:
                            styles.append("color:#dc2626; font-weight:700")
                    except (TypeError, ValueError):
                        styles.append("")
                return styles

            def _style_net_pnl(series):
                styles = []
                for v in series:
                    try:
                        f = float(v)
                        styles.append("color:#16a34a; font-weight:600" if f >= 0 else "color:#dc2626; font-weight:600")
                    except (TypeError, ValueError):
                        styles.append("")
                return styles

            def _style_avg_return(series):
                styles = []
                for v in series:
                    try:
                        f = float(v)
                        styles.append("color:#16a34a" if f >= 0 else "color:#dc2626")
                    except (TypeError, ValueError):
                        styles.append("")
                return styles

            _ra_fmt = {
                "Win Rate %": "{:.1f}%",
                "Avg Return %": "{:+.2f}%",
                "Net PnL (PKR)": "{:+,.0f}",
            }
            st.dataframe(
                ra_df.style
                .apply(_style_win_rate,   subset=["Win Rate %"])
                .apply(_style_avg_return, subset=["Avg Return %"])
                .apply(_style_net_pnl,    subset=["Net PnL (PKR)"])
                .format(_ra_fmt, na_rep="—"),
                use_container_width=True,
                hide_index=True,
                height=min(500, (len(ra_df) + 1) * 42),
            )

            # ── Key takeaways ─────────────────────────────────────────────────
            _ra_closed = ra_df[ra_df["Trades"] >= 5].copy()  # min sample size
            if not _ra_closed.empty:
                _best  = _ra_closed.loc[_ra_closed["Win Rate %"].idxmax()]
                _worst = _ra_closed.loc[_ra_closed["Win Rate %"].idxmin()]
                _total_closed = int(ra_df["Trades"].sum())
                _total_wins   = int(ra_df["Wins"].sum())
                _overall_wr   = round(100.0 * _total_wins / _total_closed, 1) if _total_closed else 0

                st.markdown(
                    f"**Key takeaways** (conditions with ≥5 trades)  \n"
                    f"- **Best condition:** {_best['Conditions']} — "
                    f"{_best['Win Rate %']:.1f}% win rate across {int(_best['Trades'])} trades  \n"
                    f"- **Worst condition:** {_worst['Conditions']} — "
                    f"{_worst['Win Rate %']:.1f}% win rate across {int(_worst['Trades'])} trades  \n"
                    f"- **Overall closed trades:** {_total_closed} · "
                    f"Overall win rate: {_overall_wr:.1f}%"
                )
            else:
                st.caption("Not enough closed trades per condition yet (min 5) to generate takeaways.")

            # ── Condition definitions (dynamic footnote) ──────────────────────
            # Joins trade_setups to market_regime on entry date so indicator
            # averages (EMA spread, ATR%, 20d return) are pulled from the DB
            # for the actual dates your trades were entered — not hardcoded.
            # Classification rules sourced verbatim from regime.py _classify().
            try:
                _def_meta = _get_regime_definitions()
            except Exception:
                _def_meta = pd.DataFrame()

            if not _def_meta.empty:
                # Sort into canonical order; keep only conditions present in data
                _def_meta["_sort"] = _def_meta["condition_label"].apply(
                    lambda x: _COND_ORDER.index(x) if x in _COND_ORDER else 99
                )
                _def_meta = _def_meta.sort_values("_sort").reset_index(drop=True)

                # Short display titles for the selectbox and heading
                _COND_TITLES = {
                    "Stable uptrend — favorable conditions":    "Stable Uptrend (6+ Days)",
                    "Uptrend settling — moderate caution":      "Uptrend Settling (3–5 Days)",
                    "Uptrend just started — proceed carefully": "Uptrend Just Started (0–2 Days)",
                    "Choppy conditions — selective only":       "Volatile / Choppy",
                    "Narrow range — low activity expected":     "Ranging / Narrow",
                    "Down / Short setups only":                 "Downtrend",
                }

                # Core definitions — one sentence per regime, derived from
                # regime.py _classify(). Duration note appended for TRENDING_UP.
                def _core_def(regime, cond):
                    if regime == "TRENDING_UP":
                        base = (
                            "KSE-100 is in a confirmed broad-market uptrend "
                            r"($EMA_{20} > EMA_{50} > EMA_{200}$), "
                            "with the index trading above the $EMA_{20}$ and posting "
                            "positive returns over the prior 20 days. "
                            "This is the only regime that provides a structural tailwind "
                            "for long setups."
                        )
                        if "favorable" in cond:
                            note = "The trend has been in place for **6+ days** — settled and reliable."
                        elif "settling" in cond:
                            note = "The trend is **3–5 days old** — still establishing; watch for false starts."
                        else:
                            note = "The trend is **0–2 days old** — very fresh; could be a genuine breakout or a brief bounce."
                        return base + " " + note
                    elif regime == "TRENDING_DOWN":
                        return (
                            "KSE-100 is in a confirmed broad-market downtrend "
                            r"($EMA_{20} < EMA_{50} < EMA_{200}$), "
                            "with the index trading below the $EMA_{20}$ and declining "
                            "over the prior 20 days. "
                            "Long setups face a direct index headwind — system flags this as short-only territory."
                        )
                    elif regime == "VOLATILE":
                        return (
                            "No directional EMA stack is present, but daily swings are elevated: "
                            "ATR(20) exceeds **1.5%** of the index level. "
                            "The market is active and reactive but structurally choppy — "
                            "harder to hold positions through noise."
                        )
                    else:  # RANGING
                        return (
                            "No directional EMA stack and ATR(20) ≤ **1.5%** of the index level. "
                            "Low-volatility, sideways action with no trend conviction — "
                            "conditions where breakouts frequently stall or reverse quickly."
                        )

                _available = [
                    c for c in _COND_ORDER
                    if c in _def_meta["condition_label"].values
                ]

                with st.expander("What do these conditions actually mean?"):
                    _sel_cond = st.selectbox(
                        "Select a condition:",
                        options=_available,
                        format_func=lambda x: _COND_TITLES.get(x, x),
                        key="regime_def_sel",
                        label_visibility="collapsed",
                    )

                    _r = _def_meta[_def_meta["condition_label"] == _sel_cond].iloc[0]
                    _regime   = _r["regime_at_entry"]
                    _min_d    = _r["min_days"]
                    _max_d    = _r["max_days"]
                    _null_n   = int(_r["null_days_n"]) if pd.notna(_r["null_days_n"]) else 0
                    _e20_v50  = _r["avg_ema20_vs_50_pct"]
                    _e50_v200 = _r["avg_ema50_vs_200_pct"]
                    _atr      = _r["avg_atr_pct"]
                    _r20      = _r["avg_return_20d"]

                    # ── Heading ───────────────────────────────────────────────
                    _title = _COND_TITLES.get(_sel_cond, _sel_cond)
                    st.markdown(f"### 📊 Regime Context: {_title}")

                    # ── Core definition ───────────────────────────────────────
                    st.markdown(
                        f"**Core Definition:** {_core_def(_regime, _sel_cond)}"
                    )

                    st.divider()

                    # ── Observed entry conditions heading ─────────────────────
                    if _min_d is not None and _max_d is not None:
                        _day_range = f"Observed {int(_min_d)}–{int(_max_d)} Days"
                    elif _null_n:
                        _day_range = "No Transition Date on Record"
                    else:
                        _day_range = "Observed"
                    st.markdown(
                        f"**Your Historical Entry Conditions ({_day_range}):**"
                    )

                    # ── Three metric columns ──────────────────────────────────
                    _mc1, _mc2, _mc3 = st.columns(3)

                    # Trend Strength
                    if pd.notna(_r20):
                        _ts_sign  = "+" if _r20 >= 0 else ""
                        _ts_label = f"{_ts_sign}{_r20:.2f}% (20-day avg)"
                        _ts_delta = "Positive momentum" if _r20 >= 0 else "Negative momentum"
                    else:
                        _ts_label, _ts_delta = "N/A", None
                    _mc1.metric("Trend Strength", _ts_label, _ts_delta)

                    # Volatility
                    if pd.notna(_atr):
                        _mc3.metric("Daily ATR (avg)", f"{_atr:.2f}% of index")
                    else:
                        _mc3.metric("Daily ATR (avg)", "N/A")

                    # EMA spread — use the middle column as a bullet block
                    _mc2.markdown("**MA Spacings**")
                    if pd.notna(_e20_v50):
                        _mc2.markdown(
                            f"$EMA_{{20}}$ was **{_e20_v50:+.2f}%** above $EMA_{{50}}$"
                        )
                    if pd.notna(_e50_v200):
                        _mc2.markdown(
                            f"$EMA_{{50}}$ was **{_e50_v200:+.2f}%** above $EMA_{{200}}$"
                        )
                    if not pd.notna(_e20_v50) and not pd.notna(_e50_v200):
                        _mc2.caption("No market_regime data matched your entry dates.")

                    # ── Footer caption ────────────────────────────────────────
                    st.caption(
                        "Classification rules sourced from `regime.py _classify()` — applied nightly to "
                        "KSE-100 OHLCV data. Indicator averages joined live from `market_regime` on "
                        "your actual trade entry dates."
                    )
        else:
            st.info("No closed Actual trades with regime data yet.")

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
    # ── Load stock_signals for latest date ────────────────────────────────────
    try:
        _ex_latest, _ex_df = _get_explorer_data()
    except Exception as _ex_load_err:
        st.error(f"Explorer data error: {_ex_load_err}")
        st.stop()

    st.markdown("**Stock Explorer**")
    st.caption(f"As of {fmt_date(_ex_latest)} · {len(_ex_df)} stocks")

    with st.expander("📖 Weinstein Screener — How It Works & Empirical Findings", expanded=False):
        st.markdown("""
### How the screener works

**Purpose — early warning, not a buy trigger.**
The Weinstein Watchlist identifies stocks that are set up for a sustained Stage 2 advance: sector in a confirmed uptrend, stock above a rising long-term moving average, relative strength improving, and price coiling near its recent high with volume contracting. A stock appearing here is a candidate to monitor. Entry is on a confirmed breakout on heavy volume, not on screener appearance alone.

**Expected frequency.** ~92 signals per year (~1–2 per week). This is the deduped count — first day a stock enters a qualifying streak. Most setups will hold the conditions for several consecutive days; the screener doesn't repeat-count those.

**Hold duration.** This is calibrated to a 90-day (multi-month) forward window. It is not a swing trade screen. Weinstein's Stage 2 plays, correctly entered, play out over months.

---

**Gate-by-gate explanation**

| Gate | What it checks | Why it's there |
|---|---|---|
| Sector Stage 2 | Sector price index is above its rising EMA | Forest-before-trees: Weinstein Ch.3 — never buy a stock in a sick sector |
| Sector rank ≤ 8 | Sector is in the top 8 globally by RS rank | Healthy sector, not necessarily #1. Hard floor prevents buying into recovering laggards |
| Stock above rising 150d EMA | Close > 150d EMA AND EMA slope positive | Weinstein 30-week MA (Ch.2): the defining condition for Stage 2 |
| RS rank improving (rank_change > 0) | Stock moved up in the cross-sectional RS ranking today | Stock is gaining relative strength vs the market, not just riding the tide |
| Sector RS rank ≤ 5 | Stock is a relative leader within its own sector | Weinstein: buy the best stock in the best sector, not the median |
| Near pivot ≥ 7 days | Stock has been 0–15% below its recent pivot high for 7+ consecutive days | Coiling/base formation: price compressing before a potential move, not extended after a run |
| Volume > 200k avg | 10-day average volume > 200,000 shares | Liquidity floor — prevents illiquid setups where spread and slippage kill execution |

---

### Empirical findings

**Grounded in Stan Weinstein's *Secrets for Profiting in Bull and Bear Markets*.**
Rules extracted with page citations before testing began. Tested original thresholds first; relaxed only where PSX data supported it.

- **Stage 2 definition**: Ch.2 pp.33–35 — price above rising 30-week MA
- **Sector-first**: Ch.3 pp.75–88 — sector must be in Stage 2, not necessarily ranked #1
- **Relative Strength formula**: Ch.4 pp.108–112 — price / market index, week-over-week slope
- **Volume at breakout**: Ch.4 p.129 — "never overlook poor volume on a breakout"
- **Short selling**: Ch.7 p.237 — "volume NOT required for shorts" (asymmetric to longs)

---

**The 20d→90d measurement window finding.**
The first backtest used a 20-day forward return window. At 20d, the sector gate `sec_rank ≤ 8` appeared to *hurt* EV vs the prior 5-day rank-improvement gate. Correcting to a 90-day window — appropriate for Stage 2 plays that take months to resolve — reversed the finding completely. The 5-day rank gate has no edge over base at any horizon. The sec_rank ≤ 8 hard floor adds +1.14% EV at 90d. The two gates were not comparable at short windows because Stage 2 setups require time to resolve.

---

**MA grid — 6 variants tested (50/100/150 × SMA/EMA) at 60/90/120d**

| Variant | EV@90d |
|---|---|
| 150d EMA | **+8.70%** |
| 150d SMA | +7.90% |
| 100d EMA | +7.68% |
| 100d SMA | +7.21% |
| 50d EMA | +4.89% |
| 50d SMA | +4.12% |

EMA beat SMA at every length. Longer beat shorter at every type. 150d EMA selected.

---

**Sector gate — tested against base (no sector rank gate) at 90d**

| Sector gate | EV@90d |
|---|---|
| sec_rank ≤ 5 | +7.89% |
| **sec_rank ≤ 8** | **+8.41%** |
| sec_rank ≤ 12 | +7.31% |
| Prior gate: 5-day rank improvement | +7.27% (= base, no edge) |
| No sector rank gate (base) | +7.27% |

sec_rank ≤ 8 selected. The prior gate (sector RS rank improving over 5 days) had no measurable edge over the unfiltered base at any horizon and was removed.

Two other gates were tested and rejected:
- **`sec_pivot_dist ≤ 10%`** (sector not extended from its high): noise at every horizon tested. Removed.
- **5-day RS rank improvement gate**: EV matched the no-gate base identically. Removed.

---

**Final combined-gate backtest (persistent-state, 90d window)**

Methodology: daily `stock_signals` rows meeting all conditions, deduped to first day of each qualifying streak per symbol. Forward return measured at 90 trading days.

| Version | N (streaks) | WR | LR | EV@90d | Freq/yr |
|---|---|---|---|---|---|
| **EMA150 Weinstein (current)** | **1,021** | **43.5%** | **35.7%** | **+10.50%** | **92/yr** |
| EMA50 Weinstein (prior) | 1,197 | 42.3% | 37.8% | +8.82% | 108/yr |

The EMA150 version improves EV by +1.68% and reduces loss rate by 2.1 percentage points. The lower frequency (92 vs 108/yr) reflects tighter filtering, not signal loss.

---

**Short screener — audited and disabled.**
The short screener was audited against the book directly (Ch.7). Key finding: Weinstein explicitly states volume is *not* required for short entries (p.237) — the signal logic was sign-flipped from the long screener rather than built from source. Tested against PSX data at all windows and variants: **negative EV at every configuration**. PSX is bullish 89% of time (TRENDING_UP + RANGING + VOLATILE); only 11% TRENDING_DOWN historically. Structural mismatch for short-side methodology. Screener code is preserved behind `market_regime = TRENDING_DOWN` gate for future revisit if PSX enters an extended bear phase and the EV can be validated on that regime subset.
""")

    # ── Screener toggle ───────────────────────────────────────────────────────
    _ex_weinstein = st.toggle(
        "📖 Weinstein Watchlist — Sector Stage 2 · Top-8 sector · Stock RS↑ · Rising 150EMA · Coiling ≥7d near pivot",
        key="exp_weinstein",
    )
    _ex_screener = False   # superseded by Weinstein screener
    _ex_edge = False       # superseded by Weinstein screener
    _ex_short = False      # disabled — negative EV on PSX; gated behind TRENDING_DOWN for future use

    # Stealth RS — watch-only toggle, filters the same main table below
    # (like Weinstein Watchlist does), but mutually exclusive with it — the
    # two are never combined/stacked (see _ex_stealth_active below). Reuses
    # sec_global_rank<=8 (Market Gate's confirmed field) as a PRACTICAL
    # pre-filter only, per PI decision — this combination has never been
    # tested. No scoring/ranking logic; not wired into leaders_scan.py,
    # kiran_voice.py, or agent.py.
    _ex_stealth_rs = st.toggle(
        "🔬 Stealth RS (Exploratory — Not Validated)",
        key="exp_stealth_rs",
    )
    if _ex_stealth_rs:
        st.caption(
            "⚠️ **Exploratory research signal — not yet confirmed on out-of-sample data. "
            "The sec_global_rank≤8 restriction is a practical trading-workflow filter, not "
            "a tested combination. Not a trading recommendation. Under observation, "
            "scheduled for re-evaluation with fresh data.**"
        )

    # Boring Breakouts -- RS_60-conditioned Donchian breakout, manual-execution
    # workflow. Independent of Weinstein/Stealth RS: its column set (Trigger/
    # Target/Stop/Status/Action) doesn't fit the shared screener table above,
    # so it renders its own section instead of filtering the same table.
    # Locked spec: boring_study_trading_rulebook_v1_2026-07-11.md (Addenda A-C).
    _ex_boring = st.toggle(
        "🎯 Boring Breakouts — RS_60-conditioned Donchian (manual execution)",
        key="exp_boring",
    )
    if _ex_boring:
        _render_boring_breakouts_section()
        st.divider()

    # Sector filter + sort controls in one row
    _fc1, _fc2, _fc3, _fc4 = st.columns([2, 2, 1, 1])
    _ex_sectors = ["All sectors"] + sorted(_ex_df["sector"].dropna().unique().tolist())
    _ex_sel_sec = _fc1.selectbox("Sector", _ex_sectors, key="exp_sector",
                                  label_visibility="collapsed")
    _ex_sort_opts = {
        "RS Rank":         ("rs_rank",            True),
        "RS Score":        ("rs_score_20",        False),
        "Rank Change":     ("rank_change",        False),
        "BBW% (tightest)": ("base_tightness",     True),
        "Pivot Distance":  ("pivot_distance_pct", True),
        "Symbol A–Z":      ("symbol",             True),
    }
    _ex_sort_label = _fc2.selectbox("Sort by", list(_ex_sort_opts.keys()),
                                     key="exp_sort", label_visibility="collapsed")
    _ex_sort_col, _ex_sort_asc = _ex_sort_opts[_ex_sort_label]
    _ex_bos_only = _fc3.checkbox("BOS only", key="exp_bos")
    _ex_top_n_input = _fc4.number_input("Top N", min_value=5, max_value=300,
                                         value=40, step=5, key="exp_n",
                                         label_visibility="collapsed")

    _ex_filtered = (
        _ex_df if _ex_sel_sec == "All sectors"
        else _ex_df[_ex_df["sector"] == _ex_sel_sec]
    ).copy()

    # Stealth RS is mutually exclusive with Weinstein Watchlist — never
    # combined/stacked, matching the original isolation requirement, but now
    # filters the SAME main table/empty-state instead of a separate one.
    # If a user somehow enables both, Weinstein takes priority and a notice
    # is shown (see below) rather than silently intersecting the two.
    _ex_stealth_active = _ex_stealth_rs and not _ex_weinstein
    if _ex_stealth_active:
        # Single code path for both backends — compute_stealth_rs() branches
        # internally on _PG_URL (SQLite locally, Postgres on Cloud), same
        # live per-page-load query either way. No separate precomputed
        # table/batch job: Cloud follows exactly what local SQLite does.
        _stealth_symbols = _ex_filtered["symbol"].tolist()
        _stealth_counts = _compute_stealth_rs_live(_ex_latest, _stealth_symbols)
        _ex_filtered["stealth_count"] = _ex_filtered["symbol"].map(_stealth_counts).fillna(0).astype(int)
    if _ex_weinstein and _ex_stealth_rs:
        st.warning(
            "Weinstein Watchlist and Stealth RS cannot be combined — showing Weinstein Watchlist. "
            "Turn off Weinstein to view Stealth RS."
        )

    # Weinstein top-down watchlist
    if _ex_weinstein:
        _total_before_w = len(_ex_filtered)
        _ex_filtered = _ex_filtered[
            # ── Sector-level criteria ─────────────────────────────────────
            # [1] Sector Stage 2 — price above rising sector EMA
            (_ex_filtered["sec_stage"] == "Stage 2") &
            # [2] Sector among global top 8 by RS rank (Weinstein: healthy sector, not necessarily #1)
            (_ex_filtered["sec_global_rank"].fillna(999) <= 8) &
            # ── Stock-level criteria ──────────────────────────────────────
            # [3] Stock above its own 150 EMA (Weinstein 30-week MA equivalent)
            (_ex_filtered["close_above_ema150"].fillna(0) == 1) &
            # [4] Stock 150 EMA sloping upward
            (_ex_filtered["ema150_slope_pos"].fillna(0) == 1) &
            # [5] RS rank improving — moving up the leaderboard
            (_ex_filtered["rank_change"].fillna(-999) > 0) &
            # [6] Coiling near pivot ≥7 consecutive days (0–15% below pivot high)
            # (former [6] "RS leader in its sector (top 5)" / sector_rs_rank<=5
            # removed 2026-07-10 — confirmed reversed/dead per S-003, see
            # PRE_BREAKOUT_Specification_v1.0.md Session Summary)
            (_ex_filtered["near_pivot_days"].fillna(0) >= 7) &
            # Liquid
            (_ex_filtered["avg_vol_10d"] > 200_000)
        ]
        _ex_filtered = _ex_filtered.sort_values(
            ["sec_global_rank", "rs_rank"], ascending=True
        )
        st.caption(
            f"📖 Weinstein Watchlist — **{len(_ex_filtered)}** stocks · "
            f"Sector Stage 2 · Global top-8 sector · Stock above rising 150EMA · "
            f"RS↑ · Coiling ≥7d"
        )

    # Stealth RS (Exploratory — Not Validated). Filters the SAME main table/
    # empty-state as every other toggle here. Uses the locked Section 12
    # stealth-count definition (unmodified) AND sec_global_rank<=8 (Market
    # Gate's confirmed field, reused as-is — same fillna(999)<=8 convention
    # as the Weinstein block above) as a practical, untested pre-filter per
    # PI decision. Watch-only: no scoring/ranking logic, not wired into
    # leaders_scan.py, kiran_voice.py, or agent.py.
    elif _ex_stealth_active:
        _ex_filtered = _ex_filtered[
            (_ex_filtered["stealth_count"] >= 2) &
            (_ex_filtered["sec_global_rank"].fillna(999) <= 8)
        ]
        st.caption(
            f"🔬 Stealth RS (Exploratory, not validated) — **{len(_ex_filtered)}** stocks · "
            f"stealth count ≥2 (locked Section 12 definition) · sector sec_global_rank ≤8 "
            f"(practical filter, untested combination — see caption above)"
        )

    # Stage 4 short screener — disabled: negative EV on PSX at all tested windows.
    # PSX is bullish 89% of time (TU+RG+VL); only 11% TRENDING_DOWN. Short signals
    # are sign-flipped from long, not book-grounded. Re-enable only if market_regime
    # is TRENDING_DOWN for an extended period and EV is re-validated on that subset.
    # _ex_short is hardcoded False above; restore the toggle when revisiting.
    if _ex_short:
        _total_before_s = len(_ex_filtered)
        _ex_filtered = _ex_filtered[
            # Sector in distribution or decline
            (_ex_filtered["sec_stage"].isin(["Stage 3", "Stage 4"])) &
            # Sector RS rank deteriorating over 5 days (rank number getting worse = higher)
            (_ex_filtered["sec_global_rank"].fillna(0) > _ex_filtered["sec_rs_rank_5d"].fillna(0)) &
            # Stock below declining 50 EMA
            (_ex_filtered["close_above_ema50"].fillna(1) == 0) &
            (_ex_filtered["ema50_slope_pos"].fillna(1) == 0) &
            # RS rank falling
            (_ex_filtered["rank_change"].fillna(0) < 0) &
            # Bounce into resistance — stock near old pivot from below (-8% to +2%)
            (_ex_filtered["pivot_distance_pct"].fillna(-99) >= -8) &
            (_ex_filtered["pivot_distance_pct"].fillna(99) <= 2) &
            # DFC eligible only
            (_ex_filtered["symbol"].isin(DFC_SYMBOLS))
        ]
        _ex_filtered = _ex_filtered.sort_values(
            ["sec_global_rank", "rank_change", "rs_rank"], ascending=[True, True, False]
        )
        st.caption(
            f"📉 Stage 4 Shorts — **{len(_ex_filtered)}** DFC stocks · "
            f"Sector Stage 3/4 + RS rank falling · Below declining 50EMA · "
            f"Bouncing to resistance (-8% to +2% of pivot) · Tight stop above pivot/EMA"
        )

    if _ex_bos_only:
        _ex_filtered = _ex_filtered[_ex_filtered["bos_flag"] == 1]
    _ex_filtered = _ex_filtered.sort_values(
        _ex_sort_col, ascending=_ex_sort_asc, na_position="last"
    )

    _ex_show = _ex_filtered.head(int(_ex_top_n_input)).copy()

    def _fmt_rank_chg(v):
        if pd.isna(v): return "—"
        v = int(v)
        if v > 0:  return f"↑{v}"
        if v < 0:  return f"↓{abs(v)}"
        return "—"

    _ex_show["rank_chg_fmt"] = _ex_show["rank_change"].apply(_fmt_rank_chg)
    _ex_show["bos"] = _ex_show["bos_flag"].apply(
        lambda x: "✅" if x == 1 else ""
    )
    _stage_icon_map = {"Stage 2": "🟢", "Stage 3": "🟡", "Stage 4": "🔴", "Stage 1": "⚪"}
    _ex_show["sec_stage_fmt"] = _ex_show["sec_stage"].map(_stage_icon_map).fillna("—")

    _ex_disp_cols  = [
        "symbol", "sector", "sec_stage_fmt", "rs_rank", "rs_score_20",
        "rank_chg_fmt", "sector_rs_rank",
        "base_tightness", "near_pivot_days", "pivot_distance_pct",
        "overhead_clear", "bos", "avg_vol_10d", "current_close"
    ]
    _ex_disp_names = [
        "Symbol", "Sector", "Sec Stage", "RS Rank", "RS Score",
        "Rank Δ", "Sec Rank",
        "BBW%", "Piv Days", "Pivot Dist%",
        "OH Clear", "BOS", "Vol 10d", "Close"
    ]
    if _ex_stealth_active:
        # Plain, unweighted, informational columns only — not part of any
        # scoring/sort logic (the sort dropdown above never offers either
        # column, so a user cannot rank by them from this table).
        _ex_disp_cols  += ["stealth_count", "sec_global_rank"]
        _ex_disp_names += ["Stealth Count", "Sec Global Rank"]

    _ex_disp = _ex_show[_ex_disp_cols].copy()
    _ex_disp.columns = _ex_disp_names
    st.dataframe(
        _ex_disp.style.format({
            "RS Score":    "{:+.1f}",
            "BBW%":        lambda v: f"{v:.1f}%" if pd.notna(v) else "—",
            "Piv Days":    lambda v: f"{int(v)}d" if pd.notna(v) else "—",
            "OH Clear":    lambda v: "✅" if v == 1 else ("❌" if v == 0 else "—"),
            "Pivot Dist%": lambda v: f"{v:+.1f}%" if pd.notna(v) else "—",
            "Vol 10d":     lambda v: f"{v/1e6:.2f}M" if pd.notna(v) and v >= 1e6 else (f"{v:,.0f}" if pd.notna(v) else "—"),
            "Sec Global Rank": lambda v: f"{int(v)}" if pd.notna(v) else "—",
            "Close":       lambda v: f"{v:.2f}" if pd.notna(v) else "—",
        }),
        use_container_width=True, hide_index=True, height=400,
    )

    st.caption(
        "**How to read this table →** "
        "**RS Rank** — lower = stronger stock relative to market (1 is best). &nbsp;"
        "**RS Score** — positive = outperforming index; negative = underperforming. &nbsp;"
        "**Rank Δ** — ↑ = rising momentum, ↓ = fading. &nbsp;"
        "**Sec Rank** — sector's RS rank; prefer stocks in top-ranked sectors (low number). &nbsp;"
        "**BBW%** — Bollinger Band Width = (Upper − Lower) / Middle × 100; lower = tighter base = stock coiling (better setup). &nbsp;"
        "**Pivot Dist%** — distance to last pivot high: near 0 = at pivot, negative = already broken out. &nbsp;"
        "**BOS ✅** — breakout signal fired today; price closed above pivot. &nbsp;"
        "**Decision flow:** top sector (low Sec Rank) → strong RS (low RS Rank, positive Score) → "
        "rising (↑ Rank Δ) → coiling base (low BBW%) → near or above pivot → BOS ✅ = highest-conviction entry."
    )

    st.divider()
    st.markdown("**Price History**")
    from database import get_prices_df

    _ex_sym_list = _ex_filtered["symbol"].tolist() if not _ex_filtered.empty else _ex_df["symbol"].tolist()
    chosen_symbol = st.selectbox("Symbol", _ex_sym_list, key="exp_sym",
                                  label_visibility="collapsed")

    if chosen_symbol:
        _ex_sig_row = _ex_df[_ex_df["symbol"] == chosen_symbol]

        if not _ex_sig_row.empty:
            _sr = _ex_sig_row.iloc[0]
            _bos   = _sr["bos_flag"] == 1
            _rs    = _sr["rs_score_20"]
            _rank  = _sr["rs_rank"]
            _pdist = _sr["pivot_distance_pct"]
            _tight = _sr["base_tightness"]
            _sec_rank = _sr["sector_rs_rank"]
            _rchg  = _sr["rank_change"]
            _close = _sr["current_close"]
            _pivot = _sr["pivot_high"]

            if _bos and _rs is not None and _rs > 0:
                _b_col = "#22c55e"; _b_label = "Breakout"
            elif _pdist is not None and 0 <= _pdist <= 5:
                _b_col = "#f59e0b"; _b_label = "Near Pivot"
            elif _rs is not None and _rs > 0:
                _b_col = "#3b82f6"; _b_label = "RS Positive"
            else:
                _b_col = "#94a3b8"; _b_label = "Lagging"

            _rchg_str  = (f"↑{int(_rchg)}" if _rchg > 0 else f"↓{abs(int(_rchg))}" if _rchg < 0 else "—") if pd.notna(_rchg) else "—"
            _pdist_str = f"{_pdist:+.1f}%" if pd.notna(_pdist) else "—"
            _tight_str = f"{_tight:.1f}%" if pd.notna(_tight) else "—"
            _pivot_str = f"PKR {_pivot:.2f}" if pd.notna(_pivot) else "—"
            _close_str = f"PKR {_close:.2f}" if pd.notna(_close) else "—"

            st.markdown(
                f"<div style='background:{_b_col}15; border-left:4px solid {_b_col}; "
                f"padding:8px 14px; border-radius:6px; margin-bottom:10px;'>"
                f"<div style='display:flex; align-items:center; gap:16px; flex-wrap:wrap;'>"
                f"<span style='font-size:0.9rem; font-weight:800; color:{_b_col}; white-space:nowrap;'>{_b_label}</span>"
                f"<span style='font-size:0.75rem; color:#475569;'>"
                f"RS #{_rank} &nbsp;·&nbsp; Score <b>{_rs:+.1f}</b> &nbsp;·&nbsp; "
                f"Rank Δ <b>{_rchg_str}</b> &nbsp;·&nbsp; Sec #{_sec_rank} &nbsp;·&nbsp; "
                f"BBW% <b>{_tight_str}</b> &nbsp;·&nbsp; "
                f"Pivot {_pivot_str} &nbsp;·&nbsp; Dist <b>{_pdist_str}</b>"
                f"</span></div>"
                f"<div style='font-size:0.72rem; color:#94a3b8; margin-top:4px;'>"
                f"Close {_close_str} &nbsp;·&nbsp; {_sr['sector']}"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        hist = get_prices_df(chosen_symbol, limit=120)
        if hist:
            h_df = pd.DataFrame(hist).sort_values("date")
            h_df["date"] = pd.to_datetime(h_df["date"])
            h_df["ma20"] = h_df["close"].rolling(20, min_periods=1).mean()
            h_df["ma50"] = h_df["close"].rolling(50, min_periods=1).mean()

            if HAS_PLOTLY:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=h_df["date"], y=h_df["close"],
                    mode="lines", name="Close",
                    line={"color": "#1e293b", "width": 2},
                ))
                fig2.add_trace(go.Scatter(
                    x=h_df["date"], y=h_df["ma20"],
                    mode="lines", name="20 MA",
                    line={"color": "#3b82f6", "width": 1.5, "dash": "dot"},
                ))
                fig2.add_trace(go.Scatter(
                    x=h_df["date"], y=h_df["ma50"],
                    mode="lines", name="50 MA",
                    line={"color": "#f59e0b", "width": 1.5, "dash": "dash"},
                ))
                if not _ex_sig_row.empty and pd.notna(_ex_sig_row.iloc[0]["pivot_high"]):
                    fig2.add_hline(
                        y=float(_ex_sig_row.iloc[0]["pivot_high"]),
                        line_dash="dot", line_color="#ef4444", line_width=1.2,
                        annotation_text="Pivot", annotation_position="right",
                    )
                fig2.update_layout(
                    title={"text": chosen_symbol, "font": {"size": 13}},
                    xaxis_title="", yaxis_title="Close (PKR)",
                    height=420,
                    margin={"l": 4, "r": 4, "t": 36, "b": 8},
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis={"gridcolor": "#f1f5f9"},
                    yaxis={"gridcolor": "#f1f5f9"},
                    legend={"orientation": "h", "y": 1.08, "font": {"size": 10}},
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.dataframe(h_df[["date","close","ma20","ma50"]],
                             use_container_width=True, hide_index=True)
        else:
            st.info(f"No price data for {chosen_symbol}.")

        with st.expander("Understanding the Price History Summary"):
            st.markdown("""
**Overview**

The coloured banner above summarises the current technical state of the selected stock based on signals computed from daily price data. It combines relative strength, breakout status, and proximity to the key pivot level into a single at-a-glance indicator.

---

**Color Meaning**

| Color | Label | What it means |
|---|---|---|
| 🟢 Green | **Breakout** | The stock fired a breakout signal today (closed above its pivot high) **and** is outperforming the KSE-100 index over the past 20 days. Highest-conviction state. |
| 🟡 Amber | **Near Pivot** | The stock is within 5% of its pivot high but has not broken out yet (or RS is negative). A setup that is coiling near resistance — watch for a breakout. |
| 🔵 Blue | **RS Positive** | The stock is outperforming the KSE-100 over 20 days but is not near its pivot or in breakout. Showing strength in the background. |
| ⚪ Gray | **Lagging** | The stock is underperforming the KSE-100 and is not near a pivot. Avoid until relative strength improves. |

Colors are applied in order: Green is checked first, then Amber, then Blue. A stock cannot be both Green and Amber simultaneously — Breakout takes priority.

---

**Score**

The **Score** (labelled *Score* in the banner) measures how much the stock has outperformed or underperformed the KSE-100 index over the **last 20 trading days**.

*Formula (high level):* Stock's 20-day % return minus KSE-100's 20-day % return.

| Score | Interpretation |
|---|---|
| **Above +10** | Strong outperformer — stock is running significantly ahead of the market |
| **+1 to +10** | Mild outperformance — trending with the market but doing better |
| **0** | Exactly matching the index |
| **−1 to −10** | Mild underperformance |
| **Below −10** | Significant laggard — stock is losing ground relative to the market |

A **positive score** is the minimum bar for a quality setup. A **negative score** disqualifies the breakout label even if the BOS signal fired.

---

**Notes**

- The Score is a raw percentage difference, not a rank or normalised value. It can go above +20 or below −20 during volatile periods.
- The 20-day window is approximately one calendar month of trading days.
- RS Rank (shown as *RS #n*) is a separate ranking: rank 1 = strongest stock in the universe by this same score. A low rank number combined with a high positive score is the ideal combination.
- Sector Rank (*Sec #n*) shows where the stock's sector sits in the sector RS ranking — prefer stocks in top-ranked (low-numbered) sectors.
- This panel only appears when today's signal data exists for the selected symbol.
""")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[6]:  # Analytics
    from config import BENCHMARK

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
        f"to your benchmark ({BENCHMARK['sample_size']})"
    )

    comp_cols = st.columns(2)

    # Build comparison dataframe
    metrics_list = [
        ("Win Rate %", f"{win_rate*100:.1f}%", f"{BENCHMARK['win_rate_pct']:.1f}%"),
        ("Profit Factor", f"{profit_factor:.2f}x", f"{BENCHMARK['profit_factor']:.2f}x"),
        ("Risk:Reward", f"{avg_rr:.2f}x", f"{BENCHMARK['risk_reward']:.2f}x"),
        ("Expectancy %", f"{expectancy_pct:+.2f}%", f"{BENCHMARK['expectancy_pct']:+.2f}%"),
    ]

    comp_df = pd.DataFrame(
        metrics_list,
        columns=["Metric", "Your Current", f"{BENCHMARK['name']}"]
    )

    with comp_cols[0]:
        st.markdown("**Current Performance**")
        st.metric("Win Rate", f"{win_rate*100:.1f}%", delta=f"{win_rate*100 - BENCHMARK['win_rate_pct']:.1f}pp vs benchmark")
        st.metric("Expectancy %", f"{expectancy_pct:+.2f}%", delta=f"{expectancy_pct - BENCHMARK['expectancy_pct']:+.2f}pp vs benchmark")

    with comp_cols[1]:
        st.markdown(f"**{BENCHMARK['name']}**")
        st.metric("Win Rate", f"{BENCHMARK['win_rate_pct']:.1f}%", label_visibility="collapsed")
        st.metric("Expectancy %", f"{BENCHMARK['expectancy_pct']:+.2f}%", label_visibility="collapsed")

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
elif cur == PAGES[9]:  # Backtest
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
    # BOS BREAKOUT BACKTEST FINDINGS  — run: 2026-06-19
    # Universe : bos_flag=1 AND BBW<10 AND avg_vol_10d>200k  (all history)
    # Winner   : +18% hit before -6% stop within 20 trading days
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.divider()
    st.markdown("### BOS Breakout Backtest — Research Findings")
    st.caption(
        "Run date: **19 Jun 2026** &nbsp;·&nbsp; "
        "Universe: all BOS signals (bos_flag=1) where BBW% < 10 and avg vol 10d > 200k &nbsp;·&nbsp; "
        "**Winner definition:** price hit +18% before hitting -6% stop within 20 trading days &nbsp;·&nbsp; "
        "Risk/Reward: 1:3 &nbsp;·&nbsp; "
        "Total qualifying events: 3,718"
    )

    st.markdown("#### Finding 1 — Market Regime is the most important filter")
    st.caption("Outside TRENDING_UP, BOS breakouts have negative expected value regardless of any other filter.")
    _bos_reg_data = {
        "Regime":     ["TRENDING_UP", "RANGING", "TRENDING_DOWN", "VOLATILE"],
        "Events":     [903,  469,  72,  69],
        "Win Rate":   ["26.8%", "12.6%", "11.1%", "7.2%"],
        "EV / trade": ["+0.43%", "-2.98%", "-3.33%", "-4.26%"],
        "Verdict":    ["✅ Only regime with positive EV", "❌ Avoid", "❌ Avoid", "❌ Avoid"],
    }
    st.dataframe(pd.DataFrame(_bos_reg_data), use_container_width=True, hide_index=True)

    st.markdown("#### Finding 2 — Extending the hold window improves EV significantly")
    st.caption(
        "59% of BOS events did not resolve within 20 days. Of those, 37% eventually hit the -6% stop "
        "by 60 days — they were not neutral, they were slowly failing. "
        "Extending to 40 days is the practical sweet spot: EV turns positive without tying up capital for 3 months."
    )
    _bos_win_data = {
        "Hold Window": ["20 days", "30 days", "40 days", "60 days"],
        "Events Resolved": ["40.7%", "55.1%", "64.2%", "77.8%"],
        "Win Rate":        ["20.8%", "24.0%", "26.4%", "30.4%"],
        "EV / trade":      ["-1.02%", "-0.24%", "+0.33%", "+1.30%"],
        "Verdict":         ["Negative EV", "Near breakeven", "✅ Positive EV", "✅ Best EV"],
    }
    st.dataframe(pd.DataFrame(_bos_win_data), use_container_width=True, hide_index=True)

    st.markdown("#### Finding 3 — Sector rank at BOS: top 3 best in TRENDING_UP; sector 4-5 is dead zone")
    st.caption(
        "In TRENDING_UP, stocks breaking out inside the top 3 ranked sectors had the highest win rate. "
        "Sector ranks 4-5 consistently underperformed — avoid. "
        "Sector ranks 6-12 and 13+ also showed positive EV in TRENDING_UP."
    )
    _bos_sec_data = {
        "Sector Rank at BOS": ["Top 3", "4-5", "6-8", "9-12", "13+"],
        "Win Rate (20d, TRENDING_UP)":  ["30.2%", "21.4%", "28.4%", "25.1%", "27.7%"],
        "Win Rate (40d, TRENDING_UP)":  ["32.5%", "20.2%", "28.0%", "29.5%", "31.9%"],
        "EV at 40d":  ["+1.81%", "-1.16%", "+0.71%", "+1.07%", "+1.66%"],
        "Verdict":    ["✅ Best", "❌ Dead zone — skip", "✅ Good", "✅ Good", "✅ Good"],
    }
    st.dataframe(pd.DataFrame(_bos_sec_data), use_container_width=True, hide_index=True)

    st.markdown("#### Finding 4 — RS rank sweet spot: 50-200, not the leaders")
    st.caption(
        "Counterintuitive: top 25 RS stocks had the lowest win rate at BOS. "
        "They are already extended when they break the pivot. "
        "RS rank 101-200 inside top sectors had the highest win rate — "
        "these are stocks not yet discovered by the market, breaking out inside a strong sector."
    )
    _bos_rs_data = {
        "RS Rank at BOS": ["Top 25", "26-50", "51-100", "101-200", "201+"],
        "Win Rate (20d, TRENDING_UP)": ["100%*", "22.8%", "23.9%", "29.5%", "27.6%"],
        "EV at 20d":                   ["+18%*", "-0.53%", "-0.26%", "+1.08%", "+0.62%"],
        "Verdict":                     ["*1 event only — ignore", "Below avg", "Below avg", "✅ Best range", "Small sample"],
    }
    st.dataframe(pd.DataFrame(_bos_rs_data), use_container_width=True, hide_index=True)

    st.markdown("#### Finding 5 — BBW sweet spot: 5-7%")
    st.caption("Very tight bases (<3%) had zero wins. The 5-7% BBW range had the highest win rate in TRENDING_UP.")
    _bos_bbw_data = {
        "BBW% at BOS": ["<3%", "3-5%", "5-7%", "7-10%"],
        "Events (TRENDING_UP)": [0, 45, 186, 672],
        "Win Rate": ["—", "24.4%", "29.0%", "26.3%"],
        "EV":       ["—", "-0.13%", "+0.97%", "+0.32%"],
        "Verdict":  ["No data", "Below avg", "✅ Sweet spot", "Positive EV"],
    }
    st.dataframe(pd.DataFrame(_bos_bbw_data), use_container_width=True, hide_index=True)

    st.markdown("#### Finding 6 — Best single combo found (TRENDING_UP + 40d window)")
    st.caption(
        "Sector top 3 × RS rank 101-200 is the standout combination. "
        "The stock is not yet a leader globally, but it is breaking out inside the strongest sector. "
        "This is the 'not yet discovered' setup — price structure is tight, sector is leading, "
        "stock is catching up. This is what the 👀 Watch List on the Explorer page targets."
    )
    _bos_combo_data = {
        "Combo (TRENDING_UP + 40d)":           ["Sector top 3 × RS 101-200", "Sector 6-8 × RS top 50", "Sector top 3 × RS top 50", "Sector 13+ × RS 201+", "All TRENDING_UP (baseline)"],
        "Events": [61, 24, 28, 22, 903],
        "Win Rate": ["45.9%", "37.5%", "35.7%", "36.4%", "26.4%"],
        "EV":       ["+5.02%", "+3.00%", "+2.57%", "+2.73%", "+0.33%"],
        "Verdict":  ["✅ Highest EV found", "✅ Strong", "✅ Strong", "✅ Strong", "Baseline"],
    }
    st.dataframe(pd.DataFrame(_bos_combo_data), use_container_width=True, hide_index=True)

    st.info(
        "**How to use these findings:** These results do not replace your discretionary process. "
        "They are a reference map — showing which conditions historically produced the best outcomes "
        "on this specific setup type. Use the 🔬 Edge Screener on the Explorer page to surface stocks "
        "that match the best combo in real time. Build conviction by observing it live before relying on it."
    )


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

    if True:  # Weinstein detail analytics

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
elif cur == PAGES[8]:  # Setup Perf
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

    # Source selector — Support Reversal disabled 2026-07-23 (pattern killed, -1.88% net)
    _sp_sources = ["System"]
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


elif False:  # STM page removed — killed (82% overlap, Z-histogram gate unvalidated)
    pass

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — 🔄 Recovery Bases
# ══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[7]:  # Recovery Bases


    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown("### 🔄 Recovery Bases")
    st.caption(
        "Post-capitulation VCP screener — stocks that declined ≥30%, formed a tight base "
        "with volume drying up, then broke out on a surge. "
        "**Triggered** = breakout fired in the last 5 days — the only actionable signal. "
        "**Watchlist** = base forming, no breakout yet — monitoring only, not an entry."
    )

    # ── Audit reference (collapsed by default) ───────────────────────────────
    with st.expander("📋 Screener audit & backtest results (June 2026)", expanded=False):
        st.markdown("""
**Verdict: KEEP AS-IS** — full 11-year backtest (2015–2026), 314-symbol universe (production sector exclusions applied).

---
**Mechanism**

Post-capitulation VCP. Six conditions must be simultaneously true on entry day:
1. **Prior decline ≥30%** from the highest close in the 90 bars before the base started — the "capitulation" requirement
2. **Base tightness <20%** — `_base_scan` walks backwards extending the base until adding one more bar would exceed 20% range (8–90 bar window)
3. **Volume contraction** — last-5d avg < 50% of early-base median, ≥3 bars individually below 60%
4. **Prior surge within base** — ≥2 bars inside the base with volume > 1.5× early-base median (accumulation fingerprint)
5. **Liquidity** — 20d avg vol ≥ 800k; close ≥ Rs.5
6. **Breakout** (Triggered only) — vol ≥ 2.5× vol_MA50 + close > base_high + close in upper 40% of H-L range

Volume baseline (Gates 3 & 4) uses the **median of the first ≤10 base bars**, not vol_MA50 — intentional because the 50-day MA includes the high-volume selling period before the base formed.
The trigger vol gate deliberately uses **vol_MA50** for absolute magnitude comparison.

---
**Backtest — TRIGGERED** (N=22, 2.0/yr, canonical universe)

| Window | N | WR | LR | EV |
|---|---|---|---|---|
| @10d | 25 | 30.0% | 10.0% | +4.6% |
| @20d | 22 | 36.8% | 26.3% | +7.7% |
| @30d | 17 | 41.2% | 35.3% | +5.7% |
| @60d | 16 | **50.0%** | 31.2% | **+12.6%** |

WIN = close > +6% at window close. LOSS = close < −6%. EV = (WR × avg_win) + (LR × avg_loss).
**Optimal holding window: 60 days.** The mechanism takes 1–2 months to resolve; 2–4 week windows are too short.

---
**Backtest — WATCHLIST** (N=1,030, ~90/yr)

| Window | WR | LR | EV |
|---|---|---|---|
| @20d | 28.2% | 32.6% | **+0.5%** |
| @30d | 30.6% | 39.0% | +0.6% |
| @60d | 39.6% | 40.7% | +3.4% |
| @90d | 38.8% | 46.0% | +4.1% (LR > WR) |

**Watchlist appearance alone has no predictive value** — near-zero EV at 20–30d, LR exceeds WR at 90d.
Watchlist is a monitoring filter only. Do not act until Triggered.

---
**Funnel (baseline ≥30%, 522 liquid symbols)**

| Gate | Pairs | Drop |
|---|---|---|
| Base found (≥8 bars) | 162,122 | — |
| Range <20% | 162,122 | 0% — redundant (enforced by _base_scan) |
| Decline ≥30% | 21,599 | 87% |
| Contraction | 4,475 | 79% |
| Surge → Watchlist | 3,201 | 28% |
| Trigger | 27 | 99% |

The 87% drop at the decline gate and 79% at contraction are structural, not tunable.
The rarity (2/yr) reflects the specificity of the setup, not a calibration error.

---
**Variant tested: loosen decline threshold to ≥20%**

| | N / freq | EV @60d |
|---|---|---|
| Baseline ≥30% | 27 / 2.4/yr | +9.5% |
| Variant ≥20% | 67 / 6.1/yr | +2.5% |

Frequency 2.5× higher, EV drops 74%. The 30% threshold is load-bearing — loosening it destroys the edge.
""")

    # ── Read pre-computed recovery signals ───────────────────────
    import sqlite3 as _rec_sq
    from config import DB_PATH as _rec_db

    @st.cache_data(ttl=300, show_spinner=False)
    def _load_recovery_signals():
        if _PG_URL:
            from dashboard_pg import get_recovery_signals_pg
            return get_recovery_signals_pg()
        conn = _rec_sq.connect(_rec_db)
        conn.execute("PRAGMA cache_size=-32000")
        latest = conn.execute(
            "SELECT MAX(as_of_date) FROM recovery_signals"
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM recovery_signals
               WHERE as_of_date = ?""",
            (latest,)
        ).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM recovery_signals LIMIT 0"
        ).description]
        conn.close()
        df = pd.DataFrame(rows, columns=cols)
        return df, latest

    _rec_df, _rec_date = _load_recovery_signals()

    # ── Stale data warning ────────────────────────────────────────
    import datetime as _rec_dt
    _rec_today = _rec_dt.date.today().isoformat()
    if _rec_date != _rec_today:
        st.warning(
            f"⚠️ Recovery signals last computed: "
            f"**{_rec_date}** — run signal_engine.py to refresh."
        )

    if _rec_df.empty:
        st.info("No recovery signals found. Run signal_engine.py first.")
        st.stop()

    # Split into triggered and watchlist — match original variable names
    _wl, _tr = (
        _rec_df[_rec_df["list_type"] == "WATCHLIST"].copy(),
        _rec_df[_rec_df["list_type"] == "TRIGGERED"].copy(),
    )
    kse_regime_ok = bool(
        _rec_df["kse_regime_ok"].iloc[0]
        if "kse_regime_ok" in _rec_df.columns
        and len(_rec_df) > 0 else True
    )
    _regime_ok = kse_regime_ok

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
            _load_recovery_signals.clear()
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
    st.caption(
        "**Not a buy signal.** These stocks meet the base conditions but have not broken out. "
        "Backtested EV for Watchlist appearance alone is near zero — no edge until Triggered. "
        "Use this list to know which stocks to watch; do not act until the breakout fires."
    )

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
        "**Parameters:** Decline >=30% from pre-base high · Base 8-90 bars · Range <20% · "
        "Volume baseline: median of first 10 base bars (base-relative, not vol_ma50) · "
        "Contraction: last-5d avg <0.50x baseline, >=3 days <0.60x · "
        "Prior surge: >=2 bars within base >1.5x baseline · "
        "Trigger: vol >=2.5x vol_MA50 + close > base high + close in upper 40% of H-L range · "
        "Liquidity: 20d avg vol >800K · Min price Rs.5 · "
        "Regime: KSE-100 close vs 10 days ago"
    )

# ── MODEL HEALTH PAGE ─────────────────────────────────────────────────────────
elif cur == PAGES[11]:  # Model Health
    import os as _os
    import subprocess as _sp
    import traceback as _tb

    st.markdown("### 🏥 Model Health Dashboard")
    st.caption("Live accuracy tracking for both ML models. Refresh daily after logging predictions.")

    st.warning(
        "**ML expansion parked — needs a planning conversation before any new work starts.**  \n"
        "Open questions before scoping: (1) prediction target — probability of WINNER label, expected EV, "
        "or time-to-resolution? (2) train/test split methodology given PSX's regime imbalance (89% non-bear "
        "history caused one contaminated backtest this session — same risk applies to ML); "
        "(3) feature leak safety — sector rank and RS columns need point-in-time correctness, not look-ahead; "
        "(4) what would the model add that the rule-based Weinstein gates don't already capture "
        "(EV 10.50%, 92/yr, validated). This page tracks the *existing* model. New ML work: separate session."
    )

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
elif st.session_state.page == PAGES[10]:
    st.markdown("### 🗂️ Stage 2 Portfolio")
    st.caption(
        "Stocks in Weinstein Stage 2 (price above rising 30-week MA) ranked by "
        "Relative Strength vs KSE-100, sector strength, and stage clarity. "
        "Hold until weekly close breaks below the 30-week MA."
    )

    # ── Read pre-computed portfolio signals ──────────────────────
    import sqlite3 as _port_sq
    from config import DB_PATH as _port_db

    @st.cache_data(ttl=300, show_spinner=False)
    def _load_portfolio_signals():
        if _PG_URL:
            from dashboard_pg import get_portfolio_signals_pg
            return get_portfolio_signals_pg()
        conn = _port_sq.connect(_port_db)
        conn.execute("PRAGMA cache_size=-32000")
        latest = conn.execute(
            "SELECT MAX(as_of_date) FROM portfolio_signals"
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM portfolio_signals
               WHERE as_of_date = ?
               ORDER BY rank""",
            (latest,)
        ).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM portfolio_signals LIMIT 0"
        ).description]
        conn.close()
        df = pd.DataFrame(rows, columns=cols)
        return df, latest

    _port_df, _port_date = _load_portfolio_signals()

    # ── Stale data warning ────────────────────────────────────────
    import datetime as _port_dt
    _port_today = _port_dt.date.today().isoformat()
    if _port_date != _port_today:
        st.warning(
            f"⚠️ Portfolio signals last computed: "
            f"**{_port_date}** — run signal_engine.py to refresh."
        )

    if _port_df.empty:
        st.info("No portfolio signals found. Run signal_engine.py first.")
        st.stop()

    port_df = _port_df

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
elif cur == PAGES[12]:  # Agent
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
                            capture_output=True, text=True, timeout=300,
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
        st.caption(
            "Suggestions are validated-signal synthesis — Claude selects and ranks signals already "
            "identified by setup_log / stock_signals / recovery_signals screeners. "
            "Claude's ranking has not been independently backtested."
        )

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
                    _oc1.metric("Entry", f"{_opp.get('entry_price') or 0:.2f}")
                    _oc2.metric("Stop Loss", f"{_opp.get('stop_loss') or 0:.2f}")
                    _oc3.metric("Target 1R", f"{_opp.get('target_1r') or 0:.2f}")
                    _oc4.metric("Target 2R", f"{_opp.get('target_2r') or 0:.2f}")

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
elif cur == PAGES[13]:  # Valuation
    from page_valuation import render_valuation_page
    render_valuation_page()

# ══════════════════════════════════════════════════════════════════════════════


elif False:  # Minervini page removed — killed (N=29 proxy, 86% BREAKOUT overlap, <5 signals/yr)
    pass

elif False:  # Flows page removed — retired 2026-07-29 (Big Fish study: FIPI/LIPI participant
    # flow found NULL, 0/360 forward cells clear the bar; see docs/KIRAN_CLEANUP_AUDIT.md,
    # Priority Findings #1 and #3). page_flows.py's scrape_flows_today() is kept and still
    # runs from main.py's daily hook — sector_signals.py's Flow column on the Market page
    # (Rotation Radar) still reads market_flows, and that column is unaffected by this.
    pass

elif cur == PAGES[14]:  # Leaders
    st.markdown("### 🏆 Leaders — Stock Signal Board")

    _ld_tab_rs, _ld_tab_unified, _ld_tab_scan, _ld_tab_radar = st.tabs([
        "🏆 RS Leaders",
        "📋 Watchlist",
        "🔬 Deep Scan",
        "📡 Radar"
    ])

    # ── Tab 1: RS Leaders ──────────────────────────────────────────────────
    with _ld_tab_rs:
        _ld_latest, _ld_rs_df = _get_leaders_rs_data()
        st.markdown(f"**Latest date:** {_ld_latest} &nbsp;|&nbsp; Liquid stocks only (Avg Vol 10d > 200K)")

        st.markdown("#### 🌍 Top 20 — Market-Wide RS Leaders")
        if _ld_rs_df.empty:
            st.info("No data available.")
        else:
            _ld_top20 = _ld_rs_df.head(20).copy()
            _ld_top20["rank_change"] = _ld_top20["rank_change"].apply(
                lambda x: f"+{int(x)}" if pd.notna(x) and x > 0
                else (f"{int(x)}" if pd.notna(x) and x < 0
                else ("▬" if pd.notna(x) else "—"))
            )
            _ld_top20["rs_score_20"] = _ld_top20["rs_score_20"].apply(
                lambda x: f"{x:.2f}%" if pd.notna(x) else "—"
            )
            _ld_top20["rs_score_50"] = _ld_top20["rs_score_50"].apply(
                lambda x: f"{x:.2f}%" if pd.notna(x) else "—"
            )
            _ld_top20["avg_vol_10d"] = _ld_top20["avg_vol_10d"].apply(
                lambda x: f"{int(x):,}" if pd.notna(x) else "—"
            )
            st.dataframe(
                _ld_top20.rename(columns={
                    "symbol": "Symbol", "sector": "Sector",
                    "rs_score_20": "RS 20d", "rs_score_50": "RS 50d",
                    "rs_rank": "Rank", "rank_change": "Rank Chg",
                    "sector_rs_rank": "Sector Rank",
                    "avg_vol_10d": "Avg Vol 10d"
                }),
                use_container_width=True, hide_index=True
            )

        st.markdown("#### 🏭 Top 3 Per Sector")
        if not _ld_rs_df.empty:
            _ld_sec = (
                _ld_rs_df.sort_values("sector_rs_rank")
                .groupby("sector")
                .head(3)
                .copy()
            )
            _ld_sec["rs_score_20"] = _ld_sec["rs_score_20"].apply(
                lambda x: f"{x:.2f}%" if pd.notna(x) else "—"
            )
            _ld_sec["avg_vol_10d"] = _ld_sec["avg_vol_10d"].apply(
                lambda x: f"{int(x):,}" if pd.notna(x) else "—"
            )
            st.dataframe(
                _ld_sec[["sector", "symbol", "sector_rs_rank",
                          "rs_score_20", "avg_vol_10d"]].rename(columns={
                    "sector": "Sector", "symbol": "Symbol",
                    "sector_rs_rank": "Sector Rank",
                    "rs_score_20": "RS 20d",
                    "avg_vol_10d": "Avg Vol 10d"
                }),
                use_container_width=True, hide_index=True
            )

    # ── Tab 2: Pre-Breakout ────────────────────────────────────────────────
    # ── Tab 2: Unified Watchlist ──────────────────────────────────────────────
    with _ld_tab_unified:
        _uw_scan_date, _uw_df, _uw_bo_dates = _get_leaders_unified_data()

        if not _uw_scan_date:
            st.info("No scan data yet — will populate after next pipeline run.")
        else:
            def _uw_status(row):
                if row['setup_type'] == 'PRE_BREAKOUT':
                    return 'COILING'
                return 'BROKE OUT TODAY' if _uw_bo_dates.get(row['symbol']) == _uw_scan_date else 'ACTIVE BREAKOUT'

            _uw_df['status'] = _uw_df.apply(_uw_status, axis=1)
            _uw_df['breakout_date'] = _uw_df['symbol'].map(_uw_bo_dates)

            _uw_counts = _uw_df['status'].value_counts()
            st.markdown(
                f"**Watchlist — {_uw_scan_date}** &nbsp;|&nbsp; "
                f"Coiling: **{_uw_counts.get('COILING', 0)}** &nbsp;·&nbsp; "
                f"Broke out today: **{_uw_counts.get('BROKE OUT TODAY', 0)}** &nbsp;·&nbsp; "
                f"Active: **{_uw_counts.get('ACTIVE BREAKOUT', 0)}**"
            )

            _uw_col1, _uw_col2 = st.columns([2, 3])
            with _uw_col1:
                _uw_filter = st.selectbox(
                    "Show",
                    ["All", "COILING", "BROKE OUT TODAY", "ACTIVE BREAKOUT"],
                    key="uw_filter",
                )
            with _uw_col2:
                _uw_tight_vol = st.checkbox(
                    "Tight vol only — coiling (vc < 85%)",
                    value=False,
                    key="uw_tight_vol",
                    help="When on: COILING rows restricted to vol_contraction < 85% (volume contracting into the base). Off: all coiling candidates shown regardless of volume behaviour.",
                )

            _uw_show = _uw_df if _uw_filter == "All" else _uw_df[_uw_df['status'] == _uw_filter]
            if _uw_tight_vol:
                # Apply vc gate only to COILING rows; leave breakout rows untouched
                _uw_show = _uw_show[
                    (_uw_show['status'] != 'COILING') |
                    (_uw_show['vol_contraction'].isna() | (_uw_show['vol_contraction'] < 85))
                ]

            if _uw_show.empty:
                st.info("No candidates in this category today.")
            else:
                _uw_disp = _uw_show[[
                    'symbol', 'status', 'breakout_date', 'sector', 'sector_rank',
                    'rs_rank', 'rs_score_20', 'pivot_distance_pct',
                    'base_tightness', 'vol_contraction', 'vol_ratio_today', 'final_score', 'flag',
                ]].copy()
                _uw_disp['rs_score_20'] = _uw_disp['rs_score_20'].apply(
                    lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
                _uw_disp['pivot_distance_pct'] = _uw_disp['pivot_distance_pct'].apply(
                    lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
                _uw_disp['base_tightness'] = _uw_disp['base_tightness'].apply(
                    lambda x: f"{x:.2f}%" if pd.notna(x) else "—")
                _uw_disp['vol_contraction'] = _uw_disp['vol_contraction'].apply(
                    lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
                _uw_disp['vol_ratio_today'] = _uw_disp['vol_ratio_today'].apply(
                    lambda x: f"{x:.1f}x" if pd.notna(x) else "—")
                _uw_disp['final_score'] = _uw_disp['final_score'].apply(
                    lambda x: int(x) if pd.notna(x) else "—")
                _uw_disp['flag'] = _uw_disp['flag'].fillna("—")
                _uw_disp['breakout_date'] = _uw_disp['breakout_date'].fillna("—")

                st.dataframe(
                    _uw_disp.rename(columns={
                        'symbol':              'Symbol',
                        'status':              'Status',
                        'breakout_date':       'BO Date',
                        'sector':              'Sector',
                        'sector_rank':         'Sec Rank',
                        'rs_rank':             'RS Rank',
                        'rs_score_20':         'RS20',
                        'pivot_distance_pct':  'Pct from Pivot',
                        'base_tightness':      'BBW%',
                        'vol_contraction':     'Vol Contr%',
                        'vol_ratio_today':     'Vol Ratio',
                        'final_score':         'Score',
                        'flag':                'Flags',
                    }),
                    use_container_width=True, hide_index=True,
                )

    # ── Tab 3: Deep Scan ──────────────────────────────────────────────────────
    with _ld_tab_scan:
        _ds_scan_date, _ds_all_picks, _ds_audit = _get_leaders_deepscan_data()

        if not _ds_scan_date:
            st.info("No deep scan data yet — will populate after next pipeline run.")
        else:
            st.markdown(f"**Deep Scan — {_ds_scan_date}** &nbsp;|&nbsp; "
                        f"Coiled bases · SL ≤ 7% · Penalty-adjusted scoring · "
                        f"Min score 8 to appear")

            _ds_picks_tab, _ds_audit_tab = st.tabs(["📌 Today's Picks", "📋 Audit Trail"])

            # ── helper: render one pick card ──────────────────────────────────
            def _ds_render_pick(row, setup_type):
                sym         = row['symbol']
                sector      = row['sector']
                sec_rank    = row['sector_rank']
                entry       = row['entry_trigger']
                sl          = row['stop_loss']
                sl_pct      = row['sl_pct']
                vr          = row['vol_ratio_today']
                rank        = int(row['rank'])
                flag_txt    = row['flag'] if pd.notna(row.get('flag','')) and row.get('flag') else None

                rs_infl     = int(row.get('rs_inflection', 0) or 0)
                rs20        = row.get('rs_score_20')
                rs50        = row.get('rs_score_50')
                rank_chg    = row.get('rank_change')
                bt          = row.get('base_tightness')
                overhead    = row.get('nearest_overhead_pct')
                avg_vol     = row.get('avg_vol_10d')
                vol_rej     = int(row.get('vol_rejection_flag', 0) or 0)
                breadth     = row.get('breadth_score')
                pivot_dist  = row.get('pivot_distance_pct')
                final_score = row.get('final_score')

                # ── rank badge colours ────────────────────────────────────────
                _badge_colours = {1: ('#EAF3DE','#3B6D11'),
                                  2: ('#E6F1FB','#185FA5'),
                                  3: ('#FAEEDA','#854F0B')}
                bg, fg = _badge_colours.get(rank, ('#F1EFE8','#5F5E5A'))

                # ── subtitle line ─────────────────────────────────────────────
                if setup_type == 'PRE_BREAKOUT':
                    subtitle = (f"{sector} &nbsp;·&nbsp; pivot `{entry:.2f}` &nbsp;·&nbsp; "
                                f"close `{entry*(1-pivot_dist/100):.2f}` (−{pivot_dist:.2f}%)")
                else:
                    subtitle = (f"{sector} &nbsp;·&nbsp; breakout above `{sl:.2f}` &nbsp;·&nbsp; "
                                f"close `{entry:.2f}` (+{pivot_dist:.2f}%)")

                # ── factor descriptions ───────────────────────────────────────
                _infl_txt = ", **rs_inflection today**" if rs_infl else ""
                _bread_txt = f", {breadth:.0f}% breadth" if pd.notna(breadth or float('nan')) else ""
                fA = f"Rank {sec_rank}/23{_infl_txt}{_bread_txt}"

                _rc_txt  = f"rank_change {rank_chg:+d}" if pd.notna(rank_chg or float('nan')) else "—"
                _r50_txt = f"RS50 {rs50:+.1f}" if pd.notna(rs50 or float('nan')) else ""
                fB = f"{_rc_txt}" + (f", {_r50_txt}" if _r50_txt else "")

                _bt_txt = f"{bt:.2f}% BBW" if pd.notna(bt or float('nan')) else "—"
                fC = _bt_txt

                _vr_txt = f"{vr:.1f}× today" if pd.notna(vr or float('nan')) else "—"
                _rej_txt = " — **vol rejection**" if vol_rej else ""
                fD = f"{_vr_txt}{_rej_txt}"

                if overhead is None or not pd.notna(overhead):
                    fE, grade_E = "Clean — no supply above pivot", "ok"
                elif overhead < 3:
                    fE, grade_E = f"**{overhead:.1f}% above pivot** — tight ceiling", "warn"
                else:
                    fE, grade_E = f"{overhead:.1f}% above pivot", "mid"

                if pd.notna(avg_vol or float('nan')):
                    if avg_vol >= 1_500_000:
                        fF, grade_F = f"{avg_vol/1e6:.1f}M avg — full size", "ok"
                    elif avg_vol >= 500_000:
                        fF, grade_F = f"{avg_vol/1e3:.0f}K avg — half size", "mid"
                    else:
                        fF, grade_F = f"{avg_vol/1e3:.0f}K avg — thin", "warn"
                else:
                    fF, grade_F = "—", "mid"

                # ── entry note ────────────────────────────────────────────────
                if setup_type == 'PRE_BREAKOUT':
                    _entry_note = (
                        f"**Entry trigger:** daily close above `{entry:.2f}` on volume. "
                        f"SL `{sl:.2f}` ({sl_pct:.1f}%). "
                        + (f"*{flag_txt}*" if flag_txt else "")
                    )
                else:
                    _entry_note = (
                        f"**Breakout confirmed.** Buy at market or limit near `{entry:.2f}`. "
                        f"SL at pivot `{sl:.2f}` ({sl_pct:.1f}% risk). "
                        + (f"*{flag_txt}*" if flag_txt else "")
                    )

                # ── render ────────────────────────────────────────────────────
                _border = "2px solid #1D9E75" if not flag_txt else "2px solid #EF9F27"
                st.markdown(
                    f'<div style="border-left:{_border}; padding:4px 0 4px 12px; margin-bottom:4px;">'
                    f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                    f'width:24px;height:24px;border-radius:50%;background:{bg};color:{fg};'
                    f'font-size:13px;font-weight:500;margin-right:8px;">#{rank}</span>'
                    f'<span style="font-size:18px;font-weight:500;">{sym}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                st.markdown(subtitle, unsafe_allow_html=True)

                # metric chips
                _mc1, _mc2, _mc3, _mc4, _mc5, _mc6 = st.columns(6)
                _mc1.metric("Sector rank", f"{sec_rank}/23")
                _mc2.metric("RS inflection", "Yes" if rs_infl else "No")
                _mc3.metric("BBW", f"{bt:.2f}%" if pd.notna(bt or float('nan')) else "—")
                _mc4.metric("RS50", f"{rs50:+.1f}" if pd.notna(rs50 or float('nan')) else "—")
                _mc5.metric("Vol today", f"{vr:.1f}×" if pd.notna(vr or float('nan')) else "—")
                _mc6.metric("Score", f"{int(final_score)}" if pd.notna(final_score or float('nan')) else "—")

                # factor grid — 2 rows × 3 cols
                def _fbox(label, text, grade):
                    _colours = {'ok':'#EAF3DE','warn':'#FCEBEB','mid':'#FAEEDA'}
                    _borders = {'ok':'#1D9E75','warn':'#E24B4A','mid':'#EF9F27'}
                    bg_ = _colours.get(grade,'#F1EFE8')
                    bd_ = _borders.get(grade,'#888780')
                    return (
                        f'<div style="background:{bg_};border-left:3px solid {bd_};'
                        f'border-radius:4px;padding:6px 8px;font-size:12px;">'
                        f'<div style="color:#5F5E5A;font-size:10px;text-transform:uppercase;'
                        f'letter-spacing:.04em;margin-bottom:2px;">{label}</div>'
                        f'<div>{text}</div></div>'
                    )

                _grade_A = 'ok' if sec_rank and sec_rank <= 8 else ('warn' if sec_rank and sec_rank > 12 else 'mid')
                _grade_B = 'ok' if (rank_chg or 0) > 0 and (rs50 or 0) < 10 else ('warn' if (rank_chg or 0) < -20 else 'mid')
                _grade_C = 'ok' if (bt or 10) < 6 else 'mid'
                _grade_D = 'warn' if vol_rej else ('ok' if (vr or 0) > 2 else 'mid')

                _gc1, _gc2, _gc3 = st.columns(3)
                _gc1.markdown(_fbox("A. Sector", fA, _grade_A), unsafe_allow_html=True)
                _gc2.markdown(_fbox("B. RS trajectory", fB, _grade_B), unsafe_allow_html=True)
                _gc3.markdown(_fbox("C. Base", fC, _grade_C), unsafe_allow_html=True)

                _gc4, _gc5, _gc6 = st.columns(3)
                _gc4.markdown(_fbox("D. Volume", fD, _grade_D), unsafe_allow_html=True)
                _gc5.markdown(_fbox("E. Overhead", fE, grade_E), unsafe_allow_html=True)
                _gc6.markdown(_fbox("F. Liquidity", fF, grade_F), unsafe_allow_html=True)

                st.markdown(_entry_note)
                st.divider()

            # ── Today's Picks ─────────────────────────────────────────────────
            with _ds_picks_tab:
                for _ds_type, _ds_label, _ds_icon in [
                    ("PRE_BREAKOUT", "Pre-Breakout", "🎯"),
                    ("BREAKOUT",     "Breakout",     "🚀"),
                ]:
                    st.markdown(f"#### {_ds_icon} {_ds_label} Picks")
                    _ds_subset = _ds_all_picks[_ds_all_picks['setup_type'] == _ds_type]
                    if _ds_subset.empty:
                        st.info(f"No qualifying {_ds_label.lower()} picks today.")
                    else:
                        for _, _r in _ds_subset.iterrows():
                            _ds_render_pick(_r.to_dict(), _ds_type)

            # ── Audit Trail ───────────────────────────────────────────────────
            with _ds_audit_tab:
                st.caption("Picks from ≥10 days ago with outcomes filled. "
                           "'NOT_TRIGGERED' = pre-breakout pivot was never hit in 20 sessions.")

                if _ds_audit.empty:
                    st.info("Audit data builds up after 10 days. Check back then.")
                else:
                    _ds_audit_disp = _ds_audit.copy()

                    def _ds_color_outcome(val):
                        if val == 'WINNER':
                            return 'background-color:#1a472a; color:white; font-weight:bold'
                        if val == 'LOSER':
                            return 'background-color:#6b1c1c; color:white'
                        if val == 'NOT_TRIGGERED':
                            return 'color:#888'
                        return ''

                    _ds_audit_disp['entry_trigger'] = _ds_audit_disp['entry_trigger'].apply(
                        lambda x: f"{x:.2f}")
                    _ds_audit_disp['sl_pct'] = _ds_audit_disp['sl_pct'].apply(
                        lambda x: f"{x:.1f}%")
                    _ds_audit_disp['fwd_return_5d'] = _ds_audit_disp['fwd_return_5d'].apply(
                        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                    _ds_audit_disp['fwd_return_10d'] = _ds_audit_disp['fwd_return_10d'].apply(
                        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                    _ds_audit_disp['fwd_return_20d'] = _ds_audit_disp['fwd_return_20d'].apply(
                        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
                    _ds_audit_disp['triggered'] = _ds_audit_disp['triggered'].apply(
                        lambda x: "Yes" if x == 1 else ("No" if x == 0 else "—"))

                    _ds_cols = [
                        'scan_date', 'setup_type', 'rank', 'symbol', 'sector',
                        'entry_trigger', 'sl_pct', 'triggered', 'trigger_date',
                        'fwd_return_5d', 'fwd_return_10d', 'fwd_return_20d',
                        'outcome_label'
                    ]
                    _ds_renamed = _ds_audit_disp[_ds_cols].rename(columns={
                        'scan_date':      'Date',
                        'setup_type':     'Type',
                        'rank':           'Rank',
                        'symbol':         'Symbol',
                        'sector':         'Sector',
                        'entry_trigger':  'Entry',
                        'sl_pct':         'SL%',
                        'triggered':      'Triggered',
                        'trigger_date':   'Trigger Date',
                        'fwd_return_5d':  'Ret 5d',
                        'fwd_return_10d': 'Ret 10d',
                        'fwd_return_20d': 'Ret 20d',
                        'outcome_label':  'Outcome',
                    })
                    _ds_styled = _ds_renamed.style.map(
                        _ds_color_outcome, subset=["Outcome"]
                    )
                    st.dataframe(_ds_styled, use_container_width=True, hide_index=True)

                    # Summary stats — only rows that triggered
                    _ds_triggered = _ds_audit[_ds_audit['triggered'] == 1].copy()
                    if not _ds_triggered.empty and _ds_triggered['outcome_label'].isin(
                            ['WINNER', 'LOSER', 'BREAKEVEN']).any():
                        _ds_closed = _ds_triggered[
                            _ds_triggered['outcome_label'].isin(['WINNER', 'LOSER', 'BREAKEVEN'])
                        ]
                        _ds_wins  = (_ds_closed['outcome_label'] == 'WINNER').sum()
                        _ds_total = len(_ds_closed)
                        _ds_wr    = _ds_wins / _ds_total * 100 if _ds_total else 0
                        _ds_avg10 = _ds_closed['fwd_return_10d'].mean()
                        _ds_c1, _ds_c2, _ds_c3 = st.columns(3)
                        _ds_c1.metric("Picks closed", _ds_total)
                        _ds_c2.metric("Win rate (10d)", f"{_ds_wr:.0f}%")
                        _ds_c3.metric("Avg 10d return",
                                      f"{_ds_avg10:+.1f}%" if pd.notna(_ds_avg10) else "—")

    # ── Tab 5: Pre-Breakout Radar ─────────────────────────────────────────────
    with _ld_tab_radar:
        _rd_date, _rd_cands, _rd_bos, _rd_sec_rows_raw, _rd_top_picks = _get_leaders_radar_data()

        if not _rd_date:
            st.info("No radar data yet — run the pipeline first.")
        else:
            _rd_n = len(_rd_cands) + len(_rd_bos)
            _rd_regime = _rd_cands['regime'].iloc[0] if not _rd_cands.empty and pd.notna(_rd_cands['regime'].iloc[0]) else "—"

            st.markdown(
                f"**Pre-Breakout Radar — {_rd_date}** &nbsp;|&nbsp; "
                f"{_rd_n} candidates · 5-factor conviction scoring · "
                f"data pulled from psx_data.db &nbsp;&nbsp;"
                f"<span style='float:right;background:#EAF3DE;color:#1D6B3E;padding:2px 8px;"
                f"border-radius:4px;font-size:12px;'>{_rd_regime}</span>",
                unsafe_allow_html=True
            )
            st.divider()

            # ── STEP 1: Full candidate list ───────────────────────────────────
            st.markdown("#### Step 1 — Full Candidate List")

            def _rd_score_color(val):
                if val >= 10: return "background-color:#C6E8C2"
                if val >= 8:  return "background-color:#FFF3C4"
                if val >= 5:  return "background-color:#FFE0B2"
                return "background-color:#FECDD3"

            if not _rd_cands.empty:
                _rd_step1 = _rd_cands[['symbol','sector','rs_rank','sector_rank',
                                        'rs_score_20','avg_vol_10d','base_tightness',
                                        'pivot_distance_pct','sector_composite','final_score']].copy()
                _rd_step1.columns = ['Symbol','Sector','RS Rank','Sec Rank',
                                      'RS20','Avg Vol 10d','BBW%','Pivot Dist%',
                                      'Sector Score','Conviction']
                _rd_step1['Avg Vol 10d'] = (_rd_step1['Avg Vol 10d'] / 1e3).round(0).astype(int).astype(str) + 'K'
                _rd_step1['BBW%']        = _rd_step1['BBW%'].round(2)
                _rd_step1['Pivot Dist%'] = _rd_step1['Pivot Dist%'].round(2)
                _rd_step1['RS20']        = _rd_step1['RS20'].round(2)
                _rd_step1['Sector Score']= _rd_step1['Sector Score'].round(2)
                st.dataframe(
                    _rd_step1.style.map(
                        _rd_score_color, subset=['Conviction']
                    ),
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("No PRE_BREAKOUT candidates today.")

            if not _rd_bos.empty:
                st.markdown("**Breakout candidates**")
                _rd_step1b = _rd_bos[['symbol','sector','rs_rank','sector_rank',
                                       'rs_score_20','avg_vol_10d','base_tightness',
                                       'pivot_distance_pct','sector_composite','final_score']].copy()
                _rd_step1b.columns = ['Symbol','Sector','RS Rank','Sec Rank',
                                       'RS20','Avg Vol 10d','BBW%','Pivot Dist%',
                                       'Sector Score','Conviction']
                _rd_step1b['Avg Vol 10d'] = (_rd_step1b['Avg Vol 10d'] / 1e3).round(0).astype(int).astype(str) + 'K'
                st.dataframe(
                    _rd_step1b.style.map(
                        _rd_score_color, subset=['Conviction']
                    ),
                    use_container_width=True, hide_index=True
                )

            st.divider()

            # ── STEP 2: Sector health snapshot ───────────────────────────────
            st.markdown("#### Step 2 — Sector Health Snapshot (all candidate sectors, today)")

            _rd_all_sectors = list(_rd_cands['sector'].unique()) + list(_rd_bos['sector'].unique())
            _rd_all_sectors = list(dict.fromkeys(_rd_all_sectors))

            if _rd_all_sectors:
                _rd_sec_rows = _rd_sec_rows_raw[_rd_sec_rows_raw['sector'].isin(_rd_all_sectors)]

                # Generate trajectory text from 30-day sector history
                def _rd_trajectory(sector, composite_today):
                    hist = _get_sector_composite_history(sector, _rd_date)
                    if not hist: return "—"
                    vals = [r[0] for r in hist if r[0] is not None]
                    if not vals: return "—"
                    avg30 = sum(vals) / len(vals)
                    trend = composite_today - vals[0] if vals else 0
                    days_top5 = sum(1 for v in vals if v > 0.55)
                    if days_top5 >= 20:    return f"Sustained leader {days_top5}+ days"
                    if trend > 0.05:       return "Sharp re-acceleration today"
                    if trend > 0.02:       return "Advancing steadily"
                    if composite_today > avg30 and trend > 0: return "Building momentum"
                    if composite_today < avg30 and trend < 0: return "Declining trend"
                    if abs(trend) < 0.01:  return "Consolidating"
                    return "Mixed — monitor"

                _rd_sec_display = _rd_sec_rows.copy()
                _rd_sec_display['Trajectory (30d)'] = _rd_sec_display.apply(
                    lambda r: _rd_trajectory(r['sector'], r['composite']), axis=1
                )
                _rd_sec_display['RS Inflection'] = _rd_sec_display['rs_inflection'].apply(
                    lambda x: "YES" if x == 1 else "No"
                )
                _rd_sec_display = _rd_sec_display.rename(columns={
                    'rank_today': 'Rank', 'sector': 'Sector',
                    'composite': 'Composite', 'breadth_score': 'Breadth%',
                    'rs_rank': 'RS Rank', 'regime': 'Regime'
                })[['Rank','Sector','Composite','Breadth%','RS Rank','RS Inflection','Regime','Trajectory (30d)']]
                _rd_sec_display['Composite'] = _rd_sec_display['Composite'].round(3)
                st.dataframe(_rd_sec_display, use_container_width=True, hide_index=True)

            st.divider()

            # ── STEP 4: Honest factor scores ─────────────────────────────────
            st.markdown("#### Step 4 — Honest Factor Scores (A–F) per Candidate")

            def _rd_factor_row(r):
                sym = r['symbol']

                # A. Sector
                sr = r['sector_rank']
                ri = int(r['rs_inflection'] or 0)
                br = r['breadth_score']
                a_parts = [f"Rank {sr}/23"]
                if ri: a_parts.append("rs_inflection today")
                if pd.notna(br): a_parts.append(f"{br:.0f}% breadth")
                fA = ", ".join(a_parts)
                gA = "ok" if sr <= 8 else ("warn" if sr > 12 else "mid")

                # B. RS trajectory
                rc = r['rank_change']
                r50 = r['rs_score_50']
                if pd.notna(rc) and pd.notna(r50):
                    fB = f"{rc:+d} rank, RS50 {r50:+.1f}"
                    gB = "ok" if rc > 0 and r50 < 10 else ("warn" if rc < -20 else "mid")
                elif pd.notna(rc):
                    fB, gB = f"{rc:+d} rank", ("ok" if rc > 0 else "warn")
                else:
                    fB, gB = "—", "mid"

                # C. Base
                bt = r['base_tightness']
                fC = f"{bt:.2f}% BBW" if pd.notna(bt) else "—"
                gC = "ok" if (bt or 10) < 6 else "mid"

                # D. Volume
                vr = r['vol_ratio_today']
                vrej = int(r['vol_rejection_flag'] or 0)
                fD = (f"{vr:.1f}x today" if pd.notna(vr) else "—") + (" — REJECTION" if vrej else "")
                gD = "warn" if vrej else ("ok" if (vr or 0) > 2 else "mid")

                # E. Overhead
                oh = r['nearest_overhead_pct']
                if not pd.notna(oh):
                    fE, gE = "Clean above pivot", "ok"
                elif oh < 3:
                    fE, gE = f"{oh:.1f}% above pivot", "warn"
                else:
                    fE, gE = f"{oh:.1f}% above pivot", "mid"

                # F. Liquidity
                av = r['avg_vol_10d']
                if pd.notna(av):
                    if av >= 1_500_000:   fF, gF = f"{av/1e6:.1f}M — full size", "ok"
                    elif av >= 500_000:   fF, gF = f"{av/1e3:.0f}K — half size", "mid"
                    else:                 fF, gF = f"{av/1e3:.0f}K — thin", "warn"
                else:
                    fF, gF = "—", "mid"

                # Verdict
                fs = r['final_score']
                flag = r['flag'] if pd.notna(r.get('flag','')) and r.get('flag') else None
                if fs >= 11 and not flag:      verdict, vg = "STRONG BUY", "ok"
                elif fs >= 8 and not flag:     verdict, vg = "BUY", "ok"
                elif fs >= 8 and flag:         verdict, vg = f"WATCH — {flag[:30]}", "mid"
                elif fs >= 5:                  verdict, vg = "SKIP — marginal", "mid"
                else:                          verdict, vg = "AVOID", "warn"

                return sym, fA, gA, fB, gB, fC, gC, fD, gD, fE, gE, fF, gF, verdict, vg

            _rd_grade_css = {'ok':'#EAF3DE','mid':'#FAEEDA','warn':'#FCEBEB'}

            def _rd_cell(text, grade):
                bg = _rd_grade_css.get(grade,'#F5F5F5')
                return (f'<td style="background:{bg};padding:5px 8px;font-size:12px;'
                        f'border:1px solid #E0E0E0;">{text}</td>')

            _rd_all_cands = pd.concat([_rd_cands, _rd_bos], ignore_index=True) if not _rd_bos.empty else _rd_cands
            if not _rd_all_cands.empty:
                _rd_tbl = ('<table style="width:100%;border-collapse:collapse;font-size:12px;">'
                           '<tr style="background:#F0F0F0;">'
                           '<th style="padding:5px 8px;text-align:left;">Symbol</th>'
                           '<th style="padding:5px 8px;text-align:left;">A. Sector</th>'
                           '<th style="padding:5px 8px;text-align:left;">B. RS Traj.</th>'
                           '<th style="padding:5px 8px;text-align:left;">C. Base</th>'
                           '<th style="padding:5px 8px;text-align:left;">D. Volume</th>'
                           '<th style="padding:5px 8px;text-align:left;">E. Overhead</th>'
                           '<th style="padding:5px 8px;text-align:left;">F. Liquidity</th>'
                           '<th style="padding:5px 8px;text-align:left;">Verdict</th>'
                           '</tr>')
                for _, _rr in _rd_all_cands.iterrows():
                    sym, fA,gA, fB,gB, fC,gC, fD,gD, fE,gE, fF,gF, verdict,vg = _rd_factor_row(_rr.to_dict())
                    _rd_tbl += ('<tr>'
                                f'<td style="padding:5px 8px;font-weight:500;border:1px solid #E0E0E0;">{sym}</td>'
                                + _rd_cell(fA,gA) + _rd_cell(fB,gB) + _rd_cell(fC,gC)
                                + _rd_cell(fD,gD) + _rd_cell(fE,gE) + _rd_cell(fF,gF)
                                + _rd_cell(verdict,vg) + '</tr>')
                _rd_tbl += '</table>'
                st.markdown(_rd_tbl, unsafe_allow_html=True)

            st.divider()

            # ── STEP 5: Top 3 picks ───────────────────────────────────────────
            st.markdown("#### Step 5 — Top 3 Picks")

            if _rd_top_picks.empty:
                st.info("No picks met the minimum score threshold today.")
            else:
                for _rd_stype, _rd_slabel, _rd_sicon in [
                    ("PRE_BREAKOUT", "Pre-Breakout", "🎯"),
                    ("BREAKOUT",     "Breakout",     "🚀"),
                ]:
                    _rd_subset = _rd_top_picks[_rd_top_picks['setup_type'] == _rd_stype]
                    if not _rd_subset.empty:
                        st.markdown(f"**{_rd_sicon} {_rd_slabel}**")
                        for _, _rr in _rd_subset.iterrows():
                            _ds_render_pick(_rr.to_dict(), _rd_stype)

            # ── Distribution warnings ────────────────────────────────────────
            _rd_flagged = _rd_all_cands[
                _rd_all_cands['flag'].notna() & (_rd_all_cands['flag'] != '') &
                (_rd_all_cands['final_score'] >= 5)
            ] if not _rd_all_cands.empty else pd.DataFrame()

            if not _rd_flagged.empty:
                st.divider()
                st.markdown("#### Distribution Warnings — Conviction score is misleading for these stocks")
                for _, _rr in _rd_flagged.iterrows():
                    _rd_sym = _rr['symbol']
                    _rd_flag = _rr['flag']
                    _rd_fs = int(_rr['final_score'] if pd.notna(_rr['final_score']) else 0)
                    _rd_penalty = int(_rr['penalty'] if pd.notna(_rr['penalty']) else 0)
                    _rd_raw = int(_rr['raw_score'] if pd.notna(_rr['raw_score']) else 0)
                    st.markdown(
                        f'<div style="background:#FFF8F0;border-left:3px solid #EF9F27;'
                        f'padding:8px 12px;margin-bottom:8px;border-radius:4px;">'
                        f'<strong>{_rd_sym}</strong> — conviction {_rd_fs} '
                        f'(raw {_rd_raw} − penalty {_rd_penalty}): '
                        f'<em>{_rd_flag}</em></div>',
                        unsafe_allow_html=True
                    )

elif cur == PAGES[15]:  # Setup History
    st.header('📋 Setup History')
    tab1, tab2 = st.tabs(['📊 Screen Performance', '🔍 Stock Lookup'])

    # ── SUB-TAB 1: SCREEN PERFORMANCE ─────────────────────────────────────────
    with tab1:
        st.subheader('📊 Screen Performance')
        st.caption(
            'Historical win rates and average returns by setup type. '
            'Filter by regime to match current market context.'
        )

        _sp_regimes, _sp_sectors = _sh_load_filter_opts()

        col1, col2, col3 = st.columns(3)
        with col1:
            _sp_regime = st.selectbox(
                'Regime', ['All'] + _sp_regimes, key='sp_regime'
            )
        with col2:
            _sp_sector = st.selectbox(
                'Sector', ['All'] + _sp_sectors, key='sp_sector'
            )
        with col3:
            _sp_type = st.selectbox(
                'Setup Type',
                ['All', 'BREAKOUT', 'PRE_BREAKOUT',
                 'RS_LEADER_MARKET', 'RS_LEADER_SECTOR'],
                key='sp_type'
            )

        _sp_rows = _sh_load_perf(_sp_regime, _sp_sector, _sp_type)

        if not _sp_rows:
            st.info('No setups match the selected filters.')
        else:
            _sp_df = pd.DataFrame(
                _sp_rows,
                columns=[
                    'setup_type', 'regime', 'sector', 'total',
                    'winners', 'losers', 'breakevens',
                    'avg_5d', 'avg_10d', 'avg_20d', 'win_pct'
                ]
            )

            def _sp_color_win(val):
                try:
                    v = float(val)
                    if v >= 50:
                        return 'background-color: #1a4a1a; color: #6fcf6f'
                    elif v < 35:
                        return 'background-color: #4a1a1a; color: #cf6f6f'
                except Exception:
                    pass
                return ''

            def _sp_color_return(val):
                try:
                    v = float(val)
                    if v > 0:
                        return 'color: #6fcf6f'
                    elif v < 0:
                        return 'color: #cf6f6f'
                except Exception:
                    pass
                return ''

            _sp_display = _sp_df[[
                'setup_type', 'regime', 'sector',
                'total', 'win_pct', 'avg_10d', 'avg_20d'
            ]].rename(columns={
                'setup_type': 'Setup Type', 'regime': 'Regime',
                'sector': 'Sector', 'total': 'n',
                'win_pct': 'Win %', 'avg_10d': 'Avg 10d %',
                'avg_20d': 'Avg 20d %'
            })

            st.dataframe(
                _sp_display.style
                    .map(_sp_color_win, subset=['Win %'])
                    .map(_sp_color_return, subset=['Avg 10d %', 'Avg 20d %']),
                use_container_width=True,
                hide_index=True
            )
            if _sp_df['total'].min() < 30:
                st.caption(
                    '⚠️ Rows with n < 30 have low statistical confidence'
                )

    # ── SUB-TAB 2: STOCK LOOKUP ────────────────────────────────────────────────
    with tab2:
        st.subheader('🔍 Stock Lookup')
        st.caption(
            'Full setup history for a single stock — '
            'every screen appearance and its outcome.'
        )

        _sl_symbol = st.text_input(
            'Enter symbol', placeholder='e.g. MEBL', key='sl_symbol'
        ).upper().strip()

        if _sl_symbol:
            _sl_summary, _sl_rows = _sh_load_symbol(_sl_symbol)

            if not _sl_rows:
                st.warning(
                    f'No history found for {_sl_symbol}. '
                    'Check symbol is correct.'
                )
            else:
                _sl_total, _sl_wins, _sl_losses, _sl_be, _sl_avg10d, _sl_winpct = _sl_summary

                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric('Total Appearances', _sl_total or 0)
                mc2.metric('Win Rate %', f'{_sl_winpct or 0:.1f}%')
                mc3.metric('Avg 10d Return', f'{_sl_avg10d or 0:.2f}%')
                mc4.metric(
                    'W / L / BE',
                    f'{_sl_wins or 0} / {_sl_losses or 0} / {_sl_be or 0}'
                )

                _sl_df = pd.DataFrame(
                    _sl_rows,
                    columns=[
                        'setup_date', 'setup_type', 'regime', 'sector',
                        'rs_rank', 'sector_rs_rank', 'rank_change',
                        'rs_score_20', 'base_tightness', 'pivot_distance_pct',
                        'bos_flag', 'fwd_return_5d', 'fwd_return_10d',
                        'fwd_return_20d', 'outcome_label'
                    ]
                )

                _sl_all_null = _sl_df['outcome_label'].isna().all()
                if _sl_all_null:
                    st.info(
                        'Setup logged but outcome window not yet closed.'
                    )

                def _sl_color_outcome(val):
                    if val == 'WINNER':
                        return 'background-color: #1a4a1a; color: #6fcf6f'
                    elif val == 'LOSER':
                        return 'background-color: #4a1a1a; color: #cf6f6f'
                    elif val == 'BREAKEVEN':
                        return 'color: #aaaaaa'
                    return ''

                def _sl_color_ret(val):
                    try:
                        v = float(val)
                        if v > 0:
                            return 'color: #6fcf6f'
                        elif v < 0:
                            return 'color: #cf6f6f'
                    except Exception:
                        pass
                    return ''

                _sl_disp = _sl_df.rename(columns={
                    'setup_date': 'Date', 'setup_type': 'Setup Type',
                    'regime': 'Regime', 'sector': 'Sector',
                    'rs_rank': 'RS Rank', 'sector_rs_rank': 'Sector Rank',
                    'rank_change': 'Rank Δ', 'rs_score_20': 'RS Score',
                    'base_tightness': 'BBW%',
                    'pivot_distance_pct': 'Pivot Dist%',
                    'bos_flag': 'BOS', 'fwd_return_5d': '5d %',
                    'fwd_return_10d': '10d %', 'fwd_return_20d': '20d %',
                    'outcome_label': 'Outcome'
                })

                st.dataframe(
                    _sl_disp.style
                        .map(_sl_color_outcome, subset=['Outcome'])
                        .map(_sl_color_ret, subset=['10d %']),
                    use_container_width=True,
                    hide_index=True
                )

elif cur == PAGES[16]:  # Data Health
    import sqlite3
    from config import DB_PATH as _dh_db
    from datetime import datetime as _dh_dt

    st.markdown("### 🏥 Data Health — Corporate Action Review")

    def _dh_load_summary():
        if _PG_URL:
            from dashboard_pg import get_dh_summary_pg
            return get_dh_summary_pg()
        _con = sqlite3.connect(_dh_db)
        try:
            pending = _con.execute(
                "SELECT COUNT(*) FROM corporate_action_suspects WHERE status = 'PENDING'"
            ).fetchone()[0]
            confirmed = _con.execute(
                "SELECT COUNT(*) FROM corporate_action_suspects "
                "WHERE status = 'CONFIRMED' AND confirmed_at >= ?",
                (str(_dh_dt.now().year),)
            ).fetchone()[0]
            last_checked = _con.execute(
                "SELECT MAX(suspect_date) FROM corporate_action_suspects"
            ).fetchone()[0] or "—"
        finally:
            _con.close()
        return pending, confirmed, last_checked

    def _dh_load_pending_df():
        if _PG_URL:
            from dashboard_pg import get_dh_pending_df_pg
            return get_dh_pending_df_pg()
        _con = sqlite3.connect(_dh_db)
        try:
            return pd.read_sql_query("""
                SELECT id, symbol, suspect_date, close_before, close_after,
                       drop_pct, likely_category
                FROM corporate_action_suspects
                WHERE status = 'PENDING'
                ORDER BY suspect_date DESC
            """, _con)
        finally:
            _con.close()

    def _dh_load_history_df():
        if _PG_URL:
            from dashboard_pg import get_dh_history_df_pg
            return get_dh_history_df_pg()
        _con = sqlite3.connect(_dh_db)
        try:
            return pd.read_sql_query("""
                SELECT symbol, suspect_date, drop_pct, likely_category,
                       confirmed_action, adjustment_factor, confirmed_at, status
                FROM corporate_action_suspects
                WHERE status IN ('CONFIRMED', 'FALSE_POSITIVE')
                ORDER BY confirmed_at DESC
            """, _con)
        finally:
            _con.close()

    # ── Section 1: Summary metrics ─────────────────────────────────────────
    _dh_pending, _dh_confirmed, _dh_last_checked = _dh_load_summary()

    _dh_c1, _dh_c2, _dh_c3 = st.columns(3)
    _dh_c1.metric("⚠️ Pending Review", _dh_pending)
    _dh_c2.metric("✅ Confirmed This Year", _dh_confirmed)
    _dh_c3.metric("🔍 Last Checked", _dh_last_checked)

    st.markdown("---")

    # ── Section 2: Tabs ────────────────────────────────────────────────────
    _dh_tab_pending, _dh_tab_history = st.tabs(["⚠️ Pending Review", "📋 History"])

    # ── Tab 1: Pending Review ────────────────────────────────────────────────
    with _dh_tab_pending:
        _dh_pending_df = _dh_load_pending_df()

        if _dh_pending_df.empty:
            st.success("No pending corporate actions — all clear.")
        else:
            st.dataframe(
                _dh_pending_df.rename(columns={
                    "symbol": "Symbol", "suspect_date": "Date",
                    "close_before": "Close Before", "close_after": "Close After",
                    "drop_pct": "Drop %", "likely_category": "Likely Type"
                }).drop(columns=["id"]),
                use_container_width=True, hide_index=True
            )

            st.markdown("---")
            st.markdown("**Review each suspect:**")

            for _, _dh_row in _dh_pending_df.iterrows():
                _dh_sym  = _dh_row["symbol"]
                _dh_date = _dh_row["suspect_date"]
                _dh_cb   = _dh_row["close_before"]
                _dh_ca   = _dh_row["close_after"]

                with st.expander(f"{_dh_sym}  ·  {_dh_date}  ·  {_dh_row['drop_pct']:.1f}%  ·  {_dh_row['likely_category']}"):
                    _dh_action = st.selectbox(
                        "Action Type",
                        ["Dividend", "Bonus", "Right Share"],
                        key=f"dh_action_{_dh_sym}_{_dh_date}"
                    )
                    _dh_btn1, _dh_btn2 = st.columns(2)

                    with _dh_btn1:
                        if st.button("✅ Confirm", key=f"dh_confirm_{_dh_sym}_{_dh_date}"):
                            if _PG_URL:
                                # Hard-blocked on purpose (see CLAUDE.md "Known Gaps"):
                                # rebuild_symbol_adjusted_pg() would correctly fix
                                # prices_adjusted, but recompute_symbol_signals()
                                # (stock_signals.py) has no Postgres port, and the
                                # nightly pipeline only appends new dates -- it never
                                # revisits historical stock_signals rows. Letting
                                # Confirm through here would leave Explorer /
                                # RS_LEADER / BREAKOUT / setup_log reading stale
                                # pre-correction signals for this symbol indefinitely,
                                # with no way to sync a local fix back. Nothing is
                                # written below -- neither table is touched.
                                st.error(
                                    f"Confirm is disabled on Postgres for {_dh_sym}: "
                                    f"prices_adjusted could be fixed, but stock_signals "
                                    f"recompute has no Postgres port yet, and the nightly "
                                    f"pipeline never revisits historical stock_signals rows "
                                    f"once written -- this symbol's Explorer/RS_LEADER/"
                                    f"BREAKOUT/setup_log signals would stay wrong "
                                    f"indefinitely with no way to sync a local fix back. "
                                    f"Nothing has been written. Confirm this suspect from a "
                                    f"local SQLite session instead, or wait for the "
                                    f"stock_signals Postgres port."
                                )
                            else:
                                try:
                                    from apply_price_adjustments import rebuild_symbol_adjusted
                                    from stock_signals import recompute_symbol_signals
                                    _dh_factor = _dh_ca / _dh_cb
                                    _dh_adj_con = sqlite3.connect(_dh_db)
                                    rebuild_symbol_adjusted(_dh_adj_con, _dh_sym, _dh_date, _dh_factor)
                                    _dh_adj_con.execute(
                                        """UPDATE corporate_action_suspects
                                           SET status = 'CONFIRMED',
                                               confirmed_action = ?,
                                               adjustment_factor = ?,
                                               confirmed_at = ?
                                           WHERE symbol = ? AND suspect_date = ?""",
                                        (_dh_action, _dh_factor,
                                         _dh_dt.now().isoformat(),
                                         _dh_sym, _dh_date)
                                    )
                                    _dh_adj_con.commit()
                                    _dh_adj_con.close()
                                    recompute_symbol_signals(_dh_sym)
                                    st.success(f"{_dh_sym} adjusted and signals recomputed.")
                                    st.rerun()
                                except Exception as _dh_e:
                                    st.error(f"Error: {_dh_e}")

                    with _dh_btn2:
                        if st.button("❌ False Positive", key=f"dh_fp_{_dh_sym}_{_dh_date}"):
                            try:
                                _dh_now = _dh_dt.now().isoformat()
                                if _PG_URL:
                                    from dashboard_pg import mark_dh_false_positive_pg
                                    mark_dh_false_positive_pg(_dh_sym, _dh_date, _dh_now)
                                else:
                                    _dh_fp_con = sqlite3.connect(_dh_db)
                                    _dh_fp_con.execute(
                                        """UPDATE corporate_action_suspects
                                           SET status = 'FALSE_POSITIVE',
                                               confirmed_at = ?
                                           WHERE symbol = ? AND suspect_date = ?""",
                                        (_dh_now, _dh_sym, _dh_date)
                                    )
                                    _dh_fp_con.commit()
                                    _dh_fp_con.close()
                                st.info(f"{_dh_sym} marked as false positive.")
                                st.rerun()
                            except Exception as _dh_e:
                                st.error(f"Error: {_dh_e}")

    # ── Tab 2: History ───────────────────────────────────────────────────────
    with _dh_tab_history:
        _dh_hist_df = _dh_load_history_df()

        if _dh_hist_df.empty:
            st.info("No confirmed or dismissed events yet.")
        else:
            _dh_hist_df["adjustment_factor"] = _dh_hist_df["adjustment_factor"].apply(
                lambda x: f"{x:.4f}" if pd.notna(x) else "—"
            )
            _dh_hist_df["drop_pct"] = _dh_hist_df["drop_pct"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "—"
            )
            st.dataframe(
                _dh_hist_df.rename(columns={
                    "symbol": "Symbol", "suspect_date": "Date",
                    "drop_pct": "Drop %", "likely_category": "Category",
                    "confirmed_action": "Action", "adjustment_factor": "Factor",
                    "confirmed_at": "Confirmed At", "status": "Status"
                }),
                use_container_width=True, hide_index=True
            )
