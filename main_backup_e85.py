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
import sys
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
)
from processor import run_analysis, print_sector_report
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


def cmd_update():
    """Scrape only dates that are newer than the last record in the database."""
    init_db()

    latest_str = get_latest_scraped_date()
    if not latest_str:
        logger.info("No existing data — running full init instead.")
        cmd_init()
        return

    from datetime import date as date_cls
    latest_date = date_cls.fromisoformat(latest_str)
    new_dates = dates_since(latest_date)

    if not new_dates:
        logger.info("Database is already up to date (latest: %s).", latest_str)
        # Still run analysis to auto-save today's support reversal setups if not yet saved
        result = run_analysis()
        if result:
            auto_save_setups_with_source(
                result.get("support_reversal_setups", []),
                source="Support Reversal"
            )
        # Still refresh leaders scan (idempotent — safe to re-run)
        try:
            from leaders_scan import run_all as leaders_run_all
            leaders_run_all()
            logger.info("Leaders deep scan updated.")
        except Exception as exc:
            logger.warning("Leaders deep scan hook failed: %s", exc)
        return

    logger.info("Update: scraping %d new date(s) since %s…", len(new_dates), latest_str)
    session = build_session()
    prev_prices = get_latest_prices()
    sector_rows, price_rows, index_rows = scrape_date_range(new_dates, session, prev_prices=prev_prices)

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

    # Append new prices to prices_adjusted and flag corporate action suspects
    try:
        import sqlite3
        from apply_price_adjustments import (
            ensure_suspects_table,
            append_new_prices_adjusted,
            auto_detect_suspects,
        )
        con = sqlite3.connect(DB_PATH)
        ensure_suspects_table(con)
        append_new_prices_adjusted(con)
        n_suspects = auto_detect_suspects(con)
        con.close()
        if n_suspects > 0:
            logger.warning("Corporate action suspects flagged: %d — review required.", n_suspects)
        else:
            logger.info("No new corporate action suspects detected.")
    except Exception as exc:
        logger.warning("prices_adjusted hook failed: %s", exc)

    # Append today's regime row to market_regime
    try:
        from regime import append_latest_regime
        append_latest_regime()
    except Exception as exc:
        logger.warning("Regime hook failed: %s", exc)

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
    except Exception as exc:
        logger.warning("Sector signals hook failed: %s", exc)

    # Append today's stock signals
    try:
        stock_signals.append_latest_stock_signals()
    except Exception as exc:
        logger.warning("Stock signals hook failed: %s", exc)

    # Append today's setups to setup_log and label outcomes
    try:
        from backfill_setup_log import append_setup_log_today
        append_setup_log_today()
    except Exception as exc:
        logger.warning("setup_log hook failed: %s", exc)

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
        leaders_run_all()
        logger.info("Leaders deep scan updated.")
    except Exception as exc:
        logger.warning("Leaders deep scan hook failed: %s", exc)

    # Auto-save today's support reversal setups
    try:
        result = run_analysis()
    except Exception as exc:
        logger.warning("run_analysis hook failed: %s", exc)
        result = None
    if result:
        auto_save_setups_with_source(
            result.get("support_reversal_setups", []),
            source="Support Reversal"
        )

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
        cmd_update()
    elif args.report:
        cmd_report()
    elif args.schedule:
        cmd_schedule()
    elif args.all:
        cmd_update()
        cmd_report()
    elif args.agent:
        cmd_agent("daily")
    elif args.agent_weekly:
        cmd_agent("weekly")
    elif args.agent_monthly:
        cmd_agent("monthly")


if __name__ == "__main__":
    main()
