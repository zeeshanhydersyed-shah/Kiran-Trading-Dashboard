"""Phase 5, Tasks 5a + 5b wiring -- nightly orchestration (archive/nightly_run.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 5): one entry point chains
Bronze ingest -> Silver build -> Gold publish for Task Scheduler, guarded so a
wake-catch-up run and a later on-time trigger never both run the pipeline for
the same calendar date (D3), then runs shadow_diff.run_once() best-effort so
5c's real streak accumulates automatically. The three build stages and
shadow_diff's own comparison logic are tested in test_bronze_ingest.py /
test_silver_build.py / test_gold_build.py / test_shadow_diff.py -- these
tests exercise nightly_run's own logic (the guard, error handling, state/log
writes, alerting, and the shadow-diff-is-best-effort wiring) with all stages
stubbed out.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from archive import nightly_run


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    calls = {"seed": 0, "ingest": 0, "silver": 0, "gold": 0, "shadow_diff": 0, "hc": [], "ntfy": []}

    monkeypatch.setattr(nightly_run.bronze_ingest, "seed", lambda store: (calls.__setitem__("seed", calls["seed"] + 1) or {"seeded": False}))
    monkeypatch.setattr(nightly_run.bronze_ingest, "ingest", lambda store, captures_dir, **kw: (calls.__setitem__("ingest", calls["ingest"] + 1) or {"appended": 0}))
    monkeypatch.setattr(nightly_run.silver_build, "build", lambda store_root: (calls.__setitem__("silver", calls["silver"] + 1) or {"rows": 0}))
    monkeypatch.setattr(nightly_run.gold_build, "publish", lambda store_root: (calls.__setitem__("gold", calls["gold"] + 1) or {"outcome": "published"}))
    monkeypatch.setattr(nightly_run.shadow_diff, "run_once", lambda store_root, archive_root: (
        calls.__setitem__("shadow_diff", calls["shadow_diff"] + 1)
        or {"verdict": "CLEAN", "session_date": "2026-09-12", "clean_streak": 1}))
    monkeypatch.setattr(nightly_run, "_hc_ping", lambda suffix="": calls["hc"].append(suffix))
    monkeypatch.setattr(nightly_run, "_ntfy_alert", lambda title, body: calls["ntfy"].append((title, body)))
    return root, calls


def test_first_run_today_executes_all_three_stages_and_records_ok(env):
    root, calls = env
    result = nightly_run.run_once(root)

    assert result["outcome"] == "ok"
    assert calls["seed"] == 1 and calls["ingest"] == 1 and calls["silver"] == 1 and calls["gold"] == 1
    assert calls["shadow_diff"] == 1
    assert result["shadow_diff"]["verdict"] == "CLEAN"
    assert calls["hc"] == ["/start", ""]
    assert calls["ntfy"] == []

    state = json.loads(nightly_run._state_path(root).read_text())
    assert state["status"] == "ok"
    assert state["date"] == dt.date.today().isoformat()
    assert state["run_id"] == result["run_id"]
    assert state["shadow_diff_verdict"] == "CLEAN"

    log_lines = nightly_run._log_path(root).read_text().splitlines()
    assert len(log_lines) == 1
    logged = json.loads(log_lines[0])
    assert logged["outcome"] == "ok"
    assert logged["shadow_diff_verdict"] == "CLEAN"


def test_shadow_diff_receives_the_gold_store_root_and_archive_root(env, monkeypatch):
    root, calls = env
    received = {}

    def _capture(store_root, archive_root):
        received["store_root"] = store_root
        received["archive_root"] = archive_root
        return {"verdict": "CLEAN"}
    monkeypatch.setattr(nightly_run.shadow_diff, "run_once", _capture)

    nightly_run.run_once(root)

    assert received["store_root"] == root / "psx_serving"
    assert received["archive_root"] == root


def test_shadow_diff_failure_does_not_fail_the_nightly_run(env, monkeypatch):
    root, calls = env
    monkeypatch.setattr(nightly_run.shadow_diff, "run_once",
                         lambda store_root, archive_root: (_ for _ in ()).throw(RuntimeError("supabase unreachable")))

    result = nightly_run.run_once(root)

    assert result["outcome"] == "ok"  # the core pipeline succeeded
    assert "supabase unreachable" in result["shadow_diff_error"]
    assert "shadow_diff" not in result  # no verdict -- the step itself blew up
    # the local pipeline's own success ping still fires -- shadow-diff is a
    # different reliability domain and must not mask that Gold built fine
    assert calls["hc"] == ["/start", ""]
    # but a distinct alert fires, so the failure isn't silent
    assert len(calls["ntfy"]) == 1
    assert "shadow-diff" in calls["ntfy"][0][0].lower()
    assert "supabase unreachable" in calls["ntfy"][0][1]


def test_shadow_diff_failure_recorded_in_state_and_log(env, monkeypatch):
    root, calls = env
    monkeypatch.setattr(nightly_run.shadow_diff, "run_once",
                         lambda store_root, archive_root: (_ for _ in ()).throw(RuntimeError("boom")))

    nightly_run.run_once(root)

    state = json.loads(nightly_run._state_path(root).read_text())
    assert state["status"] == "ok"  # still an overall-ok night
    assert "boom" in state["shadow_diff_error"]
    assert state.get("shadow_diff_verdict") is None

    logged = json.loads(nightly_run._log_path(root).read_text().splitlines()[-1])
    assert logged["outcome"] == "ok"
    assert "boom" in logged["shadow_diff_error"]


def test_shadow_diff_not_called_when_a_build_stage_fails(env, monkeypatch):
    root, calls = env
    monkeypatch.setattr(nightly_run.silver_build, "build",
                         lambda store_root: (_ for _ in ()).throw(RuntimeError("silver blew up")))

    with pytest.raises(RuntimeError):
        nightly_run.run_once(root)

    assert calls["shadow_diff"] == 0


def test_second_run_same_day_is_a_noop(env):
    root, calls = env
    first = nightly_run.run_once(root)
    second = nightly_run.run_once(root)

    assert second["outcome"] == "skipped_already_ran"
    assert second["prior_run_id"] == first["run_id"]
    # stages did not run a second time
    assert calls["seed"] == 1 and calls["ingest"] == 1 and calls["silver"] == 1 and calls["gold"] == 1
    assert calls["hc"] == ["/start", ""]  # no new pings on the no-op path


def test_force_reruns_same_day(env):
    root, calls = env
    nightly_run.run_once(root)
    result = nightly_run.run_once(root, force=True)

    assert result["outcome"] == "ok"
    assert calls["seed"] == 2 and calls["ingest"] == 2 and calls["silver"] == 2 and calls["gold"] == 2


def test_fresh_in_progress_lock_blocks_concurrent_run(env):
    root, calls = env
    today = dt.date.today()
    nightly_run._write_state(root, {
        "date": today.isoformat(), "run_id": "concurrent-run",
        "status": "in_progress", "started_at": nightly_run._now_utc(),
    })

    result = nightly_run.run_once(root)

    assert result["outcome"] == "skipped_already_ran"
    assert result["prior_run_id"] == "concurrent-run"
    assert calls["seed"] == 0 and calls["silver"] == 0 and calls["gold"] == 0


def test_stale_in_progress_lock_is_retried(env):
    root, calls = env
    today = dt.date.today()
    stale_start = (dt.datetime.now(dt.timezone.utc)
                   - dt.timedelta(hours=nightly_run.STALE_LOCK_HOURS + 1)).isoformat()
    nightly_run._write_state(root, {
        "date": today.isoformat(), "run_id": "crashed-run",
        "status": "in_progress", "started_at": stale_start,
    })

    result = nightly_run.run_once(root)

    assert result["outcome"] == "ok"
    assert calls["seed"] == 1 and calls["silver"] == 1 and calls["gold"] == 1


def test_new_calendar_day_runs_again_without_force(env):
    root, calls = env
    nightly_run.run_once(root)
    yesterday_state = json.loads(nightly_run._state_path(root).read_text())
    yesterday_state["date"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    nightly_run._write_state(root, yesterday_state)

    result = nightly_run.run_once(root)

    assert result["outcome"] == "ok"
    assert calls["seed"] == 2 and calls["silver"] == 2 and calls["gold"] == 2


def test_stage_failure_propagates_records_error_and_alerts(env, monkeypatch):
    root, calls = env
    monkeypatch.setattr(nightly_run.silver_build, "build",
                         lambda store_root: (_ for _ in ()).throw(RuntimeError("silver blew up")))

    with pytest.raises(RuntimeError, match="silver blew up"):
        nightly_run.run_once(root)

    assert calls["hc"] == ["/start"]  # start ping fired, success ping did not
    assert len(calls["ntfy"]) == 1
    assert "silver blew up" in calls["ntfy"][0][1]

    state = json.loads(nightly_run._state_path(root).read_text())
    assert state["status"] == "error"
    assert "silver blew up" in state["error"]

    log_lines = [json.loads(ln) for ln in nightly_run._log_path(root).read_text().splitlines()]
    assert log_lines[-1]["outcome"] == "error"


def test_stage_raising_systemexit_is_treated_as_a_failure_not_a_clean_exit(env, monkeypatch):
    root, calls = env
    monkeypatch.setattr(nightly_run.bronze_ingest, "ingest",
                         lambda store, captures_dir, **kw: (_ for _ in ()).throw(SystemExit("git pull failed")))

    with pytest.raises(SystemExit):
        nightly_run.run_once(root)

    state = json.loads(nightly_run._state_path(root).read_text())
    assert state["status"] == "error"
    assert calls["gold"] == 0  # later stages never ran


def test_a_failed_run_is_retried_the_same_day_by_default(env, monkeypatch):
    """An error status is a completed attempt for the day -- same-day dedup
    still applies (no silent retry storm); --force or the next calendar day
    are the two ways forward, matching an 'ok' run's no-op behaviour."""
    root, calls = env
    monkeypatch.setattr(nightly_run.silver_build, "build",
                         lambda store_root: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        nightly_run.run_once(root)

    result = nightly_run.run_once(root)
    assert result["outcome"] == "skipped_already_ran"
    assert result["prior_status"] == "error"


def test_main_returns_nonzero_on_stage_failure(env, monkeypatch, capsys):
    root, calls = env
    monkeypatch.setattr(nightly_run.silver_build, "build",
                         lambda store_root: (_ for _ in ()).throw(RuntimeError("boom")))

    rc = nightly_run.main(["--archive-root", str(root)])

    assert rc == 1
    assert "nightly run failed" in capsys.readouterr().err


def test_main_returns_zero_on_success(env, capsys):
    root, calls = env
    rc = nightly_run.main(["--archive-root", str(root)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "ok"


def test_hc_ping_is_a_noop_without_the_env_var(monkeypatch):
    monkeypatch.delenv("KIRAN_NIGHTLY_HC_URL", raising=False)
    called = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: called.append(a))
    nightly_run._hc_ping("/start")
    assert called == []


def test_hc_ping_hits_the_configured_url(monkeypatch):
    monkeypatch.setenv("KIRAN_NIGHTLY_HC_URL", "https://hc-ping.com/fake-uuid")
    called = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: called.append(url))
    nightly_run._hc_ping("/start")
    assert called == ["https://hc-ping.com/fake-uuid/start"]


def test_hc_ping_failure_is_swallowed(monkeypatch, capsys):
    monkeypatch.setenv("KIRAN_NIGHTLY_HC_URL", "https://hc-ping.com/fake-uuid")
    import urllib.request

    def _boom(*a, **kw):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    nightly_run._hc_ping()  # must not raise
    assert "not fatal" in capsys.readouterr().out
