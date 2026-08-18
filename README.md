# Job Application Agent

A personal, single-user AI-powered job-search and application-tracking assistant.
Telegram is the primary interface; FastAPI + Supabase/PostgreSQL is the backend.
The system **never automatically submits applications** and **never stores or
automates LinkedIn credentials** — you always apply manually and simply tell
the bot when you're done.

For a practical step-by-step "just tell me the commands" guide, see
**`HOW_TO_RUN.md`**. This file explains what the system does (Part 1) and
how to deploy it for real, always-on production use (Part 2).

---

# Part 1 — Functionality

## 1. Overview

```
Telegram Bot -> FastAPI -> Application/Job Services -> Supabase (source of truth)
                                                      -> Google Sheets (reporting only)
```

The agent runs on a schedule (or on demand), discovers jobs from public,
permitted sources, scores them deterministically against your real skills
and preferences, filters out irrelevant/low-fit postings, and only pushes a
Telegram alert for jobs that clear a strict match threshold. You apply
manually; the bot just tracks the full lifecycle from there.

Project layout:

```
app/
  main.py            FastAPI app (health, scheduled trigger, telegram webhook)
  config.py          Environment-driven settings (pydantic-settings)
  logging_config.py  Structured logging with secret redaction
  db/                Supabase client + one repository per table
  jobs/              Job model, JobSource abstraction, dedup, matcher
  telegram/          Bot client, message templates, command handlers
  sheets/            Google Sheets sync (best-effort, never a hard dependency)
  llm/               LLMProvider abstraction (OpenAI / Anthropic / Null)
  services/          JobSearchService - orchestrates a full discovery run
  agents/            V2: resume, cover letter, referral, application, analytics
supabase/migrations/ SQL schema (V1 + V2 tables)
config/              candidate_profile.json, job_preferences.json, candidate_skills.json
scripts/             setup_profile.py, sync_skills.py, telegram_polling.py
tests/               pytest suite (all offline, no live credentials needed)
```

## 2. Job Discovery

- Modular `JobSource` abstraction (`app/jobs/discovery.py`) — no scraping of
  platforms that prohibit it, only genuine public APIs/RSS feeds:
  - `GreenhouseSource` — any company's public Greenhouse board (opt-in via board tokens)
  - `RemoteOKSource`, `RemotiveSource`, `WorkingNomadsSource`, `HimalayasSource`, `WeWorkRemotelySource`
  - `UserProvidedSource` — manually paste in a job yourself
- `default_sources()` bundles all the public aggregators; pass
  `greenhouse_boards=[...]` to also include specific companies.
- Deterministic deduplication (`app/jobs/deduplicator.py`) — canonical key
  from normalized company + title + location + external ID + URL, not URL
  equality alone. Duplicate postings from multiple sources are merged, not
  re-created (`job_sources` table preserves the source history).

## 3. Job Matching & Filtering

All scoring is deterministic (`app/jobs/matcher.py`) — the system works
fully without any LLM configured:

- **Skill matching** — exact matches score fully; adjacent/related skills
  (from `app/jobs/skills_taxonomy.py`, e.g. PyTorch ↔ scikit-learn) score
  partial credit; an optional LLM fallback can grant the same partial
  credit for skills the taxonomy doesn't cover, but never full credit for
  something you don't actually have.
- **Role/title relevance** — job titles are matched against your
  `preferred_roles` using fuzzy word-overlap; mismatched roles (e.g. Sales
  postings on an engineering-heavy company board) are flagged and scored
  down, not blindly notified.
- **Location/visa relevance** — rewards India-based and remote postings, or
  postings that explicitly mention visa/relocation sponsorship; penalizes
  onsite-abroad postings with no such signal.
- **Seniority/fresher relevance** — penalizes Senior/Staff/Lead/Manager
  titles, rewards Junior/Entry/Intern/Graduate titles, stays neutral on
  unlabeled titles. Detection is title-only with word-boundary matching (not
  substring matching against the full description) to avoid false positives.
- **Minimum match threshold** (`MINIMUM_MATCH_SCORE`, default 80) — jobs
  below this are still persisted (visible via `/jobs`) but never pushed as a
  Telegram notification.

## 4. Persistence & Restart Recovery

Supabase/Postgres is the single source of truth — nothing relies on
in-memory state:

- `agent_runs` — every discovery run is tracked (`RUNNING` → `COMPLETED` /
  `FAILED` / `PARTIAL`); a crash mid-run is safely resumable, and re-running
  never creates duplicate jobs.
