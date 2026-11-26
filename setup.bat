@echo off
REM LNG agent environment setup (Windows)
REM Usage: double-click, or run setup.bat from a terminal in this folder
chcp 65001 > nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py > nul 2>&1
if %errorlevel%==0 (
    set PY=py -3
) else (
    set PY=python
)

if not exist .venv (
    echo [1/4] Creating virtual environment .venv
    %PY% -m venv .venv || goto :error
) else (
    echo [1/4] .venv already exists, skipping
)

echo [2/4] Installing packages
.venv\Scripts\python -m pip install --upgrade pip > nul
.venv\Scripts\python -m pip install -r requirements.txt || goto :error

echo [3/4] Generating sample data
.venv\Scripts\python scripts\make_sample_data.py || goto :error

echo [4/4] Running tests
.venv\Scripts\python -m pytest -q tests || goto :error

if not exist .env copy .env.example .env > nul
if not exist .vscode\settings.json (
    if not exist .vscode mkdir .vscode
    > .vscode\settings.json (
        echo {
        echo   "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
        echo   "python.testing.pytestEnabled": true,
        echo   "python.testing.pytestArgs": ["tests"],
        echo   "python.envFile": "${workspaceFolder}\\.env",
        echo   "terminal.integrated.env.windows": { "PYTHONUTF8": "1" }
        echo }
    )
)

echo.
echo Done. Next steps:
echo   - Put UPSTAGE_API_KEY and UPSTAGE_MODEL in .env
echo   - run.bat demo / run.bat chat --offline / run.bat chat
goto :eof

:error
echo.
echo [error] Setup stopped. Check the message above.
exit /b 1
