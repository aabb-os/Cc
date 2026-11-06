import os
import telebot
import threading
import time
import random
import string
import requests
import json
from curl_cffi import requests as curl_requests
from flask import Flask

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- قراءة الإعدادات من المتغيرات (Environment Variables) ---
TOKEN = os.environ.get("BOT_TOKEN")
# الأيديهات (نقرأها من المتغيرات أو نحطها احتياط)
OWNER_IDS_STR = os.environ.get("OWNER_ID", "7972911357,8487652113")
OWNER_IDS = [int(i.strip()) for i in OWNER_IDS_STR.split(",")]

if not TOKEN:
    print("❌ خطأ: تأكد من إضافة BOT_TOKEN في المتغيرات.")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# --- نظام البروكسيات ---
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
proxy_stats = {"fetched": 0, "checked": 0, "working": 0, "blacklisted": 0}
proxy_bg_running = True

def proxy_background_worker():
    global proxy_stats, working_proxies, proxy_blacklist
    while proxy_bg_running:
        now = time.time()
        with proxy_lock:
            expired = [p for p, t in proxy_blacklist.items() if now > t]
            for p in expired:
                del proxy_blacklist[p]
        
        if len(working_proxies) < 20:
            raw_proxies = set()
            for url in PROXY_SOURCES:
                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        for line in r.text.splitlines():
                            line = line.strip()
                            if line and ":" in line:
                                raw_proxies.add(line)
                except Exception: pass
            
            with proxy_lock: proxy_stats["fetched"] = len(raw_proxies)
            
            sample = random.sample(list(raw_proxies), min(150, len(raw_proxies)))
            for p in sample:
                if len(working_proxies) >= 20: break
                proxy_url = f"http://{p}"
                with proxy_lock:
                    if proxy_url in working_proxies or proxy_url in proxy_blacklist:
                        continue
                try:
                    res = curl_requests.get("https://api.ipify.org?format=json", proxy=proxy_url, timeout=4)
                    if res.status_code == 200:
                        with proxy_lock:
                            working_proxies.append(proxy_url)
                            proxy_stats["working"] = len(working_proxies)
                except Exception: pass
                with proxy_lock:
                    proxy_stats["checked"] += 1
        
        time.sleep(10)

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
            proxy_blacklist[proxy] = time.time() + 180 
            if proxy in working_proxies:
                working_proxies.remove(proxy)
            proxy_stats["blacklisted"] = len(proxy_blacklist)
            proxy_stats["working"] = len(working_proxies)

discord_session = curl_requests.Session(impersonate="chrome124")
stop_tiktok = threading.Event()
stop_discord = threading.Event()

stats = {
    "tiktok_checked": 0, "tiktok_found": 0,
    "discord_checked": 0, "discord_found": 0
}

def is_owner(m): 
    return m.from_user.id in OWNER_IDS

# ==========================================
# دوال التوليد (رباعي + شبه ثلاثي)
# ==========================================
def gen_tiktok():
    chars = string.ascii_lowercase + string.digits
    seps = ['.', '_']
    while True:
        mode = random.choice(['4L', '5L_2S'])
        if mode == '4L':
            u = "".join(random.choice(chars) for _ in range(4))
            yield u, '4L'
        else:
            p = [random.choice(chars) for _ in range(5)]
            pos = random.sample([1, 2, 3], 2)
            for idx in pos: p[idx] = random.choice(seps)
            u = "".join(p)
            if u[-1] != '.' and '..' not in u: 
                yield u, '5L_2S'

def gen_discord():
    chars = string.ascii_lowercase + string.digits
    seps = ['.', '_']
    while True:
        mode = random.choice(['4L', '5L_2S'])
        if mode == '4L':
            u = "".join(random.choice(chars) for _ in range(4))
            yield u, '4L'
        else:
            p = [random.choice(chars) for _ in range(5)]
            pos = random.sample([1, 2, 3], 2)
            for idx in pos: p[idx] = random.choice(seps)
            u = "".join(p)
            if u[-1] not in seps and '..' not in u:
                yield u, '5L_2S'

