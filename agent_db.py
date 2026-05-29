"""
Agent database layer — SQLite tables for the Claude Trading Agent.

Tables:
  agent_reports        — daily / weekly / monthly narrative reports
  agent_opportunities  — today's specific trade candidates with AI reasoning
  agent_patterns       — discovered patterns + running performance stats
  agent_learning_log   — what the agent learned each run (audit trail)

All functions use the same DB_PATH as the main pipeline (psx_data.db).
Call init_agent_tables() once at startup (database.py's init_db() does this).
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from config import DB_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper (mirrors database.py — same file, same conn semantics)
# ---------------------------------------------------------------------------

@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

AGENT_SCHEMA = """
-- ── Agent daily / weekly / monthly reports ──────────────────────────────
CREATE TABLE IF NOT EXISTS agent_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT    NOT NULL,          -- YYYY-MM-DD
    report_type   TEXT    NOT NULL,          -- daily | weekly | monthly
    market_regime TEXT,                      -- Bullish | Ranging | Bearish …
    breadth_score REAL,
    narrative     TEXT    NOT NULL,          -- full Markdown report from Claude
    raw_json      TEXT,                      -- full agent JSON output (debug)
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, report_type)           -- one report per type per day
);
CREATE INDEX IF NOT EXISTS idx_agent_reports_date ON agent_reports (run_date);

-- ── Agent-generated trade opportunities ─────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT    NOT NULL,        -- when the agent generated this
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,        -- LONG | SHORT
    pattern_name    TEXT,                    -- which pattern matched
    pattern_id      INTEGER,                 -- FK → agent_patterns.id (nullable)
    confidence_pct  REAL,                    -- 0–100 agent confidence
    entry_price     REAL,
    stop_loss       REAL,
    target_1r       REAL,
    target_2r       REAL,
    risk_pct        REAL,
    reasoning       TEXT    NOT NULL,        -- Claude's explanation
    sector          TEXT,
    sector_momentum TEXT,
    status          TEXT    NOT NULL DEFAULT 'Pending',  -- Pending | Taken | Skipped | Expired
    outcome         TEXT,                    -- Win | Loss | Breakeven (filled after close)
    actual_exit     REAL,
    exit_date       TEXT,
    actual_pl_pct   REAL,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_opp_date   ON agent_opportunities (run_date);
CREATE INDEX IF NOT EXISTS idx_agent_opp_symbol ON agent_opportunities (symbol);
CREATE INDEX IF NOT EXISTS idx_agent_opp_status ON agent_opportunities (status);

-- ── Discovered patterns with running performance ─────────────────────────
CREATE TABLE IF NOT EXISTS agent_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name    TEXT    NOT NULL UNIQUE,
    description     TEXT    NOT NULL,        -- Claude's description
    conditions      TEXT    NOT NULL,        -- JSON: entry rules
    first_seen      TEXT    NOT NULL,        -- YYYY-MM-DD
    last_updated    TEXT    NOT NULL,        -- YYYY-MM-DD
    signal_count    INTEGER NOT NULL DEFAULT 0,
    win_count       INTEGER NOT NULL DEFAULT 0,
    loss_count      INTEGER NOT NULL DEFAULT 0,
    win_rate_pct    REAL,
    avg_pl_pct      REAL,
    profit_factor   REAL,
    confidence      TEXT    NOT NULL DEFAULT 'Low',  -- Low | Medium | High
    is_active       INTEGER NOT NULL DEFAULT 1,      -- 0 = retired
    raw_json        TEXT,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── Agent learning log (audit trail of every run) ────────────────────────
CREATE TABLE IF NOT EXISTS agent_learning_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT    NOT NULL,
    run_type        TEXT    NOT NULL DEFAULT 'daily',
    opportunities_generated INTEGER DEFAULT 0,
    patterns_updated        INTEGER DEFAULT 0,
    market_regime           TEXT,
    key_observations        TEXT,            -- bullet-point observations (Markdown)
    model_used              TEXT,
    tokens_used             INTEGER,
    run_duration_sec        REAL,
    error_log               TEXT,            -- non-fatal errors / warnings
    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_log_date ON agent_learning_log (run_date);

