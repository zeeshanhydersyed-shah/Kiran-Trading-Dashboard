"""
prebreakout_v2_inventory.py — PRE_BREAKOUT re-alignment against BREAKOUT V2's
active_resistance / already_broken state (Part A), plus three candidate
relative-tightness measures computed on top of the existing base_tightness
(BBW%) field from stock_signals (Part B), plus a 10-symbol descriptive
comparison (Part C).

READ access:  stock_signals_breakout_v2_staging, stock_signals, stock_metadata
WRITE access: pre_breakout_v2_staging ONLY (new table, created here). No
production table is modified. Idempotent — safe to re-run (DROP+recreate own
table each run).

Reuses base_tightness exactly as computed by stock_signals.py's
_compute_bt_vc() (4*std/mean*100 over a 20-day close window) — this IS the
project's existing BBW%-equivalent measure (confirmed: _prebreakout_diag.py
already labels ss.base_tightness as "BBW%" in its own output). No new BBW%
formula is introduced here.

already_broken is NOT persisted by breakout_events_v2.py's staging table
(only symbol/date/close/active_resistance/breakout_event are stored, despite
the function's docstring documenting an already_broken return value that the
implementation never actually returns — see FLAG in Part A output). This
script re-derives already_broken from the stored (active_resistance,
breakout_event, close) sequence alone, WITHOUT touching breakout_events_v2.py
and WITHOUT re-walking raw prices. The derivation is validated by
reconstructing breakout_event from the derived state and confirming an exact
match against the stored breakout_event column for every row (see
VALIDATION section).
"""

import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

DB = str(Path(__file__).parent / "psx_data.db")
SRC_STAGING = "stock_signals_breakout_v2_staging"
OUT_STAGING = "pre_breakout_v2_staging"

MIN_TRAILING_OBS = 60   # minimum valid trailing bt observations before a
                         # percentile/z-score is computed (below this the
                         # statistic is too noisy to be meaningful) — flagged
                         # explicitly per task constraints, not silently applied.

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)


def log(msg):
    print(msg, flush=True)


# ══════════════════════════════════════════════════════════════════════════
# LOAD
# ══════════════════════════════════════════════════════════════════════════

def load_breakout_staging(con):
    df = pd.read_sql_query(
        f"SELECT symbol, date, close, active_resistance, breakout_event "
        f"FROM {SRC_STAGING} ORDER BY symbol, date",
        con,
    )
    return df


def load_stock_signals_bt(con):
    df = pd.read_sql_query(
        "SELECT symbol, date, base_tightness FROM stock_signals ORDER BY symbol, date",
        con,
    )
    return df


# ══════════════════════════════════════════════════════════════════════════
# PART A — re-derive already_broken and build the PRE_BREAKOUT population
# ══════════════════════════════════════════════════════════════════════════

