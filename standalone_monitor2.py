import json
import time
import threading
import queue
import os
import re
import random
import sqlite3
from datetime import datetime
from curl_cffi import requests
from flask import Flask, jsonify

# ==========================================
# ⚙️ COMPLETE COVERAGE + MULTI-FINGERPRINT + ULTRA FAST
# ==========================================

TOKEN_MEN = os.environ.get("TOKEN_MEN")
TOKEN_WOMEN = os.environ.get("TOKEN_WOMEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
PORT = int(os.environ.get("PORT", 8080))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")  # Render provides this automatically

SESSION_DB_PATH = "session_monitor.db"
CHECK_INTERVAL = 0.01  # Ultra fast - 10ms
NUM_WORKERS = 150  # More workers for parallel processing
PAGE_FETCH_WORKERS = 20  # Parallel page fetchers
SELF_PING_INTERVAL = 600  # 10 minutes

# Priority Sizes for Stock
PRIORITY_SIZES = ["M", "L", "XL", "32", "34", "36"]

CATEGORY_CONFIGS = {
    'Universal': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&currentPage=0&pageSize=45&format=json&query=%3Arelevance&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein"
    },
    'Women': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&Page=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AWomen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AWomen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein"
    },
    'Men': {
        'url': "https://www.sheinindia.in/api/category/sverse-5939-37961?fields=SITE&Page=0&pageSize=45&format=json&query=%3Arelevance%3Agenderfilter%3AMen&gridColumns=5&segmentIds=23%2C14%2C18%2C9&cohortIds=value%7Cmen%2CTEMP_M1_LL_FG_NOV&customerType=Existing&facets=genderfilter%3AMen&customertype=Existing&advfilter=true&platform=Desktop&showAdsOnNextPage=false&is_ads_enable_plp=true&displayRatings=true&segmentIds=&&store=shein"
    }
}

app = Flask(__name__)

# ==========================================
# 🛡️ MULTI-FINGERPRINT ANTI-BAN SYSTEM
# ==========================================

# Different browsers and versions to rotate and prevent blocks
BROWSER_FINGERPRINTS = [
    "chrome100", "chrome101", "chrome104", "chrome106", "chrome108",
    "chrome110", "chrome114", "chrome116", "chrome119", "chrome120",
    "edge101", "edge114", "edge116",
    "safari15_3", "safari15_5", "safari15_6_1", "safari16_0", "safari17_0"
]

API_SESSIONS_POOL = []

def log(message, level="INFO"):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️", "FAST": "⚡", "PING": "🔔", "STOCK": "📦"}
    icon = icons.get(level, "📝")
    print(f"[{timestamp}] {icon} {message}", flush=True)

def setup_multi_session_pool():
    """Creates a pool of sessions, each with a different fingerprint"""
    try:
        cookie_content = os.environ.get("COOKIE_FILE_CONTENT")
        if not cookie_content:
            log("No cookies provided in environment!", "ERROR")
            return False

        cookies_list = json.loads(cookie_content)
        cookies_dict = {}
        for cookie in cookies_list:
            name = cookie.get('name')
            value = cookie.get('value')
            if name and value:
                cookies_dict[name] = value

        # Create 30 distinct sessions with random fingerprints
        for _ in range(30):
            fingerprint = random.choice(BROWSER_FINGERPRINTS)
            session = requests.Session(impersonate=fingerprint)
            
            # Inject cookies
            for name, value in cookies_dict.items():
                session.cookies.set(name, value, domain=".sheinindia.in")
            
            API_SESSIONS_POOL.append({
                "session": session,
                "fingerprint": fingerprint
            })

        log(f"Multi-Fingerprint Pool ready with {len(API_SESSIONS_POOL)} rotating sessions!", "SUCCESS")
        return True
    except Exception as e:
        log(f"Session Pool Setup failed: {e}", "ERROR")
        return False

def fetch_api(url, timeout=10):
    """Fetches URL using a random fingerprint to avoid blocks"""
    try:
        # Rotate fingerprint randomly
        session_data = random.choice(API_SESSIONS_POOL)
        session = session_data["session"]
        
        # Add random cache buster
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
    """Fetches real-time stock info for a single product"""
    url = f"https://sheinindia.ajio.com/api/p/{pid}?fields=SITE"
    data = fetch_api(url, timeout=5)
    
    if not data: return None
    
    current_stock = {}
    found_priority = []
    
    try:
        # Extract stock logic similar to db_stock_monitor.py
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
            # clean thumbnail
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
# 🔔 SELF-PING KEEPER (PREVENTS SLEEP)
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
# 🚀 COMPLETE COVERAGE ULTRA FAST MONITOR
# ==========================================

