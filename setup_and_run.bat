@echo off
setlocal

echo ============================================
echo  TM Scanner — Rebuild and Run
echo ============================================

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo ERROR: .env file not found.
    echo   1. copy .env-sample .env
    echo   2. Edit .env and fill in your values
    echo   3. Re-run this script
    echo See README.md for full instructions.
    echo.
    pause
    exit /b 1
)

echo.
echo [1/5] Stopping any existing TM Scanner / Dashboard windows...
taskkill /FI "WINDOWTITLE eq TM Dashboard*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq TM Scanner*"   /T /F >nul 2>&1

echo.
echo [2/5] Installing / upgrading Python dependencies...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo [3/5] Ensuring Playwright Chromium is installed...
python -m playwright install chromium

echo.
echo [4/5] Restarting MongoDB + Redis containers...
docker compose down
docker compose up -d
if errorlevel 1 (
    echo ERROR: docker compose failed. Is Docker Desktop running?
    pause
    exit /b 1
)

echo.
echo [5/5] Starting dashboard and scanner in separate windows...
start "TM Dashboard" cmd /k "python web\app.py"

:: Read DASHBOARD_PORT from .env (default 8181)
set "PORT=8181"
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="DASHBOARD_PORT" if not "%%b"=="" set "PORT=%%b"
)

echo   Waiting for dashboard to start on port %PORT% ...
timeout /t 3 /nobreak >nul
start "" "http://localhost:%PORT%"

start "TM Scanner"   cmd /k "python scanner.py"

echo.
echo ============================================
echo  Rebuild complete.
echo  Dashboard : http://localhost:%PORT%  (opened in browser)
echo  Scanner   : running in its own window
echo ============================================
echo.
echo Close those windows (or Ctrl+C inside them) to stop.

endlocal
