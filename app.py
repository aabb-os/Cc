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
    me = psnawp.me() # هذا السطر يجبر المكتبة على تسجيل الدخول
    print(f"✅ PSNAWP Logged in as: {me.online_id}")
except Exception as e:
    init_error = str(e)
    print(f"❌ PSNAWP initialization error: {init_error}")

stop_psn = threading.Event()
stats = {"checked": 0, "found": 0, "errors": 0}
stats_lock = threading.Lock()

def is_owner(m): return m.from_user.id in OWNER_IDS

def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# محرك الفحص (الموقع القديم)
# ==========================================
def check_psn_legacy(username):
    # نضرب الرابط القديم اللي يرجع {} للمتاح
    url = f"https://secure.us.playstation.com/playstation/psn/profile/public/userData?onlineId={username}"
    headers = {
        "Referer": "https://secure.us.playstation.com/logged-in/trophies/public-trophies/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15"
    }
    try:
        res = curl_requests.get(url, headers=headers, impersonate="safari15_5", timeout=10)
        if res.status_code == 200:
            if res.text.strip() == "{}":
                return True # متاح
            return False # محجوز
        elif res.status_code in [403, 429]:
            return "BLOCKED"
    except Exception:
        pass
    return None

def worker(chat_id):
    global stats
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            with stats_lock: stats["checked"] += 1
            
            # فحص إضافي عبر PSNAWP عشان نتأكد إذا كان الحساب خاص
            is_private = False
            try:
                psnawp.user(online_id=u)
                # إذا لقاه هنا، يعني محجوز أكيد
                with stats_lock: stats["checked"] += 1 # نحسبها كفحصين
                is_private = True 
            except PSNAWPForbiddenError:
                is_private = True
            except PSNAWPNotFoundError:
                pass # قد يكون متاح، نكمل
            except Exception:
                pass

            if not is_private:
                res = check_psn_legacy(u)
                
                if res is True:
                    utype = "خماسي مكرر" if len(set(u)) < 5 else "خماسي"
                    with stats_lock: stats["found"] += 1
                    bot.send_message(chat_id, f"استلم يالامير {u} 🎮🔥\n( سوني - {utype} - متاح )")
                elif res == "BLOCKED":
                    time.sleep(10)
                    continue
            else:
                res = "BLOCKED" # محجوز

            # سرعة آمنة لمنع الحظر
            time.sleep(3)
            
        except Exception:
            with stats_lock: stats["errors"] += 1
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني.\nالسبب: `{init_error}`")
        return
    threading.Thread(target=worker, args=(chat_id,), daemon=True).start()

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
    bot.reply_to(m, "🚀 جاري التشغيل...")
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
    print("Sony V9 is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception:
            time.sleep(5)
