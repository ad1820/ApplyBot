# Job Application Agent

A personal, single-user AI-powered job-search and application-tracking assistant.
Telegram is the primary interface; FastAPI + Supabase/PostgreSQL is the backend.
The system **never automatically submits applications** and **never stores or
automates LinkedIn credentials** — you always apply manually and simply tell
the bot when you're done.

**Everyday usage:** run `scripts/run_discovery.py` yourself 2-3 times a day
(whenever convenient) to find and score new jobs, and
`scripts/telegram_polling.py` whenever you want the bot to respond to your
commands. No hosting platform, cron job, or always-on server required. See
**`DAILY_RUN.md`** for the practical step-by-step version of this workflow.
See **`HOW_TO_RUN.md`** for a fuller local-setup walkthrough. This file
covers what the system does (Part 1) and optional always-on/hosted
deployment if you ever want it (Part 2).

---

# Part 1 — Functionality

## 1. Overview

```
You, whenever convenient -> scripts/run_discovery.py -> Supabase (source of truth)
                                                       -> Google Sheets (reporting only)
                                                       -> Telegram (alerts)

You, whenever you want    -> scripts/telegram_polling.py -> Telegram (commands: /jobs, /done, ...)
```

Each discovery run discovers jobs from public, permitted sources, scores
them deterministically against your real skills and preferences, filters
out irrelevant/low-fit postings, and only pushes a Telegram alert + Google
Sheet row for jobs that clear a strict match threshold. You apply
manually; the bot just tracks the full lifecycle from there.

Project layout:

```
app/
  main.py            FastAPI app (health, /run/job-search, /telegram/webhook - optional, see Part 2)
  config.py          Environment-driven settings (pydantic-settings)
  logging_config.py  Structured logging with secret redaction
  json_config.py     File-or-env-JSON loader for candidate config + Google credentials
  db/                Supabase client + one repository per table
  jobs/              Job model, JobSource abstraction, dedup, matcher, skills taxonomy
  telegram/          Bot client, message templates, command handlers, shared dispatcher
  sheets/            Google Sheets sync (best-effort, never a hard dependency)
  llm/               LLMProvider interface, ProviderChain (failover), GeminiProvider,
                     NvidiaNIMProvider, GroqProvider, NullProvider + shared prompts
  services/          JobSearchService - orchestrates a full discovery run
  agents/            V2: resume, cover letter, referral, application, analytics
supabase/migrations/ SQL schema (V1 + V2 tables)
config/              candidate_profile.json, job_preferences.json, candidate_skills.json
scripts/             run_discovery.py, telegram_polling.py, setup_profile.py, sync_skills.py
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
  Telegram notification or synced to Google Sheets.

## 4. Persistence & Restart Recovery

Supabase/Postgres is the single source of truth — nothing relies on
in-memory state:

- `agent_runs` — every discovery run is tracked (`RUNNING` → `COMPLETED` /
  `FAILED` / `PARTIAL`); a crash mid-run is safely resumable, and re-running
  never creates duplicate jobs.
- `notifications` — every Telegram send is tracked so re-running discovery
  never results in duplicate alerts for the same job.
- Explicit job status state machine (`DISCOVERED → NOTIFIED →
  INTERESTED/SKIPPED → APPLIED → INTERVIEW → REJECTED/OFFER/WITHDRAWN`),
  persisted and validated against allowed transitions.
- Per-job and per-source failure isolation — one bad job or one dead source
  never aborts the whole run.

## 5. Telegram Bot

All commands (handlers in `app/telegram/handlers.py`, dispatched via
`dispatch_command()` — used identically by `scripts/telegram_polling.py`
and, if you ever deploy this, `POST /telegram/webhook`):

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

## 7. LLM Provider Architecture

`app/llm/` defines an `LLMProvider` interface and a `ProviderChain` that
provides automatic failover across multiple providers. All job-search-related
prompts live in one place: `app/llm/prompts.py`. Every prompt explicitly
forbids fabricating skills, jobs, degrees, certifications, or experience —
the LLM is only ever a secondary, bounded opinion; deterministic code always
makes the final call.

### Two independent provider chains

**Agent reasoning / tool calling:**
```
Meta Muse Glimmer 30B (NVIDIA NIM)
        ↓ transient failure (429, 5xx, timeout)
Gemini 3.5 Flash-Lite
        ↓
Gemini 3.1 Flash-Lite
        ↓
Groq model
        ↓
NullProvider (safe fallback — no crash)
```

**Job search / skill matching:**
```
Deterministic matcher (always runs first — source of truth)
        │
        └── ambiguous skill relationship
                    ↓
          Gemini 3.5 Flash-Lite
                    ↓ failure
          Gemini 3.1 Flash-Lite
                    ↓ failure
          Meta Muse Glimmer 30B (NVIDIA NIM)
                    ↓ failure
                  Groq
                    ↓ failure
               NullProvider (deterministic result stands)
