import os
import telebot
import threading
import time
import random
import string
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError
from psnawp_api.models.search import SearchDomain

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "PSNAWP Sony Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")
NPSSO_TOKEN = os.environ.get("NPSSO_TOKEN")

if not TOKEN or not OWNER_IDS_STR or not NPSSO_TOKEN:
    print("❌ خطأ: تأكد من إضافة BOT_TOKEN و OWNER_ID و NPSSO_TOKEN.")
    exit(1)

OWNER_IDS = [int(i.strip()) for i in OWNER_IDS_STR.split(",")]
bot = telebot.TeleBot(TOKEN)

# --- تهيئة PSNAWP ---
psnawp = None
init_error = None
try:
    psnawp = PSNAWP(NPSSO_TOKEN)
    # التحقق من صحة التوكن عند البدء
    psnawp.me()
    print("✅ PSNAWP initialized successfully.")
except Exception as e:
    init_error = str(e)
    print(f"❌ PSNAWP initialization error: {init_error}")

stop_psn = threading.Event()
stats = {"psn_checked": 0, "psn_found": 0}

def is_owner(m): return m.from_user.id in OWNER_IDS

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
# محرك فحص سوني (باستخدام PSNAWP)
# ==========================================
def check_psn_psnawp(username):
    if not psnawp:
        return "NO_AUTH"
    try:
        # محاولة جلب المستخدم. إذا رجع كائن، يعني اليوزر موجود (محجوز)
        psnawp.user(online_id=username)
        return False
    except PSNAWPNotFoundError:
        # إذا رجع خطأ "غير موجود"، قد يكون متاحاً أو محجوزاً (خاص)
        pass
    except Exception as e:
        if "429" in str(e) or "RateLimit" in str(e):
            return "BLOCKED"
        return None

    # التحقق الإضافي عبر البحث الداخلي (للتأكد من أنه غير موجود فعلاً)
    try:
        results = psnawp.search(search_query=username, search_domain=SearchDomain.SOCIAL_ALL_ACCOUNTS)
        for res in results:
            if res.get('onlineId') == username:
                return False # موجود في البحث (محجوز)
        return True # غير موجود في البحث (متاح)
    except Exception:
        return None

# ==========================================
# دوال التشغيل
# ==========================================
def worker_psn(chat_id, thread_id):
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            res = check_psn_psnawp(u)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - خماسي مكرر )")
            elif res == "BLOCKED":
                print(f"[Thread {thread_id}] Rate Limited. Sleeping...")
                time.sleep(30)
                continue
            elif res == "NO_AUTH":
                time.sleep(5)
                continue
                
            time.sleep(random.uniform(2.0, 4.0))
            
        except Exception as e:
            time.sleep(2)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني:\n`{init_error}`\n\nتأكد من أن NPSSO_TOKEN صحيح وغير منتهي الصلاحية.")
        return
        
    for i in range(5): 
        threading.Thread(target=worker_psn, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.2)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    status = "✅ متصل" if psnawp else "❌ غير متصل"
    bot.reply_to(m, f"☢️ بوت سوني (PSNAWP)\nالحالة: {status}\n\n/psn - تشغيل\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل 5 خيوط...")
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
           f"🔍 **إجمالي الفحص:** {stats['psn_checked']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("PSNAWP Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
