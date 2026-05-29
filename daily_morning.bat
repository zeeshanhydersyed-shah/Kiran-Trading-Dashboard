@echo off
REM ============================================================
REM  PSX Daily Morning Script (run after Kiran scrapes data)
REM  Logs today's predictions to prediction_log.csv
REM
REM  Add this to your existing morning workflow OR schedule
REM  in Task Scheduler to run at 09:00 PKT (04:00 UTC)
REM ============================================================

cd /d C:\Users\Lenovo\psx_pipeline

echo [Morning] Logging today's PSX predictions...
python part7_prediction_log.py log-today
echo Done.
