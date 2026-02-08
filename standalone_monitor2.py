import json
import time
import threading
import queue
import os
import re
import sqlite3
from datetime import datetime
from curl_cffi import requests
from flask import Flask, jsonify

# ==========================================
# ⚙️ ULTRA FAST CONFIGURATION
# ==========================================

TOKEN_MEN = os.environ.get("TOKEN_MEN")
TOKEN_WOMEN = os.environ.get("TOKEN_WOMEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))

SESSION_DB_PATH = "session_monitor.db"
CHECK_INTERVAL = 0.01  # Ultra fast - 10ms
NUM_WORKERS = 100  # More workers for parallel processing
BATCH_SIZE = 5  # Send in small batches for speed

CATEGORY_CONFIGS = {
    'Universal': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein"
    },
    'Women': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AWomen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AWomen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein"
    },
    'Men': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AMen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AMen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein"
    }
}

app = Flask(__name__)

api_session = requests.Session()
tg_session = requests.Session()

# ==========================================
# 🛠️ UTILITY FUNCTIONS
# ==========================================

def log(message, level="INFO"):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️", "FAST": "⚡"}
    icon = icons.get(level, "📝")
    print(f"[{timestamp}] {icon} {message}", flush=True)

def setup_api_session():
    try:
        cookie_content = os.environ.get("COOKIE_FILE_CONTENT")
        if not cookie_content:
            return False

        cookies_list = json.loads(cookie_content)
        cookies_dict = {}
        for cookie in cookies_list:
            name = cookie.get('name')
            value = cookie.get('value')
            if name and value:
                cookies_dict[name] = value

        for name, value in cookies_dict.items():
            api_session.cookies.set(name, value, domain=".sheinindia.in")

        log(f"API ready with {len(cookies_dict)} cookies", "SUCCESS")
        return True
    except Exception as e:
        log(f"Setup failed: {e}", "ERROR")
        return False

def fetch_api(url):
    try:
        separator = '&' if '?' in url else '?'
        url_with_ts = f"{url}{separator}_t={int(time.time() * 1000)}"

        response = api_session.get(
            url_with_ts,
            impersonate="chrome120",
            timeout=10
        )

        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

def send_telegram_fast(message, token, image_url=None, button_url=None):
    try:
        payload = {
            "chat_id": ADMIN_CHAT_ID,
            "parse_mode": "HTML"
        }

        if button_url:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[
                    {"text": "🛒 BUY", "url": button_url}
                ]]
            })

        if image_url and image_url.startswith('http'):
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload["photo"] = image_url
            payload["caption"] = message
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload["text"] = message
            payload["disable_web_page_preview"] = False

        import requests as req
        req.post(url, data=payload, timeout=5)
    except:
        pass

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
# 🚀 ULTRA FAST MONITOR
# ==========================================

