# UAEOPS_Bot — Full Session Handover

> Last updated: May 26, 2026
> Status: **✅ LIVE on Railway** — bot is running 24/7, no local terminal needed
> Written for: any new Claude session, any computer, fresh start

---

## 1. What This Bot Does

UAEOPS_Bot is a Slack bot for the UAE operations team. It has two core features:

1. **Reminders** — Mention `@UAEOPS_Bot remind me` in any channel. The bot shows a time-picker (30 min / 1 hour / 4 hours / Tomorrow 9am / Custom). At the scheduled time, the bot sends a DM with a link back to the original message. Reminders survive redeployments — they are stored in Supabase.

2. **Knowledge Base Q&A** — Mention `@UAEOPS_Bot` with a question, or DM the bot directly. The bot searches your connected Notion pages and passes matching content to Claude to generate an answer, then replies in the thread.

---

## 2. Tech Stack

| Component | Technology |
|-----------|-----------|
| Bot framework | Python, Slack Bolt SDK (Socket Mode) |
| Reminder scheduling | APScheduler (`BackgroundScheduler`, `Asia/Dubai` timezone) |
| Reminder storage | Supabase REST API (survives Railway redeployments) |
| Knowledge base | Notion REST API (`POST /v1/search` + block fetching) |
| AI answers | Anthropic Claude (`claude-sonnet-4-6` default) |
| Deployment | Railway (worker process, no HTTP port) |
| Image size | ~200 MB (no PyTorch — sentence-transformers removed) |

---

## 3. Repository

- **GitHub:** https://github.com/Arifplatinumlist/UAEOPS_Bot
- **Local path (Mac):** `~/UAEOPS_Bot`
- **Branch:** `main` (Railway auto-deploys on every push)
- **Key files:**

| File | Purpose |
|------|---------|
| `app.py` | All Slack event handlers, reminder logic, Q&A logic |
| `reminders.py` | Reminder CRUD — Supabase REST API via `requests` |
| `knowledge_base.py` | Notion search — `POST /v1/search` + block fetching |
| `requirements.txt` | Python dependencies (no sentence-transformers, no supabase SDK) |
| `Procfile` | `worker: python app.py` |
| `DRAFT_README.md` | Team-facing README — drafted, awaiting review before replacing README.md |

---

## 4. Environment Variables

Set in Railway Variables tab AND in a local `.env` file for development.

> ⚠️ **SECURITY WARNING:** Several credentials were shared in plaintext during Claude chat sessions. See Section 11 for what needs rotating.

| Variable | Required | Where to get it |
|----------|----------|----------------|
| `SLACK_BOT_TOKEN` | Yes | Slack App → OAuth & Permissions → Bot User OAuth Token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes | Slack App → Basic Information → App-Level Tokens (`xapp-...`) — needs `connections:write` scope |
| `ANTHROPIC_API_KEY` | Yes | https://console.anthropic.com → API Keys |
| `SUPABASE_URL` | Yes | Supabase project → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Yes | Supabase project → Settings → API → **service_role** key (the `eyJ...` JWT — NOT the `sb_publishable_` key) |
| `NOTION_TOKEN` | Yes (for Q&A) | https://www.notion.so/my-integrations → create/select integration → copy token |
| `CLAUDE_MODEL` | No | Defaults to `claude-sonnet-4-6` |

> ⚠️ **Critical:** `SUPABASE_SERVICE_KEY` must be the **service_role** JWT (starts `eyJ...`), not the new-format publishable key (starts `sb_publishable_`). Using the wrong key type causes a 401 crash loop on startup.

Current Supabase project URL: `https://ryqvaouqpufdacbhosyk.supabase.co`

---

## 5. Railway Deployment

### Service details
- **Railway project ID:** `1cd94266-60f8-4fd0-b456-473dfcfca643`
- **Railway service ID:** `ac97f6be-8658-4527-b71f-08b9afca0792`
- **Direct link:** https://railway.com/project/1cd94266-60f8-4fd0-b456-473dfcfca643/service/ac97f6be-8658-4527-b71f-08b9afca0792
- **Connected to:** GitHub `Arifplatinumlist/UAEOPS_Bot` main branch
- **Runtime:** Python 3.13, detected automatically via Railpack

