# 🚀 Job Application Agent

A personal, AI-powered assistant that hunts for jobs, scores them against your resume, and tracks your applications straight from Telegram! 🤖💼

The system **never automatically submits applications** and **never stores or automates LinkedIn credentials** — you always apply manually and simply tell the bot when you're done. Your data, your control! 🛡️

---

## 🌟 What makes this awesome? (Key Features)

- 🧠 **Built-in Local ATS Checker**: No need to pay for resume scanners! Just send your resume to the bot, and whenever you see a job you like (via the `/resume` command), it acts like a strict ATS scanner. It tells you exactly what skills you're missing and drafts a tailored resume for you!
- 🔀 **Quota-Aware AI Failovers**: Google Gemini, NVIDIA NIM, and Groq are arranged in fallback chains. Rolling request-per-minute limits and HTTP 429 cooldowns route work to the next available provider without repeatedly calling one that is already throttled.
- 🚫 **Conservative Job Filtering**: Jobs must match one of your configured role families and pass fresher/experience, India/location, and minimum-score gates before reaching Telegram or Google Sheets. Rejected jobs are still saved in Supabase for history and auditing, but they do not consume semantic-matching quota when a deterministic gate already fails.
- 📊 **Beautiful Google Sheets**: Every matched job is magically logged to a Master sheet *and* a daily tab (like `2026-08-25`), complete with auto-formatting, frozen headers, and color-coded styling. 
- 🌍 **Broad API Coverage**: Jobicy, Arbeitnow, RemoteOK, Remotive, Working Nomads, Himalayas, and We Work Remotely are enabled by default, alongside configured Greenhouse, Lever, and Ashby company boards. No browser scraping is required.
- 🛡️ **Crash-Proof**: If your computer goes to sleep mid-run, no worries! It picks up right where it left off without duplicating jobs.
- 🔐 **Safer Operational Logging**: Structured logs redact sensitive fields, while low-level HTTP request logging is suppressed so Telegram and Gemini credentials embedded in request URLs are not written to the console or log files.

---

## 🕹️ How it Works

**Everyday usage:** 
1. Run `scripts/run_discovery.py` on your computer 2-3 times a day to hunt for new jobs. 
2. Run `scripts/telegram_polling.py` whenever you want to chat with the bot and manage your applications.
*No hosting platform, cron job, or always-on server required!*

```text
You -> scripts/run_discovery.py -> 💾 Supabase (Saves the jobs)
                                -> 📊 Google Sheets (Logs them beautifully)
                                -> 📱 Telegram (Pings you the best ones!)
```

Each run scans public sources, normalizes and deduplicates jobs, and stores every new posting in Supabase. Delivery is stricter: a job reaches Sheets and the prioritized Telegram digest only when it passes the configured role, fresher, location, and score gates. Optional LLM semantic skill matching runs only after the deterministic eligibility checks pass.

---

## 📱 Telegram Commands

You can control everything directly from Telegram. 

| Command | What it does 🛠️ |
|---|---|
| `/start`, `/help` | Says hello and lists commands |
| `/today`, `/jobs`, `/job <id>` | Browse jobs discovered today |
| `/done <id>` | Mark a job as applied (after you do it manually!) |
| `/skip <id>` | Skip a job you don't like |
| `/status <id>`, `/applied`, `/stats` | Track your interview pipeline |
| `/interview <id>`, `/offer <id>`, etc | Move jobs through the hiring stages |
| `/setresume <text>` | Save a new master resume to your database |
| `/resume <id>` | **Run the ATS Checker!** Analyzes your resume fit for a specific job |
| `/approveresume <id>` | Approve a tailored resume draft |

---

## 🏗️ Project Structure

Curious about the code? Here is the layout:
* `app/jobs/` - The core engine that discovers, dedups, and matches jobs.
* `app/telegram/` - Everything related to chatting with you.
* `app/llm/` - The AI brain that routes between Gemini, Groq, and NVIDIA.
* `app/sheets/` - The magic that keeps your spreadsheets looking pretty.
* `tests/` - 200+ offline tests ensuring the bot never breaks! 🧪
* `explanation/` - Module-by-module architecture notes, engineering decisions, and interview-oriented explanations.

---

## ⚙️ Setup & Environment Variables

Here are the most important ones:
* `SUPABASE_URL` / `SUPABASE_KEY` - Connects to your free Supabase database.
* `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` - Connects to your personal bot.
* `GEMINI_API_KEY`, `NVIDIA_NIM_API_KEY`, `GROQ_API_KEY` - Your AI brains (All optional! The bot still works without them!)
* `GROQ_MODELS` - Pass a comma-separated list of models (e.g., `openai/gpt-oss-120b,openai/gpt-oss-20b`) to bypass daily rate limits!
* `MINIMUM_MATCH_SCORE` - Only jobs scoring above this (e.g. `80`) will ping your phone.

---

## 🧹 Fresh-Start Reset

To clear operational job-search history and rebuild the Google Sheet while preserving candidate profiles, job preferences, and master resumes:

```powershell
python scripts/reset_environment.py --confirm RESET
```

The explicit confirmation is required because the operation is destructive. It deletes tracked jobs and dependent application data in bounded batches, clears independent run/analytics records, attempts to remove Telegram messages whose IDs were recorded, recreates a clean `Jobs` sheet, and verifies the final database and workbook state. Telegram cannot enumerate arbitrary chat history and may reject deletion of older messages.

---

For the practical step-by-step everyday workflow, check out **`DAILY_RUN.md`**. For a fuller local-setup walkthrough, see **`HOW_TO_RUN.md`**. The module-by-module technical guide is in **`explanation/README.md`**. Happy hunting! 🏹💼
