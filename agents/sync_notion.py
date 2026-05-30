"""
Sync all Notion pages connected to the bot integration into the Supabase vector store.

Run standalone: python sync_notion.py
Also called automatically on bot startup and every 6 hours by the scheduler.
"""
import logging
import os
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sync_all() -> int:
    """
    Fetch all Notion pages, embed and upsert them to the vector store.
    Returns count of pages synced. Safe to call repeatedly — upsert is idempotent.
    """
    from agents import kb_agent as knowledge_base
    from agents import vector_store

    all_pages, cursor = [], None
    while True:
        body: dict = {
            "filter": {"value": "page", "property": "object"},
            "sort":   {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor

        resp = requests.post(
            f"{knowledge_base.NOTION_API}/search",
            headers=knowledge_base._headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        all_pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    logger.info("Found %d Notion page(s) to sync", len(all_pages))

    pages_with_content = []
    for page in all_pages:
        page_id = page["id"]
        title   = knowledge_base._page_title(page)
        url     = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
        try:
            content = knowledge_base._fetch_page_text(page_id)
            if content.strip():
                pages_with_content.append({"source": url, "title": title, "content": content})
        except Exception as e:
            logger.warning("Could not fetch page %s (%s): %s", page_id, title, e)

    if not pages_with_content:
        logger.info("No content fetched — vector store not updated")
        return 0

    chunks = vector_store.upsert(pages_with_content)
    logger.info("Synced %d page(s) (%d chunks) to vector store", len(pages_with_content), chunks)
    return len(pages_with_content)


if __name__ == "__main__":
    n = sync_all()
    print(f"Done — {n} page(s) synced")
