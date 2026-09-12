r"""
Kiran Local-First Migration -- Phase 5, Task 5a: nightly orchestration.

Chains the three Medallion stages Task Scheduler needs to fire once a night --
Bronze ingest -> Silver build -> Gold publish (the Phase 4 gated path, not the
unconditional ``build()``) -- so "the nightly local pipeline writes Gold
alongside the live Supabase pipeline" (Phase 5 checklist item 1) is one
schedulable entry point rather than three manual commands.

    python -m archive.nightly_run [--force] [--archive-root DIR]

Each stage is independently idempotent by construction (Bronze append-only +
deduped, Silver a full deterministic rebuild, Gold's own atomic staging swap)
-- a legitimate re-run for a NEW trading day is always safe. What is NOT
already safe is **two invocations landing on the same calendar day** -- the
binding condition carried over from the original design's D3 (migration
tracker Sec.9): a Task Scheduler wake-catch-up run plus a later on-time
trigger must not both run the pipeline for one date. This module's lock file
(``_nightly_run_state.json``) is that guard: the first invocation on a given
local calendar date runs the pipeline and records the outcome; a second
invocation the same date is a no-op (``--force`` overrides, for manual re-runs
after fixing a real failure). A lock left ``in_progress`` for over
``STALE_LOCK_HOURS`` is treated as a crashed prior run, not a live one, and is
retried rather than permanently wedging the schedule.

Catch-up-on-wake needs no special multi-day loop here: Bronze ingest already
walks every un-ingested capture file, Silver always rebuilds fully from
current Bronze, and Gold's 2-year window is always built fresh from current
Silver -- so one run after the machine wakes from N missed nights catches up
on all N automatically (Q4, migration tracker Sec.4). Task Scheduler's own
"Run task as soon as possible after a scheduled start is missed" setting
supplies the wake trigger; this module supplies the same-day dedup on top.

Task Scheduler wiring (owner step, mirrors KIRAN_B2_Backup / KIRAN_Archive_Checksum):
    schtasks /Create /TN "KIRAN_Nightly_Pipeline" /TR ^
      "python -m archive.nightly_run" /SC DAILY /ST 23:30 /RU Lenovo /RL LIMITED
Then enable "Run task as soon as possible after a scheduled start is missed"
on the created task's Settings tab (not exposed by ``schtasks /Create`` --
`schtasks /Change /TN "KIRAN_Nightly_Pipeline" /Z /V1`, or the Task Scheduler GUI).

Dead-man's-switch (TR-18 local analogue, mirrors ``daily_scraper.yml``'s cloud
pattern of a start ping + a success ping so a run that starts but never
finishes is distinguishable from one that never started at all): pings
``<KIRAN_NIGHTLY_HC_URL>/start`` before work begins and the bare URL on a
clean run. Requires the owner to create the healthchecks.io check and set
``KIRAN_NIGHTLY_HC_URL`` (console step, same as the cloud TR-18 setup,
ledger Sec.100) -- unset is a silent no-op, not a hard requirement, exactly
like the existing ntfy-on-withhold pattern in ``archive.gold_build``.

Exit codes: 0 = ran clean, or a same-day no-op. 1 = a stage raised (bronze
ingest, silver build, or gold publish) -- the state file records
``status: "error"`` and an ntfy alert fires; the process exit is non-zero so
Task Scheduler and healthchecks.io's grace window both observe the failure.

Tracker: docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 5 (task 5a).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import traceback
import uuid
from pathlib import Path

from archive import bronze_ingest, gold_build, silver_build
from archive.bronze_ingest import ARCHIVE_ROOT

NTFY_TOPIC = "kiran-psx-alerts-7g3k9qx2mp"  # reused from TR-18 / backup_to_b2.py / archive_checksum_check.py
STALE_LOCK_HOURS = 3  # a lock older than this and still "in_progress" is a crashed prior run, not a live one


def _state_path(archive_root: Path) -> Path:
    return archive_root / "_nightly_run_state.json"


def _log_path(archive_root: Path) -> Path:
    return archive_root / "_nightly_run_log.jsonl"


def _now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _read_state(archive_root: Path) -> dict | None:
    p = _state_path(archive_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_state(archive_root: Path, state: dict) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    _state_path(archive_root).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _log_append(archive_root: Path, entry: dict) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    with open(_log_path(archive_root), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def _hc_ping(suffix: str = "") -> None:
    url = os.environ.get("KIRAN_NIGHTLY_HC_URL")
    if not url:
        return
    try:
        import urllib.request
        urllib.request.urlopen(url.rstrip("/") + suffix, timeout=10)
    except Exception as exc:  # noqa: BLE001 -- a dead-man's-switch ping must never mask the real outcome
        print(f"healthchecks.io ping failed (not fatal): {exc}")


def _ntfy_alert(title: str, body: str) -> None:
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "warning"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:  # noqa: BLE001 -- alert failure must not mask the real outcome
        print(f"ntfy alert failed (not fatal): {exc}")


def already_ran_today(archive_root: Path, today: dt.date, *, force: bool = False) -> tuple[bool, dict | None]:
    """Returns (should_skip, prior_state). A same-day lock still ``in_progress``
    younger than STALE_LOCK_HOURS blocks a concurrent run; an older one is
    treated as crashed and does not block a retry."""
    if force:
        return False, None
    state = _read_state(archive_root)
    if not state or state.get("date") != today.isoformat():
        return False, state
    if state.get("status") == "in_progress":
        started = state.get("started_at")
        try:
            age_hours = (dt.datetime.now(dt.timezone.utc)
                         - dt.datetime.fromisoformat(started)).total_seconds() / 3600
        except (TypeError, ValueError):
            age_hours = STALE_LOCK_HOURS + 1  # unparseable timestamp -- don't block forever
        if age_hours < STALE_LOCK_HOURS:
            return True, state
        return False, state  # stale -- a crashed prior run, safe to retry
    return True, state  # already completed (ok or error) today -- no-op unless --force


def run_once(archive_root: Path = ARCHIVE_ROOT, *, force: bool = False,
             captures_dir: Path | None = None, prices_archive_root: Path | None = None,
             gold_store_root: Path | None = None) -> dict:
    """Run Bronze -> Silver -> Gold(publish) once, guarded against a same-day
    double execution. Returns a result dict; raises on a genuine stage
    failure (after recording it) so the caller's exit code reflects it."""
    today = dt.date.today()
    run_id = uuid.uuid4().hex

    skip, prior = already_ran_today(archive_root, today, force=force)
    if skip:
        result = {"outcome": "skipped_already_ran", "date": today.isoformat(),
                   "prior_run_id": (prior or {}).get("run_id"), "prior_status": (prior or {}).get("status")}
        _log_append(archive_root, {"ts": _now_utc(), "run_id": run_id, **result})
        return result

    prices_archive_root = prices_archive_root or (archive_root / "prices_archive")
    gold_store_root = gold_store_root or (archive_root / "psx_serving")
    captures_dir = captures_dir or (archive_root / "data-captures")

    started_at = _now_utc()
    _write_state(archive_root, {"date": today.isoformat(), "run_id": run_id,
                                 "status": "in_progress", "started_at": started_at})
    _hc_ping("/start")

    try:
        bronze_store = bronze_ingest.Store(prices_archive_root)
        seed_result = bronze_ingest.seed(bronze_store)
        bronze_result = bronze_ingest.ingest(bronze_store, captures_dir)

        silver_result = silver_build.build(prices_archive_root)

        gold_result = gold_build.publish(gold_store_root)
    except (Exception, SystemExit) as exc:
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _write_state(archive_root, {"date": today.isoformat(), "run_id": run_id,
                                     "status": "error", "started_at": started_at,
                                     "finished_at": _now_utc(), "error": detail})
        _log_append(archive_root, {"ts": _now_utc(), "run_id": run_id,
                                    "outcome": "error", "date": today.isoformat(), "error": detail})
        _ntfy_alert("Kiran nightly pipeline FAILED", f"run {run_id} ({today.isoformat()}): {detail}")
        raise

    result = {
        "outcome": "ok", "date": today.isoformat(), "run_id": run_id,
        "bronze": {"seed": seed_result, "ingest": bronze_result},
        "silver": silver_result,
        "gold": gold_result,
    }
    _write_state(archive_root, {"date": today.isoformat(), "run_id": run_id,
                                 "status": "ok", "started_at": started_at,
                                 "finished_at": _now_utc(),
                                 "gold_outcome": gold_result.get("outcome")})
    _log_append(archive_root, {"ts": _now_utc(), "run_id": run_id, "outcome": "ok",
                                "date": today.isoformat(), "gold_outcome": gold_result.get("outcome")})
    _hc_ping()
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Nightly orchestration -- Bronze ingest -> Silver build -> Gold publish, once per day.")
    ap.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    ap.add_argument("--force", action="store_true",
                     help="run even if today's lock shows a completed run (manual re-run after a fix)")
    args = ap.parse_args(argv)

    try:
        result = run_once(Path(args.archive_root), force=args.force)
    except (Exception, SystemExit) as exc:
        print(f"nightly run failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
