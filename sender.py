"""
sender.py — Builds the message and delivers it to the channel.

Photo + caption ALWAYS travel together (one sendPhoto), exactly as required:
  - full text ≤ 1024 chars  → single message: photo with the whole text as caption
  - longer                  → photo with header + first blocks as caption,
                              remaining blocks sent immediately after as text
                              messages (≤ 4096 chars each)

Also implements the "never send the exact same message twice" rule via a
daily hash file (data/sent.json).
"""

import hashlib
import json
import logging
from datetime import datetime

from config import (BANNER_PATH, CHANNEL_ID, DATA_DIR, IST, TG_CAPTION_LIMIT,
                    TG_MESSAGE_LIMIT)
from template import (build_message, build_no_update_message, split_for_caption,
                      split_long_text, tg_len)

log = logging.getLogger("sender")


# ---------------------------------------------------------------------------
# Dedup memory — which message hashes were already sent today
# ---------------------------------------------------------------------------

def _sent_file():
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR / "sent.json"


def _load_sent(today: str) -> list[str]:
    try:
        data = json.loads(_sent_file().read_text(encoding="utf-8"))
        if data.get("date") == today:
            return data.get("hashes", [])
    except Exception:  # noqa: BLE001
        pass
    return []


def _save_sent(today: str, hashes: list[str]) -> None:
    try:
        _sent_file().write_text(
            json.dumps({"date": today, "hashes": hashes[-50:]}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not save sent-hash file: %s", exc)


# ---------------------------------------------------------------------------
# Deliver
# ---------------------------------------------------------------------------

async def send_text_with_banner(bot, text: str, force: bool = False) -> str:
    """Send `text` to the channel with the banner photo attached on top."""
    if not CHANNEL_ID:
        raise RuntimeError("CHANNEL_ID is not set (Render → Environment → CHANNEL_ID)")

    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    already = _load_sent(today)
    if not force and digest in already:
        log.info("duplicate message suppressed (already sent today)")
        return "skipped-duplicate"

    photo = BANNER_PATH.read_bytes() if BANNER_PATH.exists() else None
    if photo is None:
        log.error("banner photo missing at %s — sending text only", BANNER_PATH)

    caption, rest = split_for_caption(text, TG_CAPTION_LIMIT)

    if photo is not None and rest is None:
        # Everything fits on the photo — photo + full text, always joined ✅
        await bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=caption)
    elif photo is not None:
        await bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=caption)
        for chunk in split_long_text(rest, TG_MESSAGE_LIMIT):
            await bot.send_message(chat_id=CHANNEL_ID, text=chunk)
    else:
        for chunk in split_long_text(text, TG_MESSAGE_LIMIT):
            await bot.send_message(chat_id=CHANNEL_ID, text=chunk)

    _save_sent(today, already + [digest])
    log.info("message sent (%d chars, split=%s)", tg_len(text), bool(rest))
    return "sent"


async def gather_and_send(bot, evening: bool = False, force: bool = False) -> str:
    """Full pipeline: check sources → build → send. Used by jobs, /sendnow and send_once.py."""
    from builder import build_releases  # local import (avoids circular import)

    now = datetime.now(IST)
    try:
        entries, report = await build_releases(now, evening=evening)
        any_ok = any(r.ok for r in report.values())
        text = (
            build_message(entries, now)
            if entries
            else build_no_update_message(now, evening=evening, sources_failed=not any_ok)
        )
    except Exception as exc:  # noqa: BLE001 — never leave the channel silent
        log.exception("build failed")
        text = build_no_update_message(now, evening=evening, sources_failed=True)
        text = text.replace(
            "❌", "⚠️ Bot update mein technical error aaya — thodi der baad dobara try karein\n❌"
        )

    return await send_text_with_banner(bot, text, force=force)
