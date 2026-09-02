# Archived, neutralized `main.py` snapshots

These four files (`main_backup_e8.py`, `main_backup_e84b.py`, `main_backup_e85.py`,
`main_backup_e86a.py`) were full, independently-runnable copies of `main.py`
that sat in the repo root — each one a complete, undocumented write path
straight to production tables, outside the orchestrated pipeline. Flagged
during the 2026-08-21 architecture review
([`docs/KIRAN_CLEANUP_AUDIT.md`](../docs/KIRAN_CLEANUP_AUDIT.md) §40.1/§41.3)
and tracked since as Trust Register row TR-12.

Archived (not deleted — same convention as `../ARCHIVED_PSX_SCRAPER/`) and
neutralized 2026-09-02: each file's real body was replaced with a stub that
raises immediately on execution, so none of them can write to production
even if run directly by mistake. Full original content is preserved in git
history — `git log --follow -- ARCHIVED_main_backups/<filename>`.

Full record: `docs/KIRAN_CLEANUP_AUDIT.md` §103.
