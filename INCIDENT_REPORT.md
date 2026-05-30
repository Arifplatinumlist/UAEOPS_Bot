# UAEOPS Bot — Incident Report & Fix Log

> All known bugs, root causes, and fixes. Used by the bot as a troubleshooting knowledge base.
> Last updated: May 27, 2026 (INC-023)

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

## INC-013 — Bot Goes Offline During Multiple Rapid Deployments

**Symptom:** Bot stops responding in Slack for several minutes. No error — it simply doesn't reply to anything (Q&A or reminders).
**When it happens:** After multiple commits are pushed to GitHub in quick succession. Each push triggers a new Railway deployment. During every build (~30–60 sec), the bot has no active Slack Socket Mode connection.
**Root cause:** Railway stops the running container before starting the new one. With 5+ commits pushed in a short session, the bot restarts repeatedly.
**How to diagnose via terminal:**
```bash
# Check Slack token is valid
curl -s -X POST "https://slack.com/api/auth.test" \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" | python3 -m json.tool
# Expected: "ok": true

# Check Supabase is reachable
curl -s -o /dev/null -w "%{http_code}" \
  "https://ryqvaouqpufdacbhosyk.supabase.co/rest/v1/reminders?select=id&limit=1" \
  -H "apikey: $SUPABASE_SERVICE_KEY"
# Expected: 200
```
If both return OK, the issue is Railway — not the code or credentials.
**Fix:** Force a fresh Railway deploy:
```bash
git commit --allow-empty -m "Force redeploy" && git push origin main
```
Then confirm in Railway dashboard → UAEOPS_Bot → Deployments → **ACTIVE / Deployment successful**.
**Prevention:** Batch all changes into a single commit instead of pushing one at a time.
**Commit:** `5ce6fbf` (force redeploy)
**Status:** ✅ Resolved

---

## INC-014 — Custom Time Modal: "We Had Some Trouble Connecting"

**Symptom:** Clicking "Custom time..." in the time picker opened the modal fine, but after typing a time and clicking "Set reminder", Slack showed "We had some trouble connecting. Try again?" and the reminder was never saved.  
**Root cause (1):** `handle_remind_custom_submit` called `dateparser.parse()` BEFORE calling `ack()`. Slack requires `ack()` within 3 seconds of a view submission. `dateparser` is slow on first call, pushing past the limit.  
**Root cause (2):** `handle_remind_custom_open` called `reminder_store.count_for_message()` (a Supabase API roundtrip) BEFORE calling `client.views_open()`. The `trigger_id` Slack issues for button clicks also expires after 3 seconds. The Supabase call consumed the window, so `views_open` arrived too late.  
**Fix:**
1. Move `ack()` to the very top of `handle_remind_custom_submit`, before `dateparser.parse()`. If parsing fails, report the error via `chat_postMessage` to the thread instead of inline form validation.
2. Store `count` inside the "Custom time..." button value at build time (in `_time_picker_blocks`). In `handle_remind_custom_open`, read count from `ctx.pop("count", 0)` — no Supabase call needed. `views_open` fires immediately after `ack()`.
**Files:** `app.py` → `handle_remind_custom_submit`, `handle_remind_custom_open`, `_time_picker_blocks`  
**Commits:** `2773c34`, `f5905fa`  
**Status:** ✅ Resolved

---

## INC-015 — Bot Running but Receives No Slack Events (DMs and Mentions Silent)

