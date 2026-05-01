# TMScanner

Watches a **Ticketmaster Exchange** event page in the background, records
ticket prices over time, and sends **Telegram alerts** when any tier (GA, GA+,
or VIP) drops below a price you configure.  A web dashboard shows current
prices, availability, an all-time low, a live chart with trendline + forecast,
a price heatmap, and a history of alerts.

- 🎟  Scans **GA / GA+ / VIP** every 60 seconds (and the number of tickets available at the lowest price)
- 🔔  Instant **Telegram alerts** when prices cross your threshold
- 🎯  **Per-tier thresholds** configured from the dashboard — no config files to edit
- 🧭  Pick which tier the dashboard is focused on (GA / GA+ / VIP); that choice also controls which tier can fire alerts
- 📈  Dashboard with live cards, trendline + forecast chart, histogram, and 7-day heatmap
- 🔗  One-click **Buy Now** link back to Ticketmaster
- 💾  Price history in **MongoDB**, live cache in **Redis**, dashboard in **Flask**

---

![Alt Text](https://raw.githubusercontent.com/norfanos/TMScanner/refs/heads/master/Screenshot%202026-04-30%20225215.png "Hero Screenshot")

## 1. What you need before you start

Install these first.  All are free.

| Tool | Why | Where to get it |
|---|---|---|
| **Python 3.10 or newer** | Runs the scanner and dashboard | <https://www.python.org/downloads/> |
| **Docker Desktop** | Runs MongoDB + Redis | <https://www.docker.com/products/docker-desktop/> |
| **A Telegram account** | Receives the alerts | Install the app from your phone |

After installing Python, open a new **PowerShell** window and check:

```powershell
python --version
```

You should see `Python 3.12.x` (or newer).  If you see *"python is not
recognized"*, reinstall Python and tick **"Add Python to PATH"**.

---

## 2. Create your Telegram bot (≈ 2 minutes)

### Step A — Talk to BotFather

1. Open **Telegram** on any device.
2. Search for `@BotFather` (it has a blue check-mark — pick the official one).
3. Send:  `/newbot`
4. Pick a **display name** (anything, e.g. `My TM Scanner`).
5. Pick a **username** — it must end in `bot`, e.g. `niks_tm_scanner_bot`.
6. BotFather replies with an **HTTP API token** like:
   ```
   8096852334:AAFl174axyMvflzBywBP4YSGJNkKnio35MA
   ```
   **Copy it.**

### Step B — Find your chat ID

1. Open a chat with your bot (search for its username) and send any message, e.g. `hi`.
2. Open this URL in a browser (replace `YOUR_TOKEN_HERE`):
   ```
   https://api.telegram.org/botYOUR_TOKEN_HERE/getUpdates
   ```
3. In the JSON response, find:
   ```json
   "chat": { "id": 8681536685, ... }
   ```
   That number is your **chat ID**.  **Copy it.**

If `"result": []` is empty you haven't sent a message to the bot yet — send one and reload.

---

## 3. Configure the app

1. In the project folder, find `.env-sample` and **copy** it to `.env`:
   ```powershell
   copy .env-sample .env      # Windows
   cp   .env-sample .env      # Mac / Linux / Git Bash
   ```

2. Open `.env` in any text editor.  Fill in:
   ```env
   SCAN_URL=https://www.ticketexchangebyticketmaster.com/seg134/....
   EVENT_NAME=EDC Las Vegas 2026
   EVENT_DATE=2026-05-15
   EVENT_VENUE=Las Vegas Motor Speedway
   EVENT_IMAGE=              # optional — public image URL; leave blank to hide

   TELEGRAM_TOKEN=<paste your BotFather token>
   TELEGRAM_CHAT_ID=<paste your chat ID>
   ```
   Leave the rest alone unless you know you want to change them.

3. **Save the file.**  You don't set price thresholds here anymore — those live in the dashboard (step 6).

If `.env` is missing, every program prints a big red error and exits.

---

## 4. One-time install

Open PowerShell (or Terminal) in the project folder:

```powershell
cd C:\ai\TMScanner           # Windows path shown
```

Install Python packages:
```powershell
pip install -r requirements.txt
```

Install the headless browser the scanner uses:
```powershell
python -m playwright install chromium
```

Start MongoDB + Redis in the background via Docker:
```powershell
docker compose up -d
```

---

## 5. Running it

### Easiest — use the helper scripts

```powershell
.\setup_and_run.bat          # Windows
```
```bash
./setup_and_run.sh           # Mac / Linux
```

This will:

1. Stop any previously running scanner / dashboard
2. Upgrade Python deps
3. Install Playwright Chromium (cached if already present)
4. Restart Mongo + Redis containers
5. Open dashboard + scanner in separate windows and pop your browser to the dashboard URL

### Manual (two terminals)

**Dashboard** (terminal 1):
```powershell
python web\app.py
```

**Scanner** (terminal 2):
```powershell
python scanner.py
```

A Chromium window opens, navigates to the Ticketmaster page, and scans every 30 seconds.

### Opening the dashboard

- **This PC**: <http://localhost:8181>
- **Any other device on your network**: `http://YOUR_PC_IP:8181`
  (run `ipconfig` on Windows or `ifconfig` on Mac/Linux to find your IP)

---

## 6. First-run setup — set your thresholds

When the dashboard opens for the first time, the **Alert Thresholds** modal
pops up automatically because no thresholds are configured yet.  Set your
target prices for each tier:

| Tier | Example |
|---|---|
| **GA**    | 600 |
| **GA+**   | 730 |
| **VIP**   | 1200 |

- `−` / `+` buttons adjust by $1
- Type a number in the field — non-numeric input is rejected and zeroed with a warning
- Set a tier to **0** to disable alerts for that tier
- **Save** persists to MongoDB; **Cancel** closes without saving
- Click **Change** on the Alert Threshold card to re-open the editor any time

---

## 7. Choosing which tier to focus on

The three pill buttons in the header (**GA / GA+ / VIP**) decide:

- Which tier the "All-Time Low", "Change", "Vs Lower Tier", and threshold cards track
- Which tier's histogram + heatmap render
- Which tier's line on the main chart is emphasized + receives a trendline and forecast band
- **Which tier can fire alerts** — the scanner reads this selection and only alerts for the focused tier

Order is **GA (lowest) → GA+ → VIP (highest)**.  The "below lower tier" alert
fires when the focused tier's price drops below the tier directly below it
(e.g. VIP < GA+, or GA+ < GA).  GA has no lower tier, so it has no
below-lower alert.  Threshold alerts take priority — when a threshold alert
fires for a tier, its below-lower alert is suppressed.

---

## 8. Allow other devices (one-time firewall rule)

If the dashboard works on `localhost` but not from your phone / another PC,
Windows Firewall is blocking it.  In **PowerShell as Administrator**:

```powershell
New-NetFirewallRule -DisplayName "TM Scanner 8181" -Direction Inbound -Protocol TCP -LocalPort 8181 -Action Allow -Profile Any
```

---

## 9. Test that Telegram works

```powershell
python test_sms.py
```
You should get a Telegram message from your bot within a second.

---

## 10. Stopping everything

- Scanner window: `Ctrl+C`
- Dashboard window: `Ctrl+C`
- Mongo + Redis:
  ```powershell
  docker compose down
  ```

---

## Project files at a glance

```
C:\ai\TMScanner\
├── .env                     ← your secrets (never committed)
├── .env-sample              ← template, safe to share
├── .gitignore
├── config.py                ← loads .env and validates values
├── scanner.py               ← the scraper; writes to Mongo + Redis
├── test_sms.py              ← quick Telegram smoke test
├── requirements.txt         ← Python dependencies
├── docker-compose.yml       ← Mongo + Redis
├── setup_and_run.bat        ← Windows setup/rebuild/run
├── setup_and_run.sh         ← Mac / Linux setup/rebuild/run
├── README.md                ← this file
└── web\
    ├── app.py               ← Flask dashboard + API
    └── templates\
        └── index.html       ← dashboard UI
```

### Data model

- **Mongo `tmscanner.prices`** — one doc per scan: `{ts, ga, ga_plus, vip, ga_avail, ga_plus_avail, vip_avail}`
- **Mongo `tmscanner.alerts`** — one doc per alert fired: `{ts, type, message, ga, ga_plus, vip}`
- **Mongo `tmscanner.settings`** — singleton `{_id: "thresholds", ga, ga_plus, vip}`
- **Redis `latest`** — most recent price snapshot (for the 5 s card refresh)
- **Redis `heartbeat`** — Unix timestamp of last scan
- **Redis `focus_tier`** — which tier the dashboard is currently focused on

---

## Troubleshooting

**"ERROR: .env file not found"**
You skipped step 3.  Copy `.env-sample` → `.env` and fill in your values.

**"TELEGRAM_TOKEN is missing or empty"**
Open `.env` — one of the required lines is blank.

**Dashboard loads but cards show `—`**
The scanner hasn't written a price yet.  Wait 60 seconds and refresh.

**Scanner opens Chromium but prices never show**
Ticketmaster's page hasn't finished rendering, or the session was blocked.
The scanner retries every 30 seconds.  If it never recovers, close Chromium
and run `python scanner.py` again — stealth fingerprinting randomizes per
session.

**Threshold modal won't close / keeps reopening**
Reload the page.  The modal only auto-opens when **all three** thresholds are
0; saving any non-zero value stops the auto-prompt for that session.

**"Available: N" never appears on a card**
Ticketmaster may use a different quantity-selector markup for that tier.  In
the scanner log look for `Available count → None` to confirm.  Send me the
log line and the `<select>` HTML from your browser's DevTools and I'll add
the missing selector.

**Other devices still can't reach the dashboard after firewall rule**
Docker Desktop on Windows sometimes needs a helper:
```powershell
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8181 connectaddress=127.0.0.1 connectport=8181
```

**"port is already allocated" from Docker**
Another program uses 27017 or 6379.  Edit `docker-compose.yml` to map
different host ports, then `docker compose up -d` again.

**Telegram test works, but real alerts never arrive**
Check you haven't muted the bot — tap the bot in Telegram and confirm the
bell icon is not crossed out.  Also make sure the focused tier on the
dashboard is the one you expect to get alerts from; only the focused tier
fires alerts.
