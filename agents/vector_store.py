"""
Vector store — embeds text via Voyage AI and stores/searches in Supabase pgvector.

Required env vars:
  VOYAGE_API_KEY       — free at voyageai.com (200M tokens/month free)
  SUPABASE_URL         — Supabase project URL
  SUPABASE_SERVICE_KEY — Supabase service role key
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

VOYAGE_API   = "https://api.voyageai.com/v1/embeddings"
VOYAGE_MODEL = "voyage-3-lite"
BATCH_SIZE   = 128


def _voyage_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}",
        "Content-Type":  "application/json",
    }


def _sb_url(path: str) -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + path


def _sb_headers() -> dict:
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a list of texts using Voyage AI. Returns list of 512-dim vectors."""
    vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp = requests.post(
            VOYAGE_API,
            headers=_voyage_headers(),
            json={"model": VOYAGE_MODEL, "input": batch, "input_type": input_type},
            timeout=30,
        )
        resp.raise_for_status()
        vectors.extend(item["embedding"] for item in resp.json()["data"])
    return vectors


def upsert(pages: list[dict]) -> int:
    """
    Chunk each page, embed all chunks, delete old rows for the same source URLs,
    then insert new chunks. Returns total chunk count stored.
    """
    records = []
    for page in pages:
        for chunk in _chunk(page.get("content", "")):
            records.append({
                "source":  page.get("source", ""),
                "title":   page.get("title", ""),
                "content": chunk,
            })

    if not records:
        return 0

    embeddings = embed([r["content"] for r in records])
    for rec, emb in zip(records, embeddings):
        rec["embedding"] = emb

    sources = list({r["source"] for r in records})
    for src in sources:
        requests.delete(
            _sb_url("/rest/v1/documents"),
            headers=_sb_headers(),
            params={"source": f"eq.{src}"},
            timeout=10,
        ).raise_for_status()

    for i in range(0, len(records), 100):
        requests.post(
            _sb_url("/rest/v1/documents"),
            headers=_sb_headers(),
            json=records[i : i + 100],
            timeout=30,
        ).raise_for_status()

    logger.info("Upserted %d chunks for %d page(s)", len(records), len(pages))
    return len(records)


def search(query: str, top_k: int = 5, threshold: float = 0.4) -> list[dict]:
    """Embed the query and return similar document chunks from Supabase."""
    query_vec = embed([query], input_type="query")[0]
    resp = requests.post(
        _sb_url("/rest/v1/rpc/search_documents"),
        headers=_sb_headers(),
        json={
            "query_embedding": query_vec,
            "match_count":     top_k,
            "match_threshold": threshold,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def is_populated() -> bool:
    """True if the documents table has at least one row with an embedding."""
    resp = requests.get(
        _sb_url("/rest/v1/documents"),
        headers={**_sb_headers(), "Prefer": "count=exact"},
        params={"select": "id", "limit": "1", "embedding": "not.is.null"},
        timeout=5,
    )
    if not resp.ok:
        return False
    cr = resp.headers.get("Content-Range", "")
    return "/" in cr and cr.split("/")[-1] not in ("0", "*")


def _chunk(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks at paragraph boundaries."""
    if not text.strip():
        return []
    if len(text) <= size:
        return [text]

    chunks, current, current_len = [], [], 0
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) > size and current:
            chunks.append("\n".join(current))
            while current and current_len > overlap:
                current_len -= len(current.pop(0)) + 1
        current.append(para)
        current_len += len(para) + 1

    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]
