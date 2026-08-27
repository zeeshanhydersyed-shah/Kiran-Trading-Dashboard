"""
leaders_scan.py — Pre-compute daily top picks for Leaders page.

Pipeline order (called from main.py after stock_signals are fresh):
    run_all()  →  append_leaders_scan()
                  save_top_picks()
                  fill_leaders_forward_returns()

Tables written:
    leaders_scan       — full filtered + scored candidate list (rebuilt daily)
    leaders_top_picks  — top 3 per setup type, with audit trail
"""

import os
import sqlite3
import pandas as pd
import config

# Postgres branch — mirrors sector_signals.py / regime.py's established
# _PG_URL pattern. leaders_scan / leaders_top_picks already exist in Supabase
# (populated once by migrate_to_supabase.py's initial copy, per project
# history) — this only adds the missing WRITE path; it does not create or
# alter schema on Postgres (DDL against production is out of scope here,
# per the project's own "acquire independently -> validate independently ->
# human review -> only then import" rule).
_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")

# Minimum final_score (raw - penalty) for a pick to be selected.
# Nothing below this threshold appears in leaders_top_picks.
# Re-derived 2026-07-10 (S-002 fix, PRE_BREAKOUT_Specification_v1.0.md Session
# Summary): _raw_score() dropped from 5 components (max 15) to 3 (max 9) after
# removing the rs_score_20 and sector_rs_rank blocks (confirmed dead, S-002).
# Old threshold was 8/15 = 53.3% of max; applied to the new max: 9 * 0.533 =
# 4.8, rounded to the nearest integer = 5.
MIN_PICK_SCORE = 5


# ── Table setup ───────────────────────────────────────────────────────────────

def ensure_tables(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS leaders_scan (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_date            DATE    NOT NULL,
        setup_type           TEXT    NOT NULL,
        symbol               TEXT    NOT NULL,
        sector               TEXT,
        sector_rank          INTEGER,
        rs_rank              INTEGER,
        sector_rs_rank       INTEGER,
        rs_score_20          REAL,
        rs_score_50          REAL,
        rank_change          INTEGER,
        base_tightness       REAL,
        pivot_high           REAL,
        pivot_distance_pct   REAL,
        avg_vol_10d          REAL,
        vol_ratio_today      REAL,
        entry_trigger        REAL,
        stop_loss            REAL,
        sl_pct               REAL,
        rs_inflection        INTEGER,
        sector_composite     REAL,
        vol_rejection_flag   INTEGER,
        nearest_overhead_pct REAL,
        vol_contraction      REAL,
        raw_score            INTEGER,
        penalty              INTEGER,
        final_score          INTEGER,
        flag                 TEXT,
        UNIQUE(scan_date, setup_type, symbol)
    );

    CREATE TABLE IF NOT EXISTS leaders_top_picks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_date       DATE    NOT NULL,
        setup_type      TEXT    NOT NULL,
        rank            INTEGER NOT NULL,
        symbol          TEXT,
        sector          TEXT,
        sector_rank     INTEGER,
        entry_trigger   REAL,
        stop_loss       REAL,
        sl_pct          REAL,
        vol_ratio_today REAL,
        key_reason      TEXT,
        flag            TEXT,
        fwd_return_5d   REAL,
        fwd_return_10d  REAL,
        fwd_return_20d  REAL,
        outcome_label   TEXT DEFAULT 'OPEN',
        triggered       INTEGER,
        trigger_date    DATE,
        UNIQUE(scan_date, setup_type, rank)
    );
    """)
    con.commit()


# ── Per-symbol price helpers ───────────────────────────────────────────────────

def _vol_ratio_today(con, symbol, scan_date):
    """Today's volume divided by prior 20-day average."""
    rows = con.execute("""
        SELECT volume FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC LIMIT 21
    """, (symbol, scan_date)).fetchall()
    if len(rows) < 2:
        return None
    today_vol = rows[0][0]
    avg = sum(r[0] for r in rows[1:]) / len(rows[1:])
    return round(today_vol / avg, 2) if avg else None


def _vol_rejection_flag(con, symbol, scan_date, pivot_high):
    """
    1 if any session in the last 10 trading days had:
      - the session HIGH reached within 2% of pivot_high, AND
      - close finished BELOW pivot_high (failed to hold), AND
      - volume was > 2x its 20-day average
    This specifically catches high-volume rejections at the resistance level,
    not just any busy day while the stock sits in the middle of its base.
    """
    rows = con.execute("""
        SELECT high, low, open, close, volume FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC LIMIT 30
    """, (symbol, scan_date)).fetchall()
    if len(rows) < 21:
        return 0
    near_pivot = pivot_high * 0.98
    for i in range(min(10, len(rows) - 20)):
        high, low, open_, close, vol = rows[i]
        avg = sum(r[4] for r in rows[i + 1:i + 21]) / 20
        # Rejection: high tested the pivot zone, close below pivot, AND bearish close
        # (close < open means the session turned down — genuine distribution, not just approach)
        if (avg and vol / avg > 2.0
                and high is not None and high >= near_pivot
                and close is not None and close < pivot_high
                and open_ is not None and close < open_):
            return 1
    return 0


def _nearest_overhead_pct(con, symbol, scan_date, pivot_high):
    """
    % distance from pivot_high to the nearest historical HIGH above it
    in the last 120 calendar days. Returns None if no overhead exists.
    """
    row = con.execute("""
        SELECT MIN(high) FROM prices
        WHERE symbol = ?
          AND date < ?
          AND date >= date(?, '-120 days')
          AND high > ?
    """, (symbol, scan_date, scan_date, pivot_high)).fetchone()
    if row and row[0]:
        return round((row[0] - pivot_high) / pivot_high * 100, 2)
    return None


