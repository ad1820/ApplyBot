# 🚀 Job Application Agent

A personal, AI-powered assistant that hunts for jobs, scores them against your resume, and tracks your applications straight from Telegram! 🤖💼

The system **never automatically submits applications** and **never stores or automates LinkedIn credentials** — you always apply manually and simply tell the bot when you're done. Your data, your control! 🛡️

---

## 🌟 What makes this awesome? (Key Features)

- 🧠 **Built-in Local ATS Checker**: No need to pay for resume scanners! Just send your resume to the bot, and whenever you see a job you like (via the `/resume` command), it acts like a strict ATS scanner. It tells you exactly what skills you're missing and drafts a tailored resume for you!
- 🔀 **Smart AI Failovers**: We use free, powerful AI models (Google Gemini, NVIDIA NIM, Groq). If one model hits a rate limit, the bot smoothly switches to the next one so your job hunt never crashes. 
- 🚫 **No Junk Jobs (Smart Filtering)**: The bot instantly throws away irrelevant roles (like "Senior", "Sales", or "Staff") before they even reach you, saving time and API tokens.
- 📊 **Beautiful Google Sheets**: Every matched job is magically logged to a Master sheet *and* a daily tab (like `2026-08-25`), complete with auto-formatting, frozen headers, and color-coded styling. 
- 🌍 **Tons of Open Sources**: Pulls seamlessly from dozens of open API job boards (Jobicy, Arbeitnow, RemoteOK, Remotive) and hundreds of private ATS company boards (Greenhouse, Lever, Ashby). No shady scraping required!
- 🛡️ **Crash-Proof**: If your computer goes to sleep mid-run, no worries! It picks up right where it left off without duplicating jobs.

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

Each run scans public sources, scores them deterministically against your actual skills, and filters out the noise. You only get a Telegram ping for jobs that genuinely match your profile!

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

---

## ⚙️ Setup & Environment Variables

Here are the most important ones:
* `SUPABASE_URL` / `SUPABASE_KEY` - Connects to your free Supabase database.
* `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` - Connects to your personal bot.
* `GEMINI_API_KEY`, `NVIDIA_NIM_API_KEY`, `GROQ_API_KEY` - Your AI brains (All optional! The bot still works without them!)
* `GROQ_MODELS` - Pass a comma-separated list of models (e.g., `openai/gpt-oss-120b,openai/gpt-oss-20b`) to bypass daily rate limits!
* `MINIMUM_MATCH_SCORE` - Only jobs scoring above this (e.g. `80`) will ping your phone.

For the practical step-by-step everyday workflow, check out **`DAILY_RUN.md`**. For a fuller local-setup walkthrough, see **`HOW_TO_RUN.md`**. Happy hunting! 🏹💼
