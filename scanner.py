import time
import random
import logging
import json
import urllib.request
import urllib.parse
from datetime import datetime
from pymongo import MongoClient
import redis as redis_lib
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config import (
    SCAN_URL         as URL,
    SCAN_INTERVAL,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    MONGO_URL,
    REDIS_URL,
    EVENT_NAME,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── TIER CONFIG ──────────────────────────────────────────────────────────────
# Order: GA (lowest) < GA+ < VIP (highest).
# For each tier, `lower` is the tier immediately below it (for "below lower" alerts).
TIER_LABEL = {"ga": "GA", "ga_plus": "GA+", "vip": "VIP"}
TIER_LOWER = {"ga": None,  "ga_plus": "ga",  "vip": "ga_plus"}

# Per-tier alert-state dedup flags
alert_below_threshold = {"ga": False, "ga_plus": False, "vip": False}
alert_below_lower     = {"ga": False, "ga_plus": False, "vip": False}
_last_focus           = None

_started_ts           = int(time.time())
_scan_count           = 0
_alert_count          = 0

# ─── DB CONNECTIONS ───────────────────────────────────────────────────────────
try:
    _mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    _mongo.server_info()
    _db        = _mongo["tmscanner"]
    _prices    = _db["prices"]
    _alerts_db = _db["alerts"]
    _settings  = _db["settings"]
    _prices.create_index("ts")
    _alerts_db.create_index("ts")
    if _settings.find_one({"_id": "thresholds"}) is None:
        _settings.insert_one({"_id": "thresholds", "ga": 0, "ga_plus": 0, "vip": 0})
    log.info("MongoDB connected.")
except Exception as e:
    _prices    = None
    _alerts_db = None
    _settings  = None
    log.warning(f"MongoDB unavailable — history disabled: {e}")


def _get_thresholds():
    """Return {ga, ga_plus, vip}.  0 = alerts disabled for that tier."""
    if _settings is None:
        return {"ga": 0, "ga_plus": 0, "vip": 0}
    try:
        doc = _settings.find_one({"_id": "thresholds"}) or {}
        return {t: int(doc.get(t, 0)) for t in ("ga", "ga_plus", "vip")}
    except Exception:
        return {"ga": 0, "ga_plus": 0, "vip": 0}

try:
    _cache = redis_lib.from_url(REDIS_URL, socket_connect_timeout=3)
    _cache.ping()
    # Mark scanner start once on boot; preserve across restarts within 10 min.
    if not _cache.exists("started_ts"):
        _cache.set("started_ts", _started_ts)
    log.info("Redis connected.")
except Exception as e:
    _cache = None
    log.warning(f"Redis unavailable — live cache disabled: {e}")


def record_prices(ga_plus, ga, vip, ga_plus_avail=None, ga_avail=None, vip_avail=None):
    global _scan_count
    ts  = int(time.time())
    doc = {
        "ts":            ts,
        "ga_plus":       ga_plus,
        "ga":            ga,
        "vip":           vip,
        "ga_plus_avail": ga_plus_avail,
        "ga_avail":      ga_avail,
        "vip_avail":     vip_avail,
    }

    if _prices is not None:
        try:
            _prices.insert_one({**doc})
        except Exception as e:
            log.warning(f"  MongoDB write failed: {e}")

    if _cache is not None:
        try:
            _scan_count += 1
            pipe = _cache.pipeline()
            pipe.set("latest",        json.dumps(doc))
            pipe.set("heartbeat",     ts)
            pipe.incr("scans:total")
            day_key = f"scans:{datetime.utcnow().strftime('%Y-%m-%d')}"
            pipe.incr(day_key)
            pipe.expire(day_key, 60 * 60 * 48)   # keep daily counter 48 h
            pipe.execute()
        except Exception as e:
            log.warning(f"  Redis write failed: {e}")


def record_alert(alert_type: str, message: str, ga_plus, ga, vip):
    global _alert_count
    ts  = int(time.time())
    doc = {
        "ts":      ts,
        "type":    alert_type,
        "message": message,
        "ga_plus": ga_plus,
        "ga":      ga,
        "vip":     vip,
    }
    if _alerts_db is not None:
        try:
            _alerts_db.insert_one(doc)
        except Exception as e:
            log.warning(f"  Alert log write failed: {e}")
    if _cache is not None:
        try:
            _alert_count += 1
            pipe = _cache.pipeline()
            pipe.incr("alerts:total")
            day_key = f"alerts:{datetime.utcnow().strftime('%Y-%m-%d')}"
            pipe.incr(day_key)
            pipe.expire(day_key, 60 * 60 * 48)
            pipe.execute()
        except Exception as e:
            log.warning(f"  Alert counter write failed: {e}")


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_alert(subject: str, body: str) -> bool:
    text = f"*{subject}*\n{body}"
    params = urllib.parse.urlencode({
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }).encode()
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=params, timeout=10) as r:
            r.read()
        log.info(f"  Telegram sent: {subject}")
        return True
    except Exception as e:
        log.error(f"  Telegram failed: {e}")
        return False


