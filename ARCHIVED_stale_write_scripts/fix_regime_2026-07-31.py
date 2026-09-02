"""
ARCHIVED — a one-time, already-used repair script, neutralized 2026-09-02
(TR-12, ledger §107).

Fixed a one-time production Postgres data-corruption incident (2 corrupted
KSE-100 `index_prices` rows, docs/KIRAN_CLEANUP_AUDIT.md §16). Directly
connects via psycopg2 and writes hardcoded correction values. Was found
sitting inside `backups/` (git-tracked despite that directory generally
being gitignored -- committed before the ignore rule existed) with
`DRY_RUN = False` -- i.e. **armed**, not reset to a safe default after its
original 2026-07-31 run, unlike the discipline this project otherwise
follows. A genuinely uncatalogued risk -- the 2026-08-21 architecture
review's script inventory (§40.1) did not find this one.

Confirmed unreferenced by any current code path before this change. Moved
here rather than deleted (archive-don't-delete, same convention as
ARCHIVED_PSX_SCRAPER/ and ARCHIVED_main_backups/) and its real body replaced
with this stub so it can no longer execute a production write even if run
directly by mistake -- closing both the "still executable" risk and the
"armed by default" risk in one step.

The original executable content is fully preserved in git history:
    git log --follow -- ARCHIVED_stale_write_scripts/fix_regime_2026-07-31.py
or the pre-archival commit on `main` (docs/KIRAN_CLEANUP_AUDIT.md §107).
"""

raise RuntimeError(
    "fix_regime_2026-07-31.py is archived and neutralized (TR-12, ledger §107). "
    "It no longer runs. See this file's module docstring for the original "
    "content's location in git history."
)
