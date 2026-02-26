import json
import time
import threading
import queue
import os
import re
import random
import sqlite3
import gc  # Added for memory management
from datetime import datetime
from curl_cffi import requests
from flask import Flask, jsonify

# ==========================================
# ⚙️ MEMORY OPTIMIZED + MULTI-FINGERPRINT
# ==========================================

TOKEN_MEN = os.environ.get("TOKEN_MEN")
TOKEN_WOMEN = os.environ.get("TOKEN_WOMEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")  

SESSION_DB_PATH = "session_monitor.db"
CHECK_INTERVAL = 0.2  # 🔥 FAST: 0.2s check interval for instant pickup
NUM_WORKERS = 25  # 🔥 INCREASED: 25 workers for fast stock checking (safe due to pipeline)
PAGE_FETCH_WORKERS = 8  # 🔥 INCREASED: 8 concurrent fetchers for pages
MAX_SESSIONS = 15 # 🔥 INCREASED: 15 sessions for faster API calls without ban
SELF_PING_INTERVAL = 600  # 10 minutes
SESSION_CLEAR_INTERVAL = 6 * 3600  # 6 hours

# Priority Sizes for Stock
PRIORITY_SIZES = ["M", "L", "XL", "32", "34", "36"]

# API URLs are set to AJIO servers for fast backend monitoring
CATEGORY_CONFIGS = {
    'Universal': {
        'url': "https://sheinindia.ajio.com/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=ajio"
    },
    'Women': {
        'url': "https://sheinindia.ajio.com/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AWomen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AWomen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&"
    },
    'Men': {
        'url': "https://sheinindia.ajio.com/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AMen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AMen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=ajio"
    }
}

app = Flask(__name__)

# ==========================================
# 🛡️ MULTI-FINGERPRINT ANTI-BAN SYSTEM
# ==========================================

BROWSER_FINGERPRINTS = [
    "chrome114", "chrome116", "chrome119", "chrome120",
    "edge114", "edge116", "safari16_0", "safari17_0"
]

API_SESSIONS_POOL = []

def log(message, level="INFO"):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️", "FAST": "⚡", "PING": "🔔", "STOCK": "📦", "CLEAN": "🧹"}
    icon = icons.get(level, "📝")
    print(f"[{timestamp}] {icon} {message}", flush=True)

def setup_multi_session_pool():
    """Creates a pool of sessions with Smart Cookie Parsing"""
    try:
        cookie_content = os.environ.get("COOKIE_FILE_CONTENT", "").strip()
        if not cookie_content:
            log("No cookies provided in environment!", "ERROR")
            return False

        cookies_dict = {}
        
        # SMART COOKIE PARSER
        try:
            parsed = json.loads(cookie_content)
            if isinstance(parsed, list):
                for cookie in parsed:
                    name = cookie.get('name')
                    value = cookie.get('value')
                    if name and value:
                        cookies_dict[name] = value
            elif isinstance(parsed, dict):
                for name, value in parsed.items():
                    cookies_dict[name] = str(value)
            log("Parsed cookies from JSON format.", "INFO")
        except json.JSONDecodeError:
            log("Parsing cookies from Single String format...", "INFO")
            parts = cookie_content.split(';')
            for part in parts:
                if '=' in part:
                    k, v = part.split('=', 1)
                    cookies_dict[k.strip()] = v.strip()

        if not cookies_dict:
            log("Failed to extract any valid cookies!", "ERROR")
            return False

        for _ in range(MAX_SESSIONS):
            fingerprint = random.choice(BROWSER_FINGERPRINTS)
            session = requests.Session(impersonate=fingerprint)
            
            session.headers.update({
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://sheinindia.ajio.com/',
                'Origin': 'https://sheinindia.ajio.com',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            })
            
            for name, value in cookies_dict.items():
                session.cookies.set(name, value, domain=".sheinindia.in")
                session.cookies.set(name, value, domain=".ajio.com")
                session.cookies.set(name, value, domain="sheinindia.ajio.com")
            
            API_SESSIONS_POOL.append({
                "session": session,
                "fingerprint": fingerprint
            })

        log(f"Multi-Fingerprint Pool ready with {len(API_SESSIONS_POOL)} sessions!", "SUCCESS")
        return True
    except Exception as e:
        log(f"Session Pool Setup failed: {e}", "ERROR")
        return False

