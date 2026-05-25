# UAEOPS Bot

A Slack bot powered by Claude (Anthropic) that answers questions in DMs and channel mentions.

## How it works

- **Direct message** the bot → it replies with an answer
- **@mention** the bot in any channel → it replies in-thread
- Conversation history is kept per-channel so the bot remembers context within a session

## Setup

### 1. Create a Slack App

1. Go to https://api.slack.com/apps and click **Create New App → From scratch**
2. Under **Socket Mode**, enable it and generate an **App-Level Token** with `connections:write` scope → copy as `SLACK_APP_TOKEN`
3. Under **OAuth & Permissions → Bot Token Scopes**, add:
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
   - `reactions:write`
   - `channels:history`
4. Under **Event Subscriptions → Subscribe to bot events**, add:
   - `app_mention`
   - `message.im`
5. Install the app to your workspace → copy **Bot User OAuth Token** as `SLACK_BOT_TOKEN`

### 2. Configure environment

```bash
cp .env.example .env
# Fill in SLACK_APP_TOKEN, SLACK_BOT_TOKEN, ANTHROPIC_API_KEY
```

### 3. Install dependencies & run

```bash
pip install -r requirements.txt
python app.py
```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes | App-level token for Socket Mode (`xapp-...`) |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `CLAUDE_MODEL` | No | Claude model ID (default: `claude-sonnet-4-6`) |
| `SYSTEM_PROMPT` | No | Custom system prompt / persona |
