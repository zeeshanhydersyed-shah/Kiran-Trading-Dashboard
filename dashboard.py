"""PSX Sector Performance Dashboard — KIRAN."""

import json
import sys
import logging
from datetime import datetime

import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import joblib
import pandas as pd
import streamlit as st

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
    save_trade_setup, get_trade_setups, update_trade_setup, close_trade_setup,
    activate_trade_setup, delete_trade_setup, auto_save_setups, get_backtest_summary,
    auto_save_stm_picks, get_sim_portfolio_data,
)
from processor import run_analysis
from main import cmd_update

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

@st.cache_data(ttl=1800, show_spinner=False)
def load_data() -> dict:
    init_db()
    return run_analysis()


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
    model_path    = os.path.join(_MODEL_DIR, "kiran_model.pkl")
    features_path = os.path.join(_MODEL_DIR, "kiran_model_features.pkl")
    if not os.path.exists(model_path) or not os.path.exists(features_path):
        return None, None
    try:
        model    = joblib.load(model_path)
        features = joblib.load(features_path)
        return model, features
    except Exception:
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

PAGES = ["📊 Market", "📈 History", "💡 Setups", "📋 Trade Log", "🔍 Explorer", "📉 Analytics", "🤖 Backtest", "🧭 Regime", "🎯 Setup Perf", "🔎 STM", "🏥 Model Health", "🗂️ Portfolio"]


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
    if st.button("🔄 Refresh Data", use_container_width=True, type="primary", key="sb_refresh"):
        with st.spinner("Updating…"):
            try:
                cmd_update()
                st.cache_data.clear()
                st.success("Done!")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    mn, mx = get_price_date_range()
    st.caption(
        f"📅 {fmt_date(mn)} → {fmt_date(mx)}  \n"
        f"**{count_prices():,}** prices · **{count_sectors():,}** symbols  \n"
        f"As of {datetime.now().strftime('%d/%m/%y %H:%M')}"
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

# ── Breadth banner ─────────────────────────────────────────────────────────────
if breadth:
    cond   = breadth["condition"]
    color  = breadth["color"]
    emoji  = breadth["emoji"]
    score  = breadth["breadth_score"]
    spct   = breadth["stock_pct_pos"]
    secpct = breadth["sector_pct_pos"]
    avg_p  = breadth["avg_sector_perf"]

    # KSE-100 50-day MA pill
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
                Score <b>{score:.0f}/100</b> &nbsp;·&nbsp;
                Stocks positive <b>{spct}%</b> &nbsp;·&nbsp;
                Sectors positive <b>{secpct}%</b> &nbsp;·&nbsp;
                Avg sector perf <b>{avg_p:+.2f}%</b> &nbsp;·&nbsp;
                {GUIDANCE.get(cond, "")}
            </span>
        </div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px;
            padding:5px 14px; margin-bottom:8px; font-size:0.72rem; color:#64748b;">
            📈 {kse_txt}{kse_note}
        </div>""",
        unsafe_allow_html=True,
    )

# ── Navigation bar ─────────────────────────────────────────────────────────────
nav_cols = st.columns(len(PAGES))
for i, pg in enumerate(PAGES):
    btn_type = "primary" if st.session_state.page == pg else "secondary"
    if nav_cols[i].button(pg, key=f"nav_{i}", use_container_width=True, type=btn_type):
        st.session_state.page = pg
        st.rerun()

st.divider()

cur = st.session_state.page



# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — MARKET
# ═══════════════════════════════════════════════════════════════════════════════
if cur == PAGES[0]:

    # Bar chart
    try:
        import plotly.express as px
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
    except ImportError:
        st.info("pip install plotly")

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
        use_container_width=True, hide_index=True, height=460,
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

    # Quick long/short ideas
    st.divider()
    st.markdown("**Quick Ideas** — strongest / weakest stock per top-3 / bottom-3 sectors")
    ci1, ci2 = st.columns(2)
    with ci1:
        st.caption("🟢 Long candidates")
        if not long_cands.empty:
            st.dataframe(
                long_cands.style
                .apply(style_pct_cols, subset=["30d Perf %"])
                .format({"30d Perf %": "{:.2f}", "Latest Close": "{:.2f}"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("—")
    with ci2:
        st.caption("🔴 Short candidates")
        if not short_cands.empty:
            st.dataframe(
                short_cands.style
                .apply(style_pct_cols, subset=["30d Perf %"])
                .format({"30d Perf %": "{:.2f}", "Latest Close": "{:.2f}"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("—")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[1]:
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
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("Select at least one sector.")
    except ImportError:
        st.info("pip install plotly")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — SETUPS
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[2]:
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
            elif rec_st in ("Hit Target", "Hit SL", "Breakeven", "Cancelled"):
                outcome_col = "#22c55e" if rec_st == "Hit Target" else (
                    "#ef4444" if rec_st == "Hit SL" else "#94a3b8")
                st.markdown(
                    f"<div style='font-size:0.7rem; color:{outcome_col}; font-weight:600; "
                    f"margin-bottom:6px;'>⬛ Closed — {rec_st}</div>",
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
elif cur == PAGES[3]:
    st.markdown("**Trade Log**")
    st.caption(
        "**System** = KIRAN's recommendation (taken or not). "
        "**STM** = Short-Term Momentum screener pick, auto-saved daily for tracking. "
        "**Actual** = a trade you took that neither screener suggested (log it below)."
    )

    all_saved = get_trade_setups()

    # ── Log table ─────────────────────────────────────────────────────────────
    if not all_saved:
        st.info("No entries yet. Save a setup above or log an actual trade below.")
    else:
        log_df = pd.DataFrame(all_saved)

        if "source" not in log_df.columns:
            log_df["source"] = "System"
        log_df["source"] = log_df["source"].fillna("System")

        flt1, flt2, flt3 = st.columns([2, 2, 2])
        sf       = flt1.selectbox("Status", ["All","Pending","Active","Hit Target","Hit SL","Cancelled"], key="log_sf")
        src      = flt2.selectbox("Source", ["All","System","STM","Actual"], key="log_src")
        sym_srch = flt3.text_input("Symbol search", placeholder="e.g. BAFL", key="log_sym").strip().upper()

        if sf       != "All": log_df = log_df[log_df["status"] == sf]
        if src      != "All": log_df = log_df[log_df["source"]  == src]
        if sym_srch:          log_df = log_df[log_df["symbol"].str.upper().str.contains(sym_srch, na=False)]

        # Ensure exit_date column exists (older cached runs may not have it)
        if "exit_date" not in log_df.columns:
            log_df["exit_date"] = None
        if "actual_exit" not in log_df.columns:
            log_df["actual_exit"] = None
        if "actual_pl_pct" not in log_df.columns:
            log_df["actual_pl_pct"] = None
        if "holding_days" not in log_df.columns:
            log_df["holding_days"] = None

        if "actual_entry" not in log_df.columns:
            log_df["actual_entry"] = None

        display_log = log_df[[
            "id", "created_date", "exit_date", "source", "direction", "symbol",
            "entry_price", "actual_entry", "stop_loss", "actual_exit",
            "risk_pct", "actual_pl_pct", "holding_days",
            "status", "outcome", "notes",
        ]].copy()
        display_log.columns = [
            "ID", "Entry Date", "Exit Date", "Source", "Dir", "Symbol",
            "KIRAN Entry", "My Fill", "SL", "Exit",
            "Risk%", "P&L%", "Days",
            "Status", "Outcome", "Notes",
        ]
        # Format dates as DD/MM/YY
        display_log["Entry Date"] = display_log["Entry Date"].apply(fmt_date)
        display_log["Exit Date"]  = display_log["Exit Date"].apply(fmt_date)

        def style_source(series):
            return [
                "color:#3b82f6;font-weight:bold" if v == "System"
                else "color:#0ea5e9;font-weight:bold" if v == "STM"
                else "color:#f59e0b;font-weight:bold"
                for v in series
            ]

        fmt_map = {
            "KIRAN Entry": "{:.2f}", "My Fill": "{:.2f}",
            "SL": "{:.2f}", "Exit": "{:.2f}",
            "Risk%": "{:.2f}", "P&L%": "{:.2f}", "Days": "{:.0f}",
        }
        st.dataframe(
            display_log.style
            .apply(style_source,    subset=["Source"])
            .apply(style_direction, subset=["Dir"])
            .apply(style_outcome,   subset=["Outcome"])
            .apply(style_pct_cols,  subset=["P&L%"])
            .format(fmt_map, na_rep="—"),
            use_container_width=True, hide_index=True, height=340,
        )

    # ── Activate a pending trade ──────────────────────────────────────────────
    if all_saved:
        pending_trades = [
            t for t in all_saved
            if t.get("status") == "Pending"
            and t.get("source") in ("System", "STM")
        ]
        if pending_trades:
            st.divider()
            st.markdown("**✏️ I took this trade**")
            st.caption(
                "Select a Pending setup (System or STM) you actually entered. "
                "Records your fill and marks it Active — no duplicate created."
            )
            act_opts = {
                f"#{t['id']} · {t['symbol']} {t['direction']} "
                f"@ {t['entry_price']:.2f}  [{t.get('source','?')} · {fmt_date(t['created_date'])}]": t
                for t in pending_trades
            }
            with st.form("activate_trade_form", clear_on_submit=True):
                act_chosen_label = st.selectbox(
                    "Pending setup", list(act_opts.keys()),
                    label_visibility="collapsed", key="act_sel",
                )
                act_chosen = act_opts[act_chosen_label]

                af1, af2 = st.columns([1, 3])
                act_fill  = af1.number_input(
                    "My fill price", min_value=0.0,
                    value=float(act_chosen["entry_price"]),
                    step=0.01, format="%.2f",
                )
                act_note = af2.text_input("Notes (optional)", placeholder="e.g. filled at open, partial")

                if st.form_submit_button("✏️ Mark as Active", type="primary"):
                    fill = act_fill if act_fill > 0 else None
                    activate_trade_setup(act_chosen["id"], fill, act_note.strip() or None)
                    st.success(
                        f"{act_chosen['symbol']} {act_chosen['direction']} "
                        f"marked Active — fill {fill:.2f}" if fill else
                        f"{act_chosen['symbol']} {act_chosen['direction']} marked Active."
                    )
                    st.rerun()

    # ── Log a non-KIRAN trade ─────────────────────────────────────────────────
    st.divider()
    st.markdown("**Log a non-KIRAN trade**")
    st.caption(
        "Use this **only** for trades no screener suggested. "
        "For System or STM setups, use **✏️ I took this trade** above — "
        "that updates the existing record instead of creating a duplicate."
    )

    with st.form("actual_trade_form", clear_on_submit=True):
        a1, a2, a3, a4 = st.columns([1, 1, 1, 1])
        act_symbol  = a1.text_input("Symbol", placeholder="e.g. FABL")
        act_dir     = a2.selectbox("Direction", ["LONG", "SHORT"])
        act_date    = a3.date_input("Trade Date", value=datetime.now().date())
        act_sector  = a4.text_input("Sector", placeholder="optional")

        b1, b2, b3, b4 = st.columns([1, 1, 1, 1])
        act_entry  = b1.number_input("Entry Price",  min_value=0.0, step=0.01, format="%.2f")
        act_sl     = b2.number_input("Stop Loss",    min_value=0.0, step=0.01, format="%.2f")
        act_target = b3.number_input("Target (T2R)", min_value=0.0, step=0.01, format="%.2f")
        act_notes  = b4.text_input("Notes", placeholder="why you took it, any context")

        submitted = st.form_submit_button("➕ Add to Log", type="primary")
        if submitted:
            sym = act_symbol.strip().upper()
            if not sym:
                st.error("Symbol is required.")
            elif act_entry <= 0:
                st.error("Entry price must be > 0.")
            elif act_sl <= 0:
                st.error("Stop loss must be > 0.")
            else:
                if act_dir == "LONG":
                    risk = round((act_entry - act_sl) / act_entry * 100, 2) if act_entry > act_sl else 0.0
                else:
                    risk = round((act_sl - act_entry) / act_entry * 100, 2) if act_sl > act_entry else 0.0

                actual_record = {
                    "created_date":    act_date.isoformat(),
                    "direction":       act_dir,
                    "symbol":          sym,
                    "sector":          act_sector.strip() or "—",
                    "sector_momentum": "—",
                    "stock_perf_30d":  0.0,
                    "stock_perf_10d":  0.0,
                    "latest_close":    act_entry,
                    "entry_price":     act_entry,
                    "stop_loss":       act_sl,
                    "target_1r":       act_target,
                    "target_2r":       act_target,
                    "risk_pct":        risk,
                    "atr_pct":         0.0,
                    "notes":           act_notes.strip(),
                    "source":          "Actual",
                }
                save_trade_setup(actual_record)
                st.success(f"{sym} {act_dir} logged as Actual trade.")
                st.rerun()

    # ── Close an open position ────────────────────────────────────────────────
    if all_saved:
        active_trades = [t for t in all_saved if t.get("status") in ("Active", "Pending")]
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
            cl_result = cl4.selectbox("Result", ["Hit Target", "Hit SL", "Breakeven", "Cancelled"],
                                      key="cl_result", label_visibility="collapsed")
            cl_notes  = cl5.text_input("Notes", placeholder="e.g. trailed stop", key="cl_notes",
                                       label_visibility="collapsed")

            with cl6:
                st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
                if st.button("✅ Close", key="btn_close", type="primary"):
                    if exit_px <= 0:
                        st.error("Enter a valid exit price.")
                    else:
                        outcome_map = {"Hit Target": "Win", "Hit SL": "Loss",
                                       "Breakeven": "Breakeven", "Cancelled": "Breakeven"}
                        pkr_override = float(cl_pkr) if cl_pkr != 0 else None
                        close_trade_setup(
                            setup_id               = int(chosen_trade["id"]),
                            exit_price             = float(exit_px),
                            exit_date              = exit_dt.isoformat(),
                            status                 = cl_result,
                            outcome                = outcome_map[cl_result],
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

    # ── Update a setup ────────────────────────────────────────────────────────
    if all_saved:
        st.divider()
        st.markdown("**Update a setup**")
        u1, u2, u3, u4, u5 = st.columns([1, 2, 2, 3, 1])
        upd_id      = u1.number_input("ID", min_value=1, step=1, key="upd_id", label_visibility="collapsed")
        upd_status  = u2.selectbox("Status", ["Pending","Active","Hit Target","Hit SL","Cancelled"], key="upd_st", label_visibility="collapsed")
        upd_outcome = u3.selectbox("Outcome", ["—","Win","Loss","Breakeven"], key="upd_oc", label_visibility="collapsed")
        upd_notes   = u4.text_input("Notes", placeholder="Notes…", key="upd_no", label_visibility="collapsed")
        u1.caption("ID"); u2.caption("Status"); u3.caption("Outcome"); u4.caption("Notes")
        with u5:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Update", key="btn_upd"):
                update_trade_setup(
                    int(upd_id),
                    upd_status,
                    None if upd_outcome == "—" else upd_outcome,
                    upd_notes.strip() or None,
                )
                st.success(f"#{int(upd_id)} updated")
                st.rerun()

    # ── Delete a duplicate / erroneous entry ─────────────────────────────────
    if all_saved:
        st.divider()
        with st.expander("🗑️ Delete an entry", expanded=False):
            st.caption("Use this to remove duplicate or mistaken entries. This cannot be undone.")
            d1, d2, d3 = st.columns([1, 4, 1])
            del_id = d1.number_input("ID to delete", min_value=1, step=1,
                                     key="del_id", label_visibility="collapsed")
            d1.caption("ID")

            # Preview the row before deletion
            del_preview = next((r for r in all_saved if r["id"] == int(del_id)), None)
            if del_preview:
                d2.markdown(
                    f"<div style='font-size:0.8rem; padding:6px 0;'>"
                    f"<b>#{del_preview['id']}</b> &nbsp;·&nbsp; "
                    f"{del_preview['symbol']} {del_preview['direction']} &nbsp;·&nbsp; "
                    f"{del_preview.get('source','—')} &nbsp;·&nbsp; "
                    f"Status: <b>{del_preview.get('status','—')}</b> &nbsp;·&nbsp; "
                    f"Date: {fmt_date(del_preview.get('created_date'))}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                d2.caption("Enter an ID to preview the record.")

            with d3:
                st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
                if st.button("🗑️ Delete", key="btn_del", type="secondary"):
                    if del_preview is None:
                        st.error(f"ID {int(del_id)} not found.")
                    else:
                        delete_trade_setup(int(del_id))
                        st.success(f"#{int(del_id)} deleted.")
                        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[4]:
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
            use_container_width=True, hide_index=True, height=480,
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
                    st.plotly_chart(fig2, use_container_width=True)
                except ImportError:
                    st.dataframe(h_df, use_container_width=True, hide_index=True)
            else:
                st.info(f"No price data for {chosen_symbol}.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
elif cur == PAGES[5]:
    import plotly.graph_objects as go

    # ── Pull all closed trades (System-taken + Actual) ────────────────────────
    all_trades = get_trade_setups()
    adf = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    closed = pd.DataFrame()
    if not adf.empty:
        if "source" not in adf.columns:
            adf["source"] = "System"
        adf["source"] = adf["source"].fillna("System")
        # Include any trade (System or Actual) that has a resolved outcome
        closed = adf[
            adf["outcome"].isin(["Win", "Loss", "Breakeven"])
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
        st.info("No closed trades yet. Close positions in the Trade Log first.")
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
    profit_factor = (gross_win / abs(gross_loss)) if gross_loss < 0 else float("inf")

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
    closed["_yr"]  = ref_date.dt.year.astype("Int64")
    closed["_mo"]  = ref_date.dt.month.astype("Int64")

    MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]

    pivot = (
        closed.groupby(["_yr","_mo"])["actual_pl_pkr"]
        .sum()
        .reset_index()
        .pivot(index="_yr", columns="_mo", values="actual_pl_pkr")
    )
    pivot.columns = [MONTH_NAMES[m-1] for m in pivot.columns]
    pivot.index.name = "Year"

    all_months = MONTH_NAMES
    for m in all_months:
        if m not in pivot.columns:
            pivot[m] = float("nan")
    pivot = pivot[all_months]
    pivot["Total"] = pivot.sum(axis=1, skipna=True, min_count=1)

    # ── Colour-coded HTML table ───────────────────────────────────────────────
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

    # Grand total row — min_count=1 keeps NaN when a whole column is empty
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

    # ── Cumulative P&L curve ──────────────────────────────────────────────────
    st.markdown("**Cumulative P&L  (PKR)**")
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
    st.plotly_chart(fig_cum, use_container_width=True)

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
        st.plotly_chart(fig_d, use_container_width=True)

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
        st.plotly_chart(fig_b, use_container_width=True)


# ===============================================================================
# PAGE 7 -- BACKTEST
# ===============================================================================
elif cur == PAGES[6]:
    import plotly.graph_objects as go

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
        st.plotly_chart(fig_pie, use_container_width=True)

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
                st.plotly_chart(fig_qs, use_container_width=True)

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
    st.plotly_chart(fig_mo, use_container_width=True)

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
            st.plotly_chart(fig_eq, use_container_width=True)
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
        use_container_width=True, hide_index=True, height=380,
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
            st.plotly_chart(fig_sim, use_container_width=True)
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
elif cur == PAGES[7]:
    try:
        import plotly.graph_objects as go
        import plotly.express as px
    except ImportError:
        st.error("pip install plotly")
        st.stop()

    from weinstein import (
        WeinsteinIndicator, run_optimizer,
        PSX_DEFAULTS, PSX_KNOWN_BOTTOMS, PSX_KNOWN_TOPS,
    )

    st.markdown(
        "**Market Regime — Weinstein Breadth Z-Score**  \n"
        "<span style='font-size:0.75rem; color:#64748b;'>"
        "Measures the statistical extreme of market breadth (% of PSX stocks above 50-day MA) "
        "relative to the past year. Signals fire when breadth crosses out of oversold/overbought "
        "territory, confirmed by KSE-100 price action."
        "</span>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Load data ──────────────────────────────────────────────────────────────
    with st.spinner("Computing breadth series…"):
        wd = load_weinstein_data()

    if wd.get("error"):
        st.error("Weinstein data error — see traceback below")
        st.code(wd["error"], language="python")
        st.stop()

    breadth  = wd["breadth"]
    signals  = wd["signals"]
    regime   = wd["regime"]
    w_params = wd["params"]

    # ── Signal banner ──────────────────────────────────────────────────────────
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

    parts = [
        f'<span style="color:{zcolor}; font-weight:700;">{zone}</span>',
        f'<span style="color:{dir_color}; font-weight:700;">{dir_arrow} {direction}</span>',
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
    st.plotly_chart(fig, use_container_width=True)

    # ── Signal history table ───────────────────────────────────────────────────
    with st.expander("Signal history (all non-HOLD signals)"):
        sig_events = signals[signals["signal"] != 0].copy()
        if sig_events.empty:
            st.info("No signals generated yet.")
        else:
            sig_events = sig_events.tail(50).copy()
            sig_events.index.name = "Date"
            sig_events = sig_events.reset_index()
            sig_events["Date"]   = sig_events["Date"].dt.strftime("%d %b %Y")
            sig_events["Signal"] = sig_events["signal"].map({1:"BUY", -1:"SELL"})
            sig_events["Fast Z"] = sig_events["fast_z"].round(2)
            sig_events["Sig Line"] = sig_events["signal_line"].round(2)
            sig_events["Histogram"] = sig_events["z_histogram"].round(2) if "z_histogram" in sig_events.columns else "—"
            sig_events["% Above MA"] = sig_events["pct_above_ma"].round(1)
            sig_events["KSE-100"] = sig_events["index_close"].round(0)

            def _col_signal(s):
                c = {"BUY": "#22c55e", "SELL": "#ef4444"}
                return [f"color:{c.get(v,'#94a3b8')}; font-weight:bold" for v in s]

            display_cols = ["Date","Signal","Fast Z","Sig Line","Histogram","% Above MA","KSE-100"]
            display_cols = [c for c in display_cols if c in sig_events.columns]
            st.dataframe(
                sig_events[display_cols]
                .style.apply(_col_signal, subset=["Signal"]),
                use_container_width=True, hide_index=True,
            )

    st.divider()

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
            st.dataframe(res, use_container_width=True, hide_index=True)

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
elif cur == PAGES[8]:
    import plotly.graph_objects as go
    import plotly.express as px

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

    # System setups only for this page
    sys_sp = sp[sp["source"] == "System"].copy()

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

    wins   = closed[closed["outcome"] == "Win"]
    losses = closed[closed["outcome"] == "Loss"]

    n_total   = len(sys_sp)
    n_pending = len(pending)
    n_active  = len(active)
    n_closed  = len(closed)
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
            use_container_width=True, hide_index=True,
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
                use_container_width=True, hide_index=True,
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
            st.plotly_chart(fig_d, use_container_width=True)

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
                st.plotly_chart(fig_s, use_container_width=True)

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
                st.plotly_chart(fig_q, use_container_width=True)
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
            st.plotly_chart(fig_m, use_container_width=True)

    # ── Pending setups summary ────────────────────────────────────────────────
    if not pending.empty:
        with st.expander(f"🕐 Pending Setups ({len(pending)}) — waiting for entry trigger"):
            pend_disp = pending[["created_date", "symbol", "direction", "sector",
                                 "entry_price", "stop_loss", "target_1r",
                                 "risk_pct", "quality_score"]].copy()
            pend_disp["created_date"] = pend_disp["created_date"].dt.strftime("%d %b %Y")
            pend_disp.columns = ["Date", "Symbol", "Dir", "Sector",
                                  "Entry", "SL", "T1", "Risk %", "Quality"]
            st.dataframe(pend_disp, use_container_width=True, hide_index=True)

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
                use_container_width=True, hide_index=False,
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
elif cur == PAGES[9]:

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
            sector_df_s2 = data["sector_df"]
            n_sec2  = len(sector_df_s2)
            cutoff2 = max(1, round(n_sec2 * 0.35))
            top_rows2 = (
                sector_df_s2[sector_df_s2["rank"] <= cutoff2]
                .sort_values("rank")[["rank", "sector", "avg_perf_pct", "momentum"]].copy()
            )
            st.markdown(f"**Sector Filter** — top {cutoff2} of {n_sec2} sectors (strongest 35%)")
            sec_disp2 = top_rows2.copy(); sec_disp2.columns = ["#", "Sector", "30d %", "Momentum"]
            st.dataframe(
                sec_disp2.style.apply(style_pct_cols, subset=["30d %"])
                    .apply(style_momentum, subset=["Momentum"]).format({"30d %": "{:+.2f}"}),
                use_container_width=True, hide_index=True,
                height=min(380, 46 + cutoff2 * 35),
            )
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
                    )
                    qual_scores.append(qs)

                disp = result[[
                    "symbol", "sector", "as_of_date", "latest_close",
                    "rs", "perf_30d", "range_5d_pct", "avg_vol_10d",
                    "ma21", "ma50", "dist_21ma_pct",
                    "stop_loss", "risk_pct", "target_2r", "tradeable",
                ]].copy()
                disp["avg_vol_10d"] = (disp["avg_vol_10d"] / 1_000).round(0).astype(int)
                disp["as_of_date"]  = pd.to_datetime(disp["as_of_date"]).dt.strftime("%d %b %Y")
                disp["Score"] = qual_scores; disp["ML %"] = ml_scores
                disp["tradeable"] = disp["tradeable"].map({True: "Valid", False: "Skip"})
                disp.columns = ["Symbol","Sector","As Of","Close","RS %","30d %","5d Rng %",
                                "Vol(K)","21MA","50MA","Dist21MA%","SL","Risk%","T2R","Trade","Score","ML%"]

                def _srs(s):  return ["color:#22c55e;font-weight:bold" if v>0 else "color:#ef4444;font-weight:bold" for v in s]
                def _srng(s): return ["color:#22c55e" if v<=5 else "color:#fbbf24" if v<=8 else "color:#94a3b8" for v in s]
                def _sdist(s):return ["color:#22c55e;font-weight:bold" if 0<v<=5 else "color:#fbbf24" if 0<v<=10 else "color:#94a3b8" for v in s]
                def _strd(s): return ["color:#22c55e;font-weight:700" if v=="Valid" else "color:#ef4444" for v in s]
                def _srsk(s): return ["color:#22c55e" if v<=3 else "color:#fbbf24" if v<=6 else "color:#ef4444" for v in s]
                def _sscr(s): return ["color:#16a34a;font-weight:700" if v>=3 else "color:#b45309;font-weight:700" if v==2 else "color:#94a3b8" for v in s]
                def _sml(s):  return ["color:#16a34a;font-weight:700" if (v is not None and v>=65) else "color:#b45309;font-weight:700" if (v is not None and v>=50) else "color:#dc2626" if v is not None else "color:#94a3b8" for v in s]

                st.caption("**Score 0-4:** 3-4 best · 2 borderline · 0-1 weak")
                st.dataframe(
                    disp.style
                        .apply(_srs,  subset=["RS %","30d %"]).apply(_srng, subset=["5d Rng %"])
                        .apply(_sdist,subset=["Dist21MA%"]).apply(_strd, subset=["Trade"])
                        .apply(_srsk, subset=["Risk%"]).apply(_sscr, subset=["Score"])
                        .apply(_sml,  subset=["ML%"])
                        .format({"Close":"{:.2f}","RS %":"{:+.2f}","30d %":"{:+.2f}",
                                 "5d Rng %":"{:.2f}","21MA":"{:.2f}","50MA":"{:.2f}",
                                 "Dist21MA%":"{:+.2f}","SL":"{:.2f}","Risk%":"{:.2f}","T2R":"{:.2f}"}, na_rep="—"),
                    use_container_width=True, hide_index=False,
                    height=min(640, 60 + n_passed * 36),
                )
                st.caption("SL = 1% below day low · T2R = 2R target · ML% = LightGBM win probability · Picks auto-saved to Trade Log")

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
            sector_df_sh = data["sector_df"]
            n_sec_sh  = len(sector_df_sh)
            cutoff_sh = max(1, round(n_sec_sh * 0.35))
            bot_rows = (
                sector_df_sh[sector_df_sh["rank"] > (n_sec_sh - cutoff_sh)]
                .sort_values("rank", ascending=False)[["rank", "sector", "avg_perf_pct", "momentum"]].copy()
            )
            st.markdown(f"**Sector Filter** — bottom {cutoff_sh} of {n_sec_sh} sectors (weakest 35%)")
            bot_disp = bot_rows.copy(); bot_disp.columns = ["#", "Sector", "30d %", "Momentum"]
            st.dataframe(
                bot_disp.style.apply(style_pct_cols, subset=["30d %"])
                    .apply(style_momentum, subset=["Momentum"]).format({"30d %": "{:+.2f}"}),
                use_container_width=True, hide_index=True,
                height=min(380, 46 + cutoff_sh * 35),
            )
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
                    use_container_width=True, hide_index=False,
                    height=min(640, 60 + n_short * 36),
                )
                st.caption(
                    "**Under-RS%** = how much stock underperforms KSE-100 (higher = weaker) · "
                    "**SL** = 1% above day high · **T2R** = 2R target (downside) · "
                    "**Dist21MA%** = negative = below 21MA · Picks auto-saved to Trade Log as SHORT"
                )

# ── MODEL HEALTH PAGE ─────────────────────────────────────────────────────────
elif cur == PAGES[10]:
    import os as _os
    import subprocess as _sp
    import traceback as _tb

    st.markdown("### 🏥 Model Health Dashboard")
    st.caption("Live accuracy tracking for both ML models. Refresh daily after logging predictions.")

    from part5_model_health import generate_health_report
    try:
        report = generate_health_report()
        st.code(report, language=None)
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
            st.dataframe(recent, use_container_width=True, hide_index=True)
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
        r = _sp.run([_py, _os.path.join(_MODEL_DIR, "part4_monthly_retrain.py"), "--force"],
                    capture_output=True, text=True, timeout=300)
        st.code(r.stdout or r.stderr)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 11 — 🗂️ Portfolio  (Weinstein Stage 2 Portfolio Screener)
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == PAGES[11]:
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
            use_container_width=True,
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
        st.plotly_chart(fig_rs, use_container_width=True)

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
