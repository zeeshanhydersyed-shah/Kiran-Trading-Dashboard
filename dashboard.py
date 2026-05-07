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

PAGES = ["📊 Market", "📈 History", "💡 Setups", "📋 Trade Log", "🔍 Explorer", "📉 Analytics", "🤖 Backtest", "🧭 Regime"]


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
        kse_txt = (f"KSE-100 <b>{kse_c:,.0f}</b> &nbsp;·&nbsp; "
                   f"50-MA <b>{kse_m:,.0f}</b> &nbsp;·&nbsp; "
                   f"<span style='color:{kse_col};font-weight:700;'>{kse_lbl} 50MA "
                   f"({kse_pct:+.1f}%)</span>")
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
        "**System** = KIRAN's recommendation. "
        "Mark it Active from the Setups page when you take it — one record, no duplicates. "
        "**Actual** = a trade you took that KIRAN never suggested (log it below)."
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

        flt1, flt2 = st.columns([2, 2])
        sf  = flt1.selectbox("Status", ["All","Pending","Active","Hit Target","Hit SL","Cancelled"], key="log_sf")
        src = flt2.selectbox("Source", ["All","System","Actual"], key="log_src")

        if sf  != "All": log_df = log_df[log_df["status"] == sf]
        if src != "All": log_df = log_df[log_df["source"]  == src]

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
                "color:#3b82f6; font-weight:bold" if v == "System"
                else "color:#f59e0b; font-weight:bold"
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

    # ── Log a non-KIRAN trade ─────────────────────────────────────────────────
    st.divider()
    st.markdown("**Log a non-KIRAN trade**")
    st.caption(
        "Use this **only** for trades KIRAN did not suggest. "
        "For KIRAN setups, use the **✏️ I took this trade** button on the Setups page — "
        "that updates the existing system record instead of creating a duplicate."
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

            cl1, cl2, cl3, cl4, cl5 = st.columns([1.5, 1.5, 2, 2, 1])
            cl1.caption("Exit Price")
            cl2.caption("Exit Date")
            cl3.caption("Result")
            cl4.caption("Notes")

            exit_px   = cl1.number_input("Exit Price",  min_value=0.0, step=0.01,
                                          format="%.2f", key="cl_px", label_visibility="collapsed")
            exit_dt   = cl2.date_input("Exit Date", value=datetime.now().date(),
                                       key="cl_dt", label_visibility="collapsed")
            cl_result = cl3.selectbox("Result", ["Hit Target", "Hit SL", "Breakeven", "Cancelled"],
                                      key="cl_result", label_visibility="collapsed")
            cl_notes  = cl4.text_input("Notes", placeholder="e.g. trailed stop", key="cl_notes",
                                       label_visibility="collapsed")

            with cl5:
                st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
                if st.button("✅ Close", key="btn_close", type="primary"):
                    if exit_px <= 0:
                        st.error("Enter a valid exit price.")
                    else:
                        outcome_map = {"Hit Target": "Win", "Hit SL": "Loss",
                                       "Breakeven": "Breakeven", "Cancelled": "Breakeven"}
                        close_trade_setup(
                            setup_id   = int(chosen_trade["id"]),
                            exit_price = float(exit_px),
                            exit_date  = exit_dt.isoformat(),
                            status     = cl_result,
                            outcome    = outcome_map[cl_result],
                            notes      = cl_notes.strip() or None,
                        )
                        # Quick preview of P&L
                        entry = float(chosen_trade["entry_price"])
                        dirn  = chosen_trade["direction"]
                        if entry > 0:
                            pl = (exit_px - entry) / entry * 100 if dirn == "LONG" else (entry - exit_px) / entry * 100
                            st.success(f"#{chosen_trade['id']} closed  ·  P&L {pl:+.2f}%")
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

    # ── Pull closed actual trades ──────────────────────────────────────────────
    all_trades = get_trade_setups()
    adf = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    closed = pd.DataFrame()
    if not adf.empty:
        closed = adf[
            (adf["source"] == "Actual") &
            (adf["outcome"].isin(["Win", "Loss", "Breakeven"]))
        ].copy()
        for col in ["actual_pl_pkr", "actual_pl_pct", "actual_rr", "holding_days", "exit_date"]:
            if col not in closed.columns:
                closed[col] = None

    if closed.empty:
        st.info("No closed actual trades yet. Log trades in the Trade Log first.")
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

    # Fill missing months with 0 for display, but track which are truly empty
    all_months = MONTH_NAMES
    for m in all_months:
        if m not in pivot.columns:
            pivot[m] = float("nan")
    pivot = pivot[all_months]                       # enforce Jan→Dec order
    pivot["Total"] = pivot.sum(axis=1, skipna=True) # year total

    # ── Colour-coded HTML table ───────────────────────────────────────────────
    def cell(v, bold=False):
        if pd.isna(v) or v == 0:
            return '<td style="text-align:right;padding:4px 8px;color:#94a3b8;font-size:0.72rem;">—</td>'
        color  = "#22c55e" if v > 0 else "#ef4444"
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
        cell(pivot[m].sum(skipna=True)) for m in all_months
    )
    grand_total = cell(pivot["Total"].sum(skipna=True), bold=True)
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
    sig_label = regime["signal"]
    zone      = regime["zone"]
    zcolor    = regime["zone_color"]
    fz_val    = regime["fast_z"]
    sl_val    = regime["signal_line"]
    pct_val   = regime["pct_above_ma"]
    idx_abv   = regime["index_above_ma"]
    last_date = regime["last_date"]

    sig_colors = {
        "BUY":   "#22c55e",
        "SELL":  "#ef4444",
        "SHORT": "#3b82f6",
        "HOLD":  "#fbbf24",
    }
    sig_icons = {"BUY": "▲", "SELL": "▼", "SHORT": "↓", "HOLD": "—"}
    sig_col   = sig_colors.get(sig_label, "#94a3b8")
    sig_icon  = sig_icons.get(sig_label, "")

    st.markdown(
        f"""<div style="background:{sig_col}18; border-left:5px solid {sig_col};
            padding:10px 16px; border-radius:8px; margin-bottom:10px;
            display:flex; align-items:center; gap:20px;">
            <span style="font-size:1.6rem; font-weight:900; color:{sig_col}; white-space:nowrap;">
                {sig_icon} {sig_label}
            </span>
            <div>
                <span style="font-size:0.85rem; font-weight:700; color:{zcolor};">{zone}</span>
                <span style="font-size:0.75rem; color:#64748b; margin-left:12px;">
                    Fast Z: <b>{fz_val:.2f}</b> &nbsp;·&nbsp;
                    Signal Line: <b>{sl_val:.2f}</b> &nbsp;·&nbsp;
                    % Above 50MA: <b>{pct_val:.1f}%</b> &nbsp;·&nbsp;
                    KSE-100 vs MA: <b>{"▲ Above" if idx_abv else "▼ Below"}</b> &nbsp;·&nbsp;
                    As of <b>{pd.Timestamp(last_date).strftime('%d %b %Y')}</b>
                </span>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── KPI row ────────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)

    def _kpi_mini(label, val, fmt, color):
        return (
            f'<div style="background:{color}12; border:1px solid {color}33; border-top:3px solid {color};'
            f'border-radius:7px; padding:9px 8px; text-align:center;">'
            f'<div style="font-size:0.6rem; color:#64748b; text-transform:uppercase; letter-spacing:.06em;">'
            f'{label}</div>'
            f'<div style="font-size:1.05rem; font-weight:800; color:{color};">{fmt.format(val) if val is not None else "—"}</div>'
            f'</div>'
        )

    buy_thr  = w_params["buy_threshold"]
    sell_thr = w_params["sell_threshold"]
    fz_color = "#3b82f6" if (fz_val is not None and fz_val < buy_thr) else "#ef4444" if (fz_val is not None and fz_val > sell_thr) else "#22c55e"

    k1.markdown(_kpi_mini("Fast Z-Score",    fz_val,  "{:.2f}", fz_color), unsafe_allow_html=True)
    k2.markdown(_kpi_mini("Signal Line",     sl_val,  "{:.2f}", "#8b5cf6"), unsafe_allow_html=True)
    k3.markdown(_kpi_mini("% Above 50MA",    pct_val, "{:.1f}%", "#06b6d4"), unsafe_allow_html=True)
    k4.markdown(_kpi_mini("Buy Threshold",   buy_thr, "{:.1f}", "#22c55e"), unsafe_allow_html=True)
    k5.markdown(_kpi_mini("Sell Threshold",  sell_thr,"{:.1f}", "#ef4444"), unsafe_allow_html=True)

    st.divider()

    # ── Z-Score chart (main chart) ─────────────────────────────────────────────
    st.markdown("**Z-Score History**")

    tail = st.slider("Show last N days", 60, len(signals), min(504, len(signals)), step=21, key="wbs_tail")
    sig_plot = signals.tail(tail).copy()

    fig_z = go.Figure()

    # Shaded zones
    fig_z.add_hrect(y0=buy_thr, y1=-4,  fillcolor="#3b82f620", line_width=0, annotation_text="Oversold zone", annotation_position="top left")
    fig_z.add_hrect(y0=sell_thr, y1=4,  fillcolor="#ef444420", line_width=0, annotation_text="Overbought zone", annotation_position="bottom left")
    fig_z.add_hline(y=0,        line_dash="dot",  line_color="#94a3b8", line_width=1)
    fig_z.add_hline(y=buy_thr,  line_dash="dash", line_color="#3b82f6", line_width=1.2)
    fig_z.add_hline(y=sell_thr, line_dash="dash", line_color="#ef4444", line_width=1.2)

    # Fast Z line
    fig_z.add_trace(go.Scatter(
        x=sig_plot.index, y=sig_plot["fast_z"].round(3),
        mode="lines", name="Fast Z",
        line={"color": "#3b82f6", "width": 2},
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Fast Z: %{y:.2f}<extra></extra>",
    ))

    # Signal line
    fig_z.add_trace(go.Scatter(
        x=sig_plot.index, y=sig_plot["signal_line"].round(3),
        mode="lines", name="Signal Line",
        line={"color": "#f59e0b", "width": 1.5, "dash": "dot"},
        hovertemplate="<b>%{x|%d %b %Y}</b><br>Signal Line: %{y:.2f}<extra></extra>",
    ))

    # BUY markers
    buys = sig_plot[sig_plot["signal"] == 1]
    if not buys.empty:
        fig_z.add_trace(go.Scatter(
            x=buys.index, y=buys["fast_z"],
            mode="markers", name="BUY",
            marker={"color": "#22c55e", "size": 12, "symbol": "triangle-up"},
            hovertemplate="<b>BUY</b><br>%{x|%d %b %Y}<br>Z: %{y:.2f}<extra></extra>",
        ))

    # SELL markers
    sells = sig_plot[sig_plot["signal"] == -1]
    if not sells.empty:
        fig_z.add_trace(go.Scatter(
            x=sells.index, y=sells["fast_z"],
            mode="markers", name="SELL",
            marker={"color": "#ef4444", "size": 12, "symbol": "triangle-down"},
            hovertemplate="<b>SELL</b><br>%{x|%d %b %Y}<br>Z: %{y:.2f}<extra></extra>",
        ))

    # SHORT markers
    shorts = sig_plot[sig_plot["signal"] == -2]
    if not shorts.empty:
        fig_z.add_trace(go.Scatter(
            x=shorts.index, y=shorts["fast_z"],
            mode="markers", name="SHORT",
            marker={"color": "#3b82f6", "size": 12, "symbol": "triangle-down"},
            hovertemplate="<b>SHORT</b><br>%{x|%d %b %Y}<br>Z: %{y:.2f}<extra></extra>",
        ))

    fig_z.update_layout(
        height=340,
        margin={"l": 4, "r": 4, "t": 8, "b": 8},
        legend={"orientation": "h", "y": 1.05, "x": 0, "font": {"size": 11}},
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis={"title": "Z-Score", "tickfont": {"size": 10}, "range": [-4, 4]},
        xaxis={"tickfont": {"size": 10}},
    )
    st.plotly_chart(fig_z, use_container_width=True)

    # ── Breadth % chart ────────────────────────────────────────────────────────
    st.markdown("**Breadth — % of PSX stocks above 50-day MA**")

    breadth_plot = breadth.tail(tail)
    fig_b = go.Figure()
    fig_b.add_hline(y=50, line_dash="dot", line_color="#94a3b8", line_width=1)
    fig_b.add_trace(go.Scatter(
        x=breadth_plot.index, y=breadth_plot.round(1),
        mode="lines", name="% Above 50MA",
        line={"color": "#06b6d4", "width": 2},
        fill="tozeroy", fillcolor="#06b6d420",
        hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.1f}% above 50MA<extra></extra>",
    ))
    fig_b.update_layout(
        height=220,
        margin={"l": 4, "r": 4, "t": 8, "b": 8},
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis={"title": "% Stocks", "tickfont": {"size": 10}, "range": [0, 100]},
        xaxis={"tickfont": {"size": 10}},
        showlegend=False,
    )
    st.plotly_chart(fig_b, use_container_width=True)

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
            sig_events["Signal"] = sig_events["signal"].map({1:"BUY", -1:"SELL", -2:"SHORT"})
            sig_events["Fast Z"] = sig_events["fast_z"].round(2)
            sig_events["Sig Line"] = sig_events["signal_line"].round(2)
            sig_events["% Above MA"] = sig_events["pct_above_ma"].round(1)
            sig_events["KSE-100"] = sig_events["index_close"].round(0)

            def _col_signal(s):
                c = {"BUY": "#22c55e", "SELL": "#ef4444", "SHORT": "#3b82f6"}
                return [f"color:{c.get(v,'#94a3b8')}; font-weight:bold" for v in s]

            st.dataframe(
                sig_events[["Date","Signal","Fast Z","Sig Line","% Above MA","KSE-100"]]
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
        gc1, gc2, gc3 = st.columns(3)
        with gc1:
            lookback_str  = st.text_input("z_lookback",       "126, 189, 252",  key="opt_lb")
            fast_str      = st.text_input("fast_smoothing",   "3, 5, 8",        key="opt_fs")
        with gc2:
            sig_str       = st.text_input("signal_smoothing", "8, 10, 13",      key="opt_ss")
            buy_str       = st.text_input("buy_threshold",    "-2.0, -1.7, -1.5", key="opt_bt")
        with gc3:
            sell_str      = st.text_input("sell_threshold",   "1.8, 2.0, 2.2", key="opt_st")

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
                "buy_threshold":    _parse(buy_str),
                "sell_threshold":   _parse(sell_str),
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
                        f"fast={best_params['fast_smoothing']} &nbsp; "
                        f"signal={best_params['signal_smoothing']} &nbsp; "
                        f"buy={best_params['buy_threshold']} &nbsp; "
                        f"sell={best_params['sell_threshold']}",
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
That number becomes the **breadth percentage** (e.g., 64% of stocks are above their MA today).

**Why Z-score it?**

A raw percentage of 64% means nothing without context.
The Z-score answers: *"Is 64% historically high or low for this market?"*
If the past year's average was 55% with a standard deviation of 8, then 64% = Z ≈ +1.1 — moderately elevated.

**The two smoothed lines**
- **Fast Z** (blue) — 5-day average of the raw Z-score. Reacts quickly.
- **Signal Line** (orange dashed) — 10-day average of Fast Z. Slower, used for crossover confirmation.

**Zone definitions**
| Zone | Fast Z range | Meaning |
|---|---|---|
| Oversold | < -1.7 | Breadth historically depressed — watch for recovery |
| Bearish | -1.7 to -0.5 | Below-average breadth |
| Neutral | -0.5 to +0.5 | Normal conditions |
| Bullish | +0.5 to +2.0 | Above-average breadth |
| Overbought | > +2.0 | Breadth historically stretched — watch for reversal |

**Signal logic**
| Signal | Trigger conditions |
|---|---|
| **BUY** | Fast Z crosses *up* through -1.7 **AND** Fast Z > Signal Line **AND** KSE-100 > 50MA |
| **SELL** | Fast Z crosses *down* from above +2.0, or rolls under Signal Line while still overbought |
| **SHORT** | Fast Z < -1.7 **AND** KSE-100 < 50MA **AND** Signal Line is negative |
| **HOLD** | None of the above conditions met |

**PSX calibration used**
- Known bottom: Jan 2024
- Known tops: Jan 2025 (stall), Jan 2026

Use the **Parameter Optimizer** to refine thresholds as more PSX history accumulates.
        """)

