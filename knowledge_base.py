"""
Knowledge base — searches Notion pages directly via the Notion REST API.

Setup:
1. Go to https://www.notion.so/my-integrations → New integration → copy the token
2. Set NOTION_TOKEN in Railway environment variables (and local .env)
3. For each Notion page you want the bot to search:
   open the page → ··· menu → Add connections → pick your integration
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_CONTENT_PER_PAGE = 3000  # chars — keeps prompts manageable


def _headers() -> dict:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError("NOTION_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _page_title(page: dict) -> str:
    """Extract plain-text title from a Notion page object."""
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(rt.get("plain_text", "") for rt in prop.get("title", []))
    return "Untitled"


def _block_to_text(block: dict) -> str:
    """Convert a single Notion block to a readable plain-text line."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich = content.get("rich_text", [])
    text = "".join(rt.get("plain_text", "") for rt in rich)
    if btype in ("heading_1", "heading_2", "heading_3"):
        text = f"\n## {text}\n"
    elif btype == "bulleted_list_item":
        text = f"• {text}"
    elif btype == "numbered_list_item":
        text = f"- {text}"
    elif btype == "to_do":
        text = f"{'[x]' if content.get('checked') else '[ ]'} {text}"
    elif btype == "code":
        text = f"`{text}`"
    elif btype == "image":
        # Extract caption if present; images themselves have no rich_text
        caption = "".join(rt.get("plain_text", "") for rt in content.get("caption", []))
        text = f"[image: {caption}]" if caption else "[image]"
    elif btype in ("divider", "table_of_contents"):
        text = ""
    return text


def _fetch_page_text(page_id: str) -> str:
    """Fetch all block text for a Notion page (handles pagination)."""
    lines, cursor = [], None
    while True:
        params: dict = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = requests.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for block in data.get("results", []):
            line = _block_to_text(block)
            if line.strip():
                lines.append(line)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return "\n".join(lines)


def search(query: str, top_k: int = 5, threshold: float = 0.0) -> list[dict]:
    """
    Search Notion for pages matching the query.
    Returns a list of dicts with keys: title, source, content.
    """
    try:
        resp = requests.post(
            f"{NOTION_API}/search",
            headers=_headers(),
            json={
                "query": query,
                "filter": {"value": "page", "property": "object"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": top_k,
            },
            timeout=10,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])
        logger.info("Notion search %r → %d page(s) found", query, len(pages))
        if not pages:
            return []

        results = []
        for page in pages:
            page_id = page["id"]
            title   = _page_title(page)
            url     = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
            try:
                content = _fetch_page_text(page_id)
                # Include the page even if content is sparse (e.g. image-heavy pages)
                if not content.strip():
                    content = f"(This page — '{title}' — appears to contain images or non-text content. Direct the user to view it at {url})"
                results.append({
                    "title":   title,
                    "source":  url,
                    "content": content[:MAX_CONTENT_PER_PAGE],
                })
            except Exception as e:
                logger.warning("Could not fetch Notion page %s (%s): %s", page_id, title, e)
        return results

    except Exception as e:
        logger.error("Notion search failed: %s", e)
        return []


def add_chunks(source: str, chunks: list[str], title: str = "", metadata: dict = None) -> int:
    """No-op in Notion mode — content lives directly in Notion pages."""
    logger.info("Notion mode: add_chunks is a no-op. Edit pages in Notion directly.")
    return 0
