"""
Q&A skill — handles mentions and DMs, calls Claude with knowledge base context.
"""
import logging
import os
import re
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TURNS  = 10
histories: dict[str, list[dict]] = {}

SYSTEM_PROMPT = """You are a helpful UAEOPS assistant. You answer questions based on the knowledge base excerpts provided in each message.

Guidelines:
- Be warm, conversational, and natural — talk like a knowledgeable colleague, not a document
- Synthesise the excerpts into a clear answer; don't just copy-paste them verbatim
- When it adds context, mention where information came from (e.g. "According to the runbook…")
- If the excerpts don't contain enough to answer, say exactly: "I don't have that in my knowledge base yet — you may want to ask the team or have an admin add it."
- Never invent facts or use knowledge outside what's in the excerpts"""

NO_RESULTS_MSG = (
    "I searched the Notion knowledge base but couldn't find anything relevant to that question. "
    "Try rephrasing, or ask an admin to add a Notion page covering that topic and connect it to the bot integration."
)

_KB_AVAILABLE       = False
_FEEDBACK_AVAILABLE = False
_bot_uid: Optional[str] = None

try:
    import knowledge_base
    if os.environ.get("NOTION_TOKEN"):
        _KB_AVAILABLE = True
except Exception as e:
    logger.warning("Knowledge base unavailable (%s). Q&A disabled, reminders still work.", e)

try:
    import feedback_store
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        _FEEDBACK_AVAILABLE = True
except Exception as e:
    logger.warning("Feedback store unavailable (%s). Ratings disabled.", e)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_bot_uid(client) -> str:
    global _bot_uid
    if not _bot_uid:
        _bot_uid = client.auth_test()["user_id"]
    return _bot_uid


def _answer_blocks(answer: str, feedback_id: Optional[str]) -> list[dict]:
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


def _qa_answer(claude: anthropic.Anthropic, channel_id: str, question: str) -> str:
    if not _KB_AVAILABLE:
        return (
            "The knowledge base isn't configured yet. "
            "Set `NOTION_TOKEN` in the Railway environment variables, then redeploy the bot."
        )

    results = knowledge_base.search_semantic(question)
    if not results:
        return NO_RESULTS_MSG

    kb_context = "\n\n---\n\n".join(
        f"[Source: {r.get('title') or r.get('source', 'unknown')}]\n{r['content']}"
        for r in results
    )
    context_parts = [f"Knowledge base excerpts:\n\n{kb_context}"]

    if _FEEDBACK_AVAILABLE:
        try:
            past = feedback_store.get_relevant(question)
            if past:
                past_context = "\n\n---\n\n".join(
                    f"[Past helpful answer for: {p['question'][:60]}]\n{p['answer']}"
                    for p in past
                )
                context_parts.insert(0, f"Past positively-rated answers:\n\n{past_context}")
        except Exception:
            pass

    augmented = "\n\n===\n\n".join(context_parts) + f"\n\n---\n\nQuestion: {question}"

    history = histories.setdefault(channel_id, [])
    history.append({"role": "user", "content": augmented})

    try:
        response = claude.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=history,
        )
        reply = response.content[0].text
    except Exception:
        history.pop()
        raise

    history[-1] = {"role": "user", "content": question}
    history.append({"role": "assistant", "content": reply})

    if len(history) > MAX_TURNS * 2:
        histories[channel_id] = history[-(MAX_TURNS * 2):]

    return reply


# ── Notion sync ───────────────────────────────────────────────────────────────

def start_background_sync(scheduler, pool):
    """Non-blocking Notion → vector store sync on startup, repeated every 6 hours."""
    if not (os.environ.get("VOYAGE_API_KEY") and os.environ.get("NOTION_TOKEN")):
        return

    try:
        import sync_notion
        pool.submit(sync_notion.sync_all)
        scheduler.add_job(
            sync_notion.sync_all,
            trigger="interval",
            hours=6,
            id="notion_sync",
            replace_existing=True,
        )
        logger.info("Notion sync scheduled (startup + every 6h)")
    except Exception as e:
        logger.warning("Could not schedule Notion sync: %s", e)


# ── register ──────────────────────────────────────────────────────────────────

def register(app, pool, claude: anthropic.Anthropic, scheduler):
    from skills.reminders import is_remind_request, handle_remind_request

    def _process_mention(event, say, client, placeholder_ts):
        channel = event["channel"]
        try:
            bot_uid   = _get_bot_uid(client)
            raw_text  = event.get("text", "")
            clean     = re.sub(rf"<@{re.escape(bot_uid)}(?:\|[^>]*)?>", "", raw_text).strip()
            logger.info("app_mention: channel=%s clean=%r", channel, clean[:80])

            if is_remind_request(clean):
                if placeholder_ts:
                    try:
                        client.chat_delete(channel=channel, ts=placeholder_ts)
                    except Exception:
                        pass
                handle_remind_request(event, say, client, scheduler)
                return

            if not clean:
                if placeholder_ts:
                    try:
                        client.chat_update(channel=channel, ts=placeholder_ts, text="Hi! Ask me anything.")
                        return
                    except Exception:
                        pass
                say("Hi! Ask me anything.")
                return

            answer = _qa_answer(claude, channel, clean)

            feedback_id = None
            if _FEEDBACK_AVAILABLE:
                feedback_id = feedback_store.create(clean, answer, channel, event.get("user", ""))
            blocks = _answer_blocks(answer, feedback_id)

            if placeholder_ts:
                try:
                    client.chat_update(channel=channel, ts=placeholder_ts, text=answer, blocks=blocks)
                    return
                except Exception:
                    pass
            say(text=answer, blocks=blocks)

        except Exception as e:
            logger.error("handle_mention error: %s", e, exc_info=True)
            try:
                if placeholder_ts:
                    client.chat_update(channel=channel, ts=placeholder_ts,
                                       text="Something went wrong — please try again.")
                else:
                    say("Something went wrong — please try again.")
            except Exception:
                pass

    @app.event("app_mention")
    def handle_mention(event, say, client):
        placeholder_ts = None
        try:
            placeholder_ts = say(text="⏳ Searching the knowledge base...").get("ts")
        except Exception:
            pass
        pool.submit(_process_mention, event, say, client, placeholder_ts)

    def _process_dm(event, say, client, placeholder_ts):
        channel = event["channel"]
        try:
            question = event.get("text", "").strip()
            if not question:
                return
            answer = _qa_answer(claude, channel, question)

            feedback_id = None
            if _FEEDBACK_AVAILABLE:
                feedback_id = feedback_store.create(question, answer, channel, event.get("user", ""))
            blocks = _answer_blocks(answer, feedback_id)

            if placeholder_ts:
                try:
                    client.chat_update(channel=channel, ts=placeholder_ts, text=answer, blocks=blocks)
                    return
                except Exception:
                    pass
            say(text=answer, blocks=blocks)
        except Exception as e:
            logger.error("handle_dm error: %s", e, exc_info=True)
            try:
                if placeholder_ts:
                    client.chat_update(channel=channel, ts=placeholder_ts,
                                       text="Something went wrong — please try again.")
                else:
                    say("Something went wrong — please try again.")
            except Exception:
                pass

    @app.event("message")
    def handle_dm(event, say, client):
        if event.get("bot_id") or event.get("subtype") or event.get("channel_type") not in ("im", "mpim"):
            return
        placeholder_ts = None
        try:
            placeholder_ts = say(text="⏳ Searching the knowledge base...").get("ts")
        except Exception:
            pass
        pool.submit(_process_dm, event, say, client, placeholder_ts)
