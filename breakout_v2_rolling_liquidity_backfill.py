"""
breakout_v2_rolling_liquidity_backfill.py — Fixes BREAKOUT V2 symbol
eligibility.

Replaces the old static/undocumented 243-symbol population in
stock_signals_breakout_v2_staging with a full-universe run gated by a
ROLLING avg_vol_10d >= 200,000 liquidity check, re-evaluated per (symbol,
date) rather than applied once as a historical membership test. A symbol
enters eligibility whenever its trailing liquidity crosses the floor, and
drops out again if it declines below it -- no symbol list is hard-coded
anywhere, so this cannot silently go stale the way the old 243-symbol
snapshot did.

Does NOT modify compute_breakout_events() -- imported verbatim from
breakout_events_v2.py and called exactly as before, over each symbol's full
contiguous prices_adjusted history (unchanged input construction). This
script only changes WHICH (symbol, date) rows of that function's own output
get exposed in the staging table -- not how any individual day's
active_resistance / breakout_event state is computed.

Universe: stock_metadata WHERE is_active = 1, intersected with symbols
present in stock_signals. NOTE: this is 305 symbols, not the 309 the task
anticipated (313 - 4 delisted) -- see the DELISTED cross-check section below;
4 MORE delisted symbols (FFBL, META, PIAA, PSMC) were, contrary to
expectation, already present in the OLD 243-symbol population. Flagged, not
silently corrected to match the anticipated number.

Eligibility per row: the most recent stock_signals.avg_vol_10d value for
that symbol at or before that date is >= 200,000 (existing column/
calculation, reused verbatim -- no new liquidity formula). If no
stock_signals row exists yet at or before that date, not eligible (no basis
to judge liquidity).

Writes to a NEW staging table (stock_signals_breakout_v2_staging_full). The
original stock_signals_breakout_v2_staging (243-symbol snapshot) is left
untouched -- pre_breakout_v2_staging was already built against it and is
paused for review; this task does not touch or invalidate that chain.
"""

import sqlite3
import bisect
from pathlib import Path
from collections import Counter

from breakout_events_v2 import compute_breakout_events

DB = str(Path(__file__).parent / "psx_data.db")
OUT_STAGING = "stock_signals_breakout_v2_staging_full"
OLD_STAGING = "stock_signals_breakout_v2_staging"
LIQUIDITY_FLOOR = 200000


def log(msg):
    print(msg, flush=True)


def build_universe(con):
    cur = con.cursor()
    ss_symbols = set(r[0] for r in cur.execute("SELECT DISTINCT symbol FROM stock_signals").fetchall())
    meta = {r[0]: r for r in cur.execute(
        "SELECT symbol, is_active, delisting_date FROM stock_metadata"
    ).fetchall()}

    universe = sorted(s for s in ss_symbols if meta.get(s, (None, 0, None))[1] == 1)
    delisted_in_ss = sorted(s for s in ss_symbols if meta.get(s, (None, 1, None))[1] == 0)
    no_metadata = sorted(s for s in ss_symbols if s not in meta)

    log(f"stock_signals distinct symbols: {len(ss_symbols)}")
    log(f"  is_active=1 (new universe): {len(universe)}")
    log(f"  is_active=0 (delisted, excluded from universe entirely): {len(delisted_in_ss)}  "
        f"-> {delisted_in_ss}")
    if no_metadata:
        log(f"  no stock_metadata row at all (excluded, flagged): {no_metadata}")

    old_bo = set(r[0] for r in cur.execute(
        f"SELECT DISTINCT symbol FROM {OLD_STAGING}").fetchall())
    delisted_previously_included = sorted(s for s in delisted_in_ss if s in old_bo)
    delisted_previously_excluded = sorted(s for s in delisted_in_ss if s not in old_bo)
    log(f"\nCross-check vs the OLD 243-symbol population:")
    log(f"  delisted symbols that were ALREADY excluded from the old 243 (expected, "
        f"per prior Check 1): {delisted_previously_excluded}")
    log(f"  delisted symbols that were INCLUDED in the old 243 despite being delisted "
        f"(new finding, not anticipated by the task's '313-4=309' framing): "
        f"{delisted_previously_included}")

    return universe, delisted_in_ss


