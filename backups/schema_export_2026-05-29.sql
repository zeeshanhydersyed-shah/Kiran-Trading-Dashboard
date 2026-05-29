-- ============================================================
-- PSX Intelligence Platform — Full Schema Export
-- Snapshot: pre_audit_stable_snapshot_2026-05-29
-- Exported: 2026-05-29
-- Source: database.py + database_pg.py (verified by audit)
-- ============================================================

-- ── prices ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prices (
    symbol  TEXT            NOT NULL,
    date    TEXT            NOT NULL,
    close   REAL            NOT NULL,
    volume  INTEGER,
    high    REAL,
    low     REAL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date   ON prices (date);
CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices (symbol);

-- ── index_prices ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS index_prices (
    symbol  TEXT    NOT NULL,
    date    TEXT    NOT NULL,
    high    REAL,
    low     REAL,
    close   REAL    NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_idx_date ON index_prices (date);

-- ── sectors ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sectors (
    symbol  TEXT    NOT NULL,
    sector  TEXT    NOT NULL,
    PRIMARY KEY (symbol)
);

-- ── trade_setups ──────────────────────────────────────────────
-- Core columns (original schema)
-- Migration columns added incrementally (via ALTER TABLE in init_db)
CREATE TABLE IF NOT EXISTS trade_setups (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,  -- SERIAL in PostgreSQL
    created_date     TEXT            NOT NULL,
    direction        TEXT            NOT NULL,            -- LONG | SHORT
    symbol           TEXT            NOT NULL,
    sector           TEXT            NOT NULL,
    sector_momentum  TEXT            NOT NULL,
    stock_perf_30d   REAL            NOT NULL,
    stock_perf_10d   REAL            NOT NULL,
    latest_close     REAL            NOT NULL,
    support_level    REAL,
    resistance_level REAL,
    entry_price      REAL            NOT NULL,
    stop_loss        REAL            NOT NULL,
    target_1r        REAL            NOT NULL,
    target_2r        REAL            NOT NULL,
    risk_pct         REAL            NOT NULL,
    atr_pct          REAL            NOT NULL,
    status           TEXT            NOT NULL DEFAULT 'Pending',
    outcome          TEXT,                                -- Win | Loss | Breakeven
    notes            TEXT,
    -- Migration columns (added via ALTER TABLE)
    quality_score    INTEGER         DEFAULT 0,
    quality_checks   TEXT            DEFAULT '{}',
    range_width_pct  REAL,
    range_window     INTEGER,
    sector_rank      INTEGER,
    breadth_score    REAL,
    source           TEXT            DEFAULT 'System',   -- System | STM | Support Reversal | Actual
    actual_exit      REAL,
    actual_pl_pkr    REAL,
    actual_pl_pct    REAL,
    actual_rr        REAL,
    holding_days     INTEGER,
    exit_date        TEXT,
    actual_entry     REAL,
    -- PostgreSQL-only migration columns (not in SQLite init_db migrations)
    trade_source     TEXT            DEFAULT 'System',
    reason_notes     TEXT,
    quantity         REAL,
    trade_execution  TEXT            DEFAULT 'Paper'     -- Paper | Actual | Paper & Actual
);
CREATE INDEX IF NOT EXISTS idx_setups_symbol ON trade_setups (symbol);
CREATE INDEX IF NOT EXISTS idx_setups_status ON trade_setups (status);

-- ── backtest_setups ───────────────────────────────────────────
-- Created by backtest.py:init_backtest_table() — SQLite only
-- NOT created by database_pg.py init_db() (known gap — see audit LOW-10)
CREATE TABLE IF NOT EXISTS backtest_setups (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date       TEXT    NOT NULL,
    direction        TEXT    NOT NULL,
    symbol           TEXT    NOT NULL,
    sector           TEXT    NOT NULL,
    sector_momentum  TEXT,
    sector_rank      INTEGER,
    breadth_score    REAL,
    stock_perf_30d   REAL,
    stock_perf_60d   REAL,
    stock_perf_10d   REAL,
    latest_close     REAL,
    support_level    REAL,
    resistance_level REAL,
    entry_price      REAL    NOT NULL,
    stop_loss        REAL    NOT NULL,
    target_1r        REAL,
    target_2r        REAL,
    risk_pct         REAL,
    atr_pct          REAL,
    range_width_pct  REAL,
    range_window     INTEGER,
    quality_score    INTEGER,
    avg_vol_10d      REAL,
    entry_triggered  INTEGER DEFAULT 0,
    trigger_date     TEXT,
    outcome          TEXT,   -- Win_Trail | Win_T1 | Loss | No_Trigger | Stale_Setup
    outcome_date     TEXT,
    outcome_days     INTEGER,
    realized_r       REAL
);
CREATE INDEX IF NOT EXISTS idx_bt_date   ON backtest_setups (as_of_date);
CREATE INDEX IF NOT EXISTS idx_bt_symbol ON backtest_setups (symbol);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bt_unique
    ON backtest_setups (as_of_date, symbol, direction);

-- ── screened_dates ────────────────────────────────────────────
-- Tracks every date the backtest screener has processed (resumable)
CREATE TABLE IF NOT EXISTS screened_dates (
    date TEXT PRIMARY KEY
);

-- ── portfolio_transactions ────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    type       TEXT    NOT NULL,   -- deposit | withdrawal | dividend
    amount     REAL    NOT NULL,
    notes      TEXT,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_portfolio_tx_date ON portfolio_transactions (date);

-- ── portfolio_values ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_values (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL UNIQUE,
    value      REAL    NOT NULL,
    notes      TEXT,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_portfolio_val_date ON portfolio_values (date);

-- ── agent_patterns ────────────────────────────────────────────
-- Created by agent_db.py:init_agent_tables()
CREATE TABLE IF NOT EXISTS agent_patterns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT,
    pattern_type TEXT,
    description  TEXT,
    confidence   REAL,
    sample_size  INTEGER,
    raw_data     TEXT
);

-- ── agent_opportunities ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_opportunities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT,
    symbol       TEXT,
    direction    TEXT,
    entry_price  REAL,
    stop_loss    REAL,
    target       REAL,
    rationale    TEXT,
    confidence   REAL,
    status       TEXT DEFAULT 'Pending'
);

-- ── agent_reports ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    report_type TEXT,
    content    TEXT,
    metadata   TEXT
);

