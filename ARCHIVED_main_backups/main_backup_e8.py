"""
ARCHIVED — stale snapshot of main.py, neutralized 2026-09-02 (TR-12, ledger §103).

This file was a full, independently-runnable copy of main.py (375 lines, last
modified 2026-06-24) sitting in the repo root — one of four such copies
(main_backup_e8.py / e84b.py / e85.py / e86a.py) found during the 2026-08-21
architecture review (docs/KIRAN_CLEANUP_AUDIT.md §40.1/§41.3) and tracked
since as a Trust Register TR-12 finding: an "undocumented trigger" capable of
writing straight to production tables (SQLite locally, or Postgres if pointed
at DATABASE_URL) completely outside the orchestrated pipeline path.

Confirmed unreferenced by any current code path (no .py/.yml/.bat file
imports or calls it) before this change. Moved here rather than deleted
(archive-don't-delete, same convention as ARCHIVED_PSX_SCRAPER/) and its
`cmd_update()` body + `__main__` entry point removed so it can no longer
execute a production write even if run directly — relocation alone would not
have closed that risk, only relabeled it.

The original executable content is fully preserved in git history:
    git log --follow -- ARCHIVED_main_backups/main_backup_e8.py
or the pre-archival commit on `main` (docs/KIRAN_CLEANUP_AUDIT.md §103).
"""

raise RuntimeError(
    "main_backup_e8.py is archived and neutralized (TR-12, ledger §103). "
    "It no longer runs. See this file's module docstring for the original "
    "content's location in git history."
)