# ── Per-symbol price helpers (Postgres) ───────────────────────────────────────
# Same logic as the SQLite versions above, %s placeholders, psycopg2 cursor.

def _vol_ratio_today_pg(cur, symbol, scan_date):
    cur.execute("""
        SELECT volume FROM prices
        WHERE symbol = %s AND date <= %s
        ORDER BY date DESC LIMIT 21
    """, (symbol, scan_date))
    rows = cur.fetchall()
    if len(rows) < 2:
        return None
    today_vol = rows[0]["volume"]
    tail = rows[1:]
    avg = sum(r["volume"] for r in tail) / len(tail)
    return round(today_vol / avg, 2) if avg else None


def _vol_rejection_flag_pg(cur, symbol, scan_date, pivot_high):
    cur.execute("""
        SELECT high, low, open, close, volume FROM prices
        WHERE symbol = %s AND date <= %s
        ORDER BY date DESC LIMIT 30
    """, (symbol, scan_date))
    rows = cur.fetchall()
    if len(rows) < 21:
        return 0
    # pivot_high is NUMERIC in Postgres -> psycopg2 hands back a
    # decimal.Decimal, and Decimal * float raises TypeError (this is the
    # "unsupported operand type(s) for *: 'decimal.Decimal' and 'float'"
    # that froze every leaders_scan date from 2026-07-01 onward). SQLite's
    # twin (_vol_rejection_flag) never hit this since sqlite3 returns plain
    # floats. Cast once, same pattern as sl_pct's float(...) cast above.
    near_pivot = float(pivot_high) * 0.98
    for i in range(min(10, len(rows) - 20)):
        r = rows[i]
        high, open_, close = r["high"], r["open"], r["close"]
        window = rows[i + 1:i + 21]
        avg = sum(w["volume"] for w in window) / 20
        vol = r["volume"]
        if (avg and vol / avg > 2.0
                and high is not None and high >= near_pivot
                and close is not None and close < pivot_high
                and open_ is not None and close < open_):
            return 1
    return 0


def _nearest_overhead_pct_pg(cur, symbol, scan_date, pivot_high):
    cur.execute("""
        SELECT MIN(high) AS min_high FROM prices
        WHERE symbol = %s
          AND date < %s
          AND date >= (%s::date - INTERVAL '120 days')
          AND high > %s
    """, (symbol, scan_date, scan_date, pivot_high))
    row = cur.fetchone()
    if row and row["min_high"]:
        return round((row["min_high"] - pivot_high) / pivot_high * 100, 2)
    return None


def _breakout_health_check_pg(cur, symbol, scan_date, pivot_high):
    cur.execute(
        "SELECT MAX(date) AS d FROM stock_signals WHERE symbol = %s "
        "AND bos_flag IS FALSE AND date <= %s",
        (symbol, scan_date),
    )
    last_zero = cur.fetchone()["d"]
    if last_zero is None:
        cur.execute("SELECT MIN(date) AS d FROM stock_signals WHERE symbol = %s", (symbol,))
        streak_start = cur.fetchone()["d"]
    else:
        cur.execute(
            "SELECT MIN(date) AS d FROM stock_signals WHERE symbol = %s "
            "AND date > %s AND bos_flag IS TRUE",
            (symbol, last_zero),
        )
        streak_start = cur.fetchone()["d"]

    if streak_start is None:
        return False

    cur.execute(
        "SELECT close FROM prices_adjusted WHERE symbol = %s AND date >= %s AND date <= %s ORDER BY date ASC",
        (symbol, streak_start, scan_date),
    )
    closes = [r["close"] for r in cur.fetchall()]
    if not closes:
        return False

    days_since    = len(closes) - 1
    current_close = closes[-1]
    current_pct   = (current_close - pivot_high) / pivot_high * 100

    if current_pct >= 15.0:
        return False

    if days_since >= 5:
        post_bo = closes[1:]
        if post_bo:
            min_val        = min(post_bo)
            min_idx        = max(i for i, c in enumerate(post_bo) if c == min_val)
            days_since_low = (len(post_bo) - 1) - min_idx
            pct_above_low  = (current_close - min_val) / min_val * 100
            if days_since_low < 2 or pct_above_low < 1.0:
                return False

    return True


# ── Scoring ────────────────────────────────────────────────────────────────────

def _raw_score(rs_rank, avg_vol_10d, sector_composite):
    """3-factor conviction score (max 9). rs_score_20 and sector_rs_rank
    components removed 2026-07-10 — both confirmed dead per S-002
    (no significant relationship with forward returns, corrected BREAKOUT V2
    population). See PRE_BREAKOUT_Specification_v1.0.md Session Summary."""
    s = 0
    if rs_rank:
        if 101 <= rs_rank <= 150:   s += 3
        elif 51 <= rs_rank <= 100:  s += 2
        elif 151 <= rs_rank <= 200: s += 1

    if avg_vol_10d:
        if avg_vol_10d > 3_000_000:   s += 3
        elif avg_vol_10d > 1_500_000: s += 2
        elif avg_vol_10d > 500_000:   s += 1

    if sector_composite:
        if sector_composite >= 0.60:   s += 3
        elif sector_composite >= 0.47: s += 2
        elif sector_composite >= 0.30: s += 1

    return s


