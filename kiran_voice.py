"""
kiran_voice.py — Kiran's Voice: persistent trading partner for Zeeshan.

Three trigger types:
  scheduled     — daily after pipeline update
  morning_open  — pre-market brief
  conversational — Zeeshan asks something

Entry points:
  run_kiran(trigger_type, zeeshan_input=None)   → response str
  get_latest_response()                          → dict or None
  get_memory(n=7)                                → list of dicts
"""

import json
import logging
import os
import sqlite3
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from config import DB_PATH

logger = logging.getLogger(__name__)

# ── Model ─────────────────────────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS  = 1024
TEMPERATURE = 0.5

# ── System prompt ─────────────────────────────────────────────────────────────
KIRAN_SYSTEM_PROMPT = """You are Kiran — a senior trading partner to Zeeshan Haider, \
a PSX swing trader with 7 years of experience.

YOUR IDENTITY:
- You are not an assistant. You are a partner with skin in the game.
- You share one goal: outperform KSE-100 with controlled risk, within the system, without violating the rules.
- You have one personality — analytical, accountable, inquisitive. Never neutral. Never decorative.
- You hold a position. You defend it with data. When data changes, you say so explicitly and explain why you revised.
- You remember what you said. You do not contradict yourself without acknowledging the contradiction and explaining it.
- You are never cheerful without reason. Never alarmed without data.
- You can be serious, witty, or blunt — but always in service of the goal.
- Brevity is respect. Say what matters. Cut the rest.

YOUR RULES:
- NEVER name a stock symbol unless it appears explicitly in the context snapshot provided in this exact call. No exceptions.
- NEVER answer a stock or sector question using general knowledge or LLM training data. PSX knowledge in your training is unreliable and incomplete.
- If the data needed to answer is not in your context, say exactly: "I don't have enough data on this in my current context. Ask me again after a deeper pull."
- You are only as good as the data in front of you. Silence is better than a wrong stock name.
- Never recommend outside Zeeshan's system
- Never ignore the benchmark. 5% month means nothing if KSE-100 did 20%
- Never forget the trade log. The market is only half the picture
- Never give a neutral answer when data demands a position
- When the market is dead — say so. Don't manufacture signals.
- When Zeeshan is hesitating without reason — say so.
- When the system missed something — investigate, don't excuse.

YOUR VOICE:
- Speak in prose. Short. Pointed.
- Never bullet points. Never tables. Never "here are today's signals."
- Two lines or eight — never a wall of text.
- You may be witty when the market deserves it.
- You may be blunt when Zeeshan needs it.
- You are always the same partner. Every single day.

STANCE INSTRUCTION:
After your prose response, on a new line write exactly:
STANCE: <one sentence summary of your position today>
This line is parsed programmatically. Keep it under 120 characters."""


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(trigger_type: str, zeeshan_input: str | None) -> tuple[str, str]:
    """Return (rendered_context_block, market_date_str)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    today = date.today().isoformat()

    # ── 1. Regime ─────────────────────────────────────────────────────────────
    cur.execute("""
        SELECT date, regime
        FROM market_regime
        ORDER BY date DESC LIMIT 1
    """)
    regime_row = cur.fetchone()
    regime      = regime_row["regime"] if regime_row else "UNKNOWN"
    market_date = regime_row["date"]   if regime_row else today

    # ── 2. KSE-100 current + 30d performance ──────────────────────────────────
    cur.execute("""
        SELECT date, close
        FROM index_prices
        WHERE symbol = 'KSE-100'
        ORDER BY date DESC LIMIT 31
    """)
    kse_rows = cur.fetchall()
    kse100_close  = kse_rows[0]["close"]  if kse_rows else None
    kse100_30d_pct = None
    if len(kse_rows) >= 2:
        close_now  = kse_rows[0]["close"]
        close_30d  = kse_rows[-1]["close"]
        if close_30d:
            kse100_30d_pct = round((close_now - close_30d) / close_30d * 100, 2)

    # ── 3. Breadth — % stocks above 20d EMA (Option B: inline from prices_adjusted) ──
    cur.execute("""
        SELECT symbol, date, close
        FROM prices_adjusted
        WHERE date >= date(?, '-45 days')
          AND symbol IN (SELECT symbol FROM stock_metadata WHERE is_active = 1)
        ORDER BY symbol, date
    """, (market_date,))
    pa_rows = cur.fetchall()

    from collections import defaultdict
    sym_closes: dict[str, list[float]] = defaultdict(list)
    for r in pa_rows:
        if r["close"]:
            sym_closes[r["symbol"]].append(r["close"])

    above_ema = 0
    total_sym = 0
    for sym, closes in sym_closes.items():
        if len(closes) < 20:
            continue
        total_sym += 1
        k = 2 / (20 + 1)
        ema = closes[0]
        for c in closes[1:]:
            ema = c * k + ema * (1 - k)
        if closes[-1] > ema:
            above_ema += 1

    breadth_pct    = round(above_ema / total_sym * 100, 1) if total_sym else None
    breadth_status = (
        "Expanding" if breadth_pct and breadth_pct >= 60 else
        "Contracting" if breadth_pct and breadth_pct <= 40 else
        "Neutral"
    ) if breadth_pct is not None else "N/A"

    # ── 4. Top 3 sectors ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT s1.sector, s1.composite_score, s1.rs_rank,
               s1.rs_inflection,
               (SELECT COUNT(*) FROM sector_signals s2
                WHERE s2.sector = s1.sector
                  AND s2.rs_inflection = s1.rs_inflection
                  AND s2.date <= s1.date
                  AND s2.date > date(s1.date, '-30 days')) AS streak_days
        FROM sector_signals s1
        WHERE s1.date = (SELECT MAX(date) FROM sector_signals)
        ORDER BY s1.composite_score DESC
        LIMIT 3
    """)
    top_sectors = cur.fetchall()

    def _fmt_sector(row, rank):
        if not row:
            return f"  {rank}. N/A"
        direction = "Rising" if row["rs_inflection"] and row["rs_inflection"] > 0 else "Falling"
        days      = row["streak_days"] or 1
        return (
            f"  {rank}. {row['sector']} — score {round(row['composite_score'], 3)}, "
            f"RS rank {row['rs_rank']}, {direction} for {days} sessions"
        )

    sector_block = "\n".join(_fmt_sector(r, i + 1) for i, r in enumerate(top_sectors))

    # ── 5. Top 5 setups today ────────────────────────────────────────────────
    cur.execute("""
        SELECT sl.symbol, sl.setup_type, sl.setup_date,
               sm.sector, ss.rs_rank, ss.base_tightness,
               ss.pivot_distance_pct, ss.avg_vol_10d
        FROM setup_log sl
        JOIN stock_signals ss
          ON ss.symbol = sl.symbol
         AND ss.date   = sl.setup_date
        LEFT JOIN stock_metadata sm ON sm.symbol = sl.symbol
        WHERE sl.setup_date = (SELECT MAX(setup_date) FROM setup_log)
          AND sl.setup_type IN ('PRE_BREAKOUT', 'BREAKOUT')
        ORDER BY
          CASE sl.setup_type WHEN 'PRE_BREAKOUT' THEN 1 ELSE 2 END,
          ss.rs_rank ASC
        LIMIT 5
    """)
    setup_rows = cur.fetchall()

    def _fmt_setup(r):
        bbw  = f"{round(r['base_tightness'], 1)}% BBW" if r["base_tightness"] else "—"
        dist = f"{round(r['pivot_distance_pct'], 1)}% from pivot" if r["pivot_distance_pct"] else "—"
        return (
            f"  {r['symbol']} [{r['setup_type']}] sector={r['sector'] or '—'} "
            f"RS#{r['rs_rank']} | {bbw} | {dist}"
        )

    setups_block = (
        "\n".join(_fmt_setup(r) for r in setup_rows)
        if setup_rows else "  No PRE_BREAKOUT/BREAKOUT setups today."
    )

    # ── 6. Trade log snapshot ─────────────────────────────────────────────────
    cur.execute("""
        SELECT
            SUM(CASE WHEN status IN ('Active','Pending') THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN status = 'Closed'
                      AND created_date >= date('now', '-30 days') THEN 1 ELSE 0 END) AS closed_30d,
            SUM(CASE WHEN outcome = 'Win'
                      AND status = 'Closed'
                      AND created_date >= date('now', '-30 days') THEN 1 ELSE 0 END) AS wins_30d,
            AVG(CASE WHEN status = 'Closed'
                      AND created_date >= date('now', '-30 days')
                     THEN actual_pl_pct END) AS avg_pl_30d
        FROM trade_setups
        WHERE source IN ('Actual', 'System', 'STM')
    """)
    tl = cur.fetchone()

    # Simpler fallback if trade_setups schema differs
    try:
        open_positions = tl["open_count"]      or 0
        closed_30d     = tl["closed_30d"]      or 0
        wins_30d       = tl["wins_30d"]        or 0
        win_rate_30d   = round(wins_30d / closed_30d * 100, 1) if closed_30d else None
        avg_pl_30d     = round(tl["avg_pl_30d"], 2) if tl["avg_pl_30d"] else None
    except Exception:
        open_positions = win_rate_30d = avg_pl_30d = None
        closed_30d = 0

    # Days inactive
    cur.execute("""
        SELECT MAX(created_date) AS last_trade FROM trade_setups
        WHERE source IN ('Actual', 'System', 'STM')
          AND status IN ('Active', 'Closed')
    """)
    lt_row = cur.fetchone()
    days_inactive = None
    if lt_row and lt_row["last_trade"]:
        from datetime import datetime
        last_dt = datetime.strptime(lt_row["last_trade"][:10], "%Y-%m-%d").date()
        days_inactive = (date.today() - last_dt).days

    # KSE-100 vs P&L gap this month — approximate
    cur.execute("""
        SELECT SUM(actual_pl_pct) AS month_pl
        FROM trade_setups
        WHERE status = 'Closed'
          AND created_date >= date('now', 'start of month')
          AND source IN ('Actual', 'System', 'STM')
    """)
    month_pl_row = cur.fetchone()
    month_pl = round(month_pl_row["month_pl"], 2) if month_pl_row and month_pl_row["month_pl"] else None

    cur.execute("""
        SELECT close FROM index_prices WHERE symbol = 'KSE-100'
          AND date >= date('now', 'start of month')
        ORDER BY date ASC LIMIT 1
    """)
    kse_month_start = cur.fetchone()
    kse100_month_pct = None
    if kse_month_start and kse100_close:
        kse100_month_pct = round(
            (kse100_close - kse_month_start["close"]) / kse_month_start["close"] * 100, 2
        )

    pnl_vs_kse100 = (
        round(month_pl - kse100_month_pct, 2)
        if month_pl is not None and kse100_month_pct is not None
        else None
    )

    # ── 7. Agent memory — last 7 entries ─────────────────────────────────────
    memory_rows = _get_memory_rows(cur, n=7)
    if memory_rows:
        mem_lines = [
            f"  {r['market_date']} [{r['trigger_type']}]: {r['stance'] or r['response'][:120]}"
            for r in memory_rows
        ]
        memory_block = "\n".join(mem_lines)
    else:
        memory_block = "  No prior entries."

    con.close()

    # ── Render context ────────────────────────────────────────────────────────
    context = f"""MARKET STATE (as of {market_date}):
Regime: {regime}
KSE-100: {kse100_close} | 30d performance: {kse100_30d_pct}%
Breadth: {breadth_pct}% stocks above 20d EMA | Status: {breadth_status}

SECTOR ROTATION:
Top 3 sectors by composite score:
{sector_block}

TODAY'S SETUPS (from setup_log):
{setups_block}

ZEESHAN'S TRADE LOG:
Current open positions: {open_positions}
Trades closed last 30 days: {closed_30d}
Win rate last 30 days: {f'{win_rate_30d}%' if win_rate_30d is not None else 'N/A'}
Avg P&L last 30 days: {f'{avg_pl_30d}%' if avg_pl_30d is not None else 'N/A'}
P&L vs KSE-100 this month: {f'{pnl_vs_kse100:+.2f}%' if pnl_vs_kse100 is not None else 'N/A'}
Days inactive: {days_inactive if days_inactive is not None else 'N/A'}

AGENT MEMORY (last 7 journal entries):
{memory_block}

TRIGGER: {trigger_type}
ZEESHAN SAYS: {zeeshan_input or ''}"""

    return context, market_date


