import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import anthropic
import knowledge_base

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

slack_app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a helpful UAEOPS assistant. You answer questions based on the knowledge base excerpts provided in each message.

Guidelines:
- Be warm, conversational, and natural — talk like a knowledgeable colleague, not a document
- Synthesise the excerpts into a clear answer; don't just copy-paste them verbatim
- When it adds context, mention where information came from (e.g. "According to the runbook…")
- If the excerpts don't contain enough to answer, say exactly: "I don't have that in my knowledge base yet — you may want to ask the team or have an admin add it."
- Never invent facts or use knowledge outside what's in the excerpts"""

NO_RESULTS_MSG = (
    "I searched my knowledge base but couldn't find anything relevant to that question. "
    "Try rephrasing, or let an admin know to add that topic with:\n"
    "`python ingest.py --file yourfile.pdf`"
)

# Per-channel conversation history (resets on restart)
histories: dict[str, list[dict]] = {}
MAX_TURNS = 10


def answer(channel_id: str, question: str) -> str:
    results = knowledge_base.search(question)

    if not results:
        return NO_RESULTS_MSG

    # Build context block from top KB chunks
    context = "\n\n---\n\n".join(
        f"[Source: {r.get('title') or r.get('source', 'unknown')}]\n{r['content']}"
        for r in results
    )
    augmented = f"Knowledge base excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"

    history = histories.setdefault(channel_id, [])
    history.append({"role": "user", "content": augmented})

    response = claude.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    reply = response.content[0].text

    # Store the original question (not the augmented version) so history stays clean
    history[-1] = {"role": "user", "content": question}
    history.append({"role": "assistant", "content": reply})

    if len(history) > MAX_TURNS * 2:
        histories[channel_id] = history[-(MAX_TURNS * 2):]

    return reply


# ── Slack event handlers ───────────────────────────────────────────────────────

@slack_app.event("app_mention")
def handle_mention(event, say, client):
    channel = event["channel"]
    bot_uid = client.auth_test()["user_id"]
    question = event.get("text", "").replace(f"<@{bot_uid}>", "").strip()

    if not question:
        say("Hi! Ask me anything.", thread_ts=event["ts"])
        return

    client.reactions_add(channel=channel, name="thinking_face", timestamp=event["ts"])
    try:
        say(text=answer(channel, question), thread_ts=event["ts"])
    except Exception as e:
        logger.error("Error: %s", e)
        say(text="Something went wrong — please try again.", thread_ts=event["ts"])
    finally:
        client.reactions_remove(channel=channel, name="thinking_face", timestamp=event["ts"])


@slack_app.event("message")
def handle_dm(event, say, client):
    if event.get("bot_id") or event.get("subtype") or event.get("channel_type") != "im":
        return

    question = event.get("text", "").strip()
    if not question:
        return

    channel = event["channel"]
    client.reactions_add(channel=channel, name="thinking_face", timestamp=event["ts"])
    try:
        say(text=answer(channel, question))
    except Exception as e:
        logger.error("Error: %s", e)
        say(text="Something went wrong — please try again.")
    finally:
        client.reactions_remove(channel=channel, name="thinking_face", timestamp=event["ts"])


if __name__ == "__main__":
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
