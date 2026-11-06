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
    return "Sony God-Mode Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية (تقرأ من المتغيرات فقط) ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")

if not TOKEN or not OWNER_IDS_STR:
    print("❌ خطأ: تأكد من إضافة BOT_TOKEN و OWNER_ID في متغيرات البيئة (Environment Variables).")
    exit(1)

# تحويل النص إلى قائمة أرقام (عشان لو حطيت أكثر من أيدي بفاصلة)
OWNER_IDS = [int(i.strip()) for i in OWNER_IDS_STR.split(",")]

bot = telebot.TeleBot(TOKEN)

# جلسة سوني المموهة (تستخدم بصمة سفاري)
psn_session = curl_requests.Session(impersonate="safari15_5")

stop_psn = threading.Event()

stats = {
    "psn_checked": 0, "psn_found": 0,
    "code_200": 0, "code_400": 0, "code_404": 0, "code_429": 0
}

def is_owner(m): 
    return m.from_user.id in OWNER_IDS

# ==========================================
# دوال التوليد (5 خانات، يبدأ بحرف، فيه حرف مكرر)
# ==========================================
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        if len(set(u)) < 5: 
            yield u

# ==========================================
# محرك فحص سوني (API الرسمي)
# ==========================================
def check_psn_api(username):
    ts = int(time.time() * 1000)
    url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={username}&_={ts}"
    
    # ترويسات كاملة عشان نخدع سوني إننا متصفح حقيقي
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.playstation.com",
        "Referer": "https://www.playstation.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site"
    }
    
    try:
        res = psn_session.get(url, headers=headers, timeout=10)
        
        # تحديث الإحصائيات بناءً على الرد
        if res.status_code == 200: stats["code_200"] += 1
        elif res.status_code == 400: stats["code_400"] += 1
        elif res.status_code == 404: stats["code_404"] += 1
        elif res.status_code == 429: stats["code_429"] += 1
        
        if res.status_code == 200:
            data = res.json()
            if data.get("available") is True:
                return True # متاح 100%
            return False # محجوز
        elif res.status_code in [429, 403]:
            return "BLOCKED"
            
    except Exception as e:
        print(f"Err: {e}")
        return None
        
    return False

# ==========================================
# دوال التشغيل (سرعة صاروخية)
# ==========================================
def worker_psn(chat_id, thread_id):
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            res = check_psn_api(u)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - خماسي مكرر )")
            elif res == "BLOCKED":
                # إذا اكتشفتنا سوني، نوقف الخيط 30 ثانية عشان يبرد الـ IP
                print(f"[Thread {thread_id}] Rate Limited (429). Sleeping...")
                time.sleep(30)
                continue
                
            # تأخير بسيط جداً عشان ما نضرب السيرفر بقوة (0.5 إلى 1.5 ثانية)
            time.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            time.sleep(2)

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
    bot.reply_to(m, "☢️ بوت سوني (God Mode)\n\n"
                     "/psn - تشغيل الصيد\n"
                     "/stop_all - إيقاف\n"
                     "/status - الإحصائيات\n"
                     "/sony_debug - عرض رد سوني الخام")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    start_psn_snipers(m.chat.id)
    bot.reply_to(m, "🚀 تم تشغيل صيد سوني (10 خيوط) بأقصى سرعة!")

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
           f"كود 200: {stats['code_200']}\n"
           f"كود 400: {stats['code_400']}\n"
           f"كود 404: {stats['code_404']}\n"
           f"كود 429 (حظر): {stats['code_429']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

@bot.message_handler(commands=['sony_debug'])
def cmd_sony_debug(m):
    if not is_owner(m): return
    test_user = next(gen_psn())
    bot.reply_to(m, f"جاري الفحص التشخيصي على يوزر: `{test_user}`...")
    
    ts = int(time.time() * 1000)
    url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={test_user}&_={ts}"
    headers = {"Accept": "application/json", "Origin": "https://www.playstation.com", "Referer": "https://www.playstation.com/"}
    
    try:
        res = psn_session.get(url, headers=headers, timeout=10)
        bot.reply_to(m, f"**الرد من سوني:**\nHTTP Status: `{res.status_code}`\nResponse: `{res.text[:200]}`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(m, f"خطأ في الاتصال: `{e}`")

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
