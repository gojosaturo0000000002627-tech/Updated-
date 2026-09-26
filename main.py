"""
main.py — The Telegram bot (entry point). MULTI-CHANNEL + MULTI-GROUP 📺👥

Koi bhi is bot ko jod sakta hai:
  • GROUP   → sirf MEMBER ke roop me add karo (admin ki zaroorat NAHI!)
  • CHANNEL → Administrators → Add Admin → ye bot (Telegram rule: channel me
              post karne ke liye admin hona zaroori hai — sab bots ke liye)

Add karte hi bot turant welcome post karta hai aur chat register ho jata hai.
Daily jobs (10:00 AM & 7:00 PM IST) message build karke SAB chats par bhejte hain.

What runs here:
  • Long-polling Telegram bot (no webhook/domain needed)
  • Two daily jobs: 10:00 AM IST and 7:00 PM IST (Asia/Kolkata, no DST)
  • Tiny HTTP health-check server on 0.0.0.0:$PORT so Render keeps it alive
  • /sendnow  — admin command, sends the update right now (all chats)
  • /test     — admin command, shows what every source returned
  • /channels — admin command, lists connected channels & groups
  • /start    — help text

Run locally:   python main.py
Run on Render: Web Service, start command `python main.py`
"""

import logging
import threading
from datetime import datetime, time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import channels
from telegram import BotCommand, Update
from telegram.constants import ChatType
from telegram.error import Forbidden
from telegram.ext import (Application, ChatMemberHandler, CommandHandler,
                          ContextTypes)

from config import (ADMIN_CHAT_ID, BOT_TOKEN, CHANNEL_ID, EVENING_SEND_TIME,
                    IST, MORNING_SEND_TIME, PORT, check_required_settings)
from template import split_long_text

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
# Chat add/remove — "GROUP me member add karo (admin nahi chahiye), CHANNEL me admin banao"
# ---------------------------------------------------------------------------

