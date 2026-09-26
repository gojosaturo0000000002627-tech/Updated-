"""
channels.py — Multi-channel registry.

Koi bhi is bot ko apne CHANNEL ka ADMIN bana kar jod sakta hai.
Telegram us waqt bot ko ek `my_chat_member` update bhejta hai —
wahi yahan registry (data/channels.json) me channel save hota hai.

  • add_channel(chat)    → bot ko admin banaya  → channel register
  • remove_channel(id)   → bot ko hata diya     → channel unregister
  • get_channels()       → sab registered channels (daily jobs in sabko bhejte hain)

Koi env var ki zaroorat NAHI — jo channel me admin banaloge, wahan updates chalu.
(Safety cap: MAX_CHANNELS, default 200 — env se badal sakte ho.)
"""

import json
import logging
import os
from datetime import datetime

from config import DATA_DIR, IST

log = logging.getLogger("channels")

MAX_CHANNELS = int(os.environ.get("MAX_CHANNELS", "200"))

_REGISTRY_FILE = DATA_DIR / "channels.json"


def _load() -> dict[str, dict]:
    try:
        data = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — fresh start is always safe
        return {}


def _save(registry: dict[str, dict]) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        _REGISTRY_FILE.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not save channel registry: %s", exc)


def get_channels() -> list[dict]:
    """All registered channels: [{"id": -100..., "title": ..., "username": ...}, ...]"""
    return list(_load().values())


def channel_ids() -> list[int]:
    return [int(c["id"]) for c in get_channels()]


def add_channel(chat) -> bool:
    """Register a chat the bot was added to. Returns True if NEW.

    Channels need the bot as ADMIN to post; groups work even when the
    bot is just a regular MEMBER — dono yahan register hote hain.
    """
    ctype = getattr(chat, "type", None)
    if ctype not in ("channel", "group", "supergroup"):
        log.info("ignoring non-group/channel chat %s (type=%s)",
                 getattr(chat, "id", "?"), ctype)
        return False

    registry = _load()
    key = str(chat.id)
    if key in registry:
        registry[key]["title"] = chat.title or registry[key].get("title", "untitled")
        _save(registry)
        return False  # already known

    if len(registry) >= MAX_CHANNELS:
        log.warning("chat limit reached (%s) — not adding %s", MAX_CHANNELS, chat.id)
        return False

    registry[key] = {
        "id": chat.id,
        "type": ctype,
        "title": chat.title or "untitled",
        "username": getattr(chat, "username", None),
        "added_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
    }
    _save(registry)
    log.info("✅ %s added: “%s” (%s) — total %d chat(s)",
             "channel" if ctype == "channel" else "group",
             registry[key]["title"], key, len(registry))
    return True


def remove_channel(chat_id) -> bool:
    registry = _load()
    key = str(chat_id)
    if key not in registry:
        return False
    info = registry.pop(key)
    _save(registry)
    log.info("❌ channel removed: “%s” (%s) — total %d channel(s)",
             info.get("title", "?"), key, len(registry))
    return True