def fetch_api(url, timeout=10):
    """Fetches URL using a random fingerprint with slight human delay"""
    try:
        time.sleep(random.uniform(0.1, 0.4))
        session_data = random.choice(API_SESSIONS_POOL)
        session = session_data["session"]
        
        separator = '&' if '?' in url else '?'
        url_with_ts = f"{url}{separator}_t={int(time.time() * 1000)}&_r={random.randint(1000, 9999)}"

        response = session.get(url_with_ts, timeout=timeout)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 403:
            log(f"403 Blocked on {session_data['fingerprint']}. Retrying...", "WARNING")
        return None
    except Exception as e:
        return None

# ==========================================
# 📦 STOCK CHECKING ENGINE
# ==========================================

def fetch_product_stock(pid):
    url = f"https://sheinindia.ajio.com/api/p/{pid}?fields=SITE"
    data = fetch_api(url, timeout=8)
    
    if not data: return None
    
    current_stock = {}
    found_priority = []
    
    try:
        for v in data.get('variantOptions', []):
            qs = v.get('variantOptionQualifiers', [])
            size = next((q['value'] for q in qs if q['qualifier'] == 'size'), 
                   next((q['value'] for q in qs if q['qualifier'] == 'standardSize'), None))
            if size:
                status = v.get('stock', {}).get('stockLevelStatus', '')
                qty = v.get('stock', {}).get('stockLevel', 0)
                if status in ['inStock', 'lowStock']: 
                    current_stock[size] = qty
                    if qty > 0 and str(size).upper() in PRIORITY_SIZES:
                        found_priority.append(f"{size} ({qty})")
                else: 
                    current_stock[size] = 0
    except: pass
    
    return {"stock": current_stock, "priority": found_priority, "full_data": data}

# ==========================================
# 🛠️ TELEGRAM ALERTS
# ==========================================

def send_telegram_fast(message, token, image_url=None, button_url=None):
    try:
        payload = {"chat_id": ADMIN_CHAT_ID, "parse_mode": "HTML"}

        if button_url:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[{"text": "🛒 BUY NOW", "url": button_url}]]
            })

        if image_url and image_url.startswith('http'):
            image_url = re.sub(r'_\d+x\d+', '', image_url).replace('_thumbnail', '')
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload["photo"] = image_url
            payload["caption"] = message
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload["text"] = message
            payload["disable_web_page_preview"] = False

        import requests as req
        req.post(url, data=payload, timeout=5)
    except: pass

def get_target_token(cat_name, product_data):
    if cat_name == 'Men': return TOKEN_MEN
    elif cat_name == 'Women': return TOKEN_WOMEN
    else:
        seg_text = product_data.get('segmentNameText', '').lower()
        if 'women' in seg_text: return TOKEN_WOMEN
        elif 'men' in seg_text: return TOKEN_MEN
        return TOKEN_WOMEN

# ==========================================
# 🔔 SELF-PING KEEPER
# ==========================================

def self_ping_keeper():
    import requests as req
    time.sleep(30)
    ping_url = RENDER_URL if RENDER_URL else "https://product-monitor.onrender.com"
    if not ping_url.startswith('http'): ping_url = f"https://{ping_url}"
    health_url = f"{ping_url}/health"
    log(f"🔔 Ping keeper active for {health_url}", "PING")

    while True:
        try:
            time.sleep(SELF_PING_INTERVAL)
            res = req.get(health_url, timeout=10)
            if res.status_code == 200: log("🔔 Self-ping success", "PING")
        except: pass

# ==========================================
# 🚀 COMPLETE COVERAGE MONITOR
# ==========================================

