import os
import telebot
import threading
import time
import random
import string
import collections
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony 5x Check Bot is running!"

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
stats = {
    "total_found": 0, 
    "total_checked": 0,
    "codes": collections.Counter() # هنا بنسجل كل رد يجي من سوني
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
# محرك الفحص (5 محاولات للتأكيد القاطع)
# ==========================================
def check_psn_5_times(username):
    if not psnawp:
        return "NO_AUTH"
        
    for attempt in range(5):
        try:
            psnawp.user(online_id=username)
            with stats_lock: stats["codes"]["200 (محجوز)"] += 1
            return False
            
        except PSNAWPForbiddenError:
            with stats_lock: stats["codes"]["403 (خاص/محجوز)"] += 1
            return False
            
        except PSNAWPNotFoundError:
            with stats_lock: stats["codes"]["404 (محاولة)"] += 1
            if attempt == 4:
                return True # متاح 100% (نجح في 5 محاولات)
            time.sleep(1.5) 
            
        except Exception as e:
            with stats_lock: stats["codes"]["Error (شبكة)"] += 1
            return None
            
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
            
            res = check_psn_5_times(u)
            
            if res is True:
                if len(set(u)) < 5:
                    utype = "خماسي مكرر"
                else:
                    utype = "خماسي"
                    
                with stats_lock:
                    stats["total_found"] += 1
                    
                msg = (f"استلم يالامير {u} 🎮🔥\n"
                       f"( سوني - {utype} - متاح 100% )")
                       
                bot.send_message(chat_id, msg)
                
            # تحديث الحالة كل 100 فحص
            if current_checked % 100 == 0:
                bot.send_message(chat_id, f"🔄 جاري الفحص... (فحص {current_checked})")
                
            time.sleep(random.uniform(1.0, 2.0))
            
        except Exception as e:
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not psnawp:
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
    bot.reply_to(m, "☢️ بوت صيد يوزرات PSN (الفحص الخماسي)\n\n"
                     "/psn - تشغيل الصيد\n"
                     "/stop_all - إيقاف\n"
                     "/status - الإحصائيات\n"
                     "/sony_status - ردود سوني")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل الصيد (5 محاولات لكل يوزر)... خله يشتغل.")
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
               f"✅ **المتاح (مؤكد 5 مرات):** {stats['total_found']}\n"
               f"🔍 **إجمالي الفحص:** {stats['total_checked']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# 👇 هذا هو الأمر اللي يوريك ردود سوني بالضبط 👇
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

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony 5x Check Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
