import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from router import route
import conversation
import agents.reminder_agent as reminder_agent
import agents.qa_agent as qa_agent
import agents.alert_agent as alert_agent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

slack_app = App(token=os.environ["SLACK_BOT_TOKEN"])
_pool     = ThreadPoolExecutor(max_workers=8)

_bot_uid: Optional[str] = None


def _get_bot_uid(client) -> str:
    global _bot_uid
    if not _bot_uid:
        _bot_uid = client.auth_test()["user_id"]
    return _bot_uid


def _react(client, channel: str, ts: str, emoji: str) -> None:
    try:
        client.reactions_add(channel=channel, name=emoji, timestamp=ts)
    except Exception:
        pass


def _unreact(client, channel: str, ts: str, emoji: str) -> None:
    try:
        client.reactions_remove(channel=channel, name=emoji, timestamp=ts)
    except Exception:
        pass


# ── Slack event handlers ───────────────────────────────────────────────────────

def _process_mention(event, say, client, placeholder_ts):
    channel = event["channel"]
    try:
        bot_uid  = _get_bot_uid(client)
        raw_text = event.get("text", "")
        clean    = raw_text.replace(f"<@{bot_uid}>", "").strip()
        ts       = event["ts"]

        if not clean:
            if placeholder_ts:
                try:
                    client.chat_update(channel=channel, ts=placeholder_ts, text="Hi! Ask me anything.")
                    return
                except Exception:
                    pass
            say("Hi! Ask me anything.", thread_ts=ts)
            return

        intent = route(clean)

        if intent == "reminder":
            if placeholder_ts:
                try:
                    client.chat_delete(channel=channel, ts=placeholder_ts)
                except Exception:
                    pass
            reminder_agent.handle(event, say, client)
            return

        if intent == "alert":
            reply = alert_agent.handle(channel, clean)
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": reply}}]
            feedback_id = None
        else:
            history = conversation.get(channel)
            reply, history, feedback_id = qa_agent.handle(channel, clean, history)
            conversation.update(channel, history)
            blocks = qa_agent.answer_blocks(reply, feedback_id)

        if placeholder_ts:
            try:
                client.chat_update(channel=channel, ts=placeholder_ts, text=reply, blocks=blocks)
                return
            except Exception:
                pass
        say(text=reply, blocks=blocks, thread_ts=ts)

    except Exception as e:
        logger.error("handle_mention error: %s", e, exc_info=True)
        try:
            msg = "Something went wrong — please try again."
            if placeholder_ts:
                client.chat_update(channel=channel, ts=placeholder_ts, text=msg)
            else:
                say(text=msg, thread_ts=event.get("ts"))
        except Exception:
            pass


@slack_app.event("app_mention")
def handle_mention(event, say, client):
    placeholder_ts = None
    try:
        placeholder_ts = say(text="⏳ Searching...", thread_ts=event["ts"]).get("ts")
    except Exception:
        pass
    _pool.submit(_process_mention, event, say, client, placeholder_ts)


def _process_dm(event, say, client, placeholder_ts):
    channel = event["channel"]
    try:
        question = event.get("text", "").strip()
        if not question:
            return

        intent = route(question)

        if intent == "alert":
            reply = alert_agent.handle(channel, question)
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": reply}}]
        else:
            history = conversation.get(channel)
            reply, history, feedback_id = qa_agent.handle(channel, question, history)
            conversation.update(channel, history)
            blocks = qa_agent.answer_blocks(reply, feedback_id)

        if placeholder_ts:
            try:
                client.chat_update(channel=channel, ts=placeholder_ts, text=reply, blocks=blocks)
                return
            except Exception:
                pass
        say(text=reply, blocks=blocks)

    except Exception as e:
        logger.error("handle_dm error: %s", e, exc_info=True)
        try:
            msg = "Something went wrong — please try again."
            if placeholder_ts:
                client.chat_update(channel=channel, ts=placeholder_ts, text=msg)
            else:
                say(text=msg)
        except Exception:
            pass


@slack_app.event("message")
def handle_dm(event, say, client):
    if event.get("bot_id") or event.get("subtype") or event.get("channel_type") not in ("im", "mpim"):
        return
    placeholder_ts = None
    try:
        placeholder_ts = say(text="⏳ Searching...").get("ts")
    except Exception:
        pass
    _pool.submit(_process_dm, event, say, client, placeholder_ts)


# ── Feedback action handlers ───────────────────────────────────────────────────

