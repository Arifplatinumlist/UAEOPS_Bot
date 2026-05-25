# UAEOPS Monitor Agent

## Overview
An autonomous Slack monitoring agent that runs on a daily schedule via GitHub Actions. It monitors the `#uaeops-task` channel for event management tasks, detects completed threads, sends reminders to pending owners, posts a daily channel digest, and sends a weekly summary DM to Mohammed Arif every Friday.

**Technology Stack:**
- Python 3.12
- Slack SDK for message operations
- Anthropic Claude Haiku 4.5 for thread analysis
- GitHub Actions for scheduling (no external server required)

---

## Schedule

| Run | Cron | UTC | Target UAE Time | Notes |
|-----|------|-----|-----------------|-------|
| Daily | `0 4 * * *` | 04:00 | ~9:00 AM (Mon–Sun) | Cron fires 5 AM UTC; GitHub adds 60–90 min delay |
| Weekly | `0 5 * * 5` | 05:00 | ~10:00 AM (Friday) | Scheduled after daily to avoid clash on Fridays |

**Timezone note:** GitHub Actions cron runs in **pure UTC — no offset exists**. UAE is UTC+4, so: 9 AM UAE = 5 AM UTC. The crons are set 1 hour earlier than the target time to account for GitHub's typical 60–90 minute queue delay.

On Fridays both jobs run: the ~9 AM daily digest to channel, then the ~10 AM weekly DM to Arif.

---

## ⚠️ IMPORTANT — Working remotely or from multiple devices

**Always say one of these at the start of every Claude Code session:**

| Your situation | What to tell Claude |
|---------------|---------------------|
| Worked locally since last session | *"I've been working locally — please pull latest from main first"* |
| Coming from handoff doc / new device | *"I'm continuing from the session handoff"* + paste `SESSION_HANDOFF.md` |
| No local changes since last session | *"No local changes since last session"* |

**Before any local edit, always run:**
```bash
git pull origin main
```
Skipping this and pushing from a stale clone will silently overwrite remote changes. This happened once and broke the agent schedule and the weekly digest. Full details in `INCIDENT_REPORT.md`.

---

## What It Does

### 1. Thread Monitoring
- Watches all threads in `#uaeops-task` for new submissions
- Extracts task metadata from Slack workflow form submissions
- Stores thread state in `state.json` for persistence across runs
- Looks back 7 days on each run

### 2. Completion Detection
Uses a two-tier detection strategy:
- **Direct keyword matching** (fast path): Checks last reply against a list of completion keywords — "Thanks", "Done", "Fixed", "Resolved", "✅", "👍", etc.
- **AI analysis** (fallback): Uses Claude Haiku to understand complex thread context when direct matching doesn't apply

### 3. Reminders
- Identifies open tasks and the **primary pending user** who should respond next
- Sends a DM reminder **only to that user** (not event managers or other mentioned users)
- The primary pending user is determined by the first mentioned user in the last reply
- Respects a 6-hour cooldown per user per thread to avoid spam
- Only runs on daily (11 AM) runs — skipped during the Friday weekly run

**Example:** If a reply says "@Ahmed please check, @Fardin needs to finish" → only @Fardin gets the reminder

### 4. Daily Channel Digest
Posted to `#uaeops-task` every day at 11 AM UAE:
- **Resolved (Last 48h):** Tasks completed in the past 48 hours, with who resolved them and when
- **Overdue tasks (48-96h):** Tasks created 48–96 hours ago still open
- **Recent pending (0-48h):** Tasks created in the last 48 hours still open
- Reminders-sent count or "All caught up" footer

### 5. Weekly Digest DM (Friday 10 AM UAE)
Sent as a private DM to Mohammed Arif (`UJ0HP9ZQD`):
- **Resolved this week:** All tasks resolved over the past 7 days
- **Overdue tasks:** Open tasks older than 48 hours
- **Recent pending:** Open tasks from the last 48 hours
- Week summary line: `N resolved · N pending`

---

## Key Files

### `monitor.py` — Main Script

**Constants:**
- `CHANNEL_NAME` — `"uaeops-task"`
- `BOT_USER_ID` — Bot's Slack user ID (excluded from reminders)
- `ARIF_USER_ID` — `"UJ0HP9ZQD"` (Mohammed Arif, weekly digest recipient)
- `REMINDER_COOLDOWN_HOURS` — `6` (minimum gap between reminders per user/thread)

**Thread Analysis:**
- `analyze_thread()` — Detects if a thread is completed (keyword match → AI fallback)
- `is_completion_keyword()` — Fast path keyword check on the last reply
- `extract_mentioned_users()` — Finds all `<@USER_ID>` mentions in a message
- `extract_form_submitter()` — Extracts actual task submitter from `:brain: *Submitted by :*` field
- `extract_event_manager()` — Extracts event manager from `:sparkles: *Event Manager :*` field
- `who_should_respond()` — Determines which user(s) should be reminded

