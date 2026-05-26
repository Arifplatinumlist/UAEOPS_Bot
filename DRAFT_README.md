# UAEOPS Bot

Your UAE operations team assistant, living inside Slack.

---

## What it does

### 1 — Reminders
Never lose track of a message again. Right-click any Slack message, set a reminder, and the bot will DM you at the right time with a link back to the original.

**How to use:**
1. Right-click any message in Slack
2. Hover over **More message shortcuts**
3. Click **Add Reminder**
4. Pick a time: **30 min / 1 hour / 4 hours / Tomorrow 9am** or type a custom time

The bot will DM you when the time comes. You can mark it done or ask to be reminded again.

**Rules:**
- Max 3 reminders per message
- All times are UAE time (UTC+4)
- Custom time accepts natural language — *"tomorrow 3pm"*, *"in 2 hours"*, *"next Monday 9am"*

---

### 2 — Knowledge Base Q&A
Ask the bot anything covered in your Notion knowledge base and get an instant, sourced answer.

**How to use:**
- Mention `@UAEOPS_Bot` in any channel with your question
- Or DM the bot directly

**Example:**
> `@UAEOPS_Bot what is the process for onboarding a new event manager?`

The bot searches your connected Notion pages and replies in the thread with an answer and the source page it pulled from. If it can't find anything, it says so — it never makes things up.

**Adding content to the knowledge base:**
Write or update a Notion page → make sure the page is connected to the bot integration → the bot will find it immediately on the next question. No syncing needed.

---

## More skills coming

This bot is being actively developed. New skills will be added over time.

---

## Setup (for admins)

### Notion integration
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration** → copy the token
2. Add `NOTION_TOKEN` to Railway environment variables
3. For each Notion page you want the bot to search: open the page → `···` menu → **Add connections** → pick the UAEOPS Bot integration

> The bot only sees pages explicitly connected to it — it cannot read your entire Notion workspace.

### Slack App requirements
| Setting | Value |
|---------|-------|
| Socket Mode | Enabled |
| Bot token scopes | `chat:write`, `channels:history`, `im:history`, `users:read` |
| Event subscriptions | `app_mention`, `message.im` |
| Interactivity & Shortcuts | Enabled |
| Message Shortcut name | Add Reminder (callback: `add_reminder`) |

### Environment variables
| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | App-level Socket Mode token (`xapp-...`) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `NOTION_TOKEN` | Notion internal integration token |

---

## Deployment

The bot runs 24/7 on [Railway](https://railway.com). No server or local terminal needed.

Any push to the `main` branch on GitHub triggers an automatic redeploy.

**GitHub repo:** https://github.com/Arifplatinumlist/UAEOPS_Bot
