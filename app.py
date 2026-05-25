import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import anthropic

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- clients ---
slack_app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful assistant for UAEOPS. Answer questions clearly and concisely.",
)

# Per-channel conversation history (in-memory, resets on restart)
conversation_histories: dict[str, list[dict]] = {}
MAX_HISTORY = 20  # keep last 20 turns per channel


def ask_claude(channel_id: str, user_message: str) -> str:
    history = conversation_histories.setdefault(channel_id, [])
    history.append({"role": "user", "content": user_message})

    response = claude.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    # Trim history to avoid unbounded growth
    if len(history) > MAX_HISTORY * 2:
        conversation_histories[channel_id] = history[-(MAX_HISTORY * 2):]

    return reply


# --- event handlers ---

@slack_app.event("app_mention")
def handle_mention(event, say, client):
    """Respond when the bot is @mentioned in a channel."""
    channel = event["channel"]
    # Strip the bot mention from the text
    text = event.get("text", "")
    bot_user_id = client.auth_test()["user_id"]
    question = text.replace(f"<@{bot_user_id}>", "").strip()

    if not question:
        say("Hi! Ask me anything.", thread_ts=event.get("ts"))
        return

    # Show typing indicator
    client.reactions_add(channel=channel, name="thinking_face", timestamp=event["ts"])

    try:
        answer = ask_claude(channel, question)
        say(text=answer, thread_ts=event.get("ts"))
    except Exception as e:
        logger.error("Claude error: %s", e)
        say(text="Sorry, I ran into an error. Please try again.", thread_ts=event.get("ts"))
    finally:
        client.reactions_remove(channel=channel, name="thinking_face", timestamp=event["ts"])


@slack_app.event("message")
def handle_dm(event, say, client):
    """Respond to direct messages (channel_type == 'im')."""
    # Ignore bot messages, edited messages, and non-DM channels
    if event.get("bot_id") or event.get("subtype") or event.get("channel_type") != "im":
        return

    question = event.get("text", "").strip()
    if not question:
        return

    channel = event["channel"]
    client.reactions_add(channel=channel, name="thinking_face", timestamp=event["ts"])

    try:
        answer = ask_claude(channel, question)
        say(text=answer)
    except Exception as e:
        logger.error("Claude error: %s", e)
        say(text="Sorry, I ran into an error. Please try again.")
    finally:
        client.reactions_remove(channel=channel, name="thinking_face", timestamp=event["ts"])


if __name__ == "__main__":
    handler = SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"])
    logger.info("UAEOPS Bot is running...")
    handler.start()
