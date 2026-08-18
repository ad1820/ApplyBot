# Publishing to Supabase — Full Active Deployment Guide

This guide gets the whole system **actively running**: Supabase as the
database + scheduler, your FastAPI app reachable over HTTPS, and the
Telegram bot always listening.

## Important: what Supabase does and doesn't run

Supabase hosts your **Postgres database** and can **trigger scheduled HTTP
calls** (via `pg_cron` + `pg_net`), and optionally **Edge Functions**
(Deno/TypeScript). It does **not** run your Python FastAPI app or a
long-lived Telegram polling process — those need a small always-on compute
host (Railway, Render, Fly.io, a VPS, etc.), which Supabase Cron calls into
on a schedule.

So "publishing to Supabase" in this project means:

```
Supabase (Postgres + pg_cron + pg_net)
        |
        | scheduled HTTPS POST
        v
Your deployed FastAPI app  (/run/job-search)
        |
        v
Telegram (via a separate always-on poller process)
```

Both pieces are covered below so everything ends up actively running.

---

## Step 1 — Create your Supabase project

1. Go to [supabase.com](https://supabase.com) → New Project.
2. Note your **Project URL** and **service_role key** (Project Settings → API).
3. `SUPABASE_URL` must be just the base URL, e.g. `https://xxxxx.supabase.co`
   — no trailing slash, no `/rest/v1` (adding either causes a `PGRST125` error).

## Step 2 — Run the database migrations

In the Supabase Dashboard → **SQL Editor** → New query:

1. Paste and run the full contents of `supabase/migrations/0001_init.sql`.
2. Paste and run the full contents of `supabase/migrations/0002_related_skills.sql`.

Both are idempotent (`if not exists`) — safe to re-run. This creates all
V1 + V2 tables: `candidate_profiles`, `job_preferences`, `jobs`,
`job_sources`, `applications`, `agent_runs`, `notifications`,
`master_resumes`, `tailored_resumes`, `cover_letters`,
`referral_assessments`, `application_questions`, `application_answers`,
`analytics_events`.

RLS is left disabled by design (only your trusted backend, using the
service_role key, talks to Supabase). Do not expose the service_role key to
any client-side code.

## Step 3 — Populate your profile, preferences, and skills

Locally (or from any machine with this repo and your `.env` configured):

```bash
cp config/candidate_profile.example.json config/candidate_profile.json
# edit config/candidate_profile.json, config/job_preferences.json, config/candidate_skills.json
python scripts/setup_profile.py
python scripts/sync_skills.py
```

This writes directly to your Supabase project via the service_role key.

## Step 4 — Deploy the FastAPI app somewhere reachable over HTTPS

Supabase Cron calls your app over the public internet, so it needs a real
HTTPS URL. Any small host works (Railway, Render, Fly.io, a VPS + reverse
proxy). Using the provided `Dockerfile`:

```bash
docker build -t job-application-agent .
docker run -d --name job-agent \
  --env-file .env \
  -v /path/to/google_service_account.json:/app/google_service_account.json:ro \
  -p 8000:8000 \
  job-application-agent
```

Put your real `.env` values on the host (see `.env.example` for every
variable) — **never bake secrets into the image**.

If your host doesn't support mounting files as volumes (e.g. some
PaaS providers), skip the `-v` flag and instead set `GOOGLE_SERVICE_ACCOUNT_JSON`
(and `CANDIDATE_PROFILE_JSON`/`JOB_PREFERENCES_JSON`/`CANDIDATE_SKILLS_JSON`
if you want those config-driven too) to the raw JSON content directly as
environment variables — the app tries the file path first and falls back
to these automatically, so either approach works without code changes.

Confirm it's reachable:

```bash
curl https://<your-deployed-host>/health
```

Expect `{"status":"ok","supabase":"connected","telegram":"configured"}`.

## Step 5 — Run the Telegram bot poller (always-on, second process)

The FastAPI container only serves HTTP endpoints — it does not listen for
Telegram messages by itself. Run this as a second always-on process
alongside it (a second container, a systemd service, or a background
worker on your host):

```bash
python scripts/telegram_polling.py
```

Verify it's alive by sending `/help` to your bot — you should get an
immediate reply. If this process ever stops, Telegram queues your messages;
restarting the poller will process the backlog with no duplicates (the
`notifications` table prevents duplicate sends).

Only run **one** poller instance at a time — Telegram rejects concurrent
`getUpdates` long-polling clients on the same bot token.