- `notifications` — every Telegram send is tracked so a restart never
  results in duplicate alerts for the same job.
- Explicit job status state machine (`DISCOVERED → NOTIFIED →
  INTERESTED/SKIPPED → APPLIED → INTERVIEW → REJECTED/OFFER/WITHDRAWN`),
  persisted and validated against allowed transitions.
- Per-job and per-source failure isolation — one bad job or one dead source
  never aborts the whole run.

All commands (handlers in `app/telegram/handlers.py`, dispatched by
`scripts/telegram_polling.py`):

| Command | Purpose |
|---|---|
| `/start`, `/help` | Intro / command list |
| `/today`, `/jobs`, `/job <id>` | Browse discovered jobs |
| `/done <id>` | Mark a job as applied (after you apply manually) |
| `/skip <id>` | Skip a job |
| `/status <id>`, `/applied`, `/stats` | Track your pipeline |
| `/interview <id>`, `/rejected <id>`, `/offer <id>`, `/withdraw <id>` | Update application stage |
| `/setresume <text>` | Save a new, versioned master resume (never overwrites old versions) |
| `/resume <id>` | Analyze resume fit against a job (never fabricates skills) |
| `/approveresume <id>` | Approve a tailored resume draft |

Job notifications include the match score, strong/related/missing skills,
concerns, and an inline "Apply" button linking directly to the posting. The
bot never submits anything on your behalf. All message content is
HTML-escaped before sending, so dynamic job titles/company names can never
break message delivery.

## 6. Google Sheets Sync (optional, reporting-only)

Best-effort sync to a spreadsheet (Date Found, Company, Role, Location,
Work Mode, Match Score, Status, Application Date, Resume Version, Referral
Potential, Job URL, Notes). Sheets deliberately **mirrors exactly what gets
pushed to Telegram**: only jobs that clear both the role-match filter and
`MINIMUM_MATCH_SCORE` are synced — every job is still persisted in Supabase
regardless of score (visible via `/jobs`), but the Sheet and Telegram only
ever show the same, genuinely strong matches. If Sheets is unconfigured or
the API call fails, the core pipeline is completely unaffected — Sheets is
never a hard dependency or the source of truth.

## 7. LLM Provider Abstraction (V2)

`app/llm/` defines an `LLMProvider` interface with `OpenAIProvider`,
`AnthropicProvider`, and a `NullProvider` (default — zero LLM calls,
deterministic matching still fully functional). All job-search-related
prompts live in one place: `app/llm/prompts.py`. Every prompt explicitly
forbids fabricating skills, jobs, degrees, certifications, or experience —
the LLM is only ever a secondary, bounded opinion; deterministic code always
makes the final call.

## 8. V2 — Resume, Cover Letter, Referral, Application Assistant

- **Master resume** — versioned (`master_resumes` table), never overwritten;
  every tailored resume references the exact version it was derived from.
- **Resume Agent** — deterministic skills-gap analysis + optional LLM
  phrasing/ordering suggestions; explicitly told to flag missing skills
  rather than paper over them.
- **Cover Letter Agent** — LLM-generated, grounded only in real resume/profile content.
- **Referral Agent** — heuristic HIGH/MEDIUM/LOW referral potential + a
  draft message for you to review and send yourself (never auto-sent).
- **Application Assistant** — `ApplicationAdapter` per platform (Greenhouse,
  Lever, Ashby, generic fallback) to extract application-form questions.
- **Answer Engine** — classifies questions into Profile Fact / Derived Fact /
  Generative / Sensitive. Sensitive/ambiguous questions (salary, visa,
  relocation, etc.) are *never* guessed — asked of you once, then reused via
  `application_answers` on future applications.
- **Analytics** — simple statistics (application/interview/offer rates,
  breakdowns by role/location/tech/match-score bucket) — no ML.

## 9. Security & Safety Guarantees

- No LinkedIn credentials are ever stored or used; no LinkedIn automation.
- No autonomous application submission — every application is manual.
- Referral messages and cover letters are drafted for human review only.
- Sensitive/ambiguous application questions are never guessed.
- The Resume/Cover-Letter/Answer agents are explicitly instructed to never
  fabricate skills, jobs, degrees, certifications, or experience.
- `.env` and `config/candidate_profile.json` (contains PII) are git-ignored.
- Structured logs redact tokens/keys/passwords and avoid unnecessary PII.

## 10. Testing

