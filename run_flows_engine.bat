@echo off
REM Kiran Sector Flows Intelligence Engine — daily runner
REM Run after market close, alongside daily_evening.bat
REM Uses importlib to bypass stale .pyc cache

cd /d %~dp0
python -c "
import sys, os, importlib.util
os.chdir(r'%~dp0')
sys.path.insert(0, r'%~dp0')
spec = importlib.util.spec_from_file_location('sfe', r'%~dp0sector_flows_engine.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.run()
"
pause
