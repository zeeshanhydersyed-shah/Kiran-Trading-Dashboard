# Archived, neutralized write-capable scripts (TR-12, batch 2)

Nine files, archived and neutralized 2026-09-02, all confirmed capable of
writing straight to production tables outside the orchestrated pipeline:

- **Five previously-uncatalogued backup/duplicate copies** (`apply_price_adjustments_backup_e85.py`,
  `migrate_to_supabase_backup_e4i.py`, `signal_engine_backup_2c.py`,
  `signal_engine_backup_e6.py`, `research_migrate_to_supabase.py` — a
  *third* live copy of the migration tool, found sitting in `research/`) —
  the same risk class as `../ARCHIVED_main_backups/` (full runnable
  snapshots of write-capable scripts), missed by the 2026-08-21
  architecture review's own script inventory (§40.1).
- **Three already-used, one-time repair scripts** (`fix_mislabeled_date.py`,
  `fix_mixed_date.py`, `fix_paper_actual.py`) — the 2026-08-21 review
  recommended archiving these (§40.6) but that step was never executed.
- **One armed one-time fix** (`fix_regime_2026-07-31.py`) — was sitting with
  `DRY_RUN = False`, not reset to safe-by-default after its original run,
  and git-tracked despite living inside the generally-gitignored `backups/`
  directory (committed before that ignore rule existed).

Archived (not deleted — same convention as `../ARCHIVED_PSX_SCRAPER/` and
`../ARCHIVED_main_backups/`) and neutralized: each file's real body was
replaced with a stub that raises immediately on execution, so none of them
can write to production even if run directly by mistake. Full original
content is preserved in git history — `git log --follow -- ARCHIVED_stale_write_scripts/<filename>`.

Full record: `docs/KIRAN_CLEANUP_AUDIT.md` §107.
