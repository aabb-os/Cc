import os
import telebot
import threading
import time
import random
import string
import requests
import json
from curl_cffi import requests as curl_requests
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError
from psnawp_api.models.search import SearchDomain

# --- إعدادات Flask (الوهمي) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية للبوت ---
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
NPSSO_TOKEN = os.environ.get("NPSSO_TOKEN", "zoxZdmM5dYcRZVOolR9JnxeUQ6u2jactLilxqhGUrP9DtkAhT39JRBdsPDgeDRlI")

if not TOKEN or OWNER_ID == 0:
    print("❌ خطأ: تأكد من إضافة BOT_TOKEN و OWNER_ID في متغيرات البيئة.")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# تهيئة سوني
try:
    psnawp = PSNAWP(NPSSO_TOKEN)
    print(f"PSN Connected: {psnawp.me().online_id}")
except Exception as e:
    print(f"PSN Token Error: {e}")
    psnawp = None

discord_session = curl_requests.Session(impersonate="chrome124")
stop_tiktok = threading.Event()
stop_psn = threading.Event()
stop_discord = threading.Event()

stats = {
    "tiktok_checked": 0, "tiktok_found": 0,
    "psn_checked": 0, "psn_found": 0,
    "discord_checked": 0, "discord_found": 0
}

def is_owner(m): return m.from_user.id == OWNER_ID

# ==========================================
# دوال التوليد
# ==========================================
def gen_tiktok():
    chars = string.ascii_lowercase + string.digits
    seps = ['.', '_']
    while True:
        p = [random.choice(chars) for _ in range(5)]
        pos = random.sample([1, 2, 3], 2)
        for idx in pos: p[idx] = random.choice(seps)
        u = "".join(p)
        if u[-1] != '.': yield u, 'شبه ثلاثي🤩'

def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        if len(set(u)) < 5: yield u

def gen_discord():
    chars = string.ascii_lowercase + string.digits
    seps = ['.', '_']
    while True:
        p = [random.choice(chars) for _ in range(5)]
        pos = random.sample([1, 2, 3], 2)
        for idx in pos: p[idx] = random.choice(seps)
        u = "".join(p)
        if u[-1] not in seps and '..' not in u: yield u, 'شبه ثلاثي 🤩'

# ==========================================
# دوال الفحص
# ==========================================
def check_tiktok(username):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(f"https://www.tiktok.com/@{username}", headers=headers, timeout=10)
        if r.status_code == 404: return True
        if r.status_code == 200:
            if f'"uniqueId":"{username}"' in r.text: return False
            if '10221' in r.text: return True
        if r.status_code in [403, 429, 503]: return "BLOCKED"
    except Exception: pass
    return None

def check_psn_smart(username):
    """الفحص الذكي لسوني باستخدام توكن NPSSO ومحرك البحث"""
    if not psnawp: return None
    
    try:
        # 1. محاولة جلب البروفايل (إذا نجح يعني محجوز)
        psnawp.user(online_id=username)
        return False 
    except PSNAWPNotFoundError:
        pass # قد يكون متاح أو خاص
    except Exception as e:
        if "429" in str(e): return "BLOCKED"
        return None

    time.sleep(1)

    try:
        # 2. البحث في سوني (إذا لقيناه في البحث، يعني موجود بس خاص)
        results = psnawp.search(search_query=username, search_domain=SearchDomain.SOCIAL_ALL_ACCOUNTS)
        for res in results:
            if res.get('onlineId') == username:
                return False # محجوز (خاص)
        return True # متاح 100%
    except Exception:
        return None

def check_discord_direct(username):
    url = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
    headers = {"Accept": "*/*", "Origin": "https://discord.com", "Referer": "https://discord.com/register", "Content-Type": "application/json"}
    
    # اتصال مباشر (بدون بروكسي) عشان نتجنب الإجابات الوهمية
    for _ in range(2): 
        try:
            r = discord_session.post(url, json={"username": username}, headers=headers, timeout=10)
            if r.status_code == 200: 
                if r.json().get("taken", True) is True: return False
            elif r.status_code == 429: 
                return "BLOCKED"
        except Exception: 
            pass
        time.sleep(1)
    return True

