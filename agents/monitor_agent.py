"""
Monitor Agent — watches Slack channels for alerts and forwards them to #uaeops-alerts.
Merged from the standalone Alert-monitor-uae repo.

Responsibilities:
- Dedup via Supabase monitor_state table (replaces state.json)
- Startup lookback: catches messages missed during restarts (30 min window)
- Artwork alert extraction: parses addy bot Block Kit messages
- Posts formatted alerts to POST_CHANNEL_ID (#uaeops-alerts)

Channels watched (set in Railway env var WATCH_CHANNEL_IDS as comma-separated list,
or falls back to the defaults below):
  C0AC62K0LCB  #tm-alerts            (only when @Arif is tagged)
  C06HXRQTSS3  #integrations-alert
  CHZCNQ8RK    #uae_operations
  C07RFK6QYSE  #uae-ops-alerts
  C06CSPJAMT9  #uaeops-customersupport
  C0ADLS9J2NB  #payments_news

Requires env vars: SLACK_BOT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY
Optional env vars:  WATCH_CHANNEL_IDS, POST_CHANNEL_ID, ALERT_BOT_ID, ARIF_USER_ID
"""
import os
import re
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ── Config (override via env vars) ────────────────────────────────────────────

_DEFAULT_WATCH_CHANNELS = [
    "C0AC62K0LCB",  # #tm-alerts
    "C06HXRQTSS3",  # #integrations-alert
    "CHZCNQ8RK",    # #uae_operations
    "C07RFK6QYSE",  # #uae-ops-alerts
    "C06CSPJAMT9",  # #uaeops-customersupport
    "C0ADLS9J2NB",  # #payments_news
]

WATCH_CHANNEL_IDS = (
    os.environ.get("WATCH_CHANNEL_IDS", "").split(",")
    if os.environ.get("WATCH_CHANNEL_IDS")
    else _DEFAULT_WATCH_CHANNELS
)

POST_CHANNEL_ID       = os.environ.get("POST_CHANNEL_ID",  "C0B5ML7HVDF")  # #uaeops-alerts
ARIF_USER_ID          = os.environ.get("ARIF_USER_ID",     "UJ0HP9ZQD")
WORKSPACE             = os.environ.get("SLACK_WORKSPACE",  "platinumlist")
STARTUP_LOOKBACK_MINS = 30

NON_CONTENT_SUBTYPES = {
    "channel_join", "channel_leave", "channel_archive", "channel_unarchive",
    "channel_name", "channel_purpose", "channel_topic",
    "pinned_item", "unpinned_item", "file_share",
    "message_changed", "message_deleted",
}

# ── Supabase state store (replaces state.json) ────────────────────────────────

def _sb_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/monitor_state"


def _sb_headers() -> dict:
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }


def _is_processed(ts: str, channel_id: str) -> bool:
    try:
        resp = requests.get(
            _sb_url(),
            headers=_sb_headers(),
            params={"ts": f"eq.{ts}", "channel_id": f"eq.{channel_id}", "select": "ts"},
            timeout=5,
        )
        resp.raise_for_status()
        return len(resp.json()) > 0
    except Exception as e:
        logger.warning("monitor_state check failed: %s", e)
        return False


def _mark_processed(ts: str, channel_id: str) -> None:
    try:
        requests.post(
            _sb_url(),
            headers={**_sb_headers(), "Prefer": "return=minimal,resolution=ignore-duplicates"},
            json={"ts": ts, "channel_id": channel_id},
            timeout=5,
        ).raise_for_status()
    except Exception as e:
        logger.warning("monitor_state insert failed: %s", e)


def _prune_old_state() -> None:
    """Delete rows older than 30 days — matches original state.json pruning logic."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        requests.delete(
            _sb_url(),
            headers=_sb_headers(),
            params={"created_at": f"lt.{cutoff}"},
            timeout=5,
        ).raise_for_status()
    except Exception as e:
        logger.warning("monitor_state prune failed: %s", e)


# ── Slack helper — rate-limit retry ──────────────────────────────────────────

def _slack_call(fn, *args, **kwargs):
    from slack_sdk.errors import SlackApiError
    for attempt in range(5):
        try:
            return fn(*args, **kwargs)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                wait = int(e.response.headers.get("Retry-After", 10)) + 1
                logger.info("Rate limited — waiting %ds...", wait)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Slack API rate limit exceeded after 5 retries")


# ── Artwork alert field extraction ────────────────────────────────────────────

def _extract_fields(msg: dict) -> dict:
    """Parse addy bot Block Kit artwork alert into structured fields."""
    event_name = event_id = event_link = ai_analysis = ""

    for block in msg.get("blocks", []):
        if block.get("type") != "section":
            continue
        text = block.get("text", {}).get("text", "")

        if not event_link:
            m = re.search(r"\*<([^|>]+)\|([^>]+)>\*", text)
            if m:
                event_link = m.group(1).strip()
                event_name = m.group(2).strip()

        if not event_id:
            m = re.search(r"Event ID:\s*`?(\d+)`?", text)
            if m:
                event_id = m.group(1).strip()

        if not ai_analysis and ("AI Analysis" in text or ":robot_face:" in text):
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            for i, ln in enumerate(lines):
                if "AI Analysis" in ln and i + 1 < len(lines):
                    ai_analysis = lines[i + 1]
                    break

    if not event_name:
        m = re.match(r"Error in (.+?) Images?$", msg.get("text", "").strip(), re.IGNORECASE)
        if m:
            event_name = m.group(1).strip().replace("&amp;", "&")

    if not event_id and event_link:
        m = re.search(r"/event-tickets/(\d+)/", event_link)
        if m:
            event_id = m.group(1)

    return {
        "event_name":  event_name  or "Unknown Event",
        "event_id":    event_id    or "—",
        "event_link":  event_link  or "—",
        "ai_analysis": ai_analysis,
    }


# ── Message filtering ─────────────────────────────────────────────────────────

def _is_relevant(msg: dict, channel_id: str) -> bool:
    """#tm-alerts: only act when Arif is tagged. All other channels: always act."""
    if channel_id == "C0AC62K0LCB":
        return f"<@{ARIF_USER_ID}>" in msg.get("text", "")
    return True


