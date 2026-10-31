from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.chunking import chunk_markdown
from src.embeddings import DeterministicEmbedder
from src.rag import RagStore, build_index, merge_results


def _chunks():
    documents = {
        "warranty.md": "# Warranty Policy\n\n## Warranty Period\n\nThe residential warranty is 24 months. Commercial systems have a 12 month warranty.",
        "returns.md": "# Returns Policy\n\n## Return Window\n\nProducts may be returned within 30 days. A 10% restocking fee applies to opened products.",
        "installation.md": "# Installation SOP\n\n## Scheduling\n\nInstallation is scheduled within 48 hours in service cities.",
    }
    chunks = []
    for source, text in documents.items():
        chunks.extend(chunk_markdown(text, source=source, max_chars=400, min_chars=10))
    return chunks


def test_retrieval_returns_relevant_chunk_with_metadata() -> None:
    store = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    build_index(store, _chunks())
    results = store.query("How long is the residential warranty?", top_k=3)
    assert results
    assert results[0].source == "warranty.md"
    assert "Warranty Period" in results[0].section
    assert 0.0 <= results[0].score <= 1.0
    assert "24 months" in results[0].text


def test_retrieval_top_k_and_min_score() -> None:
    store = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    build_index(store, _chunks())
    assert len(store.query("return window", top_k=2)) <= 2
    assert store.query("return window", top_k=3, min_score=0.99) == []
    assert store.query("", top_k=3) == []


def test_empty_store_returns_no_results() -> None:
    store = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    assert store.count() == 0
    assert store.query("warranty") == []


def test_persistent_store_reset_and_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    embedder = DeterministicEmbedder()
    store = RagStore.persistent(path, embedder)
    build_index(store, _chunks())
    assert store.count() == len(_chunks())
    assert store.query("installation 48 hours")[0].source == "installation.md"
    store.reset()
    assert store.count() == 0
    build_index(store, _chunks())
    assert store.count() == len(_chunks())


def test_merge_results_prefers_best_and_marks_uploads() -> None:
    store = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    build_index(store, _chunks())
    persistent = store.query("warranty", top_k=2)
    session_store = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    session_store.add_chunks(
        chunk_markdown(
            "# Uploaded Policy\n\n## Local Rule\n\nThe local warranty is 36 months.",
            source="uploaded-policy.md",
            max_chars=400,
            min_chars=10,
        ),
        uploaded=True,
    )
    session = session_store.query("warranty 36 months", top_k=2)
    merged = merge_results(persistent, session, top_k=5)
    assert any(item.uploaded for item in merged)
    assert len(merged) == len({(item.source, item.section, item.text) for item in merged})
    assert [item.score for item in merged] == sorted((item.score for item in merged), reverse=True)