def derive_already_broken(df):
    """Per symbol, walk the stored (active_resistance, breakout_event, close)
    sequence in date order and derive already_broken AS OF THE MOMENT each
    row's event-test would run (i.e. AFTER that day's Step-1 pivot-supersession
    reset, BEFORE that day's Step-2 fallback/continuation update). This is the
    exact value the original compute_breakout_events() loop checks in its
    `if not already_broken:` test — i.e. this IS the eligibility state that
    determines breakout_event, not a post-hoc approximation.

    NOTE on the alternative ("post-day") reading: breakout_events_v2.py's
    docstring calls already_broken "post-day state", but implementing it that
    way makes it algebraically redundant with close <= active_resistance
    (the fallback-below branch always resets already_broken to False within
    the same day, so post-day already_broken is ALWAYS False whenever
    close <= active_resistance). That reading cannot be what distinguishes
    "genuinely approaching" from "stale post-breakout continuation" as the
    task describes, so this script uses the eligibility-state reading below
    and reports it explicitly rather than silently picking one. Both
    interpretations are validated against the stored breakout_event column.
    """
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    eligibility_broken = np.empty(len(df), dtype=bool)
    postday_broken = np.empty(len(df), dtype=bool)
    recomputed_event = np.empty(len(df), dtype=np.int64)

    for symbol, idx in df.groupby("symbol").groups.items():
        idx = list(idx)
        prev_resistance = None
        broken_state = False
        for i in idx:
            ar = df.at[i, "active_resistance"]
            close = df.at[i, "close"]
            ar_isnull = pd.isna(ar)

            # Step 1: pivot supersession reset (mirrors compute_breakout_events)
            if not ar_isnull and ar != prev_resistance:
                broken_state = False

            elig = broken_state  # <-- state used for the eligibility test / population filter
            eligibility_broken[i] = elig

            # Step 2: mirror the event test to (a) recompute breakout_event
            # for validation and (b) update state for the next iteration.
            ev = 0
            if not ar_isnull and pd.notna(close):
                if close > ar:
                    if not broken_state:
                        ev = 1
                        broken_state = True
                    else:
                        ev = 0
                else:
                    ev = 0
                    broken_state = False
            recomputed_event[i] = ev
            postday_broken[i] = broken_state  # state after today's Step 2

            prev_resistance = ar if not ar_isnull else prev_resistance

    df["already_broken_eligibility"] = eligibility_broken
    df["already_broken_postday"] = postday_broken
    df["breakout_event_recomputed"] = recomputed_event
    return df


def build_population(df):
    """PRE_BREAKOUT population per task spec:
        active_resistance IS NOT NULL
        AND close <= active_resistance
        AND already_broken == False   (eligibility-state reading, see docstring above)
    """
    mask_core = df["active_resistance"].notna() & (df["close"] <= df["active_resistance"])
    pop_elig = df[mask_core & (~df["already_broken_eligibility"])].copy()
    pop_postday = df[mask_core & (~df["already_broken_postday"])].copy()
    return pop_elig, pop_postday, df[mask_core].copy()


