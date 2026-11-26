@echo off
REM Usage: run.bat demo | run.bat chat --offline | run.bat chat | run.bat approve <order_id> --approver name
chcp 65001 > nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    exit /b 1
)
.venv\Scripts\python main.py %*
