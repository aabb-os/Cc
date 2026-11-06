# app.py
# يشتغل كـ: gunicorn app:app

import os
import signal
import random
import string
import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import telebot
from flask import Flask
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import (
    PSNAWPNotFoundError,
    PSNAWPForbiddenError,
    PSNAWPAuthenticationError,
)
from curl_cffi import requests as curl_requests

log = logging.getLogger("psn_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ============ Config ============
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")
NPSSO_TOKEN = os.environ.get("NPSSO_TOKEN")

if not TOKEN or not OWNER_IDS_STR or not NPSSO_TOKEN:
    log.error("ENV missing: BOT_TOKEN/OWNER_ID/NPSSO_TOKEN")
    TOKEN = TOKEN or "MISSING"
    OWNER_IDS_STR = OWNER_IDS_STR or "0"
    NPSSO_TOKEN = NPSSO_TOKEN or "MISSING"

OWNER_IDS = {int(x.strip()) for x in OWNER_IDS_STR.split(",") if x.strip().isdigit()}

# ============ Flask app ============
app = Flask(__name__)

@app.route("/")
def home():
    return "PSN V9 is running!"

@app.route("/health")
def health():
    s = stats.snapshot()
    return {"status": "ok", "stats": s, "psnawp_ready": psnawp is not None}

# ============ Bot & PSNAWP ============
bot = telebot.TeleBot(TOKEN, parse_mode=None)

psnawp: Optional[PSNAWP] = None
init_error: Optional[str] = None
try:
    psnawp = PSNAWP(NPSSO_TOKEN)
    me = psnawp.me()
    log.info("PSNAWP logged in as %s", me.online_id)
except PSNAWPAuthenticationError as e:
    init_error = f"NPSSO منتهي: {e}"
    log.error(init_error)
except Exception as e:
    init_error = str(e)
    log.error("PSNAWP init failed: %s", e)

# ============ State ============
stop_psn = threading.Event()
shutdown_event = threading.Event()
_bot_started = threading.Event()

@dataclass
class Stats:
    checked: int = 0
    found: int = 0
    errors: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            return {"checked": self.checked, "found": self.found, "errors": self.errors}

    def inc(self, key: str) -> None:
        with self.lock:
            setattr(self, key, getattr(self, key) + 1)

stats = Stats()

# ============ Telegram rate limiter ============
_tg_send_lock = threading.Lock()
_last_send_ts = 0.0
_MIN_SEND_GAP = 1.0 / 25.0

def safe_send(chat_id: int, text: str) -> bool:
    global _last_send_ts
    try:
        with _tg_send_lock:
            now = time.monotonic()
            wait = _MIN_SEND_GAP - (now - _last_send_ts)
            if wait > 0:
                time.sleep(wait)
            _last_send_ts = time.monotonic()
        bot.send_message(chat_id, text)
        return True
    except Exception as e:
        log.warning("safe_send failed: %s", e)
        return False

def is_owner(m) -> bool:
    return m.from_user is not None and m.from_user.id in OWNER_IDS

_ALPHABET = string.ascii_lowercase + string.digits

def gen_psn() -> str:
    return random.choice(string.ascii_lowercase) + "".join(
        random.choice(_ALPHABET) for _ in range(4)
    )

# ============ Legacy checker ============
LEGACY_URL = "https://secure.us.playstation.com/playstation/psn/profile/public/userData?onlineId={}"
LEGACY_HEADERS = {
    "Referer": "https://secure.us.playstation.com/logged-in/trophies/public-trophies/",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
    ),
}

def check_psn_legacy(username: str) -> Optional[bool]:
    try:
        res = curl_requests.get(
            LEGACY_URL.format(username),
            headers=LEGACY_HEADERS,
            impersonate="safari15_5",
            timeout=10,
        )
        if res.status_code == 200:
            return res.text.strip() == "{}"
        if res.status_code in (403, 429):
            log.warning("Legacy %s => %s", username, res.status_code)
            return None
    except Exception as e:
        log.debug("legacy check %s failed: %s", username, e)
    return None

def classify(username: str) -> str:
    return "خماسي مكرر" if len(set(username)) < 5 else "خماسي"

def is_taken_by_psnawp(username: str) -> bool:
    try:
        psnawp.user(online_id=username)
        return True
    except PSNAWPForbiddenError:
        return True
    except PSNAWPNotFoundError:
        return False
    except Exception as e:
        log.debug("psnawp.user(%s) error: %s", username, e)
        return True

# ============ Worker ============
def worker(chat_id: int) -> None:
    backoff = 3.0
    while not stop_psn.is_set() and not shutdown_event.is_set():
        username = gen_psn()
        stats.inc("checked")
        try:
            if is_taken_by_psnawp(username):
                time.sleep(backoff)
                continue
            res = check_psn_legacy(username)
            if res is None:
                time.sleep(backoff + random.uniform(0, 1.5))
                backoff = min(backoff * 1.5, 30.0)
                continue
            backoff = 3.0
            if res is True:
                stats.inc("found")
                safe_send(chat_id, f"استلم يالامير {username} 🎮🔥\n( سوني - {classify(username)} - متاح )")
            time.sleep(3 + random.uniform(0, 1.5))
        except Exception as e:
            stats.inc("errors")
            log.exception("worker error: %s", e)
            time.sleep(2 + random.uniform(0, 1))

def start_psn_snipers(chat_id: int) -> None:
    if psnawp is None:
        safe_send(chat_id, f"❌ فشل الاتصال بسوني.\nالسبب: {init_error}")
        return
    threading.Thread(target=worker, args=(chat_id,), daemon=True, name=f"worker-{chat_id}").start()

# ============ Handlers ============
@bot.message_handler(commands=["start"])
def cmd_start(m):
    if not is_owner(m):
        return
    safe_send(m.chat.id, "☢️ PSN V9 Bot\n\n/psn - تشغيل\n/stop_all - إيقاف\n/status - الإحصائيات")

@bot.message_handler(commands=["psn"])
def cmd_psn(m):
    if not is_owner(m):
        return
    stop_psn.clear()
    with stats.lock:
        stats.checked = stats.found = stats.errors = 0
    safe_send(m.chat.id, "🚀 جاري التشغيل...")
    start_psn_snipers(m.chat.id)

@bot.message_handler(commands=["stop_all"])
def cmd_stop_all(m):
    if not is_owner(m):
        return
    stop_psn.set()
    safe_send(m.chat.id, "⏹ تم إيقاف الكل.")

@bot.message_handler(commands=["status"])
def cmd_status(m):
    if not is_owner(m):
        return
    s = stats.snapshot()
    safe_send(m.chat.id, f"📊 الإحصائيات:\n🔍 الفحص: {s['checked']}\n✅ المتاح: {s['found']}\n⚠️ أخطاء: {s['errors']}")

# ============ Bot polling thread ============
def _bot_runner():
    if _bot_started.is_set():
        return
    _bot_started.set()
    log.info("Bot polling starting...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning("delete_webhook failed: %s", e)
    while not shutdown_event.is_set():
        try:
            bot.polling(non_stop=True, interval=0, timeout=60, allowed_updates=["message"])
        except Exception as e:
            log.error("polling crashed: %s", e)
            time.sleep(5)

def _ensure_bot_thread():
    if not _bot_started.is_set():
        t = threading.Thread(target=_bot_runner, daemon=True, name="bot-poller")
        t.start()

@app.before_request
def _start_bot_once():
    _ensure_bot_thread()

# ============ Signal handling ============
def _handle_signal(signum, _frame):
    log.info("Signal %s — shutdown", signum)
    stop_psn.set()
    shutdown_event.set()

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)
