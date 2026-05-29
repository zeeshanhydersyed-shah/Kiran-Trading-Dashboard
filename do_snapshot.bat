@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  PSX Platform -- pre_audit_stable_snapshot_2026-05-29
echo ============================================================
echo.

REM ── 1. Backup the SQLite database ─────────────────────────────
echo [1/5] Backing up psx_data.db ...
if exist psx_data.db (
    if not exist backups mkdir backups
    copy /Y psx_data.db backups\psx_data_backup_2026-05-29.db
    if %errorlevel%==0 (
        echo       OK -- backups\psx_data_backup_2026-05-29.db
    ) else (
        echo       WARNING: DB copy failed. Continuing anyway.
    )
) else (
    echo       INFO: psx_data.db not found locally (cloud-only setup). Skipping.
)
echo.

REM ── 2. Export live schema from SQLite ─────────────────────────
echo [2/5] Exporting live SQLite schema ...
if exist psx_data.db (
    sqlite3 psx_data.db .schema > backups\schema_live_2026-05-29.sql 2>nul
    if %errorlevel%==0 (
        echo       OK -- backups\schema_live_2026-05-29.sql
    ) else (
        echo       INFO: sqlite3 not in PATH. Using pre-built schema file instead.
        echo       (backups\schema_export_2026-05-29.sql already contains full schema)
    )
) else (
    echo       INFO: No local DB -- skipping live schema export.
)
echo.

REM ── 3. Stage all files ────────────────────────────────────────
echo [3/5] Staging all files ...
git add -A
if %errorlevel% neq 0 (
    echo ERROR: git add failed. Is this a git repo?
    pause
    exit /b 1
)
echo       OK -- all files staged
echo.

REM ── 4. Commit ─────────────────────────────────────────────────
echo [4/5] Committing ...
git commit -m "pre_audit_stable_snapshot_2026-05-29" -m "Full system audit completed 2026-05-29. 23 issues found." -m "Critical: live screener produces 0 setups (processor.py label mismatch)." -m "Critical: ML model trained on mean() but live uses median() sector ranking." -m "Snapshot includes: AUDIT_REPORT_2026-05-29.md, SNAPSHOT.md, schema export, DB backup." -m "No code was changed by the audit. This is the pre-fix baseline."
if %errorlevel% neq 0 (
    echo INFO: Nothing new to commit, or commit failed.
    echo       (This is OK if everything was already committed.)
)
echo.

REM ── 5. Tag the commit ────────────────────────────────────────
echo [5/5] Tagging commit as pre_audit_stable_snapshot_2026-05-29 ...
git tag -a "pre_audit_stable_snapshot_2026-05-29" -m "Stable pre-audit baseline -- 2026-05-29"
if %errorlevel%==0 (
    echo       OK -- tag created
) else (
    echo       INFO: Tag may already exist. Skipping.
)
echo.

REM ── Push ──────────────────────────────────────────────────────
echo Pushing to GitHub (main + tags) ...
git push origin main
git push origin --tags
if %errorlevel%==0 (
    echo       OK -- pushed to GitHub
) else (
    echo       WARNING: Push failed. Check your internet connection or GitHub auth.
    echo       You can push manually with:  git push origin main --tags
)

echo.
echo ============================================================
echo  DONE.
echo  Commit:  pre_audit_stable_snapshot_2026-05-29
echo  Tag:     pre_audit_stable_snapshot_2026-05-29
echo  DB:      backups\psx_data_backup_2026-05-29.db
echo  Schema:  backups\schema_export_2026-05-29.sql
echo  Report:  AUDIT_REPORT_2026-05-29.md
echo ============================================================
echo.
pause