### How deployment works
1. Push any commit to GitHub `main` → Railway auto-triggers build
2. Railway installs `requirements.txt` (~30 sec — image is ~200 MB, no PyTorch)
3. Railway runs `python app.py` (from `Procfile` `worker:` line)
4. Bot connects to Slack via Socket Mode — no open HTTP port needed

### How to manually re-deploy
Railway → UAEOPS_Bot service → Variables tab → make any small change → click **Deploy**
OR: push any commit to GitHub main

### Critical: "Apply X changes" vs deployed
When you add/edit variables in Railway, they show as **pending changes** (bottom bar says "Apply X changes"). The bot does NOT get the new values until you click the **Deploy** button.

---

## 6. All Bugs Fixed (Complete History)

### Bug 1 — Python 3.9 type hint incompatibility
**Error:** `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
**Cause:** `str | None` syntax requires Python 3.10+.
**Fix:** Use `Optional[str]` from `typing` module everywhere.

### Bug 2 — Duplicate `action_id` in time-picker blocks
**Error:** `invalid_blocks: action_id "remind_preset" already exists`
**Fix:** Each preset button gets a unique ID: `remind_preset_30m`, `remind_preset_1h`, `remind_preset_4h`, `remind_preset_tomorrow_9am`.

### Bug 3 — Regex action handler silently failing
**Error:** Clicking time buttons did nothing (`Unhandled request for remind_preset_30m`)
**Cause:** `@slack_app.action(re.compile(...))` silently ignored in Slack Bolt Python.
**Fix:** Register each action with an explicit decorator:
```python
@slack_app.action("remind_preset_30m")
@slack_app.action("remind_preset_1h")
@slack_app.action("remind_preset_4h")
@slack_app.action("remind_preset_tomorrow_9am")
def handle_remind_preset(ack, body, respond, client): ...
```

### Bug 4 — Timezone showing UTC instead of UAE
**Fix:**
```python
UAE_TZ = timezone(timedelta(hours=4))  # UTC+4, no DST
scheduler = BackgroundScheduler(timezone="Asia/Dubai")
now_uae = datetime.now(UAE_TZ)
dt.astimezone(UAE_TZ).strftime("%a %d %b %Y at %H:%M UAE")
```

### Bug 5 — Bot running but not responding to any Slack messages
**Cause:** Event Subscriptions missing from Slack App config.
**Fix:** Slack App → Event Subscriptions → add `app_mention` + `message.im`.

### Bug 6 — Railway crash: `KeyError: 'SLACK_BOT_TOKEN'`
**Cause:** Variables saved in Railway but Deploy button never clicked.
**Fix:** Variables tab → look for bottom bar "Apply X changes" → click purple **Deploy**.

### Bug 7 — Reminders not firing after Railway redeploy
**Cause:** `reminders.json` was stored on Railway's ephemeral filesystem. Every redeploy wiped it, losing all pending reminders.
**Fix:** Migrated reminder storage to Supabase REST API. Reminders now survive redeployments.

### Bug 8 — Railway crash loop (401 Unauthorized on startup)
**Cause:** `SUPABASE_SERVICE_KEY` was set to the new-format `sb_publishable_...` key instead of the service_role JWT (`eyJ...`). The publishable key is not a valid auth credential for the REST API.
**Fix:** Replace with the correct service_role JWT from Supabase → Settings → API → service_role.
**Resilience fix:** `_load_pending_reminders()` wrapped in try/except so the bot stays up even if Supabase is unreachable at startup.

### Bug 9 — Generic "Something went wrong" in Slack
**Two causes fixed:**
1. `NOTION_TOKEN` missing → `RuntimeError` mid-request with no user-facing info. Fixed by testing `NOTION_TOKEN` at startup and setting `_KB_AVAILABLE = False` with a log warning.
2. Supabase 401 in `count_for_message()` had no exception handler. Fixed by adding try/except with an actionable error message to the user.

### Bug 10 — Custom time reminder sent DM instead of updating message
**Cause:** Preset buttons use `respond(replace_original=True)` which updates the time picker in-place. Custom time uses a modal submission which can't use `respond` — it was calling `chat_postMessage` to the user DM instead.
**Fix:** Capture the time picker message `ts` when the "Custom time..." button is clicked, store it in the modal's `private_metadata`, then use `client.chat_update()` on submit to replace the picker message in-place.

---

## 7. Slack App Configuration

Required settings in https://api.slack.com/apps:

| Setting | Required Value |
|---------|---------------|
| Socket Mode | **Enabled** |
| App-Level Token scope | `connections:write` |
| Bot Token scopes | `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `im:history`, `im:read`, `im:write`, `reactions:write`, `users:read` — ⚠️ all required; missing `im:read` silently kills all DM events (INC-015) |
| Event Subscriptions | `app_mention`, `message.im` |
| Interactivity & Shortcuts | **Enabled** — required for button clicks and modals |

