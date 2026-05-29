@echo off
:: PSX Daily Update — runs at Windows logon via Task Scheduler
:: Skips Saturday & Sunday. Pakistan holidays are handled gracefully
:: by the scraper (ksestocks returns no data, so they are simply skipped).

:: ── Skip weekends ────────────────────────────────────────────────────────────
for /f "tokens=2 delims==" %%d in (
    'wmic path Win32_LocalTime get DayOfWeek /value 2^>nul'
) do set DOW=%%d
:: DayOfWeek: 0=Sunday, 6=Saturday
if "%DOW%"=="0" exit /b
if "%DOW%"=="6" exit /b

:: ── Wait for internet (up to 3 minutes) ──────────────────────────────────────
set TRIES=0
:wait_net
ping -n 1 8.8.8.8 >nul 2>&1
if errorlevel 1 (
    set /a TRIES+=1
    if %TRIES% GEQ 18 goto no_net
    timeout /t 10 /nobreak >nul
    goto wait_net
)

:: ── Run pipeline ─────────────────────────────────────────────────────────────
cd /d C:\Users\Lenovo\psx_pipeline
echo. >> psx_scheduler.log
echo ===== %DATE% %TIME% ===== >> psx_scheduler.log
python main.py --all >> psx_scheduler.log 2>&1

:: ── Generate Twitter content drafts ──────────────────────────────────────────
echo Generating Twitter content drafts... >> psx_scheduler.log
python content_generator.py >> psx_scheduler.log 2>&1

:: ── Sync actual trades from Excel ────────────────────────────────────────────
echo Syncing actual trades from ASSET ALLOCATION.XLSX... >> psx_scheduler.log
python import_actual_trades.py --file "D:\PERSONAL\Personal Sheets\ASSET ALLOCATION\ASSET ALLOCATION.XLSX" >> psx_scheduler.log 2>&1

:: ── Weekly: agent self-learning loop (Sundays only) ─────────────────────────
if "%DOW%"=="0" (
    echo Running agent self-learning loop... >> psx_scheduler.log
    python agent_learn.py >> psx_scheduler.log 2>&1
)
exit /b

:no_net
echo %DATE% %TIME% - No internet after 3 minutes, skipping. >> C:\Users\Lenovo\psx_pipeline\psx_scheduler.log
exit /b
