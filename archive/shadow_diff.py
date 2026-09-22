r"""
Kiran Local-First Migration -- Phase 5, Task 5b: shadow-diff comparator.

Once a night, after `archive.nightly_run` has (attempted to) publish Gold, this
compares Gold's decision-driving signals against the still-live Supabase
Postgres pipeline for the shared trading session -- "per-session diff of
every signal that changes" (migration tracker Phase 5 checklist item 2).

    python -m archive.shadow_diff [--store-root DIR] [--archive-root DIR]
                                   [--pg-url URL] [--date YYYY-MM-DD]
    python -m archive.shadow_diff --status

Scope (rescoped 2026-09-22, owner-approved): the three EVERY_SESSION tables
the incoming simplified dashboard (Sector Grading, Explorer -- two pages,
no setup/screener workflow) actually reads -- `market_regime`,
`stock_signals`, `sector_signals`. `boring_signals` and `setup_log` are
being retired in their current form as part of the same migration and were
dropped from the gate the same day: gating a local-first cutover on parity
for a feature that will not exist in the new dashboard was producing
false-halts unrelated to the data that actually matters post-migration
(case in point -- the 2026-09-21 session DISAGREEd solely on a
`setup_log`/`CHBL/RS_LEADER_SECTOR` membership diff, itself downstream of a
2-symbol sector misclassification in `stock_metadata`, not a computation
bug). `digest_boring`/`digest_setup_log`/`_cmp_boring`/`_cmp_setup_log` are
left in the module, unused by the gate, as a starting point if a future
rebuild of that functionality needs the same comparison shape -- any such
rebuild depends on the new dashboard's own requirements, not this file.

Original scope (pre-2026-09-22, kept for history -- matched the
pre-2026-09-09 shadow-mode arc's own MANDATORY-table scope, TR-06/audit
Sec.39.2, `shadow_compare.py`, superseded as a *component* to wire in, not
as a *pattern* to reuse): five EVERY_SESSION tables, the three above plus
`boring_signals`/`setup_log`. `leaders_scan` / `recovery_signals` /
`portfolio_signals` were NON-MANDATORY under that same classification
(sparse/latest-date-only outputs, §39.1/§39.2) and stayed out of the diff
for the same reason -- unaffected by the 2026-09-22 rescope.

Gold intentionally has a NARROWER universe than the live pipelines by design
(3.3b/3.3c: `EXCLUDED_SECTORS` + non-equity dropped, audit §118 Defect A) --
an only-Gold/only-Postgres symbol whose sector is in `config.EXCLUDED_SECTORS`
is Gold correctly excluding it, not a disagreement, and is classified
`noted`, not `halting`. Field-level differences on the SHARED population are
what this tool exists to catch: `bos_flag`, `boring_signals` existence /
`strategy_confirmed`, and `setup_log` membership are trading-decision-driving
-> `halting` (verdict DISAGREE). Everything else (rank/composite/breadth
values, `boring_signals.status`, the regime label) is recorded in `noted`
but does not fail the session -- differences here are expected during the
migration (Gold rebuilds `sector_signals` on a pure point-in-time universe
that is provably a strict superset of live's stale hand-curated one, per
3.3c's findings) and are surfaced for a human to read, not gate on.

Verdict per session: CLEAN (no halting diffs, both sides have real data) |
DISAGREE (a halting diff) | INCOMPLETE (one side hasn't reached this date
yet -- not a disagreement, retried next run, does not reset the streak).
One append-only-by-date row per session in `shadow_diff.duckdb` (its own
file, outside the Gold swap, exactly like `current_publication.duckdb`).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from archive.bronze_ingest import ARCHIVE_ROOT

NTFY_TOPIC = "kiran-psx-alerts-7g3k9qx2mp"  # reused from TR-18 / gold_build.py / nightly_run.py

VERDICT_CLEAN = "CLEAN"
VERDICT_DISAGREE = "DISAGREE"
VERDICT_INCOMPLETE = "INCOMPLETE"

_SHADOW_DDL = """
CREATE TABLE IF NOT EXISTS shadow_sessions (
    session_date TEXT PRIMARY KEY,
    compared_at  TEXT NOT NULL,
    verdict      TEXT NOT NULL,
    clean_streak INTEGER,
    halting_json TEXT,
    noted_json   TEXT
)
"""


# --------------------------------------------------------------------- I/O

class _Source:
    """One backend to diff. kind: 'pg' (psycopg2, %s placeholders) |
    'duckdb'/'sqlite' (? placeholders -- both DB-API-compatible enough for
    the read-only SELECTs this module issues)."""
    def __init__(self, conn, kind: str, label: str):
        self.conn, self.kind, self.label = conn, kind, label

    def q(self, sql: str, params: tuple = ()) -> list[tuple]:
        ph = "%s" if self.kind == "pg" else "?"
        cur = self.conn.cursor() if hasattr(self.conn, "cursor") else self.conn
        try:
            result = cur.execute(sql.replace("{p}", ph), params)
            return result.fetchall() if hasattr(result, "fetchall") else cur.fetchall()
        finally:
            if self.kind == "pg":
                cur.close()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def open_gold(store_root: Path) -> _Source:
    import duckdb
    db = store_root / "psx_serving.duckdb"
    if not db.exists():
        raise SystemExit(f"Gold serving store not found: {db} -- run archive.gold_build first")
    return _Source(duckdb.connect(str(db), read_only=True), "duckdb", "gold")


def open_pg(pg_url: str | None = None) -> _Source:
    import psycopg2
    if pg_url is None:
        import data_health
        pg_url = data_health._env_pg_url()
    if not pg_url:
        raise SystemExit("no Postgres URL -- set DATABASE_URL/SUPABASE_DB_URL or pass --pg-url")
    conn = psycopg2.connect(pg_url)
    conn.set_session(readonly=True, autocommit=True)
    return _Source(conn, "pg", "supabase")


# --------------------------------------------------------------- normalise

def _b(v) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("1", "t", "true", "y", "yes")


def _f(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v) -> str | None:
    return None if v is None else str(v)


# ----------------------------------------------------------------- digest

_LIQUIDITY_MIN = 200_000
_PREBO_BAND = (0.0, 3.0)
_TIGHT_MAX = 8.0
_SECTOR_TOP = 3


class _Unavailable:
    """Sentinel: the table itself doesn't exist on this backend (a scoped
    `--only` Gold build, or a table this backend never wrote) -- distinct
    from the table existing with zero rows for this date. Never compared
    directly; `compare_digests` skips a table entirely (as `noted`, not
    `halting`) rather than misreading a missing table as a giant one-sided
    diff."""
    def __repr__(self) -> str:
        return "UNAVAILABLE"


UNAVAILABLE = _Unavailable()


def _is_missing_table(exc: Exception) -> bool:
    """True for 'that table does not exist' on either DuckDB or psycopg2 --
    matched on message text so this stays import-free of psycopg2/duckdb
    error classes (mirrors data_health.py's own `_is_missing_table`)."""
    msg = str(exc).lower()
    return "does not exist" in msg or "no such table" in msg or "undefinedtable" in msg


def digest_regime(src: _Source, session: str):
    try:
        rows = src.q("SELECT regime FROM market_regime WHERE date = {p}", (session,))
    except Exception as exc:
        if not _is_missing_table(exc):
            raise
        return UNAVAILABLE
    return _s(rows[0][0]) if rows else None


def digest_stock_signals(src: _Source, session: str):
    try:
        rows = src.q(
            "SELECT symbol, bos_flag, pivot_distance_pct, base_tightness, "
            "stage2_bull, avg_vol_10d, sector_rs_rank "
            "FROM stock_signals WHERE date = {p}", (session,))
    except Exception as exc:
        if not _is_missing_table(exc):
            raise
        return UNAVAILABLE
    out = {}
    for sym, bos, pdp, bt, s2, vol, sec_rank in rows:
        pdp_f, bt_f, vol_f = _f(pdp), _f(bt), _f(vol)
        out[sym] = {
            "bos": _b(bos),
            "prebo": (pdp_f is not None and _PREBO_BAND[0] <= pdp_f <= _PREBO_BAND[1]),
            "tight": (bt_f is not None and bt_f < _TIGHT_MAX),
            "stage2": _b(s2),
            "liquid": (vol_f is not None and vol_f > _LIQUIDITY_MIN),
            "sec_top3": (sec_rank is not None and int(sec_rank) <= _SECTOR_TOP),
        }
    return out


def digest_sector_signals(src: _Source, session: str):
    try:
        rows = src.q(
            "SELECT sector, rs_rank, composite_score, breadth_score "
            "FROM sector_signals WHERE date = {p}", (session,))
    except Exception as exc:
        if not _is_missing_table(exc):
            raise
        return UNAVAILABLE
    out = {}
    for sector, rank, comp, breadth in rows:
        comp_f, breadth_f = _f(comp), _f(breadth)
        out[sector] = {
            "top3": (rank is not None and int(rank) <= 3),
            "composite_pos": (comp_f is not None and comp_f > 0),
            "breadth_pos": (breadth_f is not None and breadth_f > 0),
        }
    return out


def digest_boring(src: _Source, session: str):
    """Kept for a possible future rebuild -- not called by `digest_all` as
    of the 2026-09-22 rescope (`boring_signals` is being retired). See the
    module docstring."""
    try:
        rows = src.q(
            "SELECT symbol, strategy_confirmed, status "
            "FROM boring_signals WHERE signal_date = {p}", (session,))
    except Exception as exc:
        if not _is_missing_table(exc):
            raise
        return UNAVAILABLE
    return {r[0]: {"confirmed": _b(r[1]), "status": _s(r[2])} for r in rows}


def digest_setup_log(src: _Source, session: str):
    """Kept for a possible future rebuild -- not called by `digest_all` as
    of the 2026-09-22 rescope (`setup_log` is being retired). See the
    module docstring."""
    try:
        rows = src.q("SELECT symbol, setup_type FROM setup_log WHERE setup_date = {p}", (session,))
    except Exception as exc:
        if not _is_missing_table(exc):
            raise
        return UNAVAILABLE
    return {(r[0], r[1]) for r in rows}


def digest_all(src: _Source, session: str) -> dict:
    """The gate's three tables as of the 2026-09-22 rescope. `boring_signals`
    and `setup_log` are deliberately not included -- see module docstring."""
    return {
        "market_regime": digest_regime(src, session),
        "stock_signals": digest_stock_signals(src, session),
        "sector_signals": digest_sector_signals(src, session),
    }


def sector_of_map(src: _Source) -> dict[str, str]:
    try:
        return dict(src.q("SELECT symbol, sector FROM sectors"))
    except Exception:
        return {}


def excluded_sectors() -> set[str]:
    try:
        import config
        return set(config.EXCLUDED_SECTORS)
    except Exception:
        return set()


# --------------------------------------------------------------- compare

def _cmp_stock_signals(gold: dict, pg: dict, halting: list, noted: list) -> None:
    shared = gold.keys() & pg.keys()
    bos_diff = sorted(s for s in shared if gold[s]["bos"] != pg[s]["bos"])
    if bos_diff:
        halting.append({"table": "stock_signals", "kind": "bos_flag", "symbols": bos_diff[:30]})
    for field in ("prebo", "tight", "stage2", "liquid", "sec_top3"):
        flipped = sorted(s for s in shared if gold[s][field] != pg[s][field])
        if flipped:
            noted.append({"table": "stock_signals", "field": field, "symbols": flipped[:30]})


def _cmp_sector_signals(gold: dict, pg: dict, noted: list) -> None:
    shared = gold.keys() & pg.keys()
    for field in ("top3", "composite_pos", "breadth_pos"):
        flipped = sorted(s for s in shared if gold[s][field] != pg[s][field])
        if flipped:
            noted.append({"table": "sector_signals", "field": field, "sectors": flipped})


def _split_by_excluded_sector(symbols, excl: set[str], sector_of: dict[str, str]) -> tuple[list, list]:
    """(genuine, excluded_sector_expected) -- Gold correctly drops
    EXCLUDED_SECTORS/non-equity (3.3b), so a one-sided symbol in one of those
    sectors is expected, not a disagreement."""
    genuine = sorted(s for s in symbols if sector_of.get(s) not in excl)
    expected = sorted(s for s in symbols if sector_of.get(s) in excl)
    return genuine, expected


def _cmp_boring(gold: dict, pg: dict, excl: set[str], sector_of: dict[str, str],
                halting: list, noted: list) -> None:
    only_gold_g, only_gold_x = _split_by_excluded_sector(gold.keys() - pg.keys(), excl, sector_of)
    only_pg_g, only_pg_x = _split_by_excluded_sector(pg.keys() - gold.keys(), excl, sector_of)
    if only_gold_g or only_pg_g:
        halting.append({"table": "boring_signals", "kind": "existence",
                        "only_gold": only_gold_g, "only_pg": only_pg_g})
    if only_gold_x or only_pg_x:
        noted.append({"table": "boring_signals", "kind": "existence_excluded_sector_expected",
                      "only_gold": only_gold_x, "only_pg": only_pg_x})
    shared = gold.keys() & pg.keys()
    conf_diff = sorted(s for s in shared if gold[s]["confirmed"] != pg[s]["confirmed"])
    if conf_diff:
        halting.append({"table": "boring_signals", "kind": "strategy_confirmed", "symbols": conf_diff})
    status_diff = sorted(s for s in shared if gold[s]["status"] != pg[s]["status"])
    if status_diff:
        noted.append({"table": "boring_signals", "field": "status", "symbols": status_diff})


def _cmp_setup_log(gold: set, pg: set, excl: set[str], sector_of: dict[str, str],
                    halting: list, noted: list) -> None:
    only_gold = {sym for sym, _t in gold - pg}
    only_pg = {sym for sym, _t in pg - gold}
    only_gold_g, only_gold_x = _split_by_excluded_sector(only_gold, excl, sector_of)
    only_pg_g, only_pg_x = _split_by_excluded_sector(only_pg, excl, sector_of)
    genuine_pairs = {(s, t) for s, t in (gold ^ pg) if s in only_gold_g or s in only_pg_g}
    expected_pairs = {(s, t) for s, t in (gold ^ pg) if s in only_gold_x or s in only_pg_x}
    if genuine_pairs:
        halting.append({"table": "setup_log", "kind": "membership",
                        "only_gold": sorted(f"{s}/{t}" for s, t in genuine_pairs & gold),
                        "only_pg": sorted(f"{s}/{t}" for s, t in genuine_pairs & pg)})
    if expected_pairs:
        noted.append({"table": "setup_log", "kind": "membership_excluded_sector_expected",
                      "only_gold": sorted(f"{s}/{t}" for s, t in expected_pairs & gold),
                      "only_pg": sorted(f"{s}/{t}" for s, t in expected_pairs & pg)})


def _cmp_regime(gold, pg, noted: list) -> None:
    if gold != pg:
        noted.append({"table": "market_regime", "field": "regime", "gold": gold, "pg": pg})


def _skip_if_unavailable(table: str, gold_val, pg_val, noted: list) -> bool:
    """True (and records a `noted` entry) when either side's digest for this
    table is UNAVAILABLE -- a missing table (scoped build, a table this
    backend never wrote), not a real diff to compute."""
    if gold_val is UNAVAILABLE or pg_val is UNAVAILABLE:
        noted.append({"table": table, "kind": "unavailable",
                      "gold": "missing" if gold_val is UNAVAILABLE else "present",
                      "pg": "missing" if pg_val is UNAVAILABLE else "present"})
        return True
    return False


def compare_digests(gold: dict, pg: dict, excl: set[str] | None = None,
                     sector_of: dict[str, str] | None = None) -> tuple[list, list]:
    """Returns (halting, noted). halting == real trading-decision disagreements.

    `excl`/`sector_of` are accepted but unused by the three comparators below
    (none of them are sector-scoped) -- kept in the signature so callers
    don't need to change, and because `_cmp_boring`/`_cmp_setup_log` (not
    called here as of the 2026-09-22 rescope, see module docstring) still
    take the same two arguments if reactivated.
    """
    excl = excl or set()
    sector_of = sector_of or {}
    halting: list = []
    noted: list = []
    if not _skip_if_unavailable("market_regime", gold["market_regime"], pg["market_regime"], noted):
        _cmp_regime(gold["market_regime"], pg["market_regime"], noted)
    if not _skip_if_unavailable("stock_signals", gold["stock_signals"], pg["stock_signals"], noted):
        _cmp_stock_signals(gold["stock_signals"], pg["stock_signals"], halting, noted)
    if not _skip_if_unavailable("sector_signals", gold["sector_signals"], pg["sector_signals"], noted):
        _cmp_sector_signals(gold["sector_signals"], pg["sector_signals"], noted)
    return halting, noted


def _empty_or_unavailable(v) -> bool:
    return v is UNAVAILABLE or not v


def _session_is_empty(digest: dict) -> bool:
    """Neither side has genuinely reached this date -- distinguish from a
    real disagreement (matches the old shadow_compare.py's `_local_is_behind`).
    Judged on all three gate tables (`digest_all`'s only keys as of the
    2026-09-22 rescope) -- any one of them being unavailable alone does not
    make a session INCOMPLETE by itself, it is handled per-table by
    `_skip_if_unavailable` instead; this only fires when none of the three
    has real data."""
    return (_empty_or_unavailable(digest["market_regime"])
            and _empty_or_unavailable(digest["stock_signals"])
            and _empty_or_unavailable(digest["sector_signals"]))


def compare_session(gold: _Source, pg: _Source, session_date: str) -> dict:
    """Pure(ish) comparison of one already-chosen session date across two
    already-open sources. Does not write anywhere or alert -- see
    `record_session` / `run_once` for the orchestration around this."""
    excl = excluded_sectors()
    sector_of = sector_of_map(gold)

    gold_digest = digest_all(gold, session_date)
    pg_digest = digest_all(pg, session_date)

    if _session_is_empty(gold_digest) or _session_is_empty(pg_digest):
        return {"session_date": session_date, "verdict": VERDICT_INCOMPLETE,
                "halting": [], "noted": [],
                "reason": "gold" if _session_is_empty(gold_digest) else "pg"}

    halting, noted = compare_digests(gold_digest, pg_digest, excl, sector_of)
    verdict = VERDICT_DISAGREE if halting else VERDICT_CLEAN
    return {"session_date": session_date, "verdict": verdict, "halting": halting, "noted": noted}


# ----------------------------------------------------------------- lineage

def _diff_db_path(archive_root: Path) -> Path:
    return archive_root / "shadow_diff.duckdb"


def _now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def latest_streak(archive_root: Path) -> int:
    """Consecutive CLEAN sessions counting back from the most recent
    genuinely-compared (non-INCOMPLETE) row -- an INCOMPLETE session is
    skipped, not counted as a break, matching the old system's
    'leaves the counter unchanged, retried next session' rule."""
    import duckdb
    db = _diff_db_path(archive_root)
    if not db.exists():
        return 0
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT verdict FROM shadow_sessions ORDER BY session_date DESC").fetchall()
    except Exception:
        return 0
    finally:
        con.close()
    streak = 0
    for (verdict,) in rows:
        if verdict == VERDICT_INCOMPLETE:
            continue
        if verdict == VERDICT_CLEAN:
            streak += 1
        else:
            break
    return streak


def record_session(archive_root: Path, result: dict) -> dict:
    """Writes one row (keyed by session_date -- a re-run for the same date
    replaces its row, it isn't a second attempt) and fills in `clean_streak`."""
    import duckdb
    archive_root.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(_diff_db_path(archive_root)))
    try:
        con.execute(_SHADOW_DDL)
        con.execute(
            "INSERT OR REPLACE INTO shadow_sessions VALUES (?, ?, ?, NULL, ?, ?)",
            (result["session_date"], _now_utc(), result["verdict"],
             json.dumps(result["halting"], default=str), json.dumps(result["noted"], default=str)))
    finally:
        con.close()
    streak = latest_streak(archive_root)
    con = duckdb.connect(str(_diff_db_path(archive_root)))
    try:
        con.execute("UPDATE shadow_sessions SET clean_streak = ? WHERE session_date = ?",
                    (streak, result["session_date"]))
    finally:
        con.close()
    result["clean_streak"] = streak
    return result