# ==========================================
# دوال التشغيل
# ==========================================
def worker_tiktok(chat_id, thread_id):
    try:
        for u, label in gen_tiktok():
            if stop_tiktok.is_set(): break
            stats["tiktok_checked"] += 1
            res = check_tiktok(u)
            if res is True:
                stats["tiktok_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🥷🏼✨\n( تيك توك - {label} )")
            elif res == "BLOCKED": time.sleep(120)
            time.sleep(random.uniform(1.5, 3.0)) 
    except Exception as e: print(f"Err TikTok: {e}")

def worker_psn(chat_id, thread_id):
    try:
        for u in gen_psn():
            if stop_psn.is_set(): break
            res = check_psn_smart(u)
            stats["psn_checked"] += 1
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - خماسي مكرر )")
            time.sleep(random.uniform(8.0, 12.0)) # بطيء عشان ما ينحظر IP Render
    except Exception as e: print(f"Err PSN: {e}")

def worker_discord(chat_id, thread_id):
    try:
        for u, label in gen_discord():
            if stop_discord.is_set(): break
            res = check_discord_direct(u)
            stats["discord_checked"] += 1
            if res is True:
                stats["discord_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 💎⚡️\n( ديسكورد - {label} )")
            elif res == "BLOCKED": 
                time.sleep(300) # إيقاف 5 دقائق
            time.sleep(random.uniform(15.0, 20.0)) # بطيء جداً عشان ما ينحظر
    except Exception as e: print(f"Err Discord: {e}")

def start_psn_snipers(chat_id):
    for i in range(3): # 3 خيوط فقط عشان ما نضغط على الـ IP
        threading.Thread(target=worker_psn, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.5)

def start_discord_snipers(chat_id):
    for i in range(2): # خيطين فقط
        threading.Thread(target=worker_discord, args=(chat_id, i+1), daemon=True).start()
        time.sleep(0.5)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت القنص النووي (بدون بروكسيات)\n\n"
                     "/start_all - تشغيل الكل\n"
                     "/tiktok - تيك توك\n"
                     "/psn - سوني\n"
                     "/discord - ديسكورد\n"
                     "/stop_all - إيقاف الكل\n"
                     "/status - الإحصائيات")

@bot.message_handler(commands=['start_all'])
def cmd_start_all(m):
    if not is_owner(m): return
    stop_tiktok.clear(); stop_psn.clear(); stop_discord.clear()
    for i in range(3): threading.Thread(target=worker_tiktok, args=(m.chat.id, i+1), daemon=True).start()
    bot.send_message(m.chat.id, "🚀 تيك توك (3 خيوط)!")
    start_psn_snipers(m.chat.id)
    bot.send_message(m.chat.id, "🚀 سوني (3 خيوط)!")
    start_discord_snipers(m.chat.id)
    bot.send_message(m.chat.id, "🚀 ديسكورد (2 خيوط)!")

@bot.message_handler(commands=['tiktok'])
def cmd_tiktok(m):
    if not is_owner(m): return
    stop_tiktok.clear()
    for i in range(3): threading.Thread(target=worker_tiktok, args=(m.chat.id, i+1), daemon=True).start()
    bot.reply_to(m, "TikTok Started!")

@bot.message_handler(commands=['psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    bot.reply_to(m, "🚀 سوني (3 خيوط)!")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=['discord'])
def cmd_discord(m):
    if not is_owner(m): return
    stop_discord.clear()
    bot.reply_to(m, "🚀 ديسكورد (2 خيوط)!")
    start_discord_snipers(m.chat.id)

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_tiktok.set(); stop_psn.set(); stop_discord.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات:**\n\n"
           f"**تيك توك:**\nتم فحصه: {stats['tiktok_checked']} | تم صيده: {stats['tiktok_found']}\n"
           f"**سوني:**\nتم فحصه: {stats['psn_checked']} | تم صيده: {stats['psn_found']}\n"
           f"**ديسكورد:**\nتم فحصه: {stats['discord_checked']} | تم صيده: {stats['discord_found']}\n")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("Bot is running...")
    try: 
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e: 
        print(f"Webhook delete error: {e}")
        
    bot.infinity_polling()
