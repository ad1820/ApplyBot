# Deploying to Northflank — Full Active Deployment Guide

This guide gets the whole system **actively running** on Northflank:
Supabase stays the database (source of truth), and Northflank hosts the
FastAPI app, the Telegram poller, and the scheduled discovery run — all
from the same Docker image.

## Architecture on Northflank

```
Supabase (Postgres - source of truth, no Supabase Cron needed)
        ^
        |
        |-------------------------------------------------------
        |                          |                            |
   Service #1                 Service #2                    Job (cron)
   FastAPI app                Telegram poller                job discovery
   uvicorn app.main:app       python scripts/               python scripts/
   (health check,             telegram_polling.py           run_discovery.py
    optional webhook)         (always-on)                   (scheduled, direct
                                                              command execution -
                                                              no HTTP hop needed)
```

Northflank **Jobs** run a container **once or on a schedule** and execute
an actual command inside your image — unlike the Supabase Cron approach
(which calls an HTTP endpoint from outside your app), the Job here runs
`python scripts/run_discovery.py` directly, in the same image and
environment as your services. This is simpler and avoids a network hop.

---

## Step 1 — Supabase setup (unchanged, still the source of truth)

1. Create a Supabase project → note the **Project URL** and **service_role key**.
2. In the SQL Editor, run `supabase/migrations/0001_init.sql`, then
   `supabase/migrations/0002_related_skills.sql` (both idempotent).
3. `SUPABASE_URL` must be just the base URL (`https://xxxxx.supabase.co`) —
   no trailing slash, no `/rest/v1` (causes a `PGRST125` error).
4. RLS stays disabled — only your trusted backend (service_role key) talks
   to Supabase. You do **not** need Supabase Cron for this deployment;
   Northflank's own Job scheduler replaces that role entirely.

## Step 2 — Populate your profile, preferences, and skills

From your local machine (with `.env` pointed at the production Supabase project):

```bash
cp config/candidate_profile.example.json config/candidate_profile.json
cp config/job_preferences.example.json config/job_preferences.json
cp config/candidate_skills.example.json config/candidate_skills.json
# edit all three files with your real details
python scripts/setup_profile.py
python scripts/sync_skills.py
```

These `config/*.json` files are git-ignored and stay local to your machine
— they are **not** part of what gets pushed to Git or built into the
Northflank image. That's fine: `setup_profile.py`/`sync_skills.py` only
need to run once (or whenever you update your details) to push the data
into Supabase, which is what the running app actually reads from. You can
also re-run these scripts later from a Northflank Job/shell using the
`CANDIDATE_PROFILE_JSON`/`JOB_PREFERENCES_JSON`/`CANDIDATE_SKILLS_JSON`
secrets described in Step 5 instead, if you'd rather not keep local files.

## Step 3 — Push this repo to a Git provider

Northflank builds from a linked Git repository (GitHub/GitLab/Bitbucket).
Push this project there if it isn't already, with a real `.env` **not**
committed (already git-ignored).

## Step 4 — Create a Northflank project and link your repo

1. Sign in to Northflank → **Create a project**.
2. **Link your Git account** and select this repository.
3. Northflank will build using the provided `Dockerfile` at the repo root —
   no changes needed there (it already copies `app/`, `scripts/`,
   `supabase/`, and `config/`).

## Step 5 — Store secrets once, reuse across all workloads

Rather than re-typing every variable per service, create a **Secret Group**
(Project → Secrets) with all the values from `.env.example`:

```
SUPABASE_URL
SUPABASE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
LLM_PROVIDER
LLM_API_KEY
LLM_MODEL
GOOGLE_SERVICE_ACCOUNT_JSON     (see note below)
GOOGLE_SHEETS_SPREADSHEET_ID
APP_TIMEZONE
LOG_LEVEL
SCHEDULER_SECRET
MINIMUM_MATCH_SCORE
CANDIDATE_PROFILE_JSON         (see note below)
JOB_PREFERENCES_JSON           (see note below)
CANDIDATE_SKILLS_JSON          (see note below)
```

