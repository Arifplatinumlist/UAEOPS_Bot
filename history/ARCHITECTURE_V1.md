# UAEOPS Bot — V1 Architecture (Archived)

> Archived: May 2026
> Reason: Migrated to V2 multi-agent architecture (Option C)
> V1 files: `app_v1.py`, `reminders_v1.py`, `knowledge_base_v1.py`

---

## What V1 Did

V1 was a monolithic bot with two features living in a single `app.py` (~450 lines):

1. **Reminders** — user mentions `@UAEOPS_Bot remind me` in any channel. Bot shows a time picker (30 min / 1 hour / 4 hours / Tomorrow 9am / Custom). At the scheduled time, sends a DM with a link back to the original message. Up to 3 reminders per message.

2. **Knowledge Base Q&A** — user mentions `@UAEOPS_Bot <question>` or DMs the bot. Bot searches connected Notion pages and answers via Claude.

Two helper files:
- `reminders.py` — Supabase REST API CRUD for persisting reminders across Railway redeployments
- `knowledge_base.py` — Notion REST API search + block content fetching

---

## Why It Changed

Adding a third feature (alert handling) would have meant a third `elif` branch in `handle_mention()`, a third block of inline logic, and a system prompt clash between Q&A and alert triage in the same function. The monolith would have become unmaintainable.

The team chose **Option C**: one Slack-facing bot, multiple internal agents. Each agent has one job, one system prompt, and no knowledge of the others. The router classifies intent and delegates.

---

## V1 Message Flow

```
Slack message (@mention or DM)
         │
         ▼
    app.py
    handle_mention() / handle_dm()
         │
         ▼
  _is_remind_request(text)?
    regex: "remind me" / "set a reminder"
         │
    ┌────┴────┐
    YES      NO
    │         │
    ▼         ▼
_handle_    _qa_answer()
remind_       │
request()     ├─ knowledge_base.search(question)
    │         │     └─ Notion API → POST /v1/search
    │         │        └─ fetch block content
    │         │
    │         └─ claude.messages.create()
    │              system: SYSTEM_PROMPT
    │              messages: histories[channel_id]
    │
    └─ show time picker (Block Kit buttons)
         │
         ▼
    User clicks button
         │
         ▼
    handle_remind_preset() / handle_remind_custom_*()
         │
         ├─ reminder_store.create() → Supabase INSERT
         ├─ scheduler.add_job() → APScheduler
         └─ respond(replace_original=True) → update message in-place
              │
              ▼ (at scheduled time)
         _send_reminder_dm()
              └─ slack_app.client.chat_postMessage() → DM to user
```

---

## V1 Agent Lifecycle (full example — Q&A)

```
1. User types: @UAEOPS_Bot what is the escalation procedure?

2. Slack → Railway (Socket Mode) → handle_mention()

3. Strip bot mention → clean = "what is the escalation procedure?"

4. _is_remind_request("what is the escalation...") → False

5. reactions_add(thinking_face) → user sees 🤔

6. _qa_answer(channel_id, "what is the escalation procedure?")
   │
   ├─ knowledge_base.search("what is the escalation procedure?")
   │   └─ POST https://api.notion.com/v1/search
   │       └─ fetch block content for top results
   │       └─ return list of {title, content} dicts
   │
   ├─ build augmented prompt:
   │   "Knowledge base excerpts:\n[Source: Escalation Runbook]\n...\n\nQuestion: what is the escalation procedure?"
   │
   ├─ histories[channel_id].append({role: user, content: augmented})
   │
   ├─ claude.messages.create(model, system=SYSTEM_PROMPT, messages=history)
   │   └─ returns: "According to the runbook, escalation goes to..."
   │
   ├─ histories[channel_id].append({role: assistant, content: reply})
   │   (trimmed to MAX_TURNS * 2 if too long)
   │
   └─ return reply

7. say(text=reply, thread_ts=event_ts) → posted in Slack thread

8. reactions_remove(thinking_face) → 🤔 removed
```

---

## V1 Agent Lifecycle (full example — Reminder)

```
1. User reacts to a message: @UAEOPS_Bot remind me

2. Slack → handle_mention()

3. _is_remind_request("remind me") → True

4. _handle_remind_request(event, say, client)
   │
   ├─ conversations_history() → fetch original message text
   ├─ chat_getPermalink() → get link to original message
   ├─ reminder_store.count_for_message(user_id, ref_ts) → Supabase SELECT COUNT
   │
   └─ say(blocks=_time_picker_blocks(ctx, count))
       → user sees: [30 min] [1 hour] [4 hours] [Tomorrow 9am] [Custom time...]

5. User clicks "1 hour"

6. handle_remind_preset(ack, body, respond, client)
   │
   ├─ ack()
   ├─ _preset_to_dt("1h") → datetime = now_UAE + 1h
   ├─ reminder_store.create(...) → Supabase INSERT → returns reminder dict
   ├─ _schedule(reminder) → scheduler.add_job(_send_reminder_dm, run_at=dt)
   └─ respond(replace_original=True) → "✅ Got it! I'll remind you on Thu 29 May at 15:30 UAE"
                                         + [✕ Dismiss] button

7. (1 hour later) APScheduler fires _send_reminder_dm(reminder_id)
   │
   ├─ reminder_store.get(reminder_id) → Supabase SELECT
   ├─ reminder_store.update_status(id, "sent") → Supabase UPDATE
   └─ chat_postMessage(channel=user_id, blocks=_reminder_dm_blocks(reminder))
       → DM: "👋 Here's the message you wanted to be reminded about: ..."
              [Done, thanks! ✅]  [Remind me again (1/3)]
```

---

## V1 File Responsibilities

| File | Lines | Responsibility |
|---|---|---|
| `app.py` | ~450 | Everything: Slack handlers, reminder logic, Q&A logic, Block Kit, scheduler, globals |
| `reminders.py` | ~80 | Supabase REST API CRUD for reminders table |
| `knowledge_base.py` | ~100 | Notion REST API search + block content fetching |

---

## V2 Migration

See `/agents/` directory and root `router.py`, `conversation.py` for the new architecture.

V2 adds:
- `router.py` — intent classification (reminder / alert / qa / unknown)
- `agents/kb_agent.py` — absorbs `knowledge_base.py`
- `agents/reminder_agent.py` — absorbs `reminders.py` + all reminder logic from `app.py`
- `agents/qa_agent.py` — absorbs `_qa_answer()` from `app.py`
- `agents/alert_agent.py` — new: system alert triage
- `conversation.py` — absorbs `histories` global from `app.py`
- `app.py` — trimmed to ~120 lines: Slack plumbing only