**Slack Output:**
- `send_reminder()` — DMs a user with a pending action reminder
- `post_channel_digest()` — Posts the daily formatted digest to the channel
- `post_weekly_digest()` — DMs Mohammed Arif a full 7-day summary

**State Management:**
- `load_state()` / `save_state()` — Read/write `state.json`
- Tracks status, creation date, reminder history, and extracted title per thread

**Run Mode Detection:**
- `os.environ.get("WEEKLY_DIGEST")` — Set to `"true"` by the Friday cron trigger
- When weekly: skip reminders and channel digest; only send `post_weekly_digest()`
- When daily: send reminders and `post_channel_digest()`; skip `post_weekly_digest()`

### `cleanup_digests.py` — Cleanup Utility
Safely deletes old digest messages from `#uaeops-task`. Use when the channel gets cluttered.

```bash
export SLACK_BOT_TOKEN="xoxb-your-token"
python3 cleanup_digests.py
```

Detects digests by markers: `#uaeops-task Digest`, `Overdue tasks`, `Recent pending`, `Resolved (Last 48h)`, `_Sent using @Claude_`.

### `state.json` — Persistent State
Auto-committed back to the repo after each run. Structure:

```json
{
  "last_run": "ISO timestamp",
  "known_threads": {
    "message_ts": {
      "starter_user": "Slack user ID of actual submitter",
      "starter_text": "Original form submission text",
      "status": "open | resolved",
      "created_at": "ISO timestamp",
      "reminders": { "user_id": "last reminder ISO timestamp" },
      "title": "Extracted event name"
    }
  }
}
```

### `.github/workflows/monitor.yml` — Scheduler
Two cron triggers:
- `0 7 * * *` → daily 11 AM UAE
- `0 6 * * 5` → Friday 10 AM UAE (weekly digest)

Passes `WEEKLY_DIGEST=true` to `monitor.py` when the Friday cron fires.

### `requirements.txt`
```
slack-sdk==3.33.0
anthropic==0.49.0
```

---

## Setup & Configuration

### GitHub Actions Secrets
| Secret | Description |
|--------|-------------|
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-...`) |
| `ANTHROPIC_API_KEY` | Anthropic API key (`sk-ant-...`) |

### Required Slack Bot Scopes
`channels:read`, `groups:read`, `chat:write`, `channels:history`, `groups:history`, `im:write`, `users:read`

### Local Testing
```bash
export SLACK_BOT_TOKEN="xoxb-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Daily mode
python3 monitor.py

# Weekly digest mode
WEEKLY_DIGEST=true python3 monitor.py
```

---

## How the Agent Works

### Slack Form Format
Tasks are submitted via Slack workflow with this structure:
```
:brain: *Submitted by :* <@USER_ID>
:hourglass: *Submitted on :* [date/time]
:sparkles: *Event Manager :* <@MANAGER_ID>
:gear: *New Event :* Yes / No
:ninja::skin-tone-4: *Event Name:* [Event Name Here]
:link: *Event Link :* [link]
:link: *Task direct link:* [link]
:calendar: *Event Date:* [date]
:link: *Organizer promo link:* [link]
:white_check_mark: *Assisted by:* <@ASSISTANT_ID>
```

The `:ninja::skin-tone-4: *Event Name:*` field is extracted as the task title.

### Completion Detection
**Direct keyword match (fast path):**
Checks last reply text against: `thanks`, `thank you`, `done`, `completed`, `finished`, `fixed`, `resolved`, `sorted`, `✅`, `👍`, `approved`, `ready`, `noted`, `acknowledged`, `confirmed`, `built`, `integrated`, `great`, `perfect`, `looks good`, `all set`, `ok`, `okay`, `yes`, `yep`, `will do`.

**AI analysis (fallback):**
If no direct match, Claude Haiku analyzes the thread and returns a JSON object:
```json
{ "resolved": true/false, "title": "event name", "action": "what needs doing", "urgent": true/false }
```

### Pending User Logic
1. Extract the actual form submitter from `:brain: *Submitted by :*` (not the bot that posted it)
2. Check the last reply for `<@USER_ID>` mentions → use **only the FIRST mention** (primary user)
3. If last reply is from the original submitter, check the second-to-last reply for mentions
4. Filter out the bot user ID from results
5. **Result:** Only ONE user (the primary pending user) receives the reminder, not all mentioned users

### Time Categorization
| Category | Age Range |
|----------|-----------|
| Overdue | 48–96 hours old |
| Recent | 0–48 hours old |

---

## Message Formats

### Daily Channel Digest
```
*#uaeops-task Digest — 16 May 2026*

:white_check_mark: *Resolved (Last 48h)*
• Event Name | Manager: Name
  ✓ Resolved By on 15 May 02:30PM

