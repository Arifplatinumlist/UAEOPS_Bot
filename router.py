"""
Router — classifies incoming Slack message intent and returns a routing label.
Uses a keyword pre-check for reminders (no API call), then Claude Haiku for everything else.
Falls back to "qa" on any error — the Q&A agent handles off-topic messages gracefully.
"""
import os
import re
import logging
from typing import Literal

import anthropic

logger = logging.getLogger(__name__)

Intent = Literal["reminder", "alert", "qa", "unknown"]

_VALID_INTENTS = {"reminder", "alert", "qa", "unknown"}

ROUTER_SYSTEM = """You are a message classifier for an ops team Slack bot.
Classify the user message into exactly one category:

- reminder: The user wants to be reminded about something later (e.g. "remind me", "set a reminder", "ping me about this tomorrow")
- alert: The user is pasting or describing a system alert, error, monitoring notification, or incident (e.g. PagerDuty firing, CloudWatch alarm, Datadog alert, stack trace, HTTP 5xx burst, CRITICAL/WARNING log line)
- qa: The user is asking a question about processes, policies, runbooks, or team knowledge
- unknown: A greeting, casual chat, or no clear intent

Respond with ONLY the category word, lowercase, no punctuation."""

_REMIND_RE = re.compile(r"remind\s+me|set\s+a?\s*reminder", re.IGNORECASE)

_claude = anthropic.Anthropic()


def _classify(text: str) -> Intent:
    try:
        response = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            system=ROUTER_SYSTEM,
            messages=[{"role": "user", "content": text[:500]}],
        )
        label = response.content[0].text.strip().lower()
        if label in _VALID_INTENTS:
            return label  # type: ignore[return-value]
        logger.warning("Router returned unexpected label %r — defaulting to qa", label)
        return "qa"
    except Exception as e:
        logger.error("Router classification failed: %s — defaulting to qa", e)
        return "qa"


def route(text: str) -> Intent:
    """
    Classify message intent. Reminder keyword check runs first (no LLM call).
    Everything else goes to Claude Haiku for classification.
    """
    if _REMIND_RE.search(text):
        return "reminder"
    intent = _classify(text)
    logger.info("ROUTER: %r -> %s", text[:80], intent)
    return intent
