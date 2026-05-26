# UAEOPS_Bot — Full Session Handover

> Last updated: May 26, 2026
> Status: **✅ LIVE on Railway** — bot is running 24/7, no local terminal needed
> Written for: any new Claude session, any computer, fresh start

---

## 1. What This Bot Does

UAEOPS_Bot is a Slack bot for the UAE operations team. It has two core features:

1. **Reminders** — Users right-click any Slack message → "Add Reminder" → bot shows a time-picker (30m / 1h / 4h / Tomorrow 9am). At the scheduled time, the bot sends a DM quoting the original message with a link back to it.

2. **Knowledge Base Q&A** — Users mention `@UAEOPS_Bot` with a question. The bot searches a Supabase vector database (pgvector) for relevant documents, then passes the question + context to Claude Haiku to generate an answer, and replies in the thread.

---

## 2. Tech Stack

| Component | Technology |
|-----------|-----------|
| Bot framework | Python, Slack Bolt SDK (Socket Mode) |
| Reminders scheduling | APScheduler with Asia/Dubai timezone |
| Reminder storage (local dev) | `reminders.json` file |
| Knowledge base | Supabase + pgvector (384-dim embeddings) |
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2, local inference) |
| AI answers | Anthropic Claude Haiku API |
| Deployment | Railway (worker process, no HTTP port) |

---

## 3. Repository

- **GitHub:** https://github.com/Arifplatinumlist/UAEOPS_Bot
- **Local path (Mac):** `~/UAEOPS_Bot`
- **Branch:** `main` (Railway auto-deploys on every push)
- **Key files:**
  - `app.py` — main bot application (all Slack event handlers, reminder logic, Q&A logic)
  - `reminders.py` — reminder CRUD helpers (read/write reminders.json)
  - `requirements.txt` — Python dependencies
  - `Procfile` — tells Railway to run `worker: python app.py`
  - `migrations/001_create_knowledge_base.sql` — Supabase schema for documents table

---

## 4. Environment Variables

Set in Railway Variables tab AND in a local `.env` file for development.

> ⚠️ **SECURITY WARNING:** These credentials were shared in plaintext during a Claude chat session and MUST be regenerated. See Section 11.

| Variable | Where to get it |
|----------|----------------|
| `SLACK_BOT_TOKEN` | Slack App dashboard → OAuth & Permissions → Bot User OAuth Token (starts `xoxb-`) |
| `SLACK_APP_TOKEN` | Slack App dashboard → Basic Information → App-Level Tokens (starts `xapp-`) — needs `connections:write` scope |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys (starts `sk-ant-`) |
| `SUPABASE_URL` | Supabase project → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase project → Settings → API → service_role key |

Current Supabase project URL: `https://ryqvaouqpufdacbhosyk.supabase.co`

---

## 5. Railway Deployment

### Service details
- **Railway project ID:** `1cd94266-60f8-4fd0-b456-473dfcfca643`
- **Railway service ID:** `ac97f6be-8658-4527-b71f-08b9afca0792`
- **Direct link:** https://railway.com/project/1cd94266-60f8-4fd0-b456-473dfcfca643/service/ac97f6be-8658-4527-b71f-08b9afca0792
- **Connected to:** GitHub `Arifplatinumlist/UAEOPS_Bot` main branch
- **Runtime:** Python 3.13.13, detected automatically via Railpack

### How deployment works
1. Push any commit to GitHub `main` → Railway auto-triggers build
2. Railway installs `requirements.txt` (takes ~2 min — PyTorch is large)
3. Railway runs `python app.py` (from `Procfile` `worker:` line)
4. Bot connects to Slack via Socket Mode — no open HTTP port needed

### How to manually re-deploy
Go to Railway → UAEOPS_Bot service → Variables tab → make any small change → click **Deploy**
OR: push any commit to GitHub main

### Critical lesson: "Apply X changes" vs deployed
When you add/edit variables in Railway, they show as **pending changes** (bottom bar says "Apply X changes"). The bot does NOT get the new values until you click the **Deploy** button. This was the root cause of hours of `KeyError: 'SLACK_BOT_TOKEN'` crashes.