def part_a(con):
    log("=" * 100)
    log("PART A — PRE_BREAKOUT population rebuild against active_resistance / already_broken")
    log("=" * 100)

    raw = load_breakout_staging(con)
    log(f"\nLoaded {SRC_STAGING}: {len(raw):,} rows, {raw['symbol'].nunique()} symbols, "
        f"date range {raw['date'].min()} -> {raw['date'].max()}")

    derived = derive_already_broken(raw)

    mismatches = (derived["breakout_event"] != derived["breakout_event_recomputed"]).sum()
    log(f"\nVALIDATION: re-derived breakout_event vs stored breakout_event — "
        f"{mismatches:,} mismatches out of {len(derived):,} rows.")
    if mismatches:
        log("  !! DERIVATION DOES NOT MATCH STORED STATE MACHINE — results below are unreliable "
            "until this is resolved.")
        bad = derived[derived["breakout_event"] != derived["breakout_event_recomputed"]].head(10)
        log(bad[["symbol", "date", "close", "active_resistance", "breakout_event",
                 "breakout_event_recomputed"]].to_string(index=False))
    else:
        log("  OK — derivation exactly reproduces the stored state machine for every row.")

    pop_elig, pop_postday, core = build_population(derived)

    log(f"\nRows with active_resistance NOT NULL AND close <= active_resistance "
        f"(before already_broken filter): {len(core):,}")

    log(f"\n--- Reading 1 (used as primary; see docstring): already_broken = eligibility state "
        f"(post pivot-reset, pre fallback-update) ---")
    log(f"PRE_BREAKOUT population (primary): {len(pop_elig):,} rows, "
        f"{pop_elig['symbol'].nunique()} symbols")

    log(f"\n--- Reading 2 (post-day, as literally named in the docstring) — reported for "
        f"transparency; algebraically near-identical to 'core' above ---")
    log(f"PRE_BREAKOUT population (post-day reading): {len(pop_postday):,} rows, "
        f"{pop_postday['symbol'].nunique()} symbols "
        f"(delta vs core: {len(core) - len(pop_postday):,} rows excluded, "
        f"expected to be ~0 by construction — see docstring)")

    per_sym = pop_elig.groupby("symbol").size()
    log(f"\nPer-symbol row counts (primary population, n={pop_elig['symbol'].nunique()} symbols):")
    log(f"  min={per_sym.min()}  p25={per_sym.quantile(.25):.0f}  median={per_sym.median():.0f}  "
        f"p75={per_sym.quantile(.75):.0f}  max={per_sym.max()}  mean={per_sym.mean():.1f}")
    log(f"  Symbol with min rows: {per_sym.idxmin()} ({per_sym.min()})")
    log(f"  Symbol with max rows: {per_sym.idxmax()} ({per_sym.max()})")

    # Size/shape comparison vs OLD PRE_BREAKOUT population — re-derived fresh, not trusted from memory
    cur = con.cursor()
    old_setup_log_n = cur.execute(
        "SELECT COUNT(*) FROM setup_log WHERE setup_type = 'PRE_BREAKOUT'"
    ).fetchone()[0]
    old_bos_flag0_n = cur.execute(
        "SELECT COUNT(*) FROM stock_signals WHERE bos_flag = 0"
    ).fetchone()[0]
    n_ss_symbols = cur.execute(
        "SELECT COUNT(DISTINCT symbol) FROM stock_signals"
    ).fetchone()[0]

    log(f"\n--- Size/shape comparison vs OLD PRE_BREAKOUT population (fresh counts, not the "
        f"prior inventory's cached numbers) — descriptive only, no verdict ---")
    log(f"  setup_log WHERE setup_type='PRE_BREAKOUT'  (the certified/narrowly-filtered old "
        f"population — pivot_distance_pct 0-3%% AND base_tightness<8 AND avg_vol_10d>200k): "
        f"{old_setup_log_n:,} rows")
    log(f"  stock_signals WHERE bos_flag=0  (broad 'not-yet-broken-out' rows, no narrowing "
        f"filters at all): {old_bos_flag0_n:,} rows")
    log(f"  NEW PRE_BREAKOUT population (this rebuild, no narrowing filters applied yet): "
        f"{len(pop_elig):,} rows")
    log(f"  New population is {len(pop_elig)/old_setup_log_n:.1f}x the certified setup_log count "
        f"and {len(pop_elig)/old_bos_flag0_n:.2f}x the unfiltered bos_flag=0 count.")
    log(f"  NOTE: these are NOT apples-to-apples. The old setup_log population additionally "
        f"required pivot_distance_pct 0-3%%, base_tightness<8, avg_vol_10d>200k — none of those "
        f"narrowing filters are applied here (per task spec, Part A is population + state-machine "
        f"realignment only). The new population is the broad 'currently approaching an unbroken "
        f"resistance' universe; the old setup_log population was already a tightly-gated trade-signal "
        f"subset. Size divergence is expected, not a red flag by itself.")
    log(f"  Symbol coverage: stock_signals has {n_ss_symbols} distinct symbols vs "
        f"{raw['symbol'].nunique()} in {SRC_STAGING} — a {n_ss_symbols - raw['symbol'].nunique()}-symbol "
        f"gap between the two source tables, noted but not investigated here.")

    return pop_elig, derived


# ══════════════════════════════════════════════════════════════════════════
# PART B — three candidate relative-tightness measures
# ══════════════════════════════════════════════════════════════════════════

