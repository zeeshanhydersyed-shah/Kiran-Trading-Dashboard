@echo off
cd /d C:\Users\Lenovo\psx_pipeline
echo Starting KIRAN...
python -m streamlit run dashboard.py --server.port 8501
pause
