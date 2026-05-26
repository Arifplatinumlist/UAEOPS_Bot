---
name: uaeops-debug
description: >
  Diagnose and fix UAEOPS Bot issues on Slack and Railway. Use this skill
  whenever the user says the bot is not responding, something went wrong,
  there's a Slack error, the bot is down, they see "We had some trouble
  connecting", reminders aren't working, Q&A is broken, or they ask "why
  isn't the bot working". Also triggers for Railway deployment failures,
  crash loops, or any mention of the UAEOPS Bot behaving unexpectedly.
  Always use this skill first before doing any ad-hoc debugging — it knows
  the full incident history and the fastest diagnostic path.
---

# UAEOPS Bot — Debug Skill

## Project location
All bot code lives at: `/Users/mohammedarif/UAEOPS_Bot/`

Key files:
- `app.py` — all Slack handlers and bot logic
- `reminders.py` — Supabase reminder storage
- `knowledge_base.py` — Notion search
- `INCIDENT_REPORT.md` — every known bug and its fix
- `HANDOVER.md` — full architecture and Railway details

## Step 1 — Check the incident report first

Before doing anything else, read `INCIDENT_REPORT.md`. The symptom the user is describing has likely happened before. Match the symptom to an incident and apply the documented fix.

Common matches:
| Symptom | Incident |
|---------|---------|
| "We had some trouble connecting" in reminder modal | INC-014 (trigger_id timeout) |
| Bot online but ignores all messages | INC-005 (event subscriptions) |
| Railway crash on startup | INC-006 (env vars not deployed) or INC-008 (wrong Supabase key) |
| "Something went wrong" on every message | INC-009 or INC-011 |
| Reminders disappeared | INC-007 |
| Q&A finds nothing | INC-012 (Notion pages not connected) |
| Bot offline after multiple pushes | INC-013 (rapid redeploys) |

## Step 2 — Run terminal diagnostics

Run these checks in parallel:

```bash
# 1. Slack bot token valid?
SLACK_TOKEN=$(grep SLACK_BOT_TOKEN /Users/mohammedarif/UAEOPS_Bot/.env | cut -d= -f2-)
curl -s -X POST "https://slack.com/api/auth.test" \
  -H "Authorization: Bearer $SLACK_TOKEN" | python3 -m json.tool

# 2. Slack app token valid? (Socket Mode)
APP_TOKEN=$(grep SLACK_APP_TOKEN /Users/mohammedarif/UAEOPS_Bot/.env | cut -d= -f2-)
curl -s -X POST "https://slack.com/api/auth.test" \
  -H "Authorization: Bearer $APP_TOKEN" | python3 -m json.tool

# 3. Anthropic API key valid?
ANTHROPIC_KEY=$(grep ANTHROPIC_API_KEY /Users/mohammedarif/UAEOPS_Bot/.env | cut -d= -f2-)
curl -s -o /dev/null -w "%{http_code}" https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_KEY" -H "anthropic-version: 2023-06-01"

# 4. Python syntax clean?
cd /Users/mohammedarif/UAEOPS_Bot && python3 -m py_compile app.py reminders.py knowledge_base.py && echo "All files OK"
```

## Step 3 — Interpret results

**Slack token → `"ok": false`**: Token is invalid or revoked. User must regenerate in Slack App dashboard and update Railway env vars.

**Slack app token → `"ok": false`**: Socket Mode can't connect. Regenerate the `xapp-...` token in Slack App → Basic Information → App-Level Tokens.

**Anthropic API → not 200**: API key invalid. Regenerate at https://console.anthropic.com.

**Python syntax error**: There's a broken file. Fix the syntax error, commit, and push.

**All checks pass but bot still silent**: The Railway container is probably mid-redeploy or crashed. Check if the Railway deployment is green. If it shows green but bot doesn't respond, ask the user to scroll to the bottom of Railway logs and report what the last lines say. Look for `expired_trigger_id`, `missing_scope`, or any Traceback.

## Step 4 — Force redeploy if needed

If all credentials are valid and code is clean but the bot is still offline:

```bash
cd /Users/mohammedarif/UAEOPS_Bot && git commit --allow-empty -m "Force redeploy" && git push origin main
```

Tell the user: Railway rebuilds in ~45 seconds. Try the bot again after that.

## Step 5 — After fixing, log the incident

If this was a new bug (not already in `INCIDENT_REPORT.md`), add a new entry. The file follows a numbered format (INC-001, INC-002, etc.). Include:
- Symptom
- Root cause
- Fix
- Files changed
- Commit hash
- Status: ✅ Resolved

Also update the Railway quick reference table at the bottom of `INCIDENT_REPORT.md`.

## Railway details (no CLI needed)

- **Project:** https://railway.com/project/1cd94266-60f8-4fd0-b456-473dfcfca643/service/ac97f6be-8658-4527-b71f-08b9afca0792
- **Supabase URL:** `https://ryqvaouqpufdacbhosyk.supabase.co`
- **Bot user ID in Slack:** `U0B2PHBJUAY`
- Railway CLI is not authenticated — all Railway checks must be done via curl or by asking the user to look at their dashboard

## What "green but not responding" means

Railway green = process is running. It does NOT mean Socket Mode is connected. If the bot shows green but doesn't reply:
1. Ask the user to paste the last ~10 lines of Railway logs
2. Look for the Socket Mode session line: `Starting to receive messages from a new connection`
3. If that line is absent, the Socket Mode handshake failed — likely a bad `SLACK_APP_TOKEN` in Railway
4. If that line is present but bot still doesn't reply, there's a handler crash — look for Traceback in the logs
