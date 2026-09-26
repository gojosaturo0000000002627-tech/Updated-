"""
schedule_config.py — OPTIONAL overrides only. YOU DON'T NEED TO TOUCH THIS.

════════════════════════════════════════════════════════════════════════════
 THE BOT IS 100% LIVE — NO SHOWS ARE STORED IN THE CODE.
════════════════════════════════════════════════════════════════════════════
 Every run (10 AM & 7 PM) the bot checks the live Indian anime-dub schedule
 (animedubhindi.link/schedule.php) and builds the message from what it sees
 RIGHT NOW:

   • NEW anime starts  → appears on the schedule page → bot posts it automatically
   • anime ENDS        → disappears from the page    → bot stops posting it
   • episode numbers, times, seasons, languages → all read live every run
   • platform (Crunchyroll / Muse India / Netflix / JioHotstar ...) is detected
     live from Muse India uploads, Crunchyroll's feed, AnimeSchedule and news

 If the schedule site is temporarily down, the bot reuses the same-day cached
 copy, and Muse India / Crunchyroll / LiveChart / Google News still work.

════════════════════════════════════════════════════════════════════════════
 OPTIONAL: the three lists below are escape hatches — leave them EMPTY for
 the fully-live behaviour. Use them only if you ever want to force something.
════════════════════════════════════════════════════════════════════════════
"""

# 1) Force specific shows (overrides live data for that show).
#    Example:
#    DUB_SCHEDULE = [{
#        "name": "BLACK TORCH",
#        "platform": "Crunchyroll",
#        "langs": ["Hindi"],
#        "season": 1,
#        "time": "18:30",                                # your display time
#        "weekly_day": "sat",
#        "episode": {"start": 4, "date": "2026-09-26"},  # auto +1 weekly
#    }]
DUB_SCHEDULE: list[dict] = []

# 2) Platform labels for shows (only needed if live detection says "Streaming").
#    Example: PLATFORM_HINTS = {"captain tsubasa": "Muse India (YouTube)"}
PLATFORM_HINTS: dict[str, str] = {}

# 3) Shows you NEVER want posted (matched by keyword).
#    Example: IGNORE_SHOWS = ["captain tsubasa"]
IGNORE_SHOWS: list[str] = []
