"""
Vector search against Supabase pgvector.
Uses sentence-transformers (all-MiniLM-L6-v2, 384 dims) for local embeddings.
Model (~90 MB) is downloaded on first use and cached automatically.
"""
import os
import logging
from functools import lru_cache
from supabase import create_client, Client

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _client() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def embed(text: str) -> list[float]:
    return _model().encode(text, normalize_embeddings=True).tolist()


def search(query: str, top_k: int = 5, threshold: float = 0.3) -> list[dict]:
    """Return top_k document chunks most similar to query."""
    try:
        result = _client().rpc("search_documents", {
            "query_embedding": embed(query),
            "match_count": top_k,
            "match_threshold": threshold,
        }).execute()
        return result.data or []
    except Exception as e:
        logger.error("KB search failed: %s", e)
        return []


def add_chunks(source: str, chunks: list[str], title: str = "", metadata: dict = None) -> int:
    """Embed and insert text chunks. Returns number of rows inserted."""
    rows = [
        {
            "source": source,
            "title": title or source,
            "content": chunk,
            "metadata": metadata or {},
            "embedding": embed(chunk),
        }
        for chunk in chunks
        if chunk.strip()
    ]
    if not rows:
        return 0
    _client().table("documents").insert(rows).execute()
    return len(rows)