**All *_JSON secrets work the same way:** every JSON-based config in this
project (Google service account credentials, candidate profile, job
preferences, candidate skills) is loaded from a **file on disk first**, and
falls back to an **environment variable containing the same JSON content**
if the file isn't found - no code changes needed either way. Since your
`config/*.json` files never get committed to Git (they're git-ignored) and
therefore won't exist in the built image, simply paste each file's exact
JSON content into the matching secret:

| Local file (not in the built image) | Secret env var to paste it into |
|---|---|
| Your Google service account key file | `GOOGLE_SERVICE_ACCOUNT_JSON` |
| `config/candidate_profile.json` | `CANDIDATE_PROFILE_JSON` |
| `config/job_preferences.json` | `JOB_PREFERENCES_JSON` |
| `config/candidate_skills.json` | `CANDIDATE_SKILLS_JSON` |

Northflank secret values support multi-line/JSON content directly - just
paste the whole file's contents as the value, no escaping required.
Skip `GOOGLE_SERVICE_ACCOUNT_JSON`/`GOOGLE_SHEETS_SPREADSHEET_ID` entirely
if you don't want Google Sheets sync - the pipeline works fine without it.

Attach this Secret Group to all three workloads created below so they all
share one source of truth for configuration.

## Step 6 — Service #1: FastAPI app (continuous)

1. Create a new **Service** (deployment) in your project.
2. Deployment source: build from your linked repo using the `Dockerfile`.
3. Start command: leave as the image default (`uvicorn app.main:app --host 0.0.0.0 --port 8000`, already set as the `Dockerfile`'s `CMD`).
4. Attach the Secret Group from Step 5 as environment variables.
5. Expose port `8000` publicly (Networking tab) and note the generated
   public URL, or add your own domain.
6. Deploy, then verify:
   ```bash
   curl https://<service-1-url>/health
   ```
   Expect `{"status":"ok","supabase":"connected","telegram":"configured"}`.

## Step 7 — Service #2: Telegram poller (continuous)

1. Create a second **Service** in the same project, from the same repo/image.
2. Override the command (Advanced options → Override command) to:
   ```
   python scripts/telegram_polling.py
   ```
3. Attach the same Secret Group.
4. No public port needed — this service only makes outbound calls to
   Telegram's API.
5. Deploy, then send `/help` to your bot — you should get an immediate reply.

Only run **one** instance of this service — Telegram rejects concurrent
`getUpdates` long-polling clients on the same bot token. Do not scale this
service beyond 1 replica.

## Step 8 — Job: scheduled job discovery (cron)

1. Create a new **Job** in the same project, from the same repo/image
   (Run → Run an image once or on a schedule).
2. Override the command to run the discovery script directly:
   ```
   python scripts/run_discovery.py
   ```
   Optionally pass Greenhouse board tokens as arguments to also pull
   specific companies, e.g. `python scripts/run_discovery.py stripe discord`.
3. Attach the same Secret Group from Step 5.
4. Set the **schedule** using standard cron syntax, e.g. `0 8 * * *` for
   daily at 08:00. Northflank Job schedules run in **UTC** — convert your
   desired local time (e.g. 08:00 IST = 02:30 UTC → `30 2 * * *`).
5. Set **Concurrency policy** to **Forbid** — this prevents a new run from
   starting while a previous one is still in progress (important since
   discovery runs across 5+ sources can take several minutes; overlapping
   runs would still be safe/idempotent thanks to the `agent_runs` and
   dedup logic, but `Forbid` avoids wasted duplicate work).
6. Set a **Retry limit** (e.g. 1-2) and a **Time limit** (e.g. 600 seconds)
   so a hung run doesn't block the next scheduled trigger indefinitely.
7. Save. You can also trigger the Job manually right away to test it
   without waiting for the schedule.

## Step 9 — Verify everything is actively running end-to-end

1. **FastAPI reachable**: `curl https://<service-1-url>/health` →
   `{"status":"ok","supabase":"connected","telegram":"configured"}`.
2. **Bot listening**: send `/help` in Telegram — immediate reply.
3. **Manual Job trigger works**: run the Job manually from the Northflank
   dashboard (or wait for schedule) and confirm:
   - New rows appear in Supabase's `jobs` table.
   - Jobs meeting `MINIMUM_MATCH_SCORE` arrive as Telegram messages.
   - The Job's logs show `Job discovery run finished: COMPLETED`.
4. **Restart-recovery guarantee**: trigger the Job again immediately.
   `jobs_duplicate` should match the previous run's `jobs_new`, and no
   duplicate Telegram messages should arrive.
5. **Scheduled run actually fires**: after the next scheduled time passes,
   check the Job's **Runs** tab in Northflank for a new completed run, and
   your own `agent_runs` table in Supabase for a matching row.

At this point: Supabase holds all persistent state, your FastAPI service is
live, the Telegram poller is actively listening, and the Job runs
discovery unattended on your chosen cadence — all inside Northflank, built
from one shared Docker image.

## Troubleshooting

- **Job command fails immediately** → check the Job's logs; confirm the
  Secret Group is attached (missing `SUPABASE_URL`/`SUPABASE_KEY` will
  raise `SupabaseNotConfiguredError`).
- **`PGRST125` / "Invalid path"** → `SUPABASE_URL` has a trailing slash or
  `/rest/v1` suffix; fix in the Secret Group (also auto-normalized by
  `app/config.py`, but fix at the source).
- **Bot not responding** → confirm Service #2 is actually running (check
  its logs for "Starting Telegram polling loop"); make sure no second
  instance of the poller is running elsewhere (local machine, another
  environment) causing a `getUpdates` conflict.
- **Job runs but nothing gets notified** → check `MINIMUM_MATCH_SCORE`,
  your `preferred_roles`/skills in Supabase, and that
  `config/candidate_skills.json` was synced via `scripts/sync_skills.py`
  before deployment.
- **Wrong local time for the schedule** → remember Northflank Job cron
  schedules run in UTC; convert from your `APP_TIMEZONE`.
- **Google Sheets `403`/API-disabled** → share the sheet with the service
  account's `client_email` as Editor, and enable the Sheets API in Google
  Cloud Console; or simply leave Sheets unconfigured (it's optional).

For local development and the full command reference, see `HOW_TO_RUN.md`
and `README.md`. For the alternative Supabase-Cron-based deployment
pattern, see `SUPABASE_DEPLOYMENT.md`.
