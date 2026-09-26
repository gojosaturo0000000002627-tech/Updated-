"""
send_once.py — One-shot sender (for the Render CRON JOB alternative).

Instead of a 24/7 web service, you can create two Render Cron Jobs:
  morning  →  python send_once.py morning   (schedule: "0 4 * * *"  = 09:30 IST)
  evening  →  python send_once.py evening   (schedule: "0 13 * * *" = 18:30 IST)

It checks all sources once, sends the update, and exits — perfect for cron.
"""

import asyncio
import sys
from datetime import datetime

from config import BOT_TOKEN, CHANNEL_ID, IST, check_required_settings
from telegram import Bot


async def run(mode: str) -> None:
    from sender import gather_and_send
    async with Bot(BOT_TOKEN) as bot:
        status = await gather_and_send(bot, evening=(mode == "evening"))
        if status == "no-channels":
            print(f"[send_once/{mode}] → koi channel connected nahi "
                  "(bot ko kisi channel ka admin banao)")
        else:
            print(f"[send_once/{mode}] → {status}")


def main() -> None:
    problems = check_required_settings()
    if problems:
        for p in problems:
            print(f"CONFIG ERROR: {p}")
        raise SystemExit(1)

    if len(sys.argv) > 1 and sys.argv[1] in ("morning", "evening"):
        mode = sys.argv[1]
    else:
        # auto: after 3 PM IST treat it as the evening run
        mode = "evening" if datetime.now(IST).hour >= 15 else "morning"

    print(f"[send_once] running in '{mode}' mode at {datetime.now(IST):%Y-%m-%d %H:%M IST}")
    asyncio.run(run(mode))


if __name__ == "__main__":
    main()