def _compute_penalty(row_dict, setup_type, n_sectors=23):
    """
    Penalty system (Option 3). Subtracts from raw_score; negatives = bonus.
    Returns (penalty_int, flag_str_or_None).

    n_sectors is the count of sectors ranked by sector_signals for the scan
    date -- the live denominator for the "sector N/M" flag text. Defaults to
    23 (the long-standing hard-coded value) only when a caller can't supply it.

    Rules:
      -3  sector rank > 12 (bottom half of all sectors)
      -4  vol rejection candle at pivot in last 10 days
      -3  nearest overhead < 3% above pivot (immediate ceiling)
      -2  RS50 > +10 (stock already extended on medium term)
      -3  rank_change < -20 (losing RS while sector runs — laggard trap)
      -2  BREAKOUT only: vol ratio < 1.5x (breakout on thin volume)
      +2  sector rs_inflection = 1 (sector just turned — bonus)
    """
    penalty = 0
    flags = []

    sector_rank      = row_dict.get('sector_rank')
    vol_rejection    = row_dict.get('vol_rejection_flag', 0)
    overhead_pct     = row_dict.get('nearest_overhead_pct')
    rs_score_50      = row_dict.get('rs_score_50')
    rank_change      = row_dict.get('rank_change')
    rs_inflection    = row_dict.get('rs_inflection', 0)
    vol_ratio        = row_dict.get('vol_ratio_today')

    if sector_rank and sector_rank > 12:
        penalty += 3
        flags.append(f"sector {sector_rank}/{n_sectors}")

    if vol_rejection:
        penalty += 4
        flags.append("vol rejection at pivot")

    if overhead_pct is not None and overhead_pct < 3:
        penalty += 3
        flags.append(f"overhead {overhead_pct:.1f}% above pivot")

    if rs_score_50 is not None and rs_score_50 > 10:
        penalty += 2
        flags.append(f"RS50 +{rs_score_50:.1f} extended")

    if rank_change is not None and rank_change < -20:
        penalty += 3
        flags.append(f"rank_change {rank_change}")

    if rs_inflection:
        penalty -= 2  # bonus

    if setup_type == 'BREAKOUT' and vol_ratio is not None and vol_ratio < 1.5:
        penalty += 2
        flags.append(f"thin vol {vol_ratio:.1f}x")

    flag_str = "; ".join(flags) if flags else None
    return penalty, flag_str


def _build_key_reason(row_dict, setup_type, n_sectors=23):
    """One-line human-readable reason why this pick was selected.

    n_sectors: count of sectors ranked by sector_signals for the scan date
    (see _compute_penalty). Defaults to 23 only when unavailable.
    """
    parts = []

    if row_dict.get('rs_inflection'):
        parts.append(f"sector inflecting (rank {row_dict.get('sector_rank')}/{n_sectors})")

    rs20 = row_dict.get('rs_score_20')
    if rs20 is not None:
        if rs20 < -2:
            parts.append(f"RS20 deeply rested ({rs20:.1f})")
        elif rs20 < 0:
            parts.append("RS20 cooling")

    vr = row_dict.get('vol_ratio_today')
    if vr and vr > 2:
        parts.append(f"vol {vr:.1f}x today")
    elif vr and setup_type == 'BREAKOUT' and vr >= 1.5:
        parts.append(f"breakout vol {vr:.1f}x")

    if row_dict.get('nearest_overhead_pct') is None:
        parts.append("clean overhead")

    rc = row_dict.get('rank_change')
    if rc and rc > 30:
        parts.append(f"RS accelerating (+{rc})")

    return "; ".join(parts[:3]) if parts else "meets all criteria"


# ── Post-breakout health filter ───────────────────────────────────────────────

def _breakout_health_check(con, symbol, scan_date, pivot_high):
    """
    Two-rule filter for active breakouts.

    Rule 1 (all ages): drop if current close >= 15% above pivot_high (extended).
    Rule 2 (days_since >= 5 only): require BOTH
        - the lowest post-breakout close occurred >= 2 trading days ago, AND
        - today's close is >= 1% above that low (not stale / retested cleanly).
    Returns True if symbol passes both rules and should be kept.
    """
    last_zero = con.execute(
        "SELECT MAX(date) FROM stock_signals WHERE symbol = ? AND bos_flag = 0 AND date <= ?",
        (symbol, scan_date),
    ).fetchone()[0]
    if last_zero is None:
        streak_start = con.execute(
            "SELECT MIN(date) FROM stock_signals WHERE symbol = ?", (symbol,)
        ).fetchone()[0]
    else:
        streak_start = con.execute(
            "SELECT MIN(date) FROM stock_signals WHERE symbol = ? AND date > ? AND bos_flag = 1",
            (symbol, last_zero),
        ).fetchone()[0]

    if streak_start is None:
        return False

    closes = [
        r[0] for r in con.execute(
            "SELECT close FROM prices_adjusted"
            " WHERE symbol = ? AND date >= ? AND date <= ?"
            " ORDER BY date ASC",
            (symbol, streak_start, scan_date),
        ).fetchall()
    ]
    if not closes:
        return False

    days_since    = len(closes) - 1
    current_close = closes[-1]
    current_pct   = (current_close - pivot_high) / pivot_high * 100

    # Rule 1 — extended cutoff
    if current_pct >= 15.0:
        return False

    # Rule 2 — stale / retest check (only when the breakout is 5+ trading days old)
    if days_since >= 5:
        post_bo = closes[1:]  # exclude breakout day itself
        if post_bo:
            min_val      = min(post_bo)
            min_idx      = max(i for i, c in enumerate(post_bo) if c == min_val)
            days_since_low = (len(post_bo) - 1) - min_idx
            pct_above_low  = (current_close - min_val) / min_val * 100
            if days_since_low < 2 or pct_above_low < 1.0:
                return False

    return True


# ── Main scan builder ─────────────────────────────────────────────────────────

