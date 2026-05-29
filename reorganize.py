"""
PSX Pipeline — Safe Directory Reorganizer
==========================================
Run this once from C:\\Users\\Lenovo\\psx_pipeline\\:

    python reorganize.py

What it does
------------
Creates 4 subfolders and moves non-core files into them:
  scheduler/  — Windows Task Scheduler XML files
  reports/    — generated report & log text files
  notes/      — personal notes / key files
  research/   — experimental & one-off Python scripts (none imported by core)

What it does NOT touch
-----------------------
  • psx_data.db          (SQLite database)
  • *.pkl                (model files read by dashboard)
  • merged_*.csv         (read by load_bi_history.py)
  • breadth_data.csv     (read by dashboard.py + market_breadth_oscillator.py)
  • feature_importance.csv / prediction_log.csv / features_dataset.csv
  • All *.bat launchers  (paths baked in, leave as-is)
  • Core .py files       (dashboard, processor, database, agent, etc.)
  • .env / .git / .github / .streamlit / __pycache__
  • requirements.txt / runtime.txt / CLAUDE.md / .gitignore
  • Start Kiran.lnk / twitter_output/ folder

Since this is a git repo, you can always undo with:
    git checkout -- .
or inspect changes with:
    git status
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# ── folder → files to move ────────────────────────────────────────────────────
MOVES = {
    "scheduler": [
        "PSX_TaskScheduler.xml",
        "PSX_Dashboard_TaskScheduler.xml",
        "PSX_Dashboard_TaskScheduler_v2.xml",
    ],
    "reports": [
        "merge_report.txt",
        "model_health_report.txt",
        "phase4_report.txt",
    ],
    "notes": [
        "groq key.txt",
        "virtualiztion problem.txt",
    ],
    "research": [
        # simulation variants (not the main kiran_sim.py)
        "kiran_sim_v2.py",
        "kiran_sim_v3.py",
        "kiran_sim_variants.py",
        # support / resistance research runners
        "support_research.py",
        "run_support_research_local.py",
        "run_support_research_fast.py",
        # signal analysis scripts
        "analyze_filtered_signals.py",
        "analyze_strict_trend.py",
        "redefine_trend_and_backtest.py",
        # backtest experiments
        "backtest_breakout_entry.py",
        "backtest_200ma_trailing.py",
        "audit_trailing_stop.py",
        # one-off diagnostic / migration scripts
        "check_bafl.py",
        "check_data.py",
        "inspect_schema.py",
        "query_2020.py",
        "migrate_to_supabase.py",
        "cleanup_supabase.py",
        "kse100_filter.py",
        "self_improve.py",
    ],
}

# ── safety guard — never touch these ─────────────────────────────────────────
PROTECTED = {
    "psx_data.db", "merged_psx_data.csv", "merged_index_data.csv",
    "breadth_data.csv", "feature_importance.csv", "prediction_log.csv",
    "features_dataset.csv", "kiran_model.pkl", "kiran_model_features.pkl",
    "model_validated.pkl", "dashboard.py", "processor.py", "database.py",
    "database_pg.py", "main.py", "scraper.py", "config.py", "weinstein.py",
    "backtest.py", "kiran_sim.py", "load_bi_history.py", "phase4_train.py",
    "portfolio.py", "agent.py", "agent_db.py", "agent_benchmark.py",
    "agent_learn.py", "import_actual_trades.py", "fix_paper_actual.py",
    "page_valuation.py", "page_flows.py", "knowledge_support_resistance.py",
    "market_breadth_oscillator.py", "social_dashboard.py",
    "content_generator.py", "requirements.txt", "runtime.txt",
    ".env", ".gitignore", "CLAUDE.md", "reorganize.py",
}

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no files will be moved\n")

    moved = 0
    skipped = 0
    errors = 0

    for folder_name, files in MOVES.items():
        dest_dir = ROOT / folder_name
        if not dry_run:
            dest_dir.mkdir(exist_ok=True)
        else:
            print(f"[mkdir] {dest_dir.name}/")

        for filename in files:
            src = ROOT / filename

            # safety check
            if filename in PROTECTED:
                print(f"  [SKIP — protected] {filename}")
                skipped += 1
                continue

            if not src.exists():
                print(f"  [SKIP — not found] {filename}")
                skipped += 1
                continue

            dest = dest_dir / filename
            if dest.exists():
                print(f"  [SKIP — already exists in {folder_name}/] {filename}")
                skipped += 1
                continue

            if dry_run:
                print(f"  [move] {filename}  →  {folder_name}/")
                moved += 1
            else:
                try:
                    shutil.move(str(src), str(dest))
                    print(f"  ✓  {filename}  →  {folder_name}/")
                    moved += 1
                except Exception as e:
                    print(f"  ✗  {filename}  ERROR: {e}")
                    errors += 1

    print(f"\n{'─'*50}")
    if dry_run:
        print(f"Dry run complete: {moved} files would be moved, {skipped} skipped.")
        print("Run without --dry-run to apply changes.")
    else:
        print(f"Done: {moved} moved, {skipped} skipped, {errors} errors.")
        if errors == 0:
            print("All good. To undo: git checkout -- .")

if __name__ == "__main__":
    main()
