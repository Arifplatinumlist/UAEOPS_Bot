"""
Q&A Agent — answers questions about team processes, policies, and runbooks.
Searches the knowledge base via kb_agent, then synthesises an answer via Claude.
Maintains per-channel conversation history (passed in, not stored here).
"""
import os
import logging
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
    "I searched the Notion knowledge base but couldn't find anything relevant to that question. "
    "Try rephrasing, or ask an admin to add a Notion page covering that topic and connect it to the bot integration."
)

_KB_AVAILABLE: bool = bool(os.environ.get("NOTION_TOKEN"))

_claude = anthropic.Anthropic()


def handle(channel_id: str, question: str, history: list[dict]) -> tuple[str, list[dict]]:
    """
    Search KB, call Claude, return (reply_text, updated_history).
    Caller owns and stores the history.
    """
    if not _KB_AVAILABLE:
        return (
            "The knowledge base isn't configured yet. "
            "Set `NOTION_TOKEN` in the Railway environment variables, then redeploy the bot.",
            history,
        )

    results = kb_agent.search(question)
    if not results:
        return NO_RESULTS_MSG, history

    context = "\n\n---\n\n".join(
        f"[Source: {r.get('title') or r.get('source', 'unknown')}]\n{r['content']}"
        for r in results
    )
    augmented = f"Knowledge base excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"

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

    return reply, history
