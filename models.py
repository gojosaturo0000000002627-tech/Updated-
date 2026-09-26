"""
models.py — Shared data models used across the project.
"""

from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# Raw items coming from live sources
# ---------------------------------------------------------------------------

@dataclass
class MuseVideo:
    """A recent video uploaded to a Muse India YouTube channel."""
    title: str                 # raw YouTube title
    link: str
    published: datetime        # tz-aware (IST) upload time
    channel: str = "Muse India"
    show: str = ""             # parsed show name (best effort)
    episode: int | None = None
    season: int | None = None
    langs: list[str] = field(default_factory=list)   # e.g. ["Hindi", "Telugu"]


@dataclass
class CrunchyVideo:
    """A dubbed episode item from Crunchyroll's public video RSS feed."""
    show: str
    episode: int | None
    lang: str                  # "Hindi" / "Tamil" / "Telugu"
    link: str
    published: datetime        # tz-aware (IST)


@dataclass
class AiredEpisode:
    """An episode that aired/airs today (LiveChart feed / AnimeSchedule API)."""
    show: str
    episode: int | None
    when: datetime             # tz-aware global airing time
    source: str = "livechart"
    platforms: list[str] = field(default_factory=list)   # streaming platforms (AnimeSchedule)


@dataclass
class ScheduleShow:
    """A show card from the Indian anime-dub schedule page (animedubhindi.link).

    `release` is the EXACT next-episode drop time (from the page's
    data-release attribute) — if it falls on today, the show releases today.
    """
    name: str
    season: int | None
    episode: int | str | None   # 25  or  "34-36" (multi-episode drop)
    langs: list[str]            # only Indian dub langs (Hindi/Tamil/Telugu)
    day: str                    # "Daily" / "Monday" / ...
    time_str: str               # "09:45 PM"
    release: datetime           # tz-aware IST drop time of `episode`


@dataclass
class NewsItem:
    """A news article from Google News RSS."""
    title: str
    link: str
    source: str = ""           # publisher name
    published: datetime | None = None


# ---------------------------------------------------------------------------
# The final merged release entry that gets rendered into the message
# ---------------------------------------------------------------------------

@dataclass
class Release:
    """One anime entry shown inside the daily update message."""
    name: str
    platform: str = "Streaming"
    langs: list[str] = field(default_factory=list)      # ["Hindi", "Tamil", "Telugu"]
    season: int | None = None
    episode: int | str | None = None                    # 25 or "34-36"
    episode_expected: bool = True                       # True → "S03E3 Expected"
    time_dt: datetime | None = None                     # single known IST release time
    lang_times: dict[str, str] = field(default_factory=dict)  # "Tamil" -> "09:30 PM"
    time_note: str = ""                                 # e.g. "(Daily)"
    all_times: list[datetime] = field(default_factory=list)   # for evening filtering
    sources: list[str] = field(default_factory=list)    # provenance for /test
    confirmed: bool = False                             # an actual upload confirms it

    def add_source(self, tag: str) -> None:
        if tag not in self.sources:
            self.sources.append(tag)

    def add_lang(self, lang: str) -> None:
        if lang and lang not in self.langs:
            self.langs.append(lang)

    def sort_key(self):
        """Sort entries by their earliest known time (unknown last, then name)."""
        t = self.time_dt
        if self.lang_times and self.all_times:
            t = min(self.all_times)
        return (t.timestamp() if t else float("inf"), self.name.lower())


# ---------------------------------------------------------------------------
# Per-source fetch result (for the /test command)
# ---------------------------------------------------------------------------

@dataclass
class SourceResult:
    name: str
    ok: bool = False
    error: str = ""
    items: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        if text not in self.notes and len(self.notes) < 20:
            self.notes.append(text)