---

## 8. Supabase Schema

### Reminders table
Used by the Python bot to persist reminders across Railway redeployments.

```sql
CREATE TABLE reminders (
  id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id         text NOT NULL,
  channel_id      text NOT NULL,
  message_ts      text NOT NULL,
  thread_ts       text,
  permalink       text,
  message_text    text,
  remind_at       timestamptz NOT NULL,
  status          text DEFAULT 'pending',
  reminder_number int  DEFAULT 1,
  created_at      timestamptz DEFAULT now()
);
CREATE INDEX idx_reminders_status_remind_at ON reminders (status, remind_at);
CREATE INDEX idx_reminders_user_message    ON reminders (user_id, message_ts);
```

`status` values: `pending` → `sent` or `done`.
`reminder_number` tracks which reminder (1, 2, or 3) this is for a given message (max 3 per message).

---

## 9. Notion Knowledge Base Setup

The bot searches Notion pages directly via API — no ingestion, no embeddings, no sync needed.

1. Go to https://www.notion.so/my-integrations → **New integration** → copy the Internal Integration Token
2. Set it as `NOTION_TOKEN` in Railway environment variables
3. For **each Notion page** you want the bot to search: open the page → `···` menu → **Add connections** → pick the UAEOPS Bot integration

> The bot only sees pages you explicitly connect. It does not read your entire Notion workspace.

If `NOTION_TOKEN` is missing or not set, the bot logs a warning and disables Q&A — reminders still work.

---

## 10. n8n Alternative (Built But Not Active)

Complete n8n equivalents were designed as a backup. Saved to iCloud:

```
~/Library/Mobile Documents/com~apple~CloudDocs/Claude/
├── uaeops_n8n_handler.json       # 16-node Slack event handler workflow
├── uaeops_n8n_reminders.json     # 5-node reminder sender (runs every 1 min)
└── uaeops_reminders_table.sql    # Supabase SQL for reminders table
```

Railway (Python bot) was chosen because: Socket Mode (no public URL needed), richer logic already working, and n8n free tier has execution limits.

---

## 11. Local Development Setup

```bash
# Clone the repo
git clone https://github.com/Arifplatinumlist/UAEOPS_Bot.git
cd UAEOPS_Bot

# Install dependencies (~30 sec — no PyTorch)
pip3 install -r requirements.txt

# Create .env file
cat > .env << 'EOF'
SLACK_APP_TOKEN=xapp-...
SLACK_BOT_TOKEN=xoxb-...
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://ryqvaouqpufdacbhosyk.supabase.co
SUPABASE_SERVICE_KEY=eyJ...   # service_role JWT, NOT sb_publishable_
NOTION_TOKEN=secret_...
EOF

# Run locally
python3 app.py
```

> `.env` is in `.gitignore`. Never commit it.

---

## 12. Security — Credentials to Rotate