### Build time
The Docker image is **2.7 GB** because `sentence-transformers` pulls PyTorch with CUDA. First build takes ~5 minutes. Subsequent builds are faster due to layer caching.

---

## 6. All Bugs Fixed (Complete History)

### Bug 1 — Python 3.9 type hint incompatibility
**Error:** `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
**Files:** `app.py` line 53, `reminders.py` line 86
**Cause:** `str | None` union syntax requires Python 3.10+. Broke on older environments.
**Fix:**
```python
from typing import Optional
# Before:  _bot_uid: str | None = None
# After:   _bot_uid: Optional[str] = None
# Before:  def get(reminder_id: str) -> dict | None:
# After:   def get(reminder_id: str) -> Optional[dict]:
```

### Bug 2 — Duplicate `action_id` in time-picker blocks
**Error:** `invalid_blocks: action_id "remind_preset" already exists`
**Cause:** All 4 preset time buttons in `_time_picker_blocks()` had the same `action_id: "remind_preset"`. Slack requires unique action_ids per message.
**Fix:**
```python
# Before: "action_id": "remind_preset"
# After:  "action_id": f"remind_preset_{preset}"
# Results: remind_preset_30m, remind_preset_1h, remind_preset_4h, remind_preset_tomorrow_9am
```

### Bug 3 — Regex action handler silently failing
**Error:** `Unhandled request for remind_preset_30m` (clicking time buttons did nothing)
**Cause:** `@slack_app.action(re.compile(r"^remind_preset_"))` does NOT work in Slack Bolt Python. The regex decorator is silently ignored.
**Fix — register each action explicitly:**
```python
@slack_app.action("remind_preset_30m")
@slack_app.action("remind_preset_1h")
@slack_app.action("remind_preset_4h")
@slack_app.action("remind_preset_tomorrow_9am")
def handle_remind_preset(ack, body, respond, client):
    ...
```

### Bug 4 — Timezone showing UTC instead of UAE
**Symptom:** Reminders showed "Wednesday 27 May 2026 at 08:00 UTC" instead of local UAE time
**Fix in `app.py`:**
```python
from datetime import timezone, timedelta
UAE_TZ = timezone(timedelta(hours=4))  # UTC+4, no DST

scheduler = BackgroundScheduler(timezone="Asia/Dubai")

# In _preset_to_dt():
now_uae = datetime.now(UAE_TZ)

