# 💫 Daily Anime Dub Update Bot (Telegram + Render)

A production-ready Telegram bot that posts **today's Indian-language anime dub releases**
(Hindi / Telugu / Tamil) to your channel **twice a day — 10:00 AM & 7:00 PM IST** — with your
**banner photo attached on top of every message** (photo + caption joined together, always).

Deploy it **free** on [Render.com](https://render.com).

---

## 📁 Project structure

| File | What it is |
|---|---|
| `main.py` | Bot entry point — polling, daily jobs (10 AM / 7 PM IST), `/sendnow`, `/test`, health server |
| `send_once.py` | One-shot sender for the **Cron Job** alternative |
| `sources.py` | Live source fetchers (Muse India RSS, Crunchyroll, LiveChart, AnimeSchedule, Google News) |
| `builder.py` | Merges all sources into one final list (dedup, cross-verify, evening filter) |
| `template.py` | ✏️ **The exact message format** — edit looks here (brand name, footer, emojis) |
| `schedule_config.py` | ✏️ **Your personal dub schedule** — edit shows/times here |
| `sender.py` | Sends photo+caption, handles the 1024-char caption split, blocks duplicate sends |
| `config.py` | Env vars & settings |
| `models.py` | Data models |
| `assets/banner.jpg` | 🖼 **Your photo that sits on top of every message** (replace anytime, keep the name) |
| `render.yaml` | Render blueprint (Web Service + commented Cron alternative) |
| `requirements.txt` | Python dependencies |

---

## 🪜 Step 1 — Create the bot & get the token

1. Open Telegram → search **@BotFather** → send `/newbot`
2. Choose a display name (e.g. `Fairy World Updates`) and a username (must end in `bot`)
3. BotFather replies with a token like `123456789:AAH...` → **copy it** (this is `BOT_TOKEN`)

## 🪜 Step 2 — Channels/Groups ko jodna (EASY — koi ID ki zaroorat nahi!)

Bot ab **multi-channel + multi-group** hai — koi bhi use jod sakta hai:

**👥 GROUP me (admin ki zaroorat NAHI!):**
1. Group kholo → **Add Members → bot ka username**
2. Bas! Member hi kaafi hai — bot group me daily updates bhejega

**📺 CHANNEL me (Telegram rule — admin zaroori):**
1. Channel → **Manage Channel → Administrators → Add Admin**
2. Bot ko add karo → **Post Messages** permission ON rakho
3. (Channels me Telegram kisi bhi bot ko sirf admin ban kar post karne deta hai — ye rule sab bots pe lagta hai)

- Jahan bhi add hoga, wahan ✅ welcome post + daily updates (10:00 AM & 7:00 PM IST)
- Bot ko chat se remove kiya → wahan ke updates apne aap band
- `CHANNEL_ID` env var ki **zaroorat nahi** (purane setup ke liye abhi bhi kaam karta hai —
  set karoge to woh channel bhi registry me add ho jata hai)

> **Note:** agar bot deploy hone se PEHLE se kisi channel ka admin tha, to use woh channel
> yaad nahi rehta (Telegram history nahi deta). Aise channel ke liye ya to `CHANNEL_ID` env
> set karo, ya bot ko admin se remove karke dobara add kar do.

## 🪜 Step 4 — Put the code on GitHub

Create a new GitHub repo and upload this whole folder (or push with git):
```bash
git init && git add . && git commit -m "anime dub update bot"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/anime-update-bot.git
git push -u origin main
```
*(Or drag-and-drop the files into a new repo on github.com — easiest.)*

## 🪜 Step 5 — Deploy on Render (Web Service, FREE)

1. Go to [dashboard.render.com](https://dashboard.render.com) → **New + → Web Service**
2. Connect your GitHub account → pick the repo
3. Settings (the `render.yaml` fills most of these in automatically):
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** Free
4. **Environment** tab → add:
   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | your @BotFather token |
   | `CHANNEL_ID` | `@your_channel` or `-100...` |
   | `ADMIN_CHAT_ID` | *(optional)* your numeric Telegram id — locks `/sendnow` & `/test` to you |
5. **Create Web Service** → watch the logs. When you see
   `health-check server listening on 0.0.0.0:PORT` and `bot is up` — it's live. 🎉

### ⏰ Keep it awake (important on the FREE plan)

Render **free web services sleep after 15 minutes without HTTP traffic** — a sleeping
bot can't fire the 10 AM job on time. Fix it for free with an uptime pinger:

1. Create a free account on [cron-job.org](https://cron-job.org) (or UptimeRobot)
2. Add a job that **pings your Render URL** (`https://your-service.onrender.com/`)
   **every 10 minutes**
3. Done — the bot never sleeps, and 10 AM / 7 PM jobs fire exactly on time.

> **Which option to choose — Web Service vs Cron Job?**
> - **Web Service + free pinger (recommended)** → total cost ₹0, instant `/sendnow` testing,
>   keeps state so the same message is never sent twice.
> - **Render Cron Jobs** (`render.yaml` OPTION B, ~$1/month each = 2 jobs) → zero keep-awake
>   hassle, guaranteed start time, but no instant commands and small monthly cost.

## 🧪 Step 6 — Test it

- Open your bot in Telegram (private chat) → `/start`
- `/sendnow` → posts the update to your channel **right now** (banner photo on top ✅)
- `/test` → shows exactly what every source returned (great for debugging)

---

## 🎨 Customizing

### Change the banner photo
Replace `assets/banner.jpg` with your new image (keep the filename). Max ~10 MB, JPEG/PNG.

### Add/remove shows
**You don't.** The lineup is read live from the schedule page — new shows
appear automatically when they start, and disappear when they finish.
`schedule_config.py` only has optional escape hatches (all empty by default):
```python
DUB_SCHEDULE = []     # force a specific show: [{"name": ..., "time": "18:30", ...}]
PLATFORM_HINTS = {}   # force a platform label: {"captain tsubasa": "Muse India (YouTube)"}
IGNORE_SHOWS = []     # never post these: ["captain tsubasa"]
```

### Footer line
`template.py` → `SHOW_POWERED_BY = False` removes the `💠 𝗣𝗼𝘄𝗲𝗿𝗲𝗱 𝗕𝘆 : @dc_hmm` line
if you don't want it. `POWERED_BY` changes the handle.

### Change the message look → `template.py`
- `BRAND` — the name in the first line (`💫 [ANIME HINDI UPDATE] – FAIRY WORLD ⚡`)
- `POWERED_BY` — footer handle
- `PLATFORM_EMOJI` — emoji per platform
- All block decorations live in one place; the format matches your sample exactly.

---

## 🔎 How the bot works — 100% LIVE, no shows hardcoded in the code

Every run (10 AM & 7 PM) the bot checks live sources and builds the message
from what it sees **right now**:

1. **Anime-dub schedule page** (`animedubhindi.link/schedule.php`) — the backbone.
   Lists every ongoing Indian-dub show + upcoming premieres with day, time,
   next episode and an exact drop timestamp.
   - a **new anime starts** → appears on the page → posted automatically
     (premieres like *Overgeared E1* are caught on day one from the Upcoming list)
   - an **anime ends** → disappears from the page → the bot stops posting it
   - an episode already dropped earlier today (the page rolled to next week) →
     the bot reconstructs it: episode−1 at today's slot time
   - times / episode numbers / seasons / languages all come from this page live
2. **Muse India YouTube** (RSS of `@MuseIndiaChannel`) — actual uploads today
   confirm episodes & times, and flag the show as Muse India (YouTube).
3. **Crunchyroll public video feed** — Indian-dub drops confirm & flag Crunchyroll.
4. **LiveChart / AnimeSchedule** — cross-check + expected episode numbers
   (AnimeSchedule, optional token, also exposes streaming platforms).
5. **Google News RSS** — live platform lookup per show ("... release schedule on
   Crunchyroll" → 🟠 Crunchyroll) + catches anything the page missed.

If the schedule site is temporarily down (it sometimes returns Cloudflare 525),
the bot retries 3×, then reuses the same-day cached copy — and the other
sources keep working. If NOTHING is available, the fallback message keeps the
channel from going silent.

`schedule_config.py` contains **three optional escape hatches — all empty by
default**: `DUB_SCHEDULE` (force a show's time/episode), `PLATFORM_HINTS`
(force a platform label), `IGNORE_SHOWS` (never post a show). You normally
never need them.

Extra rules:
- Everything is merged into **one message** with the photo on top.
- Caption limit 1024 chars: longer messages = photo with header+first blocks as caption,
  remainder sent instantly as follow-up text (never cut mid-block).
- The 7 PM message lists only releases **from 18:00 onwards** (configurable via `EVENING_CUTOFF_HOUR`),
  and the **exact same text is never sent twice** the same day (`data/sent.json`).
- If nothing is releasing: the channel still gets the header + `❌ Aaj koi anime episode release nahi ho raha` + footer (with photo).

## 🖥 Local run

```bash
cd anime-update-bot
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # fill BOT_TOKEN and CHANNEL_ID
python main.py           # bot + health server on :10000
# or one-shot test send:
python send_once.py morning
```

## 🩺 Troubleshooting

| Problem | Fix |
|---|---|
| Channel me updates nahi aa rahe | Bot us channel ka **admin** hai? (`Post Messages` permission ON?) — nahi to admin se remove karke dobara add karo |
| `Chat not found` / bot silent | Bot is not an **admin** of that channel — auto-remove ho gaya hoga, dobara admin banao |
| Kitne channels jude hain? | Bot ke private chat me `/channels` likho |
| No photo on the message | `assets/banner.jpg` missing — re-add it and redeploy |
| 10 AM message late/missing | Free plan slept — set up the keep-awake pinger (§ Step 5) |
| Muse India source ❌ in `/test` | YouTube RSS occasionally blocked from some datacenter IPs; other sources still cover it, and your `schedule_config.py` entries always go out |
| Want to see raw source data | Run `/test` in the bot's private chat |
| Logs | Render dashboard → your service → **Logs** tab |