The following were shared in plaintext in Claude chat sessions. Treat them as compromised:

| Token | How to Regenerate |
|-------|------------------|
| `SLACK_BOT_TOKEN` | Slack App → OAuth & Permissions → Reinstall App |
| `SLACK_APP_TOKEN` | Slack App → Basic Information → App-Level Tokens → Revoke + create new |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys → disable old, create new |
| `GitHub PAT` | https://github.com/settings/tokens → Delete + create new |
| `SUPABASE_SERVICE_KEY` | Supabase → Settings → API → Reveal service_role → rotate |

After regenerating: update all Railway environment variables (Variables tab → edit → Deploy).

---

## 13. Outstanding Tasks

1. **🔴 Rotate all credentials** (Section 12) — highest priority
2. **🟡 Install Claude skills on new machine** — after cloning repo, run:
   ```bash
   cp -r .claude/skills/uaeops-debug ~/.claude/skills/
   cp -r .claude/skills/uaeops-deploy ~/.claude/skills/
   ```
2. **🟡 Add `reactions:write` scope to Slack app** — bot works without it but won't show 🤔 emoji while thinking. Slack App → OAuth & Permissions → add `reactions:write` → Reinstall App → update `SLACK_BOT_TOKEN` in Railway
3. **🟡 Verify Q&A quality** — pages connected, search working. Test with real questions and keep adding Notion pages as content grows
4. **🟢 n8n workflows** (optional) — JSON files ready in iCloud if you ever want to switch

**Completed this session:**
- ✅ `NOTION_TOKEN` added to Railway — Q&A enabled
- ✅ Notion knowledge base connected — Document Hub database (auto-propagates to all child pages)
- ✅ Dismiss button on all reminder confirmations (`42332b6`)
- ✅ Q&A crash fixed — reactions:write scope error caught silently (`a492764`)
- ✅ Notion search fixed — image-heavy pages no longer silently dropped (`e7b879d`)
- ✅ README.md replaced with DRAFT_README.md (skills overview + Chat & Q&A section) (`8a463fd`)
- ✅ INCIDENT_REPORT.md created — full history of all bugs, root causes, and fixes (`7e45465`)
- ✅ Incident report added to Notion Document Hub — bot can now troubleshoot using its own history
- ✅ INC-013 added — bot offline during rapid deployments (force-redeploy fix documented) (`5bf8209`)
- ✅ INC-014 fixed — custom time modal "We had some trouble connecting" — two root causes:
  - `ack()` called after slow `dateparser` → moved ack to top (`2773c34`)
  - Supabase call before `views_open` → count now cached in button value (`f5905fa`)
- ✅ INC-015 fixed — bot completely silent, no events received — `im:read` scope was missing from bot token. Added scope, reinstalled Slack app (`6645563`)
- ✅ Two Claude skills created: `uaeops-debug` and `uaeops-deploy` — auto-trigger for debugging and deployment workflows (`533b740`)

---

## 14. Troubleshooting Quick Reference