-- ── User-provided reference breakout examples ────────────────────────────
-- User says "LUCK broke out on 2026-04-15" → agent analyses that bar and
-- stores the pre-breakout characteristics as a calibration template.
CREATE TABLE IF NOT EXISTS agent_reference_breakouts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT    NOT NULL,
    breakout_date       TEXT    NOT NULL,       -- YYYY-MM-DD
    direction           TEXT    NOT NULL DEFAULT 'LONG',  -- LONG | SHORT
    pre_consol_days     INTEGER,                -- how many tight days before BO
    pre_range_pct       REAL,                   -- 5d range% before the BO candle
    pre_rs_vs_kse       REAL,                   -- RS vs KSE-100 in 30d before BO
    pre_ma21_dist_pct   REAL,                   -- close vs MA21 (%)
    pre_ma50_dist_pct   REAL,                   -- close vs MA50 (%)
    pre_ma200_dist_pct  REAL,                   -- close vs MA200 (%)
    pre_vol_ratio       REAL,                   -- avg vol 5d / avg vol 20d
    bo_candle_range_pct REAL,                   -- breakout candle size as % of close
    post_gain_pct       REAL,                   -- max gain in 10 sessions after BO
    post_days_to_peak   INTEGER,                -- how many sessions to reach peak
    analysis_text       TEXT,                   -- Claude's prose analysis of the BO
    notes               TEXT,                   -- user's free notes
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (symbol, breakout_date, direction)
);
CREATE INDEX IF NOT EXISTS idx_ref_bo_symbol ON agent_reference_breakouts (symbol);

