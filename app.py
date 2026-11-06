import os
import telebot
import threading
import time
import random
import string
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError
from curl_cffi import requests as curl_requests
from concurrent.futures import ThreadPoolExecutor

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "PSN V9 is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")
NPSSO_TOKEN = os.environ.get("NPSSO_TOKEN")

if not TOKEN or not OWNER_IDS_STR or not NPSSO_TOKEN:
    print("❌ خطأ: تأكد من BOT_TOKEN و OWNER_ID و NPSSO_TOKEN.")
    exit(1)

OWNER_IDS = [int(i.strip()) for i in OWNER_IDS_STR.split(",")]
bot = telebot.TeleBot(TOKEN)

# --- تهيئة PSNAWP ---
psnawp = None
init_error = None
try:
    psnawp = PSNAWP(NPSSO_TOKEN)
    me = psnawp.me() 
    print(f"✅ PSNAWP Logged in as: {me.online_id}")
except Exception as e:
    init_error = str(e)
    print(f"❌ PSNAWP initialization error: {init_error}")

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
stats = {"checked": 0, "found": 0, "errors": 0, "blocked": 0}
stats_lock = threading.Lock()
MAX_THREADS = 10

def is_owner(m): return m.from_user.id in OWNER_IDS

def gen_psn():
    # توليد أسماء بأطوال مختلفة (3، 4، 5) لزيادة فرصة الإيجاد
    chars = string.ascii_lowercase + string.digits
    length = random.choice([3, 4, 5])
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(length - 1))
        yield u

# ==========================================
# محرك الفحص (الموقع القديم)
# ==========================================
def check_psn_legacy(username):
    url = f"https://secure.us.playstation.com/playstation/psn/profile/public/userData?onlineId={username}"
    headers = {
        "Referer": "https://secure.us.playstation.com/logged-in/trophies/public-trophies/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15"
    }
    proxy = get_proxy()
    
    try:
        res = curl_requests.get(
            url, 
            headers=headers, 
            impersonate="safari15_5", 
            timeout=10, 
            proxy=proxy
        )
        if res.status_code == 200:
            if res.text.strip() == "{}":
                return True # متاح
            return False # محجوز
        elif res.status_code in [403, 429]:
            return "BLOCKED"
        else:
            return "ERROR"
    except Exception as e:
        return "ERROR"

def worker(chat_id, psn_gen):
    while not stop_psn.is_set():
        try:
            u = next(psn_gen)
            
            # الفحص الأول عبر PSNAWP (سريع لكن محدود)
            is_available = False
            try:
                psnawp.user(online_id=u)
                # إذا لم يرمي خطأ، يعني الحساب موجود
                is_available = False 
            except PSNAWPNotFoundError:
                is_available = True # غير موجود، قد يكون متاح
            except PSNAWPForbiddenError:
                is_available = False # محظور أو خاص
            except Exception:
                continue # خطأ في الشبكة، تخطى هذا الاسم
                
            if is_available:
                # الفحص الثاني عبر الموقع القديم للتأكيد
                res = check_psn_legacy(u)
                
                with stats_lock:
                    stats["checked"] += 1
                    if res is True:
                        stats["found"] += 1
                        utype = "ثلاثي" if len(u) == 3 else ("رباعي" if len(u) == 4 else "خماسي")
                        if len(set(u)) < len(u): utype += " مكرر"
                        bot.send_message(chat_id, f"استلم يالامير {u} 🎮🔥\n( سوني - {utype} - متاح )")
                    elif res == "BLOCKED":
                        stats["blocked"] += 1
                        time.sleep(15) # انتظار طويل لو محظور
                    elif res == "ERROR":
                        stats["errors"] += 1

            # سرعة آمنة
            time.sleep(random.uniform(1.5, 3.0))
            
        except Exception:
            with stats_lock: stats["errors"] += 1
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني.\nالسبب: `{init_error}`")
        return
    
    psn_gen = gen_psn()
    # تشغيل عدة Threads لزيادة السرعة
    for _ in range(MAX_THREADS):
        threading.Thread(target=worker, args=(chat_id, psn_gen), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ PSN V9 Bot\n\n/psn - تشغيل\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    with stats_lock:
        stats["checked"] = 0
        stats["found"] = 0
        stats["errors"] = 0
        stats["blocked"] = 0
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
               f"⚠️ أخطاء: {stats['errors']}\n"
               f"🚫 محظور (IP): {stats['blocked']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony V9 is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception:
            time.sleep(5)