**Symptom:** Bot is online (Railway green, Socket Mode session established in logs), all tokens valid, event subscriptions listed in Slack dashboard — but absolutely no log lines appear when sending DMs or @mentions. Bot is completely silent.  
**Root cause:** `im:read` OAuth scope was missing from the bot token. Without this scope, Slack silently discards all `message.im` events even though they appear subscribed. The bot can connect and establish a Socket Mode session, but Slack never sends it any DM payloads.  
**How to confirm:** Run this — if it returns `missing_scope: im:read`, that's the issue:
```bash
BOT_TOKEN=$(grep SLACK_BOT_TOKEN .env | cut -d= -f2-)
curl -s "https://slack.com/api/conversations.list?types=im&limit=1" \
  -H "Authorization: Bearer $BOT_TOKEN" | python3 -m json.tool
```
**Fix:**
1. Slack App → **OAuth & Permissions** → **Bot Token Scopes** → **Add an OAuth Scope** → add `im:read`
2. Click **Reinstall to workspace** (yellow banner at top) → Allow
3. Copy the bot token (may stay the same) → update `SLACK_BOT_TOKEN` in Railway Variables → Deploy
4. Force redeploy: `git commit --allow-empty -m "Force redeploy — im:read scope added" && git push origin main`
**Verification:** After fix, `conversations.list?types=im` returns `"ok": true` with channel data.  
**Commit:** `6645563` (force redeploy after scope fix)  
**Status:** ✅ Resolved  
**Note:** This scope is required even if `im:history` and `im:write` are both present. All three are needed for full DM functionality.

---

## INC-016 — Bot Didn't Respond to @Mentions from Mobile Slack

**Symptom:** Bot responded to @mentions from desktop Slack but completely ignored them from the iOS/Android app.  
**Root cause:** Slack mobile sends mentions in the format `<@UID|botname>` (with a display-name suffix), while desktop sends `<@UID>`. The regex `<@{bot_uid}>` only matched the desktop format; the mobile format fell through unstripped, so `clean` still contained `<@UID|name>` and was treated as a different user ID — never matching any Q&A or reminder path.  
**Fix:** Replace fixed-string mention strip with a regex that handles both forms:
```python
clean = re.sub(rf"<@{re.escape(bot_uid)}(?:\|[^>]*)?>", "", raw_text).strip()
```
**Files:** `app.py` → `_process_mention`  
**Status:** ✅ Resolved

---

## INC-017 — Thread Replies Not Visible in Channel Feed on Mobile

**Symptom:** Bot replies appeared in the thread (desktop sidebar) but not in the main channel feed, making them invisible to mobile users who don't expand threads.  
**Root cause:** `say(thread_ts=...)` without `reply_broadcast=True` posts replies that only appear inside the thread. Slack mobile's default view shows the channel feed, not thread replies.  
**Fix:** Add `reply_broadcast=True` to all `say()` / `chat_postMessage()` calls in `_process_mention`:
```python
client.chat_postMessage(channel=channel, ..., thread_ts=event["ts"], reply_broadcast=True)
```
**Files:** `app.py` → `_process_mention`  
**Status:** ✅ Resolved

---

## INC-018 — DM Messages Intermittently Ignored (Random Drop)

**Symptom:** DMs to the bot sometimes got a response, sometimes nothing. No errors in Railway logs — events simply vanished.  
**Root cause:** Slack Bolt runs Socket Mode on a single WebSocket receive thread. Each `message` event handler ran synchronously (Notion search + Claude API = 15–20s). When two messages arrived within that window, the second event couldn't be processed because the thread was blocked on the first.  
**Fix:** Wrap slow handlers in a `ThreadPoolExecutor` so the receive loop is never blocked:
```python
_pool = ThreadPoolExecutor(max_workers=4)

@slack_app.event("message")
def handle_dm(event, say, client):
    ...
    _pool.submit(_process_dm, event, say, client)
```
**Files:** `app.py`  
**Status:** ✅ Resolved

---

## INC-019 — Bot Lagged 15–20 Seconds with No User Feedback

