"""
sender.py — Builds the message ONCE and delivers it to EVERY connected channel.

Multi-channel: the registry lives in channels.py (data/channels.json).
The daily text is built once per run, then broadcast:

Photo + caption ALWAYS travel together (one sendPhoto), exactly as required:
  - full text ≤ 1024 chars  → single message: photo with the whole text as caption
  - longer                  → photo with header + first blocks as caption,
                              remaining blocks sent immediately after as text
                              messages (≤ 4096 chars each)

"Never send the exact same message twice" is enforced PER CHANNEL, per day,
via data/sent.json → {"date": "...", "channels": {"<chat_id>": ["<hash>", ...]}}

If a channel kicks the bot mid-broadcast, it is auto-removed from the
registry and the rest of the channels still get their message.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime

import channels
from telegram.error import BadRequest, Forbidden, RetryAfter

from config import (BANNER_PATH, DATA_DIR, IST, TG_CAPTION_LIMIT, TG_MESSAGE_LIMIT)
from template import (build_message, build_no_update_message, split_for_caption,
                      split_long_text, tg_len)

log = logging.getLogger("sender")


# ---------------------------------------------------------------------------
# Dedup memory — per channel, per day
# ---------------------------------------------------------------------------

def _sent_file():
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR / "sent.json"


def _load_day(today: str) -> dict[str, list[str]]:
    """Hashes already sent today, per channel id."""
    try:
        data = json.loads(_sent_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if data.get("date") != today:
        return {}  # new day → clean slate
    per_channel = data.get("channels", {})
    return per_channel if isinstance(per_channel, dict) else {}


def _save_day(today: str, per_channel: dict[str, list[str]]) -> None:
    try:
        _sent_file().write_text(
            json.dumps(
                {"date": today, "channels": {k: v[-50:] for k, v in per_channel.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not save sent-hash file: %s", exc)


# ---------------------------------------------------------------------------
# Deliver
# ---------------------------------------------------------------------------

async def send_text_with_banner(bot, chat_id, text: str, force: bool = False) -> str:
    """Send `text` to ONE channel with the banner photo attached on top."""
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    per_channel = _load_day(today)
    already = per_channel.get(str(chat_id), [])
    if not force and digest in already:
        return "skipped-duplicate"

    photo = BANNER_PATH.read_bytes() if BANNER_PATH.exists() else None
    if photo is None:
        log.error("banner photo missing at %s — sending text only", BANNER_PATH)

    caption, rest = split_for_caption(text, TG_CAPTION_LIMIT)

    if photo is not None and rest is None:
        # Everything fits on the photo — photo + full text, always joined ✅
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
    elif photo is not None:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
        for chunk in split_long_text(rest, TG_MESSAGE_LIMIT):
            await bot.send_message(chat_id=chat_id, text=chunk)
    else:
        for chunk in split_long_text(text, TG_MESSAGE_LIMIT):
            await bot.send_message(chat_id=chat_id, text=chunk)

    per_channel[str(chat_id)] = already + [digest]
    _save_day(today, per_channel)
    log.info("message sent to %s (%d chars, split=%s)", chat_id, tg_len(text), bool(rest))
    return "sent"


async def deliver_to_all(bot, text: str, force: bool = False) -> str:
    """Broadcast one already-built message to every connected channel."""
    targets = channels.get_channels()
    if not targets:
        log.warning("koi channel connected nahi — message skip "
                    "(bot ko kisi channel ka ADMIN banao, updates khud chalu ho jayenge)")
        return "no-channels"

    sent = skipped = failed = 0
    for ch in targets:
        chat_id = ch["id"]
        try:
            status = await send_text_with_banner(bot, chat_id, text, force=force)
            if status == "sent":
                sent += 1
            else:
                skipped += 1
        except Forbidden:
            log.warning("channel %s (%s) ne bot ko rok diya — registry se hata raha hoon",
                        ch.get("title"), chat_id)
            channels.remove_channel(chat_id)
            failed += 1
        except RetryAfter as exc:  # flood control — wait and try once more
            await asyncio.sleep(exc.retry_after + 1)
            try:
                status = await send_text_with_banner(bot, chat_id, text, force=force)
                if status == "sent":
                    sent += 1
                else:
                    skipped += 1
            except Exception:  # noqa: BLE001
                failed += 1
        except BadRequest as exc:
            if "chat not found" in str(exc).lower():
                channels.remove_channel(chat_id)
            log.warning("send to %s failed: %s", chat_id, exc)
            failed += 1
        except Exception as exc:  # noqa: BLE001 — one bad channel must not stop the rest
            log.warning("send to %s failed: %s", chat_id, exc)
            failed += 1
        await asyncio.sleep(0.3)  # be gentle with Telegram rate limits

    log.info("broadcast done → sent:%d skipped:%d failed:%d", sent, skipped, failed)
    return f"sent:{sent} skipped:{skipped} failed:{failed}"


async def gather_and_send(bot, evening: bool = False, force: bool = False) -> str:
    """Full pipeline: check sources → build message ONCE → send to ALL channels."""
    from builder import build_releases  # local import (avoids circular import)

    now = datetime.now(IST)
    try:
        entries, report = await build_releases(now, evening=evening)
        backbone = report.get("dub_schedule")
        any_ok = any(r.ok for r in report.values()) and bool(backbone and backbone.ok)
        text = (
            build_message(entries, now)
            if entries
            else build_no_update_message(now, evening=evening, sources_failed=not any_ok)
        )
    except Exception as exc:  # noqa: BLE001 — never leave the channels silent
        log.exception("build failed")
        text = build_no_update_message(now, evening=evening, sources_failed=True)
        text = text.replace(
            "❌", "⚠️ Bot update mein technical error aaya — thodi der baad dobara try karein\n❌"
        )

    return await deliver_to_all(bot, text, force=force)
