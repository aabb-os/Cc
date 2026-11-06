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
    return "PSN V7 Ultimate Bot is running!"

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
    me = psnawp.me() # هذا السطر هو اللي يجبر المكتبة تجيب التوكن
    print(f"✅ PSNAWP Logged in as: {me.online_id}")
except Exception as e:
    init_error = str(e)
    print(f"❌ PSNAWP initialization error: {init_error}")

stop_psn = threading.Event()
stats = {
    "total_checked": 0, 
    "total_found": 0,
    "private_count": 0,
    "error_count": 0
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
# محرك الفحص القاطع (PSNAWP + API الرسمي)
# ==========================================
def check_psn_ultimate(username):
    if not psnawp:
        return "NO_AUTH"
        
    # 1. الفحص الأولي عبر PSNAWP (لتجاهل المحجوزين بسرعة)
    try:
        psnawp.user(online_id=username)
        return False # محجوز
    except PSNAWPForbiddenError:
        with stats_lock: stats["private_count"] += 1
        return False # حساب خاص = محجوز
    except PSNAWPNotFoundError:
        pass # ربما متاح، نكمل للفحص القاطع
    except Exception as e:
        with stats_lock: stats["error_count"] += 1
        return None

    time.sleep(1.5) # تأخير بسيط للتأكيد

    # 2. الفحص القاطع (الـ API الرسمي لتغيير الاسم)
    try:
        token = getattr(psnawp.authenticator, '_access_token', None)
        if not token:
            return None
            
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15"
        }
        url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={username}"
        
        res = curl_requests.get(url, headers=headers, impersonate="safari15_5", timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data.get("available") is True:
                return True # متاح 100%
            return False # محجوز
        elif res.status_code in [401, 403, 429]:
            return "BLOCKED"
            
    except Exception as e:
        with stats_lock: stats["error_count"] += 1
        pass
        
    return None

# ==========================================
# دالة التشغيل (خيط واحد فقط لضمان عدم الحظر)
# ==========================================
def human_worker(chat_id):
    global stats
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            
            with stats_lock:
                stats["total_checked"] += 1
                current_checked = stats["total_checked"]
            
            res = check_psn_ultimate(u)
            
            if res is True:
                utype = "خماسي مكرر" if len(set(u)) < 5 else "خماسي"
                with stats_lock:
                    stats["total_found"] += 1
                    
                msg = (f"استلم يالامير {u} 🎮🔥\n"
                       f"( سوني - {utype} - قاطع 100% )")
                bot.send_message(chat_id, msg)
                
            elif res == "BLOCKED":
                time.sleep(15) # انتظار عند الحظر
                continue
                
            # تحديث الحالة كل 100 فحص
            if current_checked % 100 == 0:
                bot.send_message(chat_id, f"🔄 جاري الفحص... (فحص {current_checked})")
                
            # سرعة آمنة 100% (ثانيتين بين كل فحص)
            time.sleep(random.uniform(2.0, 3.0))
            
        except Exception as e:
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني.\nالسبب: `{init_error}`")
        return
        
    # خيط واحد فقط
    threading.Thread(target=human_worker, args=(chat_id,), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ PSN V7 Ultimate Bot\n\n/psn - تشغيل الصيد\n/stop_all - إيقاف\n/monitor - مراقبة النظام\n/test - اختبار الاتصال")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    with stats_lock:
        stats["total_checked"] = 0
        stats["total_found"] = 0
        stats["private_count"] = 0
        stats["error_count"] = 0
        
    bot.reply_to(m, "🚀 جاري تشغيل الصيد (خيط واحد - دقة 100%)...")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_psn.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['monitor'])
def cmd_monitor(m):
    if not is_owner(m): return
    is_running = not stop_psn.is_set()
    sys_status = "🟢 يعمل" if is_running else "🔴 متوقف"
    
    token = getattr(psnawp.authenticator, '_access_token', None) if psnawp else None
    token_status = "✅ شغال" if token else "❌ غير متوفر"
    
    with stats_lock:
        msg = (f"🖥️ **لوحة المراقبة**\n\n"
               f"⚙️ **الحالة:** {sys_status}\n"
               f"🔑 **التوكن:** {token_status}\n\n"
               f"🔍 **إجمالي الفحص:** {stats['total_checked']}\n"
               f"✅ **المتاح:** {stats['total_found']}\n"
               f"🔒 **حسابات خاصة:** {stats['private_count']}\n"
               f"⚠️ **أخطاء:** {stats['error_count']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
def cmd_test(m):
    if not is_owner(m): return
    if not psnawp:
        bot.reply_to(m, f"❌ المكتبة فشلت في الاتصال:\n`{init_error}`")
        return
    
    token = getattr(psnawp.authenticator, '_access_token', None)
    if token:
        bot.reply_to(m, "✅ المكتبة متصلة، والتوكن متوفر. جاهز للصيد.")
    else:
        bot.reply_to(m, "⚠️ المكتبة متصلة، لكن التوكن غير متوفر.")

# ==========================================
# التشغيل النهائي (حل مشكلة 409)
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("PSN V7 Ultimate Bot is running...")
    
    # حل مشكلة 409: حذف الويب هوك وتنظيف التحديثات المعلقة
    try:
        bot.delete_webhook(drop_pending_updates=True)
        print("Webhook deleted.")
    except Exception as e:
        print(f"Webhook delete error: {e}")
        
    # استخدام polling بدل infinity_polling لضمان الاستقرار
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)
