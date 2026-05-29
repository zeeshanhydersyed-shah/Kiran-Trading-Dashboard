"""
KIRAN Self-Improving Loop.

Runs the full improvement cycle:
  1. Extend the backtest to any newly-scraped dates
  2. Re-train the ML model on the accumulated outcomes
  3. Report a summary of what changed

Designed to run unattended (cron / Task Scheduler / Claude scheduler).
Safe to re-run at any frequency — the backtest engine is resumable
(already-processed dates are skipped) so step 1 is always fast.

Usage:
    python self_improve.py              # run full cycle
    python self_improve.py --report     # report current stats only, no retrain
"""

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(HERE / "self_improve.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("self_improve")


def run(cmd: list[str], label: str) -> int:
    """Run a subprocess, stream output, return exit code."""
    log.info(">>> %s", label)
    result = subprocess.run(
        [sys.executable] + cmd,
        cwd=str(HERE),
        capture_output=False,   # stream to terminal live
    )
    if result.returncode != 0:
        log.error("FAILED: %s (exit %d)", label, result.returncode)
    else:
        log.info("OK: %s", label)
    return result.returncode


def report_stats() -> dict:
    """Pull current stats from the DB and return a summary dict."""
    from database import get_conn

    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM backtest_setups").fetchone()[0]
        triggered = conn.execute(
            "SELECT COUNT(*) FROM backtest_setups "
            "WHERE outcome IN ('Win_Trail','Win_T1','Loss')"
        ).fetchone()[0]
        by_outcome = conn.execute(
            "SELECT outcome, COUNT(*) FROM backtest_setups GROUP BY outcome"
        ).fetchall()
        net_r = conn.execute(
            "SELECT ROUND(SUM(realized_r),1) FROM backtest_setups "
            "WHERE outcome NOT IN ('No_Trigger','Expired')"
        ).fetchone()[0]
        latest_date = conn.execute(
            "SELECT MAX(as_of_date) FROM backtest_setups"
        ).fetchone()[0]

    wins   = sum(n for o, n in by_outcome if o in ("Win_Trail", "Win_T1"))
    losses = sum(n for o, n in by_outcome if o == "Loss")
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

    stats = {
        "total_setups": total,
        "triggered":    triggered,
        "win_rate_pct": round(wr, 1),
        "net_r":        net_r,
        "latest_date":  latest_date,
        "by_outcome":   dict(by_outcome),
    }
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true",
                        help="Print stats only, skip retrain")
    parser.add_argument("--force-retrain", action="store_true",
                        help="Retrain even if no new setups found")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("KIRAN Self-Improvement Cycle  %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    log.info("=" * 60)

    # ── Before stats ──────────────────────────────────────────────────────────
    before = report_stats()
    log.info("BEFORE: %d total setups | %d triggered | WR=%.1f%% | Net R=%.1f | Latest=%s",
             before["total_setups"], before["triggered"],
             before["win_rate_pct"], before["net_r"] or 0,
             before["latest_date"])

    if args.report:
        log.info("--report flag set. Skipping backtest and retrain.")
        _print_report(before)
        return

    # ── Step 1: Extend backtest (resumable — skips already-done dates) ────────
    rc = run(["backtest.py"], "Backtest extension (new dates only)")
    if rc != 0:
        log.error("Backtest step failed. Aborting self-improvement cycle.")
        sys.exit(rc)

    # ── After stats ───────────────────────────────────────────────────────────
    after = report_stats()
    new_setups = after["total_setups"] - before["total_setups"]
    log.info("AFTER : %d total setups (+%d new) | WR=%.1f%% | Net R=%.1f | Latest=%s",
             after["total_setups"], new_setups,
             after["win_rate_pct"], after["net_r"] or 0,
             after["latest_date"])

    # ── Step 2: Retrain ML ────────────────────────────────────────────────────
    if new_setups > 0 or args.force_retrain:
        log.info("New setups found (%d). Re-training ML model...", new_setups)
        rc = run(["phase4_train.py"], "ML model retrain")
        if rc != 0:
            log.warning("ML retrain failed (backtest data preserved — OK to retry).")
    else:
        log.info("No new setups since last run. ML model unchanged (use --force-retrain to override).")

    # ── Summary ───────────────────────────────────────────────────────────────
    _print_report(after)
    log.info("Self-improvement cycle complete.")


def _print_report(stats: dict):
    log.info("-" * 60)
    log.info("KIRAN BACKTEST SUMMARY")
    log.info("  Total setups   : %d", stats["total_setups"])
    log.info("  Triggered      : %d", stats["triggered"])
    log.info("  Win rate       : %.1f%%", stats["win_rate_pct"])
    log.info("  Net R          : %.1f", stats["net_r"] or 0)
    log.info("  Latest date    : %s", stats["latest_date"])
    log.info("  Outcome breakdown:")
    for o, n in sorted(stats["by_outcome"].items(), key=lambda x: -x[1]):
        log.info("    %-12s : %d", o, n)
    log.info("-" * 60)


if __name__ == "__main__":
    main()
