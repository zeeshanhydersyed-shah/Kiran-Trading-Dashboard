"""
PSX Sector Performance Pipeline — entry point.

Usage:
    python main.py --init        # First-time: scrape last 45 calendar days
    python main.py --update      # Daily: scrape only new dates since last run
    python main.py --report      # Print sector rankings to terminal
    python main.py --schedule    # Start background scheduler (runs --update daily)
    python main.py --all         # --update then --report
"""

import argparse
import logging
import os
import sys
import uuid
from datetime import date, datetime

from config import CALENDAR_DAYS_BACK, DB_PATH, SCHEDULER_HOUR, SCHEDULER_MINUTE, SCHEDULER_TIMEZONE
from database import (
    init_db,
    upsert_sectors,
    upsert_prices,
    upsert_index_prices,
    get_latest_scraped_date,
    get_latest_prices,
    cleanup_ghost_dates,
    count_prices,
    count_sectors,
    get_price_date_range,
    auto_save_setups_with_source,
)
from scraper import (
    build_session,
    scrape_date_range,
    trading_dates_to_scrape,
    dates_since,
    get_source_date,
)
from processor import run_analysis, print_sector_report
from serving_revision import resolve_code_version
import sector_signals
import stock_signals

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(logging.FileHandler("psx_pipeline.log", encoding="utf-8"))
except OSError:
    pass  # read-only filesystem (e.g. Streamlit Cloud) — stdout only

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Deployment identity (OI-9 / TR-11 -- KIRAN_CLEANUP_AUDIT.md 88)
# ---------------------------------------------------------------------------

# Resolved once per cmd_update() invocation and threaded onto every heartbeat
# that run writes, so every production row in pipeline_runs is permanently
# traceable to the exact commit that produced it. A run_id sibling.
_RUN_CODE_VERSION: str | None = None


def _set_run_code_version(value: str | None) -> None:
    global _RUN_CODE_VERSION
    _RUN_CODE_VERSION = value


def _working_tree_state():
    """('clean' | 'dirty' | 'unknown', [modified tracked *.py files]).

    Best-effort, never raises. 'dirty' counts only tracked non-test *.py files
    modified vs HEAD -- untracked files, data files (breadth_data.csv), and
    scratch dirs are deliberately ignored (they are expected to differ on a
    working machine). 'unknown' when git is unavailable or errors -- an
    Actions runner and Streamlit Cloud both have git, a locked-down box might
    not, and either way this must not affect whether the pipeline runs.

    OI-9 / TR-11: a local production write from a checkout that does not match
    what was reviewed is the shape of the OI-8 incident (ledger 85). v1
    records and warns; it does not block.
    """
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", _PROJECT_DIR, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return ("unknown", [])
        dirty = []
        for line in out.stdout.splitlines():
            # porcelain v1: two status chars, a space, then the path
            path = line[3:].strip().strip('"')
            if " -> " in path:  # rename: keep the destination
                path = path.split(" -> ", 1)[1]
            if path.endswith(".py") and not path.startswith("tests/"):
                dirty.append(path)
        return ("dirty", dirty) if dirty else ("clean", [])
    except Exception:
        return ("unknown", [])


# ---------------------------------------------------------------------------
# Core pipeline steps
# ---------------------------------------------------------------------------

def cmd_init(force: bool = False):
    """Scrape the last CALENDAR_DAYS_BACK days (initial database build)."""
    init_db()

    latest = get_latest_scraped_date()
    if latest and not force:
        logger.info(
            "Database already has data up to %s. Use --update to fetch new data, "
            "or --init --force to re-scrape everything.",
            latest,
        )
        return

    dates = trading_dates_to_scrape(CALENDAR_DAYS_BACK)
    logger.info("Initial load: scraping %d trading dates…", len(dates))

    session = build_session()
    sector_rows, price_rows, index_rows = scrape_date_range(dates, session)

    upsert_sectors(sector_rows)
    upsert_prices(price_rows)
    if index_rows:
        upsert_index_prices(index_rows)
    cleanup_ghost_dates()

    mn, mx = get_price_date_range()
    logger.info(
        "Init complete -- %d symbols, %d price records, date range %s to %s",
        count_sectors(), count_prices(), mn, mx,
    )


def _record_hook(hook_name, run_date, status="ok", rows_written=None,
                 detail=None, mirror_to_postgres=False, run_id=None,
                 execution_status=None, coverage_status=None,
                 eligible_count=None, processed_count=None, code_version=None):
    """Write one pipeline_runs heartbeat. Never raises.

    Heartbeats answer "did this producer run?", which is the only honest
    question for hooks whose tables can legitimately be empty on a given day
    (leaders_top_picks writes nothing when nothing clears MIN_PICK_SCORE;
    corporate_action finds nothing most days). For those, an empty table and a
    dead job look identical -- see docs/KIRAN_CLEANUP_AUDIT.md 31.

    TR-06 Tier 2 (2026-08-24): five additive optional kwargs, all defaulting
    to None so every existing call site keeps working unchanged. run_id: the
    shared identity for this cmd_update() invocation (see its generation at
    the top of cmd_update()). See data_health.py's record_run() for what each
    field means and why execution_status is derived from `status` rather than
    required here.

    Ledger §113 (2026-09-03): the five hooks TR-06 Tier 2 originally left
    un-threaded (regime/sector_signals/stock_signals/recovery_signals/
    portfolio_signals) now DO pass run_id + execution_status -- without them,
    mandatory_hooks_completed_for_run() could never match them to the
    freshness gate's run_id and every authoritative publication withheld.
    """
    try:
        from data_health import record_run
        # OI-9 / TR-11: default to this run's resolved code version so every
        # existing call site picks it up with no per-site change (same
        # pattern the TR-06 Tier-2 kwargs use). An explicit code_version
        # argument still wins if a caller passes one.
        if code_version is None:
            code_version = _RUN_CODE_VERSION
        record_run(hook_name, run_date, status=status, rows_written=rows_written,
                   detail=detail, mirror_to_postgres=mirror_to_postgres,
                   run_id=run_id, execution_status=execution_status,
                   coverage_status=coverage_status, eligible_count=eligible_count,
                   processed_count=processed_count, code_version=code_version)
    except Exception as exc:  # telemetry must never break the pipeline
        logger.debug("Heartbeat write failed for %s: %s", hook_name, exc)


