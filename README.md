# UAEOPS Bot

A Slack bot that answers questions from your own knowledge base using Claude (Anthropic).

**How it works:**
1. Someone DMs the bot or @mentions it in a channel
2. The bot searches your Supabase knowledge base for relevant content
3. Claude reads the matching excerpts and replies in a warm, conversational tone
4. If nothing is found in the knowledge base, it says so — it never makes things up

---

## Setup

### 1. Supabase — create the vector table

Run `migrations/001_create_knowledge_base.sql` in your Supabase SQL editor (one-time setup).

### 2. Create a Slack App

1. Go to https://api.slack.com/apps → **Create New App → From scratch**
2. **Socket Mode** → Enable → generate an App-Level Token with `connections:write` → copy as `SLACK_APP_TOKEN`
3. **OAuth & Permissions → Bot Token Scopes** — add:
   `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `reactions:write`, `channels:history`
4. **Event Subscriptions → Subscribe to bot events** — add: `app_mention`, `message.im`
5. Install to workspace → copy **Bot User OAuth Token** as `SLACK_BOT_TOKEN`

### 3. Configure environment

```bash
cp .env.example .env
# Fill in all values — use the SERVICE ROLE key from Supabase Settings > API
```

### 4. Install & run

```bash
pip install -r requirements.txt
python app.py
```

> The sentence-transformers model (~90 MB) is downloaded automatically on first run.

---

## Adding content to the knowledge base

```bash
# PDF, Word, Markdown, or plain text file
python ingest.py --file docs/runbook.pdf
python ingest.py --file notes.md

# Any web page
python ingest.py --url https://your-internal-wiki.com/page

# Notion page (needs NOTION_TOKEN in .env)
python ingest.py --notion abc123def456...

# Canva / any reference link
python ingest.py --link "https://www.canva.com/design/..." \
                 --title "Q2 Review Slides" \
                 --description "Quarterly operations review presented in April 2025"
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes | App-level token for Socket Mode (`xapp-...`) |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Yes | Service role key (Settings > API) |
| `NOTION_TOKEN` | No | Only needed for Notion ingestion |
| `CLAUDE_MODEL` | No | Defaults to `claude-sonnet-4-6` |
