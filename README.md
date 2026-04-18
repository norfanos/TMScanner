# TMScanner

Watches a **Ticketmaster Exchange** event page in the background, records
ticket prices over time, and sends **Telegram alerts** when the price drops
below a threshold you choose.  A web dashboard shows the current price, the
all-time low, and a chart of the last 24 hours.

- 🎟  Scans GA / GA+ prices every 30 seconds
- 🔔  Instant Telegram alerts when prices fall below your threshold
- 📈  Dashboard with live cards and a trendline chart
- 🔗  One-click "Buy Now" link back to Ticketmaster
- 💾  Price history stored in MongoDB, latest value cached in Redis

---

## 1. What you need before you start

Install these first.  All are free.

| Tool | Why | Where to get it |
|---|---|---|
| **Python 3.10 or newer** | Runs the scanner and dashboard | <https://www.python.org/downloads/> |
| **Docker Desktop** | Runs MongoDB + Redis | <https://www.docker.com/products/docker-desktop/> |
| **A Telegram account** | Receives the alerts | Install the app from your phone's app store |

After installing Python, open a new **PowerShell** window and check the version:

```powershell
python --version
```

You should see something like `Python 3.12.3`.  If you see *"python is not
recognized"*, reinstall Python and tick **"Add Python to PATH"** during setup.

---

## 2. Create your Telegram bot

This takes about 2 minutes.

### Step A — Talk to BotFather

1. Open **Telegram** on your phone or desktop.
2. In the search bar at the top, type `@BotFather` and tap the result
   (it has a blue check-mark — make sure you pick the official one).
3. Tap **Start**.
4. Send the message:  `/newbot`
5. BotFather asks for a **display name**.  Type anything, e.g. `My TM Scanner`.
6. BotFather asks for a **username**.  It must end in `bot`.
   Example: `niks_tm_scanner_bot`.
7. BotFather replies with a message containing an **HTTP API token** that
   looks like this:
   ```
   8096852334:AAFl174axyMvflzBywBP4YSGJNkKnio35MA
   ```
   **Copy this token — you'll paste it into `.env` later.**

### Step B — Find your chat ID

1. Go back to Telegram's main search bar and look up the bot you just made
   (the username that ends in `bot`).  Open the chat.
2. Tap **Start** and send any message, for example: `hi`
3. Open this URL in a web browser, replacing `YOUR_TOKEN_HERE` with the
   token BotFather gave you:

   ```
   https://api.telegram.org/botYOUR_TOKEN_HERE/getUpdates
   ```

4. You'll see a JSON response.  Look for the `"chat"` section:
   ```json
   "chat": { "id": 8681536685, "first_name": "Nik", ... }
   ```
   The number after `"id":` is your **chat ID**.  **Copy it too.**

If `"result": []` is empty, you haven't sent a message to the bot yet — send
one and reload the URL.

---

## 3. Configure the app

1. In File Explorer, open `C:\ai\TMScanner`.
2. Find the file named **`.env-sample`**.
3. **Copy** it and **rename** the copy to **`.env`** (no other name).
   - In File Explorer: right-click `.env-sample` → Copy → right-click →
     Paste → rename the copy to `.env`.
   - Or from PowerShell:
     ```powershell
     copy .env-sample .env
     ```

4. Open `.env` in any text editor (Notepad works) and fill in:

   ```env
   SCAN_URL=https://www.ticketexchangebyticketmaster.com/seg134/....
   PRICE_THRESHOLD=730
   TELEGRAM_TOKEN=<paste the BotFather token here>
   TELEGRAM_CHAT_ID=<paste your chat ID here>
   ```

   - **`SCAN_URL`** — the full Ticketmaster Exchange page for your event.
   - **`PRICE_THRESHOLD`** — alert when GA+ drops below this many dollars.
   - Leave the other values alone unless you know you want to change them.

5. **Save the file.**

If you forget this step, any program will print a big red error and exit.

---

## 4. One-time install

Open PowerShell in the project folder:

```powershell
cd C:\ai\TMScanner
```

Install Python packages:

```powershell
pip install -r requirements.txt
```

Install the headless browser used to read the page:

```powershell
python -m playwright install chromium
```

Start MongoDB + Redis (runs in the background via Docker):

```powershell
docker compose up -d
```

You only need to do this step **once**.  After a reboot, Docker Desktop will
restart these services automatically.

---

## 5. Running it

You need **two** PowerShell windows open.

### Window 1 — the dashboard

```powershell
cd C:\ai\TMScanner
python web\app.py
```

Leave this running.  You should see:
```
 * Running on http://0.0.0.0:8181
```

### Window 2 — the scanner

```powershell
cd C:\ai\TMScanner
python scanner.py
```

A Chromium window opens, navigates to the Ticketmaster page, and starts
scanning every 30 seconds.

### Open the dashboard

On the **same PC**:
- <http://localhost:8181>

From **any other device on your network**:
- <http://YOUR_PC_IP:8181>
  (to find your IP, run `ipconfig` in PowerShell and look for *IPv4 Address*)

---

## 6. Allow other devices through the firewall (one-time)

If the dashboard works on `localhost` but not from your phone/other PC,
Windows Firewall is blocking it.  Open **PowerShell as Administrator**
(right-click → Run as administrator) and run:

```powershell
New-NetFirewallRule -DisplayName "TM Scanner 8181" -Direction Inbound -Protocol TCP -LocalPort 8181 -Action Allow -Profile Any
```

---

## 7. Test that Telegram works

From PowerShell:

```powershell
cd C:\ai\TMScanner
python test_sms.py
```

You should get a Telegram message from your bot within a second.

---

## 8. Stopping everything

- **Scanner** window:  press `Ctrl+C`
- **Dashboard** window: press `Ctrl+C`
- **Mongo + Redis**:
  ```powershell
  docker compose down
  ```

---

## Project files at a glance

```
C:\ai\TMScanner\
├── .env                  ← your secrets (never shared)
├── .env-sample           ← template, safe to share
├── .gitignore
├── config.py             ← loads .env and validates values
├── scanner.py            ← the scraper; writes to Mongo + Redis
├── test_sms.py           ← quick Telegram smoke test
├── requirements.txt      ← Python dependencies
├── docker-compose.yml    ← Mongo + Redis containers
├── setup_and_run.bat     ← one-click setup helper (Windows)
└── web\
    ├── app.py            ← Flask dashboard
    └── templates\
        └── index.html    ← dashboard UI
```

---

## Troubleshooting

**"ERROR: .env file not found"**
You skipped Step 3.  Copy `.env-sample` to `.env` and fill in your values.

**"TELEGRAM_TOKEN is missing or empty"**
Open `.env` — the line for that variable is blank or has only a comment.

**Dashboard loads but cards show `—`**
The scanner hasn't written a price yet.  Wait 60 seconds and refresh.

**Scanner opens Chromium but prices never show**
Ticketmaster's page hasn't finished rendering.  The scanner will retry every
30 seconds.  If it never recovers, Ticketmaster may have blocked the session
— close Chromium and run `python scanner.py` again.

**"port is already allocated"** from Docker
Another program uses 27017 or 6379.  Edit `docker-compose.yml` to map a
different host port, then restart with `docker compose up -d`.

**Telegram test works, but real alerts never arrive**
Check you didn't mute the bot in Telegram.  Tap the bot → the bell icon
should not be crossed out.