```

### Supported configurations

All LLM providers are **optional**. The system starts and runs fully with
no API keys configured — deterministic matching remains 100% functional:

| What you configure | Reasoning chain | Job matching chain |
|---|---|---|
| Nothing | Null | Null |
| Gemini only | Gemini primary → fallback → Null | Gemini primary → fallback → Null |
| NVIDIA NIM only | NIM → Null | NIM → Null |
| Groq only | Groq → Null | Groq → Null |
| All providers | NIM → Gemini → Gemini → Groq → Null | Gemini → Gemini → NIM → Groq → Null |

### Failover rules

Failover to the next provider happens **only** for transient errors:
- HTTP 429 (rate limit / quota exhausted)
- HTTP 5xx (server error, gateway error)
- Timeout / transient network failure

These errors do **not** trigger failover (they are logged and the chain stops):
- HTTP 401 (invalid API key) — check your credentials
- HTTP 400 (bad request) — implementation bug, should surface clearly

The surrounding job discovery pipeline always continues successfully even if
every LLM provider fails — no LLM call can crash a discovery run.

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
- `.env` and the real `config/*.json` files (contain PII/preferences) are
  git-ignored — only `*.example.json` templates are tracked.
- Structured logs redact tokens/keys/passwords and avoid unnecessary PII.

## 10. Testing

`tests/` (200+ tests, fully offline against an in-memory fake Supabase
client and mocked LLM/HTTP transports — no live credentials required)
covers: job normalization, deduplication, deterministic scoring (skills,
role, location/visa, seniority), status transitions, notification
idempotency, full restart-recovery (`run -> crash -> restart -> continue`),
per-job/per-source failure isolation, Google Sheets failure resilience,
malformed job data, LLM failure fallback, application-answer
classification, Telegram message HTML-safety, and command dispatch.

```powershell
.\venv\Scripts\python -m pytest -v
```

---

# Part 2 — Optional Always-On Deployment

**You don't need any of this.** The everyday workflow (`DAILY_RUN.md`) is
just running `scripts/run_discovery.py` and `scripts/telegram_polling.py`
yourself, 2-3 times a day, on your own machine — no hosting, no cron job,
no server that has to stay online. This section exists only for reference
if you ever *do* want it to run unattended somewhere.

## 11. Environment Variables

Copy `.env.example` to `.env` and fill in real values. **Never commit `.env`.**

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | Supabase project connection (service role key). `SUPABASE_URL` must be just the base URL (`https://xxxxx.supabase.co`), no trailing slash or `/rest/v1` — that causes a `PGRST125` error. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Your personal Telegram bot + chat to notify |
| `GEMINI_API_KEY` | Google Gemini API key (optional — used in both chains) |
| `GEMINI_PRIMARY_MODEL` | Primary Gemini model (default: `gemini-3.5-flash-lite`) |
| `GEMINI_FALLBACK_MODEL` | Fallback Gemini model (default: `gemini-3.1-flash-lite`) |
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM API key (optional — primary reasoning model) |
| `NVIDIA_NIM_MODEL` | NVIDIA NIM model (default: `meta/muse-glimmer-30b`) |
| `GROQ_API_KEY` | Groq Cloud API key (optional — last fallback in both chains) |
| `GROQ_MODEL` | Groq model to use (e.g. `openai/gpt-oss-120b`; leave blank to skip Groq) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` / `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheets sync credentials — file path (local) or raw JSON content (fallback) |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Target spreadsheet ID |
| `MINIMUM_MATCH_SCORE` | Minimum score (0-100) before a job is pushed to Telegram/Sheets. Default `82`. |
| `APP_TIMEZONE` | e.g. `Asia/Kolkata` |
| `SCHEDULER_SECRET` | Only needed if exposing `/run/job-search` over HTTP |
| `CANDIDATE_PROFILE_JSON`, `JOB_PREFERENCES_JSON`, `CANDIDATE_SKILLS_JSON` | Fallback env vars for the matching `config/*.json` files |

## 12. If you ever host this somewhere

- **FastAPI app** (`app/main.py`) exposes `GET /health`, `POST
  /run/job-search` (HTTP-triggered discovery, guarded by
  `X-Scheduler-Secret`), and `POST /telegram/webhook` (dispatches Telegram
  commands exactly like `scripts/telegram_polling.py`, so you could point
  a webhook at it instead of running the polling script).
- Both `/run/job-search` and `scripts/run_discovery.py` call the exact same
  `app.agents.job_agent.run_job_search()` — behavior is identical whether
  triggered by you locally, an HTTP call, or a scheduler.
- A `Dockerfile` is included; its `CMD` reads the `$PORT` env var if set
  (falls back to `8000`), so it adapts to platforms that assign their own
  port.
- Any external scheduler (Supabase Cron via `pg_cron`/`pg_net`, a host's
  native cron feature, GitHub Actions, etc.) can call `/run/job-search` on
  a schedule if you want fully unattended operation later. This is
  intentionally not documented in depth here since it's not how you
  currently run this — see `HOW_TO_RUN.md` if you want to explore it.

## 13. Troubleshooting

- **`PGRST125` / "Invalid path"** → `SUPABASE_URL` has a trailing slash or
  `/rest/v1` suffix; also auto-normalized in `app/config.py`, but fix at the source.
- **No Telegram replies** → `scripts/telegram_polling.py` isn't running
  right now; start it (see `DAILY_RUN.md`).
- **Nothing ever gets notified/synced to Sheets** → check
  `MINIMUM_MATCH_SCORE`, your `preferred_roles`/skills in Supabase, and
  that `config/candidate_skills.json` was synced via `scripts/sync_skills.py`.
- **Google Sheets `403`/API-disabled** → share the sheet with your service
  account's `client_email` as Editor, and enable the Sheets API in Google
  Cloud Console; or leave Sheets unconfigured entirely (it's optional).

For the everyday workflow, see **`DAILY_RUN.md`**. For a fuller local-setup
walkthrough, see **`HOW_TO_RUN.md`**.
