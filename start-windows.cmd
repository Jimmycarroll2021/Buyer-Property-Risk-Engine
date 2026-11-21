@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3.12 -m venv .venv
if errorlevel 1 py -3.13 -m venv .venv
if errorlevel 1 python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.lock
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --no-deps -e .
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m riskengine init
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m riskengine demo
if errorlevel 1 goto failed
echo.
echo Opening your workspace in the browser. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m riskengine serve --desktop
exit /b %errorlevel%
:failed
echo Setup failed. See README.md. Python 3.12 or 3.13 is required.
pause
exit /b 1

