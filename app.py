import json
import os
import logging
import re
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import dateparser

import reminders as reminder_store

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Knowledge base is optional — bot still handles reminders without Supabase
try:
    import knowledge_base
    _KB_AVAILABLE = True
except Exception as _kb_err:
    logger.warning("Knowledge base unavailable (%s). Q&A disabled, reminders still work.", _kb_err)
    _KB_AVAILABLE = False

slack_app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a helpful UAEOPS assistant. You answer questions based on the knowledge base excerpts provided in each message.

Guidelines:
- Be warm, conversational, and natural — talk like a knowledgeable colleague, not a document
- Synthesise the excerpts into a clear answer; don't just copy-paste them verbatim
- When it adds context, mention where information came from (e.g. "According to the runbook…")
- If the excerpts don't contain enough to answer, say exactly: "I don't have that in my knowledge base yet — you may want to ask the team or have an admin add it."
- Never invent facts or use knowledge outside what's in the excerpts"""

NO_RESULTS_MSG = (
    "I searched my knowledge base but couldn't find anything relevant to that question. "
    "Try rephrasing, or let an admin know to add that topic with:\n"
    "`python ingest.py --file yourfile.pdf`"
)

histories: dict[str, list[dict]] = {}
MAX_TURNS = 10

# cached bot user ID (populated on first use)
_bot_uid: str | None = None

scheduler = BackgroundScheduler(timezone="UTC")


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_bot_uid(client) -> str:
    global _bot_uid
    if not _bot_uid:
        _bot_uid = client.auth_test()["user_id"]
    return _bot_uid


def _is_remind_request(text: str) -> bool:
    return bool(re.search(r"remind\s+me|set\s+a?\s+reminder", text, re.IGNORECASE))


def _preset_to_dt(preset: str) -> datetime:
    now = datetime.now(timezone.utc)
    presets = {
        "30m":          now + timedelta(minutes=30),
        "1h":           now + timedelta(hours=1),
        "4h":           now + timedelta(hours=4),
        "tomorrow_9am": (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0),
    }
    return presets[preset]


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%a %d %b %Y at %H:%M UTC")


# ── Block Kit builders ────────────────────────────────────────────────────────

def _time_picker_blocks(ctx: dict, count: int) -> list[dict]:
    """Blocks for choosing a reminder time. ctx carries message context."""
    remaining = reminder_store.MAX_REMINDERS - count
    ctx_str   = json.dumps(ctx)

    def btn(label, preset):
        return {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": "remind_preset",
            "value": json.dumps({"preset": preset, **ctx}),
        }

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"⏰ *When should I remind you?*\n"
                    f"_Reminder {count + 1}/{reminder_store.MAX_REMINDERS} "
                    f"— {remaining} remaining for this message._"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                btn("30 min",       "30m"),
                btn("1 hour",       "1h"),
                btn("4 hours",      "4h"),
                btn("Tomorrow 9am", "tomorrow_9am"),
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Custom time..."},
                    "action_id": "remind_custom_open",
                    "value": ctx_str,
                },
            ],
        },
    ]


def _reminder_dm_blocks(reminder: dict) -> list[dict]:
    num   = reminder["reminder_number"]
    total = reminder_store.MAX_REMINDERS
    text  = reminder["message_text"] or "(no text)"

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"👋 Hey <@{reminder['user_id']}>, here's the message you wanted to be reminded about:\n\n"
                    f"> {text[:200]}\n\n"
                    f"<{reminder['permalink']}|View original message>"
                ),
            },
        },
    ]

    if num < total:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done, thanks! ✅"},
                    "action_id": "remind_done",
                    "value": reminder["id"],
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Remind me again ({num}/{total})"},
                    "action_id": "remind_again",
                    "value": reminder["id"],
                },
            ],
        })
    else:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_This was your final reminder ({total}/{total}) for this message._",
                }
            ],
        })

    return blocks


