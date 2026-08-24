# Daily Manual Run — TL;DR

You run this yourself, 2-3 times a day, whenever it's convenient for you.
No hosting platform, no cron job, no server that has to stay online. Just
one command on your own machine.

---

## The single command you need

**Run this whenever you want fresh jobs (2-3x/day, your call):**

```powershell
cd D:\Job_Applier
.\venv\Scripts\python.exe scripts\run_agent.py
```

This does everything in one shot:
1. Starts the Telegram bot in the background automatically (so `/jobs`,
   `/companies`, `/done`, `/setresume`, `/stats`, etc. respond immediately -
   no separate polling terminal needed).
2. Runs discovery in the foreground - pulls jobs from all public sources
   (RemoteOK, Remotive, WorkingNomads, Himalayas, WeWorkRemotely), plus
   Greenhouse/Lever/Ashby boards for the companies known to hire in India
   (see `companies_hiring_in_india.txt` and `config/ats_boards.json`,
   refreshed occasionally via `scripts/discover_ats_boards.py`).
3. Deduplicates against everything already in Supabase.
4. Scores each new job against your skills/preferences - role matching is
   broadened with the curated fresher-hiring title patterns in
   `fresher_hiring_roles.txt` (SDE, SDET, GET, MTS-1, etc.), in addition to
   whatever you've listed in `config/job_preferences.json`.
5. For jobs that pass your role filter **and** `MINIMUM_MATCH_SCORE`
   (default 82):
   - Adds a row to your Google Sheet.
   - Sends **one grouped Telegram digest** for the whole run (e.g. "12 new
     matching jobs across 4 companies") with a tappable button per company
     instead of a separate push per job - tap a company to see just its
     matching roles. Use `/companies` any time afterwards to re-browse.
6. Every job (even low-scoring ones) is saved to Supabase either way, so
   `/jobs` in Telegram always shows the full picture.
7. Keeps running afterwards so you can immediately use the bot - press
   Ctrl+C when you're done for now. Nothing is lost if you close it: Telegram
   queues any commands you send while it's down, and re-running discovery is
   always safe (duplicates are detected and skipped).

If you'd rather keep discovery and the bot as two separate steps (e.g. to
run discovery without starting the bot, or vice versa), the original two
commands still work exactly as before:

**1. Discover jobs only (no bot):**

```powershell
cd D:\Job_Applier
.\venv\Scripts\python.exe scripts\run_discovery.py
```

Does steps 2-6 above, then exits - no Telegram bot started.

**2. Talk to your bot only (no discovery):**

```powershell
cd D:\Job_Applier
.\venv\Scripts\python.exe scripts\telegram_polling.py
```

This is what makes `/jobs`, `/companies`, `/done`, `/setresume`, `/stats`,
etc. actually respond. Leave it running in a terminal while you're actively
checking things; close it (Ctrl+C) when you're done for the day. Nothing
breaks if it's not running — Telegram just won't reply until you start it
again, and no messages are lost (they're queued by Telegram and processed
once you restart it).

That's the whole workflow. Everything below is detail/troubleshooting you
probably won't need day-to-day.

---

## Suggested daily routine

Pick 2-3 times a day that suit you (morning, afternoon, evening — whatever
fits your schedule, no fixed cron time required):

```powershell
cd D:\Job_Applier
.\venv\Scripts\python.exe scripts\run_agent.py
```

Leave it running afterwards (or restart it later) and use Telegram:
`/companies`, `/jobs`, `/job <id>`, `/done <id>`, `/skip <id>`, `/stats`,
etc. Press Ctrl+C in that terminal when you're done for now.

There is no downside to leaving `run_agent.py` (or `telegram_polling.py`)
running in a spare terminal all day if you don't mind it using a little
background CPU/network — it just isn't required to be always-on.

## What ends up where

- **Supabase** — the source of truth for everything: every discovered job
  (regardless of score), every notification sent, every application status
  change. Nothing is ever lost even if you close everything and come back
  a week later.
- **Google Sheet** — mirrors Telegram exactly: only jobs that cleared your
  role filter and `MINIMUM_MATCH_SCORE` appear here. Good for a quick
  visual scan or sharing/filtering in a spreadsheet.
- **Telegram** — same jobs as the Sheet, delivered as one grouped digest
  per run the moment `run_agent.py`/`run_discovery.py` finds them (tap a
  company to drill into its roles, or use `/companies` any time), plus your
  interactive command interface.

## First-time setup (only needed once)

If you haven't already:

```powershell
cd D:\Job_Applier
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # then fill in real values - see below
```