def _thread_link(channel_id: str, ts: str) -> str:
    return f"https://{WORKSPACE}.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"


# ── Alert formatter + poster ──────────────────────────────────────────────────

def _post_alert(slack_client, msg: dict, channel_id: str) -> None:
    original_link = _thread_link(channel_id, msg["ts"])
    raw_text      = msg.get("text", "").strip()
    fields        = _extract_fields(msg)
    has_structured = fields["event_link"] != "—"

    if has_structured:
        name     = fields["event_name"]
        eid      = fields["event_id"]
        link     = fields["event_link"]
        analysis = fields["ai_analysis"]

        lines = [
            f":rotating_light: *Artwork Alert — {name}*", "",
            "Dear OPS Team,", "",
            "An artwork image mismatch has been identified for the event listed below. "
            "Please review the issue and coordinate with the relevant team to have it "
            "resolved as soon as possible. Once the fix has been applied, kindly reply "
            "to the original alert thread to confirm completion.",
            "", "*Event Details*",
            f"• *Event Name:*  {name}",
            f"• *Event ID:*      {eid}",
            f"• *Event Link:*   {link}",
        ]
        if analysis:
            lines += ["", f"*Issue Detected:*  {analysis}"]
        lines += ["", f"*Original Alert Thread:*  {original_link}", "", "_Sent using @Claude_"]
        logger.info("Artwork alert → %s (ID: %s)", name, eid)

    else:
        lines = [
            ":rotating_light: *New Alert*", "",
            "Dear OPS Team,", "",
            "A new alert has been detected in one of the monitored channels. "
            "Please review and take the appropriate action. Once resolved, kindly "
            "reply to the original alert thread to confirm completion.",
            "",
        ]
        if raw_text:
            lines += [f"*Alert:*  {raw_text}", ""]
        lines += [f"*Original Alert Thread:*  {original_link}", "", "_Sent using @Claude_"]
        logger.info("General alert → %s", raw_text[:60] or "(no text)")

    _slack_call(
        slack_client.chat_postMessage,
        channel=POST_CHANNEL_ID,
        text="\n".join(lines),
    )


# ── Core message processor ────────────────────────────────────────────────────

def process_message(slack_client, msg: dict, channel_id: str) -> None:
    """
    Process one Slack message. Dedup-checked against Supabase.
    Called from app.py's message handler and startup_lookback().
    """
    ts = msg.get("ts")
    if not ts:
        return

    # Skip thread replies
    if msg.get("thread_ts") and msg["thread_ts"] != ts:
        return

    if msg.get("subtype") in NON_CONTENT_SUBTYPES:
        return

    if _is_processed(ts, channel_id):
        return

    _mark_processed(ts, channel_id)

    logger.info("Monitor: new message [%s] %r", channel_id, msg.get("text", "")[:80])

    if _is_relevant(msg, channel_id):
        try:
            _post_alert(slack_client, msg, channel_id)
        except Exception as e:
            logger.error("Could not post alert: %s", e)
    else:
        logger.debug("Monitor: skipped (Arif not tagged in #tm-alerts)")


# ── Startup lookback ──────────────────────────────────────────────────────────

def startup_lookback(slack_client) -> None:
    """
    Called once at startup. Fetches the last 30 minutes of messages from all
    watched channels to catch anything missed while the bot was redeploying.
    """
    logger.info("Monitor: startup lookback (%d min)...", STARTUP_LOOKBACK_MINS)
    _prune_old_state()
    oldest_ts = str(
        (datetime.now(timezone.utc) - timedelta(minutes=STARTUP_LOOKBACK_MINS)).timestamp()
    )

    for channel_id in WATCH_CHANNEL_IDS:
        try:
            resp = _slack_call(
                slack_client.conversations_history,
                channel=channel_id,
                oldest=oldest_ts,
                limit=50,
            )
            for msg in resp.get("messages", []):
                process_message(slack_client, msg, channel_id)
        except Exception as e:
            logger.warning("Monitor: could not read channel %s: %s", channel_id, e)

    logger.info("Monitor: lookback complete")
