# ApplyBot

AI-assisted job discovery and application tracking through Telegram, with configurable filtering, resume matching, Supabase persistence, and Google Sheets reporting.

> ApplyBot does not submit applications or store LinkedIn credentials. It helps discover, evaluate, and track opportunities while keeping the final application step under the user's control.

## Highlights

- Aggregates roles from public job APIs and configured Greenhouse, Lever, and Ashby boards
- Applies deterministic role, experience, location, and score gates before using LLM quota
- Scores jobs against a candidate profile and produces resume-tailoring suggestions
- Routes AI requests across Gemini, NVIDIA NIM, and Groq with quota-aware fallbacks
- Deduplicates jobs and resumes safely after interrupted runs
- Tracks application stages through Telegram and logs qualified roles to Google Sheets
- Redacts sensitive values from operational logs
- Includes 200+ offline tests

## Architecture

```text
Job APIs and ATS boards
          |
          v
 Discovery -> normalization -> deduplication -> eligibility filters
                                              |
                                              v
                                    optional semantic matching
                                              |
                    +-------------------------+-------------------------+
                    |                         |                         |
                 Supabase                Google Sheets              Telegram
              source of truth             reporting              interaction
```

Core modules:

- `app/jobs/` — discovery, normalization, filtering, scoring, and deduplication
- `app/llm/` — provider routing, rate-limit handling, and resume analysis
- `app/telegram/` — commands and application workflow
- `app/sheets/` — formatted workbook output
- `supabase/migrations/` — database schema
- `tests/` — offline unit and integration coverage

## Quick start

### Prerequisites

- Python 3.10+
- A Supabase project
- A Telegram bot
- Optional Google Sheets and LLM-provider credentials

### Installation

```bash
git clone https://github.com/ad1820/ApplyBot.git
cd ApplyBot
python -m venv .venv
```

Activate the environment and install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then add the credentials required for the integrations you want to enable. See [HOW_TO_RUN.md](HOW_TO_RUN.md) for the complete configuration walkthrough.

Run discovery:

```bash
python scripts/run_discovery.py
```

Start the Telegram interface:

```bash
python scripts/telegram_polling.py
```

## Telegram commands

| Command | Purpose |
|---|---|
| `/today`, `/jobs`, `/job <id>` | Browse discovered jobs |
| `/done <id>`, `/skip <id>` | Record an application decision |
| `/status <id>`, `/applied`, `/stats` | Review application progress |
| `/interview <id>`, `/offer <id>` | Move an application through the pipeline |
| `/setresume <text>` | Store the master resume |
| `/resume <id>` | Analyze resume fit for a job |
| `/approveresume <id>` | Approve a tailored-resume draft |

## Testing

The test suite is designed to run without live external services:

```bash
pytest
```

## Responsible use

ApplyBot is an assistant, not an autonomous applicant. Review generated resume content for accuracy, verify job details at the original source, and submit applications manually. Keep credentials in local environment variables and never commit a populated `.env` file.

## Documentation

- [Daily workflow](DAILY_RUN.md)
- [Complete setup guide](HOW_TO_RUN.md)
- [Architecture and engineering notes](explanation/README.md)
