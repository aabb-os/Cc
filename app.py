import os
import telebot
import threading
import time
import random
import string
import datetime
from flask import Flask
from curl_cffi import requests as curl_requests

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "PSN V9 Sniper is running!"

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

# --- إعداد البروكسي ---
def load_proxies():
    proxies = []
    if os.path.exists("proxies.txt"):
        with open("proxies.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line: proxies.append(line)
    return proxies

PROXIES = load_proxies()
proxy_lock = threading.Lock()

def get_proxy():
    with proxy_lock:
        if PROXIES:
            return random.choice(PROXIES)
    return None

# --- متغيرات التحكم ---
stop_psn = threading.Event()
stats = {"checked": 0, "found": 0, "errors": 0}
stats_lock = threading.Lock()
MAX_THREADS = 25 # زيادة الخيوط لزيادة السرعة

def is_owner(m): return m.from_user.id in OWNER_IDS

# توليد أسماء 5 أحرف (حرف + 4 أحرف/أرقام) لزيادة فرصة الإيجاد
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# محرك الفحص (الموقع القديم - سريع جداً)
# ==========================================
def check_psn_legacy(username):
    url = f"https://secure.us.playstation.com/playstation/psn/profile/public/userData?onlineId={username}"
    headers = {
        "Host": "secure.us.playstation.com",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "Referer": "https://secure.us.playstation.com/logged-in/trophies/public-trophies/",
    }
    proxy = get_proxy()
    
    try:
        res = curl_requests.get(
            url, 
            headers=headers, 
            impersonate="safari15_5", 
            timeout=8, 
            proxy=proxy
        )
        if res.status_code == 200:
            if res.text.strip() == "{}":
                return True # متاح
            return False # محجوز
        elif res.status_code in [403, 429]:
            return "BLOCKED"
    except Exception:
        return "ERROR"
    return "ERROR"

def worker(chat_id, psn_gen):
    global stats
    while not stop_psn.is_set():
        try:
            u = next(psn_gen)
            
            with stats_lock: 
                stats["checked"] += 1
            
            res = check_psn_legacy(u)
            
            if res is True:
                with stats_lock: 
                    stats["found"] += 1
                    total_found = stats["found"]
                
                # النص مطابق 100% للصور
                current_time = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                msg_text = (
                    f"🎯 يوزر PSN متاح!\n"
                    f"👤 {u}\n"
                    f"⏰ {current_time}\n"
                    f"📊 إجمالي: {total_found}"
                )
                bot.send_message(chat_id, msg_text)
                
                time.sleep(1) # استراحة بسيطة بعد الإيجاد
                
            elif res == "BLOCKED":
                # إذا تم حظرنا، ننام فترة أطول لتجنب الحظر النهائي
                time.sleep(random.uniform(10, 20)) 
            else:
                # سرعة عالية عند الفحص العادي
                time.sleep(random.uniform(0.5, 1.5))
                
        except Exception:
            with stats_lock: stats["errors"] += 1
            time.sleep(2)

def start_psn_snipers(chat_id):
    psn_gen = gen_psn()
    for _ in range(MAX_THREADS):
        threading.Thread(target=worker, args=(chat_id, psn_gen), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ PSN V9 Sniper\n\n/psn - تشغيل\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    with stats_lock:
        stats["checked"] = 0
        stats["found"] = 0
        stats["errors"] = 0
    bot.reply_to(m, f"🚀 جاري التشغيل بـ {MAX_THREADS} خيوط...")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_psn.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    with stats_lock:
        msg = (f"📊 **الإحصائيات:**\n"
               f"🔍 الفحص: {stats['checked']}\n"
               f"✅ المتاح: {stats['found']}\n"
               f"⚠️ أخطاء: {stats['errors']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony V9 Sniper is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception:
            time.sleep(5)