def _append_leaders_scan_pg(scan_date=None) -> None:
    """PG-backed equivalent of append_leaders_scan(). Same query/scoring logic,
    psycopg2 RealDictCursor instead of sqlite3.Row, ON CONFLICT instead of
    INSERT OR REPLACE. Assumes leaders_scan already exists in Supabase with
    the same schema/UNIQUE(scan_date, setup_type, symbol) constraint as
    SQLite (migrated once via migrate_to_supabase.py) — no DDL run here."""
    import psycopg2.extras
    from database_pg import get_conn

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if scan_date is None:
            cur.execute("SELECT MAX(date) AS d FROM stock_signals")
            scan_date = cur.fetchone()["d"]
        if not scan_date:
            print("Leaders scan hook (PG): no data in stock_signals.")
            return
        # stock_signals.date is a native DATE column (psycopg2 returns a
        # date object); leaders_scan.scan_date is TEXT — normalize to a
        # plain ISO string so it compares/writes correctly against both.
        scan_date = str(scan_date)

        cur.execute("DELETE FROM leaders_scan WHERE scan_date = %s", (scan_date,))

        cur.execute(
            "SELECT sector, composite_score, rs_inflection, rs_rank AS sector_rank_today "
            "FROM sector_signals WHERE date = %s", (scan_date,)
        )
        sec_rows = cur.fetchall()
        sec_composite  = {r["sector"]: r["composite_score"] for r in sec_rows}
        sec_inflection = {r["sector"]: r["rs_inflection"] for r in sec_rows}
        sec_rank_today = {r["sector"]: r["sector_rank_today"] for r in sec_rows}
        n_sectors = len(sec_rank_today) or 23

        cur.execute("SELECT symbol, close FROM prices WHERE date = %s", (scan_date,))
        closes = {r["symbol"]: r["close"] for r in cur.fetchall()}

        for setup_type in ("PRE_BREAKOUT", "BREAKOUT"):
            if setup_type == "PRE_BREAKOUT":
                sql = """
                    SELECT ss.symbol, sm.sector,
                           ss.rs_rank, ss.sector_rs_rank, ss.rank_change,
                           ss.rs_score_20, ss.rs_score_50,
                           ss.base_tightness, ss.pivot_high, ss.pivot_distance_pct,
                           ss.avg_vol_10d, ss.vol_contraction
                    FROM stock_signals ss
                    JOIN stock_metadata sm ON ss.symbol = sm.symbol
                    WHERE ss.date = %s
                      AND ss.pivot_distance_pct BETWEEN 0 AND 5
                      AND ss.base_tightness < 7
                      AND ss.avg_vol_10d > 200000
                """
            else:
                sql = """
                    SELECT ss.symbol, sm.sector,
                           ss.rs_rank, ss.sector_rs_rank, ss.rank_change,
                           ss.rs_score_20, ss.rs_score_50,
                           ss.base_tightness, ss.pivot_high, ss.pivot_distance_pct,
                           ss.avg_vol_10d
                    FROM stock_signals ss
                    JOIN stock_metadata sm ON ss.symbol = sm.symbol
                    WHERE ss.date = %s
                      -- BOOLEAN in Postgres, INTEGER in SQLite -- see the
                      -- SQLite twin of this query below, and audit §25.
                      AND ss.bos_flag IS TRUE
                      AND ss.pivot_distance_pct < 15
                      AND ss.avg_vol_10d > 200000
                """
            cur.execute(sql, (scan_date,))
            candidates = cur.fetchall()

            insert_rows = []
            for r in candidates:
                sym        = r["symbol"]
                sector     = r["sector"]
                pivot_high = r["pivot_high"]

                if setup_type == "BREAKOUT" and not _breakout_health_check_pg(cur, sym, scan_date, pivot_high):
                    continue

                s_comp   = sec_composite.get(sector, 0.0) or 0.0
                s_infl   = int(sec_inflection.get(sector, 0) or 0)
                sr_today = sec_rank_today.get(sector)

                vol_ratio = _vol_ratio_today_pg(cur, sym, scan_date)
                vol_rej   = _vol_rejection_flag_pg(cur, sym, scan_date, pivot_high)
                overhead  = _nearest_overhead_pct_pg(cur, sym, scan_date, pivot_high)

                if setup_type == "PRE_BREAKOUT":
                    entry  = pivot_high
                    sl     = round(pivot_high * (1 - r["base_tightness"] / 100), 2)
                    sl_pct = round(float(r["base_tightness"]), 2)
                else:
                    entry  = closes.get(sym, pivot_high)
                    sl     = pivot_high
                    sl_pct = round(float(r["pivot_distance_pct"]), 2)

                raw = _raw_score(r["rs_rank"], r["avg_vol_10d"], s_comp)

                pen_dict = {
                    "sector_rank":          sr_today,
                    "vol_rejection_flag":   vol_rej,
                    "nearest_overhead_pct": overhead,
                    "rs_score_50":          r["rs_score_50"],
                    "rank_change":          r["rank_change"],
                    "rs_inflection":        s_infl,
                    "vol_ratio_today":      vol_ratio,
                }
                penalty, flag_str = _compute_penalty(pen_dict, setup_type, n_sectors=n_sectors)
                final_score = raw - penalty

                rs_rank_val  = int(r["rs_rank"]) if r["rs_rank"] is not None else None
                sec_rs_rank  = int(r["sector_rs_rank"]) if r["sector_rs_rank"] is not None else None
                rank_chg_val = int(r["rank_change"]) if r["rank_change"] is not None else None
                vc_val       = float(r["vol_contraction"]) if r.get("vol_contraction") is not None else None

                insert_rows.append((
                    scan_date, setup_type, sym, sector,
                    sr_today, rs_rank_val, sec_rs_rank,
                    r["rs_score_20"], r["rs_score_50"], rank_chg_val,
                    r["base_tightness"], pivot_high, r["pivot_distance_pct"],
                    r["avg_vol_10d"], vol_ratio,
                    entry, sl, sl_pct,
                    s_infl, s_comp,
                    int(vol_rej), overhead, vc_val,
                    raw, penalty, final_score, flag_str,
                ))

            if insert_rows:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO leaders_scan
                    (scan_date, setup_type, symbol, sector,
                     sector_rank, rs_rank, sector_rs_rank,
                     rs_score_20, rs_score_50, rank_change,
                     base_tightness, pivot_high, pivot_distance_pct,
                     avg_vol_10d, vol_ratio_today,
                     entry_trigger, stop_loss, sl_pct,
                     rs_inflection, sector_composite,
                     vol_rejection_flag, nearest_overhead_pct, vol_contraction,
                     raw_score, penalty, final_score, flag)
                    VALUES %s
                    ON CONFLICT (scan_date, setup_type, symbol) DO UPDATE SET
                        sector = EXCLUDED.sector,
                        sector_rank = EXCLUDED.sector_rank,
                        rs_rank = EXCLUDED.rs_rank,
                        sector_rs_rank = EXCLUDED.sector_rs_rank,
                        rs_score_20 = EXCLUDED.rs_score_20,
                        rs_score_50 = EXCLUDED.rs_score_50,
                        rank_change = EXCLUDED.rank_change,
                        base_tightness = EXCLUDED.base_tightness,
                        pivot_high = EXCLUDED.pivot_high,
                        pivot_distance_pct = EXCLUDED.pivot_distance_pct,
                        avg_vol_10d = EXCLUDED.avg_vol_10d,
                        vol_ratio_today = EXCLUDED.vol_ratio_today,
                        entry_trigger = EXCLUDED.entry_trigger,
                        stop_loss = EXCLUDED.stop_loss,
                        sl_pct = EXCLUDED.sl_pct,
                        rs_inflection = EXCLUDED.rs_inflection,
                        sector_composite = EXCLUDED.sector_composite,
                        vol_rejection_flag = EXCLUDED.vol_rejection_flag,
                        nearest_overhead_pct = EXCLUDED.nearest_overhead_pct,
                        vol_contraction = EXCLUDED.vol_contraction,
                        raw_score = EXCLUDED.raw_score,
                        penalty = EXCLUDED.penalty,
                        final_score = EXCLUDED.final_score,
                        flag = EXCLUDED.flag
                """, insert_rows)


def append_leaders_scan(db_path=None, scan_date=None):
    """
    Build leaders_scan for today. Pulls stock_signals + sector_signals + prices,
    applies filters (base_tightness<7; not-extended for BO), scores each
    candidate, writes results. Idempotent — safe to re-run same day.
    """
    if _PG_URL:
        _append_leaders_scan_pg(scan_date)
        return

    if db_path is None:
        db_path = config.DB_PATH

    con = sqlite3.connect(db_path)
    ensure_tables(con)

    if scan_date is None:
        scan_date = con.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
    if not scan_date:
        con.close()
        return

    con.execute("DELETE FROM leaders_scan WHERE scan_date = ?", (scan_date,))
    con.commit()

    # Sector snapshot for today
    sec_df = pd.read_sql_query("""
        SELECT sector, composite_score, rs_inflection, rs_rank AS sector_rank_today
        FROM sector_signals WHERE date = ?
    """, con, params=(scan_date,))
    sec_composite  = dict(zip(sec_df['sector'], sec_df['composite_score']))
    sec_inflection = dict(zip(sec_df['sector'], sec_df['rs_inflection']))
    sec_rank_today = dict(zip(sec_df['sector'], sec_df['sector_rank_today']))
    n_sectors = len(sec_rank_today) or 23

    # Today's close prices (needed for breakout entry trigger)
    closes = dict(con.execute(
        "SELECT symbol, close FROM prices WHERE date = ?", (scan_date,)
    ).fetchall())

    for setup_type in ('PRE_BREAKOUT', 'BREAKOUT'):
        if setup_type == 'PRE_BREAKOUT':
            sql = """
                SELECT ss.symbol, sm.sector,
                       ss.rs_rank, ss.sector_rs_rank, ss.rank_change,
                       ss.rs_score_20, ss.rs_score_50,
                       ss.base_tightness, ss.pivot_high, ss.pivot_distance_pct,
                       ss.avg_vol_10d, ss.vol_contraction
                FROM stock_signals ss
                JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.pivot_distance_pct BETWEEN 0 AND 5
                  AND ss.base_tightness < 7
                  AND ss.avg_vol_10d > 200000
            """
        else:
            sql = """
                SELECT ss.symbol, sm.sector,
                       ss.rs_rank, ss.sector_rs_rank, ss.rank_change,
                       ss.rs_score_20, ss.rs_score_50,
                       ss.base_tightness, ss.pivot_high, ss.pivot_distance_pct,
                       ss.avg_vol_10d
                FROM stock_signals ss
                JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.bos_flag = 1
                  AND ss.pivot_distance_pct < 15
                  AND ss.avg_vol_10d > 200000
            """

        df = pd.read_sql_query(sql, con, params=(scan_date,))

        insert_rows = []
        for _, r in df.iterrows():
            sym        = r['symbol']
            sector     = r['sector']
            pivot_high = r['pivot_high']

            # Post-breakout health filter: skip extended or stale breakouts
            if setup_type == 'BREAKOUT' and not _breakout_health_check(con, sym, scan_date, pivot_high):
                continue

            s_comp  = sec_composite.get(sector, 0.0)
            s_infl  = int(sec_inflection.get(sector, 0))
            sr_today = sec_rank_today.get(sector)

            vol_ratio   = _vol_ratio_today(con, sym, scan_date)
            vol_rej     = _vol_rejection_flag(con, sym, scan_date, pivot_high)
            overhead    = _nearest_overhead_pct(con, sym, scan_date, pivot_high)

            if setup_type == 'PRE_BREAKOUT':
                entry  = pivot_high
                sl     = round(pivot_high * (1 - r['base_tightness'] / 100), 2)
                sl_pct = round(float(r['base_tightness']), 2)
            else:
                entry  = closes.get(sym, pivot_high)
                sl     = pivot_high
                sl_pct = round(float(r['pivot_distance_pct']), 2)

            raw = _raw_score(
                r['rs_rank'], r['avg_vol_10d'], s_comp
            )

            pen_dict = {
                'sector_rank':         sr_today,
                'vol_rejection_flag':  vol_rej,
                'nearest_overhead_pct': overhead,
                'rs_score_50':         r['rs_score_50'],
                'rank_change':         r['rank_change'],
                'rs_inflection':       s_infl,
                'vol_ratio_today':     vol_ratio,
            }
            penalty, flag_str = _compute_penalty(pen_dict, setup_type, n_sectors=n_sectors)
            final_score = raw - penalty

            rs_rank_val    = int(r['rs_rank'])    if pd.notna(r['rs_rank'])    else None
            sec_rs_rank    = int(r['sector_rs_rank']) if pd.notna(r['sector_rs_rank']) else None
            rank_chg_val   = int(r['rank_change']) if pd.notna(r['rank_change']) else None
            vc_val         = float(r['vol_contraction']) if 'vol_contraction' in r.index and pd.notna(r.get('vol_contraction')) else None

            insert_rows.append((
                scan_date, setup_type, sym, sector,
                sr_today, rs_rank_val, sec_rs_rank,
                r['rs_score_20'], r['rs_score_50'], rank_chg_val,
                r['base_tightness'], pivot_high, r['pivot_distance_pct'],
                r['avg_vol_10d'], vol_ratio,
                entry, sl, sl_pct,
                s_infl, s_comp,
                int(vol_rej), overhead, vc_val,
                raw, penalty, final_score, flag_str
            ))

        if insert_rows:
            con.executemany("""
                INSERT OR REPLACE INTO leaders_scan
                (scan_date, setup_type, symbol, sector,
                 sector_rank, rs_rank, sector_rs_rank,
                 rs_score_20, rs_score_50, rank_change,
                 base_tightness, pivot_high, pivot_distance_pct,
                 avg_vol_10d, vol_ratio_today,
                 entry_trigger, stop_loss, sl_pct,
                 rs_inflection, sector_composite,
                 vol_rejection_flag, nearest_overhead_pct, vol_contraction,
                 raw_score, penalty, final_score, flag)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, insert_rows)
            con.commit()

    con.close()


