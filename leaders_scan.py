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

import sqlite3
import pandas as pd
import config

# Minimum final_score (raw - penalty) for a pick to be selected.
# Nothing below this threshold appears in leaders_top_picks.
MIN_PICK_SCORE = 8


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


# ── Scoring ────────────────────────────────────────────────────────────────────

def _raw_score(rs_rank, rs_score_20, avg_vol_10d, sector_rs_rank, sector_composite):
    """5-factor conviction score — identical to dashboard.py Pre-Breakout radar."""
    s = 0
    if rs_rank:
        if 101 <= rs_rank <= 150:   s += 3
        elif 51 <= rs_rank <= 100:  s += 2
        elif 151 <= rs_rank <= 200: s += 1

    if rs_score_20 is not None:
        if rs_score_20 < -2:   s += 3
        elif rs_score_20 < 0:  s += 2
        elif rs_score_20 < 2:  s += 1

    if avg_vol_10d:
        if avg_vol_10d > 3_000_000:   s += 3
        elif avg_vol_10d > 1_500_000: s += 2
        elif avg_vol_10d > 500_000:   s += 1

    if sector_rs_rank:
        if sector_rs_rank > 10: s += 3
        elif sector_rs_rank > 5: s += 2
        elif sector_rs_rank > 0: s += 1

    if sector_composite:
        if sector_composite >= 0.60:   s += 3
        elif sector_composite >= 0.47: s += 2
        elif sector_composite >= 0.30: s += 1

    return s


def _compute_penalty(row_dict, setup_type):
    """
    Penalty system (Option 3). Subtracts from raw_score; negatives = bonus.
    Returns (penalty_int, flag_str_or_None).

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
        flags.append(f"sector {sector_rank}/23")

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


def _build_key_reason(row_dict, setup_type):
    """One-line human-readable reason why this pick was selected."""
    parts = []

    if row_dict.get('rs_inflection'):
        parts.append(f"sector inflecting (rank {row_dict.get('sector_rank')}/23)")

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


# ── Main scan builder ─────────────────────────────────────────────────────────

def append_leaders_scan(db_path=None):
    """
    Build leaders_scan for today. Pulls stock_signals + sector_signals + prices,
    applies filters (coiled vol_contraction<85; base_tightness<7; not-extended for BO), scores each
    candidate, writes results. Idempotent — safe to re-run same day.
    """
    if db_path is None:
        db_path = config.DB_PATH

    con = sqlite3.connect(db_path)
    ensure_tables(con)

    scan_date = con.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
    if not scan_date:
        con.close()
        return

    con.execute("DELETE FROM leaders_scan WHERE scan_date = ?", (scan_date,))
    con.commit()

    # Sector snapshot for today
    sec_df = pd.read_sql_query("""
        SELECT sector, composite_score, rs_inflection,
               RANK() OVER (ORDER BY composite_score DESC) AS sector_rank_today
        FROM sector_signals WHERE date = ?
    """, con, params=(scan_date,))
    sec_composite  = dict(zip(sec_df['sector'], sec_df['composite_score']))
    sec_inflection = dict(zip(sec_df['sector'], sec_df['rs_inflection']))
    sec_rank_today = dict(zip(sec_df['sector'], sec_df['sector_rank_today']))

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
                       ss.avg_vol_10d
                FROM stock_signals ss
                JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.pivot_distance_pct BETWEEN 0 AND 5
                  AND ss.base_tightness < 7
                  AND ss.avg_vol_10d > 200000
                  AND (
                      ss.vol_contraction < 85
                      OR ss.pivot_distance_pct < 2
                  )
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
                  AND ss.pivot_distance_pct BETWEEN 0 AND 5
                  AND ss.avg_vol_10d > 200000
            """

        df = pd.read_sql_query(sql, con, params=(scan_date,))

        insert_rows = []
        for _, r in df.iterrows():
            sym        = r['symbol']
            sector     = r['sector']
            pivot_high = r['pivot_high']

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
                r['rs_rank'], r['rs_score_20'], r['avg_vol_10d'],
                r['sector_rs_rank'], s_comp
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
            penalty, flag_str = _compute_penalty(pen_dict, setup_type)
            final_score = raw - penalty

            rs_rank_val    = int(r['rs_rank'])    if pd.notna(r['rs_rank'])    else None
            sec_rs_rank    = int(r['sector_rs_rank']) if pd.notna(r['sector_rs_rank']) else None
            rank_chg_val   = int(r['rank_change']) if pd.notna(r['rank_change']) else None

            insert_rows.append((
                scan_date, setup_type, sym, sector,
                sr_today, rs_rank_val, sec_rs_rank,
                r['rs_score_20'], r['rs_score_50'], rank_chg_val,
                r['base_tightness'], pivot_high, r['pivot_distance_pct'],
                r['avg_vol_10d'], vol_ratio,
                entry, sl, sl_pct,
                s_infl, s_comp,
                int(vol_rej), overhead,
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
                 vol_rejection_flag, nearest_overhead_pct,
                 raw_score, penalty, final_score, flag)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, insert_rows)
            con.commit()

    con.close()


# ── Top picks writer ──────────────────────────────────────────────────────────

def save_top_picks(db_path=None):
    """
    From today's leaders_scan, select up to top 3 per setup_type (final_score >= MIN_PICK_SCORE)
    and write to leaders_top_picks. If fewer than 3 qualify, write only those that do.
    If none qualify, nothing is written — this is intentional.
    """
    if db_path is None:
        db_path = config.DB_PATH

    con = sqlite3.connect(db_path)
    scan_date = con.execute("SELECT MAX(scan_date) FROM leaders_scan").fetchone()[0]
    if not scan_date:
        con.close()
        return

    con.execute("DELETE FROM leaders_top_picks WHERE scan_date = ?", (scan_date,))
    con.commit()

    for setup_type in ('PRE_BREAKOUT', 'BREAKOUT'):
        df = pd.read_sql_query("""
            SELECT * FROM leaders_scan
            WHERE scan_date = ? AND setup_type = ? AND final_score >= ?
            ORDER BY final_score DESC, vol_ratio_today DESC NULLS LAST
            LIMIT 3
        """, con, params=(scan_date, setup_type, MIN_PICK_SCORE))

        for rank_idx, (_, row) in enumerate(df.iterrows(), start=1):
            r = row.to_dict()
            key_reason = _build_key_reason(r, setup_type)

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

def fill_leaders_forward_returns(db_path=None):
    """
    Fill fwd_return_5d/10d/20d and outcome_label for picks whose window has closed.
    Also sets triggered/trigger_date for PRE_BREAKOUT picks.
    Called daily — skips picks already fully labelled.
    """
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

def run_all(db_path=None):
    append_leaders_scan(db_path)
    save_top_picks(db_path)
    fill_leaders_forward_returns(db_path)
