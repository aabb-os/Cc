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
    return "PSN V8 Ultimate is running!"

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
    me = psnawp.me() # تسجيل الدخول وجلب التوكن تلقائياً
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
# دالة التوليد (5 خانات)
# ==========================================
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# محرك الفحص القاطع (Double Check)
# ==========================================
def check_psn_decisive(username):
    if not psnawp:
        return "NO_AUTH"
        
    # الفحص الأول
    try:
        psnawp.user(online_id=username)
        return False # محجوز
    except PSNAWPForbiddenError:
        with stats_lock: stats["private_count"] += 1
        return False # حساب خاص = محجوز
    except PSNAWPNotFoundError:
        pass # ربما متاح، نكمل
    except Exception as e:
        with stats_lock: stats["error_count"] += 1
        return None

    time.sleep(2.0) # تأخير للتأكيد (عشان سوني ما تكذب)

    # الفحص الثاني (القاطع)
    try:
        psnawp.user(online_id=username)
        return False # محجوز (سوني كذبت في المرة الأولى)
    except PSNAWPForbiddenError:
        with stats_lock: stats["private_count"] += 1
        return False
    except PSNAWPNotFoundError:
        return True # متاح 100% (عدى الفحصين بنجاح)
    except Exception as e:
        with stats_lock: stats["error_count"] += 1
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
                utype = "خماسي مكرر" if len(set(u)) < 5 else "خماسي"
                with stats_lock:
                    stats["total_found"] += 1
                    
                msg = (f"استلم يالامير {u} 🎮🔥\n"
                       f"( سوني - {utype} - قاطع 100% )")
                bot.send_message(chat_id, msg)
                
            # تحديث الحالة كل 100 فحص
            if current_checked % 100 == 0:
                bot.send_message(chat_id, f"🔄 جاري الفحص... (فحص {current_checked})")
                
            # سرعة آمنة جداً (تأخير بين 1.5 و 2.5 ثانية)
            time.sleep(random.uniform(1.5, 2.5))
            
        except Exception as e:
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني.\nالسبب: `{init_error}`")
        return
        
    # خيط واحد فقط لضمان عدم الحظر (Zero Ban)
    threading.Thread(target=human_worker, args=(chat_id,), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ PSN V8 Ultimate Bot\n\n"
                     "/psn - تشغيل الصيد\n"
                     "/stop_all - إيقاف\n"
                     "/monitor - مراقبة النظام\n"
                     "/test - اختبار دقة الفحص")

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
    
    with stats_lock:
        msg = (f"🖥️ **لوحة المراقبة**\n\n"
               f"⚙️ **الحالة:** {sys_status}\n\n"
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
        
    bot.reply_to(m, "🧪 جاري فحص دقة المكتبة... (انتظر 3 ثواني)")
    
    # فحص يوزر محجوز معروف
    try:
        psnawp.user(online_id="tiktok")
        taken_res = "محجوز (صحيح) ✅"
    except PSNAWPForbiddenError:
        taken_res = "محجوز/خاص (صحيح) ✅"
    except PSNAWPNotFoundError:
        taken_res = "متاح (خطأ!) ❌"
    except Exception:
        taken_res = "خطأ في الشبكة ⚠️"
        
    time.sleep(2)
    
    # فحص يوزر عشوائي طويل
    rand_user = "a8s7d6f5g4h3j2k"
    try:
        psnawp.user(online_id=rand_user)
        rand_res = "محجوز (خطأ!) ❌"
    except PSNAWPForbiddenError:
        rand_res = "محجوز/خاص (خطأ!) ❌"
    except PSNAWPNotFoundError:
        rand_res = "متاح (صحيح) ✅"
    except Exception:
        rand_res = "خطأ في الشبكة ⚠️"
        
    msg = (f"📊 **نتيجة الاختبار:**\n\n"
           f"▪️ يوزر `tiktok`: {taken_res}\n"
           f"▪️ يوزر `{rand_user}`: {rand_res}\n\n"
           f"*(إذا طلعت الإجابتين ✅، يعني البوت دقيق 100%)*")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي (Anti-409 + Stability)
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("PSN V8 Ultimate Bot is running...")
    
    # تنظيف الويب هوك لمنع التعارض
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"Webhook cleanup error: {e}")
        
    # حلقة لا نهائية لضمان عدم توقف البوت عند أي خطأ
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"Polling error: {e}. Restarting in 5s...")
            time.sleep(5)
