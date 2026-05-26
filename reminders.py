"""
Reminder data store — persists to Supabase (survives Railway redeployments).
Uses the Supabase REST API directly via requests; no SDK needed.

Requires env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import os
import uuid
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MAX_REMINDERS = 3
UAE_TZ = timezone(timedelta(hours=4))  # UTC+4, no DST


# ── Supabase REST helpers ─────────────────────────────────────────────────────

def _url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/reminders"


def _headers(*, returning: bool = False) -> dict:
    key = os.environ["SUPABASE_SERVICE_KEY"]
    h = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    if returning:
        h["Prefer"] = "return=representation"
    return h


# ── public API ────────────────────────────────────────────────────────────────

def count_for_message(user_id: str, message_ts: str) -> int:
    resp = requests.get(
        _url(),
        headers={**_headers(), "Prefer": "count=exact"},
        params={"user_id": f"eq.{user_id}", "message_ts": f"eq.{message_ts}", "select": "id"},
        timeout=10,
    )
    resp.raise_for_status()
    # Supabase returns total in Content-Range: 0-N/TOTAL
    cr = resp.headers.get("Content-Range", "0/0")
    try:
        return int(cr.split("/")[-1])
    except (ValueError, IndexError):
        return len(resp.json())


def create(
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
    resp = requests.post(_url(), headers=_headers(returning=True), json=row, timeout=10)
    resp.raise_for_status()
    return resp.json()[0]


def update_status(reminder_id: str, status: str):
    resp = requests.patch(
        _url(),
        headers=_headers(),
        params={"id": f"eq.{reminder_id}"},
        json={"status": status},
        timeout=10,
    )
    resp.raise_for_status()


def get(reminder_id: str) -> Optional[dict]:
    resp = requests.get(
        _url(),
        headers=_headers(),
        params={"id": f"eq.{reminder_id}"},
        timeout=10,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def get_pending() -> list[dict]:
    resp = requests.get(
        _url(),
        headers=_headers(),
        params={"status": "eq.pending"},
        timeout=10,
    )
    if not resp.ok:
        logger.error("Supabase get_pending failed %s: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    return resp.json()
