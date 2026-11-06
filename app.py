import os
import telebot
import threading
import time
import random
import string
from datetime import datetime
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Sniper Bot is running!"

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
try:
    psnawp = PSNAWP(NPSSO_TOKEN)
    psnawp.me()
    print("✅ PSNAWP initialized successfully.")
except Exception as e:
    print(f"❌ PSNAWP initialization error: {e}")

stop_psn = threading.Event()

# العداد لعدد اليوزرات اللي تم صيدها (مثل الصورة)
stats = {"total_found": 0}
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
# محرك الفحص
# ==========================================
def check_psn_accurate(username):
    if not psnawp:
        return "NO_AUTH"
    try:
        psnawp.user(online_id=username)
        return False # محجوز
    except PSNAWPForbiddenError:
        return False # حساب خاص = محجوز
    except PSNAWPNotFoundError:
        return True # متاح 100%
    except Exception as e:
        if "429" in str(e) or "RateLimit" in str(e):
            return "BLOCKED"
        return None

# ==========================================
# دالة التشغيل
# ==========================================
def human_worker(chat_id):
    global stats
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            
            res = check_psn_accurate(u)
            
            if res is True:
                with stats_lock:
                    stats["total_found"] += 1
                    current_total = stats["total_found"]
                    
                # جلب الوقت الحالي بنفس تنسيق الصورة
                now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                
                # نفس الرسالة اللي في صورتك بالضبط
                msg = (f"🎯 يوزر PSN متاح!\n"
                       f"👤 {u}\n"
                       f"⏰ {now}\n"
                       f"📊 إجمالي: {current_total}")
                       
                bot.send_message(chat_id, msg)
                
            elif res == "BLOCKED":
                time.sleep(5) 
                continue
                
            # سرعة عالية جداً
            time.sleep(random.uniform(0.3, 1.0))
            
        except Exception as e:
            time.sleep(1)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, "❌ فشل الاتصال بسوني. تأكد من NPSSO_TOKEN.")
        return
        
    # 5 خيوط للسرعة القصوى
    for i in range(5): 
        threading.Thread(target=human_worker, args=(chat_id,), daemon=True).start()
        time.sleep(0.2)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت صيد يوزرات PSN (مطابق للصورة)\n\n/psn - تشغيل الصيد\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل الصيد... خله يشتغل ولا توقفه.")
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
               f"✅ **إجمالي اليوزرات المصادة:** {stats['total_found']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Sniper Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
