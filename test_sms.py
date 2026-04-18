"""Quick smoke-test: sends a Telegram message to verify the bot works."""
import urllib.request
import urllib.parse
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

text   = "*TM Scanner: test*\nTelegram alerts are working!"
params = urllib.parse.urlencode({
    "chat_id":    TELEGRAM_CHAT_ID,
    "text":       text,
    "parse_mode": "Markdown",
}).encode()
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

try:
    with urllib.request.urlopen(url, data=params, timeout=10) as r:
        r.read()
    print("✓ Telegram message sent — check your phone.")
except Exception as e:
    print(f"✗ Failed: {e}")