# In _format_dt():
return dt.astimezone(UAE_TZ).strftime("%a %d %b %Y at %H:%M UAE")
```

### Bug 5 — Bot running but not responding to any Slack messages
**Cause:** Event Subscriptions were missing from the Slack App configuration. The bot connected fine but Slack never sent it any events.
**Fix:** Slack App dashboard → Event Subscriptions → Subscribe to bot events → add:
- `app_mention`
- `message.im`

### Bug 6 — Multiple bot processes running simultaneously
**Symptom:** Bot sends duplicate messages, confusion about which instance is handling events
**Cause:** `pkill -f "python3 app.py"` matched wrong path — old instances kept running
**Fix:**
```bash
ps aux | grep app.py    # find all running PIDs
kill <PID1> <PID2> ...  # kill each one
```

### Bug 7 — Railway crash: `KeyError: 'SLACK_BOT_TOKEN'`
**Symptom:** Every Railway deployment crashed immediately with `KeyError: 'SLACK_BOT_TOKEN'`
**Cause:** Variables were typed into Railway's Variables tab but the **Deploy button was never clicked**. They sat as "5 pending changes" and were never injected into the running container.
**Fix:** Railway → Variables tab → look for the bottom bar that says "Apply X changes" → click the purple **Deploy** button.

### Bug 8 — Git push rejected
**Error:** `! [rejected] main -> main (fetch first)`
**Cause:** A PR (HANDOVER.md) had been merged to GitHub main without being pulled locally first.
**Fix:** `git pull origin main --rebase` then `git push origin main`

### Bug 9 — `ModuleNotFoundError: No module named 'slack_bolt'`
**Cause:** Running `app.py` without first installing dependencies.
**Fix:** `pip3 install -r requirements.txt`

---

## 7. Slack App Configuration

Required settings in https://api.slack.com/apps:

| Setting | Required Value |
|---------|---------------|
| Socket Mode | **Enabled** |
| App-Level Token scope | `connections:write` |
| Bot Token scopes | `chat:write`, `channels:history`, `groups:history`, `im:history`, `mpim:history`, `reactions:read`, `users:read` |
| Event Subscriptions | `app_mention`, `message.im` |
| Interactivity & Shortcuts | **Enabled** — required for button clicks |
| Message Shortcut | Name: "Add Reminder", Callback ID: `add_reminder` |

---

## 8. n8n Alternative (Built But Not Active)

During this session, complete n8n equivalents of the bot were designed and saved. These are an alternative deployment strategy — useful if you want zero-server operation via n8n Cloud.

### Files (saved to iCloud)
```
~/Library/Mobile Documents/com~apple~CloudDocs/Claude/
├── uaeops_n8n_handler.json       # 16-node Slack event handler workflow
├── uaeops_n8n_reminders.json     # 5-node reminder sender (runs every 1 min)
└── uaeops_reminders_table.sql    # Supabase SQL for reminders table
```

### n8n handler workflow summary
Triggered by Slack Events API (webhook mode, not Socket Mode):
- Route (Switch) → 4 branches: URL challenge / remind shortcut / Q&A mention / button click
- **Remind branch:** get permalink → build time-picker blocks → post to Slack
- **Q&A branch:** ACK → ilike text search in Supabase → call Anthropic Claude → post reply
- **Button branch:** calculate UAE time → store in Supabase `reminders` table → confirm to user

### n8n reminders workflow summary
Schedule trigger (every 1 minute):
- GET from Supabase: `reminders` where `status = pending` AND `remind_at <= now()`
- POST DM to Slack
- PATCH status to `sent`

### Why Railway was chosen over n8n
- Python bot already working end-to-end with richer logic
- Socket Mode (no public webhook URL needed) is simpler
- n8n requires switching to Slack webhook mode (public URL)
- n8n free tier has execution count limits

### To activate n8n instead
1. Run `uaeops_reminders_table.sql` in Supabase SQL editor
2. Import both JSONs into n8n Cloud
3. Set credentials in n8n: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SLACK_BOT_TOKEN`, `ANTHROPIC_API_KEY`
4. In Slack App: disable Socket Mode, set Events webhook URL to n8n webhook URL
5. Pause/delete the Railway service

---

## 9. Supabase Schema

### Knowledge base (`documents` table)
```sql
-- migrations/001_create_knowledge_base.sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id         uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  source     text,
  title      text,
  content    text,
  metadata   jsonb,
  embedding  vector(384),   -- all-MiniLM-L6-v2 dimensions
  created_at timestamptz DEFAULT now()
);

-- Vector similarity search function
CREATE OR REPLACE FUNCTION search_documents(
  query_embedding vector(384),
  match_count     int DEFAULT 5,
  match_threshold float DEFAULT 0.7
)
RETURNS TABLE (id uuid, source text, title text, content text, similarity float)
...
```

> The documents table currently has NO data. Q&A will work but the bot will say "no relevant context found." You need to ingest documents using the loaders in the repo (pypdf, python-docx, beautifulsoup4).

### Reminders table (for n8n only — Python bot uses `reminders.json`)
```sql
-- uaeops_reminders_table.sql (in iCloud)
CREATE TABLE reminders (
  id           uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id      text NOT NULL,
  channel_id   text NOT NULL,
  message_ts   text NOT NULL,
  thread_ts    text,
  permalink    text,
  message_text text,
  remind_at    timestamptz NOT NULL,
  status       text DEFAULT 'pending',
  created_at   timestamptz DEFAULT now()
);
CREATE INDEX ON reminders (status, remind_at);
```

---

## 10. Local Development Setup

