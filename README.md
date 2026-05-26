# UAEOPS Bot

Your UAE operations team assistant, living inside Slack.

---

## Skills overview

| # | Skill | How to trigger |
|---|-------|---------------|
| 1 | **Reminders** | `@UAEOPS_Bot remind me` in any channel |
| 2 | **Chat & Q&A** | `@UAEOPS_Bot <your question>` or DM the bot |

More skills are being added over time.

---

## Skill 1 — Reminders

Never lose track of a message again. Mention the bot in any thread or channel, set a reminder, and it will DM you at the right time with a link back to the original message.

**How to use:**
1. In any channel or thread, type: `@UAEOPS_Bot remind me`
2. Pick a time: **30 min / 1 hour / 4 hours / Tomorrow 9am** or type a custom time
3. The bot confirms in the thread — click **✕ Dismiss** to clean it up

When the time comes, the bot sends you a DM with the original message and a link back to it. You can mark it done or ask to be reminded again.

**Custom time examples:**
- *"tomorrow 3pm"*
- *"in 2 hours"*
- *"next Monday 9am"*

**Rules:**
- Max 3 reminders per message
- All times are UAE time (UTC+4)

---

## Skill 2 — Chat & Q&A

Ask the bot anything covered in your Notion knowledge base and get an instant answer. The bot tells you which page it pulled from so you can always verify.

**How to use:**
- Mention `@UAEOPS_Bot` in any channel followed by your question
- Or DM the bot directly — no @mention needed in a DM

**Examples:**
> `@UAEOPS_Bot what is the process for reporting a permit issue?`
> `@UAEOPS_Bot how do I escalate a P1 alert?`
> `@UAEOPS_Bot where do I find the onboarding guide for the task channel?`

The bot searches your connected Notion pages and replies in the thread. If it can't find anything it says so — it never makes things up.

**Tips for good answers:**
- Be specific — *"what is the escalation process for a P1 alert?"* works better than *"how do alerts work?"*
- Use keywords from the doc — if a page is called "Permit guidelines", mention "permit" in your question
- If it returns nothing, try rephrasing or check that the page is connected to the bot in Notion

**Adding content to the knowledge base:**
1. Open any Notion page
2. Click `···` menu → **Connections** → **Add connection** → **UAEOPS_bot**
3. Done — the bot finds it immediately. No syncing needed.

> Connecting a database (e.g. Document Hub) automatically gives the bot access to all pages inside it.

---

## Setup (for admins)

### Notion integration
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration** → copy the token
2. Add `NOTION_TOKEN` to Railway environment variables
3. Connect Notion pages or databases to the bot: open page → `···` → **Connections** → **UAEOPS_bot**

### Slack App requirements
| Setting | Value |
|---------|-------|
| Socket Mode | Enabled |
| Bot token scopes | `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `im:history`, `im:read`, `im:write`, `users:read` |
| Event subscriptions | `app_mention`, `message.im` |
| Interactivity | Enabled (required for buttons and modals) |

> Optional: add `reactions:write` scope to show a 🤔 emoji while the bot is thinking. Requires reinstalling the app.

### Environment variables
| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | App-level Socket Mode token (`xapp-...`) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `NOTION_TOKEN` | Notion internal integration token |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service_role JWT (`eyJ...`) |

---

## Deployment

The bot runs 24/7 on [Railway](https://railway.com). No server or local terminal needed.

Any push to the `main` branch on GitHub triggers an automatic redeploy.

**GitHub repo:** https://github.com/Arifplatinumlist/UAEOPS_Bot
