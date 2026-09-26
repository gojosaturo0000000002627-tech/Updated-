"""
main.py — The Telegram bot (entry point).

What runs here:
  • Long-polling Telegram bot (no webhook/domain needed)
  • Two daily jobs: 10:00 AM IST and 7:00 PM IST (Asia/Kolkata, no DST)
  • Tiny HTTP health-check server on 0.0.0.0:$PORT so Render keeps it alive
  • /sendnow  — admin command, sends the update right now
  • /test     — admin command, shows what every source returned
  • /start    — help text

Run locally:   python main.py
Run on Render: Web Service, start command `python main.py`
"""

import asyncio
import logging
import threading
from datetime import datetime, time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import BotCommand, Update
from telegram.constants import ChatType
from telegram.ext import (Application, CommandHandler, ContextTypes)

from config import (ADMIN_CHAT_ID, BOT_TOKEN, CHANNEL_ID, EVENING_SEND_TIME,
                    IST, MORNING_SEND_TIME, PORT, check_required_settings)
from template import tg_len

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Health-check HTTP server (Render requirement: bind 0.0.0.0:$PORT, answer /)
# ---------------------------------------------------------------------------

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — stdlib naming
        body = "OK - anime dub update bot is running".encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # silence default noisy access log
        log.debug("health: " + fmt % args)


def start_health_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health")
    thread.start()
    log.info("health-check server listening on 0.0.0.0:%s", PORT)


# ---------------------------------------------------------------------------
# Daily jobs
# ---------------------------------------------------------------------------

async def run_daily_update(context: ContextTypes.DEFAULT_TYPE, evening: bool) -> None:
    """Scheduled entry point — the whole update, guarded so it never crashes."""
    from sender import gather_and_send
    try:
        status = await gather_and_send(context.bot, evening=evening)
        log.info("daily update (%s): %s", "evening" if evening else "morning", status)
    except Exception:  # noqa: BLE001
        log.exception("daily update failed — will retry next scheduled run")


async def morning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_daily_update(context, evening=False)


async def evening_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_daily_update(context, evening=True)


# ---------------------------------------------------------------------------
# Commands (private chat only; /sendnow & /test are admin-gated)
# ---------------------------------------------------------------------------

def is_admin(update: Update) -> bool:
    """ADMIN_CHAT_ID unset → commands open (fine while testing)."""
    if not ADMIN_CHAT_ID or not update.effective_chat:
        return True
    return str(update.effective_chat.id) == ADMIN_CHAT_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "💫 𝗔𝗻𝗶𝗺𝗲 𝗗𝘂𝗯 𝗨𝗽𝗱𝗮𝘁𝗲 𝗕𝗼𝘁\n"
        "━━━━━━━━━━━━━━━\n"
        "Daily anime release updates → your channel at 10:00 AM & 7:00 PM IST.\n\n"
        "Commands:\n"
        "/sendnow — abhi turant update bhejo\n"
        "/test — sources ka debug report\n\n"
        f"Channel: {CHANNEL_ID or '⚠️ CHANNEL_ID not set'}"
    )


async def cmd_sendnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ You are not allowed to use this command.")
        return
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("🔒 Ye command sirf bot ke private chat mein chalegi.")
        return
    from sender import gather_and_send
    await update.message.reply_text("⏳ Sources check kar raha hoon...")
    try:
        status = await gather_and_send(context.bot, evening=False, force=True)
        await update.message.reply_text(
            "✅ Update channel par bhej diya!" if status == "sent"
            else "ℹ️ Ye message aaj pehle hi bheja ja chuka hai (duplicate block)."
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("/sendnow failed")
        await update.message.reply_text(f"❌ Failed: {exc}")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ You are not allowed to use this command.")
        return
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("🔒 Ye command sirf bot ke private chat mein chalegi.")
        return

    from builder import build_releases
    from template import split_long_text

    await update.message.reply_text("⏳ Sab sources check kar raha hoon (10s timeout each)...")
    now = datetime.now(IST)
    entries, report = await build_releases(now, evening=False)

    lines = [
        f"🖥 SOURCE REPORT — {now.strftime('%a %d %b, %I:%M %p')} IST",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for name, r in report.items():
        status = "✅" if r.ok else "❌"
        info = r.error if not r.ok else f"{len(r.items)} items"
        lines.append(f"{status} {r.name}: {info}")
        for n in r.notes[:4]:
            lines.append(f"     • {n}")
    lines.append("")
    lines.append(f"🎯 Final entries today: {len(entries)}")
    for r in entries:
        when = next(iter(r.lang_times.values()), None) or (
            r.time_dt.strftime("%I:%M %p") if r.time_dt else "Expected"
        )
        lines.append(
            f"  ⫷ {r.name}\n     {r.platform} | {when} | "
            f"E{r.episode if r.episode else '?'}{' (exp)' if r.episode_expected else ''} | "
            f"{','.join(r.langs)} | via: {'+'.join(r.sources)}"
        )
    if not entries:
        lines.append("  (nothing — message would be the 'no release today' fallback)")

    text = "\n".join(lines)
    for chunk in split_long_text(text, 3900):
        await update.message.reply_text(chunk)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("unhandled telegram error: %s", context.error)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def build_application() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    jq = app.job_queue
    if jq is None:
        raise RuntimeError(
            "JobQueue not available — install with: "
            "pip install 'python-telegram-bot[job-queue]'"
        )
    jq.run_daily(
        morning_job,
        time=dtime(*MORNING_SEND_TIME, tzinfo=IST),   # 10:00 AM IST
        name="morning_update",
    )
    jq.run_daily(
        evening_job,
        time=dtime(*EVENING_SEND_TIME, tzinfo=IST),   # 07:00 PM IST
        name="evening_update",
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sendnow", cmd_sendnow))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_error_handler(error_handler)
    return app


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "bot info"),
        BotCommand("sendnow", "send the update right now (admin)"),
        BotCommand("test", "source debug report (admin)"),
    ])
    log.info("bot is up — jobs: 10:00 & 19:00 IST → channel %s", CHANNEL_ID)


def main() -> None:
    problems = check_required_settings()
    if problems:
        for p in problems:
            log.error("CONFIG ERROR: %s", p)
        raise SystemExit(1)

    start_health_server()

    app = build_application()
    app.post_init = post_init
    log.info("starting polling (health server on :%s)...", PORT)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
