@echo off
:: Start the PSX Streamlit dashboard silently at logon.
:: Runs every day including weekends — useful for analysis and brainstorming.
:: Auto-restarts Streamlit if it ever exits (crash guard).

:: ── Wait for network (up to 3 minutes) ───────────────────────────────────────
set TRIES=0
:wait_net
ping -n 1 8.8.8.8 >nul 2>&1
if errorlevel 1 (
    set /a TRIES+=1
    if %TRIES% GEQ 18 exit /b
    timeout /t 10 /nobreak >nul
    goto wait_net
)

:: ── Kill any stale Streamlit process on port 8501 ────────────────────────────
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8501.*LISTENING" 2^>nul') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: ── Watchdog loop: restart Streamlit whenever it exits ────────────────────────
cd /d C:\Users\Lenovo\psx_pipeline
:restart
echo [%DATE% %TIME%] Starting KIRAN dashboard... >> streamlit.log 2>&1
python -m streamlit run dashboard.py --server.port 8501 --server.headless true >> streamlit.log 2>&1
echo [%DATE% %TIME%] Streamlit exited (code %ERRORLEVEL%). Restarting in 15s... >> streamlit.log 2>&1
timeout /t 15 /nobreak >nul
goto restart
