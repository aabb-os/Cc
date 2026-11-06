import os
import time
import random
import string
import threading
import datetime
import html
import logging
from dataclasses import dataclass, field

import telebot
from flask import Flask
from curl_cffi import requests as curl_requests

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
)
log = logging.getLogger("psn-sniper")


# ─────────────────────────────────────────────
# Flask (health check for Render)
# ─────────────────────────────────────────────
app = Flask(__name__)


@app.route("/")
def home():
    return "PSN Sniper is running!"


def run_flask() -> None:
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN")
OWNER_IDS_STR = os.environ.get("OWNER_ID")

if not TOKEN or not OWNER_IDS_STR:
    log.error("BOT_TOKEN و OWNER_ID مطلوبان.")
    raise SystemExit(1)

try:
    OWNER_IDS = {int(i.strip()) for i in OWNER_IDS_STR.split(",") if i.strip()}
except ValueError:
    log.error("OWNER_ID يجب أن يكون أرقاماً مفصولة بفواصل.")
    raise SystemExit(1)

bot = telebot.TeleBot(TOKEN, parse_mode=None)


# ─────────────────────────────────────────────
# Proxies (hot reloadable)
# ─────────────────────────────────────────────
class ProxyPool:
    def __init__(self, path: str = "proxies.txt"):
        self.path = path
        self._lock = threading.Lock()
        self._items: list[str] = []
        self.reload()

    def reload(self) -> int:
        items: list[str] = []
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            items.append(line)
            except OSError as e:
                log.warning("فشل قراءة %s: %s", self.path, e)
        with self._lock:
            self._items = items
            return len(items)

    def pick(self) -> str | None:
        with self._lock:
            if not self._items:
                return None
            return random.choice(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


proxies = ProxyPool()


# ─────────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────────
@dataclass
class Stats:
    checked: int = 0
    found: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self._lock:
            return {"checked": self.checked, "found": self.found, "errors": self.errors}

    def inc(self, key: str) -> int:
        with self._lock:
            setattr(self, key, getattr(self, key) + 1)
            return getattr(self, key)

    def reset(self) -> None:
        with self._lock:
            self.checked = self.found = self.errors = 0


stats = Stats()
stop_event = threading.Event()
throttle_event = threading.Event()
gen_lock = threading.Lock()
workers_lock = threading.Lock()
workers: list[threading.Thread] = []

MAX_THREADS = 15


def is_owner(m) -> bool:
    return m.from_user is not None and m.from_user.id in OWNER_IDS


# ─────────────────────────────────────────────
# Username generator
# ─────────────────────────────────────────────
_NAME_CHARS = string.ascii_lowercase + string.digits
_FIRST_CHARS = string.ascii_lowercase


def gen_psn():
    while True:
        u = random.choice(_FIRST_CHARS) + "".join(
            random.choice(_NAME_CHARS) for _ in range(4)
        )
        yield u


# ─────────────────────────────────────────────
# PSN check
# ─────────────────────────────────────────────
CHECK_URL = (
    "https://secure.us.playstation.com/playstation/psn/profile/"
    "public/userData?onlineId={u}"
)

CHECK_HEADERS = {
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/15.5 Safari/605.1.15"
    ),
    "Referer": "https://secure.us.playstation.com/logged-in/trophies/public-trophies/",
}


def check_psn(username: str) -> str | bool:
    proxy = proxies.pick()
    try:
        res = curl_requests.get(
            CHECK_URL.format(u=username),
            headers=CHECK_HEADERS,
            impersonate="safari15_5",
            timeout=8,
            proxy=proxy,
        )
    except curl_requests.errors.RequestsError as e:
        log.debug("request error (%s): %s", username, e)
        return "PROXY_FAIL" if proxy else "NET_FAIL"
    except Exception as e:
        log.debug("unexpected error (%s): %s", username, e)
        return "ERROR"

    if res.status_code == 200:
        body = res.text.strip()
        if body == "{}":
            return True
        if body.startswith("{"):
            return False
        return "ERROR"

    if res.status_code in (403, 429):
        return "BLOCKED"

    return "ERROR"


