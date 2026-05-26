---
name: uaeops-deploy
description: >
  Safe deployment workflow for UAEOPS Bot code changes. Use this skill
  whenever the user wants to push, deploy, commit, or ship changes to the
  UAEOPS Bot — including fixes to app.py, reminders.py, or knowledge_base.py,
  or any time they say "push this", "deploy", "commit and push", "fix and deploy",
  or "ship it". Also triggers when a code fix has just been made and needs to go
  to Railway. Always use this skill instead of ad-hoc git commands — it prevents
  the rapid-redeploy problem (INC-013) and keeps the incident report up to date.
---

# UAEOPS Bot — Deploy Skill

## Project location
`/Users/mohammedarif/UAEOPS_Bot/`

The bot runs 24/7 on Railway. Every push to `main` triggers an automatic redeploy (~45 sec build). The terminal is only needed for making changes — Railway keeps the bot alive independently.

## Deploy checklist (always follow in order)

### 1. Syntax check before committing

Never commit broken code. Run this first:

```bash
cd /Users/mohammedarif/UAEOPS_Bot && python3 -m py_compile app.py reminders.py knowledge_base.py && echo "✅ All files clean"
```

If any file fails, fix the syntax error before proceeding.

### 2. Batch all changes into ONE commit

**Critical (INC-013):** Every push triggers a Railway rebuild (~45 sec offline). Multiple rapid pushes = bot offline for minutes. Always bundle everything into a single commit.

```bash
cd /Users/mohammedarif/UAEOPS_Bot
git add <specific files>   # never use git add -A blindly
git status                 # confirm what's staged
git diff --staged          # review the actual diff
```

Write a clear commit message explaining the *why*, not the what:

```bash
git commit -m "$(cat <<'EOF'
<summary of what was fixed and why>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

### 3. Push to main

```bash
git push origin main
```

Railway auto-deploys immediately. Tell the user: **wait ~45 seconds**, then test in Slack.

### 4. Update INCIDENT_REPORT.md if this was a bug fix

If the commit fixed a bug that wasn't already documented, add a new incident entry. Check the current highest number first:

```bash
grep "^## INC-" /Users/mohammedarif/UAEOPS_Bot/INCIDENT_REPORT.md | tail -3
```

Then append a new entry following the existing format:

```markdown
## INC-XXX — Short description

**Symptom:** What the user saw  
**Root cause:** Why it happened  
**Fix:** What was changed  
**Files:** Which files  
**Commit:** `<hash>`  
**Status:** ✅ Resolved
```

Also add a row to the Railway quick reference table at the bottom of the file.

Commit the updated incident report **in the same push if possible**, or as a separate commit if the fix is already deployed:

```bash
git add INCIDENT_REPORT.md && git commit -m "Add INC-XXX to incident report" && git push origin main
```

### 5. Verify deployment

After ~45 seconds, confirm the bot is back:
- Ask the user to try `@UAEOPS_Bot remind me` in Slack
- OR run the Slack auth check: `curl -s -X POST "https://slack.com/api/auth.test" -H "Authorization: Bearer $(grep SLACK_BOT_TOKEN .env | cut -d= -f2-)"` — if `"ok": true`, the token is still valid

## Force redeploy (no code change needed)

If Railway needs a kick without any code change:

```bash
cd /Users/mohammedarif/UAEOPS_Bot && git commit --allow-empty -m "Force redeploy" && git push origin main
```

## What NOT to do

- ❌ Don't push one file at a time — batch everything
- ❌ Don't use `git add .` or `git add -A` without reviewing `git status` first
- ❌ Don't skip the `py_compile` check — a syntax error will crash Railway on startup
- ❌ Don't push when Railway is already mid-deploy — wait for it to go green first

## Env vars reminder

If the fix requires a new environment variable, remind the user:
> "You'll need to add `VAR_NAME` to Railway → Variables tab → then click **Deploy**. Variables don't take effect until you explicitly deploy — they don't apply automatically."