# ── Memory helpers ────────────────────────────────────────────────────────────

def _get_memory_rows(cur, n: int = 7) -> list:
    cur.execute("""
        SELECT market_date, trigger_type, stance, response
        FROM agent_memory
        ORDER BY id DESC
        LIMIT ?
    """, (n,))
    rows = cur.fetchall()
    return list(reversed(rows))  # oldest first for readability


def get_memory(n: int = 7) -> list[dict]:
    """Return last n agent_memory rows as list of dicts (oldest first)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = _get_memory_rows(cur, n)
    result = [dict(r) for r in rows]
    con.close()
    return result


def get_latest_response() -> dict | None:
    """Return the most recent agent_memory row as dict, or None."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT * FROM agent_memory ORDER BY id DESC LIMIT 1
    """)
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


# ── Groq call ─────────────────────────────────────────────────────────────────

def _call_groq(system: str, user_msg: str) -> tuple[str, int, int]:
    """Call Groq API. Returns (response_text, prompt_tokens, completion_tokens)."""
    try:
        from groq import Groq as GroqClient
    except ImportError:
        raise RuntimeError("groq package not installed — run: pip install groq")

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key or api_key.startswith("paste"):
        raise RuntimeError("GROQ_API_KEY not set in environment or .env")

    client = GroqClient(api_key=api_key)
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    text           = resp.choices[0].message.content or ""
    prompt_tokens  = resp.usage.prompt_tokens      if resp.usage else 0
    compl_tokens   = resp.usage.completion_tokens  if resp.usage else 0
    return text, prompt_tokens, compl_tokens


# ── Stance extractor ──────────────────────────────────────────────────────────

def _extract_stance(response: str) -> tuple[str, str]:
    """Split response into (prose, stance). Removes STANCE: line from prose."""
    lines  = response.strip().splitlines()
    stance = None
    prose_lines = []
    for line in lines:
        if line.strip().upper().startswith("STANCE:"):
            stance = line.split(":", 1)[1].strip()
        else:
            prose_lines.append(line)
    prose = "\n".join(prose_lines).strip()
    return prose, stance or ""


# ── Save to DB ────────────────────────────────────────────────────────────────

def _save_to_memory(
    market_date: str,
    trigger_type: str,
    regime: str | None,
    zeeshan_input: str | None,
    stance: str,
    response: str,
    context_snapshot: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO agent_memory
            (market_date, trigger_type, regime, zeeshan_input,
             stance, response, context_snapshot,
             model, prompt_tokens, completion_tokens)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        market_date, trigger_type, regime, zeeshan_input,
        stance, response, context_snapshot,
        GROQ_MODEL, prompt_tokens, completion_tokens,
    ))
    row_id = cur.lastrowid
    con.commit()
    con.close()
    return row_id


# ── Main entry point ──────────────────────────────────────────────────────────

def run_kiran(
    trigger_type: str = "scheduled",
    zeeshan_input: str | None = None,
) -> str:
    """
    Build context, call Groq, save to agent_memory, return prose response.

    trigger_type: 'scheduled' | 'morning_open' | 'conversational'
    zeeshan_input: his message (conversational only, else None)
    """
    if trigger_type not in ("scheduled", "morning_open", "conversational"):
        raise ValueError(f"Unknown trigger_type: {trigger_type!r}")

    context, market_date = _build_context(trigger_type, zeeshan_input)

    # Extract regime from context for storage
    regime = None
    for line in context.splitlines():
        if line.startswith("Regime:"):
            regime = line.split(":", 1)[1].strip()
            break

    raw_response, prompt_tokens, compl_tokens = _call_groq(
        system   = KIRAN_SYSTEM_PROMPT,
        user_msg = context,
    )

    prose, stance = _extract_stance(raw_response)

    _save_to_memory(
        market_date      = market_date,
        trigger_type     = trigger_type,
        regime           = regime,
        zeeshan_input    = zeeshan_input,
        stance           = stance,
        response         = prose,
        context_snapshot = context,
        prompt_tokens    = prompt_tokens,
        completion_tokens= compl_tokens,
    )

    logger.info(
        "Kiran [%s | %s] → %d tokens | stance: %s",
        trigger_type, market_date, prompt_tokens + compl_tokens, stance[:60]
    )
    return prose


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    trigger = sys.argv[1] if len(sys.argv) > 1 else "scheduled"
    msg     = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"\n--- Kiran [{trigger}] ---\n")
    try:
        response = run_kiran(trigger, msg)
        print(response)
        print("\n[Saved to agent_memory]")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
