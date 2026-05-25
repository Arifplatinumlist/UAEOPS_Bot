# Incident Report — Cron Schedule Corruption
**Date:** 2026-05-18  
**Severity:** High — Agent running 4 hours early daily, weekly digest to Mohammed Arif silently never firing  
**Status:** ✅ Resolved

---

## What Broke

| Setting | Wrong (broken) | Correct (fixed) |
|---------|---------------|-----------------|
| Daily cron | `0 3 * * *` → 03:00 UTC = **7 AM UAE** | `0 7 * * *` → 07:00 UTC = **11 AM UAE** |
| Friday cron | `0 2 * * 5` → 02:00 UTC = **6 AM UAE** | `0 6 * * 5` → 06:00 UTC = **10 AM UAE** |
| Weekly digest trigger | Checked `'0 6 * * 5'` but cron was `'0 2 * * 5'` → **never fired** | Both match `'0 6 * * 5'` → fires correctly |

---

## Root Cause

### The false assumption
A session on a local machine applied a "+4 hour offset" to the cron times under the belief that GitHub Actions adds a UTC offset for UAE. **This is incorrect.** GitHub Actions cron runs in pure UTC with no automatic offset adjustment. UAE is UTC+4, so:

- 11 AM UAE = 07:00 UTC → cron must be `0 7 * * *`
- 10 AM UAE = 06:00 UTC → cron must be `0 6 * * 5`

No compensation is needed or correct.

### The git sync problem
The local machine had a stale clone that had not been pulled before making edits. The sequence:

```
[Cloud session]  pushed correct  0 7 / 0 6  →  main
[Local machine]  still on old clone, unaware of cloud changes
[Local machine]  edited workflow with wrong 0 3 / 0 2 values
[Local machine]  pushed → overwrote the correct cloud version
```

Git accepted the push because there were no file conflicts — the local version simply won by being pushed last.

### The silent failure
The `WEEKLY_DIGEST` detection in the workflow:
```yaml
WEEKLY_DIGEST: ${{ github.event.schedule == '0 6 * * 5' && 'true' || 'false' }}
```
After the cron was changed to `0 2 * * 5`, this check could never match — `WEEKLY_DIGEST` was always `false`. The weekly digest to Mohammed Arif (`UJ0HP9ZQD`) had been silently not sending since the bad push, with no error or alert.

---

## How It Was Caught

Noticed during a documentation review pass. The `CLAUDE.md` and `SESSION_HANDOFF.md` files referenced cron values (`0 3`/`0 2`) that didn't match the intended schedule, which prompted checking the actual remote workflow file.

---

## Fix Applied

Restored `.github/workflows/monitor.yml` to:
```yaml
- cron: "0 7 * * *"   # Daily 11 AM UAE (07:00 UTC, UAE is UTC+4)
- cron: "0 6 * * 5"   # Weekly Friday 10 AM UAE (06:00 UTC)
```
With `WEEKLY_DIGEST` detection matching `'0 6 * * 5'`. Removed the incorrect `TZ: UTC` job-level env var and offset comments. Committed and pushed to `main`.

---

## ⚠️ Standing Rule — Always say this at the start of every Claude session

| Your situation | What to tell Claude |
|---------------|---------------------|
| Worked locally since last session | *"I've been working locally — please pull latest from main first"* |
| Coming from handoff doc / new device | *"I'm continuing from the session handoff"* + paste `SESSION_HANDOFF.md` |
| No local changes since last session | *"No local changes since last session"* |

This takes 5 seconds and prevents the entire class of incidents described in this report.

---

## Prevention Rules (Going Forward)

### Rule 1 — Always pull before editing locally
```bash
git pull origin main   # mandatory before any local edit
# make changes
git add .
git commit -m "message"
git push origin main
```

### Rule 2 — Prefer GitHub web editor for small changes
For single-file edits, use the GitHub web UI (`github.com/Arifplatinumlist/uaeops-monitor`) — it always edits the live version and cannot create sync conflicts.

### Rule 3 — UTC conversion for UAE
UAE is **UTC+4**. To convert a desired UAE time to a cron UTC value:
```
UAE time − 4 hours = UTC cron value

11:00 AM UAE → 11 - 4 = 07:00 UTC → cron: 0 7 * * *
10:00 AM UAE → 10 - 4 = 06:00 UTC → cron: 0 6 * * 5
```
GitHub Actions applies **no offset**. What you put in cron is the UTC time it runs.

### Rule 4 — When changing a cron value, update the WEEKLY_DIGEST check too
The `WEEKLY_DIGEST` env var detection must always match the Friday cron exactly:
```yaml
- cron: "0 6 * * 5"   ← cron value
  ...
  WEEKLY_DIGEST: ${{ github.event.schedule == '0 6 * * 5' && 'true' || 'false' }}
                                               ↑ must match exactly
```

---

## Timeline

| Time | Event |
|------|-------|
| Session 1 (cloud) | Set cron to `0 7`/`0 6`, pushed to main |
| Session 2 (local machine) | Edited workflow on stale clone, pushed `0 3`/`0 2` with false offset theory |
| Session 3 (cloud) | Discovered mismatch during doc review, restored correct values, pushed fix |
