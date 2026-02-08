import json
import time
import random
import threading
import queue
import os
import re
import requests
import sqlite3
import tempfile
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from DrissionPage import ChromiumPage, ChromiumOptions
from flask import Flask, jsonify

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================

# Tokens from environment
TOKEN_MEN = os.environ.get("TOKEN_MEN")
TOKEN_WOMEN = os.environ.get("TOKEN_WOMEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

# Settings
SESSION_DB_PATH = "session_monitor.db"
CHECK_INTERVAL = 0.05
HEADLESS_MODE = True
NUM_WORKERS = 50
BURST_TRIGGER_THRESHOLD = 15

# URLs
CATEGORY_CONFIGS = {
    'Universal': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein",
        'tab': None
    },
    'Women': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AWomen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AWomen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein",
        'tab': None
    },
    'Men': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AMen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AMen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein",
        'tab': None
    }
}

# Flask app for health check
app = Flask(__name__)

# Session
tg_session = requests.Session()
retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
tg_session.mount('https://', HTTPAdapter(max_retries=retries, pool_connections=200, pool_maxsize=200))

# ==========================================
# 🛠️ UTILITY FUNCTIONS
# ==========================================

def log(message, level="INFO"):
    """Enhanced logging with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️"}
    icon = icons.get(level, "📝")
    print(f"[{timestamp}] {icon} {message}", flush=True)

def send_telegram(message, token, image_url=None, button_url=None):
    try:
        payload = {
            "chat_id": ADMIN_CHAT_ID,
            "parse_mode": "HTML"
        }

        if button_url:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[
                    {"text": "🛍️ BUY NOW", "url": button_url}
                ]]
            })

        if image_url:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload["photo"] = image_url
            payload["caption"] = message
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload["text"] = message
            payload["disable_web_page_preview"] = False

        resp = tg_session.post(url, data=payload, timeout=30)
        if resp.status_code == 200:
            log("Telegram message sent", "SUCCESS")
    except Exception as e:
        log(f"Telegram error: {e}", "ERROR")

def get_target_token(cat_name, product_data):
    if cat_name == 'Men':
        return TOKEN_MEN
    elif cat_name == 'Women':
        return TOKEN_WOMEN
    else:
        seg_text = product_data.get('segmentNameText', '').lower()
        if 'women' in seg_text:
            return TOKEN_WOMEN
        elif 'men' in seg_text:
            return TOKEN_MEN
        return TOKEN_WOMEN

# ==========================================
# 🚀 MONITOR CLASS
# ==========================================

class StandaloneMonitor:
    def __init__(self):
        self.browser = None
        self.running = True
        self.details_queue = queue.Queue()
        self.db_queue = queue.Queue()
        self.session_cache = set()

        if os.path.exists(SESSION_DB_PATH):
            try:
                os.remove(SESSION_DB_PATH)
                log("Session DB cleared", "SUCCESS")
            except Exception:
                pass

        self.init_db_file()
        log("Session system initialized", "SUCCESS")

    def init_db_file(self):
        try:
            conn = sqlite3.connect(SESSION_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS session_seen (product_id TEXT PRIMARY KEY)")
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"DB init error: {e}", "ERROR")

    def _db_writer(self):
        conn = sqlite3.connect(SESSION_DB_PATH, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except:
            pass

        while self.running:
            try:
                pid = self.db_queue.get(timeout=1)
                try:
                    conn.execute("INSERT OR IGNORE INTO session_seen (product_id) VALUES (?)", (pid,))
                    conn.commit()
                except:
                    pass
                self.db_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass

        conn.close()

    def check_and_add_seen(self, pid):
        if pid in self.session_cache:
            return False
        self.session_cache.add(pid)
        self.db_queue.put(pid)
        return True

    def get_browser_options(self, port, headless=HEADLESS_MODE):
        co = ChromiumOptions()
        co.set_local_port(port)
        co.set_user_data_path(os.path.join(tempfile.gettempdir(), f"monitor_profile_{port}"))
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--mute-audio')
        co.set_argument('--blink-settings=imagesEnabled=false')
        co.set_argument('--disable-gpu')

        if headless:
            co.set_argument('--headless=new')

        return co

    def init_monitor(self):
        log("Starting browser initialization...", "INFO")
        port = random.randint(30001, 40000)
        co = self.get_browser_options(port)

        try:
            self.browser = ChromiumPage(co)
            log("Browser instance created", "SUCCESS")
        except Exception as e:
            log(f"Browser creation failed: {e}", "ERROR")
            return False

        # Load cookies from environment variable
        cookie_content = os.environ.get("COOKIE_FILE_CONTENT")
        if cookie_content:
            try:
                log("Loading cookies from environment...", "INFO")
                cookies = json.loads(cookie_content)
                self.browser.get('https://www.sheinindia.in/')
                time.sleep(2)
                self.browser.set.cookies(cookies)
                self.browser.refresh()
                time.sleep(2)
                log("Cookies loaded successfully", "SUCCESS")
            except Exception as e:
                log(f"Cookie loading failed: {e}", "ERROR")
                return False
        else:
            log("No cookies provided in environment", "ERROR")
            return False

        # Initialize tabs
        CATEGORY_CONFIGS['Universal']['tab'] = self.browser.latest_tab
        for cat in ['Women', 'Men']:
            CATEGORY_CONFIGS[cat]['tab'] = self.browser.new_tab('https://www.sheinindia.in/')
            time.sleep(0.5)

        log("All tabs initialized", "SUCCESS")
        return True

    def fetch_via_js(self, tab, url):
        js_code = f"""
        return fetch("{url}&_t=" + Date.now(), {{
            headers: {{'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}}
        }}).then(res => {{
            if(res.status === 403) return "403";
            if(!res.ok) return "ERR_" + res.status;
            return res.json();
        }}).catch(err => "ERR_NETWORK");
        """
        try:
            return tab.run_js(js_code, timeout=12)
        except:
            return None

    def send_burst_alerts(self, product_list, token):
        log(f"BURST MODE: {len(product_list)} alerts", "INFO")
        for p in product_list:
            try:
                pid = p.get('fnlColorVariantData', {}).get('colorGroup') or p.get('code')
                name = p.get('name', 'New Product')
                url = f"https://www.sheinindia.in/p/{pid}"
                img_url = p.get('url', '')
                if 'images' in p and len(p['images']) > 0:
                    img_url = p['images'][0].get('url')

                msg = f"⚠️ **FAST ALERT**\n📦 {name}\n🆔 `{pid}`\n\n*Fetching details...*"
                send_telegram(msg, token, image_url=img_url, button_url=url)
                time.sleep(0.1)
            except:
                pass

    def _details_worker(self):
        while self.running:
            try:
                item = self.details_queue.get(timeout=1)
                pid = item['id']
                cat_name = item['category']
                token = item['token']
                is_burst = item.get('is_burst', False)
                basic_data = item.get('basic_data', {})

                detail_url = f"https://www.sheinindia.in/api/p/{pid}?fields=SITE"
                active_tabs = [c['tab'] for c in CATEGORY_CONFIGS.values() if c['tab']]
                worker_tab = random.choice(active_tabs) if active_tabs else CATEGORY_CONFIGS['Universal']['tab']

                data = None
                for attempt in range(5):
                    data = self.fetch_via_js(worker_tab, detail_url)
                    if isinstance(data, dict):
                        break
                    time.sleep(1.5)

                if isinstance(data, dict):
                    self.format_and_send_alert(pid, cat_name, data, is_burst, token)
                else:
                    self.format_and_send_alert(pid, cat_name, None, is_burst, token, basic_data)

                self.details_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass

    def extract_image_url(self, full_data):
        try:
            img = full_data.get('selected', {}).get('modelImage', {}).get('url')
            if img:
                return img
            base_opts = full_data.get('baseOptions', [])
            if base_opts:
                img = base_opts[0].get('options', [])[0].get('modelImage', {}).get('url')
                if img:
                    return img
            if 'images' in full_data and len(full_data['images']) > 0:
                return full_data['images'][0].get('url')
        except:
            return None

    def extract_basic_image(self, basic_data):
        try:
            if 'images' in basic_data and len(basic_data['images']) > 0:
                return basic_data['images'][0].get('url')
            if 'fnlColorVariantData' in basic_data:
                return basic_data['fnlColorVariantData'].get('outfitPictureURL')
        except:
            return None

    def format_and_send_alert(self, pid, cat, full_data, is_burst, token, basic_data=None):
        try:
            buy_url = f"https://www.sheinindia.in/p/{pid}"
            timestamp = datetime.now().strftime('%H:%M:%S')

            if full_data:
                name = full_data.get('productRelationID', full_data.get('name', 'Product'))
                price_val = "N/A"
                price_obj = full_data.get('offerPrice') or full_data.get('price')
                if price_obj:
                    raw = price_obj.get('value')
                    price_val = f"₹{int(raw)}" if raw else price_obj.get('formattedValue', 'N/A')

                image_url = self.extract_image_url(full_data)

                size_list = []
                variants = full_data.get('variantOptions', [])
                if variants:
                    for v in variants:
                        qs = v.get('variantOptionQualifiers', [])
                        size = next((q['value'] for q in qs if q['qualifier'] == 'size'),
                                  next((q['value'] for q in qs if q['qualifier'] == 'standardSize'), 'N/A'))
                        qty = v.get('stock', {}).get('stockLevel', 0)
                        status = v.get('stock', {}).get('stockLevelStatus', '')

                        if status != 'outOfStock' and qty > 0:
                            size_list.append(f"✅ **{size}** : {qty}")
                        elif status == 'inStock':
                            size_list.append(f"✅ **{size}** : In Stock")
                        else:
                            size_list.append(f"❌ {size} : Out")

                    sizes_text = "\n".join(size_list)
                else:
                    sizes_text = "⚠️ Check stock"
            else:
                name = basic_data.get('name', 'Product')
                price_val = "Check Link"
                image_url = self.extract_basic_image(basic_data)
                sizes_text = "⚠️ Details unavailable"

            title = "📦 **STOCK INFO**" if is_burst else "🔥 **NEW ARRIVAL**"

            msg = (
                f"{title}\n\n"
                f"👚 **{name}**\n"
                f"💰 **{price_val}**\n\n"
                f"📏 **Stock Status:**\n"
                f"{sizes_text}\n\n"
                f"⚡ Captured: {timestamp}"
            )

            send_telegram(msg, token, image_url=image_url, button_url=buy_url)
            log(f"Alert sent: {pid}", "SUCCESS")
        except Exception as e:
            log(f"Alert error: {e}", "ERROR")

    def process_category(self, cat_name):
        config = CATEGORY_CONFIGS[cat_name]
        tab = config['tab']
        base_url = config['url']

        log(f"Started monitoring {cat_name}", "INFO")

        while self.running:
            try:
                first_page_url = re.sub(r'currentPage=\d+', 'currentPage=0', base_url)
                data = self.fetch_via_js(tab, first_page_url)

                if data == "403":
                    log(f"[{cat_name}] 403 error", "ERROR")
                    time.sleep(5)
                    continue

                if not isinstance(data, dict):
                    time.sleep(2)
                    continue

                pagination = data.get('pagination', {})
                total_pages = pagination.get('totalPages', 1)

                all_products = []
                for page_num in range(total_pages):
                    if page_num == 0:
                        page_products = data.get('products', [])
                    else:
                        page_url = re.sub(r'currentPage=\d+', f'currentPage={page_num}', base_url)
                        page_data = self.fetch_via_js(tab, page_url)
                        if isinstance(page_data, dict):
                            page_products = page_data.get('products', [])
                        else:
                            page_products = []

                    all_products.extend(page_products)

                new_session_items = []
                for p in all_products:
                    pid = p.get('fnlColorVariantData', {}).get('colorGroup') or p.get('code')
                    if not pid:
                        u = p.get('url', '')
                        if '/p/' in u:
                            pid = u.split('/p/')[1].split('.html')[0].split('?')[0]

                    if not pid:
                        continue

                    if self.check_and_add_seen(pid):
                        new_session_items.append(p)

                count = len(new_session_items)
                if count > 0:
                    log(f"[{cat_name}] Found {count} new items", "SUCCESS")

                    should_burst = count <= BURST_TRIGGER_THRESHOLD
                    items_with_tokens = []
                    for p in new_session_items:
                        token = get_target_token(cat_name, p)
                        items_with_tokens.append((p, token))

                    if should_burst:
                        men_batch = [x[0] for x in items_with_tokens if x[1] == TOKEN_MEN]
                        women_batch = [x[0] for x in items_with_tokens if x[1] == TOKEN_WOMEN]

                        if men_batch:
                            threading.Thread(target=self.send_burst_alerts, 
                                           args=(men_batch, TOKEN_MEN), daemon=True).start()
                        if women_batch:
                            threading.Thread(target=self.send_burst_alerts, 
                                           args=(women_batch, TOKEN_WOMEN), daemon=True).start()

                    for p, token in items_with_tokens:
                        pid = p.get('fnlColorVariantData', {}).get('colorGroup') or p.get('code')
                        self.details_queue.put({
                            'id': pid,
                            'category': cat_name,
                            'is_burst': should_burst,
                            'basic_data': p,
                            'token': token
                        })

                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                log(f"[{cat_name}] Error: {e}", "ERROR")
                time.sleep(2)

    def start(self):
        if not self.init_monitor():
            log("Monitor initialization failed", "ERROR")
            return

        log("=== ENGINE FULLY OPERATIONAL ===", "SUCCESS")

        threading.Thread(target=self._db_writer, daemon=True).start()

        for _ in range(NUM_WORKERS):
            threading.Thread(target=self._details_worker, daemon=True).start()

        log(f"{NUM_WORKERS} workers active", "SUCCESS")

        for cat in CATEGORY_CONFIGS.keys():
            threading.Thread(target=self.process_category, args=(cat,), daemon=True).start()

        log("All monitors active", "SUCCESS")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
            if self.browser:
                self.browser.quit()

# ==========================================
# 🌐 FLASK HEALTH ENDPOINT
# ==========================================

monitor_instance = None
start_time = datetime.now()

@app.route('/health')
def health():
    uptime = (datetime.now() - start_time).total_seconds()
    return jsonify({
        "status": "healthy",
        "uptime_seconds": uptime,
        "uptime_hours": round(uptime / 3600, 2),
        "running": monitor_instance.running if monitor_instance else False
    })

@app.route('/')
def home():
    return jsonify({
        "service": "Product Monitor",
        "status": "running",
        "platform": "Render.com"
    })

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ==========================================
# 🎯 MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    log("=== RENDER.COM DEPLOYMENT ===", "INFO")
    log("Validating environment variables...", "INFO")

    required_vars = ["TOKEN_MEN", "TOKEN_WOMEN", "ADMIN_CHAT_ID", "COOKIE_FILE_CONTENT"]
    missing = [v for v in required_vars if not os.environ.get(v)]

    if missing:
        log(f"Missing env vars: {', '.join(missing)}", "ERROR")
        exit(1)

    log("All environment variables validated", "SUCCESS")

    # Start Flask in separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log(f"Health endpoint running on port {PORT}", "SUCCESS")

    # Start monitor
    monitor_instance = StandaloneMonitor()
    monitor_instance.start()
