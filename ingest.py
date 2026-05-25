#!/usr/bin/env python3
"""
Ingest documents into the UAEOPS knowledge base.

Usage examples:
  python ingest.py --file docs/runbook.pdf
  python ingest.py --file notes.md
  python ingest.py --file report.docx
  python ingest.py --url https://example.com/page
  python ingest.py --notion PAGE_ID
  python ingest.py --link "https://www.canva.com/design/..." --title "Q2 Slides" --description "Quarterly review slides"
"""
import argparse
import os
import sys
import textwrap
from dotenv import load_dotenv

load_dotenv()

CHUNK_SIZE = 800   # characters per chunk
OVERLAP    = 100   # overlap between chunks


# ── chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_SIZE])
        start += CHUNK_SIZE - OVERLAP
    return [c.strip() for c in chunks if c.strip()]


# ── source loaders ────────────────────────────────────────────────────────────

def load_file(path: str) -> tuple[str, str, list[str]]:
    """Returns (source, title, chunks)."""
    ext = os.path.splitext(path)[1].lower()
    title = os.path.basename(path)

    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)

    elif ext in (".docx", ".doc"):
        from docx import Document
        doc = Document(path)
        text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    elif ext in (".md", ".txt", ".rst"):
        with open(path, encoding="utf-8") as f:
            text = f.read()

    else:
        sys.exit(f"Unsupported file type: {ext}")

    return path, title, chunk_text(text)


def load_url(url: str) -> tuple[str, str, list[str]]:
    import requests
    from bs4 import BeautifulSoup

    resp = requests.get(url, timeout=15, headers={"User-Agent": "UAEOPS-Bot/1.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.title.string.strip() if soup.title else url

    # Remove nav/footer/script noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    return url, title, chunk_text(text)


def load_notion(page_id: str) -> tuple[str, str, list[str]]:
    import requests

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("NOTION_TOKEN is not set in .env")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }

    # Get page title
    page = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}", headers=headers, timeout=10
    ).json()
    props = page.get("properties", {})
    title_prop = props.get("title") or props.get("Name") or {}
    title_items = (title_prop.get("title") or title_prop.get("rich_text") or [])
    title = "".join(t.get("plain_text", "") for t in title_items) or page_id

    # Get all blocks (paginated)
    texts, cursor = [], None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = requests.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers, params=params, timeout=10,
        ).json()
        for block in resp.get("results", []):
            btype = block.get("type", "")
            rich = block.get(btype, {}).get("rich_text", [])
            texts.append("".join(t.get("plain_text", "") for t in rich))
        cursor = resp.get("next_cursor")
        if not resp.get("has_more"):
            break

    text = "\n".join(t for t in texts if t.strip())
    source = f"notion:{page_id}"
    return source, title, chunk_text(text)


def load_link(url: str, title: str, description: str) -> tuple[str, str, list[str]]:
    """Store a reference link (e.g. Canva) with title + description."""
    text = f"{title}\n\n{description}\n\nLink: {url}"
    return url, title, chunk_text(text)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest documents into UAEOPS knowledge base")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file",   metavar="PATH",    help="PDF, DOCX, MD, or TXT file")
    group.add_argument("--url",    metavar="URL",     help="Web page URL to scrape")
    group.add_argument("--notion", metavar="PAGE_ID", help="Notion page ID")
    group.add_argument("--link",   metavar="URL",     help="Reference link (e.g. Canva)")
    parser.add_argument("--title",       default="", help="Title override (used with --link)")
    parser.add_argument("--description", default="", help="Description (used with --link)")
    args = parser.parse_args()

    import knowledge_base

    if args.file:
        source, title, chunks = load_file(args.file)
    elif args.url:
        source, title, chunks = load_url(args.url)
    elif args.notion:
        source, title, chunks = load_notion(args.notion)
    else:
        if not args.title:
            sys.exit("--link requires --title")
        source, title, chunks = load_link(args.link, args.title, args.description)

    if not chunks:
        sys.exit("No text extracted — nothing to ingest.")

    print(f"Ingesting '{title}' → {len(chunks)} chunks...")
    n = knowledge_base.add_chunks(source=source, chunks=chunks, title=title)
    print(f"Done. {n} chunks stored in knowledge base.")


if __name__ == "__main__":
    main()
