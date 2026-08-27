"""
Auto Price Adjuster — PSX Corporate Actions
============================================
Reads corporate_action_suspects_clean.csv, auto-confirms bonus share events
(DROP_50 / DROP_33 / DROP_25 — unambiguous magnitude signatures), computes
the backward adjustment factor from the observed close_before/close_after
ratio, and applies it to all OHLCV rows for that symbol BEFORE the event date.

DROP_OTHER events are NOT auto-applied — they require manual confirmation
(set review_status = CONFIRMED in the CSV first, then re-run with --all).

--all also merges in any event CONFIRMED via the Data Health dashboard page
that isn't in the CSV (see load_events() docstring) -- this closes a gap
where a full rebuild could silently revert an already-live, human-confirmed
correction (this happened once, MTL 2026-06-22, see docs/DECISIONS.md).
Always use --all for a genuine full rebuild of prices_adjusted; the
bonus-only default mode is intentionally narrower and will skip both
CSV-CONFIRMED and live-table-CONFIRMED rows.

Writes adjusted prices to a NEW TABLE: prices_adjusted
  — raw prices table is NEVER touched.

Usage:
    python apply_price_adjustments.py           # bonus events only
    python apply_price_adjustments.py --all     # bonus + CSV-CONFIRMED + live-table-CONFIRMED

After running, your queries should use prices_adjusted instead of prices.
"""

import sqlite3
import csv
import os
import sys
import argparse
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

BASE    = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, "psx_data.db")
CSV_PATH = os.path.join(BASE, "corporate_action_suspects_clean.csv")

AUTO_CONFIRM_CATS = {"DROP_50", "DROP_33", "DROP_25"}

# Quarantined columns -- see docs/KIRAN_CLEANUP_AUDIT.md §41-42. These hold
# real historical data (2005 -> 2026-07-31) whose producer was never found
# anywhere in this repository's git history (273 revisions, all branches,
# searched). Classification: B -- semantics strongly inferred (hit_circuit_up/
# hit_circuit_down track ~5%/7.5%/10% price-band moves; thin_trading_flag is a
# zero-exception match to high=low), producer unconfirmed. Disposition:
# PRESERVE / QUARANTINE -- do not reconstruct, backfill, or drop. A full
# rebuild (this file's DROP TABLE + CREATE TABLE AS SELECT * FROM prices) was
# empirically confirmed (§42.6, disposable-DB test) to silently destroy these
# columns with no error. The functions below only carry existing values
# forward across a rebuild -- they never compute, infer, or invent one.
QUARANTINED_COLUMNS = ["hit_circuit_up", "hit_circuit_down", "thin_trading_flag"]


def snapshot_quarantined_columns(con) -> tuple[list[str], list[tuple]]:
    """Read whichever of QUARANTINED_COLUMNS currently exist on
    prices_adjusted, keyed by (symbol, date), before a rebuild would
    otherwise destroy them. Returns ([], []) if prices_adjusted doesn't exist
    yet or has none of these columns -- never invents a column that wasn't
    already there."""
    cur = con.cursor()
    has_table = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prices_adjusted'"
    ).fetchone()
    if not has_table:
        return [], []
    existing = {row[1] for row in cur.execute("PRAGMA table_info(prices_adjusted)")}
    present = [c for c in QUARANTINED_COLUMNS if c in existing]
    if not present:
        return [], []
    cols_sql = ", ".join(present)
    rows = cur.execute(f"SELECT symbol, date, {cols_sql} FROM prices_adjusted").fetchall()
    return present, rows


