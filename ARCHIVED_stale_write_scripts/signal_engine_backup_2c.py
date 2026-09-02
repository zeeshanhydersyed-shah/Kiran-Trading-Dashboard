"""
ARCHIVED — stale duplicate of signal_engine.py, neutralized 2026-09-02
(TR-12, ledger §107).

This file was a full, independently-runnable snapshot of signal_engine.py
(865 lines, last modified 2026-07-29) sitting in the repo root — capable of
writing straight to `recovery_signals`/`portfolio_signals` outside the
orchestrated pipeline, completely uncatalogued by the 2026-08-21
architecture review (which found the 4 main_backup_e8*.py files but missed
this one and 4 others like it). A second, even newer duplicate
(signal_engine_backup_e6.py) was found and archived alongside it.

Confirmed unreferenced by any current code path before this change. Moved
here rather than deleted (archive-don't-delete, same convention as
ARCHIVED_PSX_SCRAPER/ and ARCHIVED_main_backups/) and its real body replaced
with this stub so it can no longer execute a production write even if run
directly by mistake.

The original executable content is fully preserved in git history:
    git log --follow -- ARCHIVED_stale_write_scripts/signal_engine_backup_2c.py
or the pre-archival commit on `main` (docs/KIRAN_CLEANUP_AUDIT.md §107).
"""

raise RuntimeError(
    "signal_engine_backup_2c.py is archived and neutralized (TR-12, "
    "ledger §107). It no longer runs. See this file's module docstring for the "
    "original content's location in git history."
)