# ── Top picks writer ──────────────────────────────────────────────────────────

def _save_top_picks_pg() -> None:
    """PG-backed equivalent of save_top_picks(). Same selection logic, ON
    CONFLICT instead of INSERT OR REPLACE. Assumes leaders_top_picks already
    exists in Supabase with UNIQUE(scan_date, setup_type, rank) (migrated
    once via migrate_to_supabase.py) — no DDL run here."""
    import psycopg2.extras
    from database_pg import get_conn

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT MAX(scan_date) AS d FROM leaders_scan")
        scan_date = cur.fetchone()["d"]
        if not scan_date:
            return

        cur.execute("DELETE FROM leaders_top_picks WHERE scan_date = %s", (scan_date,))

        cur.execute(
            "SELECT COUNT(*) AS n FROM sector_signals WHERE date = %s", (scan_date,)
        )
        n_sectors = (cur.fetchone()["n"] or 0) or 23

        for setup_type in ("PRE_BREAKOUT", "BREAKOUT"):
            cur.execute("""
                SELECT * FROM leaders_scan
                WHERE scan_date = %s AND setup_type = %s AND final_score >= %s
                ORDER BY final_score DESC, vol_ratio_today DESC NULLS LAST
                LIMIT 3
            """, (scan_date, setup_type, MIN_PICK_SCORE))

            for rank_idx, r in enumerate(cur.fetchall(), start=1):
                key_reason = _build_key_reason(dict(r), setup_type, n_sectors=n_sectors)

                triggered    = 1 if setup_type == "BREAKOUT" else None
                trigger_date = scan_date if setup_type == "BREAKOUT" else None

                cur.execute("""
                    INSERT INTO leaders_top_picks
                    (scan_date, setup_type, rank, symbol, sector, sector_rank,
                     entry_trigger, stop_loss, sl_pct, vol_ratio_today,
                     key_reason, flag, triggered, trigger_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (scan_date, setup_type, rank) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        sector = EXCLUDED.sector,
                        sector_rank = EXCLUDED.sector_rank,
                        entry_trigger = EXCLUDED.entry_trigger,
                        stop_loss = EXCLUDED.stop_loss,
                        sl_pct = EXCLUDED.sl_pct,
                        vol_ratio_today = EXCLUDED.vol_ratio_today,
                        key_reason = EXCLUDED.key_reason,
                        flag = EXCLUDED.flag,
                        triggered = EXCLUDED.triggered,
                        trigger_date = EXCLUDED.trigger_date
                """, (
                    scan_date, setup_type, rank_idx,
                    r["symbol"], r["sector"], r["sector_rank"],
                    r["entry_trigger"], r["stop_loss"], r["sl_pct"],
                    r["vol_ratio_today"], key_reason, r["flag"],
                    triggered, trigger_date,
                ))


