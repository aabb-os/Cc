import os
import telebot
import threading
import time
import random
import string
import requests
import json
from collections import Counter
from curl_cffi import requests as curl_requests
from flask import Flask

# --- إعدادات Flask (الوهمي) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_flask():
    # المنصة راح تعطينا البورت في متغير البيئة PORT، وإذا ما لقته بياخذ 8000
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية للبوت ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
NPSSO_TOKEN = os.environ.get("NPSSO_TOKEN", "zoxZdmM5dYcRZVOolR9JnxeUQ6u2jactLilxqhGUrP9DtkAhT39JRBdsPDgeDRlI")

if not TOKEN or OWNER_ID == 0:
    print("❌ خطأ: تأكد من إضافة BOT_TOKEN و OWNER_ID في متغيرات البيئة.")
    exit(1)

bot = telebot.TeleBot(TOKEN)

try:
    import psnawp_api
    from psnawp_api import PSNAWP
    from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError
    psnawp = PSNAWP(NPSSO_TOKEN)
    print(f"PSN Connected: {psnawp.me().online_id}")
except Exception as e:
    print(f"PSN Token Error: {e}")
    psnawp = None

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
stop_psn = threading.Event()
stop_discord = threading.Event()

stats = {
    "tiktok_checked": 0, "tiktok_found": 0,
    "psn_checked": 0, "psn_found": 0,
    "discord_checked": 0, "discord_found": 0
}

def is_owner(m): return m.from_user.id == OWNER_ID

# ==========================================
# دوال التوليد
# ==========================================
def gen_tiktok():
    chars = string.ascii_lowercase + string.digits
    seps = ['.', '_']
    while True:
        p = [random.choice(chars) for _ in range(5)]
        pos = random.sample([1, 2, 3], 2)
        for idx in pos: p[idx] = random.choice(seps)
        u = "".join(p)
        if u[-1] != '.': yield u, 'شبه ثلاثي🤩'

def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        if len(set(u)) < 5: yield u

def gen_discord():
    chars = string.ascii_lowercase + string.digits
    seps = ['.', '_']
    while True:
        p = [random.choice(chars) for _ in range(5)]
        pos = random.sample([1, 2, 3], 2)
        for idx in pos: p[idx] = random.choice(seps)
        u = "".join(p)
        if u[-1] not in seps and '..' not in u: yield u, 'شبه ثلاثي 🤩'

# ==========================================
# دوال الفحص
# ==========================================
def check_tiktok(username):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(f"https://www.tiktok.com/@{username}", headers=headers, timeout=10)
        if r.status_code == 404: return True
        if r.status_code == 200:
            if f'"uniqueId":"{username}"' in r.text: return False
            if '10221' in r.text: return True
        if r.status_code in [403, 429, 503]: return "BLOCKED"
    except Exception: pass
    return None

def check_psn_ghost_browser(username):
    if not psnawp: return None
    proxy = get_next_proxy()
    if not proxy: return "WAIT" 

    proxies = {"http": proxy, "https": proxy}
    session = curl_requests.Session(impersonate="safari15_5", proxies=proxies)
    
    try:
        session.get("https://www.playstation.com/en-us/", timeout=8)
        session.get("https://my.account.sony.com/central/unauth/", timeout=8)
        
        ts = int(time.time() * 1000)
        url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={username}&_={ts}"
        headers = {"Accept": "application/json", "Origin": "https://www.playstation.com", "Referer": "https://www.playstation.com/"}
        
        res = session.get(url, headers=headers, timeout=8)
        if res.status_code in [403, 429]:
            blacklist_proxy(proxy)
            return "BLOCKED"
        if res.status_code == 200:
            data = res.json()
            if data.get("available") is True:
                time.sleep(1)
                try:
                    psnawp.user(online_id=username)
                    return False
                except PSNAWPNotFoundError:
                    return True
                except Exception: return None
            return False
    except Exception:
        blacklist_proxy(proxy)
        pass
    return None

def check_discord_double(username):
    proxy = get_next_proxy()
    if not proxy: return "WAIT"
    proxies = {"http": proxy, "https": proxy}
    
    url = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
    headers = {"Accept": "*/*", "Origin": "https://discord.com", "Referer": "https://discord.com/register", "Content-Type": "application/json"}
    
    for _ in range(2): 
        try:
            r = discord_session.post(url, json={"username": username}, headers=headers, proxies=proxies, timeout=8)
            if r.status_code == 200: 
                if r.json().get("taken", True) is True: return False
            elif r.status_code == 429: 
                blacklist_proxy(proxy)
                return "BLOCKED"
        except Exception: 
            blacklist_proxy(proxy)
            pass
        time.sleep(1)
    return True