def restore_quarantined_columns(con, present: list[str], rows: list[tuple]) -> int:
    """Re-adds whichever quarantined columns were present before the rebuild
    and restores their exact prior values by (symbol, date) -- a byte-for-byte
    carry-forward, not a recomputation. Rows with no snapshot match (e.g. a
    brand-new date the daily append hook already wrote as 0) are left at the
    column's own NOT NULL DEFAULT 0, unchanged from today's behaviour."""
    if not present:
        return 0
    cur = con.cursor()
    for col in present:
        cur.execute(f"ALTER TABLE prices_adjusted ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
    set_clause = ", ".join(f"{c} = ?" for c in present)
    cur.executemany(
        f"UPDATE prices_adjusted SET {set_clause} WHERE symbol = ? AND date = ?",
        [(*row[2:], row[0], row[1]) for row in rows],
    )
    con.commit()
    return len(rows)


def load_events(apply_all: bool) -> list[dict]:
    """
    Load events to apply from the review CSV, merged with any CONFIRMED
    events in the live corporate_action_suspects table that the CSV doesn't
    already cover.

    Why the merge: corporate_action_suspects_clean.csv is a static snapshot
    from the original bulk categorization exercise. The Data Health dashboard
    page confirms individual suspects directly against the live
    corporate_action_suspects table (and applies them immediately via
    rebuild_symbol_adjusted) -- it does not write back to the CSV. Without
    this merge, a full rebuild reads the CSV only and silently reverts any
    such live-confirmed correction. This happened once already (MTL,
    2026-06-22, confirmed via the dashboard on 2026-06-23) and was caught and
    manually reapplied before it could ship; see docs/DECISIONS.md
    (2026-07-04 entries) for the full account.

    Gated behind apply_all for the same reason CSV-CONFIRMED DROP_OTHER rows
    already are: the default (bonus-only) mode is intentionally a narrower,
    conservative pass.
    """
    events = []
    seen: set[tuple[str, str]] = set()

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat    = row["magnitude_category"]
            status = row["review_status"].strip().upper()

            if cat in AUTO_CONFIRM_CATS:
                events.append(row)
                seen.add((row["symbol"], row["date"]))
            elif apply_all and status == "CONFIRMED":
                events.append(row)
                seen.add((row["symbol"], row["date"]))

    if apply_all and os.path.exists(DB_PATH):
        con = sqlite3.connect(DB_PATH)
        try:
            live_confirmed = con.execute("""
                SELECT symbol, suspect_date, close_before, close_after,
                       confirmed_action, adjustment_factor
                FROM corporate_action_suspects
                WHERE status = 'CONFIRMED'
            """).fetchall()
        finally:
            con.close()

        for symbol, suspect_date, close_before, close_after, confirmed_action, adjustment_factor in live_confirmed:
            key = (symbol, suspect_date)
            if key in seen:
                continue
            events.append({
                "symbol": symbol,
                "date": suspect_date,
                "close_before": str(close_before),
                "close_after": str(close_after),
                "magnitude_category": "LIVE_TABLE_CONFIRMED",
                "confirmed_action": confirmed_action or "",
                "_adjustment_factor_override": adjustment_factor,
            })
            seen.add(key)
            print(f"  [live-table merge] {symbol} {suspect_date} not in CSV -- "
                  f"using confirmed factor={adjustment_factor:.4f} from corporate_action_suspects")

    events.sort(key=lambda r: (r["symbol"], r["date"]))
    return events


def build_adjusted_prices(con, events: list[dict]) -> None:
    cur = con.cursor()

    # ── preserve any quarantined columns before the rebuild destroys them ───
    # See docs/KIRAN_CLEANUP_AUDIT.md §41-42 and QUARANTINED_COLUMNS above.
    q_cols, q_rows = snapshot_quarantined_columns(con)

    # ── create prices_adjusted as a copy of prices ───────────────────────────
    print("Creating prices_adjusted table …")
    cur.execute("DROP TABLE IF EXISTS prices_adjusted")
    cur.execute("""
        CREATE TABLE prices_adjusted AS
        SELECT * FROM prices
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pa_sym_date ON prices_adjusted(symbol, date)")
    con.commit()
    print(f"  Copied {cur.execute('SELECT COUNT(*) FROM prices_adjusted').fetchone()[0]:,} rows")

    restored = restore_quarantined_columns(con, q_cols, q_rows)
    if q_cols:
        print(f"  Restored quarantined columns {q_cols} for {restored:,} rows "
              f"(provenance UNRESOLVED, preserved as-is -- see "
              f"docs/KIRAN_CLEANUP_AUDIT.md §41-42)")

    # ── group events by symbol, sorted chronologically ───────────────────────
    by_symbol = defaultdict(list)
    for ev in events:
        by_symbol[ev["symbol"]].append(ev)

    total_rows_updated = 0
    skipped = 0

    for sym, sym_events in by_symbol.items():
        # Sort events oldest→newest — apply adjustments in reverse chronological
        # order so earlier adjustments compound correctly
        sym_events_sorted = sorted(sym_events, key=lambda r: r["date"])

        for ev in sym_events_sorted:
            ex_date     = ev["date"]
            close_before = float(ev["close_before"])
            close_after  = float(ev["close_after"])
            override    = ev.get("_adjustment_factor_override")

            if override is not None:
                # Live-table event: use the factor actually applied when a human
                # confirmed it via the dashboard, rather than recomputing (the
                # dashboard computes it the same way -- close_after/close_before --
                # but using the stored value avoids any floating-point drift and
                # is the more direct source of truth for what's already live).
                adj = override
            else:
                if close_before == 0:
                    skipped += 1
                    continue
                # Backward adjustment factor: multiply all pre-event prices by this
                adj = close_after / close_before

            cur.execute("""
                UPDATE prices_adjusted
                SET open  = ROUND(open  * ?, 4),
                    high  = ROUND(high  * ?, 4),
                    low   = ROUND(low   * ?, 4),
                    close = ROUND(close * ?, 4)
                WHERE symbol = ? AND date < ?
            """, (adj, adj, adj, adj, sym, ex_date))

            rows_hit = cur.rowcount
            total_rows_updated += rows_hit

            action = ev.get("confirmed_action") or ev.get("likely_action", "")
            print(f"  {sym:10s}  {ex_date}  adj={adj:.4f}  ({close_before:.2f}->{close_after:.2f})  "
                  f"rows={rows_hit:>5}  [{action}]")

        con.commit()

    return total_rows_updated, skipped


def verify(con, events: list[dict]) -> None:
    """Sanity check: close on ex_date in prices_adjusted should equal close_after."""
    cur = con.cursor()
    print("\n-- Verification sample (first 10 events) --")
    for ev in events[:10]:
        row = cur.execute(
            "SELECT close FROM prices_adjusted WHERE symbol=? AND date=?",
            (ev["symbol"], ev["date"])
        ).fetchone()
        adj_close = row[0] if row else "N/A"
        expected  = float(ev["close_after"])
        ok = "OK" if row and abs(adj_close - expected) < 0.01 else "MISMATCH"
        print(f"  {ok}  {ev['symbol']:10s}  {ev['date']}  "
              f"expected={expected:.2f}  got={adj_close}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="Also apply DROP_OTHER rows CONFIRMED in the CSV or the live "
                             "corporate_action_suspects table (e.g. via the Data Health dashboard page)")
    args = parser.parse_args()

    print("=" * 60)
    print("PSX Price Adjuster")
    print(f"Mode: {'bonus + CSV-CONFIRMED + live-table-CONFIRMED' if args.all else 'bonus events only (DROP_50/33/25)'}")
    if not args.all:
        print("WARNING: without --all, any dashboard-confirmed correction (e.g. MTL-style) will be SKIPPED.")
    print("=" * 60)

    events = load_events(apply_all=args.all)
    print(f"\nEvents to apply: {len(events)}")

    from collections import Counter
    for cat, cnt in Counter(e["magnitude_category"] for e in events).items():
        print(f"  {cat:<15} {cnt:>4}")

    if not events:
        print("Nothing to apply. Exiting.")
        return

    con = sqlite3.connect(DB_PATH)

    t0 = datetime.now()
    total_updated, skipped = build_adjusted_prices(con, events)
    elapsed = (datetime.now() - t0).total_seconds()

    verify(con, events)
    con.close()

    print(f"\n{'='*60}")
    print(f"Done in {elapsed:.1f}s")
    print(f"Total price rows adjusted: {total_updated:,}")
    print(f"Events skipped (zero close_before): {skipped}")
    print(f"\nUse prices_adjusted table in your queries going forward.")
    print("prices table is untouched.")
    print("=" * 60)


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 1
# ─────────────────────────────────────────────────────────────────────────────
def ensure_suspects_table(con) -> None:
    """Creates corporate_action_suspects table if it doesn't already exist."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS corporate_action_suspects (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol            TEXT NOT NULL,
            suspect_date      TEXT NOT NULL,
            close_before      REAL,
            close_after       REAL,
            drop_pct          REAL,
            likely_category   TEXT,
            status            TEXT DEFAULT 'PENDING',
            confirmed_action  TEXT,
            adjustment_factor REAL,
            confirmed_at      TEXT,
            notes             TEXT,
            UNIQUE(symbol, suspect_date)
        )
    """)
    con.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Circuit-flag producer, ported from the confirmed source of truth:
# the ml_feature_study project's scripts/compute_circuit_flags.py (a separate
# local research repo, not part of this codebase).
#
# This is a verbatim transcription of that script's band schedule and
# hit_up/hit_down/thin_trading classification formula -- see
# docs/KIRAN_CLEANUP_AUDIT.md §43/§45 for the audited reproduction against
# 1,752,550 historical rows (zero mismatches) that established this formula
# as the confirmed producer. Do NOT edit this formula independently of that
# script; if the producer's schedule ever changes, port the change here too.
# ─────────────────────────────────────────────────────────────────────────────

def circuit_band_pct(date_str: str) -> float:
    """PSX circuit-band schedule by date (regulatory phase-in, researched
    2026-08-03). See the module docstring above for provenance."""
    if date_str < '2020-01-20': return 0.05
    if date_str < '2020-02-04': return 0.055
    if date_str < '2020-02-19': return 0.06
    if date_str < '2020-03-05': return 0.065
    if date_str < '2020-03-20': return 0.07
    if date_str < '2024-05-27': return 0.075
    if date_str < '2024-06-10': return 0.08
    if date_str < '2024-06-24': return 0.085
    if date_str < '2024-07-08': return 0.09
    if date_str < '2024-07-22': return 0.095
    return 0.10


def compute_circuit_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Computes hit_circuit_up / hit_circuit_down / thin_trading_flag for
    every row in df, which must have columns: symbol, date, close, volume,
    high, low, open. df should include one row of lookback per symbol (the
    trading day immediately before the population actually being scored) so
    prior_close is correct for the first in-scope row of each symbol -- the
    caller is responsible for trimming the lookback rows back out of the
    result afterward (see _circuit_flags_for_new_rows below).

    Returns a copy of df with the three flag columns added (0/1 ints).
    Raises if df is missing a required column -- never silently degrades to
    a zeroed result.
    """
    required = {"symbol", "date", "close", "volume", "high", "low", "open"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"compute_circuit_flags: missing required column(s) {missing}")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["prior_close"] = df.groupby("symbol")["close"].shift(1)
    df["band_pct"] = df["date"].map(circuit_band_pct)

    frozen = (df["high"] == df["low"]) & (df["low"] == df["close"]) & (df["volume"] > 0)
    has_prior = df["prior_close"].notna() & (df["prior_close"] > 0)
    band_amt = np.maximum(df["prior_close"] * df["band_pct"], 1.0)
    tolerance = np.maximum(0.05, 0.005 * df["prior_close"])
    move = df["close"] - df["prior_close"]

    hit_up = frozen & has_prior & (move >= (band_amt - tolerance))
    hit_down = frozen & has_prior & (-move >= (band_amt - tolerance))
    conflict = hit_up & hit_down
    if conflict.sum() > 0:
        hit_down = hit_down & ~conflict
    thin_trading = frozen & ~(hit_up | hit_down)

    df["hit_circuit_up"] = hit_up.astype(int)
    df["hit_circuit_down"] = hit_down.astype(int)
    df["thin_trading_flag"] = thin_trading.astype(int)
    return df


def _circuit_flags_for_new_rows(con, symbols: list, min_date: str, expected_count: int) -> pd.DataFrame:
    """Computes circuit flags for the prices_adjusted rows with date >=
    min_date that were just inserted (within the still-open transaction on
    `con`), for exactly the given symbols.

    Pulls one lookback row per symbol (the last close strictly before
    min_date) so prior_close is correct for each symbol's first new row,
    then runs the confirmed producer formula, then trims the lookback rows
    back out. Raises RuntimeError if the result doesn't cover exactly the
    expected population -- callers must not catch this broadly and must not
    commit on failure (fail closed, not a silent zero-fill).
    """
    if not symbols:
        return pd.DataFrame(columns=["symbol", "date", "hit_circuit_up", "hit_circuit_down", "thin_trading_flag"])

    placeholders = ",".join("?" * len(symbols))

    lookback = pd.read_sql_query(
        f"""
        SELECT pa.symbol, pa.date, pa.close, pa.volume, pa.high, pa.low, pa.open
        FROM prices_adjusted pa
        JOIN (
            SELECT symbol, MAX(date) AS date
            FROM prices_adjusted
            WHERE symbol IN ({placeholders}) AND date < ?
            GROUP BY symbol
        ) latest ON pa.symbol = latest.symbol AND pa.date = latest.date
        """,
        con, params=[*symbols, min_date],
    )

    new_rows = pd.read_sql_query(
        f"""
        SELECT symbol, date, close, volume, high, low, open
        FROM prices_adjusted
        WHERE symbol IN ({placeholders}) AND date >= ?
        """,
        con, params=[*symbols, min_date],
    )

    if len(new_rows) != expected_count:
        raise RuntimeError(
            f"circuit-flag computation: expected {expected_count} newly-appended "
            f"rows for the given symbols, found {len(new_rows)} -- refusing to compute"
        )

    combined = pd.concat([lookback, new_rows], ignore_index=True, sort=False)
    scored = compute_circuit_flags(combined)

    result = scored[scored["date"] >= min_date][
        ["symbol", "date", "hit_circuit_up", "hit_circuit_down", "thin_trading_flag"]
    ].reset_index(drop=True)

    if len(result) != expected_count:
        raise RuntimeError(
            f"circuit-flag computation row-count mismatch after scoring: expected "
            f"{expected_count}, got {len(result)} -- refusing to publish"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 2
# ─────────────────────────────────────────────────────────────────────────────
def append_new_prices_adjusted(con) -> int:
    """Copies new raw rows from prices into prices_adjusted, explicitly by
    column name (never SELECT *), and computes hit_circuit_up /
    hit_circuit_down / thin_trading_flag for those rows using the confirmed
    producer formula (see compute_circuit_flags above) instead of leaving
    them at the column default of 0.

    The row insert and the flag computation/write happen inside one
    transaction. If the flag computation raises for any reason, nothing in
    this call is committed -- the raw rows are not appended either, so a
    calculation failure can never leave newly-appended rows silently
    defaulted to 0/0/0 that look like a valid, computed result. The next
    run will simply see the same last-appended date and retry the whole
    range. See docs/KIRAN_CLEANUP_AUDIT.md for the defect this replaces.
    """
    cur = con.cursor()

    last_adjusted = cur.execute(
        "SELECT MAX(date) FROM prices_adjusted"
    ).fetchone()[0]

    count = cur.execute(
        "SELECT COUNT(*) FROM prices WHERE date > ?", (last_adjusted,)
    ).fetchone()[0]

    if count == 0:
        print("prices_adjusted is up to date")
        return 0

    row = cur.execute(
        "SELECT MIN(date), MAX(date) FROM prices WHERE date > ?", (last_adjusted,)
    ).fetchone()
    min_date, max_date = row

    symbols = [r[0] for r in cur.execute(
        "SELECT DISTINCT symbol FROM prices WHERE date > ?", (last_adjusted,)
    ).fetchall()]

    try:
        cur.execute(
            """INSERT INTO prices_adjusted (symbol, date, close, volume, high, low, open)
               SELECT symbol, date, close, volume, high, low, open FROM prices WHERE date > ?""",
            (last_adjusted,)
        )

        flags = _circuit_flags_for_new_rows(con, symbols, min_date, count)

        cur.executemany(
            "UPDATE prices_adjusted SET hit_circuit_up=?, hit_circuit_down=?, "
            "thin_trading_flag=? WHERE symbol=? AND date=?",
            [
                (int(hu), int(hd), int(tt), str(sym), str(dt))
                for sym, dt, hu, hd, tt in flags[
                    ["symbol", "date", "hit_circuit_up", "hit_circuit_down", "thin_trading_flag"]
                ].itertuples(index=False, name=None)
            ],
        )

        # In-transaction verification before commit, same discipline as the
        # §47 historical repair: re-read every newly-written row and confirm
        # it exactly matches what was computed, before publishing it.
        check_df = pd.read_sql_query(
            "SELECT symbol, date, hit_circuit_up, hit_circuit_down, thin_trading_flag "
            "FROM prices_adjusted WHERE date > ?",
            con, params=(last_adjusted,),
        )
        if len(check_df) != count:
            raise RuntimeError(
                f"post-write row count ({len(check_df)}) does not match expected ({count}) -- refusing to commit"
            )
        merged = flags.merge(check_df, on=["symbol", "date"], suffixes=("_expected", "_actual"))
        if len(merged) != count:
            raise RuntimeError(
                f"post-write verification join produced {len(merged)} rows, expected {count} "
                f"-- symbol/date mismatch between computed and written rows, refusing to commit"
            )
        mismatched = merged[
            (merged["hit_circuit_up_expected"] != merged["hit_circuit_up_actual"])
            | (merged["hit_circuit_down_expected"] != merged["hit_circuit_down_actual"])
            | (merged["thin_trading_flag_expected"] != merged["thin_trading_flag_actual"])
        ]
        if len(mismatched) != 0:
            raise RuntimeError(
                f"{len(mismatched)} newly-written row(s) do not match their computed circuit-flag "
                f"values -- refusing to commit"
            )
    except Exception:
        con.rollback()
        raise

    con.commit()

    print(
        f"Appended {count:,} rows for dates {min_date} to {max_date} "
        f"(circuit flags: up={int(flags['hit_circuit_up'].sum())}, "
        f"down={int(flags['hit_circuit_down'].sum())}, "
        f"thin={int(flags['thin_trading_flag'].sum())})"
    )
    return count


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 3
# ─────────────────────────────────────────────────────────────────────────────
def auto_detect_suspects(con) -> int:
    """Scans newly appended prices_adjusted rows for corporate action suspects."""
    cur = con.cursor()

    last_flagged = cur.execute(
        "SELECT MAX(suspect_date) FROM corporate_action_suspects"
    ).fetchone()[0]

    if last_flagged is None:
        # Safety net: scan last 5 trading days worth of data
        scan_from = cur.execute("""
            SELECT date FROM (
                SELECT DISTINCT date FROM prices_adjusted ORDER BY date DESC LIMIT 5
            ) ORDER BY date ASC LIMIT 1
        """).fetchone()
        scan_from = scan_from[0] if scan_from else None
    else:
        scan_from = last_flagged

    if scan_from is None:
        print("No data in prices_adjusted to scan.")
        return 0

    candidates = cur.execute("""
        SELECT pa.symbol, pa.date, pa.close
        FROM prices_adjusted pa
        JOIN stock_metadata sm ON pa.symbol = sm.symbol
        WHERE pa.date > ?
        ORDER BY pa.symbol, pa.date
    """, (scan_from,)).fetchall()

    new_suspects = 0

    for symbol, date, close_after in candidates:
        row = cur.execute("""
            SELECT close FROM prices_adjusted
            WHERE symbol = ? AND date < ?
            ORDER BY date DESC LIMIT 1
        """, (symbol, date)).fetchone()

        if row is None:
            continue

        close_before = row[0]
        if close_before == 0:
            continue

        drop_pct = (close_after - close_before) / close_before * 100

        if drop_pct < -12.0:
            if drop_pct < -40.0:
                category = "DROP_50"
            elif drop_pct < -28.0:
                category = "DROP_33"
            elif drop_pct < -20.0:
                category = "DROP_25"
            else:
                category = "DROP_OTHER"

            cur.execute("""
                INSERT INTO corporate_action_suspects
                    (symbol, suspect_date, close_before, close_after, drop_pct,
                     likely_category, status)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                ON CONFLICT(symbol, suspect_date) DO NOTHING
            """, (symbol, date, close_before, close_after, drop_pct, category))

            if cur.rowcount > 0:
                new_suspects += 1

    con.commit()
    print(f"auto_detect_suspects: {new_suspects} new suspect(s) flagged")
    return new_suspects


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 4
# ─────────────────────────────────────────────────────────────────────────────
def rebuild_symbol_adjusted(con, symbol: str, ex_date: str, adjustment_factor: float) -> int:
    """Applies a single corporate action factor to one symbol's pre-event rows."""
    cur = con.cursor()

    cur.execute("""
        UPDATE prices_adjusted
        SET open  = ROUND(open  * ?, 4),
            high  = ROUND(high  * ?, 4),
            low   = ROUND(low   * ?, 4),
            close = ROUND(close * ?, 4)
        WHERE symbol = ? AND date < ?
    """, (adjustment_factor, adjustment_factor, adjustment_factor, adjustment_factor,
          symbol, ex_date))

    rows_updated = cur.rowcount
    con.commit()

    print(f"{symbol} — {rows_updated:,} rows adjusted "
          f"(factor={adjustment_factor:.4f}, ex_date={ex_date})")
    return rows_updated