-- ── Chat message log — every user/agent exchange ─────────────────────────
CREATE TABLE IF NOT EXISTS agent_chat_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,              -- UUID per dashboard session
    role            TEXT    NOT NULL,              -- user | assistant
    message         TEXT    NOT NULL,
    symbols_mentioned TEXT,                        -- JSON list e.g. ["PTC","BAFL"]
    emotions        TEXT,                          -- JSON list e.g. ["tempted","fomo"]
    question_type   TEXT,                          -- setup|performance|regime|psychology|other
    market_regime   TEXT,                          -- regime label at time of message
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_session  ON agent_chat_log (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_created  ON agent_chat_log (created_at);

-- ── Trader behavioral profile — updated weekly by Claude ─────────────────
CREATE TABLE IF NOT EXISTS agent_trader_profile (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week_date       TEXT    NOT NULL UNIQUE,       -- YYYY-MM-DD (Monday of week)
    profile_text    TEXT    NOT NULL,              -- Claude's narrative profile
    key_biases      TEXT,                          -- JSON list of identified biases
    temptation_stocks TEXT,                        -- JSON: stocks asked about most
    emotion_counts  TEXT,                          -- JSON: {"tempted":5,"fomo":2,...}
    regime_behavior TEXT,                          -- JSON: how user behaves per regime
    guardrail_rules TEXT,                          -- JSON: specific rules to enforce
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def init_agent_tables():
    """Create all agent tables and benchmark columns (safe to call multiple times)."""
    with _conn() as conn:
        conn.executescript(AGENT_SCHEMA)
    # Benchmark columns (separate migration — ALTER TABLE, can't be in executescript)
    try:
        from agent_benchmark import init_benchmark_columns
        init_benchmark_columns()
    except Exception as _e:
        logger.warning("Benchmark column init failed: %s", _e)
    # Safe migrations
    _safe_alters = [
        "ALTER TABLE agent_reference_breakouts ADD COLUMN direction TEXT NOT NULL DEFAULT 'LONG'",
        "ALTER TABLE agent_chat_log ADD COLUMN session_id TEXT NOT NULL DEFAULT 'legacy'",
        "ALTER TABLE agent_chat_log ADD COLUMN question_type TEXT",
        "ALTER TABLE agent_chat_log ADD COLUMN market_regime TEXT",
        # Step 1 & 3 — regime veto + learning loop foundation
        "ALTER TABLE agent_opportunities ADD COLUMN regime_at_creation TEXT",
        "ALTER TABLE agent_opportunities ADD COLUMN universe_stage3_pct REAL",
        "ALTER TABLE agent_opportunities ADD COLUMN suppressed_reason TEXT",
        "ALTER TABLE agent_opportunities ADD COLUMN suppressed_date TEXT",
    ]
    with _conn() as conn:
        for sql in _safe_alters:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists
    logger.info("Agent tables initialised.")


# ---------------------------------------------------------------------------
# agent_reports
# ---------------------------------------------------------------------------

def save_agent_report(
    run_date: str,
    report_type: str,
    narrative: str,
    market_regime: str = None,
    breadth_score: float = None,
    raw_json: str = None,
) -> int:
    """Upsert a report. Returns the row id."""
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_reports
                (run_date, report_type, market_regime, breadth_score, narrative, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_date, report_type) DO UPDATE
                SET narrative     = excluded.narrative,
                    market_regime = excluded.market_regime,
                    breadth_score = excluded.breadth_score,
                    raw_json      = excluded.raw_json,
                    created_at    = CURRENT_TIMESTAMP
            """,
            (run_date, report_type, market_regime, breadth_score, narrative, raw_json),
        )
        return cur.lastrowid


def get_agent_reports(report_type: str = None, limit: int = 30) -> list[dict]:
    """Return reports newest-first, optionally filtered by type."""
    with _conn() as conn:
        if report_type:
            rows = conn.execute(
                "SELECT * FROM agent_reports WHERE report_type=? ORDER BY run_date DESC LIMIT ?",
                (report_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_reports ORDER BY run_date DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_agent_report(report_type: str = "daily") -> dict | None:
    """Return the most recent report of a given type."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_reports WHERE report_type=? ORDER BY run_date DESC LIMIT 1",
            (report_type,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Regime veto helpers
# ---------------------------------------------------------------------------

def get_latest_regime_for_veto() -> dict:
    """
    Return the regime sub-dict from the most recent daily agent report.
    Used by the dashboard read-time gate to determine suppression state.
    Returns {} if no report exists yet.
    """
    report = get_latest_agent_report("daily")
    if not report or not report.get("raw_json"):
        return {}
    try:
        raw = json.loads(report["raw_json"])
        return raw.get("regime", {})
    except Exception:
        return {}


def get_prev_stage3_pct(days_back: int = 7) -> float | None:
    """
    Return the universe_stage3_pct stored in the daily report approximately
    days_back ago. Used by Phase 2 write-time gate for the RoC check.
    Returns None if no historical report is available.
    """
    from datetime import timedelta
    target_date = (date.today() - timedelta(days=days_back)).isoformat()
    with _conn() as conn:
        row = conn.execute(
            """SELECT raw_json FROM agent_reports
               WHERE report_type = 'daily' AND run_date <= ?
               ORDER BY run_date DESC LIMIT 1""",
            (target_date,),
        ).fetchone()
    if not row or not row["raw_json"]:
        return None
    try:
        raw = json.loads(row["raw_json"])
        return raw.get("universe_stage3_pct")
    except Exception:
        return None


def apply_regime_decay(
    current_regime: dict,
    trading_days_threshold: int = 5,
) -> int:
    """
    Auto-close Pending opportunities that are both:
      (a) older than trading_days_threshold weekday sessions, AND
      (b) conflicted with the current regime (long in a cash/ranging/exhaustion env)

    A breakout setup that has aged 5+ sessions in a hostile regime is a broken
    setup — price has moved on. Status → 'Closed', outcome → 'Regime Decay'.
    Returns count of opportunities closed.
    """
    from datetime import timedelta

    trade_bias      = current_regime.get("trade_bias", "Balanced").lower()
    position_sizing = current_regime.get("position_sizing", "Full").lower()
    regime_label    = current_regime.get("regime", "").lower()

    suppress_longs = (
        trade_bias == "cash"
        or position_sizing == "cash"
        or any(r in regime_label for r in ("range", "ranging", "tight range",
                                            "wide range", "volatile range"))
        or ("late bull" in regime_label and position_sizing in ("cash", "minimal"))
    )
    suppress_all = (trade_bias == "cash" or position_sizing == "cash")

    if not suppress_longs and not suppress_all:
        return 0  # regime is permissive — nothing to decay

    today = date.today()
    closed_count = 0

    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, run_date, symbol, direction FROM agent_opportunities "
            "WHERE status = 'Pending' AND outcome IS NULL",
        ).fetchall()

        for row in rows:
            direction = row["direction"]
            conflicted = (
                (direction == "LONG" and suppress_longs)
                or suppress_all
            )
            if not conflicted:
                continue

            run_dt = date.fromisoformat(row["run_date"])
            # Count weekday sessions between run_date and today (inclusive)
            trading_days = sum(
                1 for i in range((today - run_dt).days + 1)
                if (run_dt + timedelta(days=i)).weekday() < 5
            )
            if trading_days > trading_days_threshold:
                conn.execute(
                    """UPDATE agent_opportunities
                       SET status  = 'Closed',
                           outcome = 'Regime Decay',
                           exit_date = ?,
                           notes = COALESCE(notes || ' | ', '') ||
                                   'Auto-closed: regime hostile for 5+ sessions.'
                       WHERE id = ?""",
                    (today.isoformat(), row["id"]),
                )
                closed_count += 1
                logger.info(
                    "Regime decay: closed %s %s (created %s, %d sessions old)",
                    direction, row["symbol"], row["run_date"], trading_days,
                )

    return closed_count


# ---------------------------------------------------------------------------
# agent_opportunities
# ---------------------------------------------------------------------------

def save_agent_opportunity(opp: dict) -> int:
    """Insert a new agent-generated opportunity. Returns row id."""
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_opportunities (
                run_date, symbol, direction, pattern_name, pattern_id,
                confidence_pct, entry_price, stop_loss, target_1r, target_2r,
                risk_pct, reasoning, sector, sector_momentum, status,
                regime_at_creation, universe_stage3_pct
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                opp["run_date"], opp["symbol"], opp["direction"],
                opp.get("pattern_name"), opp.get("pattern_id"),
                opp.get("confidence_pct"), opp.get("entry_price"),
                opp.get("stop_loss"), opp.get("target_1r"), opp.get("target_2r"),
                opp.get("risk_pct"), opp.get("reasoning", ""),
                opp.get("sector"), opp.get("sector_momentum"), "Pending",
                opp.get("regime_at_creation"), opp.get("universe_stage3_pct"),
            ),
        )
        return cur.lastrowid


def get_agent_opportunities(
    run_date: str = None,
    status: str = None,
    limit: int = 50,
) -> list[dict]:
    """Return opportunities, optionally filtered by date and/or status."""
    clauses, params = [], []
    if run_date:
        clauses.append("run_date = ?")
        params.append(run_date)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_opportunities {where} ORDER BY run_date DESC, confidence_pct DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_todays_opportunities() -> list[dict]:
    """Return all opportunities generated today."""
    today = date.today().isoformat()
    return get_agent_opportunities(run_date=today)


def update_opportunity_status(
    opp_id: int,
    status: str,
    outcome: str = None,
    actual_exit: float = None,
    exit_date: str = None,
    actual_pl_pct: float = None,
    notes: str = None,
):
    """Update the outcome of an opportunity after a trade is closed."""
    with _conn() as conn:
        conn.execute(
            """
            UPDATE agent_opportunities
            SET status       = ?,
                outcome      = COALESCE(?, outcome),
                actual_exit  = COALESCE(?, actual_exit),
                exit_date    = COALESCE(?, exit_date),
                actual_pl_pct= COALESCE(?, actual_pl_pct),
                notes        = COALESCE(?, notes)
            WHERE id = ?
            """,
            (status, outcome, actual_exit, exit_date, actual_pl_pct, notes, opp_id),
        )


def opportunity_already_saved(symbol: str, direction: str, run_date: str) -> bool:
    """Prevent duplicate opportunities for the same symbol+direction on a given day."""
    with _conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM agent_opportunities
               WHERE symbol=? AND direction=? AND run_date=? AND status='Pending' LIMIT 1""",
            (symbol, direction, run_date),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# agent_patterns
# ---------------------------------------------------------------------------

def upsert_agent_pattern(pattern: dict) -> int:
    """Insert or update a pattern. Returns row id."""
    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM agent_patterns WHERE pattern_name=?",
            (pattern["pattern_name"],),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE agent_patterns
                SET description  = ?,
                    conditions   = ?,
                    last_updated = ?,
                    signal_count = ?,
                    win_count    = ?,
                    loss_count   = ?,
                    win_rate_pct = ?,
                    avg_pl_pct   = ?,
                    profit_factor= ?,
                    confidence   = ?,
                    is_active    = ?,
                    raw_json     = ?
                WHERE pattern_name = ?
                """,
                (
                    pattern.get("description", ""),
                    json.dumps(pattern.get("conditions", {})),
                    pattern.get("last_updated", date.today().isoformat()),
                    pattern.get("signal_count", 0),
                    pattern.get("win_count", 0),
                    pattern.get("loss_count", 0),
                    pattern.get("win_rate_pct"),
                    pattern.get("avg_pl_pct"),
                    pattern.get("profit_factor"),
                    pattern.get("confidence", "Low"),
                    int(pattern.get("is_active", True)),
                    json.dumps(pattern.get("raw_json", {})),
                    pattern["pattern_name"],
                ),
            )
            return existing["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO agent_patterns (
                    pattern_name, description, conditions,
                    first_seen, last_updated,
                    signal_count, win_count, loss_count,
                    win_rate_pct, avg_pl_pct, profit_factor,
                    confidence, is_active, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pattern["pattern_name"],
                    pattern.get("description", ""),
                    json.dumps(pattern.get("conditions", {})),
                    pattern.get("first_seen", date.today().isoformat()),
                    pattern.get("last_updated", date.today().isoformat()),
                    pattern.get("signal_count", 0),
                    pattern.get("win_count", 0),
                    pattern.get("loss_count", 0),
                    pattern.get("win_rate_pct"),
                    pattern.get("avg_pl_pct"),
                    pattern.get("profit_factor"),
                    pattern.get("confidence", "Low"),
                    int(pattern.get("is_active", True)),
                    json.dumps(pattern.get("raw_json", {})),
                ),
            )
            return cur.lastrowid


