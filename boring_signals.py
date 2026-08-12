"""
boring_signals.py -- "Boring Breakouts" manual-execution infrastructure.

Single source of truth for the RS_60-conditioned Donchian breakout system
locked in boring_study_trading_rulebook_v1_2026-07-11.md (Addenda A-C
applied). SQLite only for now -- no Postgres path yet, same "code first,
sign-off before a live Supabase write" discipline this project applies to
every new table (see CLAUDE.md's E8.7 precedent). Do not wire this into
leaders_scan.py / kiran_voice.py / agent.py -- this is a standalone,
watch-and-manually-execute tool, not an automated trader.

Locked parameters (do not change without re-running the validation this
project's own discipline requires):
  STOP_PCT / TARGET_PCT / MAX_HORIZON  -- the exact TP-before-stop race
  RS_WINDOW = 60                        -- RS_60, NOT stock_signals.py's
                                           rs_score_20/rs_score_50 (different
                                           window, never validated for this)
  LIQUIDITY_THRESHOLD = 200_000         -- avg_vol_10d gate, applied BEFORE
                                           ranking (Addendum B: gating after
                                           the fact is not equivalent)
  TOP_DECILE = 9                        -- 0-indexed decile from a 10-way
                                           cross-sectional split; only decile
                                           9 is "Strategy Confirmed"

Zero-lookahead discipline (rulebook Sec 2): RS_60 and avg_vol_10d for day t
are ALWAYS computed from data through t-1 inclusive, frozen before day t's
breakout condition is evaluated. See _rs60_and_liquidity_asof().
"""

import sqlite3
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config import DB_PATH, EXCLUDED_SECTORS

logger = logging.getLogger(__name__)

STOP_PCT = -0.06
TARGET_PCT = 0.10
MAX_HORIZON = 90   # no longer used by update_open_signal_statuses() -- see HYBRID_FLOOR_PCT below
RS_WINDOW = 60
LIQUIDITY_THRESHOLD = 200_000
TOP_DECILE = 9
LOOKBACK_NS = (20, 60)   # both validated definitions; stored, not merged
HYBRID_FLOOR_PCT = -0.08   # HYBRID exit floor: stop never sits looser than Entry x (1 + this), validated rounds 5-8