| Symptom | Cause | Fix |
|---------|-------|-----|
| `KeyError: 'SLACK_BOT_TOKEN'` on Railway | Variables saved but not deployed | Variables tab → click Deploy button |
| Bot online but ignores all messages | Event subscriptions not configured | Slack App → Event Subscriptions → add `app_mention` + `message.im` |
| `invalid_blocks` Slack error | Duplicate action_ids on buttons | Use `f"remind_preset_{preset}"` for unique IDs |
| Clicking time button does nothing | Regex action handler silently fails | Use 4 explicit `@slack_app.action("remind_preset_X")` decorators |
| Startup 401 crash loop | Wrong Supabase key type | Use service_role JWT (`eyJ...`), not `sb_publishable_` key |
| "Something went wrong" in Slack | Missing `NOTION_TOKEN` or Supabase unreachable | Check Railway logs; set `NOTION_TOKEN`; verify `SUPABASE_SERVICE_KEY` |
| Custom time reminder goes to DM | Old bug — fixed in commit `84e731a` | Already resolved |
| Reminders lost after redeploy | Old bug (reminders.json on ephemeral FS) | Already resolved — storage is now Supabase |
| Q&A says "knowledge base not configured" | `NOTION_TOKEN` not set in Railway | Add `NOTION_TOKEN` to Railway env vars + Deploy |
| Q&A finds nothing | No Notion pages connected to integration | Connect the **database** in Notion (e.g. Document Hub) → bot auto-gets all child pages |
| Q&A crashes with "Something went wrong" | `reactions:write` scope missing on Slack app | Fixed in `a492764` — reactions fail silently now |
| "We had some trouble connecting" on custom time | trigger_id expired — Supabase call before `views_open` | Fixed in `f5905fa` — count cached in button value |
| Bot completely silent — no DMs, no mentions | `im:read` scope missing from bot token | Slack App → OAuth & Permissions → add `im:read` → Reinstall → update SLACK_BOT_TOKEN in Railway (INC-015) |
| No 🤔 emoji while bot is thinking | `reactions:write` scope not granted | Add scope in Slack App → OAuth & Permissions → Reinstall App |
| Build takes 5+ minutes | Legacy — only if sentence-transformers snuck back in | Check requirements.txt — it should NOT be there |

---

## 15. Live Status (May 27, 2026)

- **Latest commit:** `6645563` — Force redeploy after im:read scope fix
- **Railway:** Online ✅ — auto-deploys on every push to main
- **Supabase:** `SUPABASE_SERVICE_KEY` set to correct service_role JWT ✅
- **NOTION_TOKEN:** ✅ Set in Railway
- **Notion pages connected:** ✅ Document Hub database (uaeops-tasks onboarding, Alert-monitor-uae onboarding, Permit guidelines)
- **Reminders:** ✅ Persist across redeployments (Supabase storage)
- **Q&A:** ✅ Live — Notion search working, answers via Claude
- **Dismiss button:** ✅ All confirmation messages have ✕ Dismiss button

**All commits this session (oldest → newest):**
| Commit | Change |
|--------|--------|
| `be60a46` | Migrate reminders: JSON file → Supabase |
| `3123998` | Startup resilience: catch Supabase errors |
| `bba3c74` | Specific error messages instead of generic "Something went wrong" |
| `2ec0ede` | Add Supabase error body to logs |
| `84e731a` | Fix custom time reminder: update message in-place |
| `4ef015a` | Rewrite HANDOVER.md for current architecture |
| `42332b6` | Add ✕ Dismiss button to all reminder confirmations |
| `a492764` | Fix Q&A crash: reactions:write scope missing — fail silently |
| `e7b879d` | Fix Notion search: include image-heavy pages, add caption extraction |
| `8a463fd` | Update README: skills overview + Chat & Q&A as Skill 2 |
| `7e45465` | Add INCIDENT_REPORT.md + update HANDOVER.md |
| `5ce6fbf` | Force redeploy (bot was offline after rapid commits) |
| `5bf8209` | Add INC-013: bot offline during rapid deployments |
| `8485d9a` | Update HANDOVER.md: sync commits |
| `2773c34` | Fix custom time modal: ack before dateparser (INC-014 part 1) |
| `f5905fa` | Fix custom time modal: cache count in button value (INC-014 part 2) |
| `533b740` | Add Claude skills: uaeops-debug and uaeops-deploy |
| `6645563` | Force redeploy after im:read scope added (INC-015 fix) |

**To test reminders:**
1. In any Slack channel: `@UAEOPS_Bot remind me`
2. Pick a preset time or click "Custom time..."
3. Picker message updates in-place → `✅ Got it! I'll remind you on...` with a ✕ Dismiss button
4. Wait for scheduled time → DM arrives with link back to original message

**To test Q&A:**
1. In Slack: `@UAEOPS_Bot <question>` or DM the bot directly
2. Bot searches Notion → answers via Claude
3. If it returns "couldn't find anything" — check pages are connected in Notion (open page → `···` → Connections → UAEOPS_bot)
