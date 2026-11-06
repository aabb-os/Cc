import os
import telebot
import threading
import time
import random
import string
import json
from curl_cffi import requests as curl_requests
from flask import Flask

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Real Auth Bot is running!"

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
psn_session = curl_requests.Session(impersonate="safari15_5")
access_token = None
token_lock = threading.Lock()

# القيمة الصحيحة والرسمية من مكتبة PSNAWP
CLIENT_BASIC_AUTH = "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A="

def get_access_token(chat_id=None):
    """تحويل NPSSO إلى Access Token باستخدام الـ Client ID الصحيح"""
    global access_token
    url = "https://ca.account.sony.com/api/authz/v3/oauth/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": CLIENT_BASIC_AUTH,
    }
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "subject_token": NPSSO_TOKEN,
        "subject_token_type": "urn:ietf:params:oauth:token-type:npsso",
        "scope": "psn:mobile.v2.core psn:clientapp",
    }
    try:
        res = psn_session.post(url, headers=headers, data=data, timeout=10)
        if res.status_code == 200:
            token = res.json().get("access_token")
            if token:
                with token_lock:
                    access_token = token
                print("✅ Access Token generated successfully.")
                if chat_id:
                    bot.send_message(chat_id, "✅ تم استخراج توكن سوني بنجاح! البوت جاهز للفحص.")
                return True
        
        error_msg = f"❌ فشل استخراج التوكن.\nكود: {res.status_code}\nالرد: {res.text[:100]}"
        print(error_msg)
        if chat_id:
            bot.send_message(chat_id, error_msg)
        return False
        
    except Exception as e:
        error_msg = f"❌ خطأ في الاتصال بسوني: {e}"
        print(error_msg)
        if chat_id:
            bot.send_message(chat_id, error_msg)
        return False

def refresh_token_loop():
    while True:
        get_access_token()
        time.sleep(1800)

threading.Thread(target=refresh_token_loop, daemon=True).start()

stop_psn = threading.Event()

stats = {
    "psn_checked": 0, "psn_found": 0,
    "code_200": 0, "code_400": 0, "code_404": 0, "code_429": 0, "code_401": 0
}

def is_owner(m): return m.from_user.id in OWNER_IDS

def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        if len(set(u)) < 5: 
            yield u

def check_psn_api(username):
    with token_lock:
        token = access_token
    
    if not token:
        return "NO_TOKEN"

    ts = int(time.time() * 1000)
    url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={username}&_={ts}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Origin": "https://www.playstation.com",
        "Referer": "https://www.playstation.com/",
    }
    
    try:
        res = psn_session.get(url, headers=headers, timeout=10)
        
        if res.status_code == 200: stats["code_200"] += 1
        elif res.status_code == 400: stats["code_400"] += 1
        elif res.status_code == 404: stats["code_404"] += 1
        elif res.status_code == 429: stats["code_429"] += 1
        elif res.status_code == 401: stats["code_401"] += 1
        
        if res.status_code == 200:
            data = res.json()
            if data.get("available") is True:
                return True
            return False
        elif res.status_code == 401:
            return "UNAUTHORIZED"
        elif res.status_code == 429:
            return "BLOCKED"
            
    except Exception as e:
        print(f"Err: {e}")
    return False

def worker_psn(chat_id, thread_id):
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            res = check_psn_api(u)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - خماسي مكرر )")
            elif res == "UNAUTHORIZED":
                print(f"[Thread {thread_id}] Token expired. Refreshing...")
                get_access_token()
                time.sleep(5)
                continue
            elif res == "BLOCKED":
                time.sleep(30)
                continue
                
            time.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not get_access_token(chat_id):
        return
        
    for i in range(10): 
        threading.Thread(target=worker_psn, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.1)

@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت سوني (Real Auth)\n\n/psn - تشغيل\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تسجيل الدخول وتشغيل 10 خيوط...")
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
           f"✅ **المتاح:** {stats['psn_found']}\n"
           f"🔍 **إجمالي الفحص:** {stats['psn_checked']}\n\n"
           f"📡 **أكواد الردود:**\n"
           f"كود 200 (نجاح): {stats['code_200']}\n"
           f"كود 404 (متاح): {stats['code_404']}\n"
           f"كود 401 (مرفوض): {stats['code_401']}\n"
           f"كود 429 (حظر): {stats['code_429']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Real Auth Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
