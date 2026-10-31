from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.chunking import Chunk
from src.embeddings import Embedder

DEFAULT_COLLECTION = "ops_docs"


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source: str
    section: str
    text: str
    score: float
    uploaded: bool = False


def _collection_names(client: object) -> set[str]:
    collections = client.list_collections()
    names: set[str] = set()
    for collection in collections:
        name = getattr(collection, "name", collection)
        names.add(str(name))
    return names


class RagStore:
    def __init__(self, client: object, collection_name: str, embedder: Embedder) -> None:
        self.client = client
        self.collection_name = collection_name
        self.embedder = embedder
        self._collection: object | None = None

    @classmethod
    def persistent(
        cls,
        path: str | Path,
        embedder: Embedder,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> RagStore:
        import chromadb
        from chromadb.config import Settings

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(path),
            settings=Settings(anonymized_telemetry=False),
        )
        return cls(client, collection_name, embedder)

    @classmethod
    def ephemeral(
        cls,
        embedder: Embedder,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> RagStore:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
        return cls(client, collection_name, embedder)

    @property
    def collection(self) -> object:
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )
        return self._collection

    def count(self) -> int:
        return int(self.collection.count())

    def reset(self) -> None:
        if self.collection_name in _collection_names(self.client):
            self.client.delete_collection(self.collection_name)
        self._collection = None

    def add_chunks(self, chunks: Iterable[Chunk], *, uploaded: bool = False) -> int:
        items = list(chunks)
        if not items:
            return 0
        vectors = self.embedder.embed_documents(chunk.text for chunk in items)
        batch_size = 64
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            batch_vectors = vectors[start : start + batch_size]
            self.collection.add(
                ids=[chunk.chunk_id for chunk in batch],
                embeddings=batch_vectors,
                documents=[chunk.text for chunk in batch],
                metadatas=[
                    {
                        "source": chunk.source,
                        "section": chunk.section,
                        "chunk_index": chunk.chunk_index,
                        "doc_title": chunk.doc_title,
                        "content_hash": chunk.content_hash,
                        "uploaded": uploaded,
                    }
                    for chunk in batch
                ],
            )
        return len(items)

    def query(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        if not query.strip() or self.count() == 0:
            return []
        top_k = max(1, min(top_k, 20))
        vector = self.embedder.embed_query(query)
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=min(top_k, self.count()),
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        retrieved: list[RetrievedChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
            if document is None or metadata is None:
                continue
            score = 1.0 - float(distance) if distance is not None else 0.0
            if score < min_score:
                continue
            retrieved.append(
                RetrievedChunk(
                    chunk_id=str(chunk_id),
                    source=str(metadata.get("source", "unknown")),
                    section=str(metadata.get("section", "")),
                    text=str(document),
                    score=score,
                    uploaded=bool(metadata.get("uploaded", False)),
                )
            )
        return retrieved


def merge_results(
    persistent: list[RetrievedChunk],
    session: list[RetrievedChunk] | None,
    *,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    combined = list(persistent)
    if session:
        combined.extend(session)
    best: dict[tuple[str, str, str], RetrievedChunk] = {}
    for item in combined:
        key = (item.source, item.section, item.text)
        current = best.get(key)
        if current is None or item.score > current.score:
            best[key] = item
    return sorted(best.values(), key=lambda item: item.score, reverse=True)[:top_k]


def build_index(
    store: RagStore,
    chunks: Iterable[Chunk],
    *,
    force: bool = False,
) -> int:
    if force:
        store.reset()
    if store.count() > 0 and not force:
        return store.count()
    return store.add_chunks(chunks)
