"""
PSX Trading Desk Agent — Claude-powered autonomous analysis system.

Architecture:
  TradingDeskAgent (orchestrator)
    ├─ RegimeDetectorAgent     — identifies current market regime + analogues
    ├─ OpportunityGeneratorAgent — screens today's market for AI-scored setups
    └─ PerformanceTrackerAgent — tracks what's working, flags degradation

  PatternAnalyzerAgent (class still defined, no longer called as of 2026-08-02):
  its win_rate_pct/confidence were unverified LLM self-estimates with a dead
  verification join (agent_learn.py's update_pattern_stats() matched pattern_name
  across two independently-generated free-text vocabularies — 0 matches, ever).
  See docs/KIRAN_CLEANUP_AUDIT.md §18.

Usage:
  python agent.py                  # run full daily analysis
  python agent.py --type weekly    # run weekly summary
  python agent.py --type monthly   # run monthly deep-dive

Requires ANTHROPIC_API_KEY set in environment or .env file in project root.
"""

import argparse
import json
import logging
import os
import sys
import time

# Force UTF-8 output on Windows (cp1252 console can't handle emojis in LLM output)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import date, datetime, timedelta

# ── Allow running from any cwd ────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Load .env if present (before anything reads os.environ) ──────────────────
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent")


# ── Anthropic SDK ─────────────────────────────────────────────────────────────
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    logger.error(
        "anthropic package not installed. Run: pip install anthropic"
    )

# ── Groq SDK (optional — used for chat to save cost) ─────────────────────────
try:
    from groq import Groq as GroqClient
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False


# ── Project imports ───────────────────────────────────────────────────────────
from config import (
    DB_PATH, BENCHMARK,
    DFC_SYMBOLS,
    AGENT_MIN_VOLUME, AGENT_MAX_SL_PCT,
    AGENT_PREFERRED_SECTORS, AGENT_AVOIDED_SECTORS,
)
from database import init_db, get_conn, get_sector_price_data, get_trade_setups
from processor import (
    compute_stock_performance,
    compute_sector_rankings,
    compute_market_breadth,
)
import agent_db as adb

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"   # fast + cheap for daily runs
MODEL_DEEP = "claude-sonnet-4-6"       # for weekly/monthly deep-dives
MAX_TOKENS = 2048
GROQ_CHAT_MODEL = "llama-3.3-70b-versatile"  # free Groq model for chat
TODAY = date.today().isoformat()

# Path to the user's Excel trading journal (read-only — never written by agent)
EXCEL_JOURNAL_PATH = r"D:\PERSONAL\Personal Sheets\ASSET ALLOCATION\ASSET ALLOCATION.XLSX"
EXCEL_JOURNAL_SHEET = "JOURNAL-2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_claude(prompt: str, system: str = None, model: str = None, max_tokens: int = MAX_TOKENS) -> str:
    """Single-shot Claude call. Returns the text response."""
    if not HAS_ANTHROPIC:
        return "[anthropic not installed — install with: pip install anthropic]"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "[ANTHROPIC_API_KEY not set — add it to your .env file or environment]"

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": prompt}]
    kwargs = dict(
        model=model or MODEL,
        max_tokens=max_tokens,
        messages=messages,
    )
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)
    return response.content[0].text


def _format_trade_history(setups: list[dict], limit: int = 80) -> str:
    """Format trade history as a compact text table for Claude."""
    closed = [s for s in setups if s.get("outcome") in ("Win", "Loss", "Breakeven")]
    closed = sorted(closed, key=lambda x: x.get("created_date", ""), reverse=True)[:limit]
    if not closed:
        return "No closed trades available yet."
    lines = ["Date       | Dir  | Symbol | Entry  | Exit   | PL%   | Outcome | Pattern/Notes"]
    lines.append("-" * 85)
    for t in closed:
        lines.append(
            f"{str(t.get('created_date',''))[:10]} | "
            f"{t.get('direction','?'):4} | "
            f"{t.get('symbol','?'):6} | "
            f"{t.get('entry_price',0):6.1f} | "
            f"{t.get('actual_exit',0) or 0:6.1f} | "
            f"{t.get('actual_pl_pct',0) or 0:+5.1f}% | "
            f"{t.get('outcome','?'):8} | "
            f"{str(t.get('notes',''))[:40]}"
        )
    return "\n".join(lines)


def _format_todays_market(stock_30d: pd.DataFrame, sector_df: pd.DataFrame, breadth: dict, top_n: int = 30) -> str:
    """Format today's market snapshot for Claude."""
    regime = f"{breadth.get('emoji','')} {breadth.get('condition','?')} " \
             f"(Breadth score: {breadth.get('breadth_score',0):.0f}/100, " \
             f"Stocks positive: {breadth.get('stock_pct_pos',0)}%)"

    sector_lines = []
    for _, row in sector_df.iterrows():
        sector_lines.append(
            f"  {row['rank']:2}. {row['sector'][:30]:30} 30d:{row['avg_perf_pct']:+5.1f}%  "
            f"10d:{row.get('avg_10d_pct',0) or 0:+5.1f}%  {row.get('momentum','?')}"
        )

    # Top movers
    top_stocks = stock_30d.nlargest(top_n, "perf_pct")[["symbol", "sector", "perf_pct", "latest_close"]]
    stock_lines = []
    for _, row in top_stocks.iterrows():
        stock_lines.append(
            f"  {row['symbol']:6} | {row['sector'][:25]:25} | "
            f"Close: {row['latest_close']:7.2f} | 30d: {row['perf_pct']:+5.1f}%"
        )

    return (
        f"MARKET REGIME: {regime}\n\n"
        f"SECTOR RANKINGS (30-day performance):\n" + "\n".join(sector_lines) +
        f"\n\nTOP PERFORMING STOCKS:\n" + "\n".join(stock_lines)
    )


