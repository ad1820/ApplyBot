# Publishing to Supabase — Full Active Deployment Guide

This guide gets the whole system **actively running** using **only free
tiers**: Supabase as the database + scheduler, and a single free Render Web
Service (or any other host with a free always-on web tier) handling both
the Telegram bot and the job-search trigger. No paid Background Worker or
Cron Job is required anywhere.

## Important: what Supabase does and doesn't run

Supabase hosts your **Postgres database** and can **trigger scheduled HTTP
calls** (via `pg_cron` + `pg_net`), and optionally **Edge Functions**
(Deno/TypeScript). It does **not** run your Python FastAPI app - that needs
a small host with an HTTPS endpoint (Render, Railway, Fly.io, a VPS, etc.),
which Supabase Cron calls into on a schedule.

So "publishing to Supabase" in this project means:

```
Supabase (Postgres + pg_cron + pg_net)
        |
        | scheduled HTTPS POST
        v
Your deployed FastAPI Web Service  (/run/job-search)
        ^
        |
        | Telegram webhook (no separate worker needed)
        |
Telegram
```

**This is the recommended setup if your hosting plan's Background
Worker/Cron Job tiers aren't free** (e.g. Render's free tier only covers
Web Services): everything - the bot's command handling *and* the scheduled
discovery trigger - runs through the one free Web Service. Both pieces are
covered below.

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

Supabase Cron and Telegram's webhook both call your app over the public
internet, so it needs a real HTTPS URL. This is exactly what a single free
Render Web Service (or Railway/Fly.io free tier) provides - see
`RENDER_DEPLOYMENT.md` for the Render-specific click-through steps, or use
the provided `Dockerfile` on any host:

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

## Step 5 — Point Telegram's webhook at your Web Service (no worker needed)

If your host's Background Worker/Cron Job tiers aren't free (this is the
case on Render), don't run `scripts/telegram_polling.py` as a second
process at all. Instead, use the `POST /telegram/webhook` endpoint already
built into the FastAPI app - it shares the exact same
`app.telegram.handlers.dispatch_command` logic as the polling script, so
every command (`/jobs`, `/done`, `/setresume`, etc.) works identically.

Tell Telegram to deliver updates to your deployed endpoint:

```bash
curl "https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<your-deployed-host>/telegram/webhook"
```

Verify it worked:

```bash
curl "https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

You should see your URL listed with no `last_error_message`. Then send
`/help` to your bot in Telegram - you should get an immediate reply,
handled entirely by your existing Web Service with **zero additional
processes or paid tiers**.

If you ever want to switch back to polling (e.g. while developing
locally), first remove the webhook so Telegram doesn't also try to deliver
to it, then run the polling script:

```bash
curl "https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/deleteWebhook"
python scripts/telegram_polling.py
```

If you do run the polling script anywhere (e.g. locally, or on a host
where a worker process is free), only run **one** instance at a time -
Telegram rejects concurrent `getUpdates` long-polling clients on the same
bot token - and don't set a webhook at the same time, since Telegram only
delivers updates through one transport at a time. If the webhook or the
poller ever stops receiving for a while, Telegram queues messages up to a
point; resuming either transport processes the backlog with no duplicates
(the `notifications` table prevents duplicate sends for job alerts, and
command replies are simply re-dispatched).

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
- **Bot not responding (webhook mode)** → check
  `getWebhookInfo` for a `last_error_message`; confirm your Web Service is
  actually reachable and its `/telegram/webhook` endpoint returns 200; check
  your host's logs for errors during `dispatch_command`.
- **Bot not responding (polling mode)** → confirm `scripts/telegram_polling.py`
  is still running as a live process, and that no webhook is also set
  (`getWebhookInfo` should show an empty `url`) - Telegram only delivers to
  one transport at a time.
- **Nothing ever gets notified** → check `MINIMUM_MATCH_SCORE`, your
  `preferred_roles`/skills in Supabase, and that `config/candidate_skills.json`
  has been synced via `scripts/sync_skills.py`.

For local development and the full command reference, see `HOW_TO_RUN.md`
and `README.md`.
