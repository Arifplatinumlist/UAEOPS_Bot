"""
Feedback skill — handles 👍/👎 rating buttons on Q&A answers.
"""
import logging
import os

logger = logging.getLogger(__name__)

_FEEDBACK_AVAILABLE = False
try:
    import feedback_store
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        _FEEDBACK_AVAILABLE = True
except Exception as e:
    logger.warning("Feedback store unavailable (%s). Ratings disabled.", e)


def _handle_feedback(ack, body, respond, rating: str):
    ack()
    feedback_id = body["actions"][0]["value"]
    user_id     = body["user"]["id"]

    if _FEEDBACK_AVAILABLE:
        feedback_store.rate(feedback_id, user_id, rating)

    emoji = "👍" if rating == "positive" else "👎"
    try:
        original_text = body["message"]["blocks"][0]["text"]["text"]
    except Exception:
        original_text = body["message"].get("text", "")

    respond(
        replace_original=True,
        text=original_text,
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": original_text}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{emoji} Thanks for the feedback!_"}]},
        ],
    )


def register(app):
    @app.action("feedback_positive")
    def handle_feedback_positive(ack, body, respond):
        _handle_feedback(ack, body, respond, "positive")

    @app.action("feedback_negative")
    def handle_feedback_negative(ack, body, respond):
        _handle_feedback(ack, body, respond, "negative")