def load_avg_vol_series(con, symbols):
    cur = con.cursor()
    series = {}
    rows = cur.execute(
        f"SELECT symbol, date, avg_vol_10d FROM stock_signals "
        f"WHERE symbol IN ({','.join('?' * len(symbols))}) AND avg_vol_10d IS NOT NULL "
        f"ORDER BY symbol, date",
        list(symbols),
    ).fetchall()
    for sym, date, vol in rows:
        series.setdefault(sym, ([], []))
        series[sym][0].append(date)
        series[sym][1].append(vol)
    return series


def load_prices(con, symbol):
    cur = con.cursor()
    return cur.execute(
        "SELECT date, close, high FROM prices_adjusted WHERE symbol = ? ORDER BY date",
        (symbol,),
    ).fetchall()


def ensure_staging_table(con):
    con.execute(f"DROP TABLE IF EXISTS {OUT_STAGING}")
    con.execute(f"""
        CREATE TABLE {OUT_STAGING} (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            active_resistance REAL,
            breakout_event INTEGER,
            avg_vol_10d_asof REAL,
            PRIMARY KEY (symbol, date)
        )
    """)
    con.commit()


def run(con, universe, vol_series):
    cur = con.cursor()
    per_symbol_stats = {}
    total_rows_computed = 0
    total_rows_eligible = 0
    total_events_eligible = 0

    for symbol in universe:
        prices = load_prices(con, symbol)
        if not prices:
            per_symbol_stats[symbol] = dict(computed=0, eligible=0, first_eligible=None,
                                             last_eligible=None, events=0)
            continue

        results = compute_breakout_events(prices)  # UNCHANGED function, unchanged input
        total_rows_computed += len(results)

        dates, vols = vol_series.get(symbol, ([], []))

        insert_rows = []
        n_events = 0
        first_elig = last_elig = None
        for r in results:
            d = r["date"]
            pos = bisect.bisect_right(dates, d) - 1
            if pos < 0:
                continue  # no avg_vol_10d known yet as of this date -> not eligible
            vol_asof = vols[pos]
            if vol_asof is None or vol_asof < LIQUIDITY_FLOOR:
                continue
            insert_rows.append((symbol, d, r["close"], r["active_resistance"],
                                 r["breakout_event"], vol_asof))
            if first_elig is None:
                first_elig = d
            last_elig = d
            n_events += r["breakout_event"]

        cur.executemany(
            f"INSERT OR REPLACE INTO {OUT_STAGING} "
            f"(symbol, date, close, active_resistance, breakout_event, avg_vol_10d_asof) "
            f"VALUES (?,?,?,?,?,?)",
            insert_rows,
        )
        total_rows_eligible += len(insert_rows)
        total_events_eligible += n_events
        per_symbol_stats[symbol] = dict(
            computed=len(results), eligible=len(insert_rows),
            first_eligible=first_elig, last_eligible=last_elig, events=n_events,
        )

    con.commit()
    return per_symbol_stats, total_rows_computed, total_rows_eligible, total_events_eligible


def validate(con, sample_symbols):
    """Re-run the Phase 4 self-consistency stale-check: recompute breakout_event
    from the stored (active_resistance, close) sequence and confirm 0 mismatches
    against the stored breakout_event column -- for the WHOLE new table, then
    print a per-row detail sample for the newly-added symbols specifically."""
    cur = con.cursor()
    rows = cur.execute(
        f"SELECT symbol, date, close, active_resistance, breakout_event "
        f"FROM {OUT_STAGING} ORDER BY symbol, date"
    ).fetchall()

    mismatches = 0
    by_symbol_prev_resistance = {}
    by_symbol_broken_state = {}
    for symbol, date, close, ar, ev in rows:
        prev_ar = by_symbol_prev_resistance.get(symbol)
        broken = by_symbol_broken_state.get(symbol, False)
        if ar is not None and ar != prev_ar:
            broken = False
        recomputed_ev = 0
        if ar is not None and close is not None:
            if close > ar:
                if not broken:
                    recomputed_ev = 1
                    broken = True
            else:
                broken = False
        if recomputed_ev != ev:
            mismatches += 1
        by_symbol_prev_resistance[symbol] = ar
        by_symbol_broken_state[symbol] = broken

    log(f"\nVALIDATION (whole new table, {len(rows):,} rows): "
        f"{mismatches:,} state-machine mismatches -- expected 0.")
    log("  NOTE: since this table's rows are drawn directly from compute_breakout_events()'s "
        "own unmodified output (just filtered by eligibility), this validates that the "
        "eligibility filter didn't corrupt row content, not a re-derivation of already_broken "
        "from scratch (that check was done in the PRE_BREAKOUT inventory task and is not "
        "repeated here since compute_breakout_events() itself was not touched).")

    log(f"\nSample detail for newly-added symbols (not in the old 243):")
    for s in sample_symbols:
        srows = cur.execute(
            f"SELECT date, close, active_resistance, breakout_event, avg_vol_10d_asof "
            f"FROM {OUT_STAGING} WHERE symbol = ? ORDER BY date", (s,)
        ).fetchall()
        if not srows:
            log(f"  {s}: 0 eligible rows (never crossed {LIQUIDITY_FLOOR:,} avg_vol_10d)")
            continue
        n_events = sum(r[3] for r in srows)
        log(f"  {s}: {len(srows)} eligible rows, {n_events} breakout_event=1 rows, "
            f"first eligible {srows[0][0]} (avg_vol_10d_asof={srows[0][4]:,.0f}), "
            f"last eligible {srows[-1][0]} (avg_vol_10d_asof={srows[-1][4]:,.0f})")


