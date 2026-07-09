# 🤖 Company Assistant — Telegram Bot

A production-ready Telegram bot that acts as a shared assistant inside a private 2-person company group chat. Built with Python 3.12, designed for **Railway deployment** via long polling.

---

## Features

| Category | Commands |
|----------|----------|
| **Tasks** | `/add`, `/list`, `/done`, `/braindump` |
| **Memory** | `/note`, `/ask` |
| **Calendar** | `/planevent`, `/agenda` |
| **Photos** | `/photodump`, `/finish` |
| **Scheduled** | Daily morning brief, Friday EOD summary |
| **Utility** | `/chatid`, `/help` |
| **Auto** | Welcome message for new members |

---

## Prerequisites

- **Python 3.12+**
- **Postgres** database (Railway provides one automatically)
- **Telegram Bot** (created via BotFather)
- **Google Cloud** project with Calendar API and Drive API enabled
- **OpenAI API** key
- **Google Drive** folder shared with the service account (for `/photodump`)

---

## Step-by-Step Setup

### 1. Create the Telegram Bot

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts. Note the **bot token**.
3. **Turn off Group Privacy**:
   - Send `/mybots` → select your bot → **Bot Settings** → **Group Privacy** → **Turn off**.
   - ⚠️ **Why?** Group Privacy is ON by default, meaning the bot only sees messages that start with `/` or mention it. The "memory" feature needs to see _all_ messages to log them. Turning it OFF lets the bot receive every message in the group.

### 2. Get an OpenAI API Key

