import os
import telebot
import threading
import time
import random
import string
import queue
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError
from curl_cffi import requests as curl_requests

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Bot is running!"

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
stats = {"hunter_checked": 0, "verifier_found": 0, "queue_dropped": 0}
stats_lock = threading.Lock()
suspect_queue = queue.Queue(maxsize=500)

def is_owner(m): return m.from_user.id in OWNER_IDS

def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        yield u

# ==========================================
# 1. الصياد (سريع)
# ==========================================
def hunter_worker():
    global stats
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            with stats_lock:
                stats["hunter_checked"] += 1
                
            if not psnawp:
                time.sleep(1)
                continue

            try:
                psnawp.user(online_id=u)
            except PSNAWPForbiddenError:
                pass
            except PSNAWPNotFoundError:
                try:
                    suspect_queue.put(u, timeout=1)
                except queue.Full:
                    with stats_lock:
                        stats["queue_dropped"] += 1
            except Exception:
                pass
                
            time.sleep(0.1)
        except Exception:
            time.sleep(1)

# ==========================================
# 2. المدقق (دقيق)
# ==========================================
def verifier_worker(chat_id):
    global stats
    while not stop_psn.is_set():
        try:
            u = suspect_queue.get(timeout=2)
        except queue.Empty:
            continue

        try:
            # نسحب التوكن من داخل المكتبة مباشرة
            token = getattr(psnawp.authenticator, '_access_token', None)
            
            is_available = False
            
            if token:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X)"
                }
                url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={u}"
                res = curl_requests.get(url, headers=headers, impersonate="safari15_5", timeout=10)
                
                if res.status_code == 200 and res.json().get("available") is True:
                    is_available = True
            else:
                # إذا ما فيه توكن، نستخدم الفحص المزدوج العادي كخطة بديلة
                time.sleep(1)
                try:
                    psnawp.user(online_id=u)
                except PSNAWPNotFoundError:
                    is_available = True
                except Exception:
                    pass

            if is_available:
                utype = "خماسي مكرر" if len(set(u)) < 5 else "خماسي"
                with stats_lock:
                    stats["verifier_found"] += 1
                msg = f"استلم يالامير {u} 🎮🔥\n( سوني - {utype} - متاح 100% )"
                bot.send_message(chat_id, msg)
                
            time.sleep(1)
            suspect_queue.task_done()
        except Exception:
            time.sleep(1)

def start_psn_snipers(chat_id):
    if not psnawp:
        bot.send_message(chat_id, f"❌ فشل الاتصال بسوني.\nالسبب: `{init_error}`")
        return
        
    for i in range(10): 
        threading.Thread(target=hunter_worker, daemon=True).start()
    for i in range(2):
        threading.Thread(target=verifier_worker, args=(chat_id,), daemon=True).start()

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت صيد يوزرات PSN\n\n/psn - تشغيل\n/stop_all - إيقاف\n/monitor - مراقبة\n/test - اختبار الاتصال")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    with stats_lock:
        stats["hunter_checked"] = 0
        stats["verifier_found"] = 0
        stats["queue_dropped"] = 0
    
    while not suspect_queue.empty():
        try: suspect_queue.get_nowait()
        except: break
        
    bot.reply_to(m, "🚀 جاري التشغيل...")
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
        h_checked = stats["hunter_checked"]
        v_found = stats["verifier_found"]
        q_dropped = stats["queue_dropped"]
        q_size = suspect_queue.qsize()
    
    msg = (f"🖥️ **لوحة المراقبة**\n\n"
           f"⚙️ **البوت:** {sys_status}\n"
           f"🔑 **التوكن:** {token_status}\n\n"
           f"🏃‍♂️ **الصيادين:** {h_checked} فحص\n"
           f"📥 **الطابور:** {q_size} ينتظر | {q_dropped} تم تخطيه\n"
           f"🕵️‍♂️ **المدققين:** {v_found} صيد")
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
        bot.reply_to(m, "⚠️ المكتبة متصلة، لكن التوكن غير متوفر. سيعتمد البوت على الفحص المزدوج.")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
