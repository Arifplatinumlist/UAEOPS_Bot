"""
Q&A Agent — answers questions about team processes, policies, and runbooks.
Uses semantic search (Voyage AI + pgvector) when available, falls back to Notion
keyword search. Surfaces past positively-rated answers as extra context.
Maintains per-channel conversation history (passed in, not stored here).
"""
import os
import logging
from typing import Optional
import anthropic

from agents import kb_agent

logger = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a helpful UAEOPS assistant. You answer questions based on the knowledge base excerpts provided in each message.

Guidelines:
- Be warm, conversational, and natural — talk like a knowledgeable colleague, not a document
- Synthesise the excerpts into a clear answer; don't just copy-paste them verbatim
- When it adds context, mention where information came from (e.g. "According to the runbook…")
- If the excerpts don't contain enough to answer, say exactly: "I don't have that in my knowledge base yet — you may want to ask the team or have an admin add it."
- Never invent facts or use knowledge outside what's in the excerpts"""

NO_RESULTS_MSG = (
    "I searched the knowledge base but couldn't find anything relevant to that question. "
    "Try rephrasing, or ask an admin to add a Notion page covering that topic and connect it to the bot integration."
)

_KB_AVAILABLE: bool = bool(os.environ.get("NOTION_TOKEN"))
_FEEDBACK_AVAILABLE: bool = False

try:
    from agents import feedback_store
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        _FEEDBACK_AVAILABLE = True
except Exception as e:
    logger.warning("Feedback store unavailable (%s). Ratings disabled.", e)

_claude = anthropic.Anthropic()


def answer_blocks(answer: str, feedback_id: Optional[str]) -> list[dict]:
    """Build Slack blocks for an answer with optional 👍/👎 feedback buttons."""
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": answer}}]
    if feedback_id:
        blocks.append({
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "👍"}, "action_id": "feedback_positive", "value": feedback_id},
                {"type": "button", "text": {"type": "plain_text", "text": "👎"}, "action_id": "feedback_negative", "value": feedback_id},
            ],
        })
    return blocks


def handle(channel_id: str, question: str, history: list[dict]) -> tuple[str, list[dict], Optional[str]]:
    """
    Search KB semantically, call Claude, return (reply_text, updated_history, feedback_id).
    feedback_id is None if feedback store is unavailable.
    Caller owns and stores the history.
    """
    if not _KB_AVAILABLE:
        return (
            "The knowledge base isn't configured yet. "
            "Set `NOTION_TOKEN` in the Railway environment variables, then redeploy the bot.",
            history,
            None,
        )

    results = kb_agent.search_semantic(question)
    if not results:
        return NO_RESULTS_MSG, history, None

    context_parts = []

    # Surface past positively-rated answers as additional context
    if _FEEDBACK_AVAILABLE:
        try:
            past = feedback_store.get_relevant(question)
            if past:
                past_context = "\n\n---\n\n".join(
                    f"[Past helpful answer for: {p['question'][:60]}]\n{p['answer']}"
                    for p in past
                )
                context_parts.append(f"Past positively-rated answers:\n\n{past_context}")
        except Exception:
            pass

    kb_context = "\n\n---\n\n".join(
        f"[Source: {r.get('title') or r.get('source', 'unknown')}]\n{r['content']}"
        for r in results
    )
    context_parts.append(f"Knowledge base excerpts:\n\n{kb_context}")

    augmented = "\n\n===\n\n".join(context_parts) + f"\n\n---\n\nQuestion: {question}"

    history = list(history)
    history.append({"role": "user", "content": augmented})

    response = _claude.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    reply = response.content[0].text

    # Store the clean question (not the augmented prompt) in history
    history[-1] = {"role": "user", "content": question}
    history.append({"role": "assistant", "content": reply})

    # Store Q&A in feedback store so users can rate it
    feedback_id = None
    if _FEEDBACK_AVAILABLE:
        try:
            feedback_id = feedback_store.create(question, reply, channel_id, "")
        except Exception:
            pass

    return reply, history, feedback_id
