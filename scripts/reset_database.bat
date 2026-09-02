@echo off
cd /d "%~dp0\.."
set PYTHONPATH=.
echo ====================================================
echo Resetting Smart Grid SQLite Database
echo ====================================================
python scripts/reset_database.py --all
pause
