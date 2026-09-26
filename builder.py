"""
builder.py — Builds today's release list 100% LIVE from the sources.

Nothing is hardcoded: which shows appear (and when they stop appearing) is
deced by live data every single run:

  1. Anime-dub schedule page (animedubhindi.link) — the backbone. Every
     ongoing show + upcoming premiere with its exact drop timestamp.
       • a NEW anime starts → appears on the page → bot posts it automatically
       • an anime ENDS      → leaves the page   → bot stops posting it
     Times, episode numbers, seasons and languages all come from this page.
  2. Muse India YouTube RSS — actual uploads today (strongest confirmation,
     also detects Muse India as the platform).
  3. Crunchyroll video RSS — Indian-dub drops today (platform: Crunchyroll).
  4. LiveChart / AnimeSchedule — cross-check + expected episode numbers.
  5. Google News RSS — platform detection + catches anything missed.
  6. schedule_config.py — OPTIONAL overrides only (empty by default).

Every entry remembers which sources backed it (visible in /test).
"""

import logging
import re
from datetime import datetime, time as dtime, timedelta

from config import EVENING_CUTOFF_HOUR, IST
from models import AiredEpisode, Release, SourceResult
from schedule_config import DUB_SCHEDULE, IGNORE_SHOWS, PLATFORM_HINTS
from template import fmt_time

log = logging.getLogger("builder")

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Platform keywords found in news articles → platform label
PLATFORM_BY_KEYWORD = {
    "crunchyroll": "Crunchyroll",
    "netflix": "Netflix",
    "muse india": "Muse India (YouTube)",
    "jiohotstar": "JioHotstar",
    "hotstar": "JioHotstar",
    "prime video": "Prime Video",
    "amazon prime": "Prime Video",
    "anime times": "Anime Times",
}


# ---------------------------------------------------------------------------
# Name normalization / fuzzy matching
# ---------------------------------------------------------------------------

def norm(s: str) -> str:
    """lowercase, alphanumeric only — for robust matching."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def name_matches(a: str, b: str) -> bool:
    """Fuzzy match: 'Skeleton Knight in Another World' ~ 'skeleton knight'."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 5 and shorter in longer:
        return True
    stop = {"season", "the", "part", "tv", "nd", "rd", "st", "th"}
    ta = {w for w in re.split(r"[^a-z0-9]+", a.lower()) if w and w not in stop}
    tb = {w for w in re.split(r"[^a-z0-9]+", b.lower()) if w and w not in stop}
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= 0.6


def name_in_text(show: str, text_lower: str) -> bool:
    """True if the show name appears in the (lowercased) text."""
    n = norm(show)
    if len(n) >= 5 and n in re.sub(r"[^a-z0-9]+", "", text_lower):
        return True
    words = [w for w in re.split(r"[^a-z0-9]+", show.lower()) if len(w) > 2]
    if not words:
        return False
    hits = sum(1 for w in words if w in text_lower)
    return hits / len(words) >= 0.6


# ---------------------------------------------------------------------------
# Live schedule → "is this show releasing TODAY?" (pure live inference)
# ---------------------------------------------------------------------------

def _slot_today(day_label: str, time_str: str, now: datetime) -> datetime | None:
    """Today's slot time for a show, e.g. ('Saturday', '07:00 PM') → today 19:00."""
    label = (day_label or "").strip().lower()
    if label == "daily":
        pass                                   # airs every day
    elif label in WEEKDAY_NAMES:
        if WEEKDAY_NAMES[label] != now.weekday():
            return None                        # airs another weekday
    else:
        return None
    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p").time()
    except ValueError:
        return None
    return datetime.combine(now.date(), t, tzinfo=IST)