Required in `.env`:
- `SUPABASE_URL`, `SUPABASE_KEY` — your Supabase project.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — your bot.
- `GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_SHEETS_SPREADSHEET_ID` — optional,
  for the Sheet (skip if you don't want Sheets sync).
- `MINIMUM_MATCH_SCORE` — how strict the Telegram/Sheets filter is
  (default 82).
- LLM API keys (`GEMINI_API_KEY`, `NVIDIA_NIM_API_KEY`, `GROQ_API_KEY`) — all optional.
  See `.env.example` for details on how the fallback chains work.

Then set up your profile once:

```powershell
Copy-Item config\candidate_profile.example.json config\candidate_profile.json
Copy-Item config\job_preferences.example.json config\job_preferences.json
Copy-Item config\candidate_skills.example.json config\candidate_skills.json
# edit all three files with your real details
.\venv\Scripts\python.exe scripts\setup_profile.py
.\venv\Scripts\python.exe scripts\sync_skills.py
```

Optionally refresh the cached Greenhouse/Lever/Ashby board tokens for
companies known to hire in India (safe to skip - `default_sources()` works
fine with whatever's already cached in `config/ats_boards.json`):

```powershell
.\venv\Scripts\python.exe scripts\discover_ats_boards.py
```

Run the database migrations once in the Supabase SQL Editor:
`supabase/migrations/0001_init.sql` then `0002_related_skills.sql`.

Send your resume once, via Telegram (with the bot running):
`/setresume <paste your resume text>`.

## Optional: run discovery and the bot as two separate terminals

`scripts/run_agent.py` already starts both in one command (see above). If
you'd rather manage them as two separate processes instead (e.g. to restart
just the bot without re-running discovery):

```powershell
Start-Process -NoNewWindow -FilePath .\venv\Scripts\python.exe -ArgumentList 'scripts\telegram_polling.py'
.\venv\Scripts\python.exe scripts\run_discovery.py
```

The poller keeps running after `run_discovery.py` finishes; close the
terminal window (or find and stop the python process) when you're done.

## Telegram commands quick reference

| Command | What it does |
|---|---|
| `/start`, `/help` | Intro / list commands |
| `/today`, `/jobs`, `/job <id>` | Browse discovered jobs |
| `/companies` | Browse notified jobs grouped by company - tap a company to see just its matching roles |
| `/done <id>` | Mark a job as applied |
| `/skip <id>` | Skip a job you're not interested in |
| `/status <id>`, `/applied`, `/stats` | Track your pipeline |
| `/interview <id>`, `/rejected <id>`, `/offer <id>`, `/withdraw <id>` | Update application stage |
| `/setresume <text>` | Save a new master resume version |
| `/resume <id>` | Analyze resume fit against a job |
| `/approveresume <id>` | Approve the tailored resume draft |

## Troubleshooting

- **No Telegram alerts even though jobs were found** → check
  `MINIMUM_MATCH_SCORE` and your `preferred_roles`/skills (also broadened by
  `fresher_hiring_roles.txt`) - the Sheet and Telegram only show jobs that
  clear both filters. Everything else is still in Supabase (`/jobs` shows it).
- **`/help` or other commands don't respond** → neither `run_agent.py` nor
  `telegram_polling.py` is running right now. Start one of them; commands
  you sent while it was down simply won't be acted on, so just re-send them
  once it's up.
- **Job links missing / notifications not arriving at all** → this usually
  means no jobs cleared `MINIMUM_MATCH_SCORE` this run, not a bug - lower it
  temporarily to sanity-check, or refresh `config/ats_boards.json` via
  `scripts/discover_ats_boards.py` to widen the pool of India-relevant
  company boards.
- **`run_agent.py`/`run_discovery.py` seems slow** → normal if you've
  configured a real LLM provider (semantic skill matching makes an API call
  per unmatched skill per job) - a few minutes for ~50 jobs is expected. Set
  `LLM_PROVIDER=null` in `.env` if you'd rather have instant, fully
  deterministic-only runs. Round-robin providers (`LLM_PROVIDERS=nvidia,groq`)
  are fast but each reasoning-capable model still spends a few tokens
  "thinking" before answering - already accounted for in the code, but
  expect brief per-call latency.
- **`PGRST125` / "Invalid path"** → `SUPABASE_URL` in `.env` has a trailing
  slash or `/rest/v1` suffix; remove it (also auto-normalized by
  `app/config.py`, but cleaner to fix at the source).
- **Google Sheets `403`/API-disabled** → share the sheet with your service
  account's `client_email` as Editor, and enable the Sheets API in Google
  Cloud Console; or just leave Sheets unconfigured - it's optional and
  never blocks the pipeline.
- **Re-running discovery right after a previous run** → completely safe.
  Duplicate jobs are detected and skipped; you'll just see `jobs_duplicate`
  go up and `jobs_new`/`jobs_notified` stay low or zero.

For the full command reference and architecture details, see `README.md`.
For a more thorough local-setup walkthrough, see `HOW_TO_RUN.md`.
