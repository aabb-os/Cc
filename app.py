import os
import telebot
import threading
import time
import random
import string
import requests
from curl_cffi import requests as curl_requests
from flask import Flask

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Speed Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")

if not TOKEN or not OWNER_IDS_STR:
    print("❌ خطأ: تأكد من BOT_TOKEN و OWNER_ID.")
    exit(1)

OWNER_IDS = [int(i.strip()) for i in OWNER_IDS_STR.split(",")]
bot = telebot.TeleBot(TOKEN)

# --- نظام البروكسيات السريع ---
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
]

working_proxies = []
proxy_blacklist = {} 
proxy_lock = threading.Lock()
proxy_cycle_index = 0
proxy_stats = {"working": 0, "blacklisted": 0}

def proxy_background_worker():
    global proxy_stats, working_proxies, proxy_blacklist
    while True:
        now = time.time()
        with proxy_lock:
            # إزالة البروكسيات من القائمة السوداء بعد 5 دقائق
            expired = [p for p, t in proxy_blacklist.items() if now > t]
            for p in expired: del proxy_blacklist[p]
        
        # جلب بروكسيات جديدة إذا قل العدد عن 15
        if len(working_proxies) < 15:
            raw_proxies = set()
            for url in PROXY_SOURCES:
                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        for line in r.text.splitlines():
                            line = line.strip()
                            if line and ":" in line: raw_proxies.add(line)
                except Exception: pass
            
            sample = random.sample(list(raw_proxies), min(100, len(raw_proxies)))
            for p in sample:
                if len(working_proxies) >= 15: break
                proxy_url = f"http://{p}"
                with proxy_lock:
                    if proxy_url in working_proxies or proxy_url in proxy_blacklist: continue
                try:
                    # فحص سريع جداً
                    res = curl_requests.get("https://api.ipify.org?format=json", proxy=proxy_url, timeout=3)
                    if res.status_code == 200:
                        with proxy_lock:
                            working_proxies.append(proxy_url)
                            proxy_stats["working"] = len(working_proxies)
                except Exception: pass
        
        time.sleep(5) # تحديث سريع كل 5 ثواني

threading.Thread(target=proxy_background_worker, daemon=True).start()

def get_next_proxy():
    global proxy_cycle_index
    with proxy_lock:
        if not working_proxies: return None
        for _ in range(len(working_proxies)):
            proxy = working_proxies[proxy_cycle_index % len(working_proxies)]
            proxy_cycle_index += 1
            if proxy not in proxy_blacklist:
                return proxy
    return None

def blacklist_proxy(proxy):
    with proxy_lock:
        if proxy:
            proxy_blacklist[proxy] = time.time() + 300
            if proxy in working_proxies: working_proxies.remove(proxy)
            proxy_stats["blacklisted"] = len(proxy_blacklist)
            proxy_stats["working"] = len(working_proxies)

stop_psn = threading.Event()
stats = {"psn_checked": 0, "psn_found": 0}

def is_owner(m): return m.from_user.id in OWNER_IDS

# ==========================================
# دالة التوليد (5 خانات)
# ==========================================
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# محرك فحص سوني (عبر PSNProfiles + تدوير IP)
# ==========================================
def check_psn_fast(username):
    proxy = get_next_proxy()
    if not proxy: return "NO_PROXY"
    
    proxies = {"http": proxy, "https": proxy}
    
    try:
        # ضرب موقع PSNProfiles (أدق وأسرع من API سوني)
        url = f"https://psnprofiles.com/{username}"
        res = curl_requests.get(url, proxies=proxies, impersonate="chrome110", timeout=8)
        
        if res.status_code == 404:
            return True # متاح 100%
        elif res.status_code == 200:
            return False # محجوز
        elif res.status_code in [403, 429, 503]:
            # إذا انحظر البروكسي من Cloudflare، نحطه في البلاك ليست
            blacklist_proxy(proxy)
            return "BLOCKED"
            
    except Exception:
        blacklist_proxy(proxy)
        return "ERROR"
        
    return False

# ==========================================
# دوال التشغيل
# ==========================================
def worker_psn(chat_id, thread_id):
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            res = check_psn_fast(u)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - 5 خانات متاح 100% )")
            elif res in ["BLOCKED", "ERROR", "NO_PROXY"]:
                time.sleep(0.5) # انتظار نص ثانية بس لو البروكسي انحظر
                continue
                
            time.sleep(0.5) # سرعة الضوء (نص ثانية بين كل فحص)
            
        except Exception as e:
            time.sleep(1)

def start_psn_snipers(chat_id):
    # 10 خيوط عشان السرعة القصوى
    for i in range(10): 
        threading.Thread(target=worker_psn, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.1)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت سوني (سرعة الضوء + تدوير IP)\n\n/psn - تشغيل الصيد\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل 10 خيوط بأقصى سرعة وتدوير IP...")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_psn.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات سوني (سرعة الضوء):**\n\n"
           f"✅ **المتاح:** {stats['psn_found']}\n"
           f"🔍 **إجمالي الفحص:** {stats['psn_checked']}\n\n"
           f"🔗 **البروكسيات الشغالة:** {proxy_stats['working']}\n"
           f"🚫 **البروكسيات المحظورة:** {proxy_stats['blacklisted']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Speed Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
