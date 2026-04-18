#!/usr/bin/env bash
# TMScanner — rebuild and run (Linux / macOS)
set -e

cd "$(dirname "$0")"

echo "============================================"
echo " TM Scanner — Rebuild and Run"
echo "============================================"

# ─── Python check ─────────────────────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: Python not found. Install from https://python.org"
    exit 1
fi

# ─── .env check ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cat <<'EOF'

ERROR: .env file not found.
  1. cp .env-sample .env
  2. Edit .env and fill in your values
  3. Re-run this script

See README.md for full instructions.

EOF
    exit 1
fi

# ─── Docker check ─────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker not found. Install from https://docs.docker.com/get-docker/"
    exit 1
fi

# ─── [1/5] Stop existing dashboard + scanner ──────────────────────────────────
echo ""
echo "[1/5] Stopping any existing TM Scanner / Dashboard processes..."
pkill -f "web/app.py" 2>/dev/null || true
pkill -f "scanner.py" 2>/dev/null || true

# ─── [2/5] pip deps ───────────────────────────────────────────────────────────
echo ""
echo "[2/5] Installing / upgrading Python dependencies..."
$PY -m pip install --upgrade -r requirements.txt

# ─── [3/5] Playwright ─────────────────────────────────────────────────────────
echo ""
echo "[3/5] Ensuring Playwright Chromium is installed..."
$PY -m playwright install chromium

# ─── [4/5] Docker ─────────────────────────────────────────────────────────────
echo ""
echo "[4/5] Restarting MongoDB + Redis containers..."
docker compose down
docker compose up -d

# ─── [5/5] Launch services ────────────────────────────────────────────────────
echo ""
echo "[5/5] Starting dashboard (background) + scanner (foreground)..."
$PY web/app.py >dashboard.log 2>&1 &
DASH_PID=$!
echo "  Dashboard PID: $DASH_PID  (logs → dashboard.log)"

cleanup() {
    echo ""
    echo "Stopping dashboard (PID $DASH_PID)..."
    kill "$DASH_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 3

# Read DASHBOARD_PORT from .env (default 8181)
PORT=$(grep -E '^DASHBOARD_PORT=' .env | cut -d= -f2 | tr -d '[:space:]')
PORT=${PORT:-8181}

# Open the dashboard in the default browser
URL="http://localhost:$PORT"
if   command -v open     >/dev/null 2>&1; then open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
elif command -v wslview  >/dev/null 2>&1; then wslview "$URL"
fi

echo ""
echo "============================================"
echo " Rebuild complete."
echo " Dashboard : $URL  (opened in browser)"
echo " Scanner   : starting now, Ctrl+C to stop"
echo "============================================"
echo ""
$PY scanner.py