**Symptom:** User sent a question; bot went completely silent for 15–20 seconds, then suddenly replied. Users thought the bot had crashed.  
**Root cause (1):** No placeholder message — the bot did all processing before sending anything.  
**Root cause (2):** Notion page content was fetched sequentially (one page at a time), each taking ~3s.  
**Fix:**
1. Post an immediate "⏳ Searching the knowledge base..." placeholder via `chat_postMessage`, then replace it with `chat_update` once the answer is ready.
2. Fetch all Notion pages in parallel using `ThreadPoolExecutor`:
```python
with ThreadPoolExecutor(max_workers=min(len(pages), 5)) as ex:
    results = [r for r in ex.map(_fetch_one, pages) if r is not None]
```
**Files:** `app.py` → `_process_dm`, `_process_mention`; `knowledge_base.py` → `search()`  
**Status:** ✅ Resolved

---

## INC-022 — Bot Replies Going to Thread Instead of Main Chat

**Symptom:** Bot answers appeared only in the thread (right-side panel / "thread history") rather than in the main channel conversation. Users on mobile especially missed responses entirely.

**Root cause:** `say(thread_ts=event["ts"])` was used for all Q&A replies in `_process_mention`. The `thread_ts` parameter posts the message as a thread reply, not as a regular channel message. Without it, `say()` posts directly into the channel conversation.

**What didn't work (dead ends to avoid):**

1. `reply_broadcast=True` — This creates a special "thread broadcast" copy in the channel, but it renders differently from normal messages and users don't recognise it as a chat reply. When combined with `chat_update` it's even worse: `chat_update` only updates the thread copy; the channel-feed broadcast copy is a separate message entity that never gets updated.

2. `client.chat_postMessage(channel=channel, text=answer)` directly — Failed silently in the event-handler context (no ⏳ appeared, no answer appeared). Root cause unclear; likely a channel membership or permission scope issue (`chat:write` vs `chat:write.public`). Bolt's `say()` uses the same underlying call but works reliably because it is pre-scoped to the event's channel and workspace context.

**Fix:**
- Use `say()` with **no `thread_ts`** for all Q&A answers — reply appears as a normal channel message.
- Use `say()` (not `client.chat_postMessage`) for the ⏳ placeholder too.
- Use `client.chat_update()` to replace the placeholder in-place once the answer is ready — this works correctly because `chat_update` and the original `say()` call share the same channel context.

```python
# In handle_mention / handle_dm event handler:
resp           = say(text="⏳ Searching the knowledge base...")
placeholder_ts = resp.get("ts")
_pool.submit(_process_mention, event, say, client, placeholder_ts)

# In _process_mention worker:
answer = _qa_answer(channel, clean)
if placeholder_ts:
    client.chat_update(channel=channel, ts=placeholder_ts, text=answer)
else:
    say(text=answer)  # fallback
```

**Rule:** Always use `say()` for first contact in an event handler. Only use `client.chat_postMessage()` when you need to post to a *different* channel than the event channel (e.g. sending a reminder DM from the scheduler).

**Files:** `app.py` → `handle_mention`, `handle_dm`, `_process_mention`, `_process_dm`  
**Commits:** `f51bee1`, `d0349ea`  
**Status:** ✅ Resolved

---

## INC-021 — No Feedback When Sending Multiple Messages Quickly

**Symptom:** When messages were sent faster than the bot could reply (rapid-fire questions), later messages queued silently — no ⏳ placeholder, no reply, nothing visible in Slack. Users assumed the bot had crashed.  
**Root cause:** The "⏳ Searching the knowledge base..." placeholder was posted *inside* the `ThreadPoolExecutor` worker, not in the Slack event handler. With 4 workers and each Q&A taking 15–20 seconds, a 5th message would queue behind busy workers with zero user-visible acknowledgment until a worker freed up.  
**Fix:**
1. Move `client.chat_postMessage("⏳ Searching...")` into the event handler itself (`handle_dm`, `handle_mention`) — takes ~200 ms, safe in the receive thread.
2. Pass the resulting `placeholder_ts` into `_pool.submit(...)` so the worker only does the slow Notion + Claude work.
3. Bump thread pool from 4 → 8 workers to handle more concurrency.

Users now see ⏳ within ~200 ms of sending any message, regardless of how many are queued behind it.

