import os
import logging
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

@slack_app.event("app_mention")
def handle_mention(event, say, client):
    try:
        bot_uid  = _get_bot_uid(client)
        raw_text = event.get("text", "")
        clean    = raw_text.replace(f"<@{bot_uid}>", "").strip()
        channel  = event["channel"]
        ts       = event["ts"]

        if not clean:
            say("Hi! Ask me anything.", thread_ts=ts)
            return

        intent = route(clean)

        if intent == "reminder":
            reminder_agent.handle(event, say, client)
            return

        _react(client, channel, ts, "thinking_face")
        try:
            if intent == "alert":
                reply = alert_agent.handle(channel, clean)
            else:
                history = conversation.get(channel)
                reply, history = qa_agent.handle(channel, clean, history)
                conversation.update(channel, history)
            say(text=reply, thread_ts=ts)
        finally:
            _unreact(client, channel, ts, "thinking_face")

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
        intent  = route(question)

        _react(client, channel, event["ts"], "thinking_face")
        try:
            if intent == "alert":
                reply = alert_agent.handle(channel, question)
            else:
                history = conversation.get(channel)
                reply, history = qa_agent.handle(channel, question, history)
                conversation.update(channel, history)
            say(text=reply)
        finally:
            _unreact(client, channel, event["ts"], "thinking_face")

    except Exception as e:
        logger.error("handle_dm error: %s", e, exc_info=True)
        try:
            say(text="Something went wrong — please try again.")
        except Exception:
            pass


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
    logger.info("UAEOPS Bot v2 starting — agents: reminder | qa | alert | router active")
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
