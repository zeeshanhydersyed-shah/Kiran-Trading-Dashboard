"""
Agent Self-Learning Loop
========================
Runs weekly (Sundays) after the backtest step.

What it does:
  1. Grade all ungraded agent_opportunities older than MIN_AGE_DAYS
     → looks up price history, determines if target_1r / stop_loss was hit
     → marks outcome: Win | Loss | Expired
  2. Recompute agent_patterns stats (win_rate, avg_pl, profit_factor, confidence)
  3. Ask Claude to write a learning summary comparing:
       - which patterns are working vs failing
       - which sectors / regimes performed best
       - concrete rule adjustments to try
  4. Save summary to agent_learning_log

Run manually:
    python agent_learn.py

Or let run_update.bat call it on Sundays (see below).
"""

import json
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

import anthropic
import json

import agent_db as adb
from database import get_conn, init_db

# ── Constants ────────────────────────────────────────────────────────────────
MIN_AGE_DAYS   = 5    # don't grade opportunities until at least this many days old
MAX_EVAL_DAYS  = 20   # look forward up to this many trading sessions
MODEL          = "claude-sonnet-4-6"


# ── Price helpers ─────────────────────────────────────────────────────────────

def _get_prices_after(symbol: str, from_date: str, limit: int = MAX_EVAL_DAYS) -> list[dict]:
    """Return up to `limit` daily closes for symbol after from_date (inclusive)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date,
                      COALESCE(high, close) AS high,
                      COALESCE(low,  close) AS low,
                      close
               FROM prices
               WHERE symbol = ? AND date > ?
               ORDER BY date ASC
               LIMIT ?""",
            (symbol, from_date, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Grade a single opportunity ────────────────────────────────────────────────

def _grade_opportunity(opp: dict) -> dict | None:
    """
    Look up price history after run_date and determine outcome.

    Returns dict with keys: outcome, exit_price, exit_date, actual_pl_pct, days_held
    or None if not enough data yet.

    Logic (uses intraday high/low to be realistic):
      LONG : high >= target_1r → Win  |  low <= stop_loss → Loss
      SHORT: low  <= target_1r → Win  |  high >= stop_loss → Loss
    If neither triggered within MAX_EVAL_DAYS → Expired (neutral).
    """
    symbol    = opp["symbol"]
    direction = opp["direction"]
    run_date  = opp["run_date"]
    entry     = float(opp.get("entry_price") or 0)
    sl        = float(opp.get("stop_loss")   or 0)
    t1        = float(opp.get("target_1r")   or 0)

    if entry <= 0 or sl <= 0 or t1 <= 0:
        return None

    prices = _get_prices_after(symbol, run_date)
    if not prices:
        return None

    for i, p in enumerate(prices):
        high  = float(p["high"])
        low   = float(p["low"])
        close = float(p["close"])
        pdate = p["date"]

        if direction == "LONG":
            if low <= sl:
                pl_pct = round((sl - entry) / entry * 100, 2)
                return {"outcome": "Loss", "exit_price": sl, "exit_date": pdate,
                        "actual_pl_pct": pl_pct, "days_held": i + 1}
            if high >= t1:
                pl_pct = round((t1 - entry) / entry * 100, 2)
                return {"outcome": "Win", "exit_price": t1, "exit_date": pdate,
                        "actual_pl_pct": pl_pct, "days_held": i + 1}
        else:  # SHORT
            if high >= sl:
                pl_pct = round((entry - sl) / entry * 100, 2) * -1
                return {"outcome": "Loss", "exit_price": sl, "exit_date": pdate,
                        "actual_pl_pct": pl_pct, "days_held": i + 1}
            if low <= t1:
                pl_pct = round((entry - t1) / entry * 100, 2)
                return {"outcome": "Win", "exit_price": t1, "exit_date": pdate,
                        "actual_pl_pct": pl_pct, "days_held": i + 1}

    # Hit neither within MAX_EVAL_DAYS — expired at last close
    last = prices[-1]
    close = float(last["close"])
    if direction == "LONG":
        pl_pct = round((close - entry) / entry * 100, 2)
    else:
        pl_pct = round((entry - close) / entry * 100, 2)

    return {"outcome": "Expired", "exit_price": close, "exit_date": last["date"],
            "actual_pl_pct": pl_pct, "days_held": len(prices)}


# ── Step 1: Grade ungraded opportunities ─────────────────────────────────────

def grade_opportunities() -> list[dict]:
    """Grade all ungraded Pending agent opportunities older than MIN_AGE_DAYS."""
    cutoff = (date.today() - timedelta(days=MIN_AGE_DAYS)).isoformat()
    newly_graded = []

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ao.id, ao.symbol, ao.direction, ao.run_date,
                      ao.entry_price, ao.stop_loss, ao.target_1r, ao.target_2r,
                      ao.risk_pct, ao.pattern_name, ao.sector, ao.confidence_pct,
                      ao.reasoning
               FROM agent_opportunities ao
               WHERE ao.status = 'Pending'
                 AND ao.outcome IS NULL
                 AND ao.run_date <= ?
               ORDER BY ao.run_date ASC""",
            (cutoff,),
        ).fetchall()

    logger.info("Found %d ungraded opportunities to evaluate", len(rows))

    for row in rows:
        opp = dict(row)
        result = _grade_opportunity(opp)
        if result is None:
            logger.debug("  %s %s (%s): insufficient price data", opp["direction"], opp["symbol"], opp["run_date"])
            continue

        note = (
            f"Auto-graded {result['days_held']}d after signal. "
            f"{'✅ Hit T1' if result['outcome'] == 'Win' else '❌ Hit SL' if result['outcome'] == 'Loss' else '⏱ Expired at close'} "
            f"on {result['exit_date']} ({result['actual_pl_pct']:+.1f}%)"
        )

        adb.update_opportunity_status(
            opp_id       = opp["id"],
            status       = "Expired",   # Pending → Expired (paper trade, not actually taken)
            outcome      = result["outcome"],
            actual_exit  = result["exit_price"],
            exit_date    = result["exit_date"],
            actual_pl_pct= result["actual_pl_pct"],
            notes        = note,
        )

        opp.update(result)
        opp["note"] = note
        newly_graded.append(opp)

        logger.info(
            "  Graded: %s %s | %s | %+.1f%% | %s",
            opp["direction"], opp["symbol"], result["outcome"],
            result["actual_pl_pct"], result["exit_date"]
        )

    logger.info("Graded %d opportunities this run", len(newly_graded))
    return newly_graded


# ── Step 2: Update pattern stats ──────────────────────────────────────────────

def update_pattern_stats() -> int:
    """
    Recompute win_rate, avg_pl, profit_factor, confidence for every pattern
    based on all graded opportunities.
    """
    with get_conn() as conn:
        pattern_rows = conn.execute(
            """SELECT pattern_name,
                      COUNT(*)                                          AS total,
                      SUM(CASE WHEN outcome='Win'  THEN 1 ELSE 0 END)  AS wins,
                      SUM(CASE WHEN outcome='Loss' THEN 1 ELSE 0 END)  AS losses,
                      AVG(actual_pl_pct)                               AS avg_pl,
                      SUM(CASE WHEN actual_pl_pct > 0 THEN actual_pl_pct ELSE 0 END) AS gross_profit,
                      SUM(CASE WHEN actual_pl_pct < 0 THEN ABS(actual_pl_pct) ELSE 0 END) AS gross_loss
               FROM agent_opportunities
               WHERE outcome IS NOT NULL
                 AND pattern_name IS NOT NULL
               GROUP BY pattern_name""",
        ).fetchall()

    updated = 0
    for p in pattern_rows:
        wins   = p["wins"]   or 0
        losses = p["losses"] or 0
        closed = wins + losses
        if closed == 0:
            continue

        win_rate = round(wins / closed * 100, 1)
        avg_pl   = round(float(p["avg_pl"] or 0), 2)
        gross_profit = float(p["gross_profit"] or 0)
        gross_loss   = float(p["gross_loss"] or 1)
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

        if closed >= 15 and win_rate >= 55:
            confidence = "High"
        elif closed >= 8 and win_rate >= 45:
            confidence = "Medium"
        else:
            confidence = "Low"

        # Retire patterns with poor enough track record
        is_active = not (closed >= 10 and win_rate < 30)

        existing = adb.get_agent_patterns(active_only=False)
        match = next((x for x in existing if x["pattern_name"] == p["pattern_name"]), None)
        if not match:
            continue

        adb.upsert_agent_pattern({
            **match,
            "signal_count": p["total"],
            "win_count":    wins,
            "loss_count":   losses,
            "win_rate_pct": win_rate,
            "avg_pl_pct":   avg_pl,
            "profit_factor": pf,
            "confidence":   confidence,
            "is_active":    is_active,
            "last_updated": date.today().isoformat(),
        })
        updated += 1
        logger.info(
            "  Pattern '%s': %d/%d wins (%.0f%%) | avg P&L %+.1f%% | PF %.2f | %s",
            p["pattern_name"], wins, closed, win_rate, avg_pl,
            pf or 0, confidence
        )

    logger.info("Updated stats for %d patterns", updated)
    return updated


# ── Step 3: Claude writes the learning summary ────────────────────────────────

def _build_learning_prompt(newly_graded: list[dict], patterns: list[dict]) -> str:
    """Build the prompt for Claude's learning summary."""

    # Outcome breakdown of newly graded
    wins      = [x for x in newly_graded if x.get("outcome") == "Win"]
    losses    = [x for x in newly_graded if x.get("outcome") == "Loss"]
    expired   = [x for x in newly_graded if x.get("outcome") == "Expired"]

    graded_lines = []
    for g in sorted(newly_graded, key=lambda x: x.get("actual_pl_pct", 0), reverse=True):
        graded_lines.append(
            f"  {g['direction']:5s} {g['symbol']:8s} | {g.get('outcome','?'):8s} | "
            f"{g.get('actual_pl_pct', 0):+.1f}% | {g.get('days_held', '?')}d | "
            f"pattern: {g.get('pattern_name') or 'none'} | sector: {g.get('sector') or '?'}"
        )

    pattern_lines = []
    for p in patterns:
        closed = (p.get("win_count") or 0) + (p.get("loss_count") or 0)
        pattern_lines.append(
            f"  {p['pattern_name']:30s} | {closed:3d} trades | "
            f"win% {p.get('win_rate_pct') or 0:.0f}% | avg P&L {p.get('avg_pl_pct') or 0:+.1f}% | "
            f"PF {p.get('profit_factor') or 0:.2f} | {p.get('confidence','Low'):6s} | "
            f"{'ACTIVE' if p.get('is_active') else 'RETIRED'}"
        )

    return f"""You are the Kiran Trading Agent, a quantitative trader focused on the Pakistan Stock Exchange (PSX/KSE-100).

This is your weekly self-review. You generated trade suggestions over the past weeks. Those suggestions have now been graded against actual price history. Write a rigorous, honest post-mortem.

════════════════════════════════════════════════════════
NEWLY GRADED OPPORTUNITIES THIS WEEK ({len(newly_graded)} total)
Wins: {len(wins)} | Losses: {len(losses)} | Expired/neutral: {len(expired)}
════════════════════════════════════════════════════════
{chr(10).join(graded_lines) if graded_lines else '  (none this week)'}

════════════════════════════════════════════════════════
ALL PATTERN PERFORMANCE (cumulative)
════════════════════════════════════════════════════════
{chr(10).join(pattern_lines) if pattern_lines else '  (no patterns yet)'}

════════════════════════════════════════════════════════

Write your learning summary in this structure:

## What Worked This Week
(specific patterns or setups that generated wins — be concrete)

## What Failed and Why
(specific losses — what did the price do that you didn't anticipate?)

## Pattern Health Check
(which patterns have enough data to trust? which need more samples? which should be retired?)

## Market Context Observations
(did regime, sector rotation, or broader market conditions affect outcomes?)

## Rule Adjustments for Next Week
(concrete, actionable changes — e.g., tighten SL on X pattern, avoid Y sector in ranging markets)

## Confidence Score Update
(rate each pattern: Low / Medium / High — justify with data)

Be direct. Don't sugarcoat losses. If a pattern is failing, say so and explain why you're keeping or retiring it.
"""


def write_learning_summary(newly_graded: list[dict]) -> str:
    """Ask Claude to write the weekly learning narrative. Returns the text."""
    patterns = adb.get_agent_patterns(active_only=False)
    prompt   = _build_learning_prompt(newly_graded, patterns)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── Step 4: Save learning log ─────────────────────────────────────────────────

def save_learning_entry(
    newly_graded: list[dict],
    patterns_updated: int,
    summary: str,
) -> None:
    wins   = sum(1 for g in newly_graded if g.get("outcome") == "Win")
    losses = sum(1 for g in newly_graded if g.get("outcome") == "Loss")

    adb.save_learning_log({
        "run_date":                date.today().isoformat(),
        "run_type":                "weekly_learn",
        "opportunities_generated": 0,
        "patterns_updated":        patterns_updated,
        "market_regime":           None,
        "key_observations":        summary,
        "model_used":              MODEL,
        "tokens_used":             None,
        "run_duration_sec":        None,
        "error_log":               None,
    })
    logger.info("Learning log saved — %d wins, %d losses this cycle", wins, losses)


# ── Step 5: Behavioral profile update ────────────────────────────────────────

def build_behavioral_profile() -> str:
    """
    Analyse the past 30 days of chat logs and ask Claude to write
    a trader behavioral profile with guardrails.
    Saves the result to agent_trader_profile.
    """
    stats = adb.get_chat_stats(days=30)
    logs  = adb.get_chat_log(days=30, limit=200)

    if stats["total_messages"] < 5:
        logger.info("Not enough chat history for behavioral profile (need 5+ messages).")
        return ""

    # Build representative sample of user messages
    user_msgs = [l for l in logs if l.get("role") == "user"][-50:]  # last 50 user messages

    emotion_counts  = stats.get("emotion_counts", {})
    top_symbols     = stats.get("top_symbols", [])
    question_types  = stats.get("question_types", {})

    sample_lines = []
    for m in user_msgs[-20:]:  # last 20 for context
        emotions = ""
        try:
            em = json.loads(m.get("emotions") or "[]")
            if em:
                emotions = f" [emotions: {', '.join(em)}]"
        except Exception:
            pass
        syms = ""
        try:
            s = json.loads(m.get("symbols_mentioned") or "[]")
            if s:
                syms = f" [stocks: {', '.join(s)}]"
        except Exception:
            pass
        sample_lines.append(
            f"  [{m.get('created_at','?')[:10]}] ({m.get('question_type','?')}){syms}{emotions}: {m.get('message','')[:120]}"
        )

    prompt = f"""You are analysing the chat history of a PSX trader named Zeeshan to build a behavioral profile.

Your goal: identify his trading psychology patterns, biases, and guardrails to put in place.

═══════════════════════════════════════════
CHAT STATISTICS (last 30 days)
═══════════════════════════════════════════
Total messages: {stats['total_messages']}
Question types: {question_types}
Emotional signals detected: {emotion_counts}
Most asked-about stocks: {[s[0] for s in top_symbols[:10]]}

═══════════════════════════════════════════
SAMPLE OF RECENT MESSAGES
═══════════════════════════════════════════
{chr(10).join(sample_lines) if sample_lines else '(none yet)'}

═══════════════════════════════════════════

Based on the above, write a trader profile in this structure:

## Trader Profile
(2-3 paragraphs describing Zeeshan's trading psychology, strengths, and blind spots based on the data)

## Key Biases Identified
(bullet list of specific psychological biases with evidence from the data)

## Behavioral Patterns
(when does he tend to ask setup questions? which regimes trigger emotional messages? what types of stocks attract him?)

## Guardrail Rules
(5-8 specific rules the agent should enforce in future conversations, based on observed patterns. E.g., "When user expresses temptation in a ranging market, require them to articulate the breakout confirmation criteria before validating")

## Watch List
(stocks he keeps asking about — note which he took vs. didn't take if inferable)

Be honest and data-driven. This profile is used to make the agent more effective at protecting him from his own biases.
"""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    profile_text = response.content[0].text

    # Extract guardrail rules section as a list
    guardrails = []
    in_guardrails = False
    for line in profile_text.split("\n"):
        if "## Guardrail Rules" in line:
            in_guardrails = True
            continue
        if in_guardrails and line.startswith("##"):
            break
        if in_guardrails and line.strip().startswith(("-", "*", "•")):
            guardrails.append(line.strip().lstrip("-*• ").strip())

    # Week date (Monday)
    from datetime import date as _date
    today = _date.today()
    week_date = (today - __import__("datetime").timedelta(days=today.weekday())).isoformat()

    adb.save_trader_profile(
        week_date       = week_date,
        profile_text    = profile_text,
        key_biases      = [],  # Claude puts them in prose
        temptation_stocks = {s[0]: s[1] for s in top_symbols[:10]},
        emotion_counts  = emotion_counts,
        regime_behavior = {},
        guardrail_rules = guardrails[:8],
    )

    logger.info("Behavioral profile saved for week %s (%d guardrails)", week_date, len(guardrails))
    return profile_text


# ── Main ──────────────────────────────────────────────────────────────────────

def run_learning_loop() -> dict:
    """Full pipeline: grade → update patterns → summarise → log."""
    import time
    t0 = time.time()

    logger.info("═" * 60)
    logger.info("KIRAN AGENT SELF-LEARNING LOOP — %s", date.today().isoformat())
    logger.info("═" * 60)

    init_db()

    # 1. Grade
    logger.info("\n── Step 1: Grade ungraded opportunities ──")
    newly_graded = grade_opportunities()

    # 2. Pattern stats
    logger.info("\n── Step 2: Update pattern stats ──")
    patterns_updated = update_pattern_stats()

    # 3. Learning summary from Claude
    logger.info("\n── Step 3: Claude writes learning summary ──")
    summary = "(No opportunities graded this run — nothing to learn yet.)"
    if newly_graded or adb.get_agent_patterns(active_only=False):
        try:
            summary = write_learning_summary(newly_graded)
            logger.info("Summary written (%d chars)", len(summary))
        except Exception as e:
            logger.warning("Claude summary failed: %s", e)
            summary = f"Summary generation failed: {e}"

    # Print summary to log
    logger.info("\n%s", summary)

    # 4. Save log
    logger.info("\n── Step 4: Save learning log ──")
    save_learning_entry(newly_graded, patterns_updated, summary)

    # 5. Behavioral profile
    logger.info("\n── Step 5: Update trader behavioral profile ──")
    try:
        profile = build_behavioral_profile()
        if profile:
            logger.info("Behavioral profile updated (%d chars)", len(profile))
        else:
            logger.info("Skipped — insufficient chat history.")
    except Exception as e:
        logger.warning("Behavioral profile failed: %s", e)

    duration = round(time.time() - t0, 1)
    logger.info("\n═" * 60)
    logger.info(
        "Learning loop complete in %.1fs | Graded: %d | Patterns updated: %d",
        duration, len(newly_graded), patterns_updated
    )

    return {
        "graded":           len(newly_graded),
        "patterns_updated": patterns_updated,
        "summary":          summary,
    }


if __name__ == "__main__":
    run_learning_loop()
