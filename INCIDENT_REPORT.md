# UAEOPS Bot — Incident Report & Fix Log

> All known bugs, root causes, and fixes. Used by the bot as a troubleshooting knowledge base.
> Last updated: May 26, 2026

---

## INC-001 — Python 3.9 Type Hint Crash

**Symptom:** `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` on startup  
**Root cause:** `str | None` union syntax requires Python 3.10+. Railway was running 3.9.  
**Fix:** Replace all `str | None` with `Optional[str]` from the `typing` module.  
**Files:** `app.py`, `reminders.py`  
**Status:** ✅ Resolved

---

## INC-002 — Time Picker Buttons Did Nothing (Duplicate action_id)

**Symptom:** Clicking 30 min / 1h / 4h / Tomorrow 9am buttons in the time picker had no effect. Slack returned `invalid_blocks: action_id already exists`.  
**Root cause:** All 4 preset buttons shared the same `action_id: "remind_preset"`. Slack requires unique action IDs per message.  
**Fix:** Give each button a unique ID: `remind_preset_30m`, `remind_preset_1h`, `remind_preset_4h`, `remind_preset_tomorrow_9am`.  
**Files:** `app.py` → `_time_picker_blocks()`  
**Status:** ✅ Resolved

---

## INC-003 — Time Picker Buttons Did Nothing (Regex Handler)

**Symptom:** Even after fixing duplicate IDs, clicking buttons still did nothing. Logs showed `Unhandled request for remind_preset_30m`.  
**Root cause:** `@slack_app.action(re.compile(r"^remind_preset_"))` is silently ignored by Slack Bolt Python. Regex patterns do not work as action decorators.  
**Fix:** Register each action with an explicit decorator:
```python
@slack_app.action("remind_preset_30m")
@slack_app.action("remind_preset_1h")
@slack_app.action("remind_preset_4h")
@slack_app.action("remind_preset_tomorrow_9am")
def handle_remind_preset(...): ...
```
**Files:** `app.py`  
**Status:** ✅ Resolved

---

## INC-004 — Reminder Times Showing UTC Instead of UAE

**Symptom:** Confirmation messages showed "Wednesday 27 May 2026 at 08:00 UTC" instead of UAE time.  
**Root cause:** `datetime.now(timezone.utc)` used throughout. `_format_dt()` was not converting to UAE timezone before formatting.  
**Fix:**
```python
UAE_TZ = timezone(timedelta(hours=4))  # UTC+4, no DST
scheduler = BackgroundScheduler(timezone="Asia/Dubai")
now_uae = datetime.now(UAE_TZ)
dt.astimezone(UAE_TZ).strftime("%a %d %b %Y at %H:%M UAE")
```
**Files:** `app.py`, `reminders.py`  
**Status:** ✅ Resolved

---

## INC-005 — Bot Online But Not Responding to Any Messages

**Symptom:** Bot connected to Slack (green dot) but never replied to @mentions or DMs.  
**Root cause:** Event Subscriptions were not configured in the Slack App dashboard. Slack never sent events to the bot.  
**Fix:** Slack App → Event Subscriptions → Subscribe to bot events → add `app_mention` + `message.im`.  
**Status:** ✅ Resolved

---

## INC-006 — Railway Crash: `KeyError: 'SLACK_BOT_TOKEN'`

**Symptom:** Every Railway deployment crashed immediately on startup.  
**Root cause:** Variables were typed into Railway's Variables tab but the Deploy button was never clicked. They stayed as "5 pending changes" and were never injected into the container.  
**Fix:** Railway → Variables tab → look for "Apply X changes" bar at the bottom → click the purple **Deploy** button.  
**Status:** ✅ Resolved  
**Note:** This is the most common cause of env var problems on Railway.

---

## INC-007 — Reminders Lost After Every Railway Redeploy

**Symptom:** All pending reminders disappeared every time the bot was redeployed. Users who set reminders before a deploy never received them.  
**Root cause:** `reminders.json` was stored on Railway's ephemeral filesystem. Every new deployment wipes the container, deleting the file.  
**Fix:** Migrated reminder storage to Supabase REST API. Reminders now persist in a database table and survive redeployments.  
**Files:** `reminders.py` (full rewrite), `app.py` (`_load_pending_reminders()`)  
**Commit:** `be60a46`  
**Status:** ✅ Resolved

---

## INC-008 — Railway Crash Loop: 401 Unauthorized on Startup