# ── scheduler ─────────────────────────────────────────────────────────────────

def _send_reminder_dm(reminder_id: str):
    reminder = reminder_store.get(reminder_id)
    if not reminder or reminder["status"] != "pending":
        return

    reminder_store.update_status(reminder_id, "sent")
    try:
        slack_app.client.chat_postMessage(
            channel=reminder["user_id"],
            text=f"⏰ Reminder: {reminder['message_text'][:80]}",
            blocks=_reminder_dm_blocks(reminder),
        )
    except Exception as e:
        logger.error("Failed to send reminder DM %s: %s", reminder_id, e)


def _schedule(reminder: dict):
    run_at = datetime.fromisoformat(reminder["remind_at"])
    if run_at <= datetime.now(timezone.utc):
        # Already past — fire immediately
        _send_reminder_dm(reminder["id"])
        return
    scheduler.add_job(
        _send_reminder_dm,
        trigger=DateTrigger(run_date=run_at),
        id=reminder["id"],
        args=[reminder["id"]],
        replace_existing=True,
    )


def _load_pending_reminders():
    """On startup, reschedule any pending reminders from the JSON file."""
    pending = reminder_store.get_pending()
    logger.info("Reloading %d pending reminder(s) from file", len(pending))
    for r in pending:
        _schedule(r)


# ── Q&A answer (existing) ─────────────────────────────────────────────────────

def _qa_answer(channel_id: str, question: str) -> str:
    if not _KB_AVAILABLE:
        return (
            "The knowledge base isn't configured yet. "
            "Set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `.env`, "
            "run the migration, then restart the bot."
        )

    results = knowledge_base.search(question)
    if not results:
        return NO_RESULTS_MSG

    context = "\n\n---\n\n".join(
        f"[Source: {r.get('title') or r.get('source', 'unknown')}]\n{r['content']}"
        for r in results
    )
    augmented = f"Knowledge base excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"

    history = histories.setdefault(channel_id, [])
    history.append({"role": "user", "content": augmented})

    response = claude.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    reply = response.content[0].text

    history[-1] = {"role": "user", "content": question}
    history.append({"role": "assistant", "content": reply})

    if len(history) > MAX_TURNS * 2:
        histories[channel_id] = history[-(MAX_TURNS * 2):]

    return reply


# ── remind request handler (called from app_mention) ─────────────────────────

def _handle_remind_request(event, say, client):
    user_id  = event["user"]
    channel  = event["channel"]
    event_ts = event["ts"]
    thread_ts = event.get("thread_ts", event_ts)

    # The message to remind about is the thread root (or the message itself)
    ref_ts = thread_ts

    # Fetch the original message text
    ref_text = ""
    try:
        resp = client.conversations_history(channel=channel, latest=ref_ts, limit=1, inclusive=True)
        msgs = resp.get("messages", [])
        if msgs:
            raw = msgs[0].get("text", "")
            # Strip any bot mention from it
            ref_text = re.sub(r"<@\w+>", "", raw).strip()
    except Exception as e:
        logger.warning("Could not fetch ref message: %s", e)

    # Get permalink
    permalink = ""
    try:
        plink = client.chat_getPermalink(channel=channel, message_ts=ref_ts)
        permalink = plink.get("permalink", "")
    except Exception as e:
        logger.warning("Could not get permalink: %s", e)

    count = reminder_store.count_for_message(user_id, ref_ts)
    if count >= reminder_store.MAX_REMINDERS:
        say(
            text=f"You've already set the maximum of {reminder_store.MAX_REMINDERS} reminders for this message.",
            thread_ts=event_ts,
        )
        return

    ctx = {
        "user_id":      user_id,
        "channel_id":   channel,
        "message_ts":   ref_ts,
        "thread_ts":    thread_ts,
        "permalink":    permalink,
        "message_text": ref_text[:200],
    }
    say(
        text="⏰ When should I remind you?",
        blocks=_time_picker_blocks(ctx, count),
        thread_ts=event_ts,
    )