1. Go to [platform.openai.com](https://platform.openai.com/) → **API Keys** → **Create new secret key**.
2. Copy the key — this becomes `OPENAI_API_KEY`.

### 3. Set Up Google Calendar

#### a) Create a Google Cloud Project & Enable the API

1. Go to [console.cloud.google.com](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Navigate to **APIs & Services** → **Library**.
4. Search for **Google Calendar API** and click **Enable**.

#### b) Create a Service Account

1. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**.
2. Give it a name (e.g. `calendar-bot`), click **Create and Continue**, skip the optional steps, click **Done**.
3. Click on the newly created service account → **Keys** tab → **Add Key** → **Create new key** → **JSON**.
4. A `.json` file will download — this is your service-account key.

#### c) Base64-Encode the Key

```bash
# macOS / Linux
base64 -i service-account-key.json | tr -d '\n'
```

Copy the output — this becomes `GOOGLE_SERVICE_ACCOUNT_B64`.

#### d) Share the Calendar

1. Open [Google Calendar](https://calendar.google.com/) → find the target calendar → ⋮ → **Settings and sharing**.
2. Under **Share with specific people or groups**, click **Add people and groups**.
3. Paste the service account email (looks like `calendar-bot@your-project.iam.gserviceaccount.com`).
4. Set permission to **Make changes to events**.
5. The **Calendar ID** is on the same settings page under "Integrate calendar" (e.g. `abc123@group.calendar.google.com`) — this becomes `GOOGLE_CALENDAR_ID`.

### 4. Deploy on Railway

1. Push this repository to GitHub.
2. Go to [railway.app](https://railway.app/) → **New Project** → **Deploy from GitHub repo** → select this repo.
3. Add a **Postgres** database:
   - Click **+ New** → **Database** → **PostgreSQL**.
   - Railway automatically injects `DATABASE_URL` into your service's environment.
4. Set the remaining environment variables in the service's **Variables** tab:

   | Variable | Value |
   |----------|-------|
   | `TELEGRAM_BOT_TOKEN` | From BotFather |
   | `ALLOWED_CHAT_ID` | Leave blank for now (see first-run flow below) |
   | `OPENAI_API_KEY` | From OpenAI platform |
   | `GOOGLE_CALENDAR_ID` | From Google Calendar settings |
   | `GOOGLE_SERVICE_ACCOUNT_B64` | Base64-encoded service-account JSON |
   | `LLM_MODEL` | _(optional)_ Default: `gpt-4.1` |
   | `TIMEZONE` | _(optional)_ Default: `Asia/Singapore` |
   | `MORNING_BRIEF_TIME` | _(optional)_ Default: `08:00` |

5. Ensure the **Procfile** is detected. Railway will run `worker: python main.py` (no web server needed).

### 5. First-Run Flow

1. **Deploy** the service with `ALLOWED_CHAT_ID` unset.
2. **Add the bot** to your private group chat.
3. Send `/chatid` in the group. The bot will reply with the chat's integer ID.
4. Copy that ID → go to Railway → **Variables** → set `ALLOWED_CHAT_ID` to the value.
5. **Redeploy** (Railway usually auto-redeploys on variable change).
6. The bot is now locked to your group and all features are active.

---

## Environment Variables Reference

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from BotFather |
| `ALLOWED_CHAT_ID` | ✅* | — | Integer chat ID of the allowed group |
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key for LLM calls |
| `GOOGLE_CALENDAR_ID` | ✅ | — | Target Google Calendar ID |
| `GOOGLE_SERVICE_ACCOUNT_B64` | ✅ | — | Base64-encoded service-account JSON key |
| `DATABASE_URL` | ✅ | — | Postgres connection string (Railway auto-injects) |
| `LLM_MODEL` | ❌ | `gpt-4.1` | OpenAI model identifier |
| `TIMEZONE` | ❌ | `Asia/Singapore` | IANA timezone for scheduling |
| `MORNING_BRIEF_TIME` | ❌ | `08:00` | HH:MM 24h local time for the morning brief |
| `GDRIVE_PARENT_FOLDER_ID` | ❌ | — | Google Drive folder ID for `/photodump` |

\* `ALLOWED_CHAT_ID` may be unset on the first deploy so you can discover it via `/chatid`.

---

## Commands Reference

### Tasks

```
/add Buy new domain for the project
```
Creates a new task from the given text. Reply to any message with `/add` to turn it into a task.

```
/list
```
Lists all open tasks with ✅ Done buttons. Tap a button to mark the task done.

```
/braindump Gav: research Halloween venues, book catering by Friday. Joy: update the pitch deck, send invoice to ABC Corp
```
Bulk task capture — sends unstructured text to the LLM to extract individual tasks (with assignee, category, due date). Shows a preview and lets you confirm before saving.

```
/done 7
```
Marks task #7 as done (text fallback for the inline button). Not shown in the command menu.

### Memory

```
/note We agreed to use Stripe for payments
```
Saves a note to the bot's memory.

```
/ask What's on this week?
```
Answers a question using stored chat history, notes, and upcoming calendar events via OpenAI.

### Calendar

```
/planevent 30 July 2026 CCK Secondary Workshop 3pm
```
Parses the free text into a calendar event, shows a preview, and lets you confirm or cancel.

```
/agenda              # rest of today
/agenda tomorrow     # tomorrow's events
/agenda week         # next 7 days
```

### Photos

```
/photodump
```
Starts a photo collection session. The bot asks for an event name, creates a Google Drive folder, then collects every photo you send — uploading it to Drive and deleting the message from the chat. Send `/finish` to end the session and get a summary with the folder link.

> **Note:** The bot must be a group admin with "Delete messages" permission for auto-deletion to work. If it isn't, photos are still uploaded but remain in the chat.

### Scheduled Briefs

- **Daily** at `MORNING_BRIEF_TIME`: Today's calendar events + open tasks.
- **Friday 17:00**: Open tasks going into next week.

### Auto-Welcome

When a new human member joins the allowed group, the bot sends a short welcome greeting with their name and a pointer to `/help`. Bot joins are silently ignored.

---

## Local Development

```bash
# 1. Clone and install
git clone <repo-url> && cd telegram-assistant-bot
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Fill in all values in .env

# 3. Run
python main.py
```

You'll need a running Postgres instance. You can use Docker:

```bash
docker run --name botdb -e POSTGRES_PASSWORD=pass -p 5432:5432 -d postgres:16
# Set DATABASE_URL=postgresql://postgres:pass@localhost:5432/postgres in .env
```

---

## Project Structure

```
main.py                 # Entrypoint: config, app setup, handlers, JobQueue, polling
config.py               # Load + validate env vars
db.py                   # SQLAlchemy engine/session, table creation
models.py               # ORM models (tasks, messages_log, notes)
llm.py                  # OpenAI SDK: answer_question, parse_event, extract_tasks
gcal.py                 # Google Calendar: create_event, list_events
gdrive.py               # Google Drive: create_folder, upload_file
handlers/
  __init__.py           # safe_handler error-wrapping decorator
  security.py           # Whitelist guard, /chatid, /help, welcome message
  tasks.py              # /add, /list, /done, /braindump + callbacks
  brain.py              # Message logging, /ask, /note
  calendar.py           # /planevent (+ confirm/cancel), /agenda
  photos.py             # /photodump, photo collection, /finish
  briefs.py             # JobQueue morning + Friday briefs
requirements.txt        # Pinned dependencies
Procfile                # Railway worker process
.env.example            # Template with all env vars
```

---

## License

Private — internal company use.
