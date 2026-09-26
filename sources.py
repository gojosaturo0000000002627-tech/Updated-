"""
sources.py — Live source fetchers.

Every fetcher returns a SourceResult (ok / error / items) so one broken
source NEVER stops the whole update. Timeout is 10 seconds per request.

Sources:
  1. Muse India YouTube RSS      → actual dub uploads (strongest evidence)
  2. Crunchyroll video RSS       → Hindi/Tamil/Telugu dub episode drops
  3. LiveChart episodes RSS      → which shows air today (global timetable)
  4. AnimeSchedule API v3        → same, optional (needs free account token)
  5. Google News RSS (many queries) → announcements & fallback safety net
"""

import asyncio
import html as html_lib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from config import ANIMESCHEDULE_TOKEN, IST, MUSE_CHANNEL_IDS, SOURCE_TIMEOUT
from models import (AiredEpisode, CrunchyVideo, MuseVideo, NewsItem, ScheduleShow,
                    SourceResult)

log = logging.getLogger("sources")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Indian dub languages we care about (everything else is ignored)
DUB_LANGS = ("hindi", "tamil", "telugu")


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=SOURCE_TIMEOUT,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    )


async def safe_fetch(name: str, coro) -> SourceResult:
    """Run a fetcher; convert any crash into a failed SourceResult."""
    try:
        return await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — one source failing must not kill the rest
        log.warning("source '%s' failed: %s", name, exc)
        return SourceResult(name=name, ok=False, error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 1) Muse India YouTube — RSS feed per channel
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone(IST)


def parse_muse_title(title: str) -> tuple[str, int | None, int | None, list[str]]:
    """Best-effort parse of a Muse India video title.

    Returns (show_name, episode, season, languages).
    Typical titles look like:
      "Skeleton Knight in Another World Episode 12 [Hindi Dub]"
      "【Tamil】Iruma-kun! S02 E10"
      "Re:ZERO Season 3 | EP 5 | Telugu Dub"
    """
    t = html_lib.unescape(title).strip()

    # languages are detected on the FULL title (incl. a leading 【Tamil】 tag)
    langs = [l.capitalize() for l in DUB_LANGS if re.search(rf"\b{l}\b", t, re.I)]

    # drop a leading 【...】 tag (usually the language label)
    t = re.sub(r"^【[^】]{1,25}】\s*", "", t)

    ep_match = (
        re.search(r"\b(?:episode|eps?\.?|ep)\s*[-:.]?\s*(\d{1,4})", t, re.I)
        or re.search(r"\bS\d{1,2}\s*[-:]?\s*E(\d{1,4})\b", t, re.I)
        or re.search(r"\bE(\d{1,4})\b", t)
        or re.search(r"#(\d{1,4})\b", t)
    )
    episode = int(ep_match.group(1)) if ep_match else None

    season_match = re.search(r"\bS(\d{1,2})\b", t) or re.search(r"season\s*(\d{1,2})", t, re.I)
    season = int(season_match.group(1)) if season_match else None

    # Show name = everything BEFORE the episode/language markers, minus brackets
    positions = []
    if ep_match:
        positions.append(ep_match.start())
    lang_match = re.search(r"(?i)\b(hindi|telugu|tamil)\b", t)
    if lang_match:
        positions.append(lang_match.start())
    cut = min(positions) if positions else len(t)

    name = t[:cut]
    name = re.sub(r"【[^】]*】|\[[^\]]*\]|\([^)]*\)", " ", name)   # strip [..] (..) 【..】
    name = re.sub(r"[【】\[\]{}「」『』]", " ", name)               # stray brackets
    # strip trailing junk words/separators one by one (incl. "Season 2", "S02")
    junk = re.compile(
        r"(?i)\s*[-–|:,.~]*\s*"
        r"(official|dub|dubbed|sub|audio|new|episode|eps?|part|season\s*\d{1,2}|\bs\d{1,2}\b)"
        r"\s*[-–|:,.~]*\s*$"
    )
    while True:
        cleaned = junk.sub("", name.rstrip()).rstrip(" -–|:,.~")
        if cleaned == name:
            break
        name = cleaned
    name = re.sub(r"\s{2,}", " ", name).strip(" -–|:,.")
    if not name:
        name = re.sub(r"【[^】]*】|\[[^\]]*\]|\([^)]*\)", " ", t)
        name = re.sub(r"\s{2,}", " ", name).strip() or t
    return name, episode, season, langs