## Step 6 — Schedule discovery runs with Supabase Cron

This is the actual "publish to Supabase" piece: Supabase's Postgres
database triggers your deployed app on a schedule via `pg_cron` + `pg_net`.

### 6a. Enable the extensions

Dashboard → **Database** → **Extensions** → search and enable:
- `pg_cron`
- `pg_net`

Or via SQL Editor:

```sql
create extension if not exists pg_cron;
create extension if not exists pg_net;
```

### 6b. Schedule the job-search trigger

In the SQL Editor, replace `<your-deployed-host>` and
`<your SCHEDULER_SECRET>` with your real values, then run:

```sql
select cron.schedule(
  'daily-job-search',              -- job name (must be unique)
  '0 8 * * *',                     -- every day at 08:00 UTC (cron syntax)
  $$
  select net.http_post(
    url := 'https://<your-deployed-host>/run/job-search',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Scheduler-Secret', '<your SCHEDULER_SECRET>'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 30000
  ) as request_id;
  $$
);
```

**Note on timezone:** `pg_cron` schedules run in **UTC**, not your
`APP_TIMEZONE`. Convert your desired local time to UTC when writing the
cron expression (e.g. 08:00 IST = 02:30 UTC → `'30 2 * * *'`).

### 6c. Verify the schedule was created

```sql
select * from cron.job;
```

You should see `daily-job-search` listed with your cron expression.

### 6d. Inspect run history / debug failures

```sql
select * from cron.job_run_details
where jobname = 'daily-job-search'
order by start_time desc
limit 10;
```

If `net.http_post` calls fail (e.g. wrong URL, host unreachable, wrong
secret), you'll see the failure here even though the *database* schedule
itself succeeded — the app-level result is tracked separately in your own
`agent_runs` table.

### 6e. Change the schedule or secret later

```sql
-- Unschedule
select cron.unschedule('daily-job-search');

-- Then re-run the cron.schedule(...) block above with new values.
```

---

## Step 7 — Confirm everything is actively running end-to-end

1. **Database**: `select * from cron.job;` shows your scheduled job.
2. **App reachable**: `curl https://<your-deployed-host>/health` returns
   `{"status":"ok","supabase":"connected","telegram":"configured"}`.
3. **Bot listening**: send `/help` in Telegram — you get an immediate reply.
4. **Manual trigger works** (don't wait for the schedule):
   ```bash
   curl -X POST https://<your-deployed-host>/run/job-search \
     -H "X-Scheduler-Secret: <your SCHEDULER_SECRET>"
   ```
   Confirm new rows in the `jobs` table, and that jobs meeting
   `MINIMUM_MATCH_SCORE` arrive as Telegram messages.
5. **Restart-recovery guarantee**: trigger the same run again immediately.
   `jobs_duplicate` should equal the previous run's `jobs_new`, and you
   should receive **no** duplicate Telegram messages.
6. **Scheduled run actually fires**: after the next scheduled time passes,
   check `select * from cron.job_run_details order by start_time desc limit 5;`
   and your own `agent_runs` table for a new row.

At this point: Supabase is running the database and the schedule, your
FastAPI app is live and reachable, the Telegram poller is actively
listening, and the full pipeline (discover → score → filter → persist →
sync → notify) runs unattended on your chosen cadence.

## Troubleshooting

- **`net.http_post` extension not found** → re-run Step 6a; `pg_net` must
  be enabled in the same project.
- **Cron job runs but app never receives the call** → check
  `cron.job_run_details` for the actual HTTP response/error; verify your
  host's URL is publicly reachable (not `localhost`) and not blocked by a
  firewall.
- **`401 Invalid scheduler secret`** → the `X-Scheduler-Secret` header value
  in your `cron.schedule` SQL must exactly match `SCHEDULER_SECRET` in the
  app's `.env`.
- **`PGRST125` / "Invalid path"** → `SUPABASE_URL` has a trailing slash or
  `/rest/v1` suffix; fix in `.env` (also auto-normalized by `app/config.py`).
- **Bot not responding** → confirm `scripts/telegram_polling.py` is still
  running as a live process; check `getUpdates` for a growing backlog as a
  sign nothing is consuming it.
- **Nothing ever gets notified** → check `MINIMUM_MATCH_SCORE`, your
  `preferred_roles`/skills in Supabase, and that `config/candidate_skills.json`
  has been synced via `scripts/sync_skills.py`.

For local development and the full command reference, see `HOW_TO_RUN.md`
and `README.md`.
