# How to Run — Job Application Agent

A practical, step-by-step guide to get this project running locally and
keep it running day-to-day. For architecture/design details see `README.md`.

---

## 1. Prerequisites

- Python 3.11+ (project developed/tested on 3.13)
- A Supabase project (free tier is fine)
- A Telegram bot token (via [@BotFather](https://t.me/BotFather))
- (Optional) Gemini, NVIDIA NIM, or Groq API keys for semantic skill matching /
  cover letter generation. (Defaults to `null` provider — fully offline mode).
- (Optional) A Google Cloud service account, for Google Sheets sync

---

## 2. Install

```powershell
cd D:\Job_Applier
python -m venv venv
.\venv\Scripts\pip install --upgrade pip
.\venv\Scripts\pip install -r requirements.txt
```

---

## 3. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `SUPABASE_URL` | Supabase dashboard → Project Settings → API → **Project URL**. Must be just the base URL, e.g. `https://xxxxx.supabase.co` — **no trailing slash, no `/rest/v1`** (adding either causes a `PGRST125` error). |
| `SUPABASE_KEY` | Same page → **service_role** key (not the anon key). |
| `TELEGRAM_BOT_TOKEN` | From @BotFather after `/newbot`. |
| `TELEGRAM_CHAT_ID` | Message your bot once, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id`. |
| `GEMINI_API_KEY`, etc. | LLM configuration is optional. See `.env.example` for details on the Gemini, NVIDIA NIM, and Groq fallback chains. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Local dev: absolute path to a downloaded service-account JSON key file. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Production fallback: paste the same key file's raw JSON content here instead (used only if the file above isn't found - see §6c). |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | The ID from your spreadsheet's URL (the long string between `/d/` and `/edit`). |
| `MINIMUM_MATCH_SCORE` | Minimum score (0-100) required before a job is pushed as a Telegram alert. Default `82`. |
| `SCHEDULER_SECRET` | Any random string — required as a header to trigger scheduled runs manually/via cron. |
| `APP_TIMEZONE` | e.g. `Asia/Kolkata`. |
| `CANDIDATE_PROFILE_JSON`, `JOB_PREFERENCES_JSON`, `CANDIDATE_SKILLS_JSON` | Production fallback for §6's config files - see §6c. |

**Never commit `.env`** — it's already git-ignored.

---

## 4. Set up Supabase (database schema)

1. Open your Supabase project → **SQL Editor** → New query.
2. Paste and run the contents of `supabase/migrations/0001_init.sql` (creates all
   V1 + V2 tables).
3. Paste and run `supabase/migrations/0002_related_skills.sql` (adds
   semantic-skill-match and fresher-preference columns).
4. Both are idempotent (`if not exists`) — safe to re-run if unsure whether
   they were already applied.

---

## 5. Set up Google Sheets (optional but recommended)

1. Create a Google Cloud project → enable the **Google Sheets API**.
2. Create a service account → download its JSON key → set
   `GOOGLE_SERVICE_ACCOUNT_FILE` to its absolute path.
3. Open your target Google Sheet → **Share** → add the service account's
   email (found in the JSON as `client_email`) as **Editor**.
4. If Sheets isn't configured or fails, the rest of the pipeline keeps
   working — Sheets is reporting-only, never a hard dependency.

---

## 6. Set your candidate profile, skills, and preferences

Everything here is config-file-driven — edit a JSON file, run a script, done.
Both scripts are idempotent (safe to re-run any time you update a file) and
never create duplicate rows (single-user system: one profile, one
preferences row).

**Profile + job preferences:**

1. Copy the templates (first time only):
   ```powershell
   Copy-Item config\candidate_profile.example.json config\candidate_profile.json
   Copy-Item config\job_preferences.example.json config\job_preferences.json
   ```
2. Edit `config\candidate_profile.json` (name, email, phone, location,
   years of experience) with your real details.
3. Edit `config\job_preferences.json` (preferred roles, technologies,
   locations, work mode, minimum salary, fresher-only filter).
4. Push both to Supabase:
   ```powershell
   .\venv\Scripts\python scripts\setup_profile.py
   ```

**Skills** (kept separate since they change more often):

1. Copy the template (first time only): `Copy-Item config\candidate_skills.example.json config\candidate_skills.json`
2. Edit `config\candidate_skills.json` with your real, current skills.
3. Push to Supabase:
   ```powershell
   .\venv\Scripts\python scripts\sync_skills.py
   ```

Re-run either script any time you update the corresponding file(s) — for
example, whenever you learn a new skill, change your target roles, or
update your salary expectation.

All three real files (`candidate_profile.json`, `job_preferences.json`,
`candidate_skills.json`) are git-ignored since they contain your real PII
and preferences — only the `.example.json` templates are tracked in git.

## 6c. Production alternative: environment variables instead of files

Both `setup_profile.py` and `sync_skills.py` look for the file on disk
first, and if it's not found, fall back to reading the equivalent
environment variable as raw JSON content — so the exact same scripts work
unchanged locally and in production:

| Local file | Production env var fallback |
|---|---|
| `config/candidate_profile.json` | `CANDIDATE_PROFILE_JSON` |
| `config/job_preferences.json` | `JOB_PREFERENCES_JSON` |
| `config/candidate_skills.json` | `CANDIDATE_SKILLS_JSON` |
| Google service account file (`GOOGLE_SERVICE_ACCOUNT_FILE`) | `GOOGLE_SERVICE_ACCOUNT_JSON` |

To use the fallback, paste the exact JSON content of the file as the
env var's value (most hosting platforms, including Northflank, support
multi-line/JSON secret values directly - no escaping needed). If a real
file exists on disk it always wins; the env var is only consulted when the
file is missing, so you never need to change code between environments.

## 6b. Upload / set your resume

Send this directly to your Telegram bot (paste your full resume as plain
text after the command):

```
/setresume <paste your resume text here>
```

Each `/setresume` call creates a new, immutable version — nothing is ever
overwritten. Later, run `/resume <job_id>` against any discovered job to get
a match analysis and a proposed tailored resume, then `/approveresume
<job_id>` to accept it.

---

## 7. Run the FastAPI server

```powershell
.\venv\Scripts\python -m uvicorn app.main:app --reload
```

Check it's healthy:

```powershell
curl http://127.0.0.1:8000/health
```

Expect `{"status":"ok","supabase":"connected","telegram":"configured"}`. If
`supabase` or `telegram` show as `not_configured`/`degraded`, re-check `.env`.

> If port 8000 is already in use, run on another port:
> `uvicorn app.main:app --port 8001`

---

## 8. Run the Telegram bot (to receive alerts and use commands)

In a separate terminal:

```powershell
.\venv\Scripts\python scripts\telegram_polling.py
```

This long-polls Telegram and dispatches all commands (`/today`, `/jobs`,
`/done`, `/skip`, `/setresume`, `/resume`, etc. — see the full list in
`README.md` §9). Keep this running in the background (or deploy it as a
long-running worker process) to interact with the bot.

---

## 9. Run a job-search discovery manually

**Option A — via the API endpoint** (what a scheduler would call):

```powershell
curl -X POST http://127.0.0.1:8000/run/job-search -H "X-Scheduler-Secret: <your SCHEDULER_SECRET>"
```

This uses `default_sources()` — RemoteOK, Remotive, WorkingNomads,
Himalayas, and We Work Remotely (all public feeds, no scraping).

**Option B — directly via Python** (useful for testing specific sources):

```powershell
.\venv\Scripts\python -c "
from app.agents.job_agent import run_job_search, default_sources
result = run_job_search(default_sources(greenhouse_boards=['stripe', 'discord']))
print(result)
"
```

`greenhouse_boards` is optional — pass company board tokens (from
`boards.greenhouse.io/<token>`) to also pull specific companies' postings.

Each run is idempotent: re-running never creates duplicate jobs or sends
duplicate Telegram notifications, and survives a crash/restart safely (see
`agent_runs` table for history).

---

## 10. Schedule it to run automatically

Point any external scheduler (Supabase Cron, a cron job, GitHub Actions,
etc.) at:

```
POST https://<your-deployed-host>/run/job-search
Header: X-Scheduler-Secret: <your SCHEDULER_SECRET>
```

on your desired cadence (e.g. daily at 08:00 `APP_TIMEZONE`). No
always-on local machine is required if this is deployed (see `Dockerfile`).

---

## 11. Run the test suite

Everything runs fully offline against an in-memory fake Supabase client and
mocked LLM/HTTP transports — no live credentials needed:

```powershell
.\venv\Scripts\python -m pytest -v
```

Expect all tests to pass (150+ at time of writing).

---

## 12. Common commands cheat-sheet (Telegram)

| Command | What it does |
|---|---|
| `/start`, `/help` | Intro / list commands |
| `/today`, `/jobs`, `/job <id>` | Browse discovered jobs |
| `/done <id>` | Mark a job as applied (after you apply manually) |
| `/skip <id>` | Skip a job you're not interested in |
| `/status <id>`, `/applied`, `/stats` | Track your pipeline |
| `/interview <id>`, `/rejected <id>`, `/offer <id>`, `/withdraw <id>` | Update application stage |
| `/companies` | Browse notified jobs grouped by company - tap a company button to see just its matching roles |
| `/setresume <text>` | Save a new master resume version |
| `/resume <id>` | Analyze resume fit against a job |
| `/approveresume <id>` | Approve the tailored resume draft |

---

## 13. Troubleshooting quick reference

- **`PGRST125` / "Invalid path"** → your `SUPABASE_URL` has a trailing
  slash or `/rest/v1` suffix. Fix it in `.env` (also auto-normalized by
  `app/config.py`, but cleaner to fix at the source).
- **Google Sheets `403 permission`** → share the sheet with your service
  account's `client_email` as Editor.
- **Google Sheets `API has not been used ... disabled`** → enable the
  Sheets API for your Google Cloud project in the Cloud Console.
- **No Telegram messages arriving** → confirm `scripts/telegram_polling.py`
  is actually running, and that `TELEGRAM_CHAT_ID` matches the chat you
  messaged the bot from.
- **Port 8000 already in use** → run uvicorn on a different `--port`, or
  find/stop the process holding it (`netstat -ano | findstr :8000` on
  Windows, then `taskkill /PID <pid> /F`).
- **All jobs scoring low / nothing notified** → check `MINIMUM_MATCH_SCORE`
  (default 82 is strict by design), your `preferred_roles`/`skills` in
  Supabase, and that `config/candidate_skills.json` has been synced.
