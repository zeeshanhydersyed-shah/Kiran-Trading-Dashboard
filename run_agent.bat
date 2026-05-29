@echo off
REM ── PSX Trading Desk Agent — Daily Runner ────────────────────────────────────
REM Run this each morning AFTER the data update (run_update.bat).
REM Or add it to Windows Task Scheduler as a second step.
REM
REM Prerequisites:
REM   pip install anthropic
REM   ANTHROPIC_API_KEY set in C:\Users\Lenovo\psx_pipeline\.env
REM ─────────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

echo [%DATE% %TIME%] Starting PSX Agent run...

python agent.py --type daily

if %ERRORLEVEL% EQU 0 (
    echo [%DATE% %TIME%] Agent completed successfully.
) else (
    echo [%DATE% %TIME%] Agent run FAILED with error code %ERRORLEVEL%.
)
