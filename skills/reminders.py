"""
Reminder skill — handles all reminder-related Slack interactions.

Registered handlers:
  @app.action  remind_preset_{30m,1h,4h,tomorrow_9am}
  @app.action  remind_custom_open
  @app.action  remind_done
  @app.action  remind_again
  @app.action  remind_dismiss
  @app.view    remind_custom_modal
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta

import dateparser
from apscheduler.triggers.date import DateTrigger

import reminders as reminder_store

logger  = logging.getLogger(__name__)
UAE_TZ  = timezone(timedelta(hours=4))

# Set by register() so _send_reminder_dm can call slack without being passed the client
_app = None


# ── helpers ───────────────────────────────────────────────────────────────────

def is_remind_request(text: str) -> bool:
    return bool(re.search(r"remind\s+me|set\s+a?\s+reminder", text, re.IGNORECASE))


def _preset_to_dt(preset: str) -> datetime:
    now = datetime.now(UAE_TZ)
    return {
        "30m":          now + timedelta(minutes=30),
        "1h":           now + timedelta(hours=1),
        "4h":           now + timedelta(hours=4),
        "tomorrow_9am": (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0),
    }[preset]


def _format_dt(dt: datetime) -> str:
    return dt.astimezone(UAE_TZ).strftime("%a %d %b %Y at %H:%M UAE")


# ── Block Kit builders ────────────────────────────────────────────────────────

def _time_picker_blocks(ctx: dict, count: int) -> list[dict]:
    remaining = reminder_store.MAX_REMINDERS - count

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
                {"type": "mrkdwn", "text": f"_This was your final reminder ({total}/{total}) for this message._"}
            ],
        })

    return blocks


def _confirmation_blocks(text: str) -> list[dict]:
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


# ── scheduler ─────────────────────────────────────────────────────────────────

def _send_reminder_dm(reminder_id: str):
    reminder = reminder_store.get(reminder_id)
    if not reminder or reminder["status"] != "pending":
        return
    reminder_store.update_status(reminder_id, "sent")
    try:
        _app.client.chat_postMessage(
            channel=reminder["user_id"],
            text=f"⏰ Reminder: {reminder['message_text'][:80]}",
            blocks=_reminder_dm_blocks(reminder),
        )
    except Exception as e:
        logger.error("Failed to send reminder DM %s: %s", reminder_id, e)


def _schedule(reminder: dict, scheduler):
    run_at = datetime.fromisoformat(reminder["remind_at"])
    if run_at <= datetime.now(timezone.utc):
        _send_reminder_dm(reminder["id"])
        return
    scheduler.add_job(
        _send_reminder_dm,
        trigger=DateTrigger(run_date=run_at),
        id=reminder["id"],
        args=[reminder["id"]],
        replace_existing=True,
    )


def load_pending(scheduler):
    """On startup, reschedule any pending reminders from Supabase."""
    try:
        pending = reminder_store.get_pending()
        logger.info("Reloading %d pending reminder(s) from database", len(pending))
        for r in pending:
            _schedule(r, scheduler)
    except Exception as e:
        logger.error("Could not load pending reminders — bot still starts: %s", e)


# ── public entry-point for mentions ──────────────────────────────────────────

def handle_remind_request(event, say, client, scheduler):
    user_id   = event["user"]
    channel   = event["channel"]
    event_ts  = event["ts"]
    thread_ts = event.get("thread_ts", event_ts)
    ref_ts    = thread_ts

    ref_text = ""
    try:
        msgs = client.conversations_history(channel=channel, latest=ref_ts, limit=1, inclusive=True).get("messages", [])
        if msgs:
            ref_text = re.sub(r"<@\w+>", "", msgs[0].get("text", "")).strip()
    except Exception as e:
        logger.warning("Could not fetch ref message: %s", e)

    permalink = ""
    try:
        permalink = client.chat_getPermalink(channel=channel, message_ts=ref_ts).get("permalink", "")
    except Exception as e:
        logger.warning("Could not get permalink: %s", e)

    try:
        count = reminder_store.count_for_message(user_id, ref_ts)
    except Exception as e:
        logger.error("Could not check reminder count: %s", e)
        say(
            text="⚠️ Reminders are temporarily unavailable — the database isn't reachable.",
            thread_ts=event_ts,
        )
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


# ── register ──────────────────────────────────────────────────────────────────

def register(app, scheduler):
    global _app
    _app = app

    @app.action("remind_preset_30m")
    @app.action("remind_preset_1h")
    @app.action("remind_preset_4h")
    @app.action("remind_preset_tomorrow_9am")
    def handle_remind_preset(ack, body, respond, client):
        ack()
        try:
            payload  = json.loads(body["actions"][0]["value"])
            preset   = payload["preset"]
            user_id  = body["user"]["id"]
            ctx = {k: payload[k] for k in ("user_id", "channel_id", "message_ts", "thread_ts", "permalink", "message_text")}
            ctx["user_id"] = user_id

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
            _schedule(reminder, scheduler)

            num       = reminder["reminder_number"]
            total     = reminder_store.MAX_REMINDERS
            conf_text = (
                f"✅ Got it! I'll remind you on *{_format_dt(remind_at)}*.\n"
                f"_Reminder {num}/{total} for this message._"
            )
            respond(replace_original=True, text=conf_text, blocks=_confirmation_blocks(conf_text))
        except ValueError as e:
            respond(replace_original=False, text=str(e))
        except Exception as e:
            logger.error("remind_preset error: %s", e)
            respond(replace_original=False, text="Something went wrong setting your reminder.")

    @app.action("remind_custom_open")
    def handle_remind_custom_open(ack, body, client):
        ack()
        ctx   = json.loads(body["actions"][0]["value"])
        count = ctx.pop("count", 0)
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
                            "text": f"_Reminder {count + 1}/{reminder_store.MAX_REMINDERS} — {reminder_store.MAX_REMINDERS - count} remaining._",
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

    @app.view("remind_custom_modal")
    def handle_remind_custom_submit(ack, body, client):
        user_input = (
            body["view"]["state"]["values"]["custom_time"]["time_input"]["value"] or ""
        ).strip()
        ack()

        ctx    = json.loads(body["view"]["private_metadata"])
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
            _schedule(reminder, scheduler)

            num       = reminder["reminder_number"]
            total     = reminder_store.MAX_REMINDERS
            conf_text = (
                f"✅ Got it! I'll remind you on *{_format_dt(parsed)}*.\n"
                f"_Reminder {num}/{total} for this message._"
            )
            conf_blocks = _confirmation_blocks(conf_text)

            picker_ts = ctx.get("picker_ts")
            if picker_ts:
                try:
                    client.chat_update(
                        channel=ctx["channel_id"],
                        ts=picker_ts,
                        text=conf_text,
                        blocks=conf_blocks,
                    )
                    return
                except Exception as e:
                    logger.warning("Could not update picker message: %s", e)

            client.chat_postMessage(
                channel=ctx["channel_id"],
                text=conf_text,
                thread_ts=ctx.get("thread_ts"),
            )
        except ValueError as e:
            client.chat_postMessage(channel=ctx["channel_id"], text=str(e), thread_ts=ctx.get("thread_ts"))
        except Exception as e:
            logger.error("remind_custom_submit error: %s", e)
            client.chat_postMessage(
                channel=ctx["channel_id"],
                text="Something went wrong setting your reminder.",
                thread_ts=ctx.get("thread_ts"),
            )

    @app.action("remind_done")
    def handle_remind_done(ack, respond, body):
        ack()
        reminder_store.update_status(body["actions"][0]["value"], "done")
        respond(
            replace_original=True,
            text="All done! ✅",
            blocks=_confirmation_blocks("All done! ✅ Reminder marked as complete."),
        )

    @app.action("remind_again")
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
        respond(
            replace_original=True,
            text="⏰ When should I remind you again?",
            blocks=_time_picker_blocks(ctx, count),
        )

    @app.action("remind_dismiss")
    def handle_remind_dismiss(ack, body, client):
        ack()
        try:
            client.chat_delete(
                channel=body["container"]["channel_id"],
                ts=body["container"]["message_ts"],
            )
        except Exception as e:
            logger.warning("Could not dismiss message: %s", e)
