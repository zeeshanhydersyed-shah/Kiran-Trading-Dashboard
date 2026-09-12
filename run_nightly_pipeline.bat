@echo off
:: Kiran Local-First Migration -- Phase 5 nightly orchestration.
:: Runs archive.nightly_run (Bronze ingest -> Silver build -> Gold publish),
:: once per calendar day -- the script's own lock (_nightly_run_state.json)
:: guards against a duplicate same-day run if Task Scheduler's wake-catch-up
:: and the normal nightly trigger both fire close together.
::
:: Registered via Task Scheduler as KIRAN_NIGHTLY_PIPELINE
:: (see archive/nightly_run.py's module docstring for detail).
:: Dead-man's-switch: KIRAN_NIGHTLY_HC_URL (a user env var, set via setx)
:: points this run at a healthchecks.io check; unset is a silent no-op.

:: -- Wait for internet (up to 3 minutes) --------------------------------
set TRIES=0
:wait_net
ping -n 1 8.8.8.8 >nul 2>&1
if errorlevel 1 (
    set /a TRIES+=1
    if %TRIES% GEQ 18 goto no_net
    timeout /t 10 /nobreak >nul
    goto wait_net
)

:: -- Run the nightly pipeline --------------------------------------------
cd /d C:\Users\Lenovo\psx_pipeline
echo. >> nightly_pipeline.log
echo ===== %DATE% %TIME% ===== >> nightly_pipeline.log
python -m archive.nightly_run >> nightly_pipeline.log 2>&1
exit /b

:no_net
echo %DATE% %TIME% - No internet after 3 minutes, skipping. >> C:\Users\Lenovo\psx_pipeline\nightly_pipeline.log
exit /b