def compute_candidate_measures(pop, bt_df):
    """For every population row, compute:
      1. pct_rank_252 — percentile rank of today's bt within trailing 252-day bt history (incl. today)
      2. pct_rank_756 — percentile rank of today's bt within trailing 756-day (or full history) bt history
      3. zscore_252   — (today's bt - trailing 252-day mean) / trailing 252-day std (incl. today)

    "Trailing" windows are INCLUSIVE of the current day (today's own bt value
    counts as one of the observations it's ranked/z-scored against) — this is
    a documented methodological choice, not hidden. Rows with fewer than
    MIN_TRAILING_OBS valid bt observations in the window get NULL, and are
    counted separately rather than silently dropped.
    """
    bt_df = bt_df.sort_values(["symbol", "date"]).reset_index(drop=True)
    bt_by_symbol = {
        sym: g[["date", "base_tightness"]].reset_index(drop=True)
        for sym, g in bt_df.groupby("symbol")
    }

    pct_252 = np.full(len(pop), np.nan)
    pct_756 = np.full(len(pop), np.nan)
    z_252 = np.full(len(pop), np.nan)
    today_bt = np.full(len(pop), np.nan)
    n_obs_252 = np.full(len(pop), 0, dtype=np.int64)
    n_obs_756 = np.full(len(pop), 0, dtype=np.int64)

    pop = pop.reset_index(drop=True)
    for sym, idx in pop.groupby("symbol").groups.items():
        series = bt_by_symbol.get(sym)
        if series is None:
            continue
        dates = series["date"].values
        vals = series["base_tightness"].values.astype(float)

        for i in idx:
            d = pop.at[i, "date"]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue  # no stock_signals row for this (symbol, date) — flagged in summary
            v = vals[pos]
            today_bt[i] = v
            if np.isnan(v):
                continue

            w252 = vals[max(0, pos - 251):pos + 1]
            w252 = w252[~np.isnan(w252)]
            n_obs_252[i] = len(w252)
            if len(w252) >= MIN_TRAILING_OBS:
                pct_252[i] = (w252 <= v).mean() * 100
                if len(w252) >= 2:
                    std252 = w252.std(ddof=1)
                    z_252[i] = (v - w252.mean()) / std252 if std252 > 0 else np.nan

            w756 = vals[max(0, pos - 755):pos + 1]
            w756 = w756[~np.isnan(w756)]
            n_obs_756[i] = len(w756)
            if len(w756) >= MIN_TRAILING_OBS:
                pct_756[i] = (w756 <= v).mean() * 100

    out = pop.copy()
    out["bbw_pct"] = today_bt
    out["pct_rank_252"] = pct_252
    out["pct_rank_756"] = pct_756
    out["zscore_252"] = z_252
    out["n_obs_252"] = n_obs_252
    out["n_obs_756"] = n_obs_756
    return out


def part_b(pop, con):
    log("\n" + "=" * 100)
    log("PART B — candidate relative-tightness measures (side by side, none selected as 'the' measure)")
    log("=" * 100)

    bt_df = load_stock_signals_bt(con)
    log(f"\nLoaded stock_signals.base_tightness (existing BBW%% field, reused verbatim): "
        f"{len(bt_df):,} rows, {bt_df['base_tightness'].notna().sum():,} non-null "
        f"({bt_df['base_tightness'].isna().sum():,} null).")
    log("KNOWN EDGE CASE in the existing formula (stock_signals.py _compute_bt_vc, not modified "
        "here): base_tightness is nulled out whenever the 10-day OR 50-day trailing volume window "
        "has any NULL/zero value — even though base_tightness's own formula (4*std/mean*100 over "
        "20-day close) does not use volume at all. This is a real coupling in the existing code "
        "(see stock_signals.py line ~179: 'bt = None  # volume issue nullifies both per spec'), "
        "flagged as-is per instructions, not silently worked around.")
    log("Also: base_tightness requires >=20 days of price history (pos>=19) — stocks with a shorter "
        "runway simply have no value for their first ~20 trading days; this is the ordinary warm-up "
        "gap, not a bug.")

    result = compute_candidate_measures(pop, bt_df)

    n = len(result)
    n_no_ss_row = result["bbw_pct"].isna().sum() - (result["n_obs_252"] == 0).sum() if False else None
    n_missing_bt_join = (result["n_obs_252"] == 0).sum()  # no stock_signals row matched at all, incl. bt-null-at-that-date
    n_bt_null_today = result["bbw_pct"].isna().sum()
    n_below_min_252 = ((result["n_obs_252"] > 0) & (result["n_obs_252"] < MIN_TRAILING_OBS)).sum()
    n_below_min_756 = ((result["n_obs_756"] > 0) & (result["n_obs_756"] < MIN_TRAILING_OBS)).sum()

    log(f"\nPopulation rows: {n:,}")
    log(f"  today's base_tightness (bbw_pct) is NULL for {n_bt_null_today:,} rows "
        f"({n_bt_null_today/n*100:.1f}%%) — either no matching stock_signals row for that "
        f"(symbol,date), or base_tightness itself is NULL there (volume-window edge case above).")
    log(f"  rows with a trailing-252 window that has fewer than MIN_TRAILING_OBS={MIN_TRAILING_OBS} "
        f"valid bt observations (pct_rank_252/zscore_252 left NULL, not silently computed on thin "
        f"data): {n_below_min_252:,}")
    log(f"  same, for the 756-day window: {n_below_min_756:,}")

    log(f"\nSide-by-side summary of the three candidate measures (non-null rows only):")
    desc = result[["bbw_pct", "pct_rank_252", "pct_rank_756", "zscore_252"]].describe(
        percentiles=[.1, .25, .5, .75, .9]
    )
    log(desc.to_string())

    return result