`tests/` (160+ tests, fully offline against an in-memory fake Supabase
client and mocked LLM/HTTP transports — no live credentials required)
covers: job normalization, deduplication, deterministic scoring (skills,
role, location/visa, seniority), status transitions, notification
idempotency, full restart-recovery (`run -> crash -> restart -> continue`),
per-job/per-source failure isolation, Google Sheets failure resilience,
malformed job data, LLM failure fallback, application-answer
classification, and Telegram message HTML-safety.

```powershell
.\venv\Scripts\python -m pytest -v
```

---

# Part 2 — Production Setup

This section covers deploying the agent so it runs unattended: a scheduled
discovery job, an always-listening Telegram bot, and persistent state that
survives restarts/redeploys. See `HOW_TO_RUN.md` for local development.

Two platform-specific, copy-paste-ready deployment guides are also
available:
- **`SUPABASE_DEPLOYMENT.md`** — schedule discovery via Supabase Cron
  (`pg_cron`/`pg_net`) calling your app's HTTP endpoint.
- **`NORTHFLANK_DEPLOYMENT.md`** — host the FastAPI app, Telegram poller,
  and scheduled discovery entirely on Northflank (Services + a native Cron
  Job running `scripts/run_discovery.py` directly, no HTTP hop needed).

## 11. Prerequisites for Production

- A hosting platform that can run a Docker container or a Python process
  continuously (Railway, Render, Fly.io, a VPS, etc.) for the FastAPI app
  and the Telegram poller.
- A production Supabase project (the free tier works fine for a single user).
- A dedicated Telegram bot (via @BotFather) — don't reuse a dev/test bot token.
- (Recommended) An LLM API key (OpenAI or Anthropic) for semantic skill
  matching and resume/cover-letter generation.
- (Optional) A Google Cloud service account for Sheets sync.
- A scheduler that can make an authenticated HTTPS POST on a cadence
  (Supabase Cron, a cron job on your host, GitHub Actions, cron-job.org, etc.).

## 12. Environment Variables (production values)

Copy `.env.example` to `.env` (or set these as real environment variables /
secrets in your hosting platform — **never bake secrets into the Docker
image**):

| Variable | Production guidance |
|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | Use the **service_role** key. Base URL only — no trailing slash, no `/rest/v1` (see `PGRST125` note below). |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | A dedicated production bot token. |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | Set a real provider (`openai`/`anthropic`) for full V2 functionality; `null` still works for V1-only deterministic matching. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Mount the JSON key file into the container (e.g. as a secret file) and point this at its in-container path. |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Your production tracking spreadsheet ID. |
| `MINIMUM_MATCH_SCORE` | Tune to taste; 80 is strict by design. |
| `SCHEDULER_SECRET` | A long random string — required to prevent unauthenticated callers from triggering `/run/job-search`. Generate with `openssl rand -hex 32` or similar. |
| `APP_TIMEZONE` | Your real timezone, e.g. `Asia/Kolkata`. |
| `LOG_LEVEL` | `INFO` in production; avoid `DEBUG` long-term (verbose). |

## 13. Database Setup (production Supabase project)

1. Create a **separate Supabase project for production** (don't share with
   a dev/test project).
2. In the SQL Editor, run `supabase/migrations/0001_init.sql`, then
   `supabase/migrations/0002_related_skills.sql`, in order. Both are
   idempotent (`if not exists`).
3. RLS is left disabled by design — only the trusted backend (service role
   key) talks to Supabase. Never expose the service role key to any
   client-side code or public endpoint.

## 14. Set Your Profile, Preferences, and Skills

Before your first production run, populate your real data (see Part 1 for
the underlying tables):

```bash
cp config/candidate_profile.example.json config/candidate_profile.json
# edit config/candidate_profile.json, config/job_preferences.json, config/candidate_skills.json
python scripts/setup_profile.py
python scripts/sync_skills.py
```

Send your resume once the bot is live: `/setresume <paste your resume text>`.

## 15. Build and Run with Docker

```bash
docker build -t job-application-agent .
docker run -d --name job-agent \
  --env-file .env \
  -v /path/to/google_service_account.json:/app/google_service_account.json:ro \
  -p 8000:8000 \
  job-application-agent
```

The image runs the FastAPI app (`app.main:app`) on port 8000, exposing
`/health`, `/run/job-search`, and `/telegram/webhook`. The `Dockerfile`
copies `app/`, `scripts/`, `supabase/`, and `config/` — mount your real
`.env` and Google service-account file as shown above rather than baking
them into the image.