def get_agent_patterns(active_only: bool = True) -> list[dict]:
    """Return all patterns, optionally only active ones."""
    with _conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM agent_patterns WHERE is_active=1 ORDER BY win_rate_pct DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_patterns ORDER BY win_rate_pct DESC"
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# agent_learning_log
# ---------------------------------------------------------------------------

def save_learning_log(entry: dict) -> int:
    """Append a run-summary entry to the learning log."""
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_learning_log (
                run_date, run_type,
                opportunities_generated, patterns_updated,
                market_regime, key_observations,
                model_used, tokens_used, run_duration_sec, error_log
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry.get("run_date", date.today().isoformat()),
                entry.get("run_type", "daily"),
                entry.get("opportunities_generated", 0),
                entry.get("patterns_updated", 0),
                entry.get("market_regime"),
                entry.get("key_observations"),
                entry.get("model_used"),
                entry.get("tokens_used"),
                entry.get("run_duration_sec"),
                entry.get("error_log"),
            ),
        )
        return cur.lastrowid


def get_learning_log(limit: int = 30) -> list[dict]:
    """Return the most recent learning log entries."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_learning_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Skipped-trade outcome tracker
# ---------------------------------------------------------------------------

def evaluate_skipped_opportunities(price_lookup_fn) -> list[dict]:
    """
    For every Skipped or Pending opportunity older than today, check whether
    it would have hit Target 2R or Stop Loss based on subsequent price closes.

    price_lookup_fn(symbol, from_date) → list of dicts with 'date' and 'close'

    Updates outcome + notes on each opportunity so the weekly report can say
    "You skipped BPL — it hit 2R (+12%). Missed opportunity."

    Returns list of evaluated opportunity dicts.
    """
    today = date.today().isoformat()
    evaluated = []

    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, symbol, direction, run_date, entry_price, stop_loss,
                      target_2r, target_1r, status, outcome
               FROM agent_opportunities
               WHERE status IN ('Skipped', 'Pending')
                 AND run_date < ?
                 AND outcome IS NULL""",
            (today,),
        ).fetchall()

    for row in rows:
        opp_id    = row["id"]
        symbol    = row["symbol"]
        direction = row["direction"]
        from_date = row["run_date"]
        entry     = float(row["entry_price"] or 0)
        sl        = float(row["stop_loss"] or 0)
        t2        = float(row["target_2r"] or 0)
        t1        = float(row["target_1r"] or 0)

        if entry == 0 or sl == 0:
            continue

        try:
            prices = price_lookup_fn(symbol, from_date)
        except Exception:
            continue

        outcome = None
        exit_price = None
        exit_date = None

        for p in prices:
            close = float(p.get("close", 0))
            if close == 0:
                continue
            pdate = p.get("date", "")

            if direction == "LONG":
                if close <= sl:
                    outcome, exit_price, exit_date = "Loss", sl, pdate
                    break
                elif t2 > 0 and close >= t2:
                    outcome, exit_price, exit_date = "Win", t2, pdate
                    break
                elif t1 > 0 and close >= t1:
                    outcome, exit_price, exit_date = "Win", t1, pdate
                    # don't break — keep checking for t2
            else:  # SHORT
                if close >= sl:
                    outcome, exit_price, exit_date = "Loss", sl, pdate
                    break
                elif t2 > 0 and close <= t2:
                    outcome, exit_price, exit_date = "Win", t2, pdate
                    break

        if outcome:
            pl_pct = 0.0
            if entry > 0 and exit_price:
                if direction == "LONG":
                    pl_pct = round((exit_price - entry) / entry * 100, 2)
                else:
                    pl_pct = round((entry - exit_price) / entry * 100, 2)

            was_skipped = row["status"] == "Skipped"
            note = (
                f"{'SKIPPED — ' if was_skipped else 'PAPER — '}"
                f"Would have {'hit 2R ✅' if outcome == 'Win' else 'hit SL ❌'} "
                f"on {exit_date} ({pl_pct:+.1f}%)"
            )

            update_opportunity_status(
                opp_id,
                status="Expired",
                outcome=outcome,
                actual_exit=exit_price,
                exit_date=exit_date,
                actual_pl_pct=pl_pct,
                notes=note,
            )

            evaluated.append({
                "id": opp_id, "symbol": symbol, "direction": direction,
                "outcome": outcome, "pl_pct": pl_pct,
                "was_skipped": was_skipped, "note": note,
            })

    if evaluated:
        logger.info(
            "evaluate_skipped_opportunities: resolved %d old opportunities "
            "(%d wins, %d losses)",
            len(evaluated),
            sum(1 for e in evaluated if e["outcome"] == "Win"),
            sum(1 for e in evaluated if e["outcome"] == "Loss"),
        )

    return evaluated


