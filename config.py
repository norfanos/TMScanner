"""
Loads configuration from `.env`.  If `.env` does not exist, exits with a clear
message pointing to `.env.sample`.  Import this module from anywhere that
needs a config value.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
_ENV  = _ROOT / ".env"

if not _ENV.exists():
    sys.stderr.write(
        "\n"
        "╔══════════════════════════════════════════════════════════════════╗\n"
        "║  ERROR: .env file not found.                                     ║\n"
        "╠══════════════════════════════════════════════════════════════════╣\n"
        "║  1. Copy `.env-sample` to `.env`                                 ║\n"
        "║       copy .env-sample .env       (Windows CMD)                  ║\n"
        "║       cp   .env-sample .env       (Mac / Linux / Git Bash)       ║\n"
        "║                                                                  ║\n"
        "║  2. Open `.env` in any text editor and fill in your values.      ║\n"
        "║                                                                  ║\n"
        "║  3. Re-run the program.                                          ║\n"
        "║                                                                  ║\n"
        "║  See README.md for full setup instructions.                      ║\n"
        "╚══════════════════════════════════════════════════════════════════╝\n\n"
    )
    sys.exit(1)

load_dotenv(_ENV)


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        sys.stderr.write(f"\nERROR: `{key}` is missing or empty in .env\n")
        sys.stderr.write("See .env-sample for the expected format.\n\n")
        sys.exit(1)
    return val


# ─── Exported config values ───────────────────────────────────────────────────
SCAN_URL         = _require("SCAN_URL")
SCAN_INTERVAL    = int(_require("SCAN_INTERVAL"))

TELEGRAM_TOKEN   = _require("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = _require("TELEGRAM_CHAT_ID")

MONGO_URL        = os.getenv("MONGO_URL", "mongodb://localhost:27017")
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379")

DASHBOARD_PORT   = int(os.getenv("DASHBOARD_PORT", "8181"))

EVENT_NAME       = os.getenv("EVENT_NAME",  "Event")
EVENT_DATE       = os.getenv("EVENT_DATE",  "")
EVENT_VENUE      = os.getenv("EVENT_VENUE", "")
EVENT_IMAGE      = os.getenv("EVENT_IMAGE", "")