**Symptom:** Bot started, immediately hit a 401 error from Supabase, crashed, Railway restarted it, crashed again — infinite loop.  
**Root cause:** `SUPABASE_SERVICE_KEY` was set to the new-format `sb_publishable_...` key instead of the service_role JWT (`eyJ...`). The publishable key is not a valid authentication credential for the Supabase REST API.  
**Fix:**  
1. Wrap `_load_pending_reminders()` in try/except so startup crash is non-fatal (bot stays online)  
2. Replace `SUPABASE_SERVICE_KEY` in Railway with the correct service_role JWT from Supabase → Settings → API → service_role  
**Commit:** `3123998`, `bba3c74`  
**Status:** ✅ Resolved  
**Note:** Always use the `eyJ...` JWT for `SUPABASE_SERVICE_KEY`, never the `sb_publishable_` key.

---

## INC-009 — Generic "Something Went Wrong" Errors in Slack

**Symptom:** Bot replied "Something went wrong — please try again" to all messages with no detail.  
**Root cause (1):** `NOTION_TOKEN` not set → `RuntimeError` raised mid-request, caught by outer except, generic message returned.  
**Root cause (2):** Supabase 401 in `count_for_message()` had no exception handler, propagated to outer except.  
**Fix:** Test `NOTION_TOKEN` at startup and set `_KB_AVAILABLE = False` with a warning log. Add specific try/except around Supabase calls with actionable user-facing messages.  
**Commit:** `bba3c74`  
**Status:** ✅ Resolved

---

## INC-010 — Custom Time Reminder Sent DM Instead of Updating Thread

**Symptom:** When a user picked a preset time (30m/1h/etc.), the time picker message updated in-place to show "✅ Got it!". When a user typed a custom time, a DM was sent instead.  
**Root cause:** Preset buttons use `respond(replace_original=True)` which updates the original message. Modal submissions can't use `respond` — the code was calling `chat_postMessage` to the user's DM channel instead of updating the original picker message.  
**Fix:** Capture the picker message `ts` in `handle_remind_custom_open` (stored in modal `private_metadata`). In `handle_remind_custom_submit`, use `client.chat_update(channel=..., ts=picker_ts)` to replace the picker in-place.  
**Commit:** `84e731a`  
**Status:** ✅ Resolved

---

## INC-011 — Q&A Crashed on Every Request: "Something Went Wrong"

**Symptom:** Every Q&A message returned "Something went wrong — please try again." Railway logs showed the actual error.  
**Root cause:** `client.reactions_add(channel, "thinking_face", ts)` requires the `reactions:write` OAuth scope. This scope was not granted on the Slack App. The call raised `SlackApiError: missing_scope` before any Q&A logic ran, and the outer except caught it with the generic message.  
**Fix:** Wrap both `reactions_add` and `reactions_remove` in try/except blocks so they fail silently. The 🤔 emoji is cosmetic — Q&A works fine without it.  
**Commit:** `a492764`  
**Status:** ✅ Resolved  
**Optional follow-up:** Add `reactions:write` scope in Slack App → OAuth & Permissions → Reinstall App to restore the thinking emoji.

---

## INC-012 — Notion Search Returns No Results Despite Pages Being Connected

**Symptom:** Bot replies "I searched the Notion knowledge base but couldn't find anything relevant" even though Notion pages are connected and have content.  
**Root cause (1):** Pages with mostly images (screenshots, diagrams) had very little extractable text. The code filtered out pages where `content.strip()` was empty — so image-heavy pages were silently dropped even when Notion found them.  
**Root cause (2):** Image blocks in Notion have no `rich_text` field. The block-to-text converter returned empty string for image blocks, making image-heavy pages appear empty.  
**Fix:**  
1. Remove `if content.strip()` gate — include all pages Notion returns, with a fallback message if content is empty  
2. Add image block handling to extract captions: `[image: caption text]` or `[image]`  
3. Add `INFO` log: `Notion search 'query' → N page(s) found` so Railway logs show exactly what Notion is returning  
**Commit:** `e7b879d`  
**Status:** ✅ Resolved  
**Note:** If the bot still returns no results, check Railway logs for the `Notion search` line to confirm whether Notion is finding the page at all. If 0 pages found, the page may not be connected to the integration.

---

## How to Add a New Page to the Bot's Knowledge Base

1. Open the Notion page
2. Click `···` menu → **Connections** → **Add connection** → **UAEOPS_bot**
3. Done — bot finds it immediately on next question

> Connecting a **database** (like Document Hub) automatically gives the bot access to all pages inside it — no need to connect each page individually.

---

## Railway Deployment Quick Reference

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Bot not starting | Env vars pending | Variables tab → click Deploy |
| 401 on Supabase | Wrong key type | Use service_role JWT (`eyJ...`), not `sb_publishable_` |
| Bot online, no replies | Event subs missing | Slack App → Event Subscriptions → add `app_mention` + `message.im` |
| "Something went wrong" | Check Railway logs | Filter by service → look for ERROR lines |
| Q&A finds nothing | Page not connected or image-heavy | Check Railway logs for `Notion search → 0 pages` |
