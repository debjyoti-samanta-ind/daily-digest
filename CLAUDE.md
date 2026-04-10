# Daily Digest — CLAUDE.md

## What this project does
Automated pipeline that fetches ~75 news articles from 17 RSS feeds across 5 categories, summarizes them using Gemini 2.5 Flash, and sends a styled HTML email to the recipient every morning at 8 AM PDT.

## Stack
- **digest.py** — Main Python script (fetch → summarize → format → send)
- **daily-digest.yml** — GitHub Actions workflow (triggered externally via workflow_dispatch)
- **requirements.txt** — feedparser, google-genai, python-dotenv
- **workflow.html** — Standalone HTML slide deck explaining the system design

## How it's triggered
GitHub's built-in cron scheduler is unreliable on free-tier repos (can silently skip runs). The schedule block has been removed from `daily-digest.yml`. Instead, **cron-job.org** calls the GitHub `workflow_dispatch` API every morning at 8 AM PDT (15:00 UTC) to reliably trigger the workflow.

The cron-job.org request:
- URL: `https://api.github.com/repos/debjyoti-samanta-ind/daily-digest/actions/workflows/daily-digest.yml/dispatches`
- Method: POST
- Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`
- Body: `{"ref":"main"}`

## Secrets (stored in GitHub Actions → Settings → Secrets)
| Secret | Purpose |
|--------|---------|
| `GEMINI_API_KEY` | Gemini API access |
| `GMAIL_ADDRESS` | Sender Gmail account |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not the real password) |
| `RECIPIENT_EMAIL` | Where the digest is delivered |

## News categories & sources
| Category | Sources |
|----------|---------|
| Finance | CNBC, MarketWatch, Yahoo Finance, BBC Business, Guardian Business, Axios |
| Geopolitics | NPR World, Foreign Policy, Deutsche Welle |
| Tech | Hacker News, TechCrunch, The Verge, Wired |
| Human Insights | HBR, Psychology Today, The Cut, Big Think |
| AI | TechCrunch AI, Ars Technica, Wired AI, VentureBeat AI, Anthropic Blog (only if new post in last 24 hours) |
| India | The Hindu, Business Standard, Economic Times Tech |

5 articles fetched per feed (`ARTICLES_PER_FEED = 5`).

## Email sections
💰 Money Talk · 🌍 World Lore · 🇮🇳 Back Home · ⚡ Tech Tea · 🧠 Human Insights · 🤖 AI

## Key decisions
- **Gemini 2.5 Flash** — fast and cheap (~$0.001/run); falls back to **Gemini 2.5 Flash Lite** on 503 errors
- **workflow_dispatch only** — GitHub's cron skipped a run on Mar 16 2026 despite correct config; moved to cron-job.org as the sole scheduler
- **Numbered list prefixes stripped in HTML formatter** — Gemini wraps stories in numbered lists; stripping the `1.` prefix prevents each story headline from showing "1." in the rendered email

## Running locally
```bash
pip install -r requirements.txt
# add GEMINI_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL to .env
python digest.py
```