def cmd_update():
    """Scrape only dates that are newer than the last record in the database."""
    # TR-06 Tier 2 (2026-08-24): one execution identity per cmd_update()
    # invocation, propagated to every heartbeat this run writes (both
    # branches below). Additive alongside pipeline_runs' existing
    # (hook_name, run_date) natural key -- see the design-lock record this
    # implements. Not used for anything else in this function; a shared
    # value threaded through only so future TR-08/TR-17 work has it without
    # another schema change.
    run_id = str(uuid.uuid4())

    # OI-9 / TR-11 (KIRAN_CLEANUP_AUDIT.md 88): resolve the commit SHA
    # producing this run once, stamp it on every heartbeat below, and record
    # a deployment_identity marker carrying it plus the local working-tree
    # state. $GITHUB_SHA on an Actions runner, else the checkout's .git/HEAD,
    # else None -- never a guess. A dirty local tree is logged loudly but does
    # NOT block the run in v1 (the local path is being deprecated to a mirror;
    # the value here is the record, per the OI-9 spec).
    code_version = resolve_code_version()
    _set_run_code_version(code_version)
    _tree_state, _tree_files = _working_tree_state()
    logger.info("cmd_update run_id=%s code_version=%s working_tree=%s",
                run_id, code_version or "unknown", _tree_state)
    if _tree_state == "dirty":
        logger.warning(
            "LOCAL WORKING TREE DIRTY at production write -- code_version=%s, "
            "modified tracked .py: %s. The running code does not match a "
            "reviewed commit; see Trust Register OI-9.",
            code_version or "unknown", ", ".join(_tree_files[:10]),
        )
    try:
        from datetime import date as _date_cls_di
        _di_detail = f"code_version={code_version or 'unknown'}; working_tree={_tree_state}"
        if _tree_state == "dirty":
            _di_detail += f" ({', '.join(_tree_files[:10])})"
        _record_hook("deployment_identity", _date_cls_di.today().isoformat(),
                     detail=_di_detail, run_id=run_id, code_version=code_version)
    except Exception as exc:
        logger.debug("deployment_identity heartbeat failed: %s", exc)

    # TR-01/TR-12 consumer-authority alert (2026-09-02, ledger §109). Option A
    # of the two-option plan: alert immediately, don't block (Option B --
    # Postgres role separation -- is a deferred follow-up). Fires only when
    # this exact process's active backend selector is Postgres AND the OS is
    # Windows -- the one combination that should never legitimately happen
    # (GitHub Actions/Streamlit Cloud never run on Windows), and does not
    # fire for the intentional boring_signals mirror (a separate, opt-in
    # .env read that never touches this variable). See
    # data_health.is_local_windows_pg_write_risk()'s own docstring for why
    # this check, not a positive "is this GitHub Actions" check.
    try:
        from data_health import is_local_windows_pg_write_risk, alert_consumer_authority_violation
        _cmd_update_pg_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
        if is_local_windows_pg_write_risk(_cmd_update_pg_url):
            alert_consumer_authority_violation(
                run_id, code_version,
                detail=f"cmd_update() invoked with a live Postgres URL on a Windows host "
                       f"(run_id={run_id})",
            )
    except Exception as exc:
        logger.debug("consumer-authority check itself failed: %s", exc)

    # init_db()'s statements are all CREATE TABLE/INDEX IF NOT EXISTS --
    # idempotent no-ops once the schema exists, which it always does for a
    # running deployment. But it's the one call in this function that was
    # never wrapped, so a transient DB hiccup here (observed live 2026-08-20:
    # Supabase's nano-tier compute briefly rejecting writes with
    # "cannot execute CREATE TABLE in a read-only transaction") aborted the
    # entire pipeline before any hook -- including ones that don't touch
    # schema at all -- got a chance to run. Nothing downstream depends on
    # this succeeding on any given run, so treat it like every other hook.
    try:
        init_db()
    except Exception as exc:
        logger.warning("init_db() failed (schema already exists on a working "
                        "deployment, so continuing): %s", exc)

    latest_str = get_latest_scraped_date()
    if not latest_str:
        # TR-05 Blocker 1 exit-path audit: deliberately NOT routed through
        # run_freshness_gate(). This is a structurally different operation
        # (one-time historical backfill via cmd_init(), not a completed
        # daily update) -- none of the 12 daily hooks below run in this
        # branch, so there is no completed daily-chain state for the gate to
        # verify yet. main()'s dispatch already treats this return's `None`
        # as "not applicable", not as success -- unchanged, not a new gap.
        logger.info("No existing data — running full init instead.")
        cmd_init()
        return

    from datetime import date as date_cls
    latest_date = date_cls.fromisoformat(latest_str)
    new_dates = dates_since(latest_date)

    if not new_dates:
        logger.info("Database is already up to date (latest: %s).", latest_str)

        # Same-day self-correction: today's row already exists, but the scrape
        # that wrote it may have caught the source before it fully finalized
        # (e.g. a run shortly after PSX's ~15:30 PKT close). Re-fetch and
        # re-upsert just that one date so a later same-day run can still fix
        # it. upsert_prices/upsert_index_prices only allow close to change for
        # a symbol's most-recent date on record, so this is safe to call
        # unconditionally — it's a no-op for any date that already has a
        # newer date on record. Deliberately narrow: does not touch
        # cleanup_ghost_dates, prices_adjusted/suspects, regime, sector/stock
        # signals, setup_log, agent, or leaders scan — those stay skipped
        # exactly as before when there is genuinely nothing new.
        if latest_date == date_cls.today():
            try:
                session = build_session()
                prev_prices = get_latest_prices()
                _cov_rows: list = []
                sector_rows, price_rows, index_rows = scrape_date_range(
                    [latest_date], session, prev_prices=prev_prices, coverage_out=_cov_rows
                )
                upsert_sectors(sector_rows)
                upsert_prices(price_rows)
                if index_rows:
                    upsert_index_prices(index_rows)
                try:      # TR-14.1a -- record completeness for the re-check too
                    from data_health import record_scrape_coverage
                    record_scrape_coverage(_cov_rows, code_version=code_version)
                except Exception as exc:
                    logger.warning("Same-day scrape coverage failed: %s", exc)
                logger.info("Same-day re-check complete for %s.", latest_date)
            except Exception as exc:
                logger.warning("Same-day re-check failed: %s", exc)

        # Still run analysis to auto-save today's support reversal setups if not yet saved
        try:
            result = run_analysis()
            if result:
                _sr_saved = auto_save_setups_with_source(
                    result.get("support_reversal_setups", []),
                    source="Support Reversal"
                )
            else:
                _sr_saved = 0
            # TR-06 Tier 2 (2026-08-24): this producer is currently DISABLED
            # at the source (processor.py's run_analysis() hardcodes
            # support_reversal_setups=[] -- pattern killed 2026-07-23,
            # -1.88% net full-history retest, RESEARCH_LOG.md line 36).
            # There is no live per-symbol scan to report an eligible
            # population for, so coverage_status is honestly
            # NOT_APPLICABLE, not a manufactured EXPECTED/INSUFFICIENT
            # verdict -- see the design-lock record this implements. The
            # heartbeat itself is still meaningful: it is new instrumentation
            # for a call site that previously had none at all, and still
            # answers "did this step run" if the screener is ever re-enabled.
            _record_hook("support_reversal", latest_str, rows_written=_sr_saved,
                         run_id=run_id, execution_status="COMPLETED",
                         coverage_status="NOT_APPLICABLE",
                         detail="screener disabled at source since 2026-07-23")
        except Exception as exc:
            logger.warning("Support Reversal auto-save hook failed: %s", exc)
            _record_hook("support_reversal", latest_str, status="error", detail=str(exc),
                         run_id=run_id, execution_status="FAILED")
        # Still refresh leaders scan (idempotent — safe to re-run)
        try:
            from leaders_scan import run_all as leaders_run_all
            _ls_result = leaders_run_all()
            logger.info("Leaders deep scan updated.")
            _ls_eligible = _ls_result.get("dates_eligible", 0)
            _ls_processed = _ls_result.get("dates_processed", 0)
            _ls_coverage = "EXPECTED" if _ls_processed == _ls_eligible else "INSUFFICIENT"
            _record_hook("leaders_scan", latest_str,
                         run_id=run_id, execution_status="COMPLETED",
                         coverage_status=_ls_coverage,
                         eligible_count=_ls_eligible, processed_count=_ls_processed,
                         detail=(f"failed_dates={_ls_result.get('failed_dates')}"
                                 if _ls_result.get("failed_dates") else None))
        except Exception as exc:
            logger.warning("Leaders deep scan hook failed: %s", exc)
            _record_hook("leaders_scan", latest_str, status="error", detail=str(exc),
                         run_id=run_id, execution_status="FAILED")
        # Rolling trim runs on every night, including no-new-data nights
        try:
            _trim_pg_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
            if _trim_pg_url:
                from database_pg import trim_old_rows_pg
                trim_results = trim_old_rows_pg()
                total_trimmed = sum(n for n in trim_results.values() if n >= 0)
                detail = ", ".join(f"{t}={n}" for t, n in trim_results.items())
                if total_trimmed > 0:
                    logger.info("Rolling trim complete: %d rows deleted (%s)", total_trimmed, detail)
                else:
                    logger.info("Rolling trim: nothing to delete (all tables within 2-year window).")
        except Exception as exc:
            logger.warning("Rolling trim hook failed: %s", exc)

        # TR-05 Blocker 1 correction: this branch runs the same daily hooks
        # (same-day recheck, support_reversal, leaders_scan, rolling trim --
        # "runs on every night, including no-new-data nights", per the
        # comment above) as the normal tail below, so it must complete the
        # same way: through the freshness gate, not a bare early return.
        # Mutually exclusive with the tail's own `return run_freshness_gate()`
        # at the end of this function -- exactly one of the two ever executes
        # per call, so this is not a duplicate gate invocation.
        return run_freshness_gate()

    logger.info("Update: scraping %d new date(s) since %s…", len(new_dates), latest_str)
    session = build_session()
    prev_prices = get_latest_prices()
    _coverage_rows: list = []
    sector_rows, price_rows, index_rows = scrape_date_range(
        new_dates, session, prev_prices=prev_prices, coverage_out=_coverage_rows)

    upsert_sectors(sector_rows)
    upsert_prices(price_rows)
    if index_rows:
        upsert_index_prices(index_rows)
    cleanup_ghost_dates()

    mn, mx = get_price_date_range()
    logger.info(
        "Update complete -- %d symbols, %d price records, date range %s to %s",
        count_sectors(), count_prices(), mn, mx,
    )

    # The trading session every hook below is processing. Recorded against each
    # heartbeat so "last ran" means "last covered this session", not "last
    # executed at some wall-clock time" -- a hook that runs daily but silently
    # processes nothing would otherwise still look healthy.
    _session_date = mx

    # TR-14.1a: record per-date scrape completeness against the source's own
    # per-sector traded-company counts (scraper.parse_sector_counts). Additive
    # this PR -- it does not yet gate anything; TR-14.1b wires a PARTIAL current
    # session into check_all() / the freshness gate. Never fatal.
    try:
        from data_health import record_scrape_coverage
        _cov = record_scrape_coverage(_coverage_rows, code_version=code_version)
        _partial = [r for r in _cov if r["coverage_status"] == "PARTIAL"]
        _unknown = [r for r in _cov if r["coverage_status"] == "UNKNOWN"]
        if _partial:
            logger.warning(
                "scrape coverage: %d PARTIAL date(s) -- %s",
                len(_partial),
                " | ".join(f"{r['scrape_date']}: {r['detail']}" for r in _partial),
            )
        _record_hook(
            "scrape_coverage", _session_date, run_id=run_id,
            execution_status="COMPLETED",
            coverage_status="INSUFFICIENT" if _partial else "EXPECTED",
            eligible_count=len(_cov),
            processed_count=len(_cov) - len(_partial) - len(_unknown),
            detail=(f"{len(_partial)} PARTIAL, {len(_unknown)} UNKNOWN"
                    if (_partial or _unknown) else None),
        )
    except Exception as exc:
        logger.warning("scrape coverage hook failed: %s", exc)

    # Append new prices to prices_adjusted, then scan for corporate action
    # suspects. TR-06 Tier 2 (2026-08-24): split into two independent
    # heartbeats -- previously one heartbeat covered both structurally
    # different operations (append_new_prices_adjusted's own return value was
    # discarded entirely, and a failure in EITHER step produced the same
    # undifferentiated status=error), so an operator could not tell which
    # step actually failed, and the append step -- the one with the stronger
    # coverage guarantee -- had no captured evidence at all. See the
    # design-lock record this implements.
    _pa_pg_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    try:
        if _pa_pg_url:
            from database_pg import ensure_suspects_table_pg, append_new_prices_adjusted_pg
            ensure_suspects_table_pg()
            _n_appended = append_new_prices_adjusted_pg()
        else:
            import sqlite3
            from apply_price_adjustments import ensure_suspects_table, append_new_prices_adjusted
            con = sqlite3.connect(DB_PATH)
            ensure_suspects_table(con)
            _n_appended = append_new_prices_adjusted(con)
            con.close()
        logger.info("prices_adjusted append: %d row(s).", _n_appended)
        # Coverage: append_new_prices_adjusted[_pg] runs a single
        # INSERT...SELECT keyed off "rows in prices newer than
        # prices_adjusted's own MAX(date)" -- eligible and processed are the
        # same computed count by construction: one atomic statement over the
        # identical predicate used to compute the count, no per-row loop
        # that could partially write, so a failure here raises out to this
        # hook's own except block below instead of silently under-writing.
        # Exact-match EXPECTED is a direct consequence of that shape, not a
        # manufactured tolerance.
        _record_hook("corporate_action_append", _session_date, rows_written=_n_appended,
                     run_id=run_id, execution_status="COMPLETED", coverage_status="EXPECTED",
                     eligible_count=_n_appended, processed_count=_n_appended)
    except Exception as exc:
        logger.warning("prices_adjusted append hook failed: %s", exc)
        _record_hook("corporate_action_append", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    try:
        if _pa_pg_url:
            from database_pg import auto_detect_suspects_pg
            n_suspects = auto_detect_suspects_pg()
        else:
            import sqlite3
            from apply_price_adjustments import auto_detect_suspects
            con = sqlite3.connect(DB_PATH)
            n_suspects = auto_detect_suspects(con)
            con.close()
        if n_suspects > 0:
            logger.warning("Corporate action suspects flagged: %d — review required.", n_suspects)
        else:
            logger.info("No new corporate action suspects detected.")
        # Heartbeat, not a findings count. The retired "Last Checked" metric read
        # MAX(suspect_date), so a scan that found nothing was indistinguishable
        # from a scan that never ran -- it sat at 2026-06-22 for two months.
        # n_suspects == 0 is a successful run and must record as one.
        # Coverage: neither backend's auto_detect_suspects[_pg] currently
        # returns or computes a scanned-symbol/date denominator, only the
        # FOUND count (n_suspects), which is legitimately volatile and is
        # not read as a coverage numerator here -- see the design-lock
        # record's explicit instruction not to manufacture one. Recorded as
        # heartbeat evidence only, honestly NOT_APPLICABLE.
        _record_hook("corporate_action_suspects_scan", _session_date, rows_written=n_suspects,
                     run_id=run_id, execution_status="COMPLETED",
                     coverage_status="NOT_APPLICABLE")
    except Exception as exc:
        logger.warning("corporate_action suspects scan hook failed: %s", exc)
        _record_hook("corporate_action_suspects_scan", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Append today's regime row to market_regime
    try:
        from regime import append_latest_regime
        append_latest_regime()
        _record_hook("regime", _session_date, run_id=run_id, execution_status="COMPLETED")
    except Exception as exc:
        logger.warning("Regime hook failed: %s", exc)
        _record_hook("regime", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Backfill days_to_nearest_transition for trade_setups rows where it is still
    # NULL. This column is retrospective-only (requires future transition data) so
    # it cannot be set at insert time; instead we fill it here once the surrounding
    # regime history has had time to accumulate. Rows created within the last ~10
    # trading days may still receive NULL if the nearest future transition hasn't
    # occurred yet — that is correct and expected behaviour.
    try:
        from backfill_regime_columns import backfill_days_to_nearest
        backfill_days_to_nearest()
    except Exception as exc:
        logger.warning("days_to_nearest_transition backfill hook failed: %s", exc)

    # Scrape today's FIPI / LIPI flows so sector_signals can use them
    try:
        from page_flows import scrape_flows_today
        flow_result = scrape_flows_today()
        logger.info(
            "Flow scrape complete — rows_saved=%d, failed=%d",
            flow_result["rows_saved"],
            flow_result["failed"],
        )
    except Exception as exc:
        logger.warning("Flow scrape hook failed: %s", exc)

    # Append today's sector signals
    try:
        sector_signals.append_latest_sector_signals()
        _record_hook("sector_signals", _session_date, run_id=run_id, execution_status="COMPLETED")
    except Exception as exc:
        logger.warning("Sector signals hook failed: %s", exc)
        _record_hook("sector_signals", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Append today's stock signals
    try:
        stock_signals.append_latest_stock_signals()
        _record_hook("stock_signals", _session_date, run_id=run_id, execution_status="COMPLETED")
    except Exception as exc:
        logger.warning("Stock signals hook failed: %s", exc)
        _record_hook("stock_signals", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Recovery Bases + Portfolio signals (signal_engine.py). Previously had no
    # automated caller at all -- see docs/KIRAN_CLEANUP_AUDIT.md 30 -- so
    # recovery_signals/portfolio_signals only updated when someone ran
    # `python signal_engine.py` by hand (last done 2026-07-01).
    try:
        import signal_engine
        _se_results = signal_engine.main()
        _rec = _se_results.get("recovery_signals", {})
        _port = _se_results.get("portfolio_signals", {})
        logger.info(
            "Signal engine: recovery=%s (rows=%s)  portfolio=%s (rows=%s)",
            _rec.get("status"), _rec.get("rows_written"),
            _port.get("status"), _port.get("rows_written"),
        )
        # Previously zero monitoring on either backend for either table (see
        # docs/KIRAN_CLEANUP_AUDIT.md §37-39, §44) -- a dead signal_engine.main()
        # call and a successful one that wrote nothing were indistinguishable
        # from the outside. Record each sub-signal's own reported status, not
        # just "the wrapping try block didn't raise" -- signal_engine.main()
        # catches each sub-signal's exception internally and reports status in
        # the dict, so this except block below only fires for something
        # signal_engine.py itself didn't anticipate.
        _record_hook("recovery_signals", _session_date,
                     status="ok" if _rec.get("status") == "ok" else "error",
                     execution_status="COMPLETED" if _rec.get("status") == "ok" else "FAILED",
                     rows_written=_rec.get("rows_written"),
                     detail=_rec.get("message"), run_id=run_id)
        _record_hook("portfolio_signals", _session_date,
                     status="ok" if _port.get("status") == "ok" else "error",
                     execution_status="COMPLETED" if _port.get("status") == "ok" else "FAILED",
                     rows_written=_port.get("rows_written"),
                     detail=_port.get("message"), run_id=run_id)
    except Exception as exc:
        logger.warning("Signal engine hook failed: %s", exc)
        _record_hook("recovery_signals", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")
        _record_hook("portfolio_signals", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Append today's setups to setup_log and label outcomes
    try:
        from backfill_setup_log import append_setup_log_today
        _sl_result = append_setup_log_today()
        # TR-06 Tier 2 (2026-08-24): append_setup_log_today() now returns a
        # dict (was a bare inserted-row int). Coverage: all 4 setup-detection
        # queries are single SQL statements over the whole stock_signals
        # population for a date, not a per-row loop, so the only genuine
        # partial-processing signal this hook's shape can produce is whether
        # every pending date was reached before an early transient-error
        # break -- eligible_count is recorded as denominator evidence
        # alongside it, not because a different processed value is
        # independently possible for a single date that did run.
        _sl_coverage = "EXPECTED" if _sl_result.get("completed_all_pending_dates") else "INSUFFICIENT"
        _record_hook("setup_log", _session_date, rows_written=_sl_result.get("inserted"),
                     run_id=run_id, execution_status="COMPLETED", coverage_status=_sl_coverage,
                     eligible_count=_sl_result.get("eligible_count"),
                     processed_count=(_sl_result.get("eligible_count")
                                      if _sl_result.get("completed_all_pending_dates") else None))
    except Exception as exc:
        logger.warning("setup_log hook failed: %s", exc)
        _record_hook("setup_log", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Boring Breakouts (RS_60-conditioned Donchian) -- scan for new signals,
    # then advance status on anything already open (Target Hit/Stopped/Expired).
    # Watch-and-manually-execute, not wired into leaders_scan/agent. Ported to
    # Postgres 2026-08-21 -- scan_boring_breakouts_pending()/
    # update_open_signal_statuses() now branch on _PG_URL internally, so this
    # runs for real against Supabase when GitHub Actions calls it, not just
    # local Task Scheduler runs.
    try:
        # scan_boring_breakouts_pending(), not scan_boring_breakouts(): the
        # latter scans the newest date only, so any day this hook missed was
        # never scanned again (audit §25). Resume is now a pure set-difference
        # against boring_signals_scanned -- no bounded window, no silent loss
        # past 15 days (TR-13/OI-6, audit §77).
        from boring_signals import (scan_boring_breakouts_pending,
                                    update_open_signal_statuses,
                                    LONG_GAP_ALERT_DAYS)
        n_new, _bs_eligible, _bs_processed = scan_boring_breakouts_pending(
            return_coverage=True, run_id=run_id)
        n_updated = update_open_signal_statuses()
        logger.info("Boring Breakouts: %d new signal(s), %d status update(s).", n_new, n_updated)
        # mirror_to_postgres: kept as a heartbeat even now that boring_signals
        # itself writes to Supabase directly -- lets the Cloud banner
        # distinguish "hook ran, zero signals fired" from "hook didn't run".
        # Coverage:
        #   * dates_processed < dates_eligible  -> stopped early on a transient
        #     failure (a real, otherwise-invisible partial-completion state).
        #   * dates_eligible > LONG_GAP_ALERT_DAYS -> a long catch-up: >15
        #     trading dates were pending in one run (an extended outage, or the
        #     very first run after this marker was introduced). Surfaced as
        #     INSUFFICIENT so it is visible, not silent -- self-resolves once
        #     the backlog is scanned and daily eligible drops back to ~1.
        # n_new (signals found) is NOT the coverage numerator -- it is
        # legitimately volatile business output, per this hook's own docstring.
        if _bs_processed != _bs_eligible:
            _bs_coverage, _bs_detail = "INSUFFICIENT", (
                f"stopped early: {_bs_processed}/{_bs_eligible} pending dates scanned")
        elif _bs_eligible > LONG_GAP_ALERT_DAYS:
            _bs_coverage, _bs_detail = "INSUFFICIENT", (
                f"long scan gap: {_bs_eligible} trading dates were pending in one run")
        else:
            _bs_coverage, _bs_detail = "EXPECTED", None
        _record_hook("boring_signals", _session_date, rows_written=n_new, detail=_bs_detail,
                     mirror_to_postgres=True, run_id=run_id, execution_status="COMPLETED",
                     coverage_status=_bs_coverage,
                     eligible_count=_bs_eligible, processed_count=_bs_processed)
    except Exception as exc:
        logger.warning("Boring Breakouts hook failed: %s", exc)
        _record_hook("boring_signals", _session_date, status="error", detail=str(exc),
                     mirror_to_postgres=True, run_id=run_id, execution_status="FAILED")

    # Run daily agent analysis in a subprocess so it cannot block the pipeline.
    # Agent is bonus — a timeout or API failure must never stop stock_signals / setup_log
    # from completing. Timeout is 360s (4 sequential LLM calls × ~60s worst-case each + margin).
    try:
        import subprocess as _sp
        _agent_proc = _sp.run(
            [sys.executable, "agent.py", "--type", "daily"],
            timeout=360,
            check=False,
            capture_output=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if _agent_proc.returncode == 0:
            logger.info("Agent daily hook: complete.")
        else:
            logger.warning(
                "Agent daily hook: exited %d — %s",
                _agent_proc.returncode,
                (_agent_proc.stderr or b"")[-500:].decode("utf-8", errors="replace"),
            )
    except Exception as exc:
        logger.warning("Agent daily hook failed (will retry next run): %s", exc)

    # Pre-compute Leaders deep scan (filtered picks + audit trail)
    try:
        from leaders_scan import run_all as leaders_run_all
        _ls_result = leaders_run_all()
        logger.info("Leaders deep scan updated.")
        # TR-06 Tier 2 (2026-08-24): run_all() now returns eligible/processed
        # date counts and never silently swallows a per-date failure (was a
        # bare print() with nothing propagated -- see leaders_scan.py's
        # run_all() docstring for the full fix rationale).
        _ls_eligible = _ls_result.get("dates_eligible", 0)
        _ls_processed = _ls_result.get("dates_processed", 0)
        _ls_coverage = "EXPECTED" if _ls_processed == _ls_eligible else "INSUFFICIENT"
        _record_hook("leaders_scan", _session_date,
                     run_id=run_id, execution_status="COMPLETED",
                     coverage_status=_ls_coverage,
                     eligible_count=_ls_eligible, processed_count=_ls_processed,
                     detail=(f"failed_dates={_ls_result.get('failed_dates')}"
                             if _ls_result.get("failed_dates") else None))
    except Exception as exc:
        logger.warning("Leaders deep scan hook failed: %s", exc)
        _record_hook("leaders_scan", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Auto-save today's support reversal setups
    try:
        result = run_analysis()
    except Exception as exc:
        logger.warning("run_analysis hook failed: %s", exc)
        result = None
    try:
        if result:
            _sr_saved = auto_save_setups_with_source(
                result.get("support_reversal_setups", []),
                source="Support Reversal"
            )
        else:
            _sr_saved = 0
        # TR-06 Tier 2 (2026-08-24): see the early-return branch's identical
        # comment above -- this producer is currently DISABLED at the source
        # (processor.py's run_analysis() hardcodes support_reversal_setups=[]
        # since 2026-07-23), so coverage_status is honestly NOT_APPLICABLE.
        _record_hook("support_reversal", _session_date, rows_written=_sr_saved,
                     run_id=run_id, execution_status="COMPLETED",
                     coverage_status="NOT_APPLICABLE",
                     detail="screener disabled at source since 2026-07-23")
    except Exception as exc:
        logger.warning("Support Reversal auto-save hook failed: %s", exc)
        _record_hook("support_reversal", _session_date, status="error", detail=str(exc),
                     run_id=run_id, execution_status="FAILED")

    # Regenerate market breadth oscillator data for Regime page
    try:
        import subprocess
        subprocess.run(
            [sys.executable, "market_breadth_oscillator.py"],
            timeout=300,
            check=False,
            capture_output=True,
        )
        logger.info("Market breadth oscillator data updated.")
    except Exception as exc:
        logger.warning("Breadth oscillator update failed: %s", exc)

    # Rolling trim — delete rows older than 2 years from large Supabase tables.
    # Runs LAST so trimming never races against any earlier step's reads.
    # Failure is logged but never crashes the pipeline.
    try:
        _trim_pg_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
        if _trim_pg_url:
            from database_pg import trim_old_rows_pg
            trim_results = trim_old_rows_pg()
            total_trimmed = sum(n for n in trim_results.values() if n >= 0)
            detail = ", ".join(f"{t}={n}" for t, n in trim_results.items())
            if total_trimmed > 0:
                logger.info("Rolling trim complete: %d rows deleted (%s)", total_trimmed, detail)
            else:
                logger.info("Rolling trim: nothing to delete (all tables within 2-year window).")
    except Exception as exc:
        logger.warning("Rolling trim hook failed: %s", exc)

    # TR-05 Blocker 1: cmd_update()'s own end-of-run self-check. Runs last,
    # after every hook above -- their existing per-hook try/except-and-warn
    # behavior is untouched, and this step does not affect whether any of
    # them ran. Extracted to its own function (rather than inlined here) so
    # it is independently unit-testable with injected fetch/check functions,
    # without exercising the rest of this ~470-line function.
    return run_freshness_gate(run_id=run_id, code_version=code_version)


def run_freshness_gate(
    fetch_expected_session=None,
    check_all_fn=None,
    run_id=None,
    code_version=None,
    mirror_to_postgres=False,
) -> bool:
    """TR-05 Blocker 1 -- fail-closed local execution-time freshness gate.

    Reuses data_health.check_all() (the same verdict logic the dashboard's
    serving-time banner already uses) and scraper.get_source_date() (the
    same live-source fetch refresh_manager.py already uses) -- no new
    freshness policy, no duplicated thresholds. Mirrors health_check.py's
    existing role for the Postgres/GitHub-Actions side, closing TR-05's
    "SQLite/local path has zero equivalent" gap.

    fetch_expected_session / check_all_fn: injectable for deterministic
    testing (no live network, no live DB) -- default to the real
    implementations when not supplied.

    Returns True only when the verdict is PUBLICATION_VERIFIED. Any failure
    to even compute a verdict is treated as a failed gate, never as success
    -- CANNOT_VERIFY must never become VERIFIED (TR-05 fail-closed
    semantics).

    TR-08 (2026-09-02, ledger §104): run_id/code_version/mirror_to_postgres
    are new, additive, optional kwargs -- every existing caller (this
    function's own tests included) keeps working unchanged. When run_id is
    supplied, this function also makes the publication decision: reuses the
    SAME verdict this call already computed (never a second live check_all()
    call, which could disagree with the first if source data changed
    between calls) to record whether this run gets promoted to "current
    published state." This is deliberately the one and only call site --
    cmd_update()'s own tail is unchanged (`return run_freshness_gate()`),
    since this function already runs on both backends (branches on
    DATABASE_URL/_PG_URL like every other hook, whether invoked from a local
    `main.py --update` or the GitHub Actions Postgres path).
    """
    from data_health import (
        check_all, publication_status, PUBLICATION_VERIFIED, PUBLICATION_CANNOT_VERIFY,
        scrape_coverage_status, decide_and_record_publication,
        mandatory_tables_coherence, COHERENCE_COHERENT,
    )

    def _record_decision(status: str, expected: str | None) -> None:
        if run_id is None:
            return
        try:
            completeness = scrape_coverage_status(expected) if expected else None
            # SHADOWMODE_SPEC_DRAFT.md §5.1 -- record whether every
            # every-session MANDATORY table carried data through the same
            # session date. Detail (which table lagged) goes to the log, the
            # bare status to the record. Does not gate promotion.
            coherence, coherence_detail = mandatory_tables_coherence(expected)
            if coherence != COHERENCE_COHERENT:
                logger.warning(
                    "PUBLICATION COHERENCE %s at run %s -- %s",
                    coherence, run_id, coherence_detail or "no detail",
                )
            decide_and_record_publication(
                run_id=run_id, code_version=code_version, source_as_of=expected,
                freshness_status=status, completeness_status=completeness,
                mirror_to_postgres=mirror_to_postgres,
                coherence_status=coherence,
            )
        except Exception as exc:
            logger.debug("publication decision recording failed: %s", exc)

    if check_all_fn is None:
        check_all_fn = check_all

    def _default_fetch_expected_session():
        session = build_session()
        source_date = get_source_date(session)
        return source_date.strftime("%Y-%m-%d") if source_date else None

    if fetch_expected_session is None:
        fetch_expected_session = _default_fetch_expected_session

    try:
        _fresh_expected = fetch_expected_session()
        _fresh_src_err = None if _fresh_expected else "ksestocks unreachable from local chain"
        _fresh_verdict = check_all_fn(expected_session=_fresh_expected, source_error=_fresh_src_err)
        _fresh_status = publication_status(_fresh_verdict)
    except Exception as exc:
        logger.error("FRESHNESS GATE COULD NOT RUN -- treating as failure: %s", exc)
        _record_decision(PUBLICATION_CANNOT_VERIFY, None)
        return False

    if _fresh_status != PUBLICATION_VERIFIED:
        _fresh_detail = "; ".join(
            f"{i.label}: {i.status} ({i.detail})" for i in _fresh_verdict.failures
        ) or "no detail available"
        logger.error(
            "FRESHNESS GATE FAILED (%s) -- local production update did not reach a "
            "verified-fresh state. expected=%s | %s",
            _fresh_status, _fresh_verdict.expected, _fresh_detail,
        )
        _record_decision(_fresh_status, _fresh_verdict.expected)
        return False

    logger.info(
        "Freshness gate passed -- state verified fresh as of %s.",
        _fresh_verdict.expected,
    )
    _record_decision(_fresh_status, _fresh_verdict.expected)
    return True


def cmd_report():
    """Print sector performance ranking to terminal."""
    result = run_analysis()
    if not result:
        print("No data. Run: python main.py --init")
        return
    sector_df = result["sector_df"]
    breadth   = result["breadth"]
    if breadth:
        print(f"\nMarket Condition: {breadth['emoji']} {breadth['condition']}"
              f"  |  Breadth score: {breadth['breadth_score']:.0f}/100"
              f"  |  Stocks positive: {breadth['stock_pct_pos']}%"
              f"  |  Sectors positive: {breadth['sector_pct_pos']}%")
    print_sector_report(sector_df)


def cmd_schedule():
    """Start APScheduler to run --update daily at configured time (blocking)."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error("APScheduler not installed. Run: pip install apscheduler")
        sys.exit(1)

    scheduler = BlockingScheduler(timezone=SCHEDULER_TIMEZONE)

    def job():
        logger.info("Scheduled run triggered at %s", datetime.now())
        try:
            cmd_update()
            cmd_report()
        except Exception as exc:
            logger.exception("Scheduled job failed: %s", exc)

    scheduler.add_job(
        job,
        CronTrigger(
            hour=SCHEDULER_HOUR,
            minute=SCHEDULER_MINUTE,
            timezone=SCHEDULER_TIMEZONE,
        ),
        id="psx_daily_update",
        name="PSX Daily Sector Update",
        misfire_grace_time=3600,
        coalesce=True,
    )

    logger.info(
        "Scheduler started — will run daily at %02d:%02d %s. Press Ctrl+C to stop.",
        SCHEDULER_HOUR, SCHEDULER_MINUTE, SCHEDULER_TIMEZONE,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PSX Sector Performance Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--init",     action="store_true", help="Initial history scrape")
    group.add_argument("--update",   action="store_true", help="Incremental daily update")
    group.add_argument("--report",   action="store_true", help="Print sector rankings")
    group.add_argument("--schedule", action="store_true", help="Start daily scheduler")
    group.add_argument("--all",      action="store_true", help="Update then report")
    group.add_argument("--agent",    action="store_true", help="Run Claude trading agent (daily analysis)")
    group.add_argument("--agent-weekly",  action="store_true", help="Run Claude agent — weekly deep-dive")
    group.add_argument("--agent-monthly", action="store_true", help="Run Claude agent — monthly review")
    p.add_argument("--force", action="store_true", help="With --init: re-scrape even if data exists")
    return p


def cmd_agent(run_type: str = "daily"):
    """Run the Claude trading agent."""
    try:
        from agent import TradingDeskAgent
    except ImportError as e:
        logger.error("Could not import agent: %s", e)
        return
    agent = TradingDeskAgent(run_type=run_type)
    result = agent.run()
    if result and result.get("narrative"):
        logger.info("Agent run complete — %d opportunities generated.", len(result.get("opportunities", [])))
    else:
        logger.warning("Agent run returned no results.")


def main():
    args = build_parser().parse_args()

    if args.init:
        cmd_init(force=args.force)
    elif args.update:
        # TR-05 Blocker 1: cmd_update() now returns False when its terminal
        # freshness gate fails (or True on a normal completed run; None on
        # the early cmd_init()-redirect bootstrap path, which is not a
        # freshness-gate outcome and must not be treated as a failure).
        if cmd_update() is False:
            sys.exit(1)
    elif args.report:
        cmd_report()
    elif args.schedule:
        cmd_schedule()
    elif args.all:
        ok = cmd_update()
        cmd_report()
        if ok is False:
            sys.exit(1)
    elif args.agent:
        cmd_agent("daily")
    elif args.agent_weekly:
        cmd_agent("weekly")
    elif args.agent_monthly:
        cmd_agent("monthly")


if __name__ == "__main__":
    main()
