import json
import os
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Optional
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

# Knowledge base is optional — bot still handles reminders without Notion
try:
    import knowledge_base
    if not os.environ.get("NOTION_TOKEN"):
        raise RuntimeError("NOTION_TOKEN not set")
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
    "I searched the Notion knowledge base but couldn't find anything relevant to that question. "
    "Try rephrasing, or ask an admin to add a Notion page covering that topic and connect it to the bot integration."
)

histories: dict[str, list[dict]] = {}
MAX_TURNS = 10

# cached bot user ID (populated on first use)
_bot_uid: Optional[str] = None

UAE_TZ = timezone(timedelta(hours=4))
scheduler = BackgroundScheduler(timezone="Asia/Dubai")

# Thread pool — lets slow Notion+Claude calls run without blocking the
# Socket Mode WebSocket receive loop, so rapid messages are never dropped.
_pool = ThreadPoolExecutor(max_workers=4)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_bot_uid(client) -> str:
    global _bot_uid
    if not _bot_uid:
        _bot_uid = client.auth_test()["user_id"]
    return _bot_uid


def _is_remind_request(text: str) -> bool:
    return bool(re.search(r"remind\s+me|set\s+a?\s+reminder", text, re.IGNORECASE))


def _preset_to_dt(preset: str) -> datetime:
    now_uae = datetime.now(UAE_TZ)
    presets = {
        "30m":          now_uae + timedelta(minutes=30),
        "1h":           now_uae + timedelta(hours=1),
        "4h":           now_uae + timedelta(hours=4),
        "tomorrow_9am": (now_uae + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0),
    }
    return presets[preset]


def _format_dt(dt: datetime) -> str:
    return dt.astimezone(UAE_TZ).strftime("%a %d %b %Y at %H:%M UAE")


# ── Block Kit builders ────────────────────────────────────────────────────────