class UltraFastMonitor:
    def __init__(self):
        self.running = True
        self.alert_queue = queue.Queue()
        self.db_queue = queue.Queue()
        self.session_cache = set()

        if os.path.exists(SESSION_DB_PATH):
            try:
                os.remove(SESSION_DB_PATH)
            except:
                pass

        self.init_db()
        log("Session initialized", "SUCCESS")

    def init_db(self):
        try:
            conn = sqlite3.connect(SESSION_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS session_seen (product_id TEXT PRIMARY KEY)")
            conn.commit()
            conn.close()
        except:
            pass

    def _db_writer(self):
        conn = sqlite3.connect(SESSION_DB_PATH, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except:
            pass

        batch = []
        while self.running:
            try:
                pid = self.db_queue.get(timeout=0.1)
                batch.append(pid)

                if len(batch) >= 50:
                    try:
                        conn.executemany("INSERT OR IGNORE INTO session_seen (product_id) VALUES (?)", 
                                       [(p,) for p in batch])
                        conn.commit()
                        batch.clear()
                    except:
                        pass

                self.db_queue.task_done()
            except queue.Empty:
                if batch:
                    try:
                        conn.executemany("INSERT OR IGNORE INTO session_seen (product_id) VALUES (?)", 
                                       [(p,) for p in batch])
                        conn.commit()
                        batch.clear()
                    except:
                        pass

        conn.close()

    def check_and_add_seen(self, pid):
        if pid in self.session_cache:
            return False
        self.session_cache.add(pid)
        self.db_queue.put(pid)
        return True

    def _alert_worker(self):
        while self.running:
            try:
                item = self.alert_queue.get(timeout=1)

                pid = item['id']
                cat_name = item['category']
                token = item['token']
                product = item['product']

                # Extract data from listing API
                name = product.get('name', 'New Product')

                # Price
                price_val = "Check Link"
                if 'price' in product:
                    price_obj = product['price']
                    raw = price_obj.get('value')
                    if raw:
                        price_val = f"₹{int(raw)}"
                    else:
                        price_val = price_obj.get('formattedValue', 'Check Link')

                # Image
                image_url = None
                if 'images' in product and len(product['images']) > 0:
                    image_url = product['images'][0].get('url')
                elif 'fnlColorVariantData' in product:
                    image_url = product['fnlColorVariantData'].get('outfitPictureURL')

                # Buy URL
                buy_url = f"https://www.sheinindia.in/p/{pid}"

                # Ultra minimal message
                msg = f"🔥 <b>{name}</b>\n💰 {price_val}"

                # Send immediately
                send_telegram_fast(msg, token, image_url=image_url, button_url=buy_url)
                log(f"⚡ Sent: {pid}", "FAST")

                self.alert_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                pass

    def process_category(self, cat_name):
        config = CATEGORY_CONFIGS[cat_name]
        base_url = config['url']

        log(f"Monitoring {cat_name} (ULTRA FAST MODE)", "SUCCESS")

        consecutive_failures = 0

        while self.running:
            try:
                first_page_url = re.sub(r'currentPage=\d+', 'currentPage=0', base_url)
                data = fetch_api(first_page_url)

                if not isinstance(data, dict):
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        time.sleep(2)
                        consecutive_failures = 0
                    else:
                        time.sleep(0.5)
                    continue

                consecutive_failures = 0

                pagination = data.get('pagination', {})
                total_pages = pagination.get('totalPages', 1)

                # Process all pages in parallel
                all_products = []
                page_products = data.get('products', [])
                all_products.extend(page_products)

                # Fetch remaining pages (max 10 for speed)
                if total_pages > 1:
                    for page_num in range(1, min(total_pages, 10)):
                        page_url = re.sub(r'currentPage=\d+', f'currentPage={page_num}', base_url)
                        page_data = fetch_api(page_url)
                        if isinstance(page_data, dict):
                            page_products = page_data.get('products', [])
                            all_products.extend(page_products)

                # Find new products
                new_items = []
                for p in all_products:
                    pid = p.get('fnlColorVariantData', {}).get('colorGroup') or p.get('code')
                    if not pid:
                        u = p.get('url', '')
                        if '/p/' in u:
                            pid = u.split('/p/')[1].split('.html')[0].split('?')[0]

                    if not pid:
                        continue

                    if self.check_and_add_seen(pid):
                        new_items.append((pid, p))

                count = len(new_items)
                if count > 0:
                    log(f"[{cat_name}] {count} NEW! ⚡⚡⚡", "FAST")

                    # Queue all for immediate sending
                    for pid, p in new_items:
                        token = get_target_token(cat_name, p)
                        self.alert_queue.put({
                            'id': pid,
                            'category': cat_name,
                            'product': p,
                            'token': token
                        })

                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                time.sleep(1)

    def start(self):
        log("⚡⚡⚡ ULTRA FAST MONITOR STARTING ⚡⚡⚡", "FAST")

        if not setup_api_session():
            log("Setup failed", "ERROR")
            return

        log(f"⚡ {NUM_WORKERS} WORKERS READY", "SUCCESS")
        log(f"⚡ CHECK INTERVAL: {CHECK_INTERVAL}s (ULTRA FAST)", "SUCCESS")
        log("⚡ NO DETAIL API = NO 403 ERRORS", "SUCCESS")
        log("⚡⚡⚡ MAXIMUM SPEED MODE ACTIVE ⚡⚡⚡", "FAST")

        # Start DB writer
        threading.Thread(target=self._db_writer, daemon=True).start()

        # Start alert workers
        for _ in range(NUM_WORKERS):
            threading.Thread(target=self._alert_worker, daemon=True).start()

        # Start category monitors
        for cat in CATEGORY_CONFIGS.keys():
            threading.Thread(target=self.process_category, args=(cat,), daemon=True).start()

        log("⚡ ALL SYSTEMS OPERATIONAL", "SUCCESS")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False

# ==========================================
# 🌐 FLASK
# ==========================================

monitor_instance = None
start_time = datetime.now()

@app.route('/health')
def health():
    uptime = (datetime.now() - start_time).total_seconds()
    return jsonify({
        "status": "healthy",
        "mode": "ULTRA FAST",
        "uptime_hours": round(uptime / 3600, 2),
        "workers": NUM_WORKERS,
        "check_interval": CHECK_INTERVAL,
        "running": monitor_instance.running if monitor_instance else False
    })

@app.route('/')
def home():
    return jsonify({
        "service": "Ultra Fast Monitor",
        "mode": "MAXIMUM SPEED",
        "platform": "Render.com",
        "version": "4.0 - Lightning Fast"
    })

def run_flask():
    from waitress import serve
    serve(app, host='0.0.0.0', port=PORT, threads=4)

# ==========================================
# 🎯 MAIN
# ==========================================

if __name__ == "__main__":
    log("⚡⚡⚡ RENDER.COM - ULTRA FAST MODE ⚡⚡⚡", "FAST")

    required_vars = ["TOKEN_MEN", "TOKEN_WOMEN", "ADMIN_CHAT_ID", "COOKIE_FILE_CONTENT"]
    missing = [v for v in required_vars if not os.environ.get(v)]

    if missing:
        log(f"Missing: {', '.join(missing)}", "ERROR")
        exit(1)

    log("All env vars validated", "SUCCESS")

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log(f"Health endpoint on port {PORT}", "SUCCESS")

    monitor_instance = UltraFastMonitor()
    monitor_instance.start()
