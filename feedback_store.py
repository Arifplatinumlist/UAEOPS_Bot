"""
Feedback store — records every Q&A interaction in Supabase so the bot can
learn from user ratings over time.

Flow:
  1. Bot answers a question → create() stores the Q&A, returns an ID
  2. User clicks 👍/👎 → rate() records the rating against that ID
  3. Next Q&A call → get_relevant() surfaces past positively-rated answers
     as extra context for Claude, improving future responses

Requires env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


def _url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/feedback"


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


def create(question: str, answer: str, channel_id: str, user_id: str = "") -> Optional[str]:
    """Store a Q&A pair awaiting a rating. Returns the row ID (or None on error)."""
    try:
        resp = requests.post(
            _url(),
            headers=_headers(returning=True),
            json={
                "question":   question[:2000],
                "answer":     answer[:5000],
                "channel_id": channel_id,
                "user_id":    user_id,
            },
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()[0]["id"]
    except Exception as e:
        logger.warning("feedback.create failed: %s", e)
        return None


def rate(feedback_id: str, user_id: str, rating: str) -> None:
    """Record a user rating ('positive' or 'negative') for a stored Q&A pair."""
    try:
        requests.patch(
            _url(),
            headers=_headers(),
            params={"id": f"eq.{feedback_id}"},
            json={"rating": rating, "user_id": user_id},
            timeout=5,
        ).raise_for_status()
    except Exception as e:
        logger.warning("feedback.rate failed: %s", e)


def get_relevant(question: str, limit: int = 3) -> list[dict]:
    """
    Return recent positively-rated answers whose question overlaps
    with the keywords in the new question. Used to enrich Claude's context.
    """
    keywords = [w.strip(".,!?") for w in question.lower().split() if len(w) > 3][:4]
    if not keywords:
        return []

    seen: set[str] = set()
    results: list[dict] = []
    for kw in keywords:
        try:
            resp = requests.get(
                _url(),
                headers=_headers(),
                params={
                    "select":   "question,answer",
                    "rating":   "eq.positive",
                    "question": f"ilike.*{kw}*",
                    "order":    "created_at.desc",
                    "limit":    str(limit),
                },
                timeout=5,
            )
            if resp.ok:
                for row in resp.json():
                    key = row["question"][:80]
                    if key not in seen:
                        seen.add(key)
                        results.append(row)
        except Exception:
            pass
        if len(results) >= limit:
            break

    return results[:limit]
