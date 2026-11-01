from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.bootstrap import FINGERPRINT_FILENAME, ensure_index
from src.embeddings import DeterministicEmbedder


def _docs(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "warranty.md").write_text(
        "# Warranty\n\n## Period\n\nThe residential warranty is 24 months.\n",
        encoding="utf-8",
    )
    (directory / "returns.md").write_text(
        "# Returns\n\n## Window\n\nReturns are accepted within 30 days.\n",
        encoding="utf-8",
    )


def test_ensure_index_builds_and_reuses_index(settings, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _docs(docs)
    configured = replace(
        settings,
        docs_dir=docs,
        index_dir=tmp_path / "index",
        fastembed_cache=tmp_path / "cache",
    )
    first = ensure_index(configured, embedder=DeterministicEmbedder())
    assert first.rebuilt is True
    assert first.chunk_count > 0
    assert first.chunk_count == first.rag.count()
    assert (tmp_path / "index" / FINGERPRINT_FILENAME).exists()

    second = ensure_index(configured, embedder=DeterministicEmbedder())
    assert second.rebuilt is False
    assert second.chunk_count == first.chunk_count


def test_ensure_index_rebuilds_when_docs_change(settings, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _docs(docs)
    configured = replace(
        settings,
        docs_dir=docs,
        index_dir=tmp_path / "index",
        fastembed_cache=tmp_path / "cache",
    )
    first = ensure_index(configured, embedder=DeterministicEmbedder())
    (docs / "warranty.md").write_text(
        "# Warranty\n\n## Period\n\nThe residential warranty is 36 months.\n",
        encoding="utf-8",
    )
    second = ensure_index(configured, embedder=DeterministicEmbedder())
    assert second.rebuilt is True
    assert second.fingerprint != first.fingerprint

    forced = ensure_index(configured, embedder=DeterministicEmbedder(), force=True)
    assert forced.rebuilt is True


def test_ensure_index_requires_documents(settings, tmp_path: Path) -> None:
    configured = replace(
        settings,
        docs_dir=tmp_path / "missing",
        index_dir=tmp_path / "index",
        fastembed_cache=tmp_path / "cache",
    )
    with pytest.raises(FileNotFoundError):
        ensure_index(configured, embedder=DeterministicEmbedder())