**Files:** `app.py` → `handle_dm`, `handle_mention`, `_process_dm`, `_process_mention`  
**Status:** ✅ Resolved

---

## INC-020 — Bot Completely Ignores All Messages After First Response

**Symptom:** Bot answered the first question correctly. Every subsequent message in the same DM was silently ignored — no "⏳" placeholder, no reply, no Railway log entry for the question.  
**Root cause (1 — critical):** History corruption. In `_qa_answer`, the augmented user message was appended to `history` *before* the Claude API call. If the API call raised an exception (rate limit, bad response, network error), the message was never removed. The next question added another user turn → history had two consecutive `"role": "user"` entries → Claude rejected the request → exception → another orphaned user message was appended. After the first failure, all subsequent calls failed permanently.  
**Root cause (2):** `say()` closures passed to the thread pool. `say()` is a Bolt context closure captured at event dispatch time. Using `client.chat_postMessage()` directly (which is always valid) is safer for calls made after the receive-thread has moved on.  
**Fix (1):** Wrap the Claude API call in `try/except` and `pop()` the orphaned entry on failure:
```python
history.append({"role": "user", "content": augmented})
try:
    response = claude.messages.create(...)
    reply = response.content[0].text
except Exception:
    history.pop()  # prevent consecutive user turns
    raise
```
**Fix (2):** Replace all `say()` calls in `_process_dm` and `_process_mention` with `client.chat_postMessage()`.  
**Files:** `app.py` → `_qa_answer`, `_process_dm`, `_process_mention`  
**Status:** ✅ Resolved

---

## INC-023 — Feedback Learning System Integration

**Symptom:** No 👍/👎 buttons on answers; bot could not learn from user ratings.  
**Root cause:** `feedback_store.py` was rolled back during INC-022 debugging. Supabase `feedback` table existed but was not integrated into `app.py`.  
**Fix:** Re-integrated `feedback_store` into `app.py`:
- Added `_FEEDBACK_AVAILABLE` flag (graceful fallback if Supabase vars missing)
- `_qa_answer` now calls `feedback_store.get_relevant(question)` to prepend past positively-rated answers as extra Claude context
- Added `_answer_blocks(answer, feedback_id)` — wraps answer in a section block with 👍/👎 action buttons
- `_process_mention` and `_process_dm` call `feedback_store.create()` after each answer, pass `feedback_id` to `_answer_blocks`
- Added `handle_feedback_positive` / `handle_feedback_negative` action handlers — call `feedback_store.rate()`, update message to show thank-you note and remove buttons  
**Files:** `app.py`  
**Status:** ✅ Resolved — deployed May 27, 2026

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
| Bot offline, no response | Deployment in progress or stuck | Check Slack + Supabase via terminal, then `git commit --allow-empty -m "Force redeploy" && git push` |
| "We had some trouble connecting" on modal | trigger_id expired (Supabase call too slow) | Fixed in `f5905fa` — count cached in button value |
| No events at all, bot completely silent | `im:read` scope missing | Slack App → OAuth & Permissions → add `im:read` → Reinstall → update SLACK_BOT_TOKEN in Railway |
| Bot ignores all messages after first reply | History corruption in `_qa_answer` | Fixed in INC-020 — Claude API failure now pops orphaned history entry |
| Bot doesn't respond from mobile @mention | Mobile mention format `<@UID\|name>` not matched | Fixed in INC-016 — regex handles both desktop and mobile formats |
| No ⏳ feedback when sending messages quickly | Placeholder posted in pool worker, not event handler | Fixed in INC-021 — placeholder now posted before `_pool.submit()` |
| Replies go to thread, not main chat | `thread_ts` set on `say()` / `client.chat_postMessage()` used instead of `say()` | Fixed in INC-022 — use `say()` with no `thread_ts`; update placeholder with `chat_update` |
| No 👍/👎 buttons on answers | `feedback_store` not imported, rolled back | Fixed in INC-023 — re-integrated feedback_store, `_FEEDBACK_AVAILABLE` guards it |