def resolve_today(show, now: datetime):
    """Decide if a live-schedule show has an episode TODAY.

    Returns (episode, when) or None.

    Case 1 — the page's listed episode drops today (normal).
    Case 2 — weekly show whose listed episode is exactly NEXT week → the site
             has already rolled over → today's episode was (ep-1) at today's slot.
             (Works both before and after the slot: 'tonight at 7 PM' or
             'already released at 7 PM'.)
    Case 3 — daily show whose listed episode is tomorrow → today's episode
             was (ep-1) at today's slot.
    """
    # Case 1: next listed episode drops today
    if show.release.date() == now.date():
        ep = show.episode if show.episode is not None else 1   # premiere → E1
        return ep, show.release

    if not isinstance(show.episode, int) or show.episode < 2:
        return None  # can't infer a previous episode (premiere/range)

    slot = _slot_today(show.day, show.time_str, now)
    if slot is None:
        return None

    if (show.day or "").strip().lower() == "daily":
        # Case 3: daily show, page already rolled to tomorrow
        if (now + timedelta(days=1)).date() == show.release.date():
            return show.episode - 1, slot
        return None

    # Case 2: weekly show, page rolled to exactly next week
    gap_days = (show.release - slot).total_seconds() / 86400
    if 6.5 <= gap_days <= 7.5:
        return show.episode - 1, slot
    return None


# ---------------------------------------------------------------------------
# Optional config overrides (schedule_config.DUB_SCHEDULE is empty by default)
# ---------------------------------------------------------------------------

def _resolve_episode(cfg: dict, today: datetime) -> tuple[int | None, bool]:
    ep_cfg = cfg.get("episode")
    if not ep_cfg:
        return None, True
    if "fixed" in ep_cfg:
        return int(ep_cfg["fixed"]), bool(cfg.get("expected", False))
    start_ep = int(ep_cfg["start"])
    start_date = datetime.strptime(ep_cfg["date"], "%Y-%m-%d").date()
    days = (today.date() - start_date).days
    if days < 0:
        return None, True
    if cfg.get("daily"):
        ep = start_ep + days
    elif "weekly_day" in cfg:
        target = WEEKDAYS[cfg["weekly_day"]]
        gap = (today.weekday() - target) % 7
        ep = start_ep + (days - gap) // 7
    else:
        ep = start_ep + days
    if ep <= 0:
        return None, True
    return ep, bool(cfg.get("expected", False))


def activate_curated(cfg: dict, now: datetime) -> Release | None:
    """Turn one optional schedule_config entry into a Release for TODAY."""
    today = now.date()
    if "from" in cfg and today < datetime.strptime(cfg["from"], "%Y-%m-%d").date():
        return None
    if "until" in cfg and today > datetime.strptime(cfg["until"], "%Y-%m-%d").date():
        return None
    if cfg.get("weekly_day") and now.weekday() != WEEKDAYS[cfg["weekly_day"]]:
        return None

    episode, expected = _resolve_episode(cfg, now)
    if episode is None and "weekly_day" in cfg:
        return None

    r = Release(
        name=cfg["name"], platform=cfg["platform"],
        langs=list(cfg.get("langs", [])), season=cfg.get("season"),
        episode=episode, episode_expected=expected,
        time_note=cfg.get("note", ""), sources=["schedule_config"],
    )
    if "lang_times" in cfg:
        for lang, hhmm in cfg["lang_times"].items():
            h, m = map(int, hhmm.split(":"))
            dt = datetime.combine(today, dtime(h, m), tzinfo=IST)
            r.lang_times[lang] = fmt_time(dt)
            r.all_times.append(dt)
            r.add_lang(lang)
        if len(r.lang_times) == 1:
            r.time_dt = r.all_times[0]
    elif "time" in cfg:
        h, m = map(int, cfg["time"].split(":"))
        r.time_dt = datetime.combine(today, dtime(h, m), tzinfo=IST)
        r.all_times.append(r.time_dt)
    return r


# ---------------------------------------------------------------------------
# Live platform detection (no hardcoded platform list)
# ---------------------------------------------------------------------------

