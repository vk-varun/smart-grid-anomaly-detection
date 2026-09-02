@echo off
cd /d "%~dp0\.."
set PYTHONPATH=.
echo ====================================================
echo Starting Smart Grid Monitoring API and Dashboard
echo Open browser at http://localhost:8000
echo ====================================================
python scripts/start_api.py
pause
