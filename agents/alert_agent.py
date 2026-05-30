"""
Alert Agent — triages system alerts for on-call engineers.
Searches KB for relevant runbooks/escalation procedures, then produces
a structured triage response via Claude. Stateless — no conversation history.
"""
import os
import re
import logging
import anthropic

from agents import kb_agent

logger = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are UAEOPS AlertBot, an on-call assistant for the UAE operations team.
Your job is to help engineers triage and respond to system alerts quickly.

When given an alert or error, respond in this exact format:

**Alert:** <one-line summary of what fired>
**Likely cause:** <most probable cause based on KB context — say "unknown — check logs" if no match>
**Immediate action:** <single most important next step>
**Escalate to:** <person or team from KB — say "unknown — check escalation matrix" if not found>
**Runbook:** <link if found in KB — say "None found — check Notion" if not found>

Rules:
- Only use information from the knowledge base excerpts provided. Never invent runbook steps.
- If no KB results match, say so explicitly and suggest the engineer search Notion directly.
- Keep responses tight — on-call engineers are under time pressure.
- If the message is not actually an alert (it just looks like one), say so briefly and offer to help with Q&A instead.
- If the alert is ambiguous (could be multiple services), ask ONE clarifying question before providing triage."""

NO_KB_MSG = (
    "⚠️ No matching runbooks found in the knowledge base for this alert.\n"
    "Search Notion directly or check the escalation matrix. "
    "To improve future responses, add a runbook page to Notion and connect it to the bot integration."
)

_claude = anthropic.Anthropic()


def _extract_service(alert_text: str) -> str:
    """Best-effort extraction of a service/host name from alert text for a second KB search."""
    match = re.search(r"(?:service|host|app|cluster|pod|container)[:\s]+(\S+)", alert_text, re.IGNORECASE)
    if match:
        return match.group(1).strip(".,;:")
    return ""


def handle(channel_id: str, alert_text: str) -> str:
    """
    Search KB for runbooks, call Claude to triage.
    Returns a formatted Slack message string.
    Each alert is independent — no conversation history.
    """
    # Two searches: raw alert text + extracted service name
    results = kb_agent.search_semantic(alert_text[:300])
    service = _extract_service(alert_text)
    if service:
        extra = kb_agent.search_semantic(service, top_k=3)
        seen_urls = {r["source"] for r in results}
        for r in extra:
            if r["source"] not in seen_urls:
                results.append(r)
                seen_urls.add(r["source"])

    if not results:
        return NO_KB_MSG

    context = "\n\n---\n\n".join(
        f"[Source: {r.get('title') or r.get('source', 'unknown')}]\n{r['content']}"
        for r in results
    )
    prompt = f"Knowledge base excerpts:\n\n{context}\n\n---\n\nAlert to triage:\n{alert_text}"

    try:
        response = _claude.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error("Alert agent Claude call failed: %s", e)
        return "Something went wrong during alert triage. Check Railway logs and try again."