```bash
# Clone the repo
git clone https://github.com/Arifplatinumlist/UAEOPS_Bot.git
cd UAEOPS_Bot

# Install dependencies (takes 2-3 min, PyTorch is large)
pip3 install -r requirements.txt

# Create .env file with your credentials
cat > .env << 'EOF'
SLACK_APP_TOKEN=xapp-...
SLACK_BOT_TOKEN=xoxb-...
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://ryqvaouqpufdacbhosyk.supabase.co
SUPABASE_SERVICE_KEY=...
EOF

# Run locally
python3 app.py

# Stop cleanly (find and kill if terminal closed)
ps aux | grep app.py
kill <PID>
```

> `.env`, `reminders.json`, and `bot.log` are all in `.gitignore`. Never commit them.

---

## 11. Security — Credentials to Rotate

All of these were typed into a Claude chat session as plaintext. Treat them as compromised:

| Token | How to Regenerate |
|-------|------------------|
| `SLACK_BOT_TOKEN` | Slack App → OAuth & Permissions → Reinstall App |
| `SLACK_APP_TOKEN` | Slack App → Basic Information → App-Level Tokens → Revoke + create new |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys → disable old, create new |
| `GitHub PAT` | https://github.com/settings/tokens → Delete + create new |

After regenerating: update all 5 Railway environment variables (Variables tab → edit → Deploy).

---

## 12. Outstanding Tasks

1. **🔴 Rotate all credentials** (Section 11) — highest priority
2. **🟡 Stop old local bot** — run `ps aux | grep app.py` on your Mac, kill any remaining processes
3. **🟡 Populate knowledge base** — the `documents` table is empty; ingest your ops documents via the loaders already in requirements.txt
4. **🟢 n8n workflows** (optional) — JSON files are ready in iCloud if you ever want to switch
5. **🟢 Slim Docker image** (optional) — replace `sentence-transformers` with Anthropic's embedding API to cut build time from 5 min to ~30 sec

---

## 13. Troubleshooting Quick Reference

| Symptom | Cause | Fix |
|---------|-------|-----|
| `KeyError: 'SLACK_BOT_TOKEN'` on Railway | Variables saved but not deployed | Variables tab → click Deploy button |
| Bot online but ignores all messages | Event subscriptions not configured | Slack App → Event Subscriptions → add `app_mention` + `message.im` |
| `invalid_blocks` Slack error | Duplicate action_ids on buttons | Use `f"remind_preset_{preset}"` for unique IDs |
| Clicking time button does nothing | Regex action handler silently fails | Use 4 explicit `@slack_app.action("remind_preset_X")` decorators |
| Bot replies twice to everything | Multiple processes running | `ps aux | grep app.py` → kill duplicates |
| `git push` rejected | Remote has newer commits | `git pull origin main --rebase` then push |
| Build takes 5+ minutes | PyTorch/sentence-transformers (2.7 GB image) | Normal first-build; subsequent builds use cache |
| `TypeError` on `str | None` | Python < 3.10 syntax | Use `Optional[str]` from `typing` module |
| Q&A replies with no context | Documents table is empty | Ingest documents into Supabase `documents` table |

---

## 14. Live Status (May 26, 2026)

```
Deployment ID:  3d6bad65-d4d2-4e00-859f-79694564fdeb
Railway status: Active ✅
Slack status:   Online (green dot) ✅

Startup log:
  Starting Container
  INFO:__main__: Starting UAEOPS Bot — KB available: True
  INFO:apscheduler.scheduler: Scheduler started
  INFO:__main__: Reloading 0 pending reminder(s) from file
  INFO:__main__: Bot ready. Connecting to Slack via Socket Mode...
  INFO:slack_bolt.App: A new session has been established
  INFO:slack_bolt.App: ⚡ Bolt app is running!
  INFO:slack_bolt.App: Starting to receive messages from a new connection
```

**To test right now:**
- Go to Slack → mention `@UAEOPS_Bot` with any question
- Right-click any message → More message shortcuts → Add Reminder → pick a time