# ==========================================
# دوال الفحص
# ==========================================
def check_tiktok(username):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = curl_requests.get(f"https://www.tiktok.com/@{username}", headers=headers, impersonate="chrome110", timeout=10)
        if r.status_code == 404: return True
        if r.status_code == 200:
            if f'"uniqueId":"{username}"' in r.text: return False
            if '10221' in r.text or "Couldn't find this account" in r.text: return True
        if r.status_code in [403, 429, 503]: return "BLOCKED"
    except Exception: pass
    return None

def check_discord(username):
    proxy = get_next_proxy()
    if not proxy: return "WAIT"
    proxies = {"http": proxy, "https": proxy}
    
    url = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
    headers = {"Accept": "*/*", "Origin": "https://discord.com", "Referer": "https://discord.com/register", "Content-Type": "application/json"}
    
    try:
        r = discord_session.post(url, json={"username": username}, headers=headers, proxies=proxies, timeout=8)
        if r.status_code == 200: 
            return not r.json().get("taken", True)
        elif r.status_code == 429: 
            blacklist_proxy(proxy)
            return "BLOCKED"
    except Exception: 
        blacklist_proxy(proxy)
    return None

# ==========================================
# دوال التشغيل
# ==========================================
def worker_tiktok(chat_id, thread_id):
    try:
        for u, utype in gen_tiktok():
            if stop_tiktok.is_set(): break
            stats["tiktok_checked"] += 1
            
            res = check_tiktok(u)
            if res is True:
                time.sleep(1.5) 
                res2 = check_tiktok(u)
                if res2 is True:
                    stats["tiktok_found"] += 1
                    label = "رباعي 🌚🚨" if utype == '4L' else "شبه ثلاثي 🤩"
                    bot.send_message(chat_id, f"استلم يالامير {u} 🥷🏼✨\n( تيك توك - {label} )")
            elif res == "BLOCKED":
                time.sleep(120)
            time.sleep(random.uniform(1.0, 2.0)) 
    except Exception as e: print(f"Err TikTok: {e}")

def worker_discord(chat_id, thread_id):
    try:
        for u, utype in gen_discord():
            if stop_discord.is_set(): break
            stats["discord_checked"] += 1
            
            res = check_discord(u)
            if res is True:
                time.sleep(1.5) 
                res2 = check_discord(u)
                if res2 is True:
                    stats["discord_found"] += 1
                    label = "رباعي 🌚🚨" if utype == '4L' else "شبه ثلاثي 🤩"
                    bot.send_message(chat_id, f"استلم يالامير {u} ✨🤩\n( ديسكورد - {label} )")
            elif res == "BLOCKED":
                time.sleep(60) 
            elif res == "WAIT":
                time.sleep(5)
            time.sleep(random.uniform(3.0, 6.0)) 
    except Exception as e: print(f"Err Discord: {e}")

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت القنص (Render)\n\n/start_all\n/tiktok\n/discord\n/stop_all\n/status")

@bot.message_handler(commands=['start_all'])
def cmd_start_all(m):
    if not is_owner(m): return
    stop_tiktok.clear(); stop_discord.clear()
    for i in range(3): threading.Thread(target=worker_tiktok, args=(m.chat.id, i+1), daemon=True).start()
    bot.send_message(m.chat.id, "🚀 تيك توك (3 خيوط)!")
    for i in range(3): threading.Thread(target=worker_discord, args=(m.chat.id, i+1), daemon=True).start()
    bot.send_message(m.chat.id, "🚀 ديسكورد (3 خيوط)!")

@bot.message_handler(commands=['tiktok'])
def cmd_tiktok(m):
    if not is_owner(m): return
    stop_tiktok.clear()
    for i in range(3): threading.Thread(target=worker_tiktok, args=(m.chat.id, i+1), daemon=True).start()
    bot.reply_to(m, "TikTok Started!")

@bot.message_handler(commands=['discord'])
def cmd_discord(m):
    if not is_owner(m): return
    stop_discord.clear()
    for i in range(3): threading.Thread(target=worker_discord, args=(m.chat.id, i+1), daemon=True).start()
    bot.reply_to(m, "Discord Started!")

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_tiktok.set(); stop_discord.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات:**\n\n"
           f"**تيك توك:** {stats['tiktok_found']} من {stats['tiktok_checked']}\n"
           f"**ديسكورد:** {stats['discord_found']} من {stats['discord_checked']}\n"
           f"🔗 **البروكسيات:** {proxy_stats['working']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
