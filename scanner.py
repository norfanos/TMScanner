import time
import random
import logging
import json
import urllib.request
import urllib.parse
from pymongo import MongoClient
import redis as redis_lib
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config import (
    SCAN_URL        as URL,
    PRICE_THRESHOLD,
    SCAN_INTERVAL,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    MONGO_URL,
    REDIS_URL,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

alert_below_threshold = False
alert_below_ga        = False

# ─── DB CONNECTIONS ───────────────────────────────────────────────────────────
try:
    _mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    _mongo.server_info()
    _col   = _mongo["tmscanner"]["prices"]
    _col.create_index("ts")
    log = logging.getLogger(__name__)
    logging.getLogger(__name__).info("MongoDB connected.")
except Exception as e:
    _col = None
    logging.getLogger(__name__).warning(f"MongoDB unavailable — history disabled: {e}")

try:
    _cache = redis_lib.from_url(REDIS_URL, socket_connect_timeout=3)
    _cache.ping()
    logging.getLogger(__name__).info("Redis connected.")
except Exception as e:
    _cache = None
    logging.getLogger(__name__).warning(f"Redis unavailable — live cache disabled: {e}")


def record_prices(ga_plus, ga):
    ts  = int(time.time())
    doc = {"ts": ts, "ga_plus": ga_plus, "ga": ga}
    if _col is not None:
        try:
            _col.insert_one({**doc})
        except Exception as e:
            logging.getLogger(__name__).warning(f"  MongoDB write failed: {e}")
    if _cache is not None:
        try:
            _cache.set("latest", json.dumps(doc))
        except Exception as e:
            logging.getLogger(__name__).warning(f"  Redis write failed: {e}")


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


# ─── HUMAN-LIKE SETTLE ────────────────────────────────────────────────────────
def human_settle(page, min_s=1.5, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))
    page.mouse.move(random.randint(300, 1100), random.randint(200, 600))
    time.sleep(random.uniform(0.2, 0.5))
    scroll_px = random.randint(250, 550)
    page.evaluate(f"window.scrollBy(0, {scroll_px})")
    time.sleep(random.uniform(0.3, 0.6))
    page.evaluate(f"window.scrollBy(0, -{scroll_px // 2})")


# ─── PRICE READING ────────────────────────────────────────────────────────────
def get_tab_min_price(page, tab_label: str) -> float | None:
    log.info(f"  [{tab_label}] Finding tab…")

    tab_loc = page.locator("a.ui-tabs-anchor").filter(has_text=tab_label).first
    try:
        tab_loc.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeout:
        log.warning(f"  [{tab_label}] Tab not visible — page may not have rendered.")
        return None

    # Read data-type from parent <li> via JS evaluation
    inv_type = tab_loc.evaluate(
        "el => el.closest('li[data-type]')?.getAttribute('data-type')"
    )
    if not inv_type:
        log.warning(f"  [{tab_label}] Could not read data-type from parent <li>.")
        return None
    log.info(f"  [{tab_label}] inv_type={inv_type}")

    # Click the tab to activate its panel
    tab_loc.click()
    time.sleep(0.8)

    # Wait for price container to attach and be visible
    container_sel = f"#allin-price-container-{inv_type}"
    try:
        page.locator(container_sel).wait_for(state="visible", timeout=8_000)
    except PlaywrightTimeout:
        log.warning(f"  [{tab_label}] {container_sel} not visible — continuing anyway.")

    # Read first <option> of the min-price select
    select_sel = f"{container_sel} select.tmr-range-min"
    try:
        page.locator(select_sel).wait_for(state="attached", timeout=8_000)
    except PlaywrightTimeout:
        log.warning(f"  [{tab_label}] select.tmr-range-min not found in {container_sel}.")
        return None

    first_option = page.locator(f"{select_sel} option").first
    first_val    = first_option.get_attribute("value")
    first_txt    = first_option.text_content()
    log.info(f"  [{tab_label}] Min price → value='{first_val}'  text='{first_txt}'")

    try:
        return float(first_val)
    except (ValueError, TypeError):
        log.warning(f"  [{tab_label}] Cannot parse '{first_val}' as float.")
        return None


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
def main():
    global alert_below_threshold, alert_below_ga

    log.info("=" * 60)
    log.info("  Ticketmaster GA+ Price Scanner  [Playwright]")
    log.info(f"  Alert 1 : GA+ < ${PRICE_THRESHOLD:.0f}")
    log.info(f"  Alert 2 : GA+ < GA min price")
    log.info(f"  Interval: {SCAN_INTERVAL}s")
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
                    ga_plus_price = get_tab_min_price(page, "GA+")
                    ga_price      = get_tab_min_price(page, "GA")

                    log.info(
                        f"  RESULT → GA+: {'$'+str(int(ga_plus_price)) if ga_plus_price else 'N/A'}"
                        f"   GA: {'$'+str(int(ga_price)) if ga_price else 'N/A'}"
                    )
                    record_prices(
                        int(ga_plus_price) if ga_plus_price else None,
                        int(ga_price)      if ga_price      else None,
                    )

                    # Alert 1: GA+ below fixed threshold
                    if ga_plus_price is not None:
                        if ga_plus_price < PRICE_THRESHOLD:
                            if not alert_below_threshold:
                                send_alert(
                                    f"TM: GA+ ${ga_plus_price:.0f}",
                                    f"GA+ is now ${ga_plus_price:.0f} — below ${PRICE_THRESHOLD:.0f} threshold!\n{URL}"
                                )
                                alert_below_threshold = True
                        else:
                            if alert_below_threshold:
                                alert_below_threshold = False
                                log.info("  Alert 1 reset (GA+ back above threshold).")

                    # Alert 2: GA+ cheaper than GA
                    if ga_plus_price is not None and ga_price is not None:
                        if ga_plus_price < ga_price:
                            if not alert_below_ga:
                                send_alert(
                                    f"TM: GA+ ${ga_plus_price:.0f} < GA ${ga_price:.0f}",
                                    f"GA+ (${ga_plus_price:.0f}) is CHEAPER than GA (${ga_price:.0f})!\n{URL}"
                                )
                                alert_below_ga = True
                        else:
                            if alert_below_ga:
                                alert_below_ga = False
                                log.info("  Alert 2 reset (GA+ no longer cheaper than GA).")

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