# ── Slack event handlers ───────────────────────────────────────────────────────

@slack_app.event("app_mention")
def handle_mention(event, say, client):
    try:
        channel   = event["channel"]
        bot_uid   = _get_bot_uid(client)
        raw_text  = event.get("text", "")
        clean     = raw_text.replace(f"<@{bot_uid}>", "").strip()

        if _is_remind_request(clean):
            _handle_remind_request(event, say, client)
            return

        if not clean:
            say("Hi! Ask me anything.", thread_ts=event["ts"])
            return

        client.reactions_add(channel=channel, name="thinking_face", timestamp=event["ts"])
        try:
            say(text=_qa_answer(channel, clean), thread_ts=event["ts"])
        finally:
            client.reactions_remove(channel=channel, name="thinking_face", timestamp=event["ts"])

    except Exception as e:
        logger.error("handle_mention error: %s", e, exc_info=True)
        try:
            say(text="Something went wrong — please try again.", thread_ts=event.get("ts"))
        except Exception:
            pass


@slack_app.event("message")
def handle_dm(event, say, client):
    try:
        if event.get("bot_id") or event.get("subtype") or event.get("channel_type") != "im":
            return

        question = event.get("text", "").strip()
        if not question:
            return

        channel = event["channel"]
        client.reactions_add(channel=channel, name="thinking_face", timestamp=event["ts"])
        try:
            say(text=_qa_answer(channel, question))
        finally:
            client.reactions_remove(channel=channel, name="thinking_face", timestamp=event["ts"])

    except Exception as e:
        logger.error("handle_dm error: %s", e, exc_info=True)
        try:
            say(text="Something went wrong — please try again.")
        except Exception:
            pass


# ── Reminder action handlers ───────────────────────────────────────────────────

@slack_app.action("remind_preset")
def handle_remind_preset(ack, body, respond, client):
    ack()
    try:
        payload  = json.loads(body["actions"][0]["value"])
        preset   = payload["preset"]
        user_id  = body["user"]["id"]
        ctx = {k: payload[k] for k in ("user_id", "channel_id", "message_ts", "thread_ts", "permalink", "message_text")}
        ctx["user_id"] = user_id  # ensure it's the clicker, not the original

        remind_at = _preset_to_dt(preset)
        reminder  = reminder_store.create(
            user_id      = user_id,
            channel_id   = ctx["channel_id"],
            message_ts   = ctx["message_ts"],
            thread_ts    = ctx["thread_ts"],
            permalink    = ctx["permalink"],
            message_text = ctx["message_text"],
            remind_at    = remind_at,
        )
        _schedule(reminder)

        num   = reminder["reminder_number"]
        total = reminder_store.MAX_REMINDERS
        respond(
            replace_original=True,
            text=f"✅ Reminder set!",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"✅ Got it! I'll remind you on *{_format_dt(remind_at)}*.\n"
                            f"_Reminder {num}/{total} for this message._"
                        ),
                    },
                }
            ],
        )
    except ValueError as e:
        respond(replace_original=False, text=str(e))
    except Exception as e:
        logger.error("remind_preset error: %s", e)
        respond(replace_original=False, text="Something went wrong setting your reminder.")


