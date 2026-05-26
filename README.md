# UAEOPS Bot

A Slack bot that answers questions from your own Notion knowledge base using Claude (Anthropic).

**How it works:**
1. Someone DMs the bot or @mentions it in a channel
2. The bot searches your connected Notion pages for relevant content
3. Claude reads the matching excerpts and replies in a warm, conversational tone
4. If nothing is found in the knowledge base, it says so — it never makes things up

---

## Setup

### 1. Notion — create an integration and connect your pages

1. Go to https://www.notion.so/my-integrations → **New integration**
2. Give it a name (e.g. `UAEOPS Bot`) → Submit → copy the **Internal Integration Token**
3. Set it as `NOTION_TOKEN` in your `.env` and Railway environment variables
4. For **each Notion page** you want the bot to search: open the page → `···` menu → **Add connections** → pick your integration

> The bot can only see pages explicitly connected to the integration — it won't read your entire workspace.

### 2. Create a Slack App

1. Go to https://api.slack.com/apps → **Create New App → From scratch**
2. **Socket Mode** → Enable → generate an App-Level Token with `connections:write` → copy as `SLACK_APP_TOKEN`
3. **OAuth & Permissions → Bot Token Scopes** — add:
   `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `reactions:write`, `channels:history`, `channels:read`
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

## Reminder agent

Anyone in Slack can tag the bot with "remind me" to create a time-based reminder:

```
@uaeops_bot remind me about this
@uaeops_bot remind me about this message
```

The bot will reply with a time picker (30 min / 1 hour / 4 hours / Tomorrow 9am / Custom).
When the time comes, the bot sends you a DM with a link back to the original message and offers
"Done" or "Remind me again" buttons.

**Rules:**
- Maximum **3 reminders per message** per user
- Pending reminders survive bot restarts (stored in `reminders.json`)
- All preset times are in UAE time (UTC+4); custom time supports natural language (e.g. `tomorrow 3pm`, `in 2 hours`, `next Monday 9am`)

`reminders.json` is written to the project directory and acts as the full history log.

---

## Adding content to the knowledge base

All content lives in Notion — just write or paste into a Notion page and connect it to the bot integration (see Setup step 1). The bot will find it on the next question.

No ingestion script needed. 🎉

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes | App-level token for Socket Mode (`xapp-...`) |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `NOTION_TOKEN` | Yes | Internal integration token from https://notion.so/my-integrations |
| `CLAUDE_MODEL` | No | Defaults to `claude-sonnet-4-6` |