def main():
    con = sqlite3.connect(DB)
    try:
        universe, delisted = build_universe(con)
        vol_series = load_avg_vol_series(con, universe)

        ensure_staging_table(con)
        per_symbol, total_computed, total_eligible, total_events = run(con, universe, vol_series)

        log(f"\n{'='*100}")
        log(f"RESULTS")
        log(f"{'='*100}")
        log(f"Universe processed: {len(universe)} symbols")
        log(f"Total rows computed by compute_breakout_events() (unfiltered, full history): "
            f"{total_computed:,}")
        log(f"Total rows ELIGIBLE (rolling avg_vol_10d >= {LIQUIDITY_FLOOR:,}) and written to "
            f"'{OUT_STAGING}': {total_eligible:,}")
        log(f"Total breakout_event=1 rows among eligible rows: {total_events:,}")

        symbols_with_rows = sorted(s for s, st in per_symbol.items() if st["eligible"] > 0)
        symbols_zero_rows = sorted(s for s, st in per_symbol.items() if st["eligible"] == 0)
        log(f"\nSymbols with >=1 eligible row: {len(symbols_with_rows)}")
        log(f"Symbols with 0 eligible rows (never crossed {LIQUIDITY_FLOOR:,} as of any date "
            f"with stock_signals coverage): {len(symbols_zero_rows)} -> {symbols_zero_rows}")

        # Before/after comparison
        cur = con.cursor()
        old_rows = cur.execute(f"SELECT COUNT(*) FROM {OLD_STAGING}").fetchone()[0]
        old_symbols = cur.execute(f"SELECT COUNT(DISTINCT symbol) FROM {OLD_STAGING}").fetchone()[0]
        log(f"\n{'='*100}")
        log(f"BEFORE / AFTER")
        log(f"{'='*100}")
        log(f"OLD ({OLD_STAGING}, untouched, preserved as-is): {old_symbols} symbols, {old_rows:,} rows")
        log(f"NEW ({OUT_STAGING}): {len(symbols_with_rows)} symbols, {total_eligible:,} rows")

        # newly-added symbols = those with >=1 eligible row now, that were NOT in the old table
        old_bo = set(r[0] for r in cur.execute(f"SELECT DISTINCT symbol FROM {OLD_STAGING}").fetchall())
        newly_added = sorted(set(symbols_with_rows) - old_bo)
        dropped = sorted(old_bo - set(symbols_with_rows))
        log(f"Newly added symbols (0 old rows -> now have eligible rows): {len(newly_added)}")
        log(f"  {newly_added}")
        log(f"Symbols dropped (were in old 243, now 0 eligible rows -- e.g. delisted or "
            f"currently illiquid): {len(dropped)}")
        log(f"  {dropped}")

        # Focus validation on the headline newly-added names from the task + a couple of
        # NEVER_LIQUID/WAS_LIQUID_NOW_NOT names for contrast
        headline = [s for s in ["MSOT", "NESTLE", "COLG", "ABOT", "INDU", "HINOON", "ATLH"]
                    if s in universe]
        validate(con, headline)

    finally:
        con.close()


if __name__ == "__main__":
    main()