def ensure_boring_signals_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS boring_signals (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol             TEXT NOT NULL,
            signal_date        TEXT NOT NULL,       -- date t; Close(t) confirms the breakout
            lookback_n         INTEGER NOT NULL,    -- 20 or 60 (which Donchian definition fired)
            breakout_level     REAL,                -- the threshold that had to be cleared:
                                                     -- 1.01 x MAX(high[t-n..t-1]) -- NOT the entry
                                                     -- price. Close(t) can land well above this.
            trigger_price      REAL NOT NULL,       -- Close(t) = entry price (was ambiguously
                                                     -- displayed as "the trigger" -- it's the entry,
                                                     -- breakout_level above is the actual level cleared)
            target_price       REAL NOT NULL,       -- trigger_price * 1.10
            stop_price         REAL NOT NULL,       -- trigger_price * 0.94
            rs_60              REAL NOT NULL,       -- RS_60(t-1), never t
            rs_60_decile       INTEGER NOT NULL,    -- 0-9, cross-sectional, eligible universe, as of t-1
            avg_vol_10d        REAL,                -- liquidity metric, as of t-1
            liquidity_pass     INTEGER NOT NULL,    -- 1 if avg_vol_10d > 200,000 else 0
            strategy_confirmed INTEGER NOT NULL,    -- 1 iff rs_60_decile = 9 AND liquidity_pass = 1
            status             TEXT NOT NULL DEFAULT 'Pending',
                               -- Pending | Executed | Target Hit | Stopped | Expired
            executed           INTEGER NOT NULL DEFAULT 0,
            executed_at        TEXT,
            executed_price     REAL,
            resolution_date    TEXT,
            resolution_type    TEXT,                -- TARGET | STOP | EXPIRED_90D
            days_open          INTEGER,
            created_at         TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(symbol, signal_date, lookback_n)
        );
        CREATE INDEX IF NOT EXISTS idx_boring_signals_status ON boring_signals(status);
        CREATE INDEX IF NOT EXISTS idx_boring_signals_date   ON boring_signals(signal_date);
        CREATE INDEX IF NOT EXISTS idx_boring_signals_symbol ON boring_signals(symbol);
    """)
    # Migration: breakout_level was added after the table already existed in
    # some environments -- CREATE TABLE IF NOT EXISTS won't retrofit a new
    # column onto an already-created table, so add it explicitly if missing.
    # Left NULL here on purpose: trigger_price/1.01 is NOT a valid stand-in
    # (trigger_price is the close, which is often well above the real
    # threshold -- dividing it back down would just fabricate a wrong
    # number). _backfill_breakout_levels() recomputes the true value from
    # actual price history instead and is called once from scan_boring_breakouts.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(boring_signals)").fetchall()}
    if "breakout_level" not in existing_cols:
        conn.execute("ALTER TABLE boring_signals ADD COLUMN breakout_level REAL")
        logger.info("boring_signals: added breakout_level column (NULL until backfilled from real price history).")
    if "current_stop" not in existing_cols:
        conn.execute("ALTER TABLE boring_signals ADD COLUMN current_stop REAL")
        logger.info("boring_signals: added current_stop column (NULL until update_open_signal_statuses() runs; "
                     "holds the live HYBRID trailing-stop level -- not the legacy fixed stop_price column).")


def _backfill_breakout_levels(conn: sqlite3.Connection) -> int:
    """
    Recomputes breakout_level for any existing rows where it's NULL (from
    before this column existed), using the actual historical prior-N-day
    high -- not an approximation from trigger_price. Safe to call every scan;
    a no-op once every row has a value.
    """
    missing = pd.read_sql_query(
        "SELECT id, symbol, signal_date, lookback_n FROM boring_signals WHERE breakout_level IS NULL", conn
    )
    if missing.empty:
        return 0
    by_symbol = _load_price_history(conn, set(missing["symbol"]))
    cur = conn.cursor()
    updated = 0
    for _, row in missing.iterrows():
        pf = by_symbol.get(row["symbol"])
        if pf is None:
            continue
        t = np.searchsorted(pf["dates"], row["signal_date"])
        n = int(row["lookback_n"])
        if t >= len(pf["dates"]) or pf["dates"][t] != row["signal_date"] or t < n:
            continue
        prior_high = np.nanmax(pf["high"][t - n:t])
        if np.isnan(prior_high):
            continue
        cur.execute("UPDATE boring_signals SET breakout_level = ? WHERE id = ?",
                    (prior_high * 1.01, int(row["id"])))
        updated += 1
    conn.commit()
    if updated:
        logger.info("boring_signals: backfilled breakout_level for %d pre-existing row(s).", updated)
    return updated


def _eligible_universe(conn: sqlite3.Connection) -> set[str]:
    """
    Verified, actively-used exclusions only: stock_metadata.is_active = 1
    (the same universe table sector_signals.py falls back to) joined
    against sectors, excluding config.EXCLUDED_SECTORS (the same filter
    processor.py applies for every other setup type).

    NOT independently verified for this feature: whether a separate
    futures/derivatives regex or config.INDEX_SYMBOLS/DFC_SYMBOLS exclusion
    is needed on top of this. No FUTURES_REGEX constant was found in
    config.py, and DFC_SYMBOLS has no other call site in this codebase as
    of 2026-07-11 -- it may not be a live universe filter at all. Recommend
    spot-checking the first live scan's output against a known futures
    symbol before trusting this blindly.
    """
    q = """
        SELECT sm.symbol FROM stock_metadata sm
        JOIN sectors s ON s.symbol = sm.symbol
        WHERE sm.is_active = 1
    """
    df = pd.read_sql_query(q, conn)
    universe = set(df["symbol"])
    excl_df = pd.read_sql_query("SELECT symbol, sector FROM sectors", conn)
    excluded = set(excl_df[excl_df["sector"].isin(EXCLUDED_SECTORS)]["symbol"])
    return universe - excluded


def _load_price_history(conn: sqlite3.Connection, symbols: set[str]) -> dict:
    q = """
        SELECT symbol, date, high, low, close, volume FROM prices_adjusted
        WHERE symbol IN ({})
        ORDER BY symbol, date
    """.format(",".join("?" * len(symbols)))
    df = pd.read_sql_query(q, conn, params=list(symbols))
    by_symbol = {}
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("date").reset_index(drop=True)
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "high": g["high"].to_numpy(dtype=float),
            "low": g["low"].to_numpy(dtype=float),
            "close": g["close"].to_numpy(dtype=float),
            "volume": g["volume"].to_numpy(dtype=float),
        }
    return by_symbol


def _load_kse100(conn: sqlite3.Connection) -> dict:
    df = pd.read_sql_query(
        "SELECT date, close FROM index_prices WHERE symbol = 'KSE-100' ORDER BY date", conn
    )
    return {"dates": df["date"].to_numpy(), "close": df["close"].to_numpy(dtype=float)}


def _rs60_and_liquidity_asof(by_symbol: dict, kse: dict, symbol: str, asof_date: str):
    """
    RS_60(symbol, asof_date) and avg_vol_10d(symbol, asof_date), computed
    using data through asof_date INCLUSIVE. Callers must pass t-1 as
    asof_date when scoring day t's breakout -- this function does not
    itself enforce the offset, by design (it's also used to freeze the
    watchlist at the close of t-1, where "asof_date" legitimately IS the
    latest available date).
    """
    pf = by_symbol.get(symbol)
    if pf is None:
        return None, None
    dates = pf["dates"]
    idx = np.searchsorted(dates, asof_date, side="right") - 1
    if idx < RS_WINDOW or idx >= len(dates):
        return None, None

    close_now = pf["close"][idx]
    close_then = pf["close"][idx - RS_WINDOW]
    if close_then <= 0 or np.isnan(close_now) or np.isnan(close_then):
        return None, None
    stock_ret = close_now / close_then - 1

    k_dates = kse["dates"]
    k_idx = np.searchsorted(k_dates, asof_date, side="right") - 1
    if k_idx < RS_WINDOW or k_idx >= len(k_dates):
        return None, None
    k_now, k_then = kse["close"][k_idx], kse["close"][k_idx - RS_WINDOW]
    if k_then <= 0 or np.isnan(k_now) or np.isnan(k_then):
        return None, None
    kse_ret = k_now / k_then - 1

    rs_60 = (stock_ret - kse_ret) * 100

    vol10 = pf["volume"][max(0, idx - 9):idx + 1]
    avg_vol_10d = np.nanmean(vol10) if len(vol10) else None

    return rs_60, avg_vol_10d


def _breakout_fires(by_symbol: dict, symbol: str, date: str, n: int):
    """
    Returns (close_t, breakout_level) if close[t] > MAX(high[t-n..t-1]) * 1.01,
    else None. breakout_level is the threshold that was cleared (1.01 x prior
    high) -- distinct from close_t, the entry price. close_t is very often
    well above breakout_level, not equal to it; that's not a contradiction,
    the rule only requires clearing the level, not landing on it exactly.
    """
    pf = by_symbol.get(symbol)
    if pf is None:
        return None
    dates = pf["dates"]
    t = np.searchsorted(dates, date)
    if t >= len(dates) or dates[t] != date or t < n:
        return None
    prior_high = np.nanmax(pf["high"][t - n:t])
    close_t = pf["close"][t]
    if np.isnan(prior_high) or np.isnan(close_t):
        return None
    breakout_level = prior_high * 1.01
    return (close_t, breakout_level) if close_t > breakout_level else None


def scan_boring_breakouts(date: str | None = None) -> int:
    """
    Evaluate the RS_60-conditioned Donchian breakout for a single trading
    date across the full eligible universe, for both locked lookbacks
    (20d, 60d), and insert any new signals. Idempotent -- UNIQUE(symbol,
    signal_date, lookback_n) plus INSERT OR IGNORE means re-running for an
    already-scanned date is a no-op. Returns the number of new rows inserted.
    """
    with sqlite3.connect(DB_PATH) as conn:
        ensure_boring_signals_table(conn)
        _backfill_breakout_levels(conn)
        universe = _eligible_universe(conn)
        by_symbol = _load_price_history(conn, universe)
        kse = _load_kse100(conn)

        if date is None:
            all_dates = sorted({d for pf in by_symbol.values() for d in pf["dates"]})
            if not all_dates:
                logger.warning("boring_signals: no price history found for eligible universe")
                return 0
            date = all_dates[-1]

        # index of t-1 for each symbol: use the latest date strictly before `date`
        prior_dates_by_symbol = {}
        for sym, pf in by_symbol.items():
            idx = np.searchsorted(pf["dates"], date) - 1
            if idx >= 0:
                prior_dates_by_symbol[sym] = pf["dates"][idx]

        # freeze RS_60 / liquidity as of t-1, per symbol (zero-lookahead)
        rs_rows = []
        for sym in universe:
            t1 = prior_dates_by_symbol.get(sym)
            if t1 is None:
                continue
            rs_60, avg_vol_10d = _rs60_and_liquidity_asof(by_symbol, kse, sym, t1)
            if rs_60 is None:
                continue
            rs_rows.append((sym, rs_60, avg_vol_10d))

        if not rs_rows:
            logger.info("boring_signals: no symbols with computable RS_60 as of %s", date)
            return 0

        rs_df = pd.DataFrame(rs_rows, columns=["symbol", "rs_60", "avg_vol_10d"])
        # FIX (RF#1): liquidity gate applied BEFORE ranking, not after -- matches this
        # module's own header comment and Addendum B's corrected methodology.
        rs_df["liquidity_pass"] = (rs_df["avg_vol_10d"].fillna(0) > LIQUIDITY_THRESHOLD).astype(int)
        gated_df = rs_df[rs_df["liquidity_pass"] == 1].copy()
        if len(gated_df) >= 10:
            gated_df["rs_60_decile"] = pd.qcut(gated_df["rs_60"], 10, labels=False, duplicates="drop")
        else:
            gated_df["rs_60_decile"] = np.nan
        rs_df = rs_df.merge(gated_df[["symbol", "rs_60_decile"]], on="symbol", how="left")
        # a symbol that fails the liquidity gate was never a member of the ranked
        # population -- sentinel, not a decile borrowed from a population it isn't in.
        rs_df["rs_60_decile"] = rs_df["rs_60_decile"].fillna(-1).astype(int)
        rs_lookup = rs_df.set_index("symbol")[
            ["rs_60", "avg_vol_10d", "liquidity_pass", "rs_60_decile"]].to_dict("index")

        inserted = 0
        cur = conn.cursor()
        # DEDUP GATE: a symbol with any currently-open (Pending/Executed) row is
        # ineligible to fire a new signal on ANY lookback until that row resolves
        # (Target Hit / Stopped / Expired). Single upfront query per scan -- not
        # one query per symbol -- held as a set, checked by O(1) membership below.
        open_symbols = {row[0] for row in cur.execute(
            "SELECT DISTINCT symbol FROM boring_signals WHERE status IN ('Pending', 'Executed')"
        ).fetchall()}
        for sym in universe:
            if sym in open_symbols:
                continue
            info = rs_lookup.get(sym)
            if info is None:
                continue
            for n in LOOKBACK_NS:
                fire = _breakout_fires(by_symbol, sym, date, n)
                if fire is None:
                    continue
                trigger_price, breakout_level = fire
                rs_60, avg_vol_10d, decile = info["rs_60"], info["avg_vol_10d"], int(info["rs_60_decile"])
                liquidity_pass = int(info["liquidity_pass"])
                strategy_confirmed = int(decile == TOP_DECILE and liquidity_pass == 1)
                try:
                    cur.execute(
                        """INSERT OR IGNORE INTO boring_signals
                           (symbol, signal_date, lookback_n, breakout_level, trigger_price,
                            target_price, stop_price, rs_60, rs_60_decile, avg_vol_10d,
                            liquidity_pass, strategy_confirmed)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sym, date, n, breakout_level, trigger_price, trigger_price * (1 + TARGET_PCT),
                         trigger_price * (1 + STOP_PCT), rs_60, decile, avg_vol_10d,
                         liquidity_pass, strategy_confirmed),
                    )
                    inserted += cur.rowcount
                except sqlite3.Error:
                    logger.exception("boring_signals: insert failed for %s %s N=%d", sym, date, n)
        conn.commit()
        logger.info("boring_signals: scanned %s, inserted %d new signal(s)", date, inserted)
        return inserted