def _format_ohlcv_for_symbol(symbol: str, raw_data: list[dict], lookback: int = 30) -> str:
    """Format OHLCV for a single symbol for pattern analysis."""
    rows = [r for r in raw_data if r["symbol"] == symbol]
    rows = sorted(rows, key=lambda x: x["date"])[-lookback:]
    if not rows:
        return f"No data for {symbol}"
    lines = [f"OHLCV for {symbol} (last {len(rows)} sessions):"]
    lines.append("Date       | High   | Low    | Close  | Volume")
    for r in rows:
        lines.append(
            f"{r['date']} | {r.get('high',r['close']):6.2f} | "
            f"{r.get('low',r['close']):6.2f} | {r['close']:6.2f} | "
            f"{int(r.get('volume',0)):>10,}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Breakout Example Analyser
# ---------------------------------------------------------------------------

def analyze_reference_breakout(symbol: str, breakout_date: str, direction: str = "LONG", notes: str = "") -> dict:
    """
    Given a symbol and the date it broke out, retrieve that stock's full price
    history from the DB, compute the pre-breakout characteristics, measure
    post-breakout outcome, have Claude write a prose analysis, and save
    everything to agent_reference_breakouts.

    This is how the agent learns what a 'Zeeshan-style momentum burst' actually
    looks like — calibrated from real examples, not theory.

    Args:
        symbol:        e.g. "LUCK"
        breakout_date: e.g. "2026-04-15"  (the day price broke out)
        notes:         optional free-text context from user

    Returns:
        dict with all computed stats + Claude's analysis_text
    """
    from database import get_conn

    logger.info("Analysing reference breakout: %s on %s", symbol, breakout_date)

    # ── Fetch full OHLCV history (get_prices_df only returns date+close) ──────
    with get_conn() as _c:
        all_rows = [dict(r) for r in _c.execute(
            """SELECT symbol,
                      date,
                      COALESCE(high,   close) AS high,
                      COALESCE(low,    close) AS low,
                      close,
                      COALESCE(volume, 0)     AS volume
               FROM prices
               WHERE symbol = ?
               ORDER BY date DESC""",
            (symbol.upper(),),
        ).fetchall()]

    if not all_rows:
        return {"error": f"No price data found for {symbol}"}

    df = pd.DataFrame(all_rows)
    df["date"]  = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    # high/low from DB (COALESCE'd to close when NULL); volume already filled
    for _col in ("high", "low"):
        df[_col] = pd.to_numeric(df[_col], errors="coerce").fillna(df["close"])
    if "volume" not in df.columns:
        df["volume"] = 0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df = df.sort_values("date").reset_index(drop=True)

    bo_dt = pd.to_datetime(breakout_date)
    if bo_dt not in df["date"].values:
        # Find nearest date in DB
        available = df["date"].tolist()
        nearest = min(available, key=lambda d: abs((d - bo_dt).days))
        logger.warning(
            "Breakout date %s not in DB for %s — using nearest: %s",
            breakout_date, symbol, nearest.date()
        )
        bo_dt = nearest

    bo_idx = df[df["date"] == bo_dt].index[0]

    # Need at least 25 bars before breakout for meaningful analysis
    pre_start = max(0, bo_idx - 60)
    pre_df    = df.iloc[pre_start : bo_idx].copy()   # bars BEFORE the BO candle
    bo_row    = df.iloc[bo_idx]
    post_df   = df.iloc[bo_idx + 1 : bo_idx + 16].copy()  # up to 15 bars after

    thin_history = len(pre_df) < 10
    if len(pre_df) < 3:
        return {"error": f"No meaningful history before {breakout_date} for {symbol} — may be a recent listing"}

    # ── Pre-breakout characteristics ─────────────────────────────────────────
    # MAs on the day before the BO
    pre_df["ma21"]  = pre_df["close"].rolling(21,  min_periods=1).mean()
    pre_df["ma50"]  = pre_df["close"].rolling(50,  min_periods=1).mean()
    pre_df["ma200"] = pre_df["close"].rolling(200, min_periods=1).mean()

    # ATR14 ending on the day before BO
    pre_df["prev_close"] = pre_df["close"].shift(1)
    pre_df["tr"] = pd.concat([
        (pre_df["high"] - pre_df["low"]).abs(),
        (pre_df["high"] - pre_df["prev_close"]).abs(),
        (pre_df["low"]  - pre_df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    pre_df["atr14"] = pre_df["tr"].rolling(14, min_periods=1).mean()

    last_pre = pre_df.iloc[-1]
    close_pre = float(last_pre["close"])
    ma21_pre  = float(last_pre["ma21"])  if not pd.isna(last_pre["ma21"])  else None
    ma50_pre  = float(last_pre["ma50"])  if not pd.isna(last_pre["ma50"])  else None
    ma200_pre = float(last_pre["ma200"]) if not pd.isna(last_pre["ma200"]) else None

    ma21_dist  = (close_pre - ma21_pre)  / ma21_pre  * 100 if ma21_pre  else None
    ma50_dist  = (close_pre - ma50_pre)  / ma50_pre  * 100 if ma50_pre  else None
    ma200_dist = (close_pre - ma200_pre) / ma200_pre * 100 if ma200_pre else None

    # 5-day consolidation range before BO
    last_5 = pre_df.tail(5)
    range_5d = (
        (last_5["high"].max() - last_5["low"].min()) / last_5["low"].min() * 100
        if len(last_5) >= 5 else None
    )

    # Consecutive tight-day streak (range ≤ 1.5 × ATR14)
    atr = float(last_pre["atr14"]) if not pd.isna(last_pre["atr14"]) else 0
    consol_days = 0
    if atr > 0:
        for i in range(len(pre_df) - 1, 0, -1):
            day_rng = pre_df["high"].iloc[i] - pre_df["low"].iloc[i]
            if day_rng <= 1.5 * atr:
                consol_days += 1
            else:
                break

    # Volume ratio: avg volume 5d before BO vs avg 20d before BO
    vol_5d  = pre_df.tail(5)["volume"].mean()
    vol_20d = pre_df.tail(20)["volume"].mean()
    vol_ratio = vol_5d / vol_20d if vol_20d > 0 else None

    # ── Breakout candle characteristics ──────────────────────────────────────
    bo_close = float(bo_row["close"])
    bo_range_pct = (float(bo_row["high"]) - float(bo_row["low"])) / float(bo_row["low"]) * 100 if float(bo_row["low"]) > 0 else 0.0

    # ── Post-breakout outcome ─────────────────────────────────────────────────
    # For LONG: measure max high reached. For SHORT: measure max low (deepest drop).
    post_gain = None
    days_to_peak = None
    if not post_df.empty:
        post_df_reset = post_df.reset_index(drop=True)
        is_short = direction.upper() == "SHORT"
        if is_short:
            peak_pos   = post_df_reset["low"].idxmin()
            peak_price = post_df_reset["low"].min()
            post_gain  = (bo_close - peak_price) / bo_close * 100  # positive = profitable short
        else:
            peak_pos   = post_df_reset["high"].idxmax()
            peak_price = post_df_reset["high"].max()
            post_gain  = (peak_price - bo_close) / bo_close * 100
        days_to_peak = int(peak_pos) + 1

    # ── KSE-100 RS in the 30d before BO ──────────────────────────────────────
    pre_rs = None
    try:
        from agent_benchmark import get_kse100_close
        d30_ago = (bo_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        kse_then = get_kse100_close(d30_ago)
        kse_now  = get_kse100_close((bo_dt - timedelta(days=1)).strftime("%Y-%m-%d"))
        if kse_then and kse_now and kse_then > 0:
            kse_30d_ret = (kse_now - kse_then) / kse_then * 100
            # stock 30d return
            d30_ago_dt = bo_dt - timedelta(days=30)
            pre_30 = pre_df[pre_df["date"] >= pd.Timestamp(d30_ago_dt)]
            if not pre_30.empty:
                stk_30d_ret = (close_pre - float(pre_30.iloc[0]["close"])) / float(pre_30.iloc[0]["close"]) * 100
                pre_rs = stk_30d_ret - kse_30d_ret
    except Exception:
        pass

    # ── Claude writes a qualitative analysis ─────────────────────────────────
    ohlcv_text = _format_ohlcv_for_symbol(symbol, all_rows, lookback=30)
    history_note = (
        f"\nNOTE: Only {len(pre_df)} bars of history available before this date "
        f"(likely a recent listing). Some metrics may be unreliable — flag this in your analysis."
        if thin_history else ""
    )

    direction_upper = direction.upper()
    post_label = "Max gain (short drop)" if direction_upper == "SHORT" else "Max gain in 15 sessions"
    entry_label = "breakdown" if direction_upper == "SHORT" else "breakout"

    analysis_prompt = f"""Analyse this {direction_upper} {entry_label} from PSX price history and describe the setup pattern.

SYMBOL: {symbol}  |  DIRECTION: {direction_upper}
{entry_label.upper()} DATE: {breakout_date}{history_note}

PRE-{entry_label.upper()} METRICS (on the day BEFORE the signal candle):
  Consolidation days (tight): {consol_days}
  5-day range%:               {f'{range_5d:.1f}%' if range_5d else 'N/A'}
  Close vs MA21:              {f'{ma21_dist:+.1f}%' if ma21_dist is not None else 'N/A'}
  Close vs MA50:              {f'{ma50_dist:+.1f}%' if ma50_dist is not None else 'N/A'}
  Close vs MA200:             {f'{ma200_dist:+.1f}%' if ma200_dist is not None else 'N/A'}
  RS vs KSE-100 (30d):        {f'{pre_rs:+.1f}%' if pre_rs is not None else 'N/A'}
  Volume ratio (5d/20d avg):  {f'{vol_ratio:.2f}x' if vol_ratio else 'N/A'}
SIGNAL CANDLE:
  Range: {bo_range_pct:.1f}%  |  Close: {bo_close:.2f}
POST-{entry_label.upper()}:
  {post_label}: {f'{post_gain:+.1f}%' if post_gain is not None else 'N/A'}
  Days to {'trough' if direction_upper == 'SHORT' else 'peak'}: {days_to_peak if days_to_peak else 'N/A'}

RECENT OHLCV (30 sessions around {entry_label}):
{ohlcv_text}

USER'S NOTE: {notes or 'None provided'}

Write 3-4 sentences describing:
1. What the setup looked like before the {entry_label} (consolidation/distribution quality, MA structure)
2. What made this a valid {'short entry' if direction_upper == 'SHORT' else 'buy entry'} (what signal triggered the trade)
3. What was the measured risk/reward at the time
4. What this example teaches about the trader's {'short-selling' if direction_upper == 'SHORT' else 'momentum burst'} pattern

Be specific and quantitative. This analysis will be used to calibrate the agent's future screening."""

    analysis_text = _call_claude(analysis_prompt, max_tokens=600)

    # ── Save to DB ────────────────────────────────────────────────────────────
    record = {
        "symbol":              symbol.upper(),
        "breakout_date":       breakout_date,
        "direction":           direction_upper,
        "pre_consol_days":     consol_days,
        "pre_range_pct":       round(range_5d, 2) if range_5d else None,
        "pre_rs_vs_kse":       round(pre_rs, 2) if pre_rs is not None else None,
        "pre_ma21_dist_pct":   round(ma21_dist, 2) if ma21_dist is not None else None,
        "pre_ma50_dist_pct":   round(ma50_dist, 2) if ma50_dist is not None else None,
        "pre_ma200_dist_pct":  round(ma200_dist, 2) if ma200_dist is not None else None,
        "pre_vol_ratio":       round(vol_ratio, 3) if vol_ratio else None,
        "bo_candle_range_pct": round(bo_range_pct, 2),
        "post_gain_pct":       round(post_gain, 2) if post_gain is not None else None,
        "post_days_to_peak":   days_to_peak,
        "analysis_text":       analysis_text,
        "notes":               notes,
    }

    try:
        adb.save_reference_breakout(record)
        logger.info(
            "Reference breakout saved: %s on %s | "
            "consol=%dd, range=%.1f%%, post-gain=%.1f%%",
            symbol, breakout_date, consol_days,
            range_5d or 0, post_gain or 0
        )
    except Exception as e:
        logger.error("Failed to save reference breakout: %s", e)

    return record


# ---------------------------------------------------------------------------
# Sub-Agent 1: Pattern Analyzer
# ---------------------------------------------------------------------------

class PatternAnalyzerAgent:
    """
    Analyzes your historical trade outcomes to discover what setup characteristics
    lead to wins vs losses. Updates agent_patterns table.
    """

    SYSTEM = """You are a quantitative trading pattern analyst specializing in
Pakistan Stock Exchange (PSX) equity markets. You analyze trading history to
discover which technical patterns and market conditions produce the best outcomes.

Respond ONLY with valid JSON. No markdown, no explanation outside the JSON."""

    def run(self, setups: list[dict], sector_df: pd.DataFrame) -> dict:
        logger.info("PatternAnalyzer: analyzing %d closed trades…",
                    len([s for s in setups if s.get("outcome")]))

        trade_history = _format_trade_history(setups)

        # Build sector performance context
        sector_summary = "\n".join([
            f"  {r['sector'][:35]:35} 30d: {r['avg_perf_pct']:+5.1f}%  {r.get('momentum','')}"
            for _, r in sector_df.iterrows()
        ]) if not sector_df.empty else "No sector data"

        prompt = f"""Analyze this PSX trading history and identify patterns.

TRADE HISTORY:
{trade_history}

CURRENT BENCHMARK:
  Win rate: {BENCHMARK['win_rate_pct']}%
  Profit factor: {BENCHMARK['profit_factor']}
  Risk/Reward: {BENCHMARK['risk_reward']}
  Sample: {BENCHMARK['sample_size']}

SECTOR PERFORMANCE:
{sector_summary}

Tasks:
1. Identify 3-6 specific patterns that characterize winning vs losing trades
2. For each pattern, estimate win rate and conditions
3. Flag any patterns that appear to be degrading (worked before but not recently)
4. Identify the single highest-confidence pattern to focus on

Return JSON with this exact structure:
{{
  "patterns": [
    {{
      "pattern_name": "Short string name",
      "description": "What the pattern looks like on a chart",
      "conditions": {{
        "sector_momentum": "what sector condition",
        "stock_behavior": "what the stock is doing",
        "entry_trigger": "exact entry condition",
        "avoid_when": "conditions to skip"
      }},
      "estimated_win_rate_pct": 55,
      "confidence": "High|Medium|Low",
      "sample_size": 10,
      "is_degrading": false,
      "notes": "any observations"
    }}
  ],
  "top_pattern": "pattern_name of the best one",
  "key_insight": "One-sentence most important finding",
  "what_to_stop_doing": "One-sentence biggest negative pattern"
}}"""

        raw = _call_claude(prompt, system=self.SYSTEM, max_tokens=3000)

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean)
        except Exception as e:
            logger.warning("PatternAnalyzer: JSON parse failed (%s) — trying regex extract", e)
            try:
                import re as _re
                m = _re.search(r'\{.*\}', raw, _re.DOTALL)
                result = json.loads(m.group()) if m else {"patterns": [], "key_insight": raw[:500], "raw": raw}
            except Exception:
                result = {"patterns": [], "key_insight": raw[:500], "raw": raw}

        # Persist patterns to DB
        patterns_saved = 0
        for p in result.get("patterns", []):
            try:
                adb.upsert_agent_pattern({
                    "pattern_name":  p.get("pattern_name", "Unnamed"),
                    "description":   p.get("description", ""),
                    "conditions":    p.get("conditions", {}),
                    "first_seen":    TODAY,
                    "last_updated":  TODAY,
                    "signal_count":  p.get("sample_size", 0),
                    "win_rate_pct":  p.get("estimated_win_rate_pct"),
                    "confidence":    p.get("confidence", "Low"),
                    "is_active":     not p.get("is_degrading", False),
                    "raw_json":      p,
                })
                patterns_saved += 1
            except Exception as ex:
                logger.warning("PatternAnalyzer: failed to save pattern: %s", ex)

        logger.info("PatternAnalyzer: saved %d patterns.", patterns_saved)
        return result


# ---------------------------------------------------------------------------
# Sub-Agent 2: Regime Detector
# ---------------------------------------------------------------------------

class RegimeDetectorAgent:
    """
    Identifies the current market regime, labels it, and finds historical
    analogues from 2020-present to guide position sizing and bias.
    """

    SYSTEM = """You are a market regime analyst specializing in PSX (Karachi Stock Exchange).
You identify market phases using Weinstein stage analysis and breadth data.
Respond ONLY with valid JSON."""

    def run(self, breadth: dict, sector_df: pd.DataFrame, stock_30d: pd.DataFrame) -> dict:
        logger.info("RegimeDetector: analyzing market regime…")

        regime_score = breadth.get("breadth_score", 50)
        condition = breadth.get("condition", "Unknown")
        stock_pct = breadth.get("stock_pct_pos", 50)
        sector_pct = breadth.get("sector_pct_pos", 50)

        # Sector stage distribution
        stage_counts = {}
        if not sector_df.empty and "momentum" in sector_df.columns:
            for m in sector_df["momentum"]:
                stage_counts[m] = stage_counts.get(m, 0) + 1

        sector_dist = "\n".join([f"  {k}: {v} sectors" for k, v in sorted(stage_counts.items())])

        prompt = f"""Analyze the current PSX market regime.

BREADTH DATA:
  Condition: {condition}
  Breadth Score: {regime_score:.0f}/100
  Stocks positive (30d): {stock_pct}%
  Sectors positive (30d): {sector_pct}%

SECTOR STAGE DISTRIBUTION (Weinstein):
{sector_dist}

TOP 5 SECTORS: {', '.join(sector_df.head(5)['sector'].tolist()) if not sector_df.empty else 'N/A'}
BOTTOM 5 SECTORS: {', '.join(sector_df.tail(5)['sector'].tolist()) if not sector_df.empty else 'N/A'}

Based on this data:
1. Identify the market regime. Use ONE of these exact labels:
   TRENDING: Early Bull | Mid Bull | Late Bull | Early Bear | Deep Bear | Recovery
   RANGING:  Tight Range (index flat ±3% over 20d) | Wide Range (±3–8%) | Volatile Range (whipsawing)
2. For RANGING regimes — this is critical. The trader has bled money in ranges before.
   Specify: is the range an accumulation base (volume contracting, RS of leaders improving)?
   Or is it distribution/chop with no clear direction? Or volatile two-way chop?
3. What is the ideal PLAYBOOK for this specific regime?
   - Trending Bull: momentum bursts, full size
   - Ranging Accumulation: range support buys (tight SL at support, target range resistance), 50–75% size
   - Ranging Distribution/Chop: minimal exposure, wait or very selective, 25–50% size
   - Volatile Range: cash or small size only, avoid chasing moves
   - Bear: DFC shorts at resistance, cash dominant
4. Position sizing: Full (100%) / Reduced (75%) / Half (50%) / Minimal (25%) / Cash
5. Top 2 risk factors

Return JSON:
{{
  "regime": "Tight Range",
  "regime_subtype": "Accumulation | Distribution | Chop | N/A",
  "regime_description": "2-sentence description of current conditions",
  "trade_bias": "Long-heavy | Range-plays | Short-heavy | Cash",
  "playbook": "What specific setup TYPE to look for in this regime (e.g. 'Range support buys at 20d low with RS improving stocks')",
  "position_sizing": "Full | Reduced | Half | Minimal | Cash",
  "sizing_rationale": "Why this sizing",
  "risk_factors": ["Risk 1", "Risk 2"],
  "sectors_to_focus": ["Sector A", "Sector B", "Sector C"],
  "sectors_to_avoid": ["Sector X"],
  "historical_analogue": "e.g. PSX mid-2024 sideways grind or 2022 bear range",
  "one_line_summary": "Brief actionable regime summary"
}}"""

        raw = _call_claude(prompt, system=self.SYSTEM, max_tokens=800)

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean)
        except Exception as e:
            logger.warning("RegimeDetector: JSON parse failed (%s)", e)
            result = {
                "regime": condition,
                "regime_subtype": "N/A",
                "trade_bias": "Balanced",
                "playbook": "Standard momentum setups",
                "position_sizing": "75%",
                "one_line_summary": raw[:300],
            }

        return result


# ---------------------------------------------------------------------------
# Sub-Agent 3: Opportunity Generator
# ---------------------------------------------------------------------------

def _compute_stm_candidates(raw_data: list[dict], stock_30d: pd.DataFrame,
                             sector_df: pd.DataFrame, kse_30d: float) -> pd.DataFrame:
    """
    Compute STM-style signals on all stocks in the DB — same logic as the
    dashboard's _compute_stm_signals() but runnable outside Streamlit.

    Adds MA200 (user requires all three MAs), consolidation duration
    (how many consecutive tight days), and RS vs KSE-100.

    Returns DataFrame with one row per qualified stock, sorted by setup quality.
    """
    df = pd.DataFrame(raw_data)
    if df.empty:
        return pd.DataFrame()

    df["date"]   = pd.to_datetime(df["date"])
    df["close"]  = pd.to_numeric(df["close"],  errors="coerce")
    df["high"]   = pd.to_numeric(df["high"],   errors="coerce").fillna(df["close"])
    df["low"]    = pd.to_numeric(df["low"],    errors="coerce").fillna(df["close"])
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df = df.sort_values(["symbol", "date"])

    # Keep only symbols with enough history for 200MA
    counts = df.groupby("symbol").size()
    df = df[df["symbol"].isin(counts[counts >= 200].index)].copy()
    if df.empty:
        return pd.DataFrame()

    # ── Rolling MAs ───────────────────────────────────────────────────────────
    g = df.groupby("symbol")["close"]
    df["ma21"]  = g.transform(lambda s: s.rolling(21,  min_periods=21).mean())
    df["ma50"]  = g.transform(lambda s: s.rolling(50,  min_periods=50).mean())
    df["ma200"] = g.transform(lambda s: s.rolling(200, min_periods=200).mean())

    # ── ATR14 ─────────────────────────────────────────────────────────────────
    df["prev_close"] = df.groupby("symbol")["close"].shift(1)
    df["tr"] = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - df["prev_close"]).abs(),
        (df["low"]  - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = df.groupby("symbol")["tr"].transform(
        lambda s: s.rolling(14, min_periods=14).mean()
    )

    # ── Latest row per symbol ─────────────────────────────────────────────────
    latest_idx = df.groupby("symbol")["date"].idxmax()
    latest = df.loc[latest_idx].reset_index(drop=True).copy()

    # ── 5-day and 10-day range % (consolidation tightness) ───────────────────
    def _range_pct(grp, n):
        tail = grp.tail(n)
        lo = tail["low"].min()
        hi = tail["high"].max()
        return (hi - lo) / lo * 100 if lo > 0 else 99.0

    r5  = df.groupby("symbol").apply(lambda g: _range_pct(g, 5)).reset_index(name="range_5d_pct")
    r10 = df.groupby("symbol").apply(lambda g: _range_pct(g, 10)).reset_index(name="range_10d_pct")

    # ── Avg 10-day volume ─────────────────────────────────────────────────────
    vol10 = (df.groupby("symbol", group_keys=False).tail(10)
               .groupby("symbol")["volume"].mean()
               .reset_index(name="avg_vol_10d"))

    # ── Consolidation streak: consecutive days where daily range < 1.5× ATR ──
    def _consol_streak(grp):
        grp = grp.sort_values("date").tail(20).copy()
        if len(grp) < 2:
            return 0
        atr = grp["atr14"].iloc[-1]
        if not atr or atr == 0:
            return 0
        streak = 0
        for i in range(len(grp) - 1, 0, -1):
            day_range = grp["high"].iloc[i] - grp["low"].iloc[i]
            if day_range <= 1.5 * atr:
                streak += 1
            else:
                break
        return streak

    consol = df.groupby("symbol").apply(_consol_streak).reset_index(name="consol_days")

    # ── Merge everything ──────────────────────────────────────────────────────
    result = (
        latest[["symbol", "sector", "date", "close", "low", "high",
                 "ma21", "ma50", "ma200", "atr14"]]
        .rename(columns={"close": "latest_close", "date": "as_of_date",
                          "low": "day_low", "high": "day_high"})
        .merge(r5,     on="symbol", how="left")
        .merge(r10,    on="symbol", how="left")
        .merge(vol10,  on="symbol", how="left")
        .merge(consol, on="symbol", how="left")
    )

    # ── RS vs KSE-100 (30d) ───────────────────────────────────────────────────
    rs_df = stock_30d[["symbol", "perf_pct"]].rename(columns={"perf_pct": "perf_30d"})
    result = result.merge(rs_df, on="symbol", how="left")
    result["rs"] = (result["perf_30d"] - kse_30d).round(2)

    # ── Sector rank ───────────────────────────────────────────────────────────
    if not sector_df.empty and "sector" in sector_df.columns:
        sec_rank = sector_df[["sector", "rank", "momentum"]].copy()
        result = result.merge(sec_rank, on="sector", how="left")
    else:
        result["rank"] = 99
        result["momentum"] = "—"

    result["atr_pct"] = (result["atr14"] / result["latest_close"] * 100).round(2)

    # ── Range context (20-day) — critical for ranging market plays ────────────
    def _range20(grp):
        tail = grp.tail(20)
        hi = tail["high"].max()
        lo = tail["low"].min()
        return pd.Series({
            "high_20d": hi,
            "low_20d":  lo,
            "range_20d_pct": (hi - lo) / lo * 100 if lo > 0 else 99.0,
        })

    range20 = df.groupby("symbol").apply(_range20).reset_index()
    result = result.merge(range20, on="symbol", how="left")

    # Distance from 20d high/low as % (0% = at top, 100% = at bottom of range)
    result["dist_from_20d_high_pct"] = (
        (result["high_20d"] - result["latest_close"]) / result["high_20d"] * 100
    ).round(2)
    result["dist_from_20d_low_pct"] = (
        (result["latest_close"] - result["low_20d"]) / result["low_20d"] * 100
    ).round(2)

    # at_range_support: close within 4% of 20d low
    result["at_range_support"]    = result["dist_from_20d_low_pct"]  <= 4.0
    # at_range_resistance: close within 4% of 20d high
    result["at_range_resistance"] = result["dist_from_20d_high_pct"] <= 4.0

    # ── Quality score: lower range + higher RS + more consol days = better ───
    result["quality"] = (
        (10 - result["range_5d_pct"].clip(0, 10))   # tight = high score
        + result["rs"].clip(-5, 15)                   # RS vs index
        + result["consol_days"].clip(0, 10) * 0.5     # longer base = bonus
    )

    return result.dropna(subset=["ma21", "ma50", "ma200"])


def _load_active_patterns() -> str:
    """Load what has actually worked in PSX from the agent_patterns table."""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT pattern_name, description, win_rate_pct, confidence, signal_count,
                   conditions
            FROM agent_patterns
            WHERE is_active = 1
            ORDER BY win_rate_pct DESC NULLS LAST
            LIMIT 8
        """).fetchall()
        conn.close()
        if not rows:
            return "No patterns recorded yet (learning will begin as trades close)."
        lines = ["PATTERNS THAT HAVE WORKED IN PSX (from actual closed trades):"]
        for r in rows:
            wr = f"{r['win_rate_pct']:.0f}%" if r['win_rate_pct'] else "unknown win rate"
            lines.append(
                f"  [{r['confidence']} confidence | {wr} | {r['signal_count']} signals] "
                f"{r['pattern_name']}: {r['description']}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Patterns unavailable: {e}"


def _load_reference_breakout_profile() -> str:
    """
    Load user-provided reference breakout case studies for Claude's calibration.

    Each example is formatted as a full case study — stats + structural analysis
    prose + trader notes — so Claude understands WHY the setup was valid, not
    just the numbers it produced.  This directly addresses S/R concept blindness:
    without the prose, Claude sees correlated numbers; with it, Claude sees
    the structural concept behind a clean setup.
    """
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT symbol, breakout_date, direction,
                   pre_consol_days, pre_range_pct, pre_rs_vs_kse,
                   pre_ma21_dist_pct, pre_ma200_dist_pct, post_gain_pct,
                   analysis_text, notes
            FROM agent_reference_breakouts
            ORDER BY direction, created_at DESC
            LIMIT 20
        """).fetchall()
        conn.close()
        if not rows:
            return ""

        longs  = [r for r in rows if (r["direction"] or "LONG") == "LONG"]
        shorts = [r for r in rows if (r["direction"] or "LONG") == "SHORT"]

        def _fmt_case(r, trade_type: str) -> str:
            rng    = f"{r['pre_range_pct']:.1f}%" if r['pre_range_pct']    else "?"
            rs     = f"{r['pre_rs_vs_kse']:+.1f}%" if r['pre_rs_vs_kse'] is not None else "?"
            ma21   = f"{r['pre_ma21_dist_pct']:+.1f}%" if r['pre_ma21_dist_pct'] is not None else "?"
            ma200  = f"{r['pre_ma200_dist_pct']:+.1f}%" if r['pre_ma200_dist_pct'] is not None else "?"
            result = f"{r['post_gain_pct']:+.1f}%" if r['post_gain_pct'] is not None else "?"
            lines  = [
                f"  [{trade_type}: {r['symbol']} on {r['breakout_date']}]",
                f"  Stats : {r['pre_consol_days']}d base | 5d-range {rng} | "
                f"RS {rs} vs KSE | MA21 {ma21} | MA200 {ma200} | outcome {result}",
            ]
            if r["analysis_text"]:
                # Truncate at 400 chars — enough for structural concept, not overwhelming
                prose = r["analysis_text"].strip()[:400]
                if len(r["analysis_text"]) > 400:
                    prose += "…"
                lines.append(f"  Why it worked: {prose}")
            if r["notes"]:
                note = r["notes"].strip()[:200]
                lines.append(f"  Trader's note: {note}")
            return "\n".join(lines)

        sections = []
        if longs:
            header = (
                f"CALIBRATION — VALID LONG BREAKOUT EXAMPLES ({len(longs)} user-labelled trades):\n"
                f"  These are the structural conditions that define a CLEAN setup in this system.\n"
                f"  Use them as your quality standard, not just statistical averages."
            )
            cases = "\n\n".join(_fmt_case(r, "LONG") for r in longs)
            sections.append(header + "\n\n" + cases)

        if shorts:
            header = (
                f"CALIBRATION — VALID SHORT BREAKDOWN EXAMPLES ({len(shorts)} user-labelled trades):\n"
                f"  These show what a genuine distribution breakdown looks like in this system."
            )
            cases = "\n\n".join(_fmt_case(r, "SHORT") for r in shorts)
            sections.append(header + "\n\n" + cases)

        return "\n\n" + "\n\n".join(sections) + "\n"
    except Exception:
        return ""


def _characterise_setup(row: pd.Series, active_symbols: set) -> str:
    """
    Build a rich one-line description of a stock's technical situation
    for Claude to reason over independently.
    """
    c     = row["latest_close"]
    ma21  = row["ma21"]
    ma50  = row["ma50"]
    ma200 = row["ma200"]

    # MA structure label
    if c > ma21 > ma50 > ma200:
        structure = "FULL-UPTREND"
    elif c > ma21 and c > ma50 and c < ma200:
        structure = "BELOW-200MA"
    elif c > ma21 and c < ma50:
        structure = "BELOW-50MA"
    elif ma200 and abs(c - ma200) / ma200 < 0.03:
        structure = "AT-200MA-SUPPORT"
    elif c < ma21 < ma50 < ma200:
        structure = "FULL-DOWNTREND"
    else:
        structure = "MIXED"

    consol = int(row.get("consol_days", 0))
    r5     = row.get("range_5d_pct", 99)
    rs     = row.get("rs", 0)
    vol_k  = row.get("avg_vol_10d", 0) / 1000
    atr_p  = row.get("atr_pct", 0)
    ma21d  = (c - ma21) / ma21 * 100 if ma21 else 0
    ma200d = (c - ma200) / ma200 * 100 if ma200 else 0
    sect   = str(row.get("sector", ""))[:20]
    mom    = str(row.get("momentum", "?"))

    # Range position label
    at_sup = bool(row.get("at_range_support", False))
    at_res = bool(row.get("at_range_resistance", False))
    rng20  = row.get("range_20d_pct", 0) or 0
    d_hi   = row.get("dist_from_20d_high_pct", 50) or 50
    if at_sup:
        range_pos = f"AT-SUPPORT(20d-rng:{rng20:.1f}%)"
    elif at_res:
        range_pos = f"AT-RESISTANCE(20d-rng:{rng20:.1f}%)"
    else:
        range_pos = f"MID-RANGE({d_hi:.0f}%fromTop,20d:{rng20:.1f}%)"

    return (
        f"{row['symbol']:6} | {sect:20} | "
        f"Close:{c:8.2f} | MA21:{ma21d:+5.1f}% | MA200:{ma200d:+5.1f}% | "
        f"5d-Rng:{r5:.1f}% | Consol:{consol}d | RS:{rs:+.1f}% | "
        f"Vol:{vol_k:.0f}K | ATR:{atr_p:.1f}% | {structure} | {range_pos} | {mom}"
    )


def _load_pipeline_signals(
    raw_data: list[dict],
    sector_df: "pd.DataFrame",
    avoid_sectors: list,
    active_symbols: set,
    is_long_ok: bool,
) -> tuple[list[str], float, list[str]]:
    """
    Pull today's validated pipeline signals from setup_log, stock_signals,
    recovery_signals.  Returns (section_text_list, universe_stage3_pct,
    all_candidate_symbols).

    This replaces _compute_stm_candidates — Claude now reasons over
    pre-validated signals rather than a raw universe ranked by a quality score.
    Claude's job: rank and select from signals the screener already found;
    it is NOT generating its own candidate list.
    """
    import sqlite3

    # Build symbol → (latest close, sector) from raw_data in one pass
    sym_info: dict[str, dict] = {}
    for row in raw_data:
        sym = row["symbol"]
        d   = str(row.get("date", ""))
        if sym not in sym_info or d > sym_info[sym]["date"]:
            sym_info[sym] = {
                "date":   d,
                "close":  float(row.get("close") or 0),
                "sector": row.get("sector", "?"),
            }
    latest_close = {s: v["close"]  for s, v in sym_info.items()}
    sym_sector   = {s: v["sector"] for s, v in sym_info.items()}

    # Sector momentum map from sector_df
    sec_momentum: dict[str, str] = {}
    if not sector_df.empty and "momentum" in sector_df.columns:
        for _, r in sector_df.iterrows():
            sec_momentum[r["sector"]] = r.get("momentum", "?")

    # Universe Stage 3 % — sector-level proxy used for Phase 2 gate
    if not sector_df.empty and "momentum" in sector_df.columns:
        stage3_count     = sector_df["momentum"].str.contains("Stage 3|Topping", na=False).sum()
        universe_stage3_pct = round(float(stage3_count) / len(sector_df) * 100, 1)
    else:
        universe_stage3_pct = 0.0

    def _sector_ok(sym: str, explicit_sector: str | None) -> tuple[bool, str]:
        """Return (passes_filter, sector_name)."""
        sector = (explicit_sector or sym_sector.get(sym, "?")) or "?"
        if avoid_sectors and sector in avoid_sectors:
            return False, sector
        return True, sector

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sections: list[str] = []
        all_syms: list[str] = []

        # ── 1. BREAKOUT signals ───────────────────────────────────────────────
        row0 = conn.execute(
            "SELECT MAX(setup_date) FROM setup_log WHERE setup_type='BREAKOUT'"
        ).fetchone()
        latest_bo = row0[0] if row0 else None

        if latest_bo:
            bo_rows = conn.execute("""
                SELECT sl.symbol, sl.sector, sl.rs_score_20,
                       sl.pivot_distance_pct, sl.base_tightness,
                       ss.avg_vol_10d, ss.bos_flag, ss.base_duration, ss.overhead_clear
                FROM setup_log sl
                LEFT JOIN stock_signals ss
                       ON ss.symbol = sl.symbol AND ss.date = sl.setup_date
                WHERE sl.setup_date = ? AND sl.setup_type = 'BREAKOUT'
                  AND sl.pivot_distance_pct >= -10
                ORDER BY sl.rs_score_20 DESC
            """, (latest_bo,)).fetchall()
            # pivot_distance_pct >= -10 filters out stocks >10% above pivot (extended runs).
            # bos_flag is a level flag (persists every day the stock stays above pivot),
            # so without this filter the pool includes stocks that broke out months ago.

            filtered = []
            for r in bo_rows:
                sym = r["symbol"]
                if sym in active_symbols:
                    continue
                ok, sector = _sector_ok(sym, r["sector"])
                if not ok:
                    continue
                if (r["avg_vol_10d"] or 0) < AGENT_MIN_VOLUME:
                    continue
                filtered.append((dict(r), sector))

            if filtered:
                lines = [
                    f"BREAKOUT SIGNALS (bos_flag=1, within 10% of pivot — {latest_bo}):",
                    "  Symbol | Sector               | RS     | Vol    | Base | Tight | PivotDist | Overhead | SectorStage",
                ]
                for r, sector in filtered:
                    sym      = r["symbol"]
                    vol_k    = (r["avg_vol_10d"] or 0) / 1000
                    rs       = r["rs_score_20"] or 0
                    base_d   = r["base_duration"] or 0
                    tight    = r["base_tightness"] or 0
                    pivot_d  = r["pivot_distance_pct"] or 0
                    ovhd     = "clear" if r["overhead_clear"] else "blocked"
                    bos      = "bos✓" if r["bos_flag"] else ""
                    mom      = sec_momentum.get(sector, "?")
                    lines.append(
                        f"  {sym:6} | {sector[:20]:20} | RS:{rs:+5.1f} | "
                        f"Vol:{vol_k:5.0f}k | {base_d:2.0f}d | {tight:.1f}% | "
                        f"{pivot_d:+.1f}% | {ovhd:7} | {bos:5} | {mom}"
                    )
                    all_syms.append(sym)
                sections.append("\n".join(lines))

        # ── 2. PRE-BREAKOUT setups ────────────────────────────────────────────
        row0 = conn.execute(
            "SELECT MAX(setup_date) FROM setup_log WHERE setup_type='PRE_BREAKOUT'"
        ).fetchone()
        latest_pre = row0[0] if row0 else None

        if latest_pre:
            pre_rows = conn.execute("""
                SELECT sl.symbol, sl.sector, sl.rs_score_20,
                       sl.pivot_distance_pct, sl.base_tightness,
                       ss.avg_vol_10d, ss.base_duration, ss.overhead_clear
                FROM setup_log sl
                LEFT JOIN stock_signals ss
                       ON ss.symbol = sl.symbol AND ss.date = sl.setup_date
                WHERE sl.setup_date = ? AND sl.setup_type = 'PRE_BREAKOUT'
                ORDER BY sl.rs_score_20 DESC
            """, (latest_pre,)).fetchall()

            filtered = []
            for r in pre_rows:
                sym = r["symbol"]
                if sym in active_symbols:
                    continue
                ok, sector = _sector_ok(sym, r["sector"])
                if not ok:
                    continue
                if (r["avg_vol_10d"] or 0) < AGENT_MIN_VOLUME:
                    continue
                filtered.append((dict(r), sector))

            if filtered:
                lines = [
                    f"PRE-BREAKOUT SETUPS (within 5% of pivot, base tight — {latest_pre}):",
                    "  Symbol | Sector               | RS     | Vol    | Base | Tight | PivotDist | SectorStage",
                ]
                for r, sector in filtered:
                    sym      = r["symbol"]
                    vol_k    = (r["avg_vol_10d"] or 0) / 1000
                    rs       = r["rs_score_20"] or 0
                    base_d   = r["base_duration"] or 0
                    tight    = r["base_tightness"] or 0
                    pivot_d  = r["pivot_distance_pct"] or 0
                    mom      = sec_momentum.get(sector, "?")
                    lines.append(
                        f"  {sym:6} | {sector[:20]:20} | RS:{rs:+5.1f} | "
                        f"Vol:{vol_k:5.0f}k | {base_d:2.0f}d | {tight:.1f}% | "
                        f"{pivot_d:+.1f}% | {mom}"
                    )
                    all_syms.append(sym)
                sections.append("\n".join(lines))

        # ── 3. Weinstein Stage 2 ──────────────────────────────────────────────
        row0 = conn.execute(
            "SELECT MAX(date) FROM stock_signals WHERE stage2_bull = 1"
        ).fetchone()
        latest_wein = row0[0] if row0 else None

        if latest_wein:
            wein_rows = conn.execute("""
                SELECT symbol, rs_score_20, avg_vol_10d,
                       close_above_ema50, ema50_slope_pos,
                       pivot_distance_pct, base_tightness, base_duration
                FROM stock_signals
                WHERE date = ? AND stage2_bull = 1
                ORDER BY rs_score_20 DESC
            """, (latest_wein,)).fetchall()

            filtered = []
            for r in wein_rows:
                sym = r["symbol"]
                if sym in active_symbols:
                    continue
                ok, sector = _sector_ok(sym, None)
                if not ok:
                    continue
                if (r["avg_vol_10d"] or 0) < AGENT_MIN_VOLUME:
                    continue
                filtered.append((dict(r), sector))

            if filtered:
                lines = [
                    f"WEINSTEIN STAGE 2 (stage2_bull=1, EMA150 rising — {latest_wein}):",
                    "  Symbol | Sector               | RS     | Vol    | above_ema50 | slope+ | PivotDist | SectorStage",
                ]
                for r, sector in filtered:
                    sym     = r["symbol"]
                    vol_k   = (r["avg_vol_10d"] or 0) / 1000
                    rs      = r["rs_score_20"] or 0
                    above   = "✓" if r["close_above_ema50"] else "✗"
                    slope   = "✓" if r["ema50_slope_pos"]   else "✗"
                    pivot_d = r["pivot_distance_pct"] or 0
                    mom     = sec_momentum.get(sector, "?")
                    lines.append(
                        f"  {sym:6} | {sector[:20]:20} | RS:{rs:+5.1f} | "
                        f"Vol:{vol_k:5.0f}k | ema50:{above} | slope:{slope} | "
                        f"{pivot_d:+.1f}% | {mom}"
                    )
                    all_syms.append(sym)
                sections.append("\n".join(lines))

        # ── 4. Recovery Bases — TRIGGERED only ───────────────────────────────
        row0 = conn.execute(
            "SELECT MAX(as_of_date) FROM recovery_signals WHERE list_type = 'TRIGGERED'"
        ).fetchone()
        latest_rec = row0[0] if row0 else None

        if latest_rec:
            rec_rows = conn.execute("""
                SELECT symbol, sector, close, drawdown_pct, base_days, base_range_pct, dist_pct
                FROM recovery_signals
                WHERE as_of_date = ? AND list_type = 'TRIGGERED'
                ORDER BY dist_pct ASC
            """, (latest_rec,)).fetchall()

            filtered = []
            for r in rec_rows:
                sym = r["symbol"]
                if sym in active_symbols:
                    continue
                ok, sector = _sector_ok(sym, r["sector"])
                if not ok:
                    continue
                filtered.append((dict(r), sector))

            if filtered:
                lines = [
                    f"RECOVERY BASES — TRIGGERED (post-capitulation breakout — {latest_rec}):",
                    "  Symbol | Sector               | Close    | Drawdown | BaseDays | BaseRng | Dist%",
                ]
                for r, sector in filtered:
                    sym = r["symbol"]
                    lines.append(
                        f"  {sym:6} | {sector[:20]:20} | "
                        f"{r['close']:8.2f} | {r['drawdown_pct']:+5.1f}% | "
                        f"{r['base_days']:3d}d | {r['base_range_pct']:.1f}% | "
                        f"{r['dist_pct']:+.1f}%"
                    )
                    all_syms.append(sym)
                sections.append("\n".join(lines))

    finally:
        conn.close()

    return sections, universe_stage3_pct, all_syms


def _check_perf_circuit_breaker() -> tuple[bool, str]:
    """
    Query agent_opportunities directly to compute recent win rate.
    Returns (blocked, reason).

    Threshold: last 5+ graded outcomes; if win_rate < 30% → block.
    At 1% risk targeting 2R, breakeven WR = 33%. Below 30% = negative
    expectancy territory even accounting for wins.

    If fewer than 5 graded outcomes exist → do NOT block (insufficient data).
    """
    CB_MIN_SAMPLE   = 5      # minimum graded outcomes before circuit breaker can fire
    CB_WIN_RATE_PCT = 30.0   # below this → block

    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT outcome
            FROM agent_opportunities
            WHERE status IN ('Expired', 'Taken', 'Skipped')
              AND outcome IN ('Win', 'Loss', 'Breakeven')
            ORDER BY run_date DESC
            LIMIT 20
        """).fetchall()
        conn.close()

        total = len(rows)
        if total < CB_MIN_SAMPLE:
            return False, ""

        wins = sum(1 for r in rows if r[0] == "Win")
        wr   = wins / total * 100

        if wr < CB_WIN_RATE_PCT:
            return True, (
                f"Circuit breaker: {wins}/{total} wins in last {total} graded suggestions "
                f"= {wr:.0f}% win rate (threshold: {CB_WIN_RATE_PCT:.0f}%). "
                f"Agent edge below threshold — no new suggestions until rate recovers."
            )
        return False, ""
    except Exception as e:
        logger.warning("Circuit breaker check failed (%s) — allowing through", e)
        return False, ""


class OpportunityGeneratorAgent:
    """
    Independent analyst: reviews the full universe of liquid PSX stocks,
    learns from historical pattern data, and makes its OWN picks.

    Architecture:
      1. Apply HARD risk controls in Python (volume, DFC for shorts, active symbols)
      2. Compute full technical picture for every passing stock
      3. Pass ALL candidates to Claude with pattern evidence
      4. Claude picks independently — no MA filter imposed by code
      5. Post-filter: SL > 6% removed (hard risk rule)
    """

    SYSTEM = """You are an independent quantitative analyst for PSX (Karachi Stock Exchange).

Your mandate: identify the best trade setups for TODAY's specific market conditions.

REGIME-SPECIFIC PLAYBOOKS — read the regime and switch strategy accordingly:

TRENDING BULL (Early/Mid/Late Bull, Recovery):
  - Look for momentum bursts: 5–10 day tight consolidation after a runup → buy breakout candle
  - Full uptrend preferred (close > MA21 > MA50 > MA200) but strong RS stocks with partial alignment also valid
  - Support reversals at 200MA valid even if below MA50
  - Targets: 2–3R, hold for trend extension
  - Size: Full to Reduced

RANGING MARKET (Tight Range / Wide Range / Volatile Range):
  THE TRADER BLEEDS MONEY IN RANGES with momentum strategies. Adapt completely:
  - DO NOT suggest momentum breakouts in a ranging market — fake-outs are the norm
  - RANGE SUPPORT PLAYS: Find stocks AT or NEAR their 20-day range low (AT-SUPPORT in data)
    with improving RS, tight recent action, volume drying up. Buy at support, stop just below,
    TARGET = range resistance (20d high), NOT a 2R extension
  - SECTOR LEADERS IN RANGE: Even in a ranging index, some sectors still advance.
    Focus on stocks with positive RS in sectors the regime flags as advancing.
  - If regime = Volatile Range / Chop with no edge → recommend REDUCED SIZE or CASH explicitly
  - Range long target = 20d high (not 2R). Range short target = 20d low (not 2R).
  - Label these setups as "Range Support Play" or "Range Resistance Short" not "Momentum Burst"

BEARISH (Early Bear / Deep Bear):
  - DFC shorts at range resistance or trend resumption
  - Cash as primary position, only high-conviction shorts
  - Size: Minimal to Half

HARD CONSTRAINTS (non-negotiable, in all regimes):
- Shorts ONLY on DFC-listed symbols (PSX rule — marked DFC✓ in data)
- Stop must be ≤ 6% from entry
- Volume ≥ 50,000 avg daily shares (all candidates already qualify)
- Do NOT suggest symbols not in the candidate list

TRADER CONTEXT:
- Momentum bursts = highest conviction in trending markets
- RS vs KSE-100 matters in all regimes
- He buys signal candle, does not wait for volume confirmation
- Max pain point historically: entering momentum trades in ranging markets

Respond ONLY with valid JSON."""

    # ------------------------------------------------------------------
    # Regime gate — evaluated BEFORE any scanning or LLM call
    # ------------------------------------------------------------------
    @staticmethod
    def _regime_gate(regime_result: dict) -> tuple[bool, str]:
        """
        Returns (blocked, reason).
        blocked=True  → hard stop, return no opportunities.
        Triggers when trade_bias OR position_sizing is "Cash",
        OR when the regime is Late Bull with Minimal sizing
        (late-cycle exhaustion = do not initiate new longs).
        """
        trade_bias      = regime_result.get("trade_bias", "Balanced").strip().lower()
        position_sizing = regime_result.get("position_sizing", "Full").strip().lower()
        regime_label    = regime_result.get("regime", "Unknown")
        subtype         = regime_result.get("regime_subtype", "N/A")
        rationale       = regime_result.get("sizing_rationale", "")
        summary         = regime_result.get("one_line_summary", "")

        is_cash_bias    = trade_bias == "cash"
        is_cash_sizing  = position_sizing == "cash"
        is_late_bull    = "late bull" in regime_label.lower()
        is_minimal      = position_sizing == "minimal"

        if is_cash_bias or is_cash_sizing or (is_late_bull and is_minimal):
            reason = (
                f"Regime={regime_label} ({subtype}) | "
                f"Bias={regime_result.get('trade_bias','?')} | "
                f"Sizing={regime_result.get('position_sizing','?')}. "
                f"{rationale or summary}"
            )
            return True, reason

        return False, ""

    _BLOCKED_RESULT = staticmethod(
        lambda reason, regime_result: {
            "opportunities":    [],
            "regime_warning":   f"REGIME GATE ACTIVE — no new positions. {reason}",
            "market_read":      regime_result.get("one_line_summary", ""),
            "regime_blocked":   True,
            "universe_stage3_pct": None,
        }
    )

    @staticmethod
    def _regime_gate_phase2(
        regime_result: dict,
        universe_stage3_pct: float,
        prev_stage3_pct: float | None,
    ) -> tuple[bool, str]:
        """
        Post-scan breadth gate — runs AFTER universe is computed.
        Two triggers:

        1. Absolute threshold:
           - Late Bull + universe_stage3_pct >= 50%  → blocked
           - Any regime  + universe_stage3_pct >= 60% (and not short-biased) → blocked

        2. Rate-of-Change modifier:
           - stage3_pct rose > 15 percentage-points week-over-week → immediate block
             (rapidly accelerating distribution is as deadly as absolute exhaustion)
        """
        LATE_BULL_THRESHOLD = 50.0   # % Stage 3 that triggers block in Late Bull
        GENERAL_THRESHOLD   = 60.0   # % Stage 3 that triggers block in any regime
        ROC_THRESHOLD       = 15.0   # pp week-over-week increase that triggers block

        regime_label    = regime_result.get("regime", "").lower()
        trade_bias      = regime_result.get("trade_bias", "Balanced").lower()
        is_late_bull    = "late bull" in regime_label
        is_short_biased = "short" in trade_bias or "bear" in trade_bias

        # RoC check — fires first (most urgent signal)
        if prev_stage3_pct is not None:
            roc = universe_stage3_pct - prev_stage3_pct
            if roc >= ROC_THRESHOLD:
                reason = (
                    f"Stage 3 RoC +{roc:.1f}pp week-over-week "
                    f"({prev_stage3_pct:.0f}% → {universe_stage3_pct:.0f}%). "
                    f"Rapid distribution acceleration — immediate long block."
                )
                return True, reason

        # Absolute threshold checks
        if is_late_bull and universe_stage3_pct >= LATE_BULL_THRESHOLD:
            reason = (
                f"Late Bull exhaustion: {universe_stage3_pct:.0f}% of universe is "
                f"Stage 3 Topping (threshold: {LATE_BULL_THRESHOLD:.0f}%). "
                f"Regime={regime_result.get('regime','?')}."
            )
            return True, reason

        if not is_short_biased and universe_stage3_pct >= GENERAL_THRESHOLD:
            reason = (
                f"Broad market exhaustion: {universe_stage3_pct:.0f}% of universe is "
                f"Stage 3 Topping (threshold: {GENERAL_THRESHOLD:.0f}%). "
                f"Regime={regime_result.get('regime','?')}."
            )
            return True, reason

        return False, ""

    def run(
        self,
        stock_30d: pd.DataFrame,
        sector_df: pd.DataFrame,
        raw_data: list[dict],
        regime_result: dict,
        patterns_result: dict,
        setups: list[dict],
    ) -> dict:
        logger.info("OpportunityGenerator: independent universe scan…")

        # ── HARD REGIME GATE — must pass before any work is done ─────────────
        gate_blocked, gate_reason = self._regime_gate(regime_result)
        if gate_blocked:
            logger.warning(
                "OpportunityGenerator: REGIME GATE ACTIVE — %s", gate_reason
            )
            return self._BLOCKED_RESULT(gate_reason, regime_result)

        trade_bias  = regime_result.get("trade_bias", "Balanced")
        is_long_ok  = "cash" not in trade_bias.lower()
        is_short_ok = "short" in trade_bias.lower() or "bear" in trade_bias.lower()

        avoid_sectors = list(regime_result.get("sectors_to_avoid", []))
        if AGENT_AVOIDED_SECTORS:
            avoid_sectors = list(set(avoid_sectors) | AGENT_AVOIDED_SECTORS)

        # Symbols already in open positions — skip them
        active_symbols = {
            s["symbol"] for s in setups
            if s.get("status") in ("Pending", "Active")
        }

        # ── Pull validated pipeline signals from screener tables ────────────────
        logger.info("Loading validated pipeline signals from setup_log / stock_signals…")
        pipeline_sections, universe_stage3_pct, pipeline_syms = _load_pipeline_signals(
            raw_data, sector_df, avoid_sectors, active_symbols, is_long_ok
        )
        prev_stage3_pct = adb.get_prev_stage3_pct(days_back=7)

        logger.info(
            "Pipeline signals: %d symbols across %d signal types | "
            "Sector breadth Stage 3: %.0f%%%s",
            len(pipeline_syms), len(pipeline_sections), universe_stage3_pct,
            f" | prev-week: {prev_stage3_pct:.0f}%" if prev_stage3_pct is not None else "",
        )

        # ── PHASE 2 GATE — breadth exhaustion + RoC ──────────────────────────
        gate2_blocked, gate2_reason = self._regime_gate_phase2(
            regime_result, universe_stage3_pct, prev_stage3_pct
        )
        if gate2_blocked:
            logger.warning("OpportunityGenerator: REGIME GATE [Phase 2] — %s", gate2_reason)
            result = self._BLOCKED_RESULT(gate2_reason, regime_result)
            result["universe_stage3_pct"] = universe_stage3_pct
            return result

        # ── Pull Support Reversal setups from DB ──────────────────────────────
        sr_setups = []
        if is_long_ok:
            sr_setups = [
                s for s in setups
                if s.get("source") == "Support Reversal"
                and s.get("status") == "Pending"
                and s.get("symbol") not in active_symbols
                and (s.get("risk_pct") or 99) <= AGENT_MAX_SL_PCT
            ]
        logger.info("Support Reversal candidates from DB: %d", len(sr_setups))

        if sr_setups:
            lines = [
                "SUPPORT REVERSAL SETUPS (pre-calculated by main screener — "
                "price at 200MA/major support with bullish reversal candle):",
                "Symbol | Sector | Entry | SL | Target2R | Risk%",
            ]
            for s in sr_setups[:8]:
                lines.append(
                    f"  {s['symbol']:6} | {s.get('sector','?')[:22]:22} | "
                    f"Entry:{s.get('entry_price',0):.2f} | "
                    f"SL:{s.get('stop_loss',0):.2f} | "
                    f"T2:{s.get('target_2r',0):.2f} | "
                    f"Risk:{s.get('risk_pct',0):.1f}%"
                )
            pipeline_sections.append("\n".join(lines))

        if not pipeline_sections:
            logger.info("OpportunityGenerator: no validated signals available today.")
            return {"opportunities": [], "regime_warning": "", "market_read": "",
                    "universe_stage3_pct": universe_stage3_pct}

        candidates_text = "\n\n".join(pipeline_sections)

        # ── Detect ranging regime for prompt context ──────────────────────────
        regime_label = regime_result.get("regime", "").lower()
        is_ranging = any(r in regime_label for r in ("range", "ranging", "tight range", "wide range", "volatile"))
        playbook   = regime_result.get("playbook", "Standard momentum setups")
        subtype    = regime_result.get("regime_subtype", "N/A")

        # ── Load reference calibration ─────────────────────────────────────
        # _load_active_patterns() / patterns_result removed 2026-08-02 — the pattern
        # analysis they fed from was unverified (win_count/loss_count always 0, see
        # docs/KIRAN_CLEANUP_AUDIT.md §18). Kept in code, no longer called.
        reference_profile = _load_reference_breakout_profile()

        # ── Claude's task: rank and select from pre-validated signals ─────────
        prompt = f"""Today is {TODAY}. Select the best trade setups from today's validated pipeline signals.

IMPORTANT: The signals below have already been identified by the system's validated screeners
(setup_log, stock_signals, recovery_signals). Your job is NOT to find setups — the screeners
already did that. Your job is to RANK and SELECT from these validated signals based on
today's specific regime, and calculate precise entry/exit levels.

MARKET REGIME: {regime_result.get('one_line_summary', 'Unknown')}
REGIME TYPE: {regime_result.get('regime', '?')} — {subtype}
TRADE BIAS: {trade_bias}
REGIME PLAYBOOK: {playbook}
RECOMMENDED SIZING: {regime_result.get('position_sizing', '?')} — {regime_result.get('sizing_rationale', '')}
SECTOR BREADTH: {universe_stage3_pct:.0f}% of sectors are Stage 3: Topping
SECTORS TO FOCUS: {', '.join(regime_result.get('sectors_to_focus', [])[:5])}
SECTORS TO AVOID: {', '.join(regime_result.get('sectors_to_avoid', [])[:3])}

{'RANGING MARKET — MANDATORY PLAYBOOK SWITCH: BREAKOUT and PRE-BREAKOUT signals are lower priority — fake-outs are the norm. The most valid longs are RECOVERY BASES (TRIGGERED) and SUPPORT REVERSAL setups. If the range is volatile/choppy with no clean boundaries, recommend minimal exposure and say so explicitly.' if is_ranging else 'TRENDING MARKET — BREAKOUT signals are highest priority. Stage 2 confirmed uptrends with strong RS and tight bases. Recovery Bases TRIGGERED are also strong in trending markets. PRE-BREAKOUT: watch but do not chase.'}

VALIDATED PIPELINE SIGNALS — pre-screened by signal_engine, grouped by type:
NOTE: These signals come from the system's validated screeners. Claude's selection
      and ranking from this list has NOT been independently backtested.
{candidates_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CALIBRATION STANDARD — WHAT A VALID SETUP LOOKS LIKE IN THIS SYSTEM:
The following are real trades the trader has labelled as structurally correct.
Before selecting any signal below, ask: does this stock's situation share the
STRUCTURAL qualities described in these examples — not just similar numbers?
{reference_profile}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YOUR TASK:
1. Re-read the regime. Apply the correct signal-type priority:
   - TRENDING : BREAKOUT > Recovery TRIGGERED > PRE_BREAKOUT > SR. Targets = 2–3R.
   - RANGING  : Recovery TRIGGERED + SR = valid longs. BREAKOUT = avoid.
                Volatile/Chop regime = state 0 opportunities and explain why.
2. For each signal type present, assess whether the regime supports it.
   Reject signal types that are regime-mismatched — explain why in skipped_reasons.
3. Compare each candidate to the calibration examples above. Reject candidates
   that match the statistics but not the structure.
4. Pick 3–5 best opportunities. If genuine opportunities don't exist, return 0.
   Do NOT fill the list to reach a target count.
5. For each pick, calculate precise levels:
   TRENDING LONG : Entry = close or just above 5d high | SL = recent low × 0.99 (<=6%) | T1 = 1.5R | T2 = 2.5R
   RANGE LONG    : Entry = close (near support)        | SL = 20d low × 0.99 (<=6%)   | Target = 20d high
   RANGE SHORT   : Entry = close (near resistance)     | SL = 20d high × 1.01 (<=6%)  | Target = 20d low
   TRENDING SHORT: Entry = close                       | SL = recent high × 1.01 (<=6%) | T1 = 1.5R | T2 = 2.5R
6. In reasoning, explicitly state: signal type, regime match, RS vs KSE, calibration match.
7. Confidence 50–90. Be conservative — lower in ranging markets, lower for partial matches.

Return JSON:
{{
  "opportunities": [
    {{
      "symbol": "LUCK",
      "direction": "LONG",
      "pattern_name": "Range Support Play — AT 20d Low",
      "confidence_pct": 72,
      "entry_price": 1234.50,
      "stop_loss": 1200.00,
      "target_1r": 1286.75,
      "target_2r": 1322.25,
      "risk_pct": 2.8,
      "sector": "CEMENT",
      "sector_momentum": "Stage 2: Advancing",
      "reasoning": "Ranging market — stock AT-SUPPORT at 20d low, RS +4% vs KSE (stable). Volume contracting. Target = 20d high at 1340, not a 2R extension. Matches calibration example structurally: tight consolidation at tested support, not at exhaustion high.",
      "agent_logic": "Selected because AT-SUPPORT + positive RS in ranging regime = only valid long type today. Calibration match: pre-breakout base quality similar to reference examples."
    }}
  ],
  "skipped_reasons": "Why candidates were skipped — be specific",
  "market_read": "1-sentence honest read of today's market",
  "regime_warning": "If ranging/volatile, state what traders should NOT do today"
}}"""

        raw_resp = _call_claude(prompt, system=self.SYSTEM, max_tokens=4096)

        try:
            clean = raw_resp.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean)
        except Exception as e:
            logger.warning("OpportunityGenerator: JSON parse failed (%s)", e)
            return {"opportunities": [], "regime_warning": "", "market_read": ""}

        opportunities = result.get("opportunities", [])

        # Final hard check: SL must be within limit
        opportunities = [
            o for o in opportunities
            if (o.get("risk_pct") or 0) <= AGENT_MAX_SL_PCT
        ]

        # Save to DB
        saved_count = 0
        saved_opportunities = []
        for opp in opportunities:
            symbol    = opp.get("symbol", "")
            direction = opp.get("direction", "LONG")
            if not symbol:
                continue
            if adb.opportunity_already_saved(symbol, direction, TODAY):
                logger.info("OpportunityGenerator: %s %s already saved today, skipping", direction, symbol)
                continue
            # Merge agent_logic into reasoning so it shows up in dashboard
            if opp.get("agent_logic"):
                opp["reasoning"] = (opp.get("reasoning", "") + "\n\n**Why this was picked:** " + opp["agent_logic"]).strip()
            opp["run_date"]            = TODAY
            opp["regime_at_creation"]  = regime_result.get("regime", "Unknown")
            opp["universe_stage3_pct"] = universe_stage3_pct
            try:
                opp_id = adb.save_agent_opportunity(opp)
                opp["id"] = opp_id
                saved_opportunities.append(opp)
                saved_count += 1
            except Exception as ex:
                logger.warning("OpportunityGenerator: failed to save %s: %s", symbol, ex)

        logger.info(
            "OpportunityGenerator: %d candidates → %d saved. Skipped: %s",
            len(opportunities), saved_count, result.get("skipped_reasons", "—")
        )
        # Return opportunities + top-level meta fields
        return {
            "opportunities":      saved_opportunities,
            "regime_warning":     result.get("regime_warning", ""),
            "market_read":        result.get("market_read", ""),
            "universe_stage3_pct": universe_stage3_pct,
            "input_signals":      pipeline_sections,  # audit trail: what was shown to Claude
        }


# ---------------------------------------------------------------------------
# Sub-Agent 4: Performance Tracker
# ---------------------------------------------------------------------------

class PerformanceTrackerAgent:
    """
    Reviews closed agent opportunities and system setups to generate
    performance insights and flag what's working vs degrading.
    """

    SYSTEM = """You are a trading performance analyst. You review trading results
objectively and identify what's working, what's not, and what to change.
Be honest and data-driven. Respond ONLY with valid JSON."""

    def run(self, setups: list[dict], agent_opps: list[dict]) -> dict:
        logger.info("PerformanceTracker: reviewing performance…")

        # Closed system setups
        closed_system = [s for s in setups if s.get("outcome") and s.get("source") == "System"]
        closed_agent = [o for o in agent_opps if o.get("outcome")]

        # System performance
        if closed_system:
            sys_wins = sum(1 for s in closed_system if s["outcome"] == "Win")
            sys_total = len(closed_system)
            sys_wr = round(sys_wins / sys_total * 100, 1)
            sys_avg_pl = sum(s.get("actual_pl_pct", 0) or 0 for s in closed_system) / sys_total
        else:
            sys_wr, sys_avg_pl, sys_total = None, None, 0

        # Recent 20 vs all-time (trend check)
        recent = sorted(closed_system, key=lambda x: x.get("created_date",""), reverse=True)[:20]
        if recent:
            rec_wins = sum(1 for s in recent if s["outcome"] == "Win")
            rec_wr = round(rec_wins / len(recent) * 100, 1)
        else:
            rec_wr = None

        # Agent performance
        agent_wins = sum(1 for o in closed_agent if o.get("outcome") == "Win")
        agent_total = len(closed_agent)

        # KSE-100 benchmark context
        bm_summary_text = ""
        try:
            from agent_benchmark import get_inception_summary, get_rolling_comparison
            bm = get_inception_summary()
            r30 = get_rolling_comparison(30)
            if bm:
                bm_summary_text = (
                    f"\nKSE-100 BENCHMARK (agent suggestions vs index):\n"
                    f"  Avg agent return per trade: {bm.get('avg_agent_return','?')}%\n"
                    f"  Avg KSE-100 return (same periods): {bm.get('avg_kse100_return','?')}%\n"
                    f"  Avg alpha per trade: {bm.get('avg_alpha','?')}%\n"
                    f"  30-day verdict: {r30.get('verdict','?')}\n"
                    f"  30-day alpha: {r30.get('avg_alpha','?')}%"
                )
        except Exception:
            pass

        if agent_total == 0 and sys_total == 0:
            return {"summary": "Not enough closed trades to evaluate performance yet.", "observations": []}

        prompt = f"""Review PSX trading performance and identify what to improve.

SYSTEM SETUPS (all-time):
  Total closed: {sys_total}
  Win rate: {sys_wr}%
  Avg P&L: {sys_avg_pl:.2f}% per trade
  Benchmark win rate: {BENCHMARK['win_rate_pct']}%
  Benchmark profit factor: {BENCHMARK['profit_factor']}

RECENT PERFORMANCE (last 20 trades):
  Win rate: {rec_wr}%
  vs All-time: {sys_wr}%
  Trend: {'IMPROVING' if rec_wr and sys_wr and rec_wr > sys_wr else 'DECLINING' if rec_wr and sys_wr and rec_wr < sys_wr else 'STABLE'}

AGENT OPPORTUNITY PERFORMANCE:
  Total closed: {agent_total}
  Wins: {agent_wins}
  Win rate: {round(agent_wins/agent_total*100,1) if agent_total > 0 else 'N/A'}%
{bm_summary_text}

RECENT CLOSED TRADES:
{_format_trade_history(closed_system, limit=30)}

Analyze:
1. Is the system's edge holding up or degrading?
2. What types of setups are winning most consistently?
3. What's the single biggest improvement opportunity?
4. Should position sizing be adjusted?

Return JSON:
{{
  "edge_status": "Stable|Improving|Degrading|Insufficient data",
  "observations": [
    "Observation 1 with specific data",
    "Observation 2",
    "Observation 3"
  ],
  "top_improvement": "Single most important thing to change",
  "sizing_recommendation": "Maintain|Reduce|Increase",
  "sizing_reason": "Why",
  "green_flags": ["What's working well"],
  "red_flags": ["What's concerning"],
  "summary": "2-3 sentence overall performance summary"
}}"""

        raw = _call_claude(prompt, system=self.SYSTEM, max_tokens=1000)

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            result = json.loads(clean)
        except Exception as e:
            logger.warning("PerformanceTracker: JSON parse failed (%s)", e)
            result = {"summary": raw[:500], "observations": [], "edge_status": "Unknown"}

        return result


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

class TradingDeskAgent:
    """
    Orchestrates the 4 sub-agents, synthesizes results, writes the daily
    report to the database, and returns a summary dict.
    """

    SYSTEM_SYNTH = """You are Kiran, a senior PSX trading desk manager.
You synthesize inputs from your analysis team into a clear, actionable daily briefing.
Write in a direct, professional tone. Use Markdown formatting."""

    def __init__(self, run_type: str = "daily"):
        self.run_type = run_type
        self.model = MODEL_DEEP if run_type in ("weekly", "monthly") else MODEL

    def run(self) -> dict:
        start_time = time.time()
        logger.info("TradingDeskAgent: starting %s run for %s", self.run_type, TODAY)

        # ── 1. Initialise DB ──────────────────────────────────────────────
        init_db()
        adb.init_agent_tables()

        # ── 2. Load data ──────────────────────────────────────────────────
        logger.info("Loading market data…")
        raw_data = get_sector_price_data()
        if not raw_data:
            logger.error("No price data in database. Run: python main.py --update")
            return {}

        import pandas as pd
        df = pd.DataFrame(raw_data)
        df["date"] = pd.to_datetime(df["date"])

        stock_30d = compute_stock_performance(df, window=30)
        stock_10d = compute_stock_performance(df, window=10)

        from config import EXCLUDED_SECTORS
        stock_30d = stock_30d[~stock_30d["sector"].isin(EXCLUDED_SECTORS)]
        stock_10d = stock_10d[~stock_10d["sector"].isin(EXCLUDED_SECTORS)]

        sector_df = compute_sector_rankings(stock_30d, stock_10d)
        breadth = compute_market_breadth(stock_30d, sector_df)

        # Trade history
        setups = get_trade_setups()
        agent_opps = adb.get_agent_opportunities(limit=200)

        # ── Regime decay: close stale Pending opps in hostile regimes ─────────
        # Runs before sub-agents so the dashboard is never stale after each run.
        # We need regime first — use the last saved regime as a best-effort proxy.
        _prev_regime = adb.get_latest_regime_for_veto()
        if _prev_regime:
            _decayed = adb.apply_regime_decay(_prev_regime, trading_days_threshold=5)
            if _decayed:
                logger.info("Regime decay: auto-closed %d stale Pending opportunities.", _decayed)
                agent_opps = adb.get_agent_opportunities(limit=200)  # refresh

        logger.info(
            "Data loaded: %d symbols, %d price rows, %d trade setups, %d agent opps",
            len(stock_30d), len(raw_data), len(setups), len(agent_opps),
        )

        # ── 2b. Evaluate skipped/pending opportunities against price history ──
        # This runs BEFORE the report so PerformanceTracker sees up-to-date outcomes.
        try:
            from database import get_prices_df

            def _price_lookup(symbol: str, from_date: str) -> list[dict]:
                """Fetch closes for symbol after from_date, oldest first."""
                rows = get_prices_df(symbol, limit=60)  # newest-first from DB
                rows_sorted = sorted(rows, key=lambda x: x["date"])
                return [r for r in rows_sorted if r["date"] > from_date]

            evaluated = adb.evaluate_skipped_opportunities(_price_lookup)
            if evaluated:
                logger.info(
                    "Resolved %d skipped/pending opportunities: %d wins, %d losses",
                    len(evaluated),
                    sum(1 for e in evaluated if e["outcome"] == "Win"),
                    sum(1 for e in evaluated if e["outcome"] == "Loss"),
                )
                # Refresh agent_opps after evaluation
                agent_opps = adb.get_agent_opportunities(limit=200)
        except Exception as _eval_err:
            logger.warning("Skipped-trade evaluation failed: %s", _eval_err)

        # ── 2c. Backfill KSE-100 benchmark on all newly-closed opportunities ─
        try:
            from agent_benchmark import init_benchmark_columns, backfill_all_benchmarks
            init_benchmark_columns()
            filled = backfill_all_benchmarks()
            if filled:
                logger.info("Benchmark backfill: updated %d opportunities.", filled)
        except Exception as _bm_err:
            logger.warning("Benchmark backfill failed: %s", _bm_err)

        # ── 3. Run sub-agents ─────────────────────────────────────────────
        errors = []

        # PatternAnalyzerAgent retired 2026-08-02 — its output (win_rate_pct,
        # confidence, sample_size) was 100% LLM self-estimate with no working
        # verification path: agent_learn.py's update_pattern_stats() was meant to
        # check it against real outcomes by matching pattern_name to
        # agent_opportunities.pattern_name, but those names are independently
        # free-text generated by two separate Claude calls — confirmed 0 of 30
        # opportunity pattern names ever matched any of 76 discovered patterns,
        # so win_count/loss_count sat at 0 for every row. See
        # docs/KIRAN_CLEANUP_AUDIT.md §18. Class kept in code, no longer called.
        pattern_result = {"patterns": [], "key_insight": None,
                           "top_pattern": None, "what_to_stop_doing": None}

        try:
            regime_result = RegimeDetectorAgent().run(breadth, sector_df, stock_30d)
        except Exception as e:
            logger.error("RegimeDetector failed: %s", e)
            regime_result = {"regime": "Unknown", "trade_bias": "Balanced", "one_line_summary": str(e)}
            errors.append(f"RegimeDetector: {e}")

        # ── Circuit breaker: check agent win rate before generating new suggestions ─
        _cb_blocked, _cb_reason = _check_perf_circuit_breaker()

        try:
            if _cb_blocked:
                logger.warning("TradingDesk: CIRCUIT BREAKER ACTIVE — %s", _cb_reason)
                _opp_result = {
                    "opportunities": [],
                    "regime_warning": f"CIRCUIT BREAKER ACTIVE — {_cb_reason}",
                    "market_read": regime_result.get("one_line_summary", ""),
                    "regime_blocked": True,
                    "universe_stage3_pct": None,
                }
            else:
                _opp_result = OpportunityGeneratorAgent().run(
                    stock_30d, sector_df, raw_data, regime_result, pattern_result, setups
                )
            opportunities      = _opp_result.get("opportunities", [])
            regime_warning     = _opp_result.get("regime_warning", "")
            market_read        = _opp_result.get("market_read", "")
            universe_stage3_pct = _opp_result.get("universe_stage3_pct")
        except Exception as e:
            logger.error("OpportunityGenerator failed: %s", e)
            opportunities       = []
            regime_warning      = ""
            market_read         = ""
            universe_stage3_pct = None
            errors.append(f"OpportunityGenerator: {e}")

        try:
            perf_result = PerformanceTrackerAgent().run(setups, agent_opps)
        except Exception as e:
            logger.error("PerformanceTracker failed: %s", e)
            perf_result = {"summary": str(e), "observations": []}
            errors.append(f"PerformanceTracker: {e}")

        # ── 4. Synthesize into report ─────────────────────────────────────
        market_snapshot = _format_todays_market(stock_30d, sector_df, breadth)
        opp_text = "\n".join([
            f"  • {o['direction']} {o['symbol']} @ {o.get('entry_price','?')} | "
            f"SL: {o.get('stop_loss','?')} | T2: {o.get('target_2r','?')} | "
            f"Conf: {o.get('confidence_pct','?')}% — {o.get('reasoning','')[:100]}"
            for o in opportunities
        ]) or "  No high-confidence opportunities identified today."

        synth_prompt = f"""Write a {self.run_type} trading desk briefing for PSX.

DATE: {TODAY}

MARKET SNAPSHOT:
{market_snapshot}

REGIME ANALYSIS:
  Regime: {regime_result.get('regime','?')} — {regime_result.get('regime_subtype','N/A')}
  Bias: {regime_result.get('trade_bias','?')}
  Playbook: {regime_result.get('playbook','?')}
  Sizing: {regime_result.get('position_sizing','?')} — {regime_result.get('sizing_rationale','')}
  Risk factors: {', '.join(regime_result.get('risk_factors',[]))}
  Summary: {regime_result.get('one_line_summary','?')}

TODAY'S OPPORTUNITIES:
{opp_text}

PERFORMANCE:
  Edge status: {perf_result.get('edge_status','?')}
  Summary: {perf_result.get('summary','?')}
  Top improvement: {perf_result.get('top_improvement','?')}

Write a professional Markdown briefing with these sections:
1. 📊 Market Regime (2-3 sentences — state clearly if ranging/trending and what that means)
2. 🎯 Today's Playbook (one bold sentence on what setup TYPE fits today — momentum burst vs range play vs cash)
3. 📋 Opportunities (list each with entry/stop/target/why — note if range play vs trend trade)
4. ⚡ Performance Check (edge status + one key improvement)
5. ⚠️ What NOT To Do Today (critical in ranging markets — e.g. 'do not chase breakouts')
6. 💡 Action Plan (3 clear bullets)

Keep it under 650 words. Be direct and actionable."""

        try:
            narrative = _call_claude(
                synth_prompt,
                system=self.SYSTEM_SYNTH,
                model=self.model,
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            narrative = f"Report generation failed: {e}\n\n**Raw data available in agent tables.**"
            errors.append(f"Synthesis: {e}")

        # ── 5. Save report ────────────────────────────────────────────────
        full_output = {
            "run_date":            TODAY,
            "run_type":            self.run_type,
            "regime":              regime_result,
            "patterns":            pattern_result,
            "opportunities":       [o.get("id") for o in opportunities],
            "performance":         perf_result,
            "regime_warning":      regime_warning,
            "market_read":         market_read,
            "universe_stage3_pct": universe_stage3_pct,   # learning loop foundation
            "input_signals":       _opp_result.get("input_signals", []),  # audit trail: what Claude was shown
        }

        try:
            adb.save_agent_report(
                run_date=TODAY,
                report_type=self.run_type,
                narrative=narrative,
                market_regime=regime_result.get("regime"),
                breadth_score=breadth.get("breadth_score"),
                raw_json=json.dumps(full_output),
            )
        except Exception as e:
            logger.error("Failed to save report: %s", e)
            errors.append(f"SaveReport: {e}")

        # ── 6. Save learning log ──────────────────────────────────────────
        duration = time.time() - start_time
        try:
            adb.save_learning_log({
                "run_date": TODAY,
                "run_type": self.run_type,
                "opportunities_generated": len(opportunities),
                "patterns_updated": len(pattern_result.get("patterns", [])),
                "market_regime": regime_result.get("regime"),
                "key_observations": perf_result.get("top_improvement"),
                "model_used": self.model,
                "run_duration_sec": round(duration, 1),
                "error_log": "; ".join(errors) if errors else None,
            })
        except Exception as e:
            logger.warning("Failed to save learning log: %s", e)

        logger.info(
            "TradingDeskAgent: completed in %.1fs — %d opportunities, %d patterns, %d errors",
            duration, len(opportunities), len(pattern_result.get("patterns", [])), len(errors),
        )

        return {
            "narrative": narrative,
            "opportunities": opportunities,
            "regime": regime_result,
            "patterns": pattern_result,
            "performance": perf_result,
            "breadth": breadth,
            "errors": errors,
            "duration_sec": round(duration, 1),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PSX Trading Desk Agent — Claude-powered autonomous analysis"
    )
    parser.add_argument(
        "--type",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="Report type (default: daily)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run analysis but do NOT save to database (for testing)",
    )
    args = parser.parse_args()

    if not HAS_ANTHROPIC:
        print("\n[ERROR] anthropic package not installed.")
        print("   Run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n[ERROR] ANTHROPIC_API_KEY not set.")
        print("   Add it to C:\\Users\\Lenovo\\psx_pipeline\\.env:")
        print("   ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    agent = TradingDeskAgent(run_type=args.type)
    result = agent.run()

    if result:
        print("\n" + "=" * 60)
        print(f"[OK] Agent run complete ({result.get('duration_sec', 0):.1f}s)")
        print(f"   Opportunities: {len(result.get('opportunities', []))}")
        print(f"   Regime: {result.get('regime', {}).get('regime', 'Unknown')}")
        print(f"   Errors: {len(result.get('errors', []))}")
        if result.get("errors"):
            for e in result["errors"]:
                print(f"   [!] {e}")
        print("\n[REPORT PREVIEW]")
        print("-" * 60)
        narrative = result.get("narrative", "")
        print(narrative[:1500] + ("..." if len(narrative) > 1500 else ""))
    else:
        print("[FAIL] Agent run returned no results.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Chat interface — ask the agent anything
# ---------------------------------------------------------------------------

CHAT_SYSTEM = """You are Kiran's personal PSX trading desk analyst and coach.

You have access to real data from his trading system: regime analysis, trade performance,
open positions, pattern discovery, and market context. You answer in a direct, honest,
and coaching-oriented way.

Your personality:
- Direct and honest — if the data says he's in a losing streak, say so clearly
- Supportive but not sycophantic — acknowledge difficulty but focus on what to do
- Data-driven — always reference actual numbers when they're available
- Aware of PSX market dynamics — this is Pakistan Stock Exchange, not NYSE
- Aware of his trading style: momentum burst trader, tight consolidations,
  prefers longs but shorts DFC stocks in bear markets

You can help with:
1. DATA QUESTIONS — "What's my win rate?", "How many trades did I take last month?"
   → Reference the performance data in your context
2. REGIME QUESTIONS — "Why is the market ranging?", "What does this breadth mean?"
   → Explain using the regime and breadth data in context
3. PSYCHOLOGY — "I'm in a losing streak, what should I do?", "Am I overtrading?"
   → Be an honest coach. Reference his actual data, not generic advice.
4. PERFORMANCE — "Is my edge degrading?", "Which setups work best for me?"
   → Analyse the patterns and trade history in context
5. SETUP REVIEW — "Does X setup look good given the current regime?"
   → Cross-reference the regime, breadth, and pattern data

Always reference specific numbers from the data when available.
Keep responses focused and under 400 words unless depth is specifically needed.
Never make up numbers — if data isn't available, say so.

HARD RULE — SYMBOL GUARD:
Only reference or recommend specific PSX stock tickers (e.g. LUCK, OGDC, HBL) if they
appear explicitly in the LIVE DATA CONTEXT provided to you in this conversation.
Never suggest, recall, or mention a symbol from your training data or general knowledge.
If the user asks about a symbol not in the context, fetch it from the context or say it
is not in today's data — do not invent price levels, setups, or commentary for it."""


def _load_excel_journal() -> str:
    """
    Read the JOURNAL-2 sheet from ASSET ALLOCATION.XLSX and return a
    formatted string with rich trade detail (Trigger notes, all columns).
    Returns empty string if the file is unavailable.
    """
    try:
        import pandas as pd

        if not os.path.exists(EXCEL_JOURNAL_PATH):
            return ""

        raw = pd.read_excel(EXCEL_JOURNAL_PATH, sheet_name=EXCEL_JOURNAL_SHEET, header=None)

        # Auto-detect header row (look for "Date1")
        header_row = None
        for i, row in raw.iterrows():
            if any(str(cell).strip() == "Date1" for cell in row):
                header_row = i
                break
        if header_row is None:
            return ""

        df = pd.read_excel(EXCEL_JOURNAL_PATH, sheet_name=EXCEL_JOURNAL_SHEET, header=header_row)

        # Keep only real columns (drop Unnamed and numeric-header garbage)
        named_cols = [c for c in df.columns if isinstance(c, str) and not c.startswith("Unnamed")]
        df = df[named_cols].copy()

        # Keep only rows that were actually taken (Status = C or O)
        if "Status" in df.columns:
            df = df[df["Status"].astype(str).str.strip().str.upper().isin(["C", "O"])]

        if df.empty:
            return ""

        # Build a compact per-trade summary
        lines = [f"\nEXCEL JOURNAL (JOURNAL-2) — {len(df)} trades (C=Closed, O=Open):"]

        for _, row in df.iterrows():
            try:
                symbol   = str(row.get("Name", "?")).strip().upper()
                status   = str(row.get("Status", "?")).strip().upper()
                direction = str(row.get("POS", "Long")).strip().lower()
                direction_label = "SHORT" if direction in ("short", "s") else "LONG"
                qty      = row.get("QTY")
                buy      = row.get("BUY")
                sell     = row.get("SELL")
                gain_pct = row.get("Gain/Loss%")
                gain_pkr = row.get("Gain/Loss")
                days     = row.get("Days")
                rr       = row.get("R:R")
                trigger  = row.get("Trigger")
                date1    = row.get("Date1")
                date2    = row.get("Date2")

                # Format dates
                def _fmt(v):
                    try:
                        return pd.to_datetime(v).strftime("%Y-%m-%d")
                    except Exception:
                        return str(v).strip() if v and str(v).strip() not in ("nan", "NaT") else "?"

                entry_dt = _fmt(date1)
                exit_dt  = _fmt(date2) if status == "C" else "open"

                # Format P&L%
                pl_str = "?"
                if gain_pct is not None:
                    try:
                        v = float(gain_pct)
                        pl_str = f"{v*100:+.1f}%" if abs(v) < 5 else f"{v:+.1f}%"
                    except Exception:
                        pass

                # Format PKR gain
                pkr_str = "?"
                if gain_pkr is not None:
                    try:
                        pkr_str = f"PKR {float(gain_pkr):+,.0f}"
                    except Exception:
                        pass

                # Trigger note (most valuable column not in DB)
                trigger_str = ""
                if trigger and str(trigger).strip() not in ("nan", "", "NaT"):
                    trigger_str = f" | Trigger: {str(trigger).strip()}"

                rr_str = ""
                if rr is not None:
                    try:
                        rr_str = f" | R:R {float(rr):.2f}"
                    except Exception:
                        pass

                status_label = "Closed" if status == "C" else "Open"
                lines.append(
                    f"  [{entry_dt}→{exit_dt}] {direction_label} {symbol} "
                    f"| {status_label} | {pl_str} ({pkr_str}) | {days or '?'}d{rr_str}{trigger_str}"
                )
            except Exception:
                continue

        return "\n".join(lines)

    except Exception as _e:
        return f"\n(Excel journal unavailable: {_e})"


def _build_chat_context() -> str:
    """
    Build a rich context snapshot for the chat agent from live DB data.
    Called fresh on every chat message to ensure current data.
    """
    lines = [f"TODAY: {TODAY}\n"]

    # ── Latest regime ─────────────────────────────────────────────────────────
    try:
        latest = adb.get_latest_agent_report(report_type="daily")
        if latest and latest.get("raw_json"):
            rj = json.loads(latest.get("raw_json", "{}"))
            reg = rj.get("regime", {})
            lines.append(
                f"CURRENT MARKET REGIME:\n"
                f"  Regime: {reg.get('regime','?')} — {reg.get('regime_subtype','')}\n"
                f"  Bias: {reg.get('trade_bias','?')}\n"
                f"  Playbook: {reg.get('playbook','?')}\n"
                f"  Sizing: {reg.get('position_sizing','?')}\n"
                f"  Risk factors: {', '.join(reg.get('risk_factors',[]))}\n"
                f"  Summary: {reg.get('one_line_summary','?')}\n"
                f"  Report date: {latest.get('run_date','?')}"
            )
            perf = rj.get("performance", {})
            if perf:
                lines.append(
                    f"\nSYSTEM PERFORMANCE (from last agent run):\n"
                    f"  Edge status: {perf.get('edge_status','?')}\n"
                    f"  Top improvement: {perf.get('top_improvement','?')}\n"
                    f"  Sizing recommendation: {perf.get('sizing_recommendation','?')}\n"
                    f"  Observations: " + " | ".join(perf.get("observations", []))
                )
            mread = rj.get("market_read", "")
            if mread:
                lines.append(f"\nMARKET READ: {mread}")
    except Exception:
        pass

    # ── Trade performance stats ───────────────────────────────────────────────
    try:
        from database import get_trade_setups
        setups = get_trade_setups()

        def _execution_type(s):
            src = s.get("source", "")
            has_actual = s.get("actual_entry") is not None
            if src == "Actual":
                return "Actual"
            elif src in ("System", "STM", "Support Reversal", "Support Reversal") and has_actual:
                return "Paper & Actual"
            else:
                return "Paper"

        # Real money trades only (Actual + Paper & Actual)
        real_closed = [
            s for s in setups
            if s.get("outcome") in ("Win", "Loss", "Breakeven")
            and _execution_type(s) in ("Actual", "Paper & Actual")
        ]
        paper_closed = [
            s for s in setups
            if s.get("outcome") in ("Win", "Loss", "Breakeven")
            and _execution_type(s) == "Paper"
        ]

        if real_closed:
            real_sorted = sorted(real_closed, key=lambda x: x.get("exit_date") or x.get("created_date",""), reverse=True)
            wins    = sum(1 for s in real_closed if s["outcome"] == "Win")
            losses  = sum(1 for s in real_closed if s["outcome"] == "Loss")
            wr      = round(wins / len(real_closed) * 100, 1)
            avg_pl  = sum(s.get("actual_pl_pct") or 0 for s in real_closed) / len(real_closed)
            recent  = real_sorted[:20]
            rec_wins = sum(1 for s in recent if s["outcome"] == "Win")
            rec_wr   = round(rec_wins / len(recent) * 100, 1) if recent else 0

            lines.append(
                f"\nREAL MONEY TRADE PERFORMANCE (Actual + Paper&Actual — excludes paper-only):\n"
                f"  Total real closed trades: {len(real_closed)}\n"
                f"  Win rate (all-time): {wr}%  |  Recent 20: {rec_wr}%\n"
                f"  Wins: {wins}  |  Losses: {losses}\n"
                f"  Avg P&L per trade: {avg_pl:+.2f}%\n"
                f"  Trend: {'⚠️ DECLINING' if rec_wr < wr - 5 else '✅ IMPROVING' if rec_wr > wr + 5 else '➡️ STABLE'}\n"
                f"  (Paper-only trades excluded from above: {len(paper_closed)})"
            )

            # Last 10 real trades with dates
            lines.append(f"\n  Last {min(10, len(real_sorted))} real trades (newest first):")
            for s in real_sorted[:10]:
                trade_date = s.get("exit_date") or s.get("created_date","?")
                pl         = s.get("actual_pl_pct") or 0
                exec_t     = _execution_type(s)
                lines.append(
                    f"    [{trade_date}] {s.get('direction','?')} {s.get('symbol','?')} "
                    f"→ {s.get('outcome','?')} ({pl:+.1f}%) [{exec_t}]"
                )

            # Last profitable real trade
            last_win = next((s for s in real_sorted if s.get("outcome") == "Win"), None)
            if last_win:
                w_date = last_win.get("exit_date") or last_win.get("created_date","?")
                w_pl   = last_win.get("actual_pl_pct") or 0
                lines.append(
                    f"\n  LAST PROFITABLE REAL TRADE: {last_win.get('symbol','?')} "
                    f"on {w_date} → +{w_pl:.1f}%  [{_execution_type(last_win)}]"
                )
        else:
            lines.append("\nREAL MONEY TRADES: No real-money closed trades found in DB yet.")
            if paper_closed:
                lines.append(f"  (Paper-only closed trades: {len(paper_closed)} — these are screener accountability records, not real money)")

        # Open positions (real only)
        open_pos = [
            s for s in setups
            if s.get("status") in ("Active", "Pending")
            and _execution_type(s) in ("Actual", "Paper & Actual")
        ]
        if open_pos:
            lines.append(f"\nOPEN REAL POSITIONS ({len(open_pos)}):")
            for p in open_pos[:5]:
                lines.append(
                    f"  {p.get('direction','?')} {p.get('symbol','?')} "
                    f"@ {p.get('actual_entry') or p.get('entry_price','?')} "
                    f"| SL: {p.get('stop_loss','?')} | [{_execution_type(p)}]"
                )
    except Exception as _e:
        lines.append(f"\nTrade data unavailable: {_e}")

    # ── Agent opportunities (recent 30 days, not just today) ─────────────────
    try:
        recent_opps = adb.get_agent_opportunities(limit=50)
        if recent_opps:
            lines.append(f"\nRECENT AGENT SUGGESTIONS (last 30 days, {len(recent_opps)} total):")
            for o in recent_opps:
                outcome_str = o.get("outcome") or "open"
                lines.append(
                    f"  [{o.get('run_date','?')}] {o.get('direction','?')} {o.get('symbol','?')} "
                    f"| {o.get('pattern_name','?')} | Conf: {o.get('confidence_pct','?')}% "
                    f"| Status: {o.get('status','Pending')} | Outcome: {outcome_str}"
                )
    except Exception:
        pass

    # ── Agent performance vs KSE-100 ─────────────────────────────────────────
    try:
        from agent_benchmark import get_inception_summary, get_rolling_comparison
        bm = get_inception_summary()
        r30 = get_rolling_comparison(30)
        if bm and bm.get("n", 0) > 0:
            lines.append(
                f"\nAGENT vs KSE-100:\n"
                f"  Trades measured: {bm.get('n','?')}\n"
                f"  Avg agent return: {bm.get('avg_agent_return','?')}%\n"
                f"  Avg KSE-100 return (same periods): {bm.get('avg_kse100_return','?')}%\n"
                f"  Avg alpha per trade: {bm.get('avg_alpha','?')}%\n"
                f"  30d verdict: {r30.get('verdict','?')}"
            )
    except Exception:
        pass

    # Active-patterns block removed 2026-08-02 — adb.get_agent_patterns() output was
    # unverified LLM self-estimate (win_count/loss_count always 0, dead verification
    # join). Was being injected into the chat context as if factual. See
    # docs/KIRAN_CLEANUP_AUDIT.md §18.

    # ── Excel journal (Trigger notes + full history) ──────────────────────────
    excel_section = _load_excel_journal()
    if excel_section:
        lines.append(excel_section)

    return "\n".join(lines)


def _detect_emotions(text: str) -> list[str]:
    """
    Detect emotional/behavioural signals in a user message.
    Returns a list of detected emotion tags.
    """
    text_lower = text.lower()
    signals = {
        "tempted":    ["tempted", "temptation", "feel like taking", "want to take",
                       "thinking of buying", "thinking of taking", "itching to"],
        "fomo":       ["fomo", "missing out", "already moved", "too late", "missed it",
                       "missed the move", "already up", "fear of missing"],
        "revenge":    ["revenge", "make it back", "recover my loss", "lost yesterday",
                       "need to recover", "after that loss"],
        "impatient":  ["boring", "nothing happening", "sitting in cash", "doing nothing",
                       "just watching", "no setups", "quiet market"],
        "fearful":    ["scared", "afraid", "worried", "nervous", "anxious",
                       "should i cut", "should i exit", "getting nervous"],
        "greedy":     ["double down", "add more", "average down", "add to position",
                       "bigger position", "all in"],
        "uncertain":  ["not sure", "confused", "dont know", "do you think",
                       "what do you think", "is it safe", "risky"],
        "overconfident": ["sure thing", "cant lose", "obvious trade", "easy money",
                          "guaranteed", "no brainer"],
    }
    found = []
    for tag, keywords in signals.items():
        if any(kw in text_lower for kw in keywords):
            found.append(tag)
    return found


def _classify_question(text: str) -> str:
    """Classify the intent of a user message."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["breakout", "bo", "setup", "entry", "chart",
                                      "buy", "long", "short", "sell", "pattern"]):
        return "setup"
    if any(w in text_lower for w in ["win rate", "performance", "p&l", "profit",
                                      "loss", "how am i doing", "my trades"]):
        return "performance"
    if any(w in text_lower for w in ["regime", "market", "kse", "bullish", "bearish",
                                      "ranging", "trend", "breadth"]):
        return "regime"
    if any(w in text_lower for w in ["scared", "tempted", "feel", "emotion", "psychology",
                                      "discipline", "patience", "mistake", "bias"]):
        return "psychology"
    return "other"


def _extract_symbols_from_message(text: str) -> list[str]:
    """
    Extract likely PSX ticker symbols from a chat message.
    Looks for all-caps words of 2-6 characters (e.g. PTC, BAFL, LUCK).
    Also checks the conversation for single-word stock mentions.
    """
    import re
    # Match standalone all-caps words (2-6 chars), possibly followed by punctuation
    raw = re.findall(r'\b([A-Z]{2,6})\b', text)
    # Filter out common English stop words that might be all-caps
    IGNORE = {
        "I", "A", "AN", "THE", "AND", "OR", "BUT", "IS", "IT", "IN",
        "ON", "AT", "TO", "DO", "GO", "BE", "BY", "AS", "IF", "UP",
        "NO", "OK", "SO", "MY", "ITS", "BUY", "SL", "TP", "RR", "MA",
        "PE", "EPS", "ROE", "PF", "PL", "DB", "BO", "RS", "ATR",
        "KSE", "PSX", "PKR", "USD", "LONG", "SHORT", "WIN", "LOSS",
        "YES", "NOT", "CAN", "YOU", "ARE", "WAS", "HAS", "HAD",
        "FOR", "WITH", "FROM", "INTO", "THAT", "THIS", "WHAT", "HOW",
    }
    return [s for s in raw if s not in IGNORE]


def _fetch_stock_context(symbols: list[str]) -> str:
    """
    For each symbol, fetch recent OHLCV from the prices table and compute
    key technical indicators. Returns a formatted string for Claude's context.
    """
    if not symbols:
        return ""

    import numpy as np

    results = []

    with get_conn() as conn:
        # Validate which symbols actually exist in DB
        placeholders = ",".join("?" * len(symbols))
        known = conn.execute(
            f"SELECT DISTINCT symbol FROM prices WHERE symbol IN ({placeholders})",
            symbols
        ).fetchall()
        valid = [r["symbol"] for r in known]

    if not valid:
        return ""

    for symbol in valid:
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    """SELECT date,
                              COALESCE(high,  close) AS high,
                              COALESCE(low,   close) AS low,
                              close,
                              COALESCE(volume, 0)   AS volume
                       FROM prices
                       WHERE symbol = ?
                       ORDER BY date DESC
                       LIMIT 120""",
                    (symbol,)
                ).fetchall()

            if not rows or len(rows) < 5:
                continue

            # Reverse so oldest→newest
            rows = list(reversed(rows))
            closes  = [float(r["close"])  for r in rows]
            highs   = [float(r["high"])   for r in rows]
            lows    = [float(r["low"])    for r in rows]
            volumes = [float(r["volume"]) for r in rows]
            dates   = [r["date"]          for r in rows]

            n = len(closes)
            latest = closes[-1]
            latest_date = dates[-1]

            # Moving averages
            def sma(data, period):
                if len(data) < period:
                    return None
                return round(sum(data[-period:]) / period, 2)

            ma21  = sma(closes, 21)
            ma50  = sma(closes, 50)
            ma200 = sma(closes, 200) if n >= 200 else None

            def dist(price, ma):
                if ma and ma > 0:
                    return round((price - ma) / ma * 100, 1)
                return None

            # ATR (14-day)
            trs = []
            for i in range(1, min(15, n)):
                tr = max(highs[-i] - lows[-i],
                         abs(highs[-i] - closes[-(i+1)]),
                         abs(lows[-i]  - closes[-(i+1)]))
                trs.append(tr)
            atr = round(sum(trs) / len(trs), 2) if trs else None
            atr_pct = round(atr / latest * 100, 1) if atr and latest > 0 else None

            # 20-day high/low — breakout reference
            hi20 = max(highs[-20:]) if n >= 20 else max(highs)
            lo20 = min(lows[-20:])  if n >= 20 else min(lows)
            hi52 = max(highs[-252:]) if n >= 252 else max(highs)
            lo52 = min(lows[-252:])  if n >= 252 else min(lows)

            dist_from_hi20 = round((hi20 - latest) / hi20 * 100, 1) if hi20 > 0 else None
            dist_from_hi52 = round((hi52 - latest) / hi52 * 100, 1) if hi52 > 0 else None

            # Volume analysis
            avg_vol20 = sum(volumes[-20:]) / min(20, n)
            avg_vol5  = sum(volumes[-5:])  / min(5, n)
            vol_ratio = round(avg_vol5 / avg_vol20, 2) if avg_vol20 > 0 else None

            # Consolidation: count days where 5d range < 5%
            consol_days = 0
            for i in range(n - 1, max(n - 31, 0), -1):
                window_hi = max(highs[max(0, i-4):i+1])
                window_lo = min(lows[max(0, i-4):i+1])
                if window_lo > 0 and (window_hi - window_lo) / window_lo * 100 < 5:
                    consol_days += 1
                else:
                    break

            # Recent performance
            perf5d  = round((closes[-1] - closes[-6])  / closes[-6]  * 100, 1) if n >= 6  else None
            perf20d = round((closes[-1] - closes[-21]) / closes[-21] * 100, 1) if n >= 21 else None

            # MA structure label
            if ma21 and ma50 and ma200:
                if latest > ma21 > ma50 > ma200:
                    ma_label = "FULL UPTREND (price > MA21 > MA50 > MA200)"
                elif latest > ma50 > ma200 and (ma21 is None or latest > ma21):
                    ma_label = "ABOVE MA50 & MA200"
                elif latest > ma200 and latest < ma50:
                    ma_label = "ABOVE MA200 but below MA50"
                elif latest < ma200:
                    ma_label = "BELOW MA200 (weak structure)"
                else:
                    ma_label = "MIXED"
            elif ma21 and ma50:
                if latest > ma21 > ma50:
                    ma_label = "UPTREND (above MA21 > MA50, no MA200 data)"
                elif latest > ma50:
                    ma_label = "ABOVE MA50"
                else:
                    ma_label = "BELOW MA50"
            else:
                ma_label = "INSUFFICIENT HISTORY"

            # Breakout assessment
            bo_signal = ""
            if dist_from_hi20 is not None:
                if dist_from_hi20 <= 1.0:
                    bo_signal = "⚡ AT OR ABOVE 20-DAY HIGH — potential breakout zone"
                elif dist_from_hi20 <= 3.0:
                    bo_signal = f"🔶 Near 20-day high ({dist_from_hi20:.1f}% below) — approaching resistance"
                else:
                    bo_signal = f"🔵 {dist_from_hi20:.1f}% below 20-day high"

            # ── Past agent suggestions for this symbol ────────────────
            prior_opps_str = ""
            try:
                with get_conn() as _pc:
                    prior = _pc.execute(
                        """SELECT run_date, direction, pattern_name, confidence_pct,
                                  entry_price, stop_loss, target_2r, status, outcome
                           FROM agent_opportunities
                           WHERE symbol = ?
                           ORDER BY run_date DESC
                           LIMIT 5""",
                        (symbol,)
                    ).fetchall()
                if prior:
                    prior_lines = [f"  AGENT'S PRIOR SUGGESTIONS FOR {symbol}:"]
                    for p in prior:
                        outcome_str = p["outcome"] or "open"
                        prior_lines.append(
                            f"    [{p['run_date']}] {p['direction']} | {p['pattern_name']} "
                            f"| Conf: {p['confidence_pct']}% | Entry: {p['entry_price']} "
                            f"| SL: {p['stop_loss']} | T2: {p['target_2r']} "
                            f"| Status: {p['status']} | Outcome: {outcome_str}"
                        )
                    prior_opps_str = "\n".join(prior_lines)
            except Exception:
                pass

            lines = [
                f"\n{'='*50}",
                f"STOCK DATA: {symbol}  (as of {latest_date})",
                f"{'='*50}",
                f"  Latest close  : {latest:.2f}",
                f"  MA structure  : {ma_label}",
                f"  MA21          : {ma21 or '—'}  (dist: {dist(latest, ma21):+.1f}%)" if ma21 else f"  MA21          : —",
                f"  MA50          : {ma50 or '—'}  (dist: {dist(latest, ma50):+.1f}%)" if ma50 else f"  MA50          : —",
                f"  MA200         : {ma200 or '—'}  (dist: {dist(latest, ma200):+.1f}%)" if ma200 else f"  MA200         : — (insufficient history)",
                f"  ATR (14d)     : {atr or '—'}  ({atr_pct or '—'}% of price)",
                f"  20d High      : {hi20:.2f}  |  20d Low: {lo20:.2f}",
                f"  52wk High     : {hi52:.2f}  |  52wk Low: {lo52:.2f}",
                f"  Dist from 52wk high: {dist_from_hi52:+.1f}%" if dist_from_hi52 is not None else "",
                f"  Breakout flag : {bo_signal}",
                f"  Consol streak : {consol_days}d of tight price action before today",
                f"  Volume ratio  : {vol_ratio}x  (5d avg vs 20d avg)" if vol_ratio else "  Volume        : —",
                f"  Perf 5d       : {perf5d:+.1f}%" if perf5d is not None else "",
                f"  Perf 20d      : {perf20d:+.1f}%" if perf20d is not None else "",
                f"\n  Last 10 closes: {', '.join(f'{c:.2f}' for c in closes[-10:])}",
                f"  Last 10 volumes (000s): {', '.join(f'{int(v/1000)}' for v in volumes[-10:])}",
            ]
            if prior_opps_str:
                lines.append(f"\n{prior_opps_str}")
            results.append("\n".join(l for l in lines if l))

        except Exception as e:
            results.append(f"\n{symbol}: data error — {e}")

    return "\n".join(results)


def _load_trader_profile_context() -> str:
    """Load the latest behavioral profile into a string for Claude's context."""
    try:
        profile = adb.get_latest_trader_profile()
        if not profile:
            return ""
        lines = [
            f"\nYOUR TRADER BEHAVIORAL PROFILE (updated {profile.get('week_date','?')}):",
            profile.get("profile_text", ""),
        ]
        try:
            rules = json.loads(profile.get("guardrail_rules") or "[]")
            if rules:
                lines.append("\nACTIVE GUARDRAILS (enforce these in your responses):")
                for r in rules:
                    lines.append(f"  ⚠️  {r}")
        except Exception:
            pass
        try:
            biases = json.loads(profile.get("key_biases") or "[]")
            if biases:
                lines.append(f"\nKNOWN BIASES: {', '.join(biases)}")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception:
        return ""


def chat_with_agent(
    user_message: str,
    conversation_history: list[dict] | None = None,
    session_id: str = "default",
) -> str:
    """
    Answer a natural language question using live trading data as context.
    Logs every exchange and detects behavioral signals for long-term learning.
    """
    # ── Detect signals in the user message ───────────────────────────────────
    emotions     = _detect_emotions(user_message)
    q_type       = _classify_question(user_message)
    recent_text  = user_message
    if conversation_history:
        for msg in conversation_history[-4:]:
            recent_text += " " + msg.get("content", "")
    mentioned_symbols = _extract_symbols_from_message(recent_text.upper())

    # ── Get current regime for logging ────────────────────────────────────────
    current_regime = None
    try:
        latest_report = adb.get_latest_agent_report(report_type="daily")
        if latest_report and latest_report.get("raw_json"):
            rj = json.loads(latest_report["raw_json"])
            current_regime = rj.get("regime", {}).get("regime")
    except Exception:
        pass

    # ── Log user message ──────────────────────────────────────────────────────
    try:
        adb.log_chat_message(
            session_id       = session_id,
            role             = "user",
            message          = user_message,
            symbols_mentioned= mentioned_symbols,
            emotions         = emotions,
            question_type    = q_type,
            market_regime    = current_regime,
        )
    except Exception:
        pass

    # ── Build context ─────────────────────────────────────────────────────────
    context = _build_chat_context()

    # Stock price data for mentioned symbols
    stock_context = ""
    if mentioned_symbols:
        stock_context = _fetch_stock_context(mentioned_symbols)

    # Behavioral profile + guardrails
    profile_context = _load_trader_profile_context()

    full_context = context
    if profile_context:
        full_context += f"\n\n{'='*60}\n{profile_context}"
    if stock_context:
        full_context += f"\n\n{'='*60}\nLIVE PRICE DATA FOR MENTIONED STOCKS:\n{'='*60}{stock_context}"

    # Emotion-aware injection — warn Claude if user seems emotional
    emotion_note = ""
    if emotions:
        emotion_map = {
            "tempted":       "⚠️  User appears TEMPTED — challenge the setup with data before validating",
            "fomo":          "⚠️  User shows FOMO — check if the move has already happened before responding",
            "revenge":       "⚠️  User may be in REVENGE TRADE mode — caution strongly",
            "impatient":     "⚠️  User seems IMPATIENT/BORED — warn about forcing trades in quiet markets",
            "fearful":       "⚠️  User is FEARFUL — be calm, data-driven, avoid amplifying fear",
            "greedy":        "⚠️  User showing GREED signals — challenge position sizing",
            "uncertain":     "User is UNCERTAIN — give clear data-backed view",
            "overconfident": "⚠️  User sounds OVERCONFIDENT — add appropriate caution",
        }
        notes = [emotion_map[e] for e in emotions if e in emotion_map]
        if notes:
            emotion_note = "\n\nBEHAVIORAL ALERT (act on this before responding):\n" + "\n".join(notes)

    system = (
        f"{CHAT_SYSTEM}"
        f"{emotion_note}"
        f"\n\n{'=' * 60}\nLIVE DATA CONTEXT:\n{'=' * 60}\n{full_context}"
    )

    history = list(conversation_history or [])
    history.append({"role": "user", "content": user_message})

    # ── Try Groq first (free, fast) — fall back to Claude if unavailable ─────
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    use_groq  = HAS_GROQ and groq_key and not groq_key.startswith("paste-your")

    reply = None

    if use_groq:
        try:
            groq_client = GroqClient(api_key=groq_key)
            groq_messages = [{"role": "system", "content": system}] + history
            groq_response = groq_client.chat.completions.create(
                model=GROQ_CHAT_MODEL,
                messages=groq_messages,
                max_tokens=1024,
                temperature=0.4,
            )
            reply = groq_response.choices[0].message.content
            logger.debug("Chat via Groq (%s)", GROQ_CHAT_MODEL)
        except Exception as _groq_err:
            logger.warning("Groq chat failed (%s) — falling back to Claude", _groq_err)
            reply = None

    if reply is None:
        # Claude fallback
        if not HAS_ANTHROPIC:
            return "[anthropic package not installed — run: pip install anthropic]"
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "[ANTHROPIC_API_KEY not set in .env file]"
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL_DEEP,
            max_tokens=1024,
            system=system,
            messages=history,
        )
        reply = response.content[0].text
        logger.debug("Chat via Claude (%s)", MODEL_DEEP)

    # ── Log assistant reply ───────────────────────────────────────────────────
    try:
        adb.log_chat_message(
            session_id    = session_id,
            role          = "assistant",
            message       = reply,
            market_regime = current_regime,
        )
    except Exception:
        pass

    return reply


if __name__ == "__main__":
    main()
