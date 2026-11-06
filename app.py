import os
import telebot
import threading
import time
import random
import string
import json
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError
from curl_cffi import requests as curl_requests

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Double-Check Bot is running!"

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
    psnawp.me()
    print("✅ PSNAWP initialized successfully.")
except Exception as e:
    init_error = str(e)
    print(f"❌ PSNAWP initialization error: {init_error}")

stop_psn = threading.Event()
stats = {"psn_checked": 0, "psn_found": 0, "psn_private": 0, "psn_error": 0}

def is_owner(m): return m.from_user.id in OWNER_IDS

# ==========================================
# دالة التوليد (5 خانات عشوائية تبدأ بحرف)
# ==========================================
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# محرك الفحص المزدوج (PSNAWP + الموقع الرسمي)
# ==========================================
def check_psn_accurate(username):
    if not psnawp:
        return "NO_AUTH"

    # --- الفحص الأول: PSNAWP ---
    try:
        psnawp.user(online_id=username)
        return False # محجوز
    except PSNAWPForbiddenError:
        stats["psn_private"] += 1
        return False # حساب خاص => محجوز
    except PSNAWPNotFoundError:
        pass # قد يكون متاحاً، نكمل للفحص الثاني
    except Exception as e:
        if "429" in str(e) or "RateLimit" in str(e):
            return "BLOCKED"
        stats["psn_error"] += 1
        return "ERROR"
    
    time.sleep(1.5) # تأخير بسيط بين الفحصين

    # --- الفحص الثاني: الموقع الرسمي (التحقق من الاستجابة الفارغة) ---
    try:
        ts = int(time.time() * 1000)
        url = f"https://secure.us.playstation.com/playstation/psn/profile/public/userData?onlineId={username}&_={ts}"
        headers = {"Referer": "https://secure.us.playstation.com/logged-in/trophies/public-trophies/"}
        res = curl_requests.get(url, headers=headers, impersonate="safari15_5", timeout=10)
        
        if res.status_code == 200 and res.text.strip() == "{}":
            return True # متاح 100% (كلا الفحصين أكدا ذلك)
        elif res.status_code in [403, 429]:
            return "BLOCKED"
        else:
            return False # الموقع الرسمي أظهر أن هناك بيانات، لذا هو محجوز
            
    except Exception:
        return "ERROR"

# ==========================================
# خيط واحد فقط + تأخير عشوائي
# ==========================================
def human_worker(chat_id):
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            res = check_psn_accurate(u)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - 5 خانات متاح 100% )")
            elif res == "BLOCKED":
                time.sleep(30)
                continue
            elif res == "NO_AUTH":
                time.sleep(5)
                continue
            elif res == "ERROR":
                time.sleep(3)
                continue
                
            # تأخير عشوائي بين 4 و 7 ثوانٍ
            time.sleep(random.uniform(4.0, 7.0))
            
        except Exception as e:
            time.sleep(5)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني:\n`{init_error}`")
        return
    threading.Thread(target=human_worker, args=(chat_id,), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    status = "✅ متصل" if psnawp else "❌ غير متصل"
    bot.reply_to(m, f"☢️ بوت سوني (تحقق مزدوج)\nالحالة: {status}\n\n/psn - تشغيل الصيد\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل الصيد (تحقق مزدوج + تأخير)...")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_psn.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات سوني:**\n\n"
           f"✅ **المتاح (مؤكد):** {stats['psn_found']}\n"
           f"🔒 **حسابات خاصة (تم استبعادها):** {stats['psn_private']}\n"
           f"⚠️ **أخطاء (تم تجاهلها):** {stats['psn_error']}\n"
           f"🔍 **إجمالي الفحص:** {stats['psn_checked']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Double-Check Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
