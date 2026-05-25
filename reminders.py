"""
Reminder data store — persists to reminders.json.
Thread-safe via a single module-level lock.
"""
import json
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REMINDERS_FILE = Path("reminders.json")
MAX_REMINDERS = 3

_lock = threading.Lock()


# ── internal I/O (caller must hold _lock) ─────────────────────────────────────

def _load() -> list[dict]:
    if not REMINDERS_FILE.exists():
        return []
    return json.loads(REMINDERS_FILE.read_text())


def _save(data: list[dict]):
    REMINDERS_FILE.write_text(json.dumps(data, indent=2, default=str))


# ── public API ────────────────────────────────────────────────────────────────

def count_for_message(user_id: str, message_ts: str) -> int:
    with _lock:
        return sum(
            1 for r in _load()
            if r["user_id"] == user_id and r["message_ts"] == message_ts
        )


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
    with _lock:
        data = _load()
        existing = sum(
            1 for r in data
            if r["user_id"] == user_id and r["message_ts"] == message_ts
        )
        if existing >= MAX_REMINDERS:
            raise ValueError(f"Max {MAX_REMINDERS} reminders per message reached")

        reminder = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "channel_id": channel_id,
            "message_ts": message_ts,
            "thread_ts": thread_ts,
            "permalink": permalink,
            "message_text": message_text[:200],
            "remind_at": remind_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "reminder_number": existing + 1,
        }
        data.append(reminder)
        _save(data)
        return reminder


def update_status(reminder_id: str, status: str):
    with _lock:
        data = _load()
        for r in data:
            if r["id"] == reminder_id:
                r["status"] = status
                break
        _save(data)


def get(reminder_id: str) -> Optional[dict]:
    with _lock:
        return next((r for r in _load() if r["id"] == reminder_id), None)


def get_pending() -> list[dict]:
    with _lock:
        return [r for r in _load() if r["status"] == "pending"]
