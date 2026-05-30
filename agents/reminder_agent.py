"""
Reminder Agent — owns everything related to reminders:
  - Supabase CRUD (persists across Railway redeployments)
  - APScheduler (fires DMs at the right time)
  - Block Kit UI (time picker, DM layout, confirmation messages)
  - handle() — called by app.py when intent == "reminder"

Requires env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import json
import os
import uuid
import logging
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

import dateparser
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

MAX_REMINDERS = 3
UAE_TZ = timezone(timedelta(hours=4))
scheduler = BackgroundScheduler(timezone="Asia/Dubai")

# populated lazily by app.py passing the slack_app client reference
_slack_client = None


def init(slack_client) -> None:
    """Called once at startup from app.py to give this agent the Slack client."""
    global _slack_client
    _slack_client = slack_client


# ── Supabase REST helpers ─────────────────────────────────────────────────────

def _db_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/reminders"


def _db_headers(*, returning: bool = False) -> dict:
    key = os.environ["SUPABASE_SERVICE_KEY"]
    h = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    if returning:
        h["Prefer"] = "return=representation"
    return h


# ── Supabase CRUD ─────────────────────────────────────────────────────────────

def count_for_message(user_id: str, message_ts: str) -> int:
    resp = requests.get(
        _db_url(),
        headers={**_db_headers(), "Prefer": "count=exact"},
        params={"user_id": f"eq.{user_id}", "message_ts": f"eq.{message_ts}", "select": "id"},
        timeout=10,
    )
    resp.raise_for_status()
    cr = resp.headers.get("Content-Range", "0/0")
    try:
        return int(cr.split("/")[-1])
    except (ValueError, IndexError):
        return len(resp.json())


def create_reminder(
    *,
    user_id: str,
    channel_id: str,
    message_ts: str,
    thread_ts: str,
    permalink: str,
    message_text: str,
    remind_at: datetime,
) -> dict:
    existing = count_for_message(user_id, message_ts)
    if existing >= MAX_REMINDERS:
        raise ValueError(f"Max {MAX_REMINDERS} reminders per message reached")

    row = {
        "id":              str(uuid.uuid4()),
        "user_id":         user_id,
        "channel_id":      channel_id,
        "message_ts":      message_ts,
        "thread_ts":       thread_ts,
        "permalink":       permalink,
        "message_text":    message_text[:200],
        "remind_at":       remind_at.astimezone(UAE_TZ).isoformat(),
        "created_at":      datetime.now(UAE_TZ).isoformat(),
        "status":          "pending",
        "reminder_number": existing + 1,
    }
    resp = requests.post(_db_url(), headers=_db_headers(returning=True), json=row, timeout=10)
    resp.raise_for_status()
    return resp.json()[0]


def update_status(reminder_id: str, status: str) -> None:
    resp = requests.patch(
        _db_url(),
        headers=_db_headers(),
        params={"id": f"eq.{reminder_id}"},
        json={"status": status},
        timeout=10,
    )
    resp.raise_for_status()


def get_reminder(reminder_id: str) -> Optional[dict]:
    resp = requests.get(
        _db_url(),
        headers=_db_headers(),
        params={"id": f"eq.{reminder_id}"},
        timeout=10,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def get_pending() -> list[dict]:
    resp = requests.get(
        _db_url(),
        headers=_db_headers(),
        params={"status": "eq.pending"},
        timeout=10,
    )
    if not resp.ok:
        logger.error("Supabase get_pending failed %s: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    return resp.json()


# ── Time helpers ──────────────────────────────────────────────────────────────

def preset_to_dt(preset: str) -> datetime:
    now_uae = datetime.now(UAE_TZ)
    presets = {
        "30m":          now_uae + timedelta(minutes=30),
        "1h":           now_uae + timedelta(hours=1),
        "4h":           now_uae + timedelta(hours=4),
        "tomorrow_9am": (now_uae + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0),
    }
    return presets[preset]


def format_dt(dt: datetime) -> str:
    return dt.astimezone(UAE_TZ).strftime("%a %d %b %Y at %H:%M UAE")


# ── Block Kit builders ────────────────────────────────────────────────────────

def time_picker_blocks(ctx: dict, count: int) -> list[dict]:
    remaining = MAX_REMINDERS - count

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
                    f"_Reminder {count + 1}/{MAX_REMINDERS} "
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


def reminder_dm_blocks(reminder: dict) -> list[dict]:
    num   = reminder["reminder_number"]
    total = MAX_REMINDERS
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


def confirmation_blocks(text: str) -> list[dict]:
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


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _send_reminder_dm(reminder_id: str) -> None:
    reminder = get_reminder(reminder_id)
    if not reminder or reminder["status"] != "pending":
        return
    update_status(reminder_id, "sent")
    try:
        _slack_client.chat_postMessage(
            channel=reminder["user_id"],
            text=f"⏰ Reminder: {reminder['message_text'][:80]}",
            blocks=reminder_dm_blocks(reminder),
        )
    except Exception as e:
        logger.error("Failed to send reminder DM %s: %s", reminder_id, e)


def schedule(reminder: dict) -> None:
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


def load_pending_reminders() -> None:
    """Called once at startup to reschedule pending reminders from Supabase."""
    try:
        pending = get_pending()
        logger.info("Reloading %d pending reminder(s) from Supabase", len(pending))
        for r in pending:
            schedule(r)
    except Exception as e:
        logger.error("Could not load pending reminders — bot will still start: %s", e)


# ── Main handler (called by app.py) ──────────────────────────────────────────

def handle(event: dict, say, client) -> None:
    """Entry point — called when router classifies intent as 'reminder'."""
    user_id   = event["user"]
    channel   = event["channel"]
    event_ts  = event["ts"]
    thread_ts = event.get("thread_ts", event_ts)
    ref_ts    = thread_ts

    ref_text = ""
    try:
        resp = client.conversations_history(channel=channel, latest=ref_ts, limit=1, inclusive=True)
        msgs = resp.get("messages", [])
        if msgs:
            raw = msgs[0].get("text", "")
            ref_text = re.sub(r"<@\w+>", "", raw).strip()
    except Exception as e:
        logger.warning("Could not fetch ref message: %s", e)

    permalink = ""
    try:
        plink = client.chat_getPermalink(channel=channel, message_ts=ref_ts)
        permalink = plink.get("permalink", "")
    except Exception as e:
        logger.warning("Could not get permalink: %s", e)

    try:
        count = count_for_message(user_id, ref_ts)
    except Exception as e:
        logger.error("Could not check reminder count (Supabase error): %s", e)
        say(
            text="⚠️ Reminders are temporarily unavailable — the database isn't reachable. Please ask an admin to check the `SUPABASE_SERVICE_KEY` in Railway.",
            thread_ts=event_ts,
        )
        return

    if count >= MAX_REMINDERS:
        say(
            text=f"You've already set the maximum of {MAX_REMINDERS} reminders for this message.",
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
        blocks=time_picker_blocks(ctx, count),
        thread_ts=event_ts,
    )


# ── Custom time modal submit helper (called by app.py action handler) ─────────

def handle_custom_time_submit(user_input: str, ctx: dict, user_id: str, client) -> None:
    """
    Parse the user's custom time string, create reminder, update Slack message.
    Called from the view submission handler in app.py after ack().
    """
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

    try:
        reminder = create_reminder(
            user_id=user_id,
            channel_id=ctx["channel_id"],
            message_ts=ctx["message_ts"],
            thread_ts=ctx["thread_ts"],
            permalink=ctx["permalink"],
            message_text=ctx["message_text"],
            remind_at=parsed,
        )
        schedule(reminder)

        num       = reminder["reminder_number"]
        total     = MAX_REMINDERS
        conf_text = (
            f"✅ Got it! I'll remind you on *{format_dt(parsed)}*.\n"
            f"_Reminder {num}/{total} for this message._"
        )
        conf_blocks = confirmation_blocks(conf_text)
        picker_ts   = ctx.get("picker_ts")

        if picker_ts:
            try:
                client.chat_update(
                    channel=ctx["channel_id"],
                    ts=picker_ts,
                    text=conf_text,
                    blocks=conf_blocks,
                )
            except Exception as update_err:
                logger.warning("Could not update picker message: %s", update_err)
                client.chat_postMessage(
                    channel=ctx["channel_id"],
                    text=conf_text,
                    thread_ts=ctx.get("thread_ts"),
                )
        else:
            client.chat_postMessage(
                channel=ctx["channel_id"],
                text=conf_text,
                thread_ts=ctx.get("thread_ts"),
            )

    except ValueError as e:
        client.chat_postMessage(
            channel=ctx["channel_id"],
            text=str(e),
            thread_ts=ctx.get("thread_ts"),
        )
    except Exception as e:
        logger.error("handle_custom_time_submit error: %s", e)
        client.chat_postMessage(
            channel=ctx["channel_id"],
            text="Something went wrong setting your reminder.",
            thread_ts=ctx.get("thread_ts"),
        )