def _alert_disagree(result: dict) -> None:
    try:
        import urllib.request
        body = f"session {result['session_date']}: {len(result['halting'])} halting diff(s)"
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
            headers={"Title": "Kiran shadow-diff DISAGREE", "Priority": "urgent", "Tags": "warning"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:  # noqa: BLE001 -- alert failure must not mask the real outcome
        print(f"ntfy alert failed (not fatal): {exc}")


def _iso_date(v) -> str | None:
    """Normalise a str or datetime.date/datetime (psycopg2 hands back the
    latter for a native DATE column; DuckDB's TEXT date columns are already
    plain strings) to a plain YYYY-MM-DD string, so the two backends' max
    dates are comparable."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)[:10]


def _default_session_date(gold: _Source, pg: _Source) -> str:
    g = gold.q("SELECT MAX(date) FROM market_regime")
    p = pg.q("SELECT MAX(date) FROM market_regime")
    gmax = _iso_date(g[0][0]) if g else None
    pmax = _iso_date(p[0][0]) if p else None
    if not gmax:
        raise SystemExit("Gold market_regime is empty -- run archive.gold_build first")
    return min(gmax, pmax) if pmax else gmax


def run_once(store_root: Path, archive_root: Path = ARCHIVE_ROOT,
             pg_url: str | None = None, session_date: str | None = None) -> dict:
    gold = open_gold(store_root)
    pg = open_pg(pg_url)
    try:
        session_date = session_date or _default_session_date(gold, pg)
        result = compare_session(gold, pg, session_date)
    finally:
        gold.close()
        pg.close()

    result = record_session(archive_root, result)
    if result["verdict"] == VERDICT_DISAGREE:
        _alert_disagree(result)
    return result


def status(archive_root: Path = ARCHIVE_ROOT, limit: int = 15) -> dict:
    import duckdb
    db = _diff_db_path(archive_root)
    if not db.exists():
        return {"streak": 0, "sessions": []}
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT session_date, verdict, clean_streak FROM shadow_sessions "
            "ORDER BY session_date DESC LIMIT ?", (limit,)).fetchall()
    finally:
        con.close()
    return {"streak": latest_streak(archive_root),
            "sessions": [{"session_date": r[0], "verdict": r[1], "clean_streak": r[2]} for r in rows]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Shadow-diff -- compare Gold's decision-driving signals vs live Supabase for one session.")
    ap.add_argument("--store-root", default=str(ARCHIVE_ROOT / "psx_serving"))
    ap.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    ap.add_argument("--pg-url", default=None)
    ap.add_argument("--date", default=None, help="session date (default: the latest shared date)")
    ap.add_argument("--status", action="store_true", help="print the streak + recent verdicts, do nothing else")
    args = ap.parse_args(argv)

    if args.status:
        print(json.dumps(status(Path(args.archive_root)), indent=2, sort_keys=True, default=str))
        return 0

    try:
        result = run_once(Path(args.store_root), Path(args.archive_root), args.pg_url, args.date)
    except (Exception, SystemExit) as exc:
        print(f"shadow-diff failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["verdict"] != VERDICT_DISAGREE else 1


if __name__ == "__main__":
    sys.exit(main())
