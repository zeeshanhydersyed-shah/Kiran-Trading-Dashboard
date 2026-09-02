"""
shadow_compare.py -- TR-01 shadow-mode Component C (Phase 5 of the §40.17
migration sequence; SHADOWMODE_SPEC_DRAFT.md §7 / ledger §112).

Once per session (run as a tail step of local_archive_sync.py), for the
latest `current_publication` session on Postgres that is `promoted` and
`coherence = 'COHERENT'`:

  1. LOCAL vs AUTHORITATIVE -- compare the decision-driving projection of
     every MANDATORY table between `psx_data.db` (today's local compute) and
     Postgres. A disagreement on a §4.2 halt field (boring_signals
     existence / strategy_confirmed; stock_signals.bos_flag; setup_log
     (symbol, setup_type) membership; prices / prices_adjusted symbol
     coverage or a close outside float tolerance) -> verdict DISAGREE.
  2. ARCHIVE vs AUTHORITATIVE -- the same projection from `psx_archive.db`
     (local_archive_sync's pull-sync mirror) must match Postgres exactly; it
     was copied. ANY difference here is a Component B bug, not a pipeline
     disagreement -> verdict INCOMPLETE (the comparison infra is not sound),
     flagged separately.
  3. Write one `shadow_comparison` row (in psx_archive.db):
     session_date, compared_at, verdict (CLEAN | DISAGREE | INCOMPLETE),
     clean_session_number (running count of consecutive CLEAN),
     halting_json / noted_json / detail.
  4. DISAGREE, or an ARCHIVE-integrity INCOMPLETE -> loud logger.error + an
     ntfy push (reusing TR-18's topic). CLEAN -> the counter increments.
     A plain INCOMPLETE (a source not caught up yet, session not published)
     leaves the counter unchanged and is retried next session.

Non-halting differences (stock_signals threshold-bucket flips other than
bos_flag; sector_signals rank/composite/breadth; boring_signals status;
market_regime label) are recorded in `noted_json` and surfaced in the
status summary, but do NOT reset the clock (owner decision §4.2).

Shadow mode PASSES when the clean-session streak reaches the floor
(default 10). This does NOT trigger cutover -- it is evidence for §40.18
criterion 6.

CLI:
    python shadow_compare.py            # compare the latest eligible session
    python shadow_compare.py --status   # print the streak + recent verdicts
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sqlite3
import sys

logger = logging.getLogger("shadow_compare")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config  # noqa: E402

VERDICT_CLEAN = "CLEAN"
VERDICT_DISAGREE = "DISAGREE"
VERDICT_INCOMPLETE = "INCOMPLETE"

DEFAULT_FLOOR = 10
_NTFY_TOPIC = "https://ntfy.sh/kiran-psx-alerts-7g3k9qx2mp"

# RS_LEADER_* / PRE_BREAKOUT / BREAKOUT gates, from CLAUDE.md's setup-detection
# table -- the thresholds a bucket flip is measured against.
_LIQUIDITY_MIN = 200_000
_PREBO_BAND = (0.0, 3.0)
_TIGHT_MAX = 8.0
_SECTOR_TOP = 3

_SHADOW_DDL = """
CREATE TABLE IF NOT EXISTS shadow_comparison (
    session_date          TEXT PRIMARY KEY,
    compared_at           TEXT NOT NULL,
    verdict               TEXT NOT NULL,          -- CLEAN | DISAGREE | INCOMPLETE
    clean_session_number  INTEGER,
    halting_json          TEXT,
    noted_json            TEXT,
    detail                TEXT
)
"""


# ---------------------------------------------------------------------------
# normalisation -- psycopg2 hands back bool/Decimal/date; sqlite hands back
# int/float/str. Reduce both to plain comparable primitives.
# ---------------------------------------------------------------------------
def _b(v) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    return s in ("1", "t", "true", "y", "yes")


def _f(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v) -> str | None:
    return None if v is None else str(v)


class _Source:
    """One backend. kind: 'pg' (psycopg2, %s) | 'sqlite' (?)."""
    def __init__(self, conn, kind: str, label: str):
        self.conn, self.kind, self.label = conn, kind, label

    def q(self, sql: str, params=()) -> list[tuple]:
        ph = "%s" if self.kind == "pg" else "?"
        cur = self.conn.cursor()
        try:
            cur.execute(sql.replace("{p}", ph), params)
            return cur.fetchall()
        finally:
            if self.kind == "pg":
                cur.close()

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# per-table decision-driving digests (session-scoped)
# ---------------------------------------------------------------------------
def _digest_prices(src: _Source, session: str, table: str) -> dict:
    rows = src.q(f"SELECT symbol, close FROM {table} WHERE date = {{p}}", (session,))
    return {"symbols": {r[0] for r in rows},
            "close": {r[0]: _f(r[1]) for r in rows}}


def _digest_stock_signals(src: _Source, session: str) -> dict:
    rows = src.q(
        "SELECT symbol, bos_flag, pivot_distance_pct, base_tightness, "
        "stage2_bull, avg_vol_10d, sector_rs_rank "
        "FROM stock_signals WHERE date = {p}", (session,))
    out = {}
    for sym, bos, pdp, bt, s2, vol, src_rank in rows:
        pdp_f, bt_f, vol_f = _f(pdp), _f(bt), _f(vol)
        out[sym] = {
            "bos": _b(bos),
            "prebo": (pdp_f is not None and _PREBO_BAND[0] <= pdp_f <= _PREBO_BAND[1]),
            "tight": (bt_f is not None and bt_f < _TIGHT_MAX),
            "stage2": _b(s2),
            "liquid": (vol_f is not None and vol_f > _LIQUIDITY_MIN),
            "sec_top3": (src_rank is not None and int(src_rank) <= _SECTOR_TOP),
        }
    return out


def _digest_sector_signals(src: _Source, session: str) -> dict:
    rows = src.q(
        "SELECT sector, rs_rank, composite_score, breadth_score "
        "FROM sector_signals WHERE date = {p}", (session,))
    out = {}
    for sector, rank, comp, breadth in rows:
        comp_f, breadth_f = _f(comp), _f(breadth)
        out[sector] = {
            "top3": (rank is not None and int(rank) <= 3),
            "composite_pos": (comp_f is not None and comp_f > 0),
            "breadth_pos": (breadth_f is not None and breadth_f > 0),
        }
    return out


def _digest_boring(src: _Source, session: str) -> dict:
    rows = src.q(
        "SELECT symbol, strategy_confirmed, status "
        "FROM boring_signals WHERE signal_date = {p}", (session,))
    return {r[0]: {"confirmed": _b(r[1]), "status": _s(r[2])} for r in rows}


def _digest_setup_log(src: _Source, session: str) -> set:
    rows = src.q(
        "SELECT symbol, setup_type FROM setup_log WHERE setup_date = {p}", (session,))
    return {(r[0], r[1]) for r in rows}


def _digest_regime(src: _Source, session: str) -> str | None:
    rows = src.q("SELECT regime FROM market_regime WHERE date = {p}", (session,))
    return _s(rows[0][0]) if rows else None


def digest_all(src: _Source, session: str) -> dict:
    return {
        "prices": _digest_prices(src, session, "prices"),
        "prices_adjusted": _digest_prices(src, session, "prices_adjusted"),
        "stock_signals": _digest_stock_signals(src, session),
        "sector_signals": _digest_sector_signals(src, session),
        "boring_signals": _digest_boring(src, session),
        "setup_log": _digest_setup_log(src, session),
        "market_regime": _digest_regime(src, session),
    }


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------
def _close_within_tol(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(0.01, 0.001 * abs(a))


def _cmp_prices(auth: dict, other: dict, table: str, halting: list, noted: list) -> None:
    only_auth = auth["symbols"] - other["symbols"]
    only_other = other["symbols"] - auth["symbols"]
    if only_auth or only_other:
        halting.append({"table": table, "kind": "coverage",
                        "only_authoritative": sorted(only_auth)[:20],
                        "only_other": sorted(only_other)[:20]})
    bad = []
    for sym in auth["symbols"] & other["symbols"]:
        if not _close_within_tol(auth["close"].get(sym), other["close"].get(sym)):
            bad.append(f"{sym} {auth['close'].get(sym)}~{other['close'].get(sym)}")
    if bad:
        halting.append({"table": table, "kind": "close_outside_tolerance",
                        "symbols": bad[:20]})


def _cmp_stock_signals(auth: dict, other: dict, halting: list, noted: list) -> None:
    bos_diff = [s for s in auth.keys() & other.keys()
               if auth[s]["bos"] != other[s]["bos"]]
    if bos_diff:
        halting.append({"table": "stock_signals", "kind": "bos_flag",
                        "symbols": sorted(bos_diff)[:30]})
    for field in ("prebo", "tight", "stage2", "liquid", "sec_top3"):
        flipped = [s for s in auth.keys() & other.keys()
                  if auth[s][field] != other[s][field]]
        if flipped:
            noted.append({"table": "stock_signals", "field": field,
                          "symbols": sorted(flipped)[:30]})


def _cmp_sector_signals(auth: dict, other: dict, halting: list, noted: list) -> None:
    for field in ("top3", "composite_pos", "breadth_pos"):
        flipped = [s for s in auth.keys() & other.keys()
                  if auth[s][field] != other[s][field]]
        if flipped:
            noted.append({"table": "sector_signals", "field": field,
                          "sectors": sorted(flipped)})


def _cmp_boring(auth: dict, other: dict, halting: list, noted: list) -> None:
    only_auth = auth.keys() - other.keys()
    only_other = other.keys() - auth.keys()
    if only_auth or only_other:
        halting.append({"table": "boring_signals", "kind": "existence",
                        "only_authoritative": sorted(only_auth),
                        "only_other": sorted(only_other)})
    conf_diff = [s for s in auth.keys() & other.keys()
                if auth[s]["confirmed"] != other[s]["confirmed"]]
    if conf_diff:
        halting.append({"table": "boring_signals", "kind": "strategy_confirmed",
                        "symbols": sorted(conf_diff)})
    status_diff = [s for s in auth.keys() & other.keys()
                  if auth[s]["status"] != other[s]["status"]]
    if status_diff:
        noted.append({"table": "boring_signals", "field": "status",
                      "symbols": sorted(status_diff)})


def _cmp_setup_log(auth: set, other: set, halting: list, noted: list) -> None:
    if auth != other:
        halting.append({"table": "setup_log", "kind": "membership",
                        "only_authoritative": sorted(f"{s}/{t}" for s, t in auth - other),
                        "only_other": sorted(f"{s}/{t}" for s, t in other - auth)})


def _cmp_regime(auth, other, halting: list, noted: list) -> None:
    if auth != other:
        noted.append({"table": "market_regime", "field": "regime",
                      "authoritative": auth, "other": other})


def compare_digests(auth: dict, other: dict) -> tuple[list, list]:
    """Returns (halting, noted) -- halting entries are §4.2 halt conditions."""
    halting: list = []
    noted: list = []
    _cmp_prices(auth["prices"], other["prices"], "prices", halting, noted)
    _cmp_prices(auth["prices_adjusted"], other["prices_adjusted"],
                "prices_adjusted", halting, noted)
    _cmp_stock_signals(auth["stock_signals"], other["stock_signals"], halting, noted)
    _cmp_sector_signals(auth["sector_signals"], other["sector_signals"], halting, noted)
    _cmp_boring(auth["boring_signals"], other["boring_signals"], halting, noted)
    _cmp_setup_log(auth["setup_log"], other["setup_log"], halting, noted)
    _cmp_regime(auth["market_regime"], other["market_regime"], halting, noted)
    return halting, noted


def _local_is_behind(local_digest: dict) -> bool:
    """LOCAL genuinely hasn't computed this session yet -- distinguish from a
    real disagreement. Zero rows in the every-session core tables == behind."""
    return (not local_digest["prices"]["symbols"]
            and not local_digest["stock_signals"]
            and not local_digest["sector_signals"])


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def _latest_eligible_session(auth: _Source) -> str | None:
    rows = auth.q(
        "SELECT source_as_of FROM current_publication "
        "WHERE promoted = {p} AND coherence = {p} "
        "ORDER BY promoted_at DESC, id DESC LIMIT 1",
        (True, "COHERENT"))
    if not rows or not rows[0][0]:
        return None
    return str(rows[0][0])[:10]


def _prev_clean_number(arc: sqlite3.Connection, session: str) -> int:
    row = arc.execute(
        "SELECT clean_session_number FROM shadow_comparison "
        "WHERE session_date < ? ORDER BY session_date DESC LIMIT 1", (session,)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _default_ntfy(title: str, message: str) -> None:
    import urllib.request
    req = urllib.request.Request(
        _NTFY_TOPIC, data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "urgent", "Tags": "warning"},
        method="POST")
    urllib.request.urlopen(req, timeout=10)


def run_compare(auth_conn=None, local_path: str | None = None,
                archive_path: str | None = None, floor: int = DEFAULT_FLOOR,
                notify=None, now: _dt.datetime | None = None) -> dict:
    local_path = local_path or config.DB_PATH
    archive_path = archive_path or os.path.join(
        os.path.dirname(config.DB_PATH), "psx_archive.db")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    notify = notify if notify is not None else _default_ntfy

    owns_auth = auth_conn is None
    if owns_auth:
        from local_archive_sync import _default_pg_conn
        auth_conn = _default_pg_conn()

    arc = sqlite3.connect(archive_path)
    try:
        arc.execute(_SHADOW_DDL)
        auth = _Source(auth_conn, "pg", "authoritative")

        try:
            session = _latest_eligible_session(auth)
        except Exception as exc:
            logger.warning("shadow_compare: could not read current_publication: %s", exc)
            return {"status": "authoritative unreachable", "session": None,
                    "verdict": VERDICT_INCOMPLETE, "detail": str(exc)}
        if session is None:
            return {"status": "no eligible session", "session": None}

        existing = arc.execute(
            "SELECT verdict FROM shadow_comparison WHERE session_date = ?", (session,)
        ).fetchone()
        if existing and existing[0] != VERDICT_INCOMPLETE:
            return {"status": "already compared", "session": session,
                    "verdict": existing[0]}

        result = _compare_one(auth, local_path, archive_path, session)

        prev = _prev_clean_number(arc, session)
        if result["verdict"] == VERDICT_CLEAN:
            clean_n = prev + 1
        elif result["verdict"] == VERDICT_DISAGREE:
            clean_n = 0
        else:  # INCOMPLETE -- carry the streak, retry next run
            clean_n = prev

        arc.execute(
            "INSERT INTO shadow_comparison "
            "(session_date, compared_at, verdict, clean_session_number, "
            " halting_json, noted_json, detail) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_date) DO UPDATE SET "
            "  compared_at=excluded.compared_at, verdict=excluded.verdict, "
            "  clean_session_number=excluded.clean_session_number, "
            "  halting_json=excluded.halting_json, noted_json=excluded.noted_json, "
            "  detail=excluded.detail",
            (session, now.isoformat(), result["verdict"], clean_n,
             json.dumps(result["halting"]), json.dumps(result["noted"]),
             result["detail"]),
        )
        arc.commit()

        if result["verdict"] == VERDICT_DISAGREE or result.get("archive_integrity_fail"):
            logger.error("SHADOW COMPARE %s for %s -- %s",
                         result["verdict"], session, result["detail"])
            try:
                notify(f"Kiran shadow-mode {result['verdict']} ({session})",
                       result["detail"][:900])
            except Exception as exc:
                logger.debug("shadow_compare ntfy failed: %s", exc)

        return {"status": "compared", "session": session,
                "verdict": result["verdict"], "clean_session_number": clean_n,
                "shadow_passes": clean_n >= floor,
                "halting": result["halting"], "noted": result["noted"],
                "detail": result["detail"]}
    finally:
        arc.close()
        if owns_auth:
            auth_conn.close()


def _compare_one(auth: _Source, local_path: str, archive_path: str,
                 session: str) -> dict:
    try:
        auth_d = digest_all(auth, session)
    except Exception as exc:
        auth.rollback()
        return dict(verdict=VERDICT_INCOMPLETE, halting=[], noted=[],
                    detail=f"authoritative unreadable: {type(exc).__name__}: {exc}")

    # ARCHIVE vs AUTHORITATIVE -- must be exact (it was copied)
    arc_fail = None
    if os.path.exists(archive_path):
        try:
            with sqlite3.connect(archive_path) as ac:
                arc_d = digest_all(_Source(ac, "sqlite", "archive"), session)
            a_halt, a_noted = compare_digests(auth_d, arc_d)
            if a_halt or a_noted:
                arc_fail = {"halting": a_halt, "noted": a_noted}
        except Exception as exc:
            arc_fail = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        arc_fail = {"error": "psx_archive.db not present"}

    if arc_fail is not None:
        return dict(verdict=VERDICT_INCOMPLETE, halting=[], noted=[],
                    archive_integrity_fail=True,
                    detail=f"ARCHIVE vs AUTHORITATIVE mismatch (Component B): "
                           f"{json.dumps(arc_fail)[:600]}")

    # LOCAL vs AUTHORITATIVE -- the shadow test
    if not os.path.exists(local_path):
        return dict(verdict=VERDICT_INCOMPLETE, halting=[], noted=[],
                    detail="psx_data.db not present")
    try:
        with sqlite3.connect(local_path) as lc:
            local_d = digest_all(_Source(lc, "sqlite", "local"), session)
    except Exception as exc:
        return dict(verdict=VERDICT_INCOMPLETE, halting=[], noted=[],
                    detail=f"local unreadable: {type(exc).__name__}: {exc}")

    if _local_is_behind(local_d):
        return dict(verdict=VERDICT_INCOMPLETE, halting=[], noted=[],
                    detail=f"local compute has not reached {session} yet")

    halting, noted = compare_digests(auth_d, local_d)
    if halting:
        return dict(verdict=VERDICT_DISAGREE, halting=halting, noted=noted,
                    detail="; ".join(h["table"] + "/" + h.get("kind", "?")
                                     for h in halting))
    return dict(verdict=VERDICT_CLEAN, halting=[], noted=noted,
                detail=(f"{len(noted)} non-halting difference(s) noted"
                        if noted else "clean"))


def shadow_status(archive_path: str | None = None, floor: int = DEFAULT_FLOOR) -> dict | None:
    archive_path = archive_path or os.path.join(
        os.path.dirname(config.DB_PATH), "psx_archive.db")
    if not os.path.exists(archive_path):
        return None
    try:
        arc = sqlite3.connect(archive_path)
        try:
            rows = arc.execute(
                "SELECT session_date, verdict, clean_session_number, detail "
                "FROM shadow_comparison ORDER BY session_date DESC LIMIT 20"
            ).fetchall()
            if not rows:
                return {"streak": 0, "shadow_passes": False, "sessions": []}
            streak = int(rows[0][2]) if rows[0][2] is not None else 0
            best = arc.execute(
                "SELECT MAX(clean_session_number) FROM shadow_comparison"
            ).fetchone()[0] or 0
            return {
                "streak": streak,
                "best_streak": int(best),
                "floor": floor,
                "shadow_passes": int(best) >= floor,
                "sessions": [{"session": s, "verdict": v, "clean_n": n, "detail": d}
                             for s, v, n, d in rows],
            }
        finally:
            arc.close()
    except Exception:
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--archive-path", default=None)
    ap.add_argument("--floor", type=int, default=DEFAULT_FLOOR)
    args = ap.parse_args()

    if args.status:
        st = shadow_status(args.archive_path, args.floor)
        print(json.dumps(st, indent=2, default=str) if st else "no shadow_comparison rows yet")
        return 0

    out = run_compare(archive_path=args.archive_path, floor=args.floor)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("verdict") in (VERDICT_CLEAN, None) or out.get("status") in (
        "already compared", "no eligible session") else 1


if __name__ == "__main__":
    sys.exit(main())
