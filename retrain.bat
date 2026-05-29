@echo off
REM ============================================================
REM  PSX Monthly Retraining Script
REM  Runs on: 1st Monday of each month (set via Task Scheduler)
REM
REM  TO SCHEDULE IN WINDOWS:
REM  1. Open Task Scheduler (search in Start menu)
REM  2. Click "Create Basic Task"
REM  3. Name: "PSX Monthly Retrain"
REM  4. Trigger: Monthly → select "First" + "Monday"
REM  5. Action: Start a program
REM     Program: C:\Users\Lenovo\psx_pipeline\retrain.bat
REM  6. Click Finish
REM ============================================================

cd /d C:\Users\Lenovo\psx_pipeline

echo ============================================================
echo  PSX MONTHLY RETRAINING  -  %DATE% %TIME%
echo ============================================================

REM Step 1: Rebuild features with latest data
echo.
echo [1/4] Rebuilding feature dataset...
python part2_feature_engineering.py
if errorlevel 1 (
    echo ERROR in feature engineering. Aborting.
    exit /b 1
)

REM Step 2: Run monthly retrain (retrains BOTH kiran_model.pkl and direction_model.pkl)
echo.
echo [2/4] Retraining models...
echo       - kiran_model.pkl    (setup quality, via phase4_train.py)
echo       - direction_model.pkl (market direction, via part4)
python part4_monthly_retrain.py
if errorlevel 1 (
    echo ERROR in retraining. Aborting.
    exit /b 1
)

REM Step 3: Generate health report
echo.
echo [3/4] Generating model health report...
python part5_model_health.py

REM Step 4: Log today's predictions
echo.
echo [4/4] Logging today's predictions...
python part7_prediction_log.py log-today

echo.
echo ============================================================
echo  Retraining complete. Check model_health_report.txt
echo ============================================================

REM Optional: open the health report in Notepad
REM notepad model_health_report.txt
