import os
import telebot
import threading
import time
import random
import string
import requests
from flask import Flask
from playwright.sync_api import sync_playwright

# --- إعدادات Flask (الوهمي لـ Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Playwright Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

# --- الإعدادات الأساسية ---
TOKEN = "9134237983:AAFdXB9Zw2sXWujnAdebF8YuiU9cUx3XHYA"
OWNER_IDS = [7972911357, 8487652113]

bot = telebot.TeleBot(TOKEN)
stop_psn = threading.Event()

stats = {"psn_checked": 0, "psn_found": 0, "psn_errors": 0}

def is_owner(m): return m.from_user.id in OWNER_IDS

# ==========================================
# دوال التوليد
# ==========================================
def gen_psn():
    chars = string.ascii_lowercase + string.digits
    while True:
        u = random.choice(string.ascii_lowercase) + "".join(random.choice(chars) for _ in range(4))
        if len(set(u)) < 5: yield u

# ==========================================
# محرك الفحص (Playwright)
# ==========================================
def check_psn_playwright(username):
    try:
        with sync_playwright() as p:
            # تشغيل المتصفح بأقل استهلاك للرام
            browser = p.chromium.launch(
                headless=True, 
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--single-process']
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
            )
            page = context.new_page()
            
            # فتح صفحة البروفايل في PSNProfiles
            url = f"https://psnprofiles.com/{username}"
            response = page.goto(url, timeout=20000, wait_until="domcontentloaded")
            
            if response.status == 404:
                browser.close()
                return True # متاح
            
            content = page.content()
            if "Profile Not Found" in content or "This user has not been found" in content:
                browser.close()
                return True
                
            browser.close()
            return False # محجوز
            
    except Exception as e:
        # إذا صار خطأ في المتصفح (نفاذ رام أو حظر)، نرجع رسالة الخطأ
        return f"ERROR: {str(e)[:50]}" 

# ==========================================
# دوال التشغيل
# ==========================================
def worker_psn(chat_id):
    count = 0
    while not stop_psn.is_set():
        try:
            u = next(gen_psn())
            stats["psn_checked"] += 1
            
            res = check_psn_playwright(u)
            
            if res is True:
                stats["psn_found"] += 1
                bot.send_message(chat_id, f"استلم يالامير {u} 🎮🥷🏼\n( سوني - خماسي مكرر )")
            elif isinstance(res, str) and res.startswith("ERROR"):
                stats["psn_errors"] += 1
                # يرسل الخطأ أول 3 مرات عشان نعرف وش المشكلة
                if stats["psn_errors"] <= 3:
                    bot.send_message(chat_id, f"🚨 خطأ في المتصفح:\n`{res}`", parse_mode='Markdown')
            
            count += 1
            if count % 10 == 0:
                bot.send_message(chat_id, f"🔄 سوني (متصفح) يفحص... (فحص {stats['psn_checked']})")
                
            time.sleep(random.uniform(3.0, 6.0))
        except Exception as e:
            time.sleep(5)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if not is_owner(m): return
    bot.reply_to(m, "☢️ بوت المتصفح\n\n/psn - تشغيل سوني\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=['start_all', 'psn'])
def cmd_psn(m):
    if not is_owner(m): return
    stop_psn.clear()
    threading.Thread(target=worker_psn, args=(m.chat.id,), daemon=True).start()
    bot.reply_to(m, "🚀 سوني (متصفح) Started!")

@bot.message_handler(commands=['stop_all'])
def cmd_stop_all(m):
    if not is_owner(m): return
    stop_psn.set()
    bot.reply_to(m, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=['status'])
def cmd_status(m):
    if not is_owner(m): return
    msg = (f"📊 **إحصائيات:**\n\n"
           f"**سوني:** {stats['psn_found']} من {stats['psn_checked']}\n"
           f"**أخطاء المتصفح:** {stats['psn_errors']}")
    bot.reply_to(m, msg, parse_mode='Markdown')

# ==========================================
# التشغيل النهائي
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Playwright Bot is running...")
    try: bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling()
