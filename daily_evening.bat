@echo off
REM ============================================================
REM  PSX Daily Evening Script (run after market close ~15:30 PKT)
REM  Updates outcomes in prediction_log.csv
REM ============================================================

cd /d C:\Users\Lenovo\psx_pipeline

echo [Evening] Updating prediction outcomes...
python part7_prediction_log.py update-outcomes
echo Done.