WELCOME_POST = (
    "✅ 𝗔𝗻𝗶𝗺𝗲 𝗗𝘂𝗯 𝗨𝗽𝗱𝗮𝘁𝗲 𝗕𝗼𝘁 𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗲𝗱!\n"
    "━━━━━━━━━━━━━━━━━\n"
    "📅 Daily anime release updates ab yahan milenge — 10:00 AM & 7:00 PM IST\n"
    "🎬 Hindi • Tamil • Telugu dub anime — exact time + platform ke saath\n"
    "➖ Band karana ho to: admins ye bot remove kar dein"
)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fires when the bot is added to / removed from any chat.

    • CHANNEL → bot ko ADMIN banana padta hai (Telegram rule — channel me
      sirf admin post kar sakta hai, koi bhi bot nahi)
    • GROUP   → sirf MEMBER add karo, admin ki zaroorat NAHI — updates chalu!
    """
    cm = update.my_chat_member
    if cm is None or cm.chat is None:
        return
    chat = cm.chat
    new = cm.new_chat_member
    status = new.status if new else ""

    is_channel = chat.type == ChatType.CHANNEL
    is_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    if not is_channel and not is_group:
        return  # private chats ignore

    # Kya bot yahan post kar sakta hai?
    can_post = (
        status == "administrator"
        or (is_group and status == "member")                     # group me admin nahi chahiye!
        or (status == "restricted"
            and bool(getattr(new, "can_send_messages", False)))  # muted but can still send
    )

    if can_post:
        if channels.add_channel(chat):
            try:  # chhota welcome post — turant pata chale bot live hai
                await context.bot.send_message(chat_id=chat.id, text=WELCOME_POST)
            except Forbidden:
                # add to hua par post karne ki permission nahi — bekaar hai
                log.warning("chat %s par post karne ki permission nahi — removing", chat.id)
                channels.remove_channel(chat.id)
            except Exception as exc:  # noqa: BLE001 — welcome best-effort hai
                log.warning("welcome post to %s failed: %s", chat.id, exc)
    else:
        # kicked / left / restricted-without-send → unregister
        channels.remove_channel(chat.id)


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
# Commands (private chat only; admin commands are admin-gated)
# ---------------------------------------------------------------------------

def is_admin(update: Update) -> bool:
    """ADMIN_CHAT_ID unset → commands open (fine while testing)."""
    if not ADMIN_CHAT_ID or not update.effective_chat:
        return True
    return str(update.effective_chat.id) == ADMIN_CHAT_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = len(channels.get_channels())
    await update.message.reply_text(
        "💫 𝗔𝗻𝗶𝗺𝗲 𝗗𝘂𝗯 𝗨𝗽𝗱𝗮𝘁𝗲 𝗕𝗼𝘁\n"
        "━━━━━━━━━━━━━━━\n"
        "Daily anime release updates — Hindi, Tamil & Telugu dub.\n\n"
        "🔗 𝗔𝗮𝗽 𝗸𝗼𝗶 𝗯𝗵𝗶 𝗷𝗼𝗱 𝘀𝗮𝗸𝘁𝗮 𝗵𝗮𝗶:\n"
        "👥 𝗚𝗿𝗼𝘂𝗽 — bas member ke roop me add karo (admin ki zaroorat NAHI!)\n"
        "📺 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 — Administrators → Add Admin → ye bot\n"
        "(Telegram rule: channel me post karne ke liye admin hona padta hai)\n"
        "Bas! Wahan updates apne aap aane lagenge (10:00 AM & 7:00 PM IST).\n\n"
        f"📺 Abhi {n} channel/group connected hai{'n' if n != 1 else ''}.\n\n"
        "Commands:\n"
        "/sendnow — abhi turant update bhejo\n"
        "/test — sources ka debug report\n"
        "/channels — connected channels ki list"
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
        if status == "no-channels":
            await update.message.reply_text(
                "⚠️ Koi channel/group connected nahi hai!\n"
                "👥 Group me member ke roop me add karo (admin nahi chahiye), ya\n"
                "📺 channel me admin banao — wahan updates khud chale jayenge."
            )
        elif status.startswith("sent:"):
            await update.message.reply_text(f"✅ Broadcast complete! ({status})")
        else:
            await update.message.reply_text(f"ℹ️ {status}")
    except Exception as exc:  # noqa: BLE001
        log.exception("/sendnow failed")
        await update.message.reply_text(f"❌ Failed: {exc}")


async def cmd_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ You are not allowed to use this command.")
        return
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("🔒 Ye command sirf bot ke private chat mein chalegi.")
        return

    chs = channels.get_channels()
    if not chs:
        await update.message.reply_text(
            "📭 Abhi koi channel/group connected nahi.\n"
            "👥 Group → member ke roop me add karo (admin nahi chahiye)\n"
            "📺 Channel → Administrators → Add Admin → ye bot"
        )
        return
    lines = [f"📺 Connected chats: {len(chs)}", "━━━━━━━━━━━━━━━━━━"]
    for c in chs:
        icon = "📺" if c.get("type") == "channel" else "👥"
        uname = f" (@{c['username']})" if c.get("username") else ""
        lines.append(f"{icon} {c['title']}{uname}\n   id: {c['id']} • added: {c.get('added_at', '?')}")
    text = "\n".join(lines)
    for chunk in split_long_text(text, 3900):
        await update.message.reply_text(chunk)


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ You are not allowed to use this command.")
        return
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("🔒 Ye command sirf bot ke private chat mein chalegi.")
        return

    from builder import build_releases

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

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "bot info & jodne ka tarika"),
        BotCommand("sendnow", "send the update right now (admin)"),
        BotCommand("test", "source debug report (admin)"),
        BotCommand("channels", "connected channels/groups ki list (admin)"),
    ])

    if CHANNEL_ID:  # legacy fallback: env me diya ho to registry me bhi daal do
        try:
            chat = await app.bot.get_chat(CHANNEL_ID)
            channels.add_channel(chat)
        except Exception as exc:  # noqa: BLE001
            log.warning("CHANNEL_ID env (%s) resolve nahi hua: %s", CHANNEL_ID, exc)

    n = len(channels.get_channels())
    if n:
        log.info("bot is up — jobs: 10:00 & 19:00 IST → %d channel/group(s)", n)
    else:
        log.info("bot is up — jobs: 10:00 & 19:00 IST → koi channel/group abhi nahi "
                 "(koi bhi GROUP me member banao ya CHANNEL me admin — updates khud shuru)")


def build_application() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
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

    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sendnow", cmd_sendnow))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    problems = check_required_settings()
    if problems:
        for p in problems:
            log.error("CONFIG ERROR: %s", p)
        raise SystemExit(1)

    start_health_server()

    app = build_application()
    log.info("starting polling (health server on :%s)...", PORT)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
