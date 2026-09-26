"""
template.py — The EXACT message format.

⚠️ This is the only file you need to touch to change how the message LOOKS.
All the unicode decorations (⟣ ⟢ ⫷ ⫸ ┃ ╰ ━ ─ etc.) are copied from the
original design, so the output looks identical to the sample.

Editable knobs (top of the file):
  BRAND        – channel/brand name shown in the first line
  POWERED_BY   – the @handle in the footer
  Platform emojis, header rule length, etc.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from models import Release

IST = ZoneInfo("Asia/Kolkata")

# ===========================================================================
# ✏️ EDIT ME — quick customization
# ===========================================================================
BRAND = "FAIRY WORLD"                    # shown as: 💫 [ANIME HINDI UPDATE] – FAIRY WORLD ⚡
POWERED_BY = "@dc_hmm"                   # footer credit handle
SHOW_POWERED_BY = True                   # False → the 💠 Powered By line is removed
SUB_LINE = "  『 Anime Release Guide | Hindi, Tamil, Telugu Dub 』"

# Platform → emoji (add your own here)
PLATFORM_EMOJI = {
    "Crunchyroll": "🟠",
    "Netflix": "🔴",
    "Muse India (YouTube)": "▶️",
    "Anione India (YouTube)": "▶️",
    "Prime Video": "🔵",
    "Amazon Prime Video": "🔵",
    "JioHotstar": "🟣",
    "Hotstar": "🟣",
    "Anime Times": "🎬",
    "BookMyShow": "🎟️",
    "Streaming": "📺",
}
DEFAULT_PLATFORM_EMOJI = "📺"

# How many entries go into the photo caption before the rest moves to
# a follow-up text message (caption limit is 1024 — handled automatically).
# ===========================================================================


# ---------------------------------------------------------------------------
# Fixed decoration strings (byte-exact from the original design)
# ---------------------------------------------------------------------------
def _title_line() -> str:
    return f"💫 [ANIME HINDI UPDATE] – {BRAND} ⚡"

RULE_TOP = "⟣" + "━" * 17 + "⟢"        # header separator
RULE_BOTTOM = "━" * 19                  # footer separator
BLOCK_END = "╰" + "─" * 19              # end of each anime block

# Footer — copied EXACTLY (special unicode bold/double-struck letters)
FOOTER_TITLE = "🔔 𝗗𝗮𝗶𝗹𝘆 𝗔𝗻𝗶𝗺𝗲 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 | 𝗡𝗲𝘄 𝗘𝗽𝗶𝘀𝗼𝗱𝗲𝘀 | 𝗔𝗻𝗶𝗺𝗲 𝗡𝗲𝘄𝘀"
FOOTER_JOIN = "❗ 𝕁𝕠𝕚𝕟 ℕ𝕠𝕨 ➤"


def _ordinal(n: int) -> str:
    """1 → 1st, 2 → 2nd, 3 → 3rd, 4 → 4th, 21 → 21st ..."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return {1: f"{n}st", 2: f"{n}nd", 3: f"{n}rd"}.get(n % 10, f"{n}th")

# ---------------------------------------------------------------------------
# Unicode helpers
# ---------------------------------------------------------------------------

def bold_caps(text: str) -> str:
    """Convert A-Z to 𝗔-𝗭 (mathematical sans-serif bold) — e.g. SUNDAY → 𝗦𝗨𝗡𝗗𝗔𝗬."""
    out = []
    for ch in text.upper():
        if "A" <= ch <= "Z":
            out.append(chr(0x1D5D4 + (ord(ch) - ord("A"))))
        else:
            out.append(ch)
    return "".join(out)


def tg_len(text: str) -> int:
    """Length in Telegram's units (UTF-16 code units, not Python characters).

    Telegram counts emojis (💫, ⫷ is fine, but astral-plane emojis count as 2),
    so plain len() can under-count and cause 'caption is too long' errors.
    """
    return len(text.encode("utf-16-le")) // 2


def fmt_time(dt: datetime | None) -> str:
    """datetime → '08:30 PM' style; None → 'Expected'."""
    if dt is None:
        return "Expected"
    return dt.strftime("%I:%M %p")


def platform_emoji(platform: str) -> str:
    return PLATFORM_EMOJI.get(platform, DEFAULT_PLATFORM_EMOJI)


# ---------------------------------------------------------------------------
# Header / footer
# ---------------------------------------------------------------------------

def header_lines(now: datetime) -> list[str]:
    weekday = now.strftime("%A")                        # e.g. Saturday
    date_part = f"{_ordinal(now.day)} {now.strftime('%B')}"   # e.g. 26th September
    return [
        _title_line(),
        RULE_TOP,
        f"📅 {weekday} • {date_part}",
        SUB_LINE,
        RULE_TOP,
    ]


def footer_lines() -> list[str]:
    lines = [RULE_BOTTOM, FOOTER_TITLE]
    if SHOW_POWERED_BY:
        lines.append(f"💠 𝗣𝗼𝘄𝗲𝗿𝗲𝗱 𝗕𝘆 : {POWERED_BY}")
    lines.append(FOOTER_JOIN)
    return lines


# ---------------------------------------------------------------------------
# One anime block
# ---------------------------------------------------------------------------

def episode_text(r: Release) -> str:
    """'S03E3 Expected' / 'S01E11' / '12' / '' when nothing is known."""
    if r.episode is None:
        return ""
    text = f"S{r.season:02d}E{r.episode}" if r.season else str(r.episode)
    if r.episode_expected:
        text += " Expected"
    return text