# ══════════════════════════════════════════════════════════════════════════
# PART C — 10-symbol descriptive comparison
# ══════════════════════════════════════════════════════════════════════════

SAMPLE_SYMBOLS = ["ATRL", "GAL", "GHNI", "MEBL", "UBL", "BAFL", "LUCK", "OGDC", "ENGRO", "PSO"]


def part_c(result, con):
    log("\n" + "=" * 100)
    log("PART C — 10-symbol descriptive comparison (own-history BBW%% distribution + candidate agreement)")
    log("=" * 100)

    sectors = pd.read_sql_query(
        f"SELECT symbol, sector FROM stock_metadata WHERE symbol IN "
        f"({','.join('?' for _ in SAMPLE_SYMBOLS)})", con, params=SAMPLE_SYMBOLS
    ).set_index("symbol")["sector"].to_dict()

    log(f"\nSample: {', '.join(SAMPLE_SYMBOLS)}")
    for s in SAMPLE_SYMBOLS:
        log(f"  {s}: {sectors.get(s, '?')}")

    log(f"\n--- 1. Each symbol's OWN base_tightness (BBW%%) distribution shape "
        f"(full history, not just population rows) — illustrates 'different DNA' ---")
    bt_df = load_stock_signals_bt(con)
    rows = []
    for s in SAMPLE_SYMBOLS:
        v = bt_df.loc[bt_df["symbol"] == s, "base_tightness"].dropna()
        if len(v) == 0:
            rows.append([s, sectors.get(s), 0, np.nan, np.nan, np.nan, np.nan, np.nan])
            continue
        rows.append([
            s, sectors.get(s), len(v),
            v.min(), v.quantile(.25), v.median(), v.quantile(.75), v.max(),
        ])
    shape_df = pd.DataFrame(rows, columns=["symbol", "sector", "n", "min", "p25", "median", "p75", "max"])
    log(shape_df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    log(f"\n--- 2. Per-symbol PRE_BREAKOUT population size (this rebuild) ---")
    pop_counts = result[result["symbol"].isin(SAMPLE_SYMBOLS)].groupby("symbol").size()
    for s in SAMPLE_SYMBOLS:
        log(f"  {s}: {int(pop_counts.get(s, 0))} population rows")

    log(f"\n--- 3. Sample dates per symbol: do the 3 candidate measures agree on which days were "
        f"'tight'? (up to 8 rows/symbol, evenly spaced through that symbol's population rows, "
        f"non-null on all 3 measures only) ---")
    for s in SAMPLE_SYMBOLS:
        sub = result[(result["symbol"] == s) &
                     result["pct_rank_252"].notna() &
                     result["pct_rank_756"].notna() &
                     result["zscore_252"].notna()].sort_values("date")
        if len(sub) == 0:
            log(f"\n  {s}: no population rows with all 3 measures non-null (insufficient trailing "
                f"history or base_tightness NULL throughout) — cannot compare.")
            continue
        take = min(8, len(sub))
        sample_idx = np.linspace(0, len(sub) - 1, take).round().astype(int)
        sample_idx = sorted(set(sample_idx))
        picked = sub.iloc[sample_idx][
            ["date", "close", "active_resistance", "bbw_pct", "pct_rank_252", "pct_rank_756", "zscore_252"]
        ].copy()
        picked["pct_rank_252"] = picked["pct_rank_252"].round(1)
        picked["pct_rank_756"] = picked["pct_rank_756"].round(1)
        picked["zscore_252"] = picked["zscore_252"].round(2)
        picked["bbw_pct"] = picked["bbw_pct"].round(2)

        # crude agreement check: is this day in the "tight" tercile by each measure?
        picked["tight_by_252"] = picked["pct_rank_252"] <= 33.3
        picked["tight_by_756"] = picked["pct_rank_756"] <= 33.3
        picked["tight_by_z"] = picked["zscore_252"] <= -0.43  # ~ z equiv of bottom tercile under normality

        agree_all3 = (picked["tight_by_252"] == picked["tight_by_756"]) & \
                     (picked["tight_by_756"] == picked["tight_by_z"])
        n_agree = agree_all3.sum()

        log(f"\n  {s} ({sectors.get(s)}) — {len(sub)} total population rows w/ all 3 measures; "
            f"showing {take} sampled dates. Tercile-agreement across all 3 measures on "
            f"{n_agree}/{take} sampled days:")
        log("    " + picked.to_string(index=False).replace("\n", "\n    "))

    log(f"\nNOTE: 'tight_by_*' / tercile-agreement columns above are a crude illustrative check "
        f"(bottom-third of own-history distribution per measure) — not a proposed decision rule, "
        f"and no measure is being selected here per task constraints.")


# ══════════════════════════════════════════════════════════════════════════
# WRITE — new staging table only
# ══════════════════════════════════════════════════════════════════════════

def write_staging(con, result):
    cur = con.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {OUT_STAGING}")
    cur.execute(f"""
        CREATE TABLE {OUT_STAGING} (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            active_resistance REAL,
            already_broken_eligibility INTEGER,
            bbw_pct REAL,
            pct_rank_252 REAL,
            pct_rank_756 REAL,
            zscore_252 REAL,
            n_obs_252 INTEGER,
            n_obs_756 INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    rows = list(result[[
        "symbol", "date", "close", "active_resistance",
        "bbw_pct", "pct_rank_252", "pct_rank_756", "zscore_252", "n_obs_252", "n_obs_756",
    ]].itertuples(index=False, name=None))
    rows = [(sym, date, close, ar, 0, bbw, p252, p756, z252, int(n252), int(n756))
            for (sym, date, close, ar, bbw, p252, p756, z252, n252, n756) in rows]
    cur.executemany(
        f"INSERT INTO {OUT_STAGING} "
        f"(symbol, date, close, active_resistance, already_broken_eligibility, "
        f"bbw_pct, pct_rank_252, pct_rank_756, zscore_252, n_obs_252, n_obs_756) "
        f"VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    log(f"\nWrote {len(rows):,} rows to new staging table '{OUT_STAGING}' "
        f"(DROP+recreate on each run — no production table touched).")


def main():
    con = sqlite3.connect(DB)
    try:
        pop, derived = part_a(con)
        result = part_b(pop, con)
        part_c(result, con)
        write_staging(con, result)
    finally:
        con.close()


if __name__ == "__main__":
    main()