def _time_picker_blocks(ctx: dict, count: int) -> list[dict]:
    """Blocks for choosing a reminder time. ctx carries message context."""
    remaining = reminder_store.MAX_REMINDERS - count
    ctx_str   = json.dumps(ctx)

    def btn(label, preset):
        return {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": f"remind_preset_{preset}",
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
                    "value": json.dumps({**ctx, "count": count}),
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
    """On startup, reschedule any pending reminders from Supabase."""
    try:
        pending = reminder_store.get_pending()
        logger.info("Reloading %d pending reminder(s) from database", len(pending))
        for r in pending:
            _schedule(r)
    except Exception as e:
        logger.error("Could not load pending reminders from Supabase — bot will still start: %s", e)


# ── Q&A answer (existing) ─────────────────────────────────────────────────────

def _qa_answer(channel_id: str, question: str) -> str:
    if not _KB_AVAILABLE:
        return (
            "The knowledge base isn't configured yet. "
            "Set `NOTION_TOKEN` in the Railway environment variables, "
            "then redeploy the bot."
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

    try:
        count = reminder_store.count_for_message(user_id, ref_ts)
    except Exception as e:
        logger.error("Could not check reminder count (Supabase error): %s", e)
        say(text="⚠️ Reminders are temporarily unavailable — the database isn't reachable. Please ask an admin to check the `SUPABASE_SERVICE_KEY` in Railway.", thread_ts=event_ts)
        return

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

def _process_mention(event, say, client):
    channel         = event["channel"]
    placeholder_ts  = None
    try:
        bot_uid  = _get_bot_uid(client)
        raw_text = event.get("text", "")
        clean    = re.sub(rf"<@{re.escape(bot_uid)}(?:\|[^>]*)?>", "", raw_text).strip()
        logger.info("app_mention: channel=%s channel_type=%s clean=%r",
                    channel, event.get("channel_type"), clean[:120])

        if _is_remind_request(clean):
            _handle_remind_request(event, say, client)
            return

        if not clean:
            say("Hi! Ask me anything.", thread_ts=event["ts"], reply_broadcast=True)
            return

        # Post a placeholder immediately so the user sees a response right away
        try:
            resp = say(text="⏳ Searching the knowledge base...",
                       thread_ts=event["ts"], reply_broadcast=True)
            placeholder_ts = resp.get("ts")
        except Exception:
            pass

        answer = _qa_answer(channel, clean)

        if placeholder_ts:
            try:
                client.chat_update(channel=channel, ts=placeholder_ts, text=answer)
                return
            except Exception:
                pass
        say(text=answer, thread_ts=event["ts"], reply_broadcast=True)

    except Exception as e:
        logger.error("handle_mention error: %s", e, exc_info=True)
        error_text = "Something went wrong — please try again."
        try:
            if placeholder_ts:
                client.chat_update(channel=channel, ts=placeholder_ts, text=error_text)
            else:
                say(text=error_text, thread_ts=event.get("ts"), reply_broadcast=True)
        except Exception:
            pass


@slack_app.event("app_mention")
def handle_mention(event, say, client):
    _pool.submit(_process_mention, event, say, client)


def _process_dm(event, say, client):
    channel        = event["channel"]
    placeholder_ts = None
    try:
        question = event.get("text", "").strip()
        if not question:
            return

        # Immediate feedback — user sees this within ~1 second while Notion+Claude run
        try:
            resp = say(text="⏳ Searching the knowledge base...")
            placeholder_ts = resp.get("ts")
        except Exception:
            pass

        answer = _qa_answer(channel, question)

        if placeholder_ts:
            try:
                client.chat_update(channel=channel, ts=placeholder_ts, text=answer)
                return
            except Exception:
                pass
        say(text=answer)

    except Exception as e:
        logger.error("handle_dm error: %s", e, exc_info=True)
        error_text = "Something went wrong — please try again."
        try:
            if placeholder_ts:
                client.chat_update(channel=channel, ts=placeholder_ts, text=error_text)
            else:
                say(text=error_text)
        except Exception:
            pass


def _confirmation_blocks(text: str) -> list[dict]:
    """Confirmation message with a dismiss button so users can clean up the thread."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✕ Dismiss"},
                    "action_id": "remind_dismiss",
                    "value": "dismiss",
                }
            ],
        },
    ]


@slack_app.event("message")
def handle_dm(event, say, client):
    subtype      = event.get("subtype")
    bot_id       = event.get("bot_id")
    channel_type = event.get("channel_type")
    logger.info("message event: channel_type=%s subtype=%s bot_id=%s",
                channel_type, subtype, bool(bot_id))

    if bot_id or subtype or channel_type not in ("im", "mpim"):
        return

    _pool.submit(_process_dm, event, say, client)


# ── Reminder action handlers ───────────────────────────────────────────────────

@slack_app.action("remind_preset_30m")
@slack_app.action("remind_preset_1h")
@slack_app.action("remind_preset_4h")
@slack_app.action("remind_preset_tomorrow_9am")
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
        conf_text = (
            f"✅ Got it! I'll remind you on *{_format_dt(remind_at)}*.\n"
            f"_Reminder {num}/{total} for this message._"
        )
        respond(
            replace_original=True,
            text=conf_text,
            blocks=_confirmation_blocks(conf_text),
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

    # count is stored in the button value — no Supabase call needed here,
    # so views_open fires immediately within the 3-second trigger_id window.
    count     = ctx.pop("count", 0)
    remaining = reminder_store.MAX_REMINDERS - count

    # Store the time picker message ts so we can update it on submit
    ctx["picker_ts"] = body.get("message", {}).get("ts", "")
    ctx_str = json.dumps(ctx)

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
                    "label": {"type": "plain_text", "text": "When should I remind you? (UAE time, UTC+4)"},
                },
            ],
        },
    )


@slack_app.view("remind_custom_modal")
def handle_remind_custom_submit(ack, body, client):
    user_input = (
        body["view"]["state"]["values"]["custom_time"]["time_input"]["value"] or ""
    ).strip()

    # Ack immediately — Slack requires a response within 3 seconds.
    # dateparser can be slow, so we ack first and handle errors via chat message.
    ack()

    ctx     = json.loads(body["view"]["private_metadata"])

    parsed = dateparser.parse(
        user_input,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "Asia/Dubai",
            "TO_TIMEZONE": "Asia/Dubai",
        },
    )
    if not parsed:
        client.chat_postMessage(
            channel=ctx["channel_id"],
            text=f"⚠️ Couldn't understand *'{user_input}'*. Try `tomorrow 3pm`, `in 2 hours`, or `next Monday 9am`.",
            thread_ts=ctx.get("thread_ts"),
        )
        return
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

        num      = reminder["reminder_number"]
        total    = reminder_store.MAX_REMINDERS
        conf_text = (
            f"✅ Got it! I'll remind you on *{_format_dt(parsed)}*.\n"
            f"_Reminder {num}/{total} for this message._"
        )
        conf_blocks = _confirmation_blocks(conf_text)

        picker_ts = ctx.get("picker_ts")
        if picker_ts:
            # Update the original time picker message in-place (same as preset buttons)
            try:
                client.chat_update(
                    channel=ctx["channel_id"],
                    ts=picker_ts,
                    text=conf_text,
                    blocks=conf_blocks,
                )
            except Exception as update_err:
                logger.warning("Could not update picker message: %s", update_err)
                client.chat_postMessage(channel=ctx["channel_id"], text=conf_text,
                                        thread_ts=ctx.get("thread_ts"))
        else:
            client.chat_postMessage(channel=ctx["channel_id"], text=conf_text,
                                    thread_ts=ctx.get("thread_ts"))

    except ValueError as e:
        client.chat_postMessage(channel=ctx["channel_id"], text=str(e),
                                thread_ts=ctx.get("thread_ts"))
    except Exception as e:
        logger.error("remind_custom_submit error: %s", e)
        client.chat_postMessage(channel=ctx["channel_id"],
                                text="Something went wrong setting your reminder.",
                                thread_ts=ctx.get("thread_ts"))


@slack_app.action("remind_done")
def handle_remind_done(ack, respond, body):
    ack()
    reminder_id = body["actions"][0]["value"]
    reminder_store.update_status(reminder_id, "done")
    respond(
        replace_original=True,
        text="All done! ✅",
        blocks=_confirmation_blocks("All done! ✅ Reminder marked as complete."),
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


@slack_app.action("remind_dismiss")
def handle_remind_dismiss(ack, body, client):
    ack()
    try:
        channel = body["container"]["channel_id"]
        ts      = body["container"]["message_ts"]
        client.chat_delete(channel=channel, ts=ts)
    except Exception as e:
        logger.warning("Could not dismiss message: %s", e)


# ── startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting UAEOPS Bot — KB available: %s", _KB_AVAILABLE)
    scheduler.start()
    _load_pending_reminders()
    logger.info("Bot ready. Connecting to Slack via Socket Mode...")
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