# ---------------------------------------------------------------------------
# Summary stats helper (for dashboard widgets)
# ---------------------------------------------------------------------------

def get_agent_performance_summary() -> dict:
    """
    Quick stats on how the agent's past opportunities performed.
    Returns a dict with overall win_rate, avg_pl_pct, total closed, etc.
    """
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)                                         AS total,
                SUM(CASE WHEN outcome='Win'  THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome='Loss' THEN 1 ELSE 0 END) AS losses,
                AVG(CASE WHEN actual_pl_pct IS NOT NULL THEN actual_pl_pct END) AS avg_pl,
                SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) AS pending
            FROM agent_opportunities
            WHERE status IN ('Win','Loss','Breakeven','Pending','Taken')
            """
        ).fetchone()
    if not row or row["total"] == 0:
        return {}
    closed = (row["wins"] or 0) + (row["losses"] or 0)
    win_rate = round(row["wins"] / closed * 100, 1) if closed > 0 else None
    return {
        "total":    row["total"],
        "wins":     row["wins"] or 0,
        "losses":   row["losses"] or 0,
        "pending":  row["pending"] or 0,
        "win_rate": win_rate,
        "avg_pl":   round(row["avg_pl"], 2) if row["avg_pl"] is not None else None,
    }


# ---------------------------------------------------------------------------
# Reference breakout examples (user-provided calibration data)
# ---------------------------------------------------------------------------

def save_reference_breakout(record: dict) -> int:
    """
    Upsert a user-provided reference breakout example.
    record keys: symbol, breakout_date, direction, pre_consol_days, pre_range_pct,
                 pre_rs_vs_kse, pre_ma21_dist_pct, pre_ma50_dist_pct,
                 pre_ma200_dist_pct, pre_vol_ratio, bo_candle_range_pct,
                 post_gain_pct, post_days_to_peak, analysis_text, notes
    """
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_reference_breakouts
                (symbol, breakout_date, direction, pre_consol_days, pre_range_pct,
                 pre_rs_vs_kse, pre_ma21_dist_pct, pre_ma50_dist_pct,
                 pre_ma200_dist_pct, pre_vol_ratio, bo_candle_range_pct,
                 post_gain_pct, post_days_to_peak, analysis_text, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, breakout_date, direction) DO UPDATE SET
                pre_consol_days     = excluded.pre_consol_days,
                pre_range_pct       = excluded.pre_range_pct,
                pre_rs_vs_kse       = excluded.pre_rs_vs_kse,
                pre_ma21_dist_pct   = excluded.pre_ma21_dist_pct,
                pre_ma50_dist_pct   = excluded.pre_ma50_dist_pct,
                pre_ma200_dist_pct  = excluded.pre_ma200_dist_pct,
                pre_vol_ratio       = excluded.pre_vol_ratio,
                bo_candle_range_pct = excluded.bo_candle_range_pct,
                post_gain_pct       = excluded.post_gain_pct,
                post_days_to_peak   = excluded.post_days_to_peak,
                analysis_text       = excluded.analysis_text,
                notes               = excluded.notes
            """,
            (
                record.get("symbol"),
                record.get("breakout_date"),
                record.get("direction", "LONG"),
                record.get("pre_consol_days"),
                record.get("pre_range_pct"),
                record.get("pre_rs_vs_kse"),
                record.get("pre_ma21_dist_pct"),
                record.get("pre_ma50_dist_pct"),
                record.get("pre_ma200_dist_pct"),
                record.get("pre_vol_ratio"),
                record.get("bo_candle_range_pct"),
                record.get("post_gain_pct"),
                record.get("post_days_to_peak"),
                record.get("analysis_text"),
                record.get("notes"),
            ),
        )
        return cur.lastrowid


