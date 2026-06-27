# NextBid

Bid intelligence platform that scrapes international tender sources, runs AI-powered analysis, and emails structured reports with Excel exports.

## Features

- **8 Scrapers** — UNGM, World Bank, GIZ, FCDO, DevelopmentAid, ActionAid, CRS, AfDB
- **AI Analysis** — Scores each notice on strategic fit, geographic fit, win probability, revenue potential; assigns suggested positioning
- **Email Reports** — Sends HTML summary with Excel attachment (Top 5 with HYPERLINK titles)
- **User Management** — CRUD users with role-based access, change-password flow, self-deletion protection
- **Dashboard & Reports** — Real-time stats, per-source counts, run history with re-analyze/email/export/delete
- **System Prompt** — Customizable markdown prompt rendered as read-only HTML in settings

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | Flask + SQLAlchemy |
| Database | SQLite (default), PostgreSQL-ready |
| Scraping | Playwright (headless Chromium) |
| AI | OpenRouter / OpenAI / Anthropic |
| Frontend | Alpine.js SPA + Tailwind CSS |
| Email | SMTP (Gmail, etc.) with Excel attachments |

## Quick Start

```bash
# Prerequisites
pip install -r requirements.txt
playwright install chromium

# Configure
cp .env.example .env
# Edit .env — at minimum set AI_API_KEY, SMTP_* for email, SECRET_KEY

# Run
python app.py
# → http://localhost:8080
```

## Configuration

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Web server port |
| `DATABASE_URL` | `sqlite:///bidz.db` | Database connection string |
| `SECRET_KEY` | `change-me` | Flask session secret |
| `AI_PROVIDER` | `openrouter` | LLM provider |
| `AI_API_KEY` | — | LLM API key |
| `AI_MODEL` | — | Model name |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP login |
| `SMTP_PASS` | — | SMTP password |
| `EMAIL_FROM` | — | From address for emails |
| `DEVELOPMENTAID_EMAIL` | — | Login for DevelopmentAid scraper |
| `DEVELOPMENTAID_PASSWORD` | — | Password for DevelopmentAid scraper |

## Project Structure

```
site/
├── app.py                 # Flask application (API routes + SPA)
├── run_scraper.py         # Scrape orchestration pipeline
├── models.py              # SQLAlchemy models
├── utils.py               # Excel generator, retry helper
├── config.py              # Configuration loader
├── system_prompt.md       # LLM system prompt (customizable)
├── scrapers/              # Individual source scrapers
│   ├── ungm.py
│   ├── worldbank.py
│   ├── giz.py
│   ├── fcdo.py
│   ├── developmentaid.py
│   ├── actionaid.py
│   ├── crs.py
│   └── afdb.py
├── agents/                # AI analysis and email modules
│   ├── agent.py           # LLM provider abstraction
│   ├── batch_processor.py # Background analysis runner
│   └── emailer.py         # HTML email + Excel builder
├── templates/
│   └── admin.html         # Alpine.js SPA single page
├── static/                # Static assets
├── venv/                  # Python virtual environment
└── .env                   # Environment configuration
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login |
| GET | `/api/runs` | List scrape runs |
| POST | `/api/scrape` | Trigger full scan |
| GET | `/api/scrape/progress/<batch_id>` | Scrape progress |
| POST | `/api/analyze/<batch_id>` | Run AI analysis |
| GET | `/api/analysis/progress/<analysis_id>` | Analysis progress |
| POST | `/api/runs/<batch_id>/email` | Email results |
| GET | `/api/runs/<batch_id>/export` | Download Excel |
| DELETE | `/api/runs/<batch_id>` | Delete run |
| GET/POST | `/api/users` | User CRUD |
| PUT/DELETE | `/api/users/<id>` | User update/delete |
| PUT | `/api/users/<id>/password` | Change password |
| GET | `/api/system-prompt` | Get system prompt |
| GET | `/api/settings` | Get app settings |
| POST | `/api/settings` | Save app settings |

## Running Scrapers Standalone

```bash
# All sources
python run_scraper.py

# Single source
python run_scraper.py --source UNGM
python run_scraper.py --source ALL
```

## Adding a New Scraper

1. Create `scrapers/yoursource.py` with a function that accepts `(browser, seen_set=None, progress_cb=None)` and returns a list of notice dicts
2. Add `('YOURSOURCE', 'scrapers.yoursource', 'your_function')` to `SCRAPER_SOURCES` in `run_scraper.py`