async def fetch_muse(client: httpx.AsyncClient) -> SourceResult:
    """Latest uploads from every configured Muse channel.

    Primary: the channel's RSS feed (works from normal servers/cloud IPs).
    Fallback: if the RSS endpoint is unreachable (some networks block it),
    scrape the /videos page HTML instead and parse ytInitialData.
    """
    result = SourceResult(name="Muse India YouTube (RSS)")
    videos: list[MuseVideo] = []
    for channel_id in MUSE_CHANNEL_IDS:
        feed_entries = []
        used_fallback = False
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            resp = await client.get(url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.get("bozo") and not feed.entries:
                raise ValueError(f"feed parse error: {feed.get('bozo_exception')}")
            feed_entries = feed.entries
        except Exception as exc:  # noqa: BLE001 — try the HTML fallback
            log.info("muse RSS failed for %s (%s) — trying channel page", channel_id, exc)
            feed_entries = await _scrape_channel_videos(client, channel_id)
            used_fallback = True
            if feed_entries:
                result.note(f"channel {channel_id}: RSS blocked, page-scrape fallback used")

        for e in feed_entries:
            try:
                if used_fallback:
                    pub = e["_published_dt"]          # pre-computed by scraper
                    title, link = e["title"], e.get("link", "")
                else:
                    pub = _parse_iso(e.get("published", e.get("updated", "")))
                    title, link = e.get("title", ""), e.get("link", "")
            except Exception:  # noqa: BLE001
                continue
            show, ep, season, langs = parse_muse_title(title)
            videos.append(
                MuseVideo(
                    title=title,
                    link=link,
                    published=pub,
                    show=show,
                    episode=ep,
                    season=season,
                    langs=langs,
                )
            )
        result.note(
            f"channel {channel_id}: {len(feed_entries)} recent videos"
            + (" (page scrape)" if used_fallback else "")
        )
    result.items = videos
    result.ok = True
    return result


# ---------------------------------------------------------------------------
# 1b) Fallback: scrape the channel's /videos page (ytInitialData)
# ---------------------------------------------------------------------------

_REL_TIME = re.compile(
    r"(?i)(streamed|premiered)?\s*(?P<n>\d+)\s*(?P<unit>second|minute|hour|day|week)s?\s+ago"
)


def _relative_to_datetime(text: str, now: datetime) -> datetime | None:
    """'3 hours ago' → now - 3h (tz-aware IST)."""
    m = _REL_TIME.search(text or "")
    if not m:
        return None
    n = int(m.group("n"))
    unit = m.group("unit").lower()
    if unit == "second":
        delta = timedelta(seconds=n)
    elif unit == "minute":
        delta = timedelta(minutes=n)
    elif unit == "hour":
        delta = timedelta(hours=n)
    elif unit == "day":
        delta = timedelta(days=n)
    else:
        delta = timedelta(weeks=n)
    return now - delta


async def _scrape_channel_videos(client: httpx.AsyncClient, channel_id: str) -> list[dict]:
    """Defensive scrape of youtube.com/channel/<id>/videos — returns feed-like dicts.
    Any problem → empty list (never raises)."""
    try:
        resp = await client.get(f"https://www.youtube.com/channel/{channel_id}/videos")
        resp.raise_for_status()
        m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", resp.text, re.S)
        if not m:
            return []
        data = json.loads(m.group(1))
        out: list[dict] = []
        now = datetime.now(IST)

        def walk(obj):
            if isinstance(obj, dict):
                vr = obj.get("videoRenderer")
                if isinstance(vr, dict):
                    title = "".join(
                        r.get("text", "") for r in vr.get("title", {}).get("runs", [])
                    ) or vr.get("title", {}).get("simpleText", "")
                    pub_text = vr.get("publishedTimeText", {}).get("simpleText", "")
                    pub_dt = _relative_to_datetime(pub_text, now)
                    if title and pub_dt is not None:
                        out.append(
                            {
                                "title": title,
                                "link": "https://www.youtube.com/watch?v=" + vr.get("videoId", ""),
                                "_published_dt": pub_dt,
                            }
                        )
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(data)
        return out
    except Exception as exc:  # noqa: BLE001
        log.info("channel page scrape failed for %s: %s", channel_id, exc)
        return []


# ---------------------------------------------------------------------------
# 2) Crunchyroll — public video RSS (dub drops appear as "(Hindi Dub)")
# ---------------------------------------------------------------------------

CRUNCHY_TITLE = re.compile(r"^(?P<show>.+?)\s*\((?P<lang>[A-Za-z ]+?)\s+Dub\)\s*-\s*Episode\s+(?P<ep>\d+)")


async def fetch_crunchyroll(client: httpx.AsyncClient) -> SourceResult:
    result = SourceResult(name="Crunchyroll (video RSS)")
    resp = await client.get("https://www.crunchyroll.com/rss/news")
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items: list[CrunchyVideo] = []
    for e in feed.entries:
        title = html_lib.unescape(e.get("title", ""))
        m = CRUNCHY_TITLE.match(title)
        if not m:
            continue
        lang = m.group("lang").strip().lower()
        if lang not in DUB_LANGS:
            continue  # English/Polish/Thai/... dubs are irrelevant
        try:
            pub = datetime.fromtimestamp(
                _struct_to_unix(e.get("published_parsed")), tz=timezone.utc
            ).astimezone(IST)
        except Exception:  # noqa: BLE001
            pub = datetime.now(IST)
        items.append(
            CrunchyVideo(
                show=m.group("show").strip(),
                episode=int(m.group("ep")),
                lang=lang.capitalize(),
                link=e.get("link", ""),
                published=pub,
            )
        )
    result.items = items
    result.ok = True
    result.note(f"{len(items)} Indian-dub items (of {len(feed.entries)} total in feed)")
    return result


def _struct_to_unix(st) -> float:
    import calendar
    return calendar.timegm(st)


# ---------------------------------------------------------------------------
# 3) LiveChart — recent episodes RSS (what aired today, globally)
# ---------------------------------------------------------------------------

LIVECHART_TITLE = re.compile(r"^(?P<show>.+?)\s*#(?P<ep>\d+)$")


async def fetch_livechart(client: httpx.AsyncClient) -> SourceResult:
    result = SourceResult(name="LiveChart (episodes RSS)")
    resp = await client.get("https://www.livechart.me/feeds/episodes")
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items: list[AiredEpisode] = []
    for e in feed.entries:
        title = html_lib.unescape(e.get("title", "")).strip()
        m = LIVECHART_TITLE.match(title)
        if not m:
            continue
        try:
            when = datetime.fromtimestamp(
                _struct_to_unix(e.get("published_parsed")), tz=timezone.utc
            ).astimezone(IST)
        except Exception:  # noqa: BLE001
            continue
        items.append(
            AiredEpisode(show=m.group("show").strip(), episode=int(m.group("ep")), when=when)
        )
    result.items = items
    result.ok = True
    return result


# ---------------------------------------------------------------------------
# 4) AnimeSchedule — API v3 (OPTIONAL, needs a free account + app token)
#    https://animeschedule.net → account settings → API tab
# ---------------------------------------------------------------------------

async def fetch_animeschedule(client: httpx.AsyncClient) -> SourceResult:
    result = SourceResult(name="AnimeSchedule (API v3)")
    if not ANIMESCHEDULE_TOKEN:
        result.note("skipped (no ANIMESCHEDULE_TOKEN set — using LiveChart instead)")
        result.ok = True
        return result

    now = datetime.now(IST)
    year, week, _ = now.isocalendar()
    url = (
        "https://animeschedule.net/api/v3/timetables/sub"
        f"?year={year}&week={week}&tz=Asia%2FKolkata"
    )
    resp = await client.get(
        url, headers={"Authorization": f"Bearer {ANIMESCHEDULE_TOKEN}"}
    )
    resp.raise_for_status()
    data = resp.json()

    items: list[AiredEpisode] = []
    today = now.date()
    for entry in data if isinstance(data, list) else []:
        try:
            when = _parse_iso(entry["episodeDate"])
            if when.date() != today:
                continue
            show = entry.get("english") or entry.get("title") or entry.get("romaji") or ""
            if not show:
                continue
            # streaming platforms (used for live platform detection)
            platforms = []
            for stream in entry.get("streams") or []:
                plat = (stream.get("platform") or "").lower()
                label = (stream.get("name") or "")
                if "muse" in plat or "muse" in label.lower():
                    mapped = "Muse India (YouTube)"
                else:
                    mapped = {
                        "crunchyroll": "Crunchyroll", "netflix": "Netflix",
                        "amazon": "Prime Video", "disney": "JioHotstar",
                        "hulu": "JioHotstar",
                    }.get(plat, "")
                if mapped and mapped not in platforms:
                    platforms.append(mapped)
            items.append(
                AiredEpisode(
                    show=show,
                    episode=entry.get("episodeNumber"),
                    when=when,
                    source="animeschedule",
                    platforms=platforms,
                )
            )
        except Exception:  # noqa: BLE001 — defensive: schema may vary
            continue
    result.items = items
    result.ok = True
    return result


# ---------------------------------------------------------------------------
# 5) Indian anime-dub schedule page (animedubhindi.link/schedule.php)
#    → the FULL live lineup: every ongoing show + upcoming premieres with
#      day, time, next episode and an exact data-release drop timestamp.
#    New shows appear here automatically; finished shows disappear — so the
#    bot never needs a hardcoded list. A same-day cache is kept in data/ as
#    a backup when the site is flaky (it sometimes returns Cloudflare 525).
# ---------------------------------------------------------------------------

DUB_SCHEDULE_URL = "https://www.animedubhindi.link/schedule.php"


def _parse_ep_text(txt: str) -> int | str | None:
    """'EP 25' → 25,  'EP 34-36' → '34-36',  'Coming Soon' → None."""
    m = re.search(r"(\d+(?:\s*-\s*\d+)?)", txt or "")
    if not m:
        return None
    raw = m.group(1).replace(" ", "")
    return raw if "-" in raw else int(raw)


def _parse_season_text(txt: str) -> int | None:
    m = re.search(r"\d+", txt or "")
    return int(m.group(0)) if m else None


def _schedule_cache_path():
    from config import DATA_DIR
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR / "schedule_cache.json"


def _save_schedule_cache(items: list[ScheduleShow]) -> None:
    try:
        payload = {
            "date": datetime.now(IST).strftime("%Y-%m-%d"),
            "items": [
                {
                    "name": i.name, "season": i.season, "episode": i.episode,
                    "langs": i.langs, "day": i.day, "time_str": i.time_str,
                    "release": i.release.isoformat(),
                }
                for i in items
            ],
        }
        _schedule_cache_path().write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not save schedule cache: %s", exc)


def _load_schedule_cache() -> list[ScheduleShow] | None:
    """Today's cached schedule (None if missing / from another day)."""
    try:
        payload = json.loads(_schedule_cache_path().read_text(encoding="utf-8"))
        if payload.get("date") != datetime.now(IST).strftime("%Y-%m-%d"):
            return None
        return [
            ScheduleShow(
                name=i["name"], season=i["season"], episode=i["episode"],
                langs=i["langs"], day=i["day"], time_str=i["time_str"],
                release=datetime.fromisoformat(i["release"]),
            )
            for i in payload.get("items", [])
        ]
    except Exception:  # noqa: BLE001
        return None


def _parse_schedule_cards(container, list_id: str) -> list[ScheduleShow]:
    items: list[ScheduleShow] = []
    if container is None:
        return items
    for card in container.find_all("div", class_="card"):
        h2 = card.find("h2")
        if h2 is None:
            continue
        name = h2.get_text(strip=True)

        meta = [m.get_text(strip=True) for m in card.find_all("div", class_="meta-box")]
        season = _parse_season_text(meta[0]) if meta else None
        episode = _parse_ep_text(meta[1]) if len(meta) > 1 else None  # None = Coming Soon

        lang_div = card.find("div", class_="lang")
        langs = []
        if lang_div is not None:
            for span in lang_div.find_all("span"):
                lang = span.get_text(strip=True).lower()
                if lang in DUB_LANGS:
                    langs.append(lang.capitalize())

        day_blocks = card.find_all("div", class_="date-block")
        day = day_blocks[0].get_text(strip=True) if day_blocks else ""
        tblock = card.find("div", class_="time-block")
        time_str = tblock.get_text(strip=True) if tblock else ""

        cd = card.find("div", class_="countdown")
        release_attr = cd.get("data-release", "") if cd else ""
        try:
            release = datetime.fromisoformat(release_attr).astimezone(IST)
        except ValueError:
            continue  # no valid drop time (e.g. "Date Not Announced")

        items.append(
            ScheduleShow(
                name=name, season=season, episode=episode, langs=langs,
                day=day, time_str=time_str, release=release,
            )
        )
    return items


async def fetch_dub_schedule(client: httpx.AsyncClient) -> SourceResult:
    result = SourceResult(name="Anime Dub Schedule (animedubhindi.link)")
    # The site sits behind Cloudflare and intermittently returns 525 — retry.
    last_error: Exception | None = None
    resp = None
    for attempt in range(3):
        try:
            resp = await client.get(
                DUB_SCHEDULE_URL,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            if resp.status_code == 200 and len(resp.content) > 20000:
                break  # full page received
            last_error = ValueError(
                f"attempt {attempt + 1}: HTTP {resp.status_code}, {len(resp.content)} bytes"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        resp = None
        await asyncio.sleep(1.5)

    items: list[ScheduleShow] = []
    if resp is not None and resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        ongoing = _parse_schedule_cards(soup.find("div", id="ongoingList"), "ongoingList")
        upcoming = _parse_schedule_cards(soup.find("div", id="upcomingList"), "upcomingList")
        items = ongoing + upcoming
        if not items:
            last_error = last_error or ValueError("schedule page parsed 0 shows")
        else:
            result.note(f"{len(ongoing)} ongoing + {len(upcoming)} upcoming shows (live)")

    if not items:
        # site failed → fall back to today's cached copy so the day is covered
        cached = _load_schedule_cache()
        if cached:
            result.items = cached
            result.ok = True
            result.note(f"site unreachable — using today's cached schedule ({len(cached)} shows)")
            return result
        raise last_error or RuntimeError("schedule page unreachable")

    _save_schedule_cache(items)
    result.items = items
    result.ok = True
    return result


# ---------------------------------------------------------------------------
# 6) Google News RSS — announcements & fallback for anything missed
# ---------------------------------------------------------------------------

# platform keywords (in news headlines) → platform label shown in the message
PLATFORM_KEYWORDS = {
    "crunchyroll": "Crunchyroll",
    "netflix": "Netflix",
    "muse india": "Muse India (YouTube)",
    "jiohotstar": "JioHotstar",
    "hotstar": "JioHotstar",
    "prime video": "Prime Video",
    "amazon prime": "Prime Video",
    "anime times": "Anime Times",
    "anione": "Anione India (YouTube)",
}


def _title_mentions_show(title: str, show_name: str) -> bool:
    """Do the significant words of the show name appear in this headline?"""
    words = [w for w in re.split(r"[^a-z0-9]+", show_name.lower()) if len(w) > 3]
    if not words:
        return False
    hits = sum(1 for w in words if w in title.lower())
    return hits / len(words) >= 0.6


async def news_platform_for(client: httpx.AsyncClient, show_name: str) -> str | None:
    """Live platform lookup via Google News headlines.

    Tier 1: query '"<show>" hindi dub' — Google already ensures the article is
            about this show, so a single platform keyword in the headline counts
            (e.g. 'NETFLIX Summer 2026 Hindi, Tamil, Telugu Dub Anime Lineup' → Netflix).
    Tier 2: query '"<show>"' — stricter: the headline must itself mention the show
            (e.g. 'Bleach ... Now Streaming on JioHotstar With Brand New Hindi Dub').
    Headlines mentioning SEVERAL platforms are roundups → ignored.
    """
    for query, require_name in ((f'"{show_name}" hindi dub', False), (f'"{show_name}"', True)):
        url = (
            "https://news.google.com/rss/search?q="
            + httpx.QueryParams({"q": query}).get("q", query).replace(" ", "+")
            + "&hl=en-IN&gl=IN&ceid=IN:en"
        )
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for e in feed.entries:
                title = html_lib.unescape(e.get("title", ""))
                if require_name and not _title_mentions_show(title, show_name):
                    continue
                low = title.lower()
                found = list(dict.fromkeys(
                    p for kw, p in PLATFORM_KEYWORDS.items() if kw in low
                ))
                if len(found) == 1:
                    return found[0]
        except Exception as exc:  # noqa: BLE001
            log.info("platform news lookup failed for %s: %s", show_name, exc)
    return None

NEWS_QUERIES = [
    '"Hindi dub" anime episode',
    '"Muse India" episode',
    'anime "Tamil dub" release',
    'anime "Telugu dub" release',
    'Crunchyroll "Hindi dub"',
    'Netflix anime Hindi dub',
]


async def fetch_news(client: httpx.AsyncClient) -> SourceResult:
    result = SourceResult(name="Google News (RSS)")
    items: list[NewsItem] = []
    seen: set[str] = set()
    for q in NEWS_QUERIES:
        url = (
            "https://news.google.com/rss/search?q="
            + httpx.QueryParams({"q": q}).get("q", q).replace(" ", "+")
            + "&hl=en-IN&gl=IN&ceid=IN:en"
        )
        resp = await client.get(url)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for e in feed.entries:
            title = html_lib.unescape(e.get("title", "")).strip()
            if title in seen:
                continue
            seen.add(title)
            # Google News titles end with " - Publisher"
            source_name = ""
            if " - " in title:
                title, _, source_name = title.rpartition(" - ")
            published = None
            try:
                published = datetime.fromtimestamp(
                    _struct_to_unix(e.get("published_parsed")), tz=timezone.utc
                ).astimezone(IST)
            except Exception:  # noqa: BLE001
                pass
            items.append(NewsItem(title=title, link=e.get("link", ""), source=source_name, published=published))
    # keep only the last 7 days of news (used for platform detection and
    # cross-verification of shows airing TODAY — never adds stale releases)
    cutoff = datetime.now(IST) - timedelta(days=7)
    items = [i for i in items if i.published is None or i.published >= cutoff]
    result.items = items
    result.ok = True
    return result


# ---------------------------------------------------------------------------
# Fetch everything in parallel
# ---------------------------------------------------------------------------

async def fetch_all() -> dict[str, SourceResult]:
    async with new_client() as client:
        muse, crunchy, dub_sched, livechart, animesched, news = await asyncio.gather(
            safe_fetch("muse", fetch_muse(client)),
            safe_fetch("crunchyroll", fetch_crunchyroll(client)),
            safe_fetch("dub_schedule", fetch_dub_schedule(client)),
            safe_fetch("livechart", fetch_livechart(client)),
            safe_fetch("animeschedule", fetch_animeschedule(client)),
            safe_fetch("news", fetch_news(client)),
        )
    return {
        "muse": muse,
        "crunchyroll": crunchy,
        "dub_schedule": dub_sched,
        "livechart": livechart,
        "animeschedule": animesched,
        "news": news,
    }