def get_reference_breakouts(limit: int = 50) -> list[dict]:
    """Return all reference breakout examples, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_reference_breakouts ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_breakout_profile_stats() -> dict:
    """
    Compute the average characteristics of all reference breakouts.
    Used to calibrate what a 'Zeeshan-style momentum burst' looks like.
    """
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)                    AS n,
                AVG(pre_consol_days)        AS avg_consol_days,
                AVG(pre_range_pct)          AS avg_range_pct,
                AVG(pre_rs_vs_kse)          AS avg_rs,
                AVG(pre_ma21_dist_pct)      AS avg_ma21_dist,
                AVG(pre_ma200_dist_pct)     AS avg_ma200_dist,
                AVG(post_gain_pct)          AS avg_post_gain,
                AVG(post_days_to_peak)      AS avg_days_to_peak,
                MIN(pre_consol_days)        AS min_consol_days,
                MAX(pre_consol_days)        AS max_consol_days
            FROM agent_reference_breakouts
            WHERE post_gain_pct IS NOT NULL
            """
        ).fetchone()
    return dict(row) if row and row["n"] else {}


# ---------------------------------------------------------------------------
# Chat log
# ---------------------------------------------------------------------------

def log_chat_message(
    session_id: str,
    role: str,
    message: str,
    symbols_mentioned: list = None,
    emotions: list = None,
    question_type: str = None,
    market_regime: str = None,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO agent_chat_log
               (session_id, role, message, symbols_mentioned, emotions, question_type, market_regime)
               VALUES (?,?,?,?,?,?,?)""",
            (
                session_id, role, message,
                json.dumps(symbols_mentioned or []),
                json.dumps(emotions or []),
                question_type,
                market_regime,
            ),
        )
        return cur.lastrowid


def get_chat_log(days: int = 30, limit: int = 500) -> list[dict]:
    """Return recent chat messages, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM agent_chat_log
               WHERE created_at >= datetime('now', ?)
               ORDER BY created_at DESC LIMIT ?""",
            (f"-{days} days", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_chat_stats(days: int = 30) -> dict:
    """Aggregate stats from chat log for behavioral analysis."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT symbols_mentioned, emotions, question_type, market_regime
               FROM agent_chat_log
               WHERE role = 'user'
                 AND created_at >= datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchall()

    from collections import Counter
    symbol_counter  = Counter()
    emotion_counter = Counter()
    qtype_counter   = Counter()

    for r in rows:
        try:
            for s in json.loads(r["symbols_mentioned"] or "[]"):
                symbol_counter[s] += 1
        except Exception:
            pass
        try:
            for e in json.loads(r["emotions"] or "[]"):
                emotion_counter[e] += 1
        except Exception:
            pass
        if r["question_type"]:
            qtype_counter[r["question_type"]] += 1

    return {
        "total_messages": len(rows),
        "top_symbols":    symbol_counter.most_common(10),
        "emotion_counts": dict(emotion_counter),
        "question_types": dict(qtype_counter),
    }


# ---------------------------------------------------------------------------
# Trader behavioral profile
# ---------------------------------------------------------------------------

def save_trader_profile(
    week_date: str,
    profile_text: str,
    key_biases: list = None,
    temptation_stocks: dict = None,
    emotion_counts: dict = None,
    regime_behavior: dict = None,
    guardrail_rules: list = None,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO agent_trader_profile
               (week_date, profile_text, key_biases, temptation_stocks,
                emotion_counts, regime_behavior, guardrail_rules)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(week_date) DO UPDATE SET
                 profile_text     = excluded.profile_text,
                 key_biases       = excluded.key_biases,
                 temptation_stocks= excluded.temptation_stocks,
                 emotion_counts   = excluded.emotion_counts,
                 regime_behavior  = excluded.regime_behavior,
                 guardrail_rules  = excluded.guardrail_rules,
                 created_at       = CURRENT_TIMESTAMP""",
            (
                week_date,
                profile_text,
                json.dumps(key_biases or []),
                json.dumps(temptation_stocks or {}),
                json.dumps(emotion_counts or {}),
                json.dumps(regime_behavior or {}),
                json.dumps(guardrail_rules or []),
            ),
        )
        return cur.lastrowid


def get_latest_trader_profile() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_trader_profile ORDER BY week_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_trader_profile_history(limit: int = 10) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_trader_profile ORDER BY week_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