🔴 *Overdue tasks* (48-96 hours)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Event name:* Name | *Event Manager:* Name
  _Pending by:_ Name

🟡 *Recent pending* (0-48 hours)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Event name:* Name | *Event Manager:* Name
  _Pending by:_ Name

🔔 Reminders sent to N team member(s)
_Sent using @Claude_
```

### Weekly DM to Mohammed Arif
```
*#uaeops-task Weekly Digest — 10 May to 16 May 2026*

:white_check_mark: *Resolved this week (N)*
• Event Name | Manager: Name
  ✓ Resolved By on 14 May 03:00PM

🔴 *Overdue tasks (N)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Event name:* Name | *Event Manager:* Name
  _Pending by:_ Name

🟡 *Recent pending (N)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Event name:* Name | *Event Manager:* Name
  _Pending by:_ Name

📊 *Week summary:* N resolved · N pending
_Sent using @Claude_
```

---

## Common Issues & Solutions

### "Channel not found"
Bot lacks permission or the private channel isn't accessible. Ensure the bot is invited to `#uaeops-task` and has `groups:read` scope.

### "Pending by" shows the submitter themselves
Prevented by rule: `pending_user` must never equal `starter_user`. The code enforces this:
```python
non_starter_targets = [u for u in targets if u != starter]
pending_user = non_starter_targets[0] if non_starter_targets else None
```
If all targets are the submitter, no "Pending by" is shown. If this breaks, check that `starter_user` is correctly populated in `state.json`.

### Wrong "Pending by" user (someone other than submitter)
Verify `:brain: *Submitted by :*` is present in the form text. Check `who_should_respond()` — it inspects the previous reply if the last reply is from the original submitter.

### AI not detecting completion
Add the missing keyword to `is_completion_keyword()`. If the thread is genuinely ambiguous, review the AI prompt in `analyze_thread()`.

### Reminders sent too frequently
`REMINDER_COOLDOWN_HOURS = 6` — a reminder per user per thread will only fire once every 6 hours.

### Only one user getting reminder (not multiple)
This is correct behavior. Only the **primary pending user** (first mentioned in last reply) receives reminders.
Event managers and other mentioned users do NOT receive reminders to reduce spam. To send a reminder to 
a different user, ensure they are the first mention in the next reply.

### Git merge conflicts in state.json
```bash
git fetch origin
git reset --hard origin/main
```

### Digest runs at wrong time
Verify cron values in `.github/workflows/monitor.yml` are correct. GitHub Actions cron runs in **pure UTC — no offset exists**. UAE is UTC+4, so subtract 4 hours:

```
11:00 AM UAE → 07:00 UTC → cron: 0 7 * * *   ✓ correct
10:00 AM UAE → 06:00 UTC → cron: 0 6 * * 5   ✓ correct
```

If someone "compensated" the values (e.g. changed to `0 3` thinking GitHub adds +4h), that is wrong and will run the agent 4 hours early. See `INCIDENT_REPORT.md` for full details of this exact incident.

### Weekly digest to Arif not sending
Check that the `WEEKLY_DIGEST` detection in `monitor.yml` matches the Friday cron exactly:
```yaml
- cron: "0 6 * * 5"
  ...
  WEEKLY_DIGEST: ${{ github.event.schedule == '0 6 * * 5' && 'true' || 'false' }}
```
If the cron value and the string in the condition don't match, `WEEKLY_DIGEST` will always be `false` and the DM will silently never send.

### Working from a local machine or different device
Always pull before editing:
```bash
git pull origin main   # mandatory before any local edit
```
Editing on a stale clone and pushing will silently overwrite changes made in other sessions. See `INCIDENT_REPORT.md` for a full breakdown of this incident.

---

## Running the Agent

### Automatic (GitHub Actions)
Two scheduled triggers in `.github/workflows/monitor.yml`. GitHub Actions logs are at:
`https://github.com/Arifplatinumlist/uaeops-monitor/actions`

### Manual Execution
```bash
cd uaeops-monitor
export SLACK_BOT_TOKEN="xoxb-..."
export ANTHROPIC_API_KEY="sk-ant-..."
python3 monitor.py                    # Daily mode
WEEKLY_DIGEST=true python3 monitor.py # Weekly mode
```

### Cleaning Up Old Digests
```bash
export SLACK_BOT_TOKEN="xoxb-..."
python3 cleanup_digests.py
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Run (daily mode) | `python3 monitor.py` |
| Run (weekly mode) | `WEEKLY_DIGEST=true python3 monitor.py` |
| Clean digests | `python3 cleanup_digests.py` |
| Check state | `cat state.json` |
| View Action logs | GitHub Actions UI |
| Get channel ID | Slack → right-click channel → Copy ID |

---

## References

- Slack API: https://api.slack.com/methods
- Anthropic API: https://docs.anthropic.com
- GitHub repo: https://github.com/Arifplatinumlist/uaeops-monitor