-- ── chat_log ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    role       TEXT,
    content    TEXT,
    session_id TEXT
);

-- ── trader_profile ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trader_profile (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT,
    key        TEXT UNIQUE,
    value      TEXT
);

-- ── agent_reference_breakouts ─────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_reference_breakouts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    symbol     TEXT,
    date       TEXT,
    direction  TEXT,
    notes      TEXT
);

-- ── sim_portfolio_trades ──────────────────────────────────────
-- Created by kiran_sim.py (local simulation only)
CREATE TABLE IF NOT EXISTS sim_portfolio_trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_date   TEXT,
    symbol       TEXT,
    direction    TEXT,
    entry_price  REAL,
    stop_loss    REAL,
    target_2r    REAL,
    outcome      TEXT,
    realized_r   REAL,
    outcome_date TEXT
);

-- ============================================================
-- KNOWN SCHEMA DIVERGENCES (from audit CRITICAL/HIGH findings)
-- ============================================================
-- 1. trade_execution column exists in PostgreSQL (database_pg.py migration)
--    but NOT in SQLite migrations (database.py). evaluate_paper_trades()
--    queries this column → crashes on SQLite (see audit HIGH-3).
--
-- 2. backtest_setups table is NOT created by database_pg.py init_db().
--    Must be created manually on Supabase if backtest data is needed on Cloud
--    (see audit LOW-10).
--
-- 3. sector_momentum labels changed in processor.py (Stage 2/3/4 format)
--    but backtest.py still uses old format (Heating Up / Cooling Down).
--    Stored values in trade_setups.sector_momentum are therefore mixed
--    across time (see audit CRITICAL-1).
-- ============================================================
