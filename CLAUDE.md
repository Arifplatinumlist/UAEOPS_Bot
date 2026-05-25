# UAEOPS Monitor — Claude Code Context

## ⚠️ IMPORTANT — Working remotely or from a different device

**Always say one of these at the start of every new session:**

| Your situation | What to tell Claude |
|---------------|---------------------|
| Worked locally since last session | *"I've been working locally — please pull latest from main first"* |
| Coming from handoff doc / new device | *"I'm continuing from the session handoff"* + paste `SESSION_HANDOFF.md` |
| Haven't touched anything locally | *"No local changes since last session"* |

**Why this matters:** Editing on a stale local clone and pushing overwrites cloud changes silently. This caused a real incident where the agent ran 4 hours early and the weekly digest to Mohammed Arif stopped firing. Full details in `INCIDENT_REPORT.md`.

**Claude will always `git fetch` at session start to check for drift — but you telling me helps too.**

---

## What this repo does
Autonomous GitHub Actions agent that monitors the Slack channel `#uaeops-task`, detects completed/pending event management tasks, sends reminders, and posts digests.

## Schedule
- **Daily ~9 AM UAE (04:00 UTC cron):** `0 4 * * *` — reminders + channel digest. Cron fires at 5 AM UTC; GitHub typically adds 60–90 min delay, so digest arrives ~9 AM UAE.
- **Friday ~10 AM UAE (05:00 UTC cron):** `0 5 * * 5` — weekly DM digest to Mohammed Arif only. Scheduled slightly after daily to avoid same-time clash on Fridays.

**WEEKLY_DIGEST detection string must match the Friday cron exactly:** `'0 5 * * 5'`

The Friday weekly run sets `WEEKLY_DIGEST=true`; this skips reminders and channel digest and only calls `post_weekly_digest()`.

## Key files
| File | Purpose |
|------|---------|
| `monitor.py` | Main agent — runs on every schedule trigger |
| `cleanup_digests.py` | Manual utility to delete old digest messages from channel |
| `state.json` | Persisted thread state (auto-committed by Actions after each run) |
| `.github/workflows/monitor.yml` | Cron schedule + secrets wiring |
| `requirements.txt` | `slack-sdk==3.33.0`, `anthropic==0.49.0` |

## Important constants in monitor.py
```python
CHANNEL_NAME = "uaeops-task"
BOT_USER_ID = "D0B2S4PPTS7"       # bot — excluded from reminder targets
ARIF_USER_ID = "UJ0HP9ZQD"        # Mohammed Arif — weekly digest DM recipient
REMINDER_COOLDOWN_HOURS = 6        # min gap between reminders per user/thread
```

## Secrets required (GitHub Actions)
- `SLACK_BOT_TOKEN` — `xoxb-...`
- `ANTHROPIC_API_KEY` — `sk-ant-...`

## Run modes
```bash
# Daily mode
python3 monitor.py

# Weekly digest mode (Friday only)
WEEKLY_DIGEST=true python3 monitor.py
```

## Core functions
- `analyze_thread()` — keyword match → Claude Haiku fallback → returns `{resolved, title, action, urgent}`
- `who_should_respond()` — determines reminder targets from thread mentions
- `send_reminder()` — DMs the target user (falls back to in-thread if DMs blocked)
- `post_channel_digest()` — daily summary posted to `#uaeops-task`
- `post_weekly_digest()` — Friday DM to Arif with 7-day summary

## Pending user rule (critical)
`pending_user` shown in the digest must **never** be the same as the task submitter (`starter_user`).
Code enforces this at `main()`:
```python
non_starter_targets = [u for u in targets if u != starter]
pending_user = non_starter_targets[0] if non_starter_targets else None
```
If all targets are the submitter, no "Pending by" is shown.

## State shape (state.json)
```json
{
  "last_run": "ISO timestamp",
  "known_threads": {
    "<message_ts>": {
      "starter_user": "Slack user ID",
      "starter_text": "raw form text",
      "status": "open | resolved",
      "created_at": "ISO timestamp",
      "reminders": { "<user_id>": "ISO timestamp" },
      "title": "event name"
    }
  }
}
```

## Slack form fields (extracted by regex)
- Submitter: `:brain: *Submitted by :* <@USER>`
- Event Manager: `:sparkles: *Event Manager :* <@USER>`
- Event Name: `:ninja::skin-tone-4: *Event Name:* <name>`

## Time buckets used in digests
| Label | Age |
|-------|-----|
| Resolved (daily) | resolved in last 48h |
| Resolved (weekly) | resolved in last 7 days |
| Overdue | created > 48h ago, still open |
| Recent pending | created ≤ 48h ago, still open |

## Active branch
All changes are on `main`. No open feature branches.