def scan_boring_breakouts_pending(max_lookback: int = 15) -> int:
    """Scan every trading date that may not have been scanned yet, not just
    the newest one.

    `scan_boring_breakouts()` defaults to `all_dates[-1]` -- the newest date
    only. Called once a day from main.py's hook, that meant any day the hook
    missed was never scanned again: the next run just looked at the new
    newest date. Same single-date defect as the market_regime/sector_signals
    loss and setup_log's (docs/KIRAN_CLEANUP_AUDIT.md §21, §24, §25).

    Deciding *where* to resume is the wrinkle here, and it is why this is a
    bounded window rather than a true high-water mark: `boring_signals` only
    gets a row when a signal actually fires, so an empty stretch is
    indistinguishable from an unscanned one -- the table cannot tell you what
    has been scanned. So resume from whichever is later:

      * the most recent `signal_date` already recorded, or
      * `max_lookback` trading dates back from the newest date.

    That converts permanent silent loss into self-healing within
    `max_lookback` days, the same bounded-window compromise
    `auto_detect_suspects()` already makes in this codebase. A gap longer
    than the window would still be missed; closing that properly needs an
    explicit scan-progress marker, which is a schema change and is not worth
    it for a watch-only, SQLite-only feature. Re-scanning is cheap and safe:
    the per-date work is small next to the one-off universe/price load, and
    UNIQUE(symbol, signal_date, lookback_n) + INSERT OR IGNORE makes a
    repeat scan a no-op.

    Returns total new rows inserted across all dates scanned.
    """
    with sqlite3.connect(DB_PATH) as conn:
        ensure_boring_signals_table(conn)
        universe = _eligible_universe(conn)
        by_symbol = _load_price_history(conn, universe)
        all_dates = sorted({d for pf in by_symbol.values() for d in pf["dates"]})
        if not all_dates:
            logger.warning("boring_signals: no price history found for eligible universe")
            return 0
        last_signal = conn.execute(
            "SELECT MAX(signal_date) FROM boring_signals"
        ).fetchone()[0]

    window_start = all_dates[-max_lookback] if len(all_dates) > max_lookback else all_dates[0]
    resume_from = max(window_start, last_signal) if last_signal else window_start
    pending = [d for d in all_dates if d >= resume_from]

    if len(pending) > 1:
        logger.warning("boring_signals: scanning %d date(s), %s -> %s.",
                       len(pending), pending[0], pending[-1])
    total = 0
    for scan_date in pending:
        try:
            total += scan_boring_breakouts(scan_date)
        except Exception as exc:
            logger.warning("boring_signals: scan failed for %s: %s", scan_date, exc)
    return total


