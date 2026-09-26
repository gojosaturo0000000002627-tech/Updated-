"""
config.py — Environment variables & global settings.

Never hardcode secrets here. Everything comes from environment variables
(Render dashboard → Environment tab), or from a local `.env` file while testing.

Env vars:
  BOT_TOKEN      (required)  Token from @BotFather
  CHANNEL_ID     (required)  Your channel: "@your_channel" (public) or "-100xxxxxxxxxx" (private)
  ADMIN_CHAT_ID  (optional)  Your personal chat id, so only YOU can use /sendnow and /test
  PORT           (optional)  HTTP port for the health-check server (Render sets this)
  MUSE_CHANNEL_IDS (optional) Comma-separated YouTube channel IDs to watch
                             (default: Muse India main channel)
  EVENING_CUTOFF_HOUR (optional) 7 PM message only shows releases from this hour onwards (default 18)
  ANIMESCHEDULE_TOKEN (optional) animeschedule.net API v3 app token (needs a free account there)
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"           # runtime state (sent-message history)
BANNER_PATH = ROOT / "assets" / "banner.jpg"   # the photo attached on top of every message

# ---------------------------------------------------------------------------
# Timezone — IST has no daylight saving, so fixed times are always correct
# ---------------------------------------------------------------------------
IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Tiny .env loader (for local testing only; on Render env vars come from dashboard)
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

_load_dotenv()

# ---------------------------------------------------------------------------
# Required settings
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()

# ---------------------------------------------------------------------------
# Optional settings (with sane defaults)
# ---------------------------------------------------------------------------
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()
PORT = int(os.environ.get("PORT", "10000"))

# Muse India main YouTube channel (handle: @MuseIndiaChannel).
# You can add more channels (e.g. Muse IN Collection / Muse Hindi Dub) as a
# comma-separated list — find the ID in the channel page source: "channelId":"UC..."
MUSE_CHANNEL_IDS = [
    c.strip()
    for c in os.environ.get(
        "MUSE_CHANNEL_IDS", "UCYYhAzgWuxPauRXdPpLAX3Q"
    ).split(",")
    if c.strip()
]

# The evening (7 PM) message only lists shows releasing from this hour onwards.
EVENING_CUTOFF_HOUR = int(os.environ.get("EVENING_CUTOFF_HOUR", "18"))

# Optional: animeschedule.net API v3 token (https://animeschedule.net → account → API tab).
# Without a token this source is simply skipped; the bot uses LiveChart instead.
ANIMESCHEDULE_TOKEN = os.environ.get("ANIMESCHEDULE_TOKEN", "").strip()

# Daily send times (IST)
MORNING_SEND_TIME = (10, 0)    # 10:00 AM IST
EVENING_SEND_TIME = (19, 0)    #  7:00 PM IST

# Per-source HTTP timeout (seconds) — prompt requires 10s, skip source on timeout
SOURCE_TIMEOUT = 10.0

# Telegram limits (in UTF-16 code units!)
TG_CAPTION_LIMIT = 1024   # sendPhoto caption max length
TG_MESSAGE_LIMIT = 4096   # sendMessage max length


def check_required_settings() -> list[str]:
    """Return a list of human-readable problems (empty = everything is fine)."""
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN is not set. Get it from @BotFather on Telegram.")
    # NOTE: CHANNEL_ID is NOT required anymore — bot ko kisi bhi channel ka
    # admin bana kar add kar do, woh khud register ho jata hai.
    return problems