def entry_lines(r: Release) -> list[str]:
    lines = [f"⫷ {r.name} ⫸"]

    ep = episode_text(r)
    if ep:
        lines.append(f"┃🎬 Episode: {ep}")

    # Time lines — one per language when a show has separate dub slots
    # (like Skeleton Knight), otherwise a single "Time:" line.
    if len(r.lang_times) > 1:
        for lang, t in r.lang_times.items():
            line = f"┃⏰ {lang}: {t}"
            if r.time_note:
                line += f" {r.time_note}"
            lines.append(line)
    else:
        if len(r.lang_times) == 1:
            t = next(iter(r.lang_times.values()))
        else:
            t = fmt_time(r.time_dt)
        line = f"┃🕗 Time: {t}"
        if r.time_note:
            line += f" {r.time_note}"
        lines.append(line)

    lines.append(f"┃📺 Platform: {platform_emoji(r.platform)} {r.platform}")

    if r.langs:
        lines.append("┃🔊 " + " ".join(f"#{l}" for l in r.langs))

    lines.append(BLOCK_END)
    return lines


# ---------------------------------------------------------------------------
# Full messages
# ---------------------------------------------------------------------------

def build_message(entries: list[Release], now: datetime) -> str:
    """The daily update: header + one block per anime + footer."""
    lines = header_lines(now)
    for r in sorted(entries, key=Release.sort_key):
        lines.extend(entry_lines(r))
    lines.extend(footer_lines())
    return "\n".join(lines)


def build_no_update_message(now: datetime, evening: bool = False,
                            sources_failed: bool = False) -> str:
    """Sent when nothing is releasing — channel never stays silent."""
    lines = header_lines(now)
    if evening:
        lines.append("❌ Aaj shaam/raat koi aur anime episode release nahi ho raha")
    else:
        lines.append("❌ Aaj koi anime episode release nahi ho raha")
    if sources_failed:
        lines.append("⚠️ Kuch sources abhi check nahi ho paye, thodi der baad dobara update aayega")
    lines.extend(footer_lines())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram length splitting
# ---------------------------------------------------------------------------

def split_for_caption(text: str, limit: int = 1024) -> tuple[str, str | None]:
    """Split the full message into (photo caption, follow-up text).

    - If the whole message fits in the caption limit → (text, None).
    - Otherwise the caption keeps the header + as many COMPLETE anime blocks
      as fit, and the rest is returned as the follow-up message text.
    - Never cuts a block in the middle.
    """
    if tg_len(text) <= limit:
        return text, None

    lines = text.split("\n")

    # Largest prefix of whole lines that fits into the caption limit.
    used = 0
    best = 0
    for i, ln in enumerate(lines):
        cost = tg_len(ln) + (1 if i > 0 else 0)
        if used + cost > limit:
            break
        used += cost
        best = i + 1

    # Always keep at least the 5 header lines.
    if best < 6:
        best = 6

    # Prefer to end on a clean boundary (end of an anime block / footer rule).
    cut = 6
    for i in range(6, best):
        if lines[i].startswith("╰") or lines[i].startswith("━━"):
            cut = i + 1

    caption = "\n".join(lines[:cut]).rstrip()
    rest = "\n".join(lines[cut:]).lstrip("\n")
    return caption, (rest if rest.strip() else None)


def split_long_text(text: str, limit: int = 4096) -> list[str]:
    """Split follow-up text into ≤4096-char chunks at line boundaries."""
    if tg_len(text) <= limit:
        return [text]
    lines = text.split("\n")
    chunks, current, used = [], [], 0
    for ln in lines:
        cost = tg_len(ln) + (1 if current else 0)
        if current and used + cost > limit:
            chunks.append("\n".join(current))
            current, used = [], 0
            cost = tg_len(ln)
        current.append(ln)
        used += cost
    if current:
        chunks.append("\n".join(current))
    return chunks


# ---------------------------------------------------------------------------
# Self-test:  python template.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from datetime import date, time

    demo = [
        Release(
            name="Mushoku Tensei: Jobless Reincarnation Season 3", platform="Crunchyroll",
            langs=["Hindi"], season=3, episode=3, episode_expected=True,
            time_dt=datetime.combine(date.today(), time(20, 30), tzinfo=IST),
        ),
        Release(
            name="Skeleton Knight in Another World", platform="Muse India (YouTube)",
            langs=["Tamil", "Telugu"], season=1, episode=12, episode_expected=False,
            lang_times={"Tamil": "09:30 PM", "Telugu": "10:00 PM"}, time_note="(Daily)",
        ),
    ]
    now = datetime.combine(date(2026, 9, 13), time(10, 0), tzinfo=IST)
    msg = build_message(demo, now)
    print(msg)
    print()
    print(f"tg_len = {tg_len(msg)} chars (caption limit 1024)")
    cap, rest = split_for_caption(msg)
    print(f"caption part = {tg_len(cap)} chars, rest = {tg_len(rest) if rest else 0} chars")
    assert bold_caps("SUNDAY") == "𝗦𝗨𝗡𝗗𝗔𝗬", "bold_caps broken!"
    assert split_for_caption(msg)[0].startswith("💫 [ANIME HINDI UPDATE]")
    print("OK — template self-test passed ✅")