class CompleteCoverageMonitor:
    def __init__(self):
        self.running = True
        # Max size added to prevent Queues from eating all memory
        self.alert_queue = queue.Queue(maxsize=1000)
        self.db_queue = queue.Queue(maxsize=1000)
        self.session_cache = set()
        self.page_fetch_queue = queue.Queue(maxsize=200)

        if os.path.exists(SESSION_DB_PATH):
            try: os.remove(SESSION_DB_PATH)
            except: pass
        self.init_db()

    def init_db(self):
        try:
            conn = sqlite3.connect(SESSION_DB_PATH)
            conn.execute("CREATE TABLE IF NOT EXISTS session_seen (product_id TEXT PRIMARY KEY)")
            conn.commit(); conn.close()
        except: pass

    def clear_session_db(self):
        try:
            self.session_cache.clear()
            conn = sqlite3.connect(SESSION_DB_PATH)
            conn.execute("DELETE FROM session_seen")
            conn.commit()
            conn.close()
            gc.collect() # Force free memory
            log("Session DB cleared! Old products will trigger alerts again.", "CLEAN")
        except Exception as e:
            log(f"Session DB clear error: {e}", "ERROR")

    def _session_clear_worker(self):
        while self.running:
            for _ in range(SESSION_CLEAR_INTERVAL):
                if not self.running: return
                time.sleep(1)
            self.clear_session_db()

    def _db_writer(self):
        conn = sqlite3.connect(SESSION_DB_PATH, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except: pass

        batch = []
        while self.running:
            try:
                pid = self.db_queue.get(timeout=1)
                batch.append(pid)
                if len(batch) >= 100:
                    try:
                        conn.executemany("INSERT OR IGNORE INTO session_seen (product_id) VALUES (?)", [(p,) for p in batch])
                        conn.commit()
                        batch.clear()
                    except: pass
                self.db_queue.task_done()
            except queue.Empty:
                if batch:
                    try:
                        conn.executemany("INSERT OR IGNORE INTO session_seen (product_id) VALUES (?)", [(p,) for p in batch])
                        conn.commit()
                        batch.clear()
                    except: pass

    def check_and_add_seen(self, pid):
        if pid in self.session_cache: return False
        self.session_cache.add(pid)
        try:
            self.db_queue.put(pid, timeout=2) # Non-blocking to avoid deadlocks
        except queue.Full: pass
        return True

    def _alert_worker(self):
        while self.running:
            try:
                item = self.alert_queue.get(timeout=1)
                try:
                    pid = item['id']
                    token = item['token']
                    product = item['product']

                    stock_data = fetch_product_stock(pid)
                    
                    name = product.get('name', 'New Product')
                    if stock_data and stock_data.get('full_data'):
                        name = stock_data['full_data'].get('productRelationID', stock_data['full_data'].get('name', name))

                    price_val = "Check Link"
                    if 'price' in product:
                        raw = product['price'].get('value')
                        if raw: price_val = f"₹{int(raw)}"

                    image_url = None
                    if stock_data and 'full_data' in stock_data:
                        fd = stock_data['full_data']
                        image_url = fd.get('selected', {}).get('modelImage', {}).get('url')
                        if not image_url and 'images' in fd and fd['images']: image_url = fd['images'][0].get('url')

                    if not image_url and 'images' in product and len(product['images']) > 0:
                        image_url = product['images'][0].get('url')

                    buy_url = f"https://www.sheinindia.in/p/{pid}"
                    
                    msg_parts = [f"🔥 <b>{name}</b>", f"💰 <b>{price_val}</b>\n"]
                    
                    if stock_data:
                        priority = stock_data['priority']
                        stock = stock_data['stock']
                        
                        if priority: msg_parts.append(f"🎯 <b>Priority:</b> {', '.join(priority)}\n")
                        
                        if stock:
                            all_sizes_text = "\n".join([f"{'✅' if q>0 else '❌'} {s}: {q}" for s, q in stock.items()])
                            msg_parts.append(f"📏 <b>Full Stock:</b>\n<pre>{all_sizes_text}</pre>")
                        else:
                            msg_parts.append("⚠️ Stock details loading failed / Sold out")
                    else:
                        msg_parts.append("⚡ <i>Fast Alert (Stock check skipped due to API block)</i>")

                    msg = "\n".join(msg_parts)
                    send_telegram_fast(msg, token, image_url=image_url, button_url=buy_url)
                    log(f"Alert Sent for {pid} with Stock Info!", "STOCK")
                except Exception as e:
                    pass
                finally:
                    # Guarantee task_done is called to prevent queue blocking forever
                    self.alert_queue.task_done()
            except queue.Empty: continue

    def _extract_and_queue_products(self, products, cat_name):
        """Helper to process products instantly and free memory"""
        new_items = []
        for p in products:
            pid = p.get('fnlColorVariantData', {}).get('colorGroup') or p.get('code')
            if not pid:
                u = p.get('url', '')
                if '/p/' in u: pid = u.split('/p/')[1].split('.html')[0].split('?')[0]
            if not pid: continue

            if self.check_and_add_seen(pid):
                new_items.append((pid, p))

        if new_items:
            log(f"[{cat_name}] {len(new_items)} NEW ITEMS! Fetching stock instantly...", "STOCK")
            for pid, p in new_items:
                try:
                    self.alert_queue.put({
                        'id': pid, 'category': cat_name, 'product': p, 
                        'token': get_target_token(cat_name, p)
                    }, timeout=2)
                except queue.Full:
                    pass

    def _page_fetcher_worker(self):
        while self.running:
            try:
                task = self.page_fetch_queue.get(timeout=1)
                if task is None: break
                
                try:
                    data = fetch_api(task['url'])
                    if data and isinstance(data, dict):
                        # Pipelining: Process and send to alert queue IMMEDIATELY
                        products = data.get('products', [])
                        self._extract_and_queue_products(products, task['cat_name'])
                        
                        # Delete to free memory instantly
                        del products
                        del data
                except Exception as e:
                    pass
                finally:
                    # Guarantee task_done is called
                    self.page_fetch_queue.task_done()
                    
            except queue.Empty: continue

    def process_category(self, cat_name):
        config = CATEGORY_CONFIGS[cat_name]
        base_url = config['url']
        consecutive_failures = 0

        while self.running:
            try:
                # Ajio API uses currentPage=0 for pagination
                first_page_url = re.sub(r'currentPage=\d+', 'currentPage=0', base_url)
                data = fetch_api(first_page_url)

                if not isinstance(data, dict):
                    consecutive_failures += 1
                    time.sleep(2 if consecutive_failures > 5 else 0.5)
                    continue

                consecutive_failures = 0
                total_pages = data.get('pagination', {}).get('totalPages', 1)
                
                # Process 1st page directly (Zero Wait Time)
                self._extract_and_queue_products(data.get('products', []), cat_name)
                del data # Free memory
                
                # Push remaining pages to fetch queue
                for page_num in range(1, total_pages):
                    page_url = re.sub(r'currentPage=\d+', f'currentPage={page_num}', base_url)
                    self.page_fetch_queue.put({'url': page_url, 'cat_name': cat_name})

                # Wait until workers finish fetching this batch so we don't duplicate loops instantly
                while not self.page_fetch_queue.empty():
                    time.sleep(0.5)

                gc.collect() 
                time.sleep(CHECK_INTERVAL)
            except Exception as e: 
                time.sleep(1)

    def start(self):
        log("⚡⚡ ULTRA FAST PIPELINE BOT STARTED ⚡⚡", "FAST")

        if not setup_multi_session_pool(): return

        log(f"⚡ {PAGE_FETCH_WORKERS} FETCHERS | {NUM_WORKERS} WORKERS", "SUCCESS")

        threading.Thread(target=self._db_writer, daemon=True).start()
        threading.Thread(target=self_ping_keeper, daemon=True).start()
        threading.Thread(target=self._session_clear_worker, daemon=True).start()

        for _ in range(PAGE_FETCH_WORKERS):
            threading.Thread(target=self._page_fetcher_worker, daemon=True).start()

        for _ in range(NUM_WORKERS):
            threading.Thread(target=self._alert_worker, daemon=True).start()

        for cat in CATEGORY_CONFIGS.keys():
            threading.Thread(target=self.process_category, args=(cat,), daemon=True).start()

        log("🚀 BOT IS RUNNING SAFELY WITHIN 512MB RAM", "SUCCESS")
        while self.running: time.sleep(1)

# ==========================================
# 🌐 FLASK HEALTH DASHBOARD
# ==========================================

monitor_instance = None
start_time = datetime.now()
ping_count = 0

@app.route('/health')
def health():
    global ping_count
    ping_count += 1
    return jsonify({
        "status": "healthy",
        "fingerprints_pool_size": len(API_SESSIONS_POOL),
        "uptime_hours": round((datetime.now() - start_time).total_seconds() / 3600, 2),
        "ping_count": ping_count,
        "memory_optimized": True
    })

def run_flask():
    from waitress import serve
    serve(app, host='0.0.0.0', port=PORT, threads=4)

if __name__ == "__main__":
    required_vars = ["TOKEN_MEN", "TOKEN_WOMEN", "ADMIN_CHAT_ID", "COOKIE_FILE_CONTENT"]
    if [v for v in required_vars if not os.environ.get(v)]:
        log("Missing environment variables!", "ERROR"); exit(1)

    threading.Thread(target=run_flask, daemon=True).start()
    
    monitor_instance = CompleteCoverageMonitor()
    try: monitor_instance.start()
    except KeyboardInterrupt: monitor_instance.running = False