# ==========================================
# دوال التشغيل
# ==========================================
def worker_tiktok(chat_id, thread_id):
    try:
        for u, label in gen_tiktok():
            if stop_tiktok.is_set(): break
            stats["tiktok_checked"] += 1
            res = check_tiktok(u)
            if res is True:
                stats["tiktok_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🥷🏼✨\n( تيك توك - {label} )")
            elif res == "BLOCKED": time.sleep(120)
            time.sleep(random.uniform(1.0, 2.0)) 
    except Exception as e: print(f"Err TikTok: {e}")

def worker_psn(chat_id, thread_id):
    try:
        for u in gen_psn():
            if stop_psn.is_set(): break
            res = check_psn_ghost_browser(u)
            if res == "WAIT":
                time.sleep(5) 
                continue
            stats["psn_checked"] += 1
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - خماسي مكرر )")
            time.sleep(random.uniform(4.0, 7.0)) 
    except Exception as e: print(f"Err PSN: {e}")

def worker_discord(chat_id, thread_id):
    try:
        for u, label in gen_discord():
            if stop_discord.is_set(): break
            res = check_discord_double(u)
            if res == "WAIT":
                time.sleep(5) 
                continue
            stats["discord_checked"] += 1
            if res is True:
                stats["discord_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 💎⚡️\n( ديسكورد - {label} )")
            time.sleep(random.uniform(5.0, 9.0)) 
    except Exception as e: print(f"Err Discord: {e}")

def start_psn_snipers(chat_id):
    for i in range(5): 
        threading.Thread(target=worker_psn, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.2)

def start_discord_snipers(chat_id):
    for i in range(3): 
        threading.Thread(target=worker_discord, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.2)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت القنص النووي (Ghost Browser)\n\n"
                     "/start_all - تشغيل الكل\n"
                     "/tiktok - تيك توك\n"
                     "/psn - سوني\n"
                     "/discord - ديسكورد\n"
                     "/stop_all - إيقاف الكل\n"
                     "/status - الإحصائيات\n"
                     "/proxy_status - حالة البروكسيات")

@bot.message_handler(commands=['start_all'])
def cmd_start_all(m):
    if not is_owner(m): return
    stop_tiktok.clear(); stop_psn.clear(); stop_discord.clear()
    for i in range(3): threading.Thread(target=worker_tiktok, args=(m.chat.id, i+1), daemon=True).start()
    bot.send_message(m.chat.id, "🚀 تيك توك (3 خيوط)!")
    start_psn_snipers(m.chat.id)
    bot.send_message(m.chat.id, "🚀 سوني (5 خيوط)!")
    start_discord_snipers(m.chat.id)
    bot.send_message(m.chat.id, "🚀 ديسكورد (3 خيوط)!")

@bot.message_handler(commands=['tiktok'])
def cmd_tiktok(m):
    if not is_owner(m): return
    stop_tiktok.clear()
    for i in range(3): threading.Thread(target=worker_tiktok, args=(m.chat.id, i+1), daemon=True).start()
    bot.reply_to(m, "TikTok Started!")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 سوني (5 خيوط)!")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['discord'])
def cmd_discord(m):
    if not is_owner(m): return
    stop_discord.clear()
    bot.reply_to(m, "🚀 ديسكورد (3 خيوط)!")
    start_discord_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_tiktok.set(); stop_psn.set(); stop_discord.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات:**\n\n"
           f"**تيك توك:**\nتم فحصه: {stats['tiktok_checked']} | تم صيده: {stats['tiktok_found']}\n"
           f"**سوني:**\nتم فحصه: {stats['psn_checked']} | تم صيده: {stats['psn_found']}\n"
           f"**ديسكورد:**\nتم فحصه: {stats['discord_checked']} | تم صيده: {stats['discord_found']}\n\n"
           f"🔗 **البروكسيات الشغالة:** {proxy_stats['working']} | **المحظورة:** {proxy_stats['blacklisted']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

@bot.message_handler(commands=['proxy_status'])
def cmd_proxy_status(m):
    if not is_owner(m): return
    with proxy_lock:
        msg = (f"🔗 **حالة البروكسيات:**\n\n"
               f"▪️ تم سحب: **{proxy_stats['fetched']}** بروكسي\n"
               f"▪️ تم فحص: **{proxy_stats['checked']}** بروكسي\n"
               f"▪️ الشغال حالياً: **{proxy_stats['working']}** بروكسي\n"
               f"▪️ في القائمة السوداء: **{proxy_stats['blacklisted']}** بروكسي\n\n")
        if working_proxies:
            msg += "أمثلة:\n" + "\n".join([f"`{p}`" for p in working_proxies[:5]])
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    # 1. تشغيل سيرفر الويب الوهمي (عشان المنصة ما تطفينا)
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("Bot is running...")
    try: 
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e: 
        print(f"Webhook delete error: {e}")
        
    # 2. تشغيل البوت
    bot.infinity_polling()