@slack_app.action("remind_custom_open")
def handle_remind_custom_open(ack, body, client):
    ack()
    ctx_str  = body["actions"][0]["value"]
    ctx      = json.loads(ctx_str)
    user_id  = body["user"]["id"]
    count    = reminder_store.count_for_message(user_id, ctx["message_ts"])
    remaining = reminder_store.MAX_REMINDERS - count

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type":             "modal",
            "callback_id":      "remind_custom_modal",
            "private_metadata": ctx_str,
            "title":  {"type": "plain_text", "text": "Set a reminder"},
            "submit": {"type": "plain_text", "text": "Set reminder"},
            "close":  {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type":     "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"_Reminder {count + 1}/{reminder_store.MAX_REMINDERS} — {remaining} remaining._",
                    },
                },
                {
                    "type":     "input",
                    "block_id": "custom_time",
                    "element":  {
                        "type":        "plain_text_input",
                        "action_id":   "time_input",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "e.g. tomorrow 3pm, in 2 hours, next Monday 9am",
                        },
                    },
                    "label": {"type": "plain_text", "text": "When should I remind you? (times are UTC)"},
                },
            ],
        },
    )


@slack_app.view("remind_custom_modal")
def handle_remind_custom_submit(ack, body, client):
    user_input = (
        body["view"]["state"]["values"]["custom_time"]["time_input"]["value"] or ""
    ).strip()

    parsed = dateparser.parse(
        user_input,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "TO_TIMEZONE": "UTC",
        },
    )
    if not parsed:
        ack(
            response_action="errors",
            errors={"custom_time": f"Couldn't understand '{user_input}'. Try 'tomorrow 3pm' or 'in 2 hours'."},
        )
        return

    ack()

    ctx     = json.loads(body["view"]["private_metadata"])
    user_id = body["user"]["id"]

    try:
        reminder = reminder_store.create(
            user_id      = user_id,
            channel_id   = ctx["channel_id"],
            message_ts   = ctx["message_ts"],
            thread_ts    = ctx["thread_ts"],
            permalink    = ctx["permalink"],
            message_text = ctx["message_text"],
            remind_at    = parsed,
        )
        _schedule(reminder)

        num   = reminder["reminder_number"]
        total = reminder_store.MAX_REMINDERS
        client.chat_postMessage(
            channel=user_id,
            text=(
                f"✅ Got it! I'll remind you on *{_format_dt(parsed)}*. "
                f"_(Reminder {num}/{total})_"
            ),
        )
    except ValueError as e:
        client.chat_postMessage(channel=user_id, text=str(e))
    except Exception as e:
        logger.error("remind_custom_submit error: %s", e)
        client.chat_postMessage(channel=user_id, text="Something went wrong setting your reminder.")


@slack_app.action("remind_done")
def handle_remind_done(ack, respond, body):
    ack()
    reminder_id = body["actions"][0]["value"]
    reminder_store.update_status(reminder_id, "done")
    respond(
        replace_original=True,
        text="All done! ✅",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": "All done! ✅ Reminder marked as complete."},
        }],
    )


@slack_app.action("remind_again")
def handle_remind_again(ack, respond, body, client):
    ack()
    reminder_id = body["actions"][0]["value"]
    original    = reminder_store.get(reminder_id)
    if not original:
        respond(replace_original=False, text="Reminder not found.")
        return

    user_id = body["user"]["id"]
    count   = reminder_store.count_for_message(user_id, original["message_ts"])

    if count >= reminder_store.MAX_REMINDERS:
        respond(
            replace_original=True,
            text=f"You've reached the maximum of {reminder_store.MAX_REMINDERS} reminders for this message.",
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚠️ You've used all {reminder_store.MAX_REMINDERS} reminders for this message.",
                },
            }],
        )
        return

    ctx = {
        "user_id":      user_id,
        "channel_id":   original["channel_id"],
        "message_ts":   original["message_ts"],
        "thread_ts":    original["thread_ts"],
        "permalink":    original["permalink"],
        "message_text": original["message_text"],
    }
    # Replace the DM buttons with a fresh time picker
    respond(
        replace_original=True,
        text="⏰ When should I remind you again?",
        blocks=_time_picker_blocks(ctx, count),
    )


# ── startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting UAEOPS Bot — KB available: %s", _KB_AVAILABLE)
    scheduler.start()
    _load_pending_reminders()
    logger.info("Bot ready. Connecting to Slack via Socket Mode...")
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
