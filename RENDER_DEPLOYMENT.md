# Deploying to Render — Full Active Deployment Guide

This guide gets the whole system **actively running** on Render: Supabase
stays the database (source of truth), and Render hosts the FastAPI app,
the Telegram poller, and the scheduled discovery run — all from the same
Docker image.

## Architecture on Render

```
Supabase (Postgres - source of truth, no Supabase Cron needed)
        ^
        |
        |----------------------------------------------------------
        |                          |                               |
   Web Service                Background Worker                Cron Job
   FastAPI app                Telegram poller                  job discovery
   uvicorn app.main:app       python scripts/                  python scripts/
   (binds to $PORT,           telegram_polling.py               run_discovery.py
    /health endpoint)         (always-on, no port needed)       (scheduled, direct
                                                                  command execution,
                                                                  runs in UTC)
```

Render's **Cron Jobs** run a container on a schedule and execute a command
directly (like Northflank Jobs) — no HTTP hop needed. Render also
guarantees at most one run of a given cron job is active at a time, so
overlapping discovery runs are never a concern.

> **Free tier note:** Render's Free compute plan officially covers **Web
> Services, Render Postgres, and Render Key Value** only. Background
> Workers and Cron Jobs are billed compute (Cron Jobs have a $1/month
> minimum, prorated by the second for actual run time). Check your Render
> dashboard for current plan availability before assuming free hosting for
> the worker/cron pieces - pricing and free-tier scope can change.

---

## Step 1 — Supabase setup (unchanged, still the source of truth)

1. Create a Supabase project → note the **Project URL** and **service_role key**.
2. In the SQL Editor, run `supabase/migrations/0001_init.sql`, then
   `supabase/migrations/0002_related_skills.sql` (both idempotent).
3. `SUPABASE_URL` must be just the base URL (`https://xxxxx.supabase.co`) —
   no trailing slash, no `/rest/v1` (causes a `PGRST125` error).
4. RLS stays disabled — only your trusted backend (service_role key) talks
   to Supabase. No Supabase Cron needed here; Render's own Cron Job
   scheduler replaces that role entirely.

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

These `config/*.json` files are git-ignored and stay local — they don't
need to be part of what gets pushed to Git/Render. The scripts only need
to run once (or whenever you update your details) to push data into
Supabase, which is what the running app actually reads from.

## Step 3 — Push this repo to a Git provider

Render builds from a linked GitHub/GitLab/Bitbucket repository. Push this
project there if it isn't already, with a real `.env` **not** committed
(already git-ignored).

## Step 4 — Set up environment variables and secrets once

Render lets you create an **Environment Group** and link it to multiple
services, so you configure credentials once and reuse them across the Web
Service, Background Worker, and Cron Job below.

1. In the Render Dashboard → **Environment Groups** → **New Environment Group**.
2. Add every variable from `.env.example`:
   ```
   SUPABASE_URL
   SUPABASE_KEY
   TELEGRAM_BOT_TOKEN
   TELEGRAM_CHAT_ID
   LLM_PROVIDER
   LLM_API_KEY
   LLM_MODEL
   GOOGLE_SHEETS_SPREADSHEET_ID
   APP_TIMEZONE
   LOG_LEVEL
   SCHEDULER_SECRET
   MINIMUM_MATCH_SCORE
   ```
   Render supports multi-line/quoted values directly in the dashboard, so
   pasting a long API key or token is fine.
3. **Google service account credentials** - Render has a dedicated
   **Secret Files** feature (Environment tab → Secret Files) for exactly
   this case: upload your service account JSON key as a file (e.g. named
   `google_service_account.json`), and Render mounts it into the
   container's filesystem at a path you choose (e.g.
   `/etc/secrets/google_service_account.json`). Then set
   `GOOGLE_SERVICE_ACCOUNT_FILE=/etc/secrets/google_service_account.json`
   as a regular environment variable in the same group. This avoids
   needing the `GOOGLE_SERVICE_ACCOUNT_JSON` env-var fallback at all, but
   that fallback still works too if you prefer pasting raw JSON into an
   env var instead.
4. Optionally set `CANDIDATE_PROFILE_JSON`, `JOB_PREFERENCES_JSON`,
   `CANDIDATE_SKILLS_JSON` the same way (as Secret Files or env vars) if
   you want to be able to re-run `setup_profile.py`/`sync_skills.py` from
   a Render shell without keeping local files.

## Step 5 — Web Service: FastAPI app

1. Render Dashboard → **New** → **Web Service**.
2. Connect your linked repository. Render detects the `Dockerfile` at the
   repo root automatically (Docker deploys are supported directly).
3. The `Dockerfile`'s `CMD` already binds to `$PORT` if Render sets it
   (falling back to `8000` otherwise), so no Start Command override is
   needed - Render automatically injects `PORT` (default `10000`) and the
   container picks it up.
4. Under **Environment**, link the Environment Group from Step 4.
5. Choose an instance type (Free is available for Web Services, subject to
   the spin-down caveat below).
6. Deploy. Once live, verify:
   ```bash
   curl https://<your-service>.onrender.com/health
   ```
   Expect `{"status":"ok","supabase":"connected","telegram":"configured"}`.

