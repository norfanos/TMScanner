@echo off
echo ============================================
echo  TM Scanner - Setup and Run
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
    echo   1. Copy .env-sample to .env
    echo   2. Open .env and fill in your values
    echo   3. Re-run this script
    echo See README.md for full instructions.
    echo.
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt

echo Installing Playwright browser...
python -m playwright install chromium

echo.
echo Starting MongoDB + Redis (Docker)...
docker compose up -d

echo.
echo Starting dashboard in a separate window...
start "TM Dashboard" python web\app.py

echo.
echo Starting scanner... Press Ctrl+C to stop.
echo.
python scanner.py

pause
