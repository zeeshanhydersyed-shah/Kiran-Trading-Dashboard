"""
ARCHIVED — a one-time, already-used repair script, neutralized 2026-09-02
(TR-12, ledger §107).

Directly ran UPDATE/DELETE against `prices`/`index_prices` to fix a
one-time mislabeled-date incident. Named as a candidate for archiving in
the original 2026-08-21 architecture review (§40.6: "already-used, one-time
scripts with no ongoing purpose; leaving them live and executable is
unforced risk for zero remaining benefit") but that step was never actually
executed until now.

Confirmed unreferenced by any current code path before this change. Moved
here rather than deleted (archive-don't-delete, same convention as
ARCHIVED_PSX_SCRAPER/ and ARCHIVED_main_backups/) and its real body replaced
with this stub so it can no longer execute a production write even if run
directly by mistake.

The original executable content is fully preserved in git history:
    git log --follow -- ARCHIVED_stale_write_scripts/fix_mislabeled_date.py
or the pre-archival commit on `main` (docs/KIRAN_CLEANUP_AUDIT.md §107).
"""

raise RuntimeError(
    "fix_mislabeled_date.py is archived and neutralized (TR-12, ledger §107). "
    "It no longer runs. See this file's module docstring for the original "
    "content's location in git history."
)
