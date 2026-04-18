#!/usr/bin/env bash
# TMScanner — setup and run (Linux / macOS)
set -e

cd "$(dirname "$0")"

echo "============================================"
echo " TM Scanner - Setup and Run"
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
echo "Using: $($PY --version)"

# ─── .env check ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cat <<'EOF'

ERROR: .env file not found.
  1. Copy .env-sample to .env:     cp .env-sample .env
  2. Open .env and fill in your values
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

# ─── Install Python deps ──────────────────────────────────────────────────────
echo ""
echo "Installing Python dependencies..."
$PY -m pip install -r requirements.txt

echo ""
echo "Installing Playwright browser..."
$PY -m playwright install chromium

# ─── Start Mongo + Redis ──────────────────────────────────────────────────────
echo ""
echo "Starting MongoDB + Redis (Docker)..."
docker compose up -d

# ─── Dashboard in background ──────────────────────────────────────────────────
echo ""
echo "Starting dashboard in the background..."
$PY web/app.py >dashboard.log 2>&1 &
DASH_PID=$!
echo "  Dashboard PID: $DASH_PID  (logs → dashboard.log)"

cleanup() {
    echo ""
    echo "Stopping dashboard (PID $DASH_PID)..."
    kill "$DASH_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ─── Scanner in foreground ────────────────────────────────────────────────────
echo ""
echo "Starting scanner... Press Ctrl+C to stop."
echo ""
$PY scanner.py
