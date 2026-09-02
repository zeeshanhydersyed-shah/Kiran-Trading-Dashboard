"""
ARCHIVED — a THIRD live duplicate of migrate_to_supabase.py, neutralized
2026-09-02 (TR-12, ledger §107).

This file was a full, independently-runnable copy of migrate_to_supabase.py
sitting inside `research/` (identical docstring: "One-time migration: copy
all data from the local SQLite DB to Supabase" — same table list: sectors,
prices, index_prices, trade_setups). Its `ON CONFLICT DO NOTHING` inserts
make it "safe to re-run" by its own docstring's framing, but that framing
predates this project's TR-01 single-authority direction -- run today it
would still write straight to real production table names on whichever
Postgres `DATABASE_URL`/`SUPABASE_DB_URL` happens to be set, outside the
orchestrated pipeline. Landed in `research/` most likely via `reorganize.py`
(a one-time file-mover that sweeps "experimental & one-off Python scripts"
into that folder) without anyone separately re-auditing it for write
capability once moved -- a concrete instance of why folder location alone
is not a safety control.

Confirmed unreferenced by any current code path before this change. Moved
here rather than deleted (archive-don't-delete, same convention as
ARCHIVED_PSX_SCRAPER/ and ARCHIVED_main_backups/) and its real body replaced
with this stub so it can no longer execute a production write even if run
directly by mistake.

The original executable content is fully preserved in git history:
    git log --follow -- ARCHIVED_stale_write_scripts/research_migrate_to_supabase.py
or the pre-archival commit on `main` (docs/KIRAN_CLEANUP_AUDIT.md §107).
"""

raise RuntimeError(
    "research/migrate_to_supabase.py is archived and neutralized (TR-12, "
    "ledger §107). It no longer runs. See this file's module docstring for "
    "the original content's location in git history."
)