@slack_app.action("feedback_positive")
@slack_app.action("feedback_negative")
def handle_feedback(ack, body, respond):
    ack()
    try:
        from agents import feedback_store
        action    = body["actions"][0]
        rating    = "positive" if action["action_id"] == "feedback_positive" else "negative"
        feedback_id = action["value"]
        user_id   = body["user"]["id"]
        feedback_store.rate(feedback_id, user_id, rating)
        icon = "👍" if rating == "positive" else "👎"
        respond(
            replace_original=False,
            text=f"{icon} Thanks for the feedback!",
            response_type="ephemeral",
        )
    except Exception as e:
        logger.warning("Feedback action failed: %s", e)


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
        ctx["user_id"] = user_id

        remind_at = reminder_agent.preset_to_dt(preset)
        reminder  = reminder_agent.create_reminder(
            user_id=user_id,
            channel_id=ctx["channel_id"],
            message_ts=ctx["message_ts"],
            thread_ts=ctx["thread_ts"],
            permalink=ctx["permalink"],
            message_text=ctx["message_text"],
            remind_at=remind_at,
        )
        reminder_agent.schedule(reminder)

        num       = reminder["reminder_number"]
        total     = reminder_agent.MAX_REMINDERS
        conf_text = (
            f"✅ Got it! I'll remind you on *{reminder_agent.format_dt(remind_at)}*.\n"
            f"_Reminder {num}/{total} for this message._"
        )
        respond(
            replace_original=True,
            text=conf_text,
            blocks=reminder_agent.confirmation_blocks(conf_text),
        )
    except ValueError as e:
        respond(replace_original=False, text=str(e))
    except Exception as e:
        logger.error("remind_preset error: %s", e)
        respond(replace_original=False, text="Something went wrong setting your reminder.")


@slack_app.action("remind_custom_open")
def handle_remind_custom_open(ack, body, client):
    ack()
    ctx   = json.loads(body["actions"][0]["value"])
    count = ctx.pop("count", 0)
    remaining = reminder_agent.MAX_REMINDERS - count
    ctx["picker_ts"] = body.get("message", {}).get("ts", "")

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type":             "modal",
            "callback_id":      "remind_custom_modal",
            "private_metadata": json.dumps(ctx),
            "title":  {"type": "plain_text", "text": "Set a reminder"},
            "submit": {"type": "plain_text", "text": "Set reminder"},
            "close":  {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"_Reminder {count + 1}/{reminder_agent.MAX_REMINDERS} — {remaining} remaining._",
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
    ack()
    ctx     = json.loads(body["view"]["private_metadata"])
    user_id = body["user"]["id"]
    reminder_agent.handle_custom_time_submit(user_input, ctx, user_id, client)


@slack_app.action("remind_done")
def handle_remind_done(ack, respond, body):
    ack()
    reminder_id = body["actions"][0]["value"]
    reminder_agent.update_status(reminder_id, "done")
    respond(
        replace_original=True,
        text="All done! ✅",
        blocks=reminder_agent.confirmation_blocks("All done! ✅ Reminder marked as complete."),
    )


@slack_app.action("remind_again")
def handle_remind_again(ack, respond, body, client):
    ack()
    reminder_id = body["actions"][0]["value"]
    original    = reminder_agent.get_reminder(reminder_id)
    if not original:
        respond(replace_original=False, text="Reminder not found.")
        return

    user_id = body["user"]["id"]
    count   = reminder_agent.count_for_message(user_id, original["message_ts"])

    if count >= reminder_agent.MAX_REMINDERS:
        respond(
            replace_original=True,
            text=f"You've reached the maximum of {reminder_agent.MAX_REMINDERS} reminders for this message.",
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚠️ You've used all {reminder_agent.MAX_REMINDERS} reminders for this message.",
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
    respond(
        replace_original=True,
        text="⏰ When should I remind you again?",
        blocks=reminder_agent.time_picker_blocks(ctx, count),
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
    reminder_agent.init(slack_app.client)
    reminder_agent.scheduler.start()
    reminder_agent.load_pending_reminders()

    # Start Notion → vector store background sync if Voyage AI is configured
    if os.environ.get("VOYAGE_API_KEY") and os.environ.get("NOTION_TOKEN"):
        try:
            from agents import sync_notion
            _pool.submit(sync_notion.sync_all)
            reminder_agent.scheduler.add_job(
                sync_notion.sync_all,
                trigger="interval",
                hours=6,
                id="notion_sync",
                replace_existing=True,
            )
            logger.info("Notion → vector store sync scheduled (startup + every 6h)")
        except Exception as e:
            logger.warning("Could not schedule Notion sync: %s", e)

    logger.info("UAEOPS Bot v2 — agents: reminder | qa (semantic) | alert | router")
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
