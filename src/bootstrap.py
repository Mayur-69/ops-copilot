from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.chunking import docs_fingerprint, load_markdown_documents
from src.config import Settings
from src.embeddings import Embedder, FastEmbedder
from src.rag import RagStore

FINGERPRINT_FILENAME = "docs_fingerprint.txt"


@dataclass(frozen=True)
class IndexBuildResult:
    rag: RagStore
    rebuilt: bool
    chunk_count: int
    fingerprint: str


def ensure_index(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    rag: RagStore | None = None,
    force: bool = False,
) -> IndexBuildResult:
    active_embedder = embedder or FastEmbedder(
        model_name=settings.fastembed_model,
        cache_dir=settings.fastembed_cache,
    )
    store = rag or RagStore.persistent(settings.index_dir, active_embedder)
    fingerprint = docs_fingerprint(settings.docs_dir)
    fingerprint_path = Path(settings.index_dir) / FINGERPRINT_FILENAME
    previous = fingerprint_path.read_text(encoding="utf-8").strip() if fingerprint_path.exists() else ""
    stale = force or previous != fingerprint or store.count() == 0

    if stale:
        chunks = load_markdown_documents(settings.docs_dir)
        store.reset()
        store.add_chunks(chunks)
        fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
        fingerprint_path.write_text(fingerprint + "\n", encoding="utf-8")
        return IndexBuildResult(
            rag=store,
            rebuilt=True,
            chunk_count=store.count(),
            fingerprint=fingerprint,
        )

    return IndexBuildResult(
        rag=store,
        rebuilt=False,
        chunk_count=store.count(),
        fingerprint=fingerprint,
    )
