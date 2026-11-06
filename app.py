import os
import telebot
import threading
import time
import random
import string
from curl_cffi import requests as curl_requests
from flask import Flask

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Human-Mode Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")

if not TOKEN or not OWNER_IDS_STR:
    print("❌ خطأ: تأكد من BOT_TOKEN و OWNER_ID.")
    exit(1)

OWNER_IDS = [int(i.strip()) for i in OWNER_IDS_STR.split(",")]
bot = telebot.TeleBot(TOKEN)

# --- البروكسيات العشرة (من Webshare) ---
PROXIES = [
    "http://jbtndvvo:o2mmxk3x9sm7@45.38.107.97:6014",
    "http://jbtndvvo:o2mmxk3x9sm7@64.137.96.74:6641",
    "http://jbtndvvo:o2mmxk3x9sm7@198.23.243.226:6361",
    "http://jbtndvvo:o2mmxk3x9sm7@38.154.185.97:6370",
    "http://jbtndvvo:o2mmxk3x9sm7@84.247.60.125:6095",
    "http://jbtndvvo:o2mmxk3x9sm7@191.96.254.138:6185",
    "http://jbtndvvo:o2mmxk3x9sm7@198.46.161.42:5092",
    "http://jbtndvvo:o2mmxk3x9sm7@64.137.10.153:5803",
    "http://jbtndvvo:o2mmxk3x9sm7@104.164.49.38:7693",
    "http://jbtndvvo:o2mmxk3x9sm7@23.26.71.145:5628"
]

# تتبع حالة البروكسيات
proxy_health = {i: "⏳ لم يفحص بعد" for i in range(len(PROXIES))}

stop_psn = threading.Event()
stats = {"psn_checked": 0, "psn_found": 0, "current_proxy_idx": 0}

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
# محرك الفحص (عبر PSNProfiles + التصرف البشري)
# ==========================================
def check_psn_human(username, proxy_url, proxy_idx):
    global proxy_health
    proxies = {"http": proxy_url, "https": proxy_url}
    
    try:
        url = f"https://psnprofiles.com/{username}"
        # انتحال بصمة كروم 124 عشان نتخطى الحماية
        res = curl_requests.get(url, proxies=proxies, impersonate="chrome124", timeout=15)
        
        if res.status_code == 404:
            proxy_health[proxy_idx] = "✅ شغال (رد 404)"
            return True # متاح 100%
        elif res.status_code == 200:
            proxy_health[proxy_idx] = "✅ شغال (رد 200)"
            return False # محجوز
        elif res.status_code in [403, 429, 503]:
            proxy_health[proxy_idx] = "🚫 محظور من الموقع"
            return "BLOCKED"
        else:
            proxy_health[proxy_idx] = f"⚠️ كود {res.status_code}"
            return False
            
    except Exception as e:
        proxy_health[proxy_idx] = "❌ خطأ اتصال (ميت)"
        return "ERROR"

# ==========================================
# دالة التشغيل (خيط واحد فقط للتصرف البشري)
# ==========================================
def human_worker(chat_id):
    global stats
    proxy_index = 0
    total_proxies = len(PROXIES)

    while not stop_psn.is_set():
        try:
            # اختيار البروكسي بالترتيب (Round-Robin)
            current_proxy = PROXIES[proxy_index]
            stats["current_proxy_idx"] = proxy_index + 1
            
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            # الفحص
            res = check_psn_human(u, current_proxy, proxy_index)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - 5 خانات متاح 100% )")
                
            # الانتقال للبروكسي التالي
            proxy_index = (proxy_index + 1) % total_proxies
            
            # الفارق الزمني البشري العشوائي (من 6 إلى 12 ثانية)
            delay = random.uniform(6.0, 12.0)
            time.sleep(delay)
            
        except Exception as e:
            time.sleep(5)

def start_psn_snipers(chat_id):
    # خيط واحد فقط لضمان عدم الحظر
    threading.Thread(target=human_worker, args=(chat_id,), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت سوني (الوضع البشري - Zero Ban)\n\n"
                     "/psn - تشغيل الصيد\n"
                     "/stop_all - إيقاف\n"
                     "/status - الإحصائيات\n"
                     "/proxy_status - حالة البروكسيات")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 جاري تشغيل الوضع البشري (10 بروكسيات بالتناوب + تأخير عشوائي)...")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_psn.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات (الوضع البشري):**\n\n"
           f"✅ **المتاح:** {stats['psn_found']}\n"
           f"🔍 **إجمالي الفحص:** {stats['psn_checked']}\n\n"
           f"🌐 **البروكسي الحالي:** {stats['current_proxy_idx']} من 10\n"
           f"⏱️ **الحالة:** يفحص ببطء وتأخير عشوائي (آمن 100%)")
    bot.reply_to(m, msg, parse_mode='Markdown')

@bot.message_handler(commands=['proxy_status'])
def cmd_proxy_status(m):
    if not is_owner(m): return
    msg = "🌐 **حالة البروكسيات العشرة:**\n\n"
    
    for i in range(len(PROXIES)):
        # نستخرج الـ IP والـ Port بس عشان ما نطول الرسالة
        ip_port = PROXIES[i].split('@')[-1]
        status = proxy_health[i]
        msg += f"▪️ **بروكسي {i+1}** (`{ip_port}`):\n   {status}\n\n"
        
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Human-Mode Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