def detect_platform(name: str, muse_videos, crunchy_items, asched_items, news_items) -> str:
    """Which platform is this show on? — inferred from live data only."""
    # 1. the show appears in Muse India's recent uploads → Muse India (YouTube)
    for v in muse_videos:
        if v.show and name_matches(name, v.show):
            return "Muse India (YouTube)"
    # 2. the show appears in Crunchyroll's feed → Crunchyroll
    for c in crunchy_items:
        if name_matches(name, c.show):
            return "Crunchyroll"
    # 3. AnimeSchedule lists its streaming platforms (optional token)
    for a in asched_items:
        if a.platforms and name_matches(name, a.show):
            return a.platforms[0]
    # 4. a news article mentions the show together with a platform
    for n in news_items:
        title = (n.title or "").lower()
        if name_in_text(name, title):
            for kw, platform in PLATFORM_BY_KEYWORD.items():
                if kw in title:
                    return platform
    return "Streaming"


# ---------------------------------------------------------------------------
# The main build
# ---------------------------------------------------------------------------

async def build_releases(now: datetime, evening: bool = False):
    """Returns (entries, source_report) for this moment — fully live."""
    from sources import fetch_all  # local import to avoid circulars at module load

    report: dict[str, SourceResult] = await fetch_all()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

    muse = report["muse"]
    crunchy = report["crunchyroll"]
    dub_sched = report["dub_schedule"]
    news = report["news"]
    airing_src = (report["animeschedule"] if report["animeschedule"].ok
                  and report["animeschedule"].items else report["livechart"])

    entries: list[Release] = []
    aliases: list[tuple[str, str]] = []

    def find_match(show: str) -> Release | None:
        for r in entries:
            if name_matches(r.name, show):
                return r
        for alias, target in aliases:
            if name_matches(alias, show) or norm(alias) in norm(show):
                for r in entries:
                    if r.name == target:
                        return r
        return None

    # ---- A) LIVE schedule page (the backbone) -----------------------------
    if dub_sched.ok:
        added = 0
        for s in dub_sched.items:
            resolved = resolve_today(s, now)
            if resolved is None:
                continue
            if not s.langs:
                dub_sched.note(f"skipped (no Hindi/Telugu/Tamil): {s.name[:50]}")
                continue
            if any(name_matches(ig, s.name) or norm(ig) in norm(s.name) for ig in IGNORE_SHOWS):
                dub_sched.note(f"ignored (IGNORE_SHOWS): {s.name[:50]}")
                continue
            ep, when = resolved
            r = Release(
                name=s.name,
                platform="Streaming",           # resolved live later
                langs=s.langs,
                season=s.season,
                episode=ep,
                episode_expected=False,
                time_dt=when,
                sources=["dub_schedule"],
            )
            r.all_times.append(when)
            entries.append(r)
            added += 1
        dub_sched.note(f"{added} show(s) with an episode today")

    # ---- B) optional config overrides (empty by default) ------------------
    for cfg in DUB_SCHEDULE:
        r_cfg = activate_curated(cfg, now)
        if r_cfg is None:
            continue
        for a in cfg.get("aliases", []):
            aliases.append((a, cfg["name"]))
        existing = find_match(r_cfg.name)
        if existing is not None:
            # config wins over live data for this show
            existing.name = r_cfg.name
            existing.platform = r_cfg.platform
            existing.langs = r_cfg.langs or existing.langs
            existing.season = r_cfg.season
            existing.episode = r_cfg.episode if r_cfg.episode is not None else existing.episode
            existing.episode_expected = r_cfg.episode_expected
            existing.time_dt = r_cfg.time_dt
            existing.lang_times = r_cfg.lang_times
            existing.time_note = r_cfg.time_note
            existing.all_times = r_cfg.all_times or existing.all_times
            existing.add_source("schedule_config")
        else:
            entries.append(r_cfg)

    # ---- C) Muse India uploads today (strongest live confirmation) --------
    if muse.ok:
        for v in muse.items:
            if v.published < today0:
                continue
            if not v.langs:
                muse.note(f"skipped (no Hindi/Telugu/Tamil tag): {v.title[:60]}")
                continue
            r = find_match(v.show)
            if r is None:
                r = Release(
                    name=v.show or v.title, platform="Muse India (YouTube)",
                    season=v.season, episode=v.episode, episode_expected=False,
                    sources=["muse_rss"], confirmed=True,
                )
                r.all_times.append(v.published)
                entries.append(r)
            r.confirmed = True
            r.add_source("muse_rss")
            r.platform = "Muse India (YouTube)"
            if v.episode:
                r.episode = v.episode
                r.episode_expected = False
            if r.season is None:
                r.season = v.season
            for lang in v.langs:
                r.add_lang(lang)
                r.lang_times[lang] = fmt_time(v.published)
            if r.time_dt is None:
                r.time_dt = v.published
            if not r.all_times:
                r.all_times.append(v.published)
        muse.note(f"{sum(1 for v in muse.items if v.published >= today0)} uploads today")

    # ---- D) Crunchyroll Indian-dub drops today -----------------------------
    if crunchy.ok:
        for v in crunchy.items:
            if v.published < today0:
                continue
            r = find_match(v.show)
            if r is None:
                r = Release(
                    name=v.show, platform="Crunchyroll", langs=[v.lang],
                    episode=v.episode, episode_expected=False,
                    time_dt=v.published, sources=["crunchyroll_rss"], confirmed=True,
                )
                r.all_times.append(v.published)
                entries.append(r)
            else:
                r.confirmed = True
                r.add_source("crunchyroll_rss")
                r.add_lang(v.lang)
                if v.episode:
                    r.episode = v.episode
                    r.episode_expected = False
                if not r.all_times:
                    r.all_times.append(v.published)

    # ---- E) LiveChart / AnimeSchedule cross-check --------------------------
    airing_today: list[AiredEpisode] = []
    if airing_src.ok:
        for a in airing_src.items:
            if a.when.date() == now.date():
                airing_today.append(a)
        for a in airing_today:
            r = find_match(a.show)
            if r is not None and not r.confirmed:
                if r.episode is None and a.episode:
                    r.episode = a.episode
                    r.episode_expected = True
                r.add_source(a.source)

    # ---- F) News: catch shows missed by the schedule page ------------------
    if news.ok:
        for a in airing_today:
            if find_match(a.show) is not None:
                continue
            blob = " ".join((i.title + " " + i.source).lower() for i in news.items)
            if not name_in_text(a.show, blob):
                continue
            langs = [l.capitalize() for l in ("hindi", "tamil", "telugu") if l in blob]
            if not langs:
                continue
            platform = next(
                (p for kw, p in PLATFORM_BY_KEYWORD.items() if kw in blob), "Streaming"
            )
            r = Release(
                name=a.show, platform=platform, langs=langs,
                episode=a.episode, episode_expected=True,
                sources=["airing+" + a.source, "google_news"],
            )
            entries.append(r)

    # ---- G) live platform resolution for still-unknown platforms -----------
    # 1st pass: cheap detection from data we already fetched
    for r in entries:
        if r.platform == "Streaming":
            r.platform = detect_platform(
                r.name,
                muse.items if muse.ok else [],
                crunchy.items if crunchy.ok else [],
                airing_src.items if (airing_src.ok and airing_src.name.startswith("AnimeSchedule")) else [],
                news.items if news.ok else [],
            )

    # 2nd pass: per-show live Google News lookup (e.g. "Daemons of the Shadow
    # Realm release schedule on Crunchyroll" → Crunchyroll). Only for shows
    # that are still unknown, capped so a big day can't slow the run down.
    still_unknown = [r for r in entries if r.platform == "Streaming"][:10]
    if still_unknown:
        from sources import new_client, news_platform_for
        async with new_client() as client:
            for r in still_unknown:
                platform = await news_platform_for(client, r.name)
                if platform:
                    r.platform = platform
                    r.add_source("news_platform")

    # last resort: optional manual hints (empty by default)
    if PLATFORM_HINTS:
        for r in entries:
            if r.platform == "Streaming":
                for key, platform in PLATFORM_HINTS.items():
                    if name_matches(key, r.name) or norm(key) in norm(r.name):
                        r.platform = platform
                        break

    # ---- H) evening filter: only the rest of the day ------------------------
    if evening:
        cutoff = now.replace(hour=EVENING_CUTOFF_HOUR, minute=0, second=0, microsecond=0)
        entries = [
            r for r in entries
            if not r.all_times or any(t >= cutoff for t in r.all_times)
        ]

    entries.sort(key=Release.sort_key)
    return entries, report
