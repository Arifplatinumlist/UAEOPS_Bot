# UAEOPS Bot — Local Setup Handover

Follow these steps in order. Takes about 15 minutes.

---

## What this bot does

- **Q&A**: Anyone can DM the bot or @mention it in a channel to ask questions from the knowledge base
- **Reminders**: Anyone can reply to any message with `@UAE_OPS remind me about this` — the bot asks when, then DMs them at that time with a link back to the original message

---

## Prerequisites

Install these on your PC before starting:

- **Python 3.11+** → https://www.python.org/downloads/
- **Git** → https://git-scm.com/downloads

Verify in your terminal:
```bash
python --version   # should show 3.11 or higher
git --version
```

---

## Step 1 — Get the code

```bash
git clone https://github.com/Arifplatinumlist/UAEOPS_Bot.git
cd UAEOPS_Bot
```

---

## Step 2 — Configure the Slack app

Go to **https://api.slack.com/apps** and open the **UAE_OPS** app (or whichever app you want the bot to run as).

### 2a — Enable Socket Mode

1. Left sidebar → **Socket Mode**
2. Toggle **Enable Socket Mode** → ON
3. It will ask you to create an App-Level Token
4. Name it anything (e.g. `local-bot`) and add the scope: `connections:write`
5. Click **Generate** → copy the token that starts with `xapp-`
   - This is your **SLACK_APP_TOKEN**

### 2b — Get the Bot Token

1. Left sidebar → **OAuth & Permissions**
2. Copy the **Bot User OAuth Token** (starts with `xoxb-`)
   - This is your **SLACK_BOT_TOKEN**

### 2c — Enable Interactivity (needed for reminder buttons)

1. Left sidebar → **Interactivity & Shortcuts**
2. Toggle → **ON**
3. Click **Save Changes**

### 2d — Check Event Subscriptions

1. Left sidebar → **Event Subscriptions**
2. Toggle **Enable Events** → ON
3. Under **Subscribe to bot events** make sure these are listed:
   - `app_mention`
   - `message.im`
4. Click **Save Changes** if you made any changes

### 2e — Check Bot Scopes

1. Left sidebar → **OAuth & Permissions** → scroll to **Scopes**
2. Under **Bot Token Scopes** make sure all of these are present:
   - `app_mentions:read`
   - `channels:history`
   - `channels:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
   - `reactions:write`
3. If any are missing, click **Add an OAuth Scope**, add it, then click **Reinstall to Workspace** at the top of the page

---

## Step 3 — Create your .env file

In the `UAEOPS_Bot` folder, create a file called `.env` (no extension):

```
SLACK_APP_TOKEN=xapp-...        ← paste your App-Level Token here
SLACK_BOT_TOKEN=xoxb-...        ← paste your Bot Token here
ANTHROPIC_API_KEY=sk-ant-...    ← your Anthropic API key
```

> **Anthropic API key**: get one at https://console.anthropic.com → API Keys

Leave Supabase blank for now — the bot works without it (Q&A will be enabled once you set up the knowledge base later).

---

## Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

This installs Slack Bolt, Anthropic SDK, APScheduler, and other packages.
First run downloads a ~90 MB embedding model — that's normal.

---

## Step 5 — Run the bot

```bash
python app.py
```

You should see:
```
INFO  Starting UAEOPS Bot — KB available: False
INFO  Reloading 0 pending reminder(s) from file
INFO  Bot ready. Connecting to Slack via Socket Mode...
```

The bot is now live. Keep this terminal window open — closing it stops the bot.

---

## Step 6 — Test it

### Test 1: Reminder in a channel thread

1. Go to any channel where UAE_OPS is a member (e.g. `#uaeops-alerts`)
2. Click on any existing message to open its thread
3. In the reply box type: `@UAE_OPS remind me about this`
4. The bot should reply with a time picker (30 min / 1 hour / 4 hours / Tomorrow 9am / Custom)
5. Click **30 min** → bot confirms the reminder
6. In 30 minutes you will receive a DM from the bot with a link back to that message

### Test 2: Direct message

1. In Slack, click **+ New Message** and search for UAE_OPS
2. Send any message
3. The bot will reply (if knowledge base is set up it answers from docs; if not, it says KB not configured yet)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` on startup | Run `pip install -r requirements.txt` again |
| Bot starts but doesn't respond to @mentions | Check that `app_mention` is in Event Subscriptions (Step 2d) |
| Time picker appears but clicking does nothing | Enable Interactivity (Step 2c) |
| `SLACK_APP_TOKEN` error | Make sure it starts with `xapp-`, not `xoxb-` |
| Bot stops when you close the terminal | That's expected for local run — leave terminal open or use `nohup python app.py &` |
| Want reminders to survive a restart | They do — stored in `reminders.json` in the project folder |

---

## File overview

```
UAEOPS_Bot/
├── app.py              ← main bot (run this)
├── reminders.py        ← reminder data store
├── knowledge_base.py   ← Supabase vector search (optional for now)
├── ingest.py           ← add documents to knowledge base
├── requirements.txt    ← Python dependencies
├── .env                ← your secrets (never commit this)
├── reminders.json      ← auto-created, stores all reminders
└── migrations/
    └── 001_create_knowledge_base.sql   ← run in Supabase when ready
```

---

## Adding knowledge base later (optional)

Once the bot is working, you can add documents for the Q&A feature:

1. Add Supabase credentials to `.env`:
   ```
   SUPABASE_URL=https://ryqvaouqpufdacbhosyk.supabase.co
   SUPABASE_SERVICE_KEY=your-service-role-key
   ```
2. Run the migration in Supabase SQL editor: `migrations/001_create_knowledge_base.sql`
3. Restart the bot — it will say `KB available: True`
4. Add documents:
   ```bash
   python ingest.py --file your-runbook.pdf
   python ingest.py --url https://your-wiki.com/page
   ```