**Free-tier spin-down caveat:** a Free web service spins down after a
period of inactivity and takes a few seconds to spin back up on the next
request. This is harmless for `/health` (it just responds slower after an
idle period) but matters if you rely on hitting `/run/job-search` via an
*external* scheduler (see `SUPABASE_DEPLOYMENT.md`'s Supabase-Cron
approach) - the first request after idle time will be slow, and a very
short scheduler timeout could see it as a failure. Using Render's own
**Cron Job** (Step 7 below) avoids this entirely, since Cron Jobs run
their own container directly rather than depending on the Web Service
being awake.

## Step 6 — Background Worker: Telegram poller

1. Render Dashboard → **New** → **Background Worker**.
2. Connect the same repository/Dockerfile.
3. Override the **Start Command**:
   ```
   python scripts/telegram_polling.py
   ```
4. Link the same Environment Group from Step 4.
5. No port binding needed - background workers don't receive inbound
   traffic.
6. Deploy, then send `/help` to your bot - you should get an immediate
   reply.

Only run **one** instance of this worker - Telegram rejects concurrent
`getUpdates` long-polling clients on the same bot token. Do not scale this
service beyond 1 instance.

## Step 7 — Cron Job: scheduled job discovery

1. Render Dashboard → **New** → **Cron Job**.
2. Connect the same repository/Dockerfile.
3. Set the **Command**:
   ```
   python scripts/run_discovery.py
   ```
   Optionally pass Greenhouse board tokens as arguments, e.g.
   `python scripts/run_discovery.py stripe discord`.
4. Set the **Schedule** using cron syntax, e.g. `0 8 * * *` for daily at
   08:00. **Render Cron Jobs always run in UTC** - convert your desired
   local time (e.g. 08:00 IST = 02:30 UTC → `30 2 * * *`).
5. Link the same Environment Group from Step 4.
6. Save. Render guarantees at most one run of this job is active at a
   time (a new manual trigger cancels an in-progress run; an overlapping
   scheduled run is delayed until the active one finishes) - no need to
   configure a separate concurrency policy. Render also force-stops any
   run after 12 hours, which is far more than this job should ever need.
7. Use **Trigger Run** in the Render Dashboard to test it immediately
   without waiting for the schedule.

---

## Step 8 — Verify everything is actively running end-to-end

1. **Web Service reachable**: `curl https://<your-service>.onrender.com/health`
   → `{"status":"ok","supabase":"connected","telegram":"configured"}`.
2. **Bot listening**: send `/help` in Telegram - immediate reply.
3. **Manual Cron Job trigger works**: click **Trigger Run** and confirm in
   the job's logs:
   - `"Job discovery run finished: COMPLETED"`.
   - New rows appear in Supabase's `jobs` table.
   - Jobs meeting `MINIMUM_MATCH_SCORE` arrive as Telegram messages **and**
     appear in your Google Sheet (Sheets mirrors Telegram exactly - see
     `README.md` §6).
4. **Restart-recovery guarantee**: trigger the Cron Job again immediately.
   `jobs_duplicate` should match the previous run's `jobs_new`, and no
   duplicate Telegram messages or Sheet rows should appear.
5. **Scheduled run actually fires**: after the next scheduled UTC time
   passes, check the Cron Job's run history in the Render Dashboard for a
   new completed run, and your own `agent_runs` table in Supabase for a
   matching row.

At this point: Supabase holds all persistent state, your FastAPI Web
Service is live, the Telegram Background Worker is actively listening, and
the Cron Job runs discovery unattended on your chosen cadence - all on
Render, built from one shared Docker image.

## Troubleshooting

- **Web Service fails to bind / deploy fails with a port error** → the
  `Dockerfile`'s `CMD` already reads `$PORT` (falls back to `8000`); if you
  overrode the Start Command manually, make sure it also uses `--port
  $PORT` rather than a hardcoded port. Render only forwards traffic to the
  port defined by the `$PORT` env var.
- **`PGRST125` / "Invalid path"** → `SUPABASE_URL` has a trailing slash or
  `/rest/v1` suffix; fix it in the Environment Group (also auto-normalized
  by `app/config.py`, but cleaner to fix at the source).
- **Bot not responding** → confirm the Background Worker is actually
  running (check its logs for "Starting Telegram polling loop"); make sure
  no second poller instance is running elsewhere (local machine, another
  environment) causing a `getUpdates` conflict.
- **Cron Job command fails immediately** → check its logs; confirm the
  Environment Group is linked (missing `SUPABASE_URL`/`SUPABASE_KEY` raises
  `SupabaseNotConfiguredError`).
- **Google Sheets `403`/API-disabled** → share the sheet with the service
  account's `client_email` as Editor, and enable the Sheets API in Google
  Cloud Console; or leave Sheets unconfigured entirely (it's optional).
- **Nothing ever gets notified or synced to Sheets** → check
  `MINIMUM_MATCH_SCORE`, your `preferred_roles`/skills in Supabase, and
  that `config/candidate_skills.json` was synced via `scripts/sync_skills.py`
  before deployment.
- **Free Web Service feels slow on first request after idle time** →
  expected spin-down behavior on the Free plan; not an error. Upgrade to a
  paid instance type if this matters for your use case, or rely on the
  Cron Job (not the Web Service) for scheduled discovery, since the Cron
  Job doesn't depend on the Web Service being awake.

For local development and the full command reference, see `HOW_TO_RUN.md`
and `README.md`. For alternative deployment patterns, see
`SUPABASE_DEPLOYMENT.md` (Supabase-Cron-triggered) and
`NORTHFLANK_DEPLOYMENT.md` (Northflank Services + Jobs).