def save_top_picks(db_path=None):
    """
    From today's leaders_scan, select up to top 3 per setup_type (final_score >= MIN_PICK_SCORE)
    and write to leaders_top_picks. If fewer than 3 qualify, write only those that do.
    If none qualify, nothing is written — this is intentional.
    """
    if _PG_URL:
        _save_top_picks_pg()
        return

    if db_path is None:
        db_path = config.DB_PATH

    con = sqlite3.connect(db_path)
    scan_date = con.execute("SELECT MAX(scan_date) FROM leaders_scan").fetchone()[0]
    if not scan_date:
        con.close()
        return

    con.execute("DELETE FROM leaders_top_picks WHERE scan_date = ?", (scan_date,))
    con.commit()

    n_sectors = con.execute(
        "SELECT COUNT(*) FROM sector_signals WHERE date = ?", (scan_date,)
    ).fetchone()[0] or 23

    for setup_type in ('PRE_BREAKOUT', 'BREAKOUT'):
        df = pd.read_sql_query("""
            SELECT * FROM leaders_scan
            WHERE scan_date = ? AND setup_type = ? AND final_score >= ?
            ORDER BY final_score DESC, vol_ratio_today DESC NULLS LAST
            LIMIT 3
        """, con, params=(scan_date, setup_type, MIN_PICK_SCORE))

        for rank_idx, (_, row) in enumerate(df.iterrows(), start=1):
            r = row.to_dict()
            key_reason = _build_key_reason(r, setup_type, n_sectors=n_sectors)

            # Breakouts are already triggered on scan day
            triggered    = 1 if setup_type == 'BREAKOUT' else None
            trigger_date = scan_date if setup_type == 'BREAKOUT' else None

            con.execute("""
                INSERT OR REPLACE INTO leaders_top_picks
                (scan_date, setup_type, rank, symbol, sector, sector_rank,
                 entry_trigger, stop_loss, sl_pct, vol_ratio_today,
                 key_reason, flag, triggered, trigger_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_date, setup_type, rank_idx,
                r['symbol'], r['sector'], r['sector_rank'],
                r['entry_trigger'], r['stop_loss'], r['sl_pct'],
                r['vol_ratio_today'], key_reason, r['flag'],
                triggered, trigger_date
            ))

    con.commit()
    con.close()


# ── Forward return filler ─────────────────────────────────────────────────────

def _fill_leaders_forward_returns_pg() -> None:
    """PG-backed equivalent of fill_leaders_forward_returns(). Same logic,
    %s placeholders, CURRENT_DATE instead of date('now', ...)."""
    import psycopg2.extras
    from database_pg import get_conn

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # leaders_top_picks.scan_date is TEXT (ISO 'YYYY-MM-DD'), but
        # CURRENT_DATE - INTERVAL yields a timestamp -- raises "operator
        # does not exist: text < timestamp without time zone" without the
        # cast. Same bug/fix shape already applied in dashboard_pg.py's
        # E10.5 batch C (see its comment at line ~824): the extra ::date
        # strips the time component so the cutoff round-trips to a plain
        # 'YYYY-MM-DD' string matching what scan_date already holds,
        # rather than relying on fragile lexicographic prefix comparison.
        cur.execute("""
            SELECT id, scan_date, setup_type, symbol, entry_trigger,
                   triggered, trigger_date, fwd_return_20d, outcome_label
            FROM leaders_top_picks
            WHERE outcome_label IN ('OPEN', 'NOT_TRIGGERED')
              AND scan_date < (CURRENT_DATE - INTERVAL '4 days')::date::text
        """)
        picks = cur.fetchall()

        for pick in picks:
            pid        = pick["id"]
            sym        = pick["symbol"]
            scan_date  = pick["scan_date"]
            entry      = pick["entry_trigger"]
            setup_type = pick["setup_type"]

            cur.execute("""
                SELECT date, close FROM prices
                WHERE symbol = %s AND date > %s
                ORDER BY date ASC LIMIT 25
            """, (sym, scan_date))
            fwd = cur.fetchall()
            if not fwd:
                continue

            triggered    = pick["triggered"]
            trigger_date = pick["trigger_date"]

            if setup_type == "PRE_BREAKOUT" and not triggered:
                hit = [f for f in fwd if f["close"] >= entry]
                if hit:
                    triggered    = 1
                    # prices.date is a native DATE column; trigger_date is
                    # TEXT — normalize before writing back.
                    trigger_date = str(hit[0]["date"])
                elif len(fwd) >= 20:
                    cur.execute("""
                        UPDATE leaders_top_picks
                        SET triggered=0, outcome_label='NOT_TRIGGERED'
                        WHERE id=%s
                    """, (pid,))
                    continue
                else:
                    continue

            if not triggered:
                continue

            def fwd_ret(n):
                if len(fwd) >= n:
                    return round((fwd[n - 1]["close"] - entry) / entry * 100, 2)
                return None

            r5, r10, r20 = fwd_ret(5), fwd_ret(10), fwd_ret(20)
            if r10 is not None:
                outcome = "WINNER" if r10 > 0 else ("LOSER" if r10 < 0 else "BREAKEVEN")
            else:
                outcome = "OPEN"

            cur.execute("""
                UPDATE leaders_top_picks
                SET triggered=%s, trigger_date=%s,
                    fwd_return_5d=%s, fwd_return_10d=%s, fwd_return_20d=%s,
                    outcome_label=%s
                WHERE id=%s
            """, (triggered, trigger_date, r5, r10, r20, outcome, pid))


def fill_leaders_forward_returns(db_path=None):
    """
    Fill fwd_return_5d/10d/20d and outcome_label for picks whose window has closed.
    Also sets triggered/trigger_date for PRE_BREAKOUT picks.
    Called daily — skips picks already fully labelled.
    """
    if _PG_URL:
        _fill_leaders_forward_returns_pg()
        return

    if db_path is None:
        db_path = config.DB_PATH

    con = sqlite3.connect(db_path)

    picks = pd.read_sql_query("""
        SELECT id, scan_date, setup_type, symbol, entry_trigger,
               triggered, trigger_date, fwd_return_20d, outcome_label
        FROM leaders_top_picks
        WHERE outcome_label IN ('OPEN', 'NOT_TRIGGERED')
          AND scan_date < date('now', '-4 days')
    """, con)

    for _, pick in picks.iterrows():
        pid        = int(pick['id'])
        sym        = pick['symbol']
        scan_date  = pick['scan_date']
        entry      = pick['entry_trigger']
        setup_type = pick['setup_type']

        # Forward prices after scan_date (up to 25 trading sessions)
        fwd = pd.read_sql_query("""
            SELECT date, close FROM prices
            WHERE symbol = ? AND date > ?
            ORDER BY date ASC LIMIT 25
        """, con, params=(sym, scan_date))

        if fwd.empty:
            continue

        triggered    = pick['triggered']
        trigger_date = pick['trigger_date']

        # Determine trigger for PRE_BREAKOUT
        if setup_type == 'PRE_BREAKOUT' and not triggered:
            hit = fwd[fwd['close'] >= entry]
            if not hit.empty:
                triggered    = 1
                trigger_date = hit.iloc[0]['date']
            elif len(fwd) >= 20:
                # 20 sessions passed and never triggered
                con.execute("""
                    UPDATE leaders_top_picks
                    SET triggered=0, outcome_label='NOT_TRIGGERED'
                    WHERE id=?
                """, (pid,))
                continue
            else:
                continue  # window not closed yet

        if not triggered:
            continue

        def fwd_ret(n):
            if len(fwd) >= n:
                return round((fwd.iloc[n - 1]['close'] - entry) / entry * 100, 2)
            return None

        r5  = fwd_ret(5)
        r10 = fwd_ret(10)
        r20 = fwd_ret(20)

        if r10 is not None:
            outcome = 'WINNER' if r10 > 0 else ('LOSER' if r10 < 0 else 'BREAKEVEN')
        else:
            outcome = 'OPEN'

        con.execute("""
            UPDATE leaders_top_picks
            SET triggered=?, trigger_date=?,
                fwd_return_5d=?, fwd_return_10d=?, fwd_return_20d=?,
                outcome_label=?
            WHERE id=?
        """, (triggered, trigger_date, r5, r10, r20, outcome, pid))

    con.commit()
    con.close()


# ── Single entry point for main.py ───────────────────────────────────────────

def _pending_scan_dates(db_path=None):
    """Trading dates with stock_signals but no leaders_scan rows yet.

    Policy is imported, not re-implemented: leaders_scan carried the exact
    same single-date defect as setup_log -- `scan_date = MAX(stock_signals
    .date)` with no loop, so any day the hook missed was lost the moment a
    newer date was written. Sharing one function means the two cannot drift
    apart the way the daily hooks already did once.
    See docs/KIRAN_CLEANUP_AUDIT.md §24, §25.
    """
    from backfill_setup_log import _pending_setup_log_dates

    if _PG_URL:
        import psycopg2.extras
        from database_pg import get_conn
        with get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT MAX(scan_date) AS d FROM leaders_scan")
            last = cur.fetchone()["d"]
            if last:
                cur.execute("SELECT DISTINCT date AS d FROM stock_signals "
                            "WHERE date >= %s ORDER BY date", (last,))
            else:
                cur.execute("SELECT MAX(date) AS d FROM stock_signals")
            dates = [str(r["d"]) for r in cur.fetchall() if r["d"]]
        return _pending_setup_log_dates(dates, str(last) if last else None)

    con = sqlite3.connect(db_path or config.DB_PATH)
    try:
        last = con.execute("SELECT MAX(scan_date) FROM leaders_scan").fetchone()[0]
        if last:
            rows = con.execute("SELECT DISTINCT date FROM stock_signals "
                               "WHERE date >= ? ORDER BY date", (last,)).fetchall()
        else:
            rows = con.execute("SELECT MAX(date) FROM stock_signals").fetchall()
        dates = [r[0] for r in rows if r[0]]
    finally:
        con.close()
    return _pending_setup_log_dates(dates, last)


def run_all(db_path=None) -> dict:
    """Run the leaders-scan chain for every pending date.

    TR-06 Tier 2 (2026-08-24) fix: per-date failures were previously caught
    and reduced to a bare `print()`, with nothing propagated to the caller --
    a date that failed here was indistinguishable, from main.py's heartbeat
    onward, from one that succeeded, because run_all() always returned
    normally regardless of how many dates actually failed. The fix preserves
    the existing intended behaviour exactly (each date is still a
    self-contained DELETE+rebuild, one bad date still cannot corrupt the
    others, processing of the remaining dates still continues rather than
    aborting) -- it only makes the outcome observable, by tracking which
    dates failed and returning that instead of silently discarding it.

    Returns {"dates_eligible": int, "dates_processed": int, "failed_dates": list[str]}.
    """
    pending = _pending_scan_dates(db_path)
    if len(pending) > 1:
        print(f"Leaders scan: backfilling {len(pending)} missing date(s), "
              f"{pending[0]} -> {pending[-1]}.")
    failed_dates = []
    for scan_date in pending:
        # Each date is a self-contained DELETE+rebuild for that scan_date, so
        # one bad date cannot corrupt the others -- and a failure part-way
        # through keeps the dates already written.
        try:
            append_leaders_scan(db_path, scan_date=scan_date)
        except Exception as exc:
            print(f"Leaders scan failed for {scan_date}: {exc}")
            failed_dates.append(scan_date)
    # Top picks and forward returns are whole-table operations, not per-date.
    save_top_picks(db_path)
    fill_leaders_forward_returns(db_path)
    return {
        "dates_eligible": len(pending),
        "dates_processed": len(pending) - len(failed_dates),
        "failed_dates": failed_dates,
    }