class CompleteCoverageMonitor:
    def __init__(self):
        self.running = True
        self.alert_queue = queue.Queue()
        self.db_queue = queue.Queue()
        self.session_cache = set()
        self.page_fetch_queue = queue.Queue()
        self.page_results = {}
        self.page_results_lock = threading.Lock()

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

    def _db_writer(self):
        conn = sqlite3.connect(SESSION_DB_PATH, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except: pass

        batch = []
        while self.running:
            try:
                pid = self.db_queue.get(timeout=0.1)
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
        self.db_queue.put(pid)
        return True

    def _alert_worker(self):
        """Worker that fetches stock and sends alerts"""
        while self.running:
            try:
                item = self.alert_queue.get(timeout=1)
                pid = item['id']
                token = item['token']
                product = item['product']

                # 1. Fetch deep stock info
                stock_data = fetch_product_stock(pid)
                
                # 2. Extract Details
                name = product.get('name', 'New Product')
                if stock_data and stock_data.get('full_data'):
                    name = stock_data['full_data'].get('productRelationID', stock_data['full_data'].get('name', name))

                # Price
                price_val = "Check Link"
                if 'price' in product:
                    raw = product['price'].get('value')
                    if raw: price_val = f"₹{int(raw)}"

                # Image
                image_url = None
                if stock_data and 'full_data' in stock_data:
                    fd = stock_data['full_data']
                    image_url = fd.get('selected', {}).get('modelImage', {}).get('url')
                    if not image_url and 'images' in fd and fd['images']: image_url = fd['images'][0].get('url')

                if not image_url and 'images' in product and len(product['images']) > 0:
                    image_url = product['images'][0].get('url')

                buy_url = f"https://www.sheinindia.in/p/{pid}"
                
                # Format Stock Message
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

                self.alert_queue.task_done()
            except queue.Empty: continue
            except: pass

    def _page_fetcher_worker(self):
        while self.running:
            try:
                task = self.page_fetch_queue.get(timeout=1)
                if task is None: break
                
                data = fetch_api(task['url'])
                
                with self.page_results_lock:
                    if task['request_id'] not in self.page_results:
                        self.page_results[task['request_id']] = {}
                    self.page_results[task['request_id']][task['page_num']] = data

                self.page_fetch_queue.task_done()
            except queue.Empty: continue
            except: pass

    def fetch_all_pages_parallel(self, cat_name, base_url, total_pages):
        request_id = f"{cat_name}_{int(time.time())}"
        for page_num in range(total_pages):
            page_url = re.sub(r'Page=\d+', f'Page={page_num}', base_url)
            self.page_fetch_queue.put({
                'request_id': request_id, 'page_num': page_num, 'url': page_url
            })

        self.page_fetch_queue.join()

        all_products = []
        with self.page_results_lock:
            if request_id in self.page_results:
                for page_num in range(total_pages):
                    if page_num in self.page_results[request_id]:
                        data = self.page_results[request_id][page_num]
                        if isinstance(data, dict):
                            all_products.extend(data.get('products', []))
                del self.page_results[request_id]
        return all_products

    def process_category(self, cat_name):
        config = CATEGORY_CONFIGS[cat_name]
        base_url = config['url']
        consecutive_failures = 0

        while self.running:
            try:
                first_page_url = re.sub(r'Page=\d+', 'currentPage=0', base_url)
                data = fetch_api(first_page_url)

                if not isinstance(data, dict):
                    consecutive_failures += 1
                    time.sleep(2 if consecutive_failures > 5 else 0.5)
                    continue

                consecutive_failures = 0
                total_pages = data.get('pagination', {}).get('totalPages', 1)
                
                # Log without spamming terminal too much
                # log(f"[{cat_name}] Scanning {total_pages} pages using Rotating Fingerprints", "FAST")
                
                all_products = self.fetch_all_pages_parallel(cat_name, base_url, total_pages)

                new_items = []
                for p in all_products:
                    pid = p.get('fnlColorVariantData', {}).get('colorGroup') or p.get('code')
                    if not pid:
                        u = p.get('url', '')
                        if '/p/' in u: pid = u.split('/p/')[1].split('.html')[0].split('?')[0]
                    if not pid: continue

                    if self.check_and_add_seen(pid):
                        new_items.append((pid, p))

                if new_items:
                    log(f"[{cat_name}] {len(new_items)} NEW PRODUCTS DETECTED! Fetching stock...", "STOCK")
                    for pid, p in new_items:
                        self.alert_queue.put({
                            'id': pid, 'category': cat_name, 'product': p, 
                            'token': get_target_token(cat_name, p)
                        })

                time.sleep(CHECK_INTERVAL)
            except Exception as e: time.sleep(1)

    def start(self):
        log("⚡⚡ MULTI-FINGERPRINT ULTRA FAST MONITOR ⚡⚡", "FAST")

        if not setup_multi_session_pool(): return

        log(f"⚡ {PAGE_FETCH_WORKERS} PAGE FETCHERS | {NUM_WORKERS} ALERT/STOCK WORKERS", "SUCCESS")

        threading.Thread(target=self._db_writer, daemon=True).start()
        threading.Thread(target=self_ping_keeper, daemon=True).start()

        for _ in range(PAGE_FETCH_WORKERS):
            threading.Thread(target=self._page_fetcher_worker, daemon=True).start()

        for _ in range(NUM_WORKERS):
            threading.Thread(target=self._alert_worker, daemon=True).start()

        for cat in CATEGORY_CONFIGS.keys():
            threading.Thread(target=self.process_category, args=(cat,), daemon=True).start()

        log("🚀 BOT IS RUNNING 24/7 WITH ANTI-BAN AND STOCK PARSING", "SUCCESS")
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
        "anti_ban": "Active (curl_cffi rotation)"
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