# ─────────────────────────────────────────────
# Safe send with retry
# ─────────────────────────────────────────────
def safe_send(chat_id: int, text: str, retries: int = 3) -> bool:
    for attempt in range(retries):
        try:
            bot.send_message(chat_id, text)
            return True
        except Exception as e:
            log.warning("send_message فشل (محاولة %d): %s", attempt + 1, e)
            time.sleep(1 + attempt)
    return False


# ─────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────
def worker(chat_id: int, psn_gen) -> None:
    while not stop_event.is_set():
        try:
            if throttle_event.is_set():
                time.sleep(0.3)

            with gen_lock:
                u = next(psn_gen)

            stats.inc("checked")
            res = check_psn(u)

            if res is True:
                total = stats.inc("found")
                ts = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                msg = (
                    f"🎯 يوزر PSN متاح!\n"
                    f"👤 {html.escape(u)}\n"
                    f"⏰ {ts}\n"
                    f"📊 إجمالي: {total}"
                )
                safe_send(chat_id, msg)

                throttle_event.set()
                try:
                    time.sleep(3)
                finally:
                    throttle_event.clear()

            elif res == "BLOCKED":
                time.sleep(random.uniform(10, 20))
            elif res in ("PROXY_FAIL", "NET_FAIL"):
                time.sleep(random.uniform(1, 3))
            else:
                time.sleep(random.uniform(0.5, 1.5))

        except Exception as e:
            stats.inc("errors")
            log.exception("worker crash: %s", e)
            time.sleep(2)


# ─────────────────────────────────────────────
# Snipers lifecycle
# ─────────────────────────────────────────────
def start_psn_snipers(chat_id: int) -> int:
    with workers_lock:
        stop_event.set()
        time.sleep(0.3)
        alive = [t for t in workers if t.is_alive()]
        if alive:
            log.warning("ما زال %d خيطاً حياً بعد stop", len(alive))
        workers.clear()
        stop_event.clear()
        throttle_event.clear()

        psn_gen = gen_psn()
        for i in range(MAX_THREADS):
            t = threading.Thread(
                target=worker,
                args=(chat_id, psn_gen),
                name=f"snip-{i}",
                daemon=True,
            )
            t.start()
            workers.append(t)
        return len(workers)


# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(m):
    if not is_owner(m):
        return
    bot.reply_to(
        m,
        "☢️ PSN Sniper\n"
        "/psn — تشغيل\n"
        "/stop_all — إيقاف\n"
        "/status — إحصائيات\n"
        "/reload_proxies — إعادة تحميل البروكسي",
    )


@bot.message_handler(commands=["psn"])
def cmd_psn(m):
    if not is_owner(m):
        return
    if len(proxies) == 0:
        log.warning("لا بروكسي — سيُفحص بالـ IP المباشر")
    stats.reset()
    n = start_psn_snipers(m.chat.id)
    bot.reply_to(m, f"🚀 تشغيل بـ {n} خيوط...")


@bot.message_handler(commands=["stop_all"])
def cmd_stop_all(m):
    if not is_owner(m):
        return
    stop_event.set()
    bot.reply_to(m, "⏹ إيقاف الكل.")


@bot.message_handler(commands=["status"])
def cmd_status(m):
    if not is_owner(m):
        return
    s = stats.snapshot()
    msg = (
        f"📊 الإحصائيات:\n"
        f"🔍 الفحص: {s['checked']}\n"
        f"✅ المتاح: {s['found']}\n"
        f"⚠️ أخطاء: {s['errors']}"
    )
    bot.reply_to(m, msg)


@bot.message_handler(commands=["reload_proxies"])
def cmd_reload(m):
    if not is_owner(m):
        return
    n = proxies.reload()
    bot.reply_to(m, f"🔄 تم تحميل {n} بروكسي.")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
def main() -> None:
    threading.Thread(target=run_flask, daemon=True, name="flask").start()
    log.info("PSN Sniper starting — threads=%d proxies=%d", MAX_THREADS, len(proxies))

    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning("delete_webhook: %s", e)

    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=60)
        except Exception as e:
            log.exception("polling crash: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
