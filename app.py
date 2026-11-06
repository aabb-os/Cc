import os
import telebot
import threading
import time
import random
import string
import collections
import json
from flask import Flask
from curl_cffi import requests as curl_requests

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Real-API Bot is running!"

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

# --- متغيرات المصادقة والتوكن ---
psn_session = curl_requests.Session(impersonate="safari15_5")
access_token = None
token_lock = threading.Lock()

# حالة التوكن للمراقبة
token_info = {
    "status": "⏳ لم يتم التوليد بعد",
    "last_time": "غير معروف"
}

# بيانات الـ Client الرسمية لسوني
CLIENT_BASIC_AUTH = "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A="

def refresh_token():
    """توليد توكن وصول جديد من NPSSO"""
    global access_token, token_info
    url = "https://ca.account.sony.com/api/authz/v3/oauth/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": CLIENT_BASIC_AUTH,
    }
    data = {
        "grant_type": "authorization_code",
        "code": NPSSO_TOKEN,
        "redirect_uri": "com.scee.psxandroid.scecompcall://redirect",
        "token_format": "jwt",
    }
    try:
        res = psn_session.post(url, headers=headers, data=data, timeout=10)
        if res.status_code == 200:
            token = res.json().get("access_token")
            with token_lock:
                access_token = token
                token_info["status"] = "✅ تم التوليد بنجاح"
                token_info["last_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{token_info['last_time']}] Access Token generated.")
            return True
        else:
            with token_lock:
                token_info["status"] = f"❌ فشل (كود: {res.status_code})"
            print(f"❌ فشل جلب التوكن: {res.status_code} - {res.text}")
    except Exception as e:
        with token_lock:
            token_info["status"] = f"❌ خطأ: {str(e)[:30]}"
        print(f"❌ خطأ في التوكن: {e}")
    return False

# تشغيل جلب التوكن في البداية
refresh_token()

stop_psn = threading.Event()
stats = {
    "total_found": 0, 
    "total_checked": 0,
    "codes": collections.Counter()
}
stats_lock = threading.Lock()

def is_owner(m): return m.from_user.id in OWNER_IDS

# ==========================================
# دالة التوليد
# ==========================================
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# محرك الفحص (الـ API الرسمي القاطع)
# ==========================================
def check_psn_decisive(username):
    global access_token
    with token_lock:
        token = access_token
    
    if not token:
        return "NO_AUTH"

    url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={username}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Origin": "https://www.playstation.com",
        "Referer": "https://www.playstation.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15"
    }
    
    try:
        res = psn_session.get(url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data.get("available") is True:
                with stats_lock: stats["codes"]["قاطع (متاح 100%)"] += 1
                return True
            return False # محجوز
        elif res.status_code in [401, 403]:
            with stats_lock: stats["codes"]["401/403 (توكن مرفوض)"] += 1
            refresh_token() # تجديد التوكن
            return "BLOCKED"
        elif res.status_code == 429:
            with stats_lock: stats["codes"]["429 (حظر)"] += 1
            return "BLOCKED"
            
    except Exception as e:
        with stats_lock: stats["codes"]["Error (قاطع)"] += 1
        pass
        
    return None

# ==========================================
# دالة التشغيل
# ==========================================
def human_worker(chat_id):
    global stats
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            
            with stats_lock:
                stats["total_checked"] += 1
                current_checked = stats["total_checked"]
            
            res = check_psn_decisive(u)
            
            if res is True:
                if len(set(u)) < 5:
                    utype = "خماسي مكرر"
                else:
                    utype = "خماسي"
                    
                with stats_lock:
                    stats["total_found"] += 1
                    
                msg = (f"استلم يالامير {u} 🎮🔥\n"
                       f"( سوني - {utype} - قاطع 100% )")
                       
                bot.send_message(chat_id, msg)
                
            elif res == "BLOCKED":
                time.sleep(10) # انتظار عند الحظر
                continue
                
            # تحديث الحالة كل 100 فحص
            if current_checked % 100 == 0:
                bot.send_message(chat_id, f"🔄 جاري الفحص... (فحص {current_checked})")
                
            time.sleep(random.uniform(1.5, 2.5))
            
        except Exception as e:
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not access_token:
        bot.send_message(chat_id, "❌ فشل الاتصال بسوني. تأكد من NPSSO_TOKEN.")
        return
        
    for i in range(3): 
        threading.Thread(target=human_worker, args=(chat_id,), daemon=True).start()
        time.sleep(0.2)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت صيد يوزرات PSN (القاطع الرسمي)\n\n"
                     "/psn - تشغيل الصيد\n"
                     "/stop_all - إيقاف\n"
                     "/status - الإحصائيات\n"
                     "/sony_status - ردود سوني\n"
                     "/api_status - حالة الـ API والتوكن")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل الصيد (الـ API الرسمي)...")
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
        msg = (f"📊 **إحصائيات سوني:**\n\n"
               f"✅ **المتاح (قاطع):** {stats['total_found']}\n"
               f"🔍 **إجمالي الفحص:** {stats['total_checked']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

@bot.message_handler(commands=['sony_status'])
def cmd_sony_status(m):
    if not is_owner(m): return
    with stats_lock:
        msg = "📡 **ردود سوني (منذ التشغيل):**\n\n"
        if not stats["codes"]:
            msg += "لا توجد ردود بعد. شغل `/psn` أولاً."
        else:
            for code, count in stats["codes"].most_common():
                msg += f"▪️ **{code}**: {count} مرة\n"
    bot.reply_to(m, msg, parse_mode='Markdown')

# 👇 أمر حالة الـ API والتوكن الجديد 👇
@bot.message_handler(commands=['api_status'])
def cmd_api_status(m):
    if not is_owner(m): return
    
    with token_lock:
        status = token_info["status"]
        last_time = token_info["last_time"]
        
    msg = (f"⚙️ **حالة الـ API والتوكن:**\n\n"
           f"🔑 **التوكن:** {status}\n"
           f"⏱️ **آخر تحديث:** {last_time}\n\n")
           
    # فحص تجريبي سريع قدام المستخدم
    msg += "🧪 **جاري فحص تجريبي (Live Test)...**\n"
    test_user = "testuser123xyz"
    res = check_psn_decisive(test_user)
    
    if res is True:
        msg += f"✅ سوني ردت بنجاح: اليوزر `{test_user}` متاح."
    elif res is False:
        msg += f"✅ سوني ردت بنجاح: اليوزر `{test_user}` محجوز."
    elif res == "BLOCKED":
        msg += "🚨 سوني رفضت التوكن (401/403) أو حظرت الـ IP (429)."
    elif res == "NO_AUTH":
        msg += "❌ ما فيه توكن شغال حالياً."
    else:
        msg += "⚠️ خطأ غير معروف في الاتصال."

    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Real-API Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
