import os
import telebot
import threading
import time
import random
import string
import json
from flask import Flask
from curl_cffi import requests as curl_requests
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "PSN Accurate Bot is running!"

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

# --- متغيرات المصادقة ---
access_token = None
token_lock = threading.Lock()

def get_access_token():
    global access_token
    url = "https://ca.account.sony.com/api/authz/v3/oauth/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A=",
    }
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "subject_token": NPSSO_TOKEN,
        "subject_token_type": "urn:ietf:params:oauth:token-type:npsso",
        "scope": "psn:mobile.v2.core psn:clientapp",
    }
    try:
        res = curl_requests.post(url, headers=headers, data=data, impersonate="safari15_5", timeout=10)
        if res.status_code == 200:
            with token_lock:
                access_token = res.json().get("access_token")
            print("✅ Access Token generated.")
            return True
        else:
            print(f"❌ Token Error: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Token Exception: {e}")
    return False

# جلب التوكن أول مرة
get_access_token()

stop_psn = threading.Event()
stats = {"checked": 0, "found": 0, "errors": 0}
stats_lock = threading.Lock()

def is_owner(m): return m.from_user.id in OWNER_IDS

def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

def check_psn_accurate(username):
    global access_token
    with token_lock:
        token = access_token
    
    if not token:
        get_access_token()
        with token_lock:
            token = access_token
        if not token: return "NO_AUTH"

    url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={username}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Origin": "https://www.playstation.com",
        "Referer": "https://www.playstation.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X)"
    }
    
    try:
        res = curl_requests.get(url, headers=headers, impersonate="safari15_5", timeout=10)
        
        if res.status_code == 200:
            if res.json().get("available") is True:
                return True
            return False
        elif res.status_code in [401, 403]:
            # التوكن انتهى أو مرفوض
            get_access_token()
            return "TOKEN_EXPIRED"
        elif res.status_code == 429:
            return "RATE_LIMIT"
    except Exception:
        return "ERROR"
    return False

def worker(chat_id):
    global stats
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            with stats_lock: stats["checked"] += 1
            
            res = check_psn_accurate(u)
            
            if res is True:
                utype = "خماسي مكرر" if len(set(u)) < 5 else "خماسي"
                with stats_lock: stats["found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🔥\n( سوني - {utype} - قاطع 100% )")
            elif res == "RATE_LIMIT":
                time.sleep(15) # انتظار عند الحظر
            elif res == "TOKEN_EXPIRED":
                time.sleep(5)
            elif res == "ERROR":
                with stats_lock: stats["errors"] += 1
                
            # السرعة الآمنة جداً لمنع الحظر (4 ثواني بين كل فحص)
            time.sleep(4)
            
        except Exception:
            time.sleep(2)

def start_sniper(chat_id):
    if not access_token:
        bot.send_message(chat_id, "❌ فشل جلب التوكن. تأكد من NPSSO في المتغيرات.")
        return
    threading.Thread(target=worker, args=(chat_id,), daemon=True).start()

@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت سوني (القاطع الرسمي)\n\n/psn - تشغيل الصيد\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    with stats_lock:
        stats["checked"] = 0
        stats["found"] = 0
        stats["errors"] = 0
    bot.reply_to(m, "🚀 جاري التشغيل (سرعة آمنة جداً)...")
    start_sniper(m.chat.id)

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
    print("Sony Accurate Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception as e:
            time.sleep(5)
