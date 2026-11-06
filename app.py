import os
import telebot
import threading
import time
import random
import string
import queue
import json
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPForbiddenError
from curl_cffi import requests as curl_requests

# --- إعدادات Flask (لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sony Producer-Consumer Bot is running!"

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

# --- تهيئة PSNAWP وجلب التوكن ---
psnawp = None
access_token = None
token_lock = threading.Lock()

def init_sony():
    global psnawp, access_token
    try:
        psnawp = PSNAWP(NPSSO_TOKEN)
        psnawp.me()
        print("✅ PSNAWP initialized.")
        
        # جلب التوكن بالقوة عشان المدقق
        url = "https://ca.account.sony.com/api/authz/v3/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A=",
        }
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "subject_token": NPSSO_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:npsso",
            "scope": "psn:mobile.v2.core psn:clientapp",
        }
        res = curl_requests.post(url, headers=headers, data=data, impersonate="safari15_5", timeout=10)
        if res.status_code == 200:
            with token_lock:
                access_token = res.json().get("access_token")
            print("✅ Token extracted manually.")
            return True
    except Exception as e:
        print(f"❌ Init Error: {e}")
    return False

init_sony()

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
            with token_lock:
                token = access_token
                
            if not token:
                # إذا اختفى التوكن، نجدد
                init_sony()
                time.sleep(2)
                continue
                
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X)"
            }
            url = f"https://accounts.api.playstation.com/api/v1/accounts/checkOnlineId?onlineId={u}"
            res = curl_requests.get(url, headers=headers, impersonate="safari15_5", timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                if data.get("available") is True:
                    utype = "خماسي مكرر" if len(set(u)) < 5 else "خماسي"
                    with stats_lock:
                        stats["verifier_found"] += 1
                    msg = f"استلم يالامير {u} 🎮🔥\n( سوني - {utype} - قاطع 100% )"
                    bot.send_message(chat_id, msg)
            elif res.status_code in [401, 403]:
                init_sony() # توكن منتهي
                time.sleep(5)
                
            time.sleep(1)
            suspect_queue.task_done()
        except Exception:
            time.sleep(1)

def start_psn_snipers(chat_id):
    if not psnawp or not access_token:
        bot.send_message(chat_id, "❌ فشل الاتصال بسوني. التوكن غير متوفر. تأكد من NPSSO_TOKEN في المتغيرات.")
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
    bot.reply_to(m, "☢️ بوت صيد يوزرات PSN\n\n/psn - تشغيل الصيد\n/stop_all - إيقاف\n/monitor - مراقبة النظام")

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
        
    bot.reply_to(m, "🚀 جاري تشغيل الصياد (10) + المدقق (2)...")
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
    
    with token_lock:
        has_token = access_token is not None
    token_status = "✅ شغال" if has_token else "❌ غير متوفر"
    
    with stats_lock:
        h_checked = stats["hunter_checked"]
        v_found = stats["verifier_found"]
        q_dropped = stats["queue_dropped"]
        q_size = suspect_queue.qsize()
    
    msg = (f"🖥️ **لوحة مراقبة النظام**\n\n"
           f"⚙️ **حالة البوت:** {sys_status}\n"
           f"🔑 **التوكن:** {token_status}\n\n"
           f"🏃‍♂️ **الصيادين (10 خيوط):**\n"
           f"▪️ إجمالي الفحص: {h_checked} يوزر\n\n"
           f"📥 **طابور التدقيق:**\n"
           f"▪️ في الانتظار: {q_size} يوزر\n"
           f"▪️ تم تخطيه (ممتلئ): {q_dropped} يوزر\n\n"
           f"🕵️‍♂️ **المدققين (خيطين):**\n"
           f"▪️ إجمالي الصيد: {v_found} يوزر")
    bot.reply_to(m, msg, parse_mode='Markdown')

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Sony Producer-Consumer Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