# ─── STEALTH ──────────────────────────────────────────────────────────────────
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            {name:'Chrome PDF Plugin',   filename:'internal-pdf-viewer',             description:'Portable Document Format'},
            {name:'Chrome PDF Viewer',   filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai', description:''},
            {name:'Native Client',       filename:'internal-nacl-plugin',             description:''},
        ];
        arr.__proto__ = PluginArray.prototype;
        return arr;
    }
});

Object.defineProperty(navigator, 'languages',          {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory',        {get: () => 8});

window.chrome = { runtime: {} };

const _origQuery = window.navigator.permissions.query.bind(navigator.permissions);
window.navigator.permissions.query = (params) =>
    params.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : _origQuery(params);

const _getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Google Inc. (NVIDIA)';
    if (p === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return _getParam.call(this, p);
};

const _getImageData = CanvasRenderingContext2D.prototype.getImageData;
const _noise = () => Math.floor(Math.random() * 10) - 5;
CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
    const data = _getImageData.call(this, x, y, w, h);
    for (let i = 0; i < data.data.length; i += 4) {
        data.data[i]     = Math.min(255, Math.max(0, data.data[i]     + _noise()));
        data.data[i + 1] = Math.min(255, Math.max(0, data.data[i + 1] + _noise()));
        data.data[i + 2] = Math.min(255, Math.max(0, data.data[i + 2] + _noise()));
    }
    return data;
};
"""


# ─── BROWSER SETUP ────────────────────────────────────────────────────────────
def make_page(playwright):
    browser = playwright.chromium.launch(
        headless=False,
        args=[
            "--window-size=1440,900",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-notifications",
            "--disable-infobars",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    context.add_init_script(_STEALTH_JS)
    page = context.new_page()
    return browser, page


def human_settle(page, min_s=1.5, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))
    page.mouse.move(random.randint(300, 1100), random.randint(200, 600))
    time.sleep(random.uniform(0.2, 0.5))
    scroll_px = random.randint(250, 550)
    page.evaluate(f"window.scrollBy(0, {scroll_px})")
    time.sleep(random.uniform(0.3, 0.6))
    page.evaluate(f"window.scrollBy(0, -{scroll_px // 2})")


# ─── PRICE + AVAILABILITY READING ─────────────────────────────────────────────
def _max_int_option(select_loc) -> int | None:
    try:
        opts = select_loc.locator("option")
        n    = opts.count()
        vals = []
        for i in range(n):
            raw = opts.nth(i).get_attribute("value")
            try:
                vals.append(int(raw))
            except (TypeError, ValueError):
                continue
        return max(vals) if vals else None
    except Exception:
        return None


def _extract_availability(page, inv_type: str) -> int | None:
    """Return the largest quantity option in the 'number of tickets' dropdown
    (i.e. how many tickets can be bought at the cheapest listing)."""
    root = f"#tlp-filter-{inv_type}"
    # Explicit selectors we've seen on Ticketmaster Exchange layouts.
    candidates = [
        f"#allin-quantity-container-{inv_type} select",
        f"{root} select.tmr-qty-select",
        f"{root} select.tmr-quantity-select",
        f"{root} select[name*='quantity']",
        f"{root} select[name*='qty']",
        f"{root} select[aria-label*='Quantity']",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count():
                val = _max_int_option(loc)
                if val is not None:
                    return val
        except Exception:
            continue

    # Fallback: any <select> inside the filter area whose options look like
    # small whole numbers (≤ 20) and that isn't the price min/max selector.
    try:
        selects = page.locator(f"{root} select")
        for i in range(selects.count()):
            cls = (selects.nth(i).get_attribute("class") or "")
            if "tmr-range-min" in cls or "tmr-range-max" in cls:
                continue
            val = _max_int_option(selects.nth(i))
            if val is not None and 1 <= val <= 20:
                return val
    except Exception:
        pass
    return None


def get_tab_min_price(page, tab_label: str):
    """Return (min_price, available_count) for the given tab.  Either may be None."""
    log.info(f"  [{tab_label}] Finding tab…")

    tab_loc = page.locator("a.ui-tabs-anchor").filter(has_text=tab_label).first
    try:
        tab_loc.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeout:
        log.warning(f"  [{tab_label}] Tab not visible — page may not have rendered.")
        return (None, None)

    inv_type = tab_loc.evaluate(
        "el => el.closest('li[data-type]')?.getAttribute('data-type')"
    )
    if not inv_type:
        log.warning(f"  [{tab_label}] Could not read data-type from parent <li>.")
        return (None, None)
    log.info(f"  [{tab_label}] inv_type={inv_type}")

    tab_loc.click()
    time.sleep(0.8)

    container_sel = f"#allin-price-container-{inv_type}"
    try:
        page.locator(container_sel).wait_for(state="visible", timeout=8_000)
    except PlaywrightTimeout:
        log.warning(f"  [{tab_label}] {container_sel} not visible — continuing anyway.")

    select_sel = f"{container_sel} select.tmr-range-min"
    try:
        page.locator(select_sel).wait_for(state="attached", timeout=8_000)
    except PlaywrightTimeout:
        log.warning(f"  [{tab_label}] select.tmr-range-min not found in {container_sel}.")
        return (None, None)

    first_option = page.locator(f"{select_sel} option").first
    first_val    = first_option.get_attribute("value")
    first_txt    = first_option.text_content()
    log.info(f"  [{tab_label}] Min price → value='{first_val}'  text='{first_txt}'")

    try:
        price = float(first_val)
    except (ValueError, TypeError):
        log.warning(f"  [{tab_label}] Cannot parse '{first_val}' as float.")
        price = None

    avail = _extract_availability(page, inv_type)
    log.info(f"  [{tab_label}] Available count → {avail}")
    return (price, avail)


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
def _get_focus_tier():
    """Read the user's focus tier from Redis (set by the dashboard).  Default GA+."""
    if _cache is None:
        return "ga_plus"
    try:
        val = _cache.get("focus_tier")
        if isinstance(val, bytes):
            val = val.decode()
        return val if val in TIER_LABEL else "ga_plus"
    except Exception:
        return "ga_plus"


def main():
    global _last_focus

    log.info("=" * 60)
    log.info(f"  {EVENT_NAME} — Price Scanner [Playwright]")
    log.info(f"  Thresholds  : per-tier, configured in dashboard (0 = disabled)")
    log.info(f"  Alerts fire : only for the tier currently focused on the dashboard")
    log.info(f"  Interval    : {SCAN_INTERVAL}s")
    log.info("=" * 60)

    with sync_playwright() as playwright:
        browser, page = make_page(playwright)

        try:
            log.info("Loading page (waiting for network idle)…")
            page.goto(URL, wait_until="networkidle", timeout=60_000)
            human_settle(page)

            scan_n = 0

            while True:
                scan_n += 1
                log.info(f"══ Scan #{scan_n} {'═'*40}")

                try:
                    ga_plus_price, ga_plus_avail = get_tab_min_price(page, "GA+")
                    ga_price,      ga_avail      = get_tab_min_price(page, "GA")
                    vip_price,     vip_avail     = get_tab_min_price(page, "VIP")

                    def _fmt(p, a):
                        price = f"${int(p)}" if p else "N/A"
                        qty   = f" ({a} avail)" if a else ""
                        return price + qty

                    log.info(
                        f"  RESULT → GA+: {_fmt(ga_plus_price, ga_plus_avail)}"
                        f"   GA: {_fmt(ga_price, ga_avail)}"
                        f"   VIP: {_fmt(vip_price, vip_avail)}"
                    )
                    record_prices(
                        int(ga_plus_price) if ga_plus_price else None,
                        int(ga_price)      if ga_price      else None,
                        int(vip_price)     if vip_price     else None,
                        ga_plus_avail, ga_avail, vip_avail,
                    )

                    # ── Alerting (driven by the dashboard's focus tier) ────────
                    focus = _get_focus_tier()

                    # Clear all dedup flags when focus changes so switching tiers
                    # doesn't leave stale state.
                    if _last_focus is not None and _last_focus != focus:
                        for t in alert_below_threshold: alert_below_threshold[t] = False
                        for t in alert_below_lower:     alert_below_lower[t]     = False
                        log.info(f"  Focus changed {_last_focus} → {focus}; alert state reset.")
                    _last_focus = focus

                    prices_by_tier = {
                        "ga":      ga_price,
                        "ga_plus": ga_plus_price,
                        "vip":     vip_price,
                    }
                    focus_price = prices_by_tier[focus]
                    focus_label = TIER_LABEL[focus]
                    lower_key   = TIER_LOWER[focus]
                    lower_price = prices_by_tier[lower_key] if lower_key else None
                    lower_label = TIER_LABEL[lower_key] if lower_key else None

                    thresholds  = _get_thresholds()
                    focus_limit = thresholds.get(focus, 0)

                    log.info(
                        f"  Focus: {focus_label} "
                        f"(threshold "
                        + (f"${focus_limit}" if focus_limit > 0 else "disabled")
                        + (f", lower tier {lower_label})" if lower_label else ", no lower tier)")
                    )

                    threshold_hit = (
                        focus_limit > 0
                        and focus_price is not None
                        and focus_price < focus_limit
                    )
                    below_lower = (
                        focus_price is not None
                        and lower_price is not None
                        and focus_price < lower_price
                    )

                    # Alert 1 — threshold (priority, suppresses below-lower)
                    if threshold_hit:
                        if not alert_below_threshold[focus]:
                            subject = f"🔔 {focus_label} ${focus_price:.0f} — below ${focus_limit}!"
                            body    = (
                                f"{focus_label} is now ${focus_price:.0f} — "
                                f"below your ${focus_limit} threshold.\n{URL}"
                            )
                            send_alert(subject, body)
                            record_alert("threshold", subject, ga_plus_price, ga_price, vip_price)
                            alert_below_threshold[focus] = True
                        # Threshold fire mutes the secondary alert for the same tier.
                        alert_below_lower[focus] = False
                    else:
                        if alert_below_threshold[focus]:
                            alert_below_threshold[focus] = False
                            log.info(f"  Threshold alert reset ({focus_label} back above ${focus_limit}).")

                        # Alert 2 — focus tier cheaper than its next-lower tier
                        # (GA has no lower tier → no alert)
                        if below_lower:
                            if not alert_below_lower[focus]:
                                subject = f"{focus_label} ${focus_price:.0f} < {lower_label} ${lower_price:.0f}"
                                body    = (
                                    f"{focus_label} (${focus_price:.0f}) is CHEAPER than "
                                    f"{lower_label} (${lower_price:.0f}).\n{URL}"
                                )
                                send_alert(subject, body)
                                record_alert("below_lower", subject, ga_plus_price, ga_price, vip_price)
                                alert_below_lower[focus] = True
                        else:
                            if alert_below_lower[focus]:
                                alert_below_lower[focus] = False
                                log.info(f"  Below-lower alert reset ({focus_label} no longer cheaper than {lower_label}).")

                except Exception as e:
                    log.error(f"  Scan error: {e}", exc_info=True)

                log.info(f"  Next scan in {SCAN_INTERVAL}s…")
                time.sleep(SCAN_INTERVAL)

                log.info("  Reloading page…")
                try:
                    page.reload(wait_until="networkidle", timeout=60_000)
                    human_settle(page, 1.0, 2.0)
                except Exception as e:
                    log.error(f"  Navigation error: {e}")

        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