## 16. Run the Telegram Bot Process

The FastAPI container serves HTTP endpoints only — it does **not** by
itself listen for Telegram messages. You need one more always-running
process for that. Two options:

**Option A — Long-polling worker (simplest)**

Run `scripts/telegram_polling.py` as a second, always-on process (e.g. a
second container, a systemd service, or a background worker on your
hosting platform):

```bash
python scripts/telegram_polling.py
```

This is the same script used in local development — it long-polls Telegram
and dispatches every command. If it stops, restart it; there is no message
loss risk because Telegram queues unfetched updates and this project's
notification tracking (`notifications` table) prevents any duplicates once
it resumes.

**Option B — Webhook (more production-idiomatic)**

Point Telegram's webhook at your deployed `POST /telegram/webhook`
endpoint:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-host>/telegram/webhook"
```

Note: as shipped, `app/main.py`'s webhook handler only acknowledges receipt
— full command dispatch through `app.telegram.handlers` currently only runs
in the polling script. If you choose the webhook route, wire the same
`dispatch()` logic from `scripts/telegram_polling.py` into
`telegram_webhook()` in `app/main.py` before relying on it in production.
Option A works out of the box with no changes.

## 17. Schedule Job Discovery

Point any scheduler at your deployed instance:

```
POST https://<your-host>/run/job-search
Header: X-Scheduler-Secret: <your SCHEDULER_SECRET>
```

- **Supabase Cron** (via `pg_cron` + `pg_net`, or a Supabase Edge Function
  on a schedule) calling the above endpoint.
- **A cron job** on your host: `0 8 * * * curl -X POST ... -H "X-Scheduler-Secret: ..."`.
- **GitHub Actions** scheduled workflow, or any third-party cron-as-a-service.

Pick a cadence appropriate for the sources you use (e.g. once or twice
daily) — remember RemoteOK/Remotive/etc. have their own rate-limit
expectations (see `app/jobs/discovery.py` docstrings). Every run is
idempotent, so more frequent runs are safe but wasteful, not harmful.

## 18. Verify the Deployment

```bash
curl https://<your-host>/health
```

Expect `{"status":"ok","supabase":"connected","telegram":"configured"}`.
Then trigger one discovery run manually and confirm:
1. New jobs appear in Supabase (`jobs` table) and, if configured, your
   Google Sheet.
2. Jobs meeting your `MINIMUM_MATCH_SCORE` arrive as Telegram messages.
3. `/jobs`, `/stats`, etc. respond correctly from your Telegram client.
4. Re-triggering the same run produces `jobs_duplicate` equal to the
   previous run's `jobs_new`, and no duplicate Telegram messages — this is
   the mandatory restart-recovery guarantee.

## 19. Operational Notes

- **Logs** are structured JSON (see `app/logging_config.py`) with secrets
  redacted — safe to forward to any log aggregator.
- **Failure isolation** — one bad job or one dead source never aborts a
  run; check `agent_runs.error_message` for partial-failure details.
- **Google Sheets outages** never block the pipeline — check
  `agent_runs`/application logs for sync failures and re-sync manually if
  needed; Sheets is not the source of truth.
- **Rotating secrets** — if you rotate `TELEGRAM_BOT_TOKEN`,
  `SUPABASE_KEY`, or `LLM_API_KEY`, update `.env` and restart both the
  FastAPI process and the polling process.
- **Scaling** — this is designed for a single user; do not point multiple
  Telegram polling processes at the same bot token simultaneously (Telegram
  rejects concurrent `getUpdates` long-polling clients).

## 20. Production Troubleshooting

- **`PGRST125` / "Invalid path"** → `SUPABASE_URL` has a trailing slash or
  `/rest/v1` suffix; also auto-normalized in `app/config.py`, but fix at the source.
- **Telegram bot not responding** → confirm the polling process (or webhook)
  is actually running; check `getUpdates` for a growing backlog as a sign
  nothing is consuming it.
- **Google Sheets `403`/API-disabled** → share the sheet with the service
  account's `client_email` as Editor, and enable the Sheets API in Google
  Cloud Console.
- **Nothing ever gets notified** → check `MINIMUM_MATCH_SCORE`, your
  `preferred_roles`/skills in Supabase, and that `config/candidate_skills.json`
  has actually been synced via `scripts/sync_skills.py`.

For a full step-by-step local setup walkthrough, see **`HOW_TO_RUN.md`**.