def update_open_signal_statuses() -> int:
    """
    Advances status for every row not yet in a terminal state (Stopped).

    Exit logic: HYBRID_TRAIL, validated rounds 5-8 -- a prior-day-low
    trailing stop with a hard floor at Entry x (1 + HYBRID_FLOOR_PCT):
      stop(entry_day) = max(Low(entry_day), Entry x (1 + HYBRID_FLOOR_PCT))
      stop(d)         = max(stop(d-1), Low(d-1))               for d > entry_day
    Monotonically non-decreasing by construction -- the floor never needs
    separate re-application after day 1 since stop(d-1) is already >= the
    floor by induction (verified equivalent to the two-variable trail/floor
    formulation used in the round 5-8 test scripts, not just assumed).
    Exit the first day Low(d) <= stop(d). Resolution price = stop(d) itself
    (the modeled level, not the printed Low) -- same optimistic-fill
    convention used throughout rounds 5-8, for continuity with what was
    actually validated, not a new assumption introduced here.
    No fixed take-profit (removed entirely -- this rule has no cap) and no
    fixed horizon/expiry (removed -- "censored," i.e. still-open, is a real
    validated outcome category, not an error state; MAX_HORIZON is no
    longer used by this function).

    Recomputed fully from entry on every call, not incrementally -- matches
    this module's existing idempotent, stateless-across-calls design (see
    _backfill_breakout_levels()'s docstring). current_stop is persisted
    purely for display/visibility of today's live level; it is never read
    back in as an input to the next call, so a stale or missing value here
    cannot corrupt a future resolution.

    Both Pending and Executed rows are evaluated identically (existing
    behavior, unchanged from before this rewrite) -- only Pending rows get
    days_open bumped while still open with no exit yet (existing asymmetry,
    preserved as-is, not introduced by this change).
    """
    with sqlite3.connect(DB_PATH) as conn:
        ensure_boring_signals_table(conn)
        open_rows = pd.read_sql_query(
            "SELECT * FROM boring_signals WHERE status IN ('Pending','Executed')", conn
        )
        if open_rows.empty:
            return 0

        symbols = set(open_rows["symbol"])
        by_symbol = _load_price_history(conn, symbols)
        updated = 0
        cur = conn.cursor()
        for _, row in open_rows.iterrows():
            pf = by_symbol.get(row["symbol"])
            if pf is None:
                continue
            dates, low = pf["dates"], pf["low"]
            t = int(np.searchsorted(dates, row["signal_date"]))
            if t >= len(dates) or dates[t] != row["signal_date"]:
                continue
            n = len(dates)
            entry = row["trigger_price"]
            floor_level = entry * (1 + HYBRID_FLOOR_PCT)

            stop = max(low[t], floor_level)
            exit_d = None
            for d in range(t + 1, n):
                stop = max(stop, low[d - 1])
                if low[d] <= stop:
                    exit_d = d
                    break

            if exit_d is not None:
                cur.execute(
                    """UPDATE boring_signals SET status=?, resolution_type=?, resolution_date=?,
                       days_open=?, current_stop=? WHERE id=?""",
                    ("Stopped", "STOP", dates[exit_d], exit_d - t, stop, row["id"]),
                )
                updated += 1
            elif row["status"] == "Pending":
                cur.execute("UPDATE boring_signals SET days_open=?, current_stop=? WHERE id=?",
                            ((n - 1) - t, stop, row["id"]))
            else:
                cur.execute("UPDATE boring_signals SET current_stop=? WHERE id=?", (stop, row["id"]))

        conn.commit()
        logger.info("boring_signals: updated %d signal statuses", updated)
        return updated


def mark_executed(signal_id: int, executed_price: float | None = None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """UPDATE boring_signals SET executed = 1, status = 'Executed',
               executed_at = datetime('now'), executed_price = COALESCE(?, trigger_price)
               WHERE id = ?""",
            (executed_price, signal_id),
        )
        conn.commit()


def get_boring_signals(status: str | None = None) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        ensure_boring_signals_table(conn)
        if status:
            return pd.read_sql_query(
                "SELECT * FROM boring_signals WHERE status = ? ORDER BY signal_date DESC", conn, params=(status,)
            )
        return pd.read_sql_query("SELECT * FROM boring_signals ORDER BY signal_date DESC", conn)
