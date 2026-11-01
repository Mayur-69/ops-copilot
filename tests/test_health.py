from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.bootstrap import ensure_index
from src.embeddings import DeterministicEmbedder
from src.health import check_health


def _configured(settings, tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "policy.md").write_text("# Policy\n\n## Rule\n\nUse evidence.", encoding="utf-8")
    return replace(
        settings,
        docs_dir=docs,
        index_dir=tmp_path / "index",
        fastembed_cache=tmp_path / "cache",
        llm_provider="mock",
        anthropic_api_key=None,
        openai_api_key=None,
    )


def test_health_ok_with_mock_provider(settings, tmp_path: Path) -> None:
    configured = _configured(settings, tmp_path)
    index = ensure_index(configured, embedder=DeterministicEmbedder())
    report = check_health(configured, rag=index.rag)
    assert report.ok is True
    assert report.data_as_of == "2026-11-01"
    assert report.checks["database"]["ok"] is True
    assert report.checks["documents"]["count"] == 1
    assert report.checks["index"]["chunks"] > 0
    assert report.checks["llm"]["provider"] == "mock"
    assert report.to_dict()["ok"] is True


def test_health_fails_without_index_or_key(settings, tmp_path: Path) -> None:
    configured = _configured(settings, tmp_path)
    configured = replace(
        configured,
        llm_provider="anthropic",
        anthropic_api_key=None,
    )
    report = check_health(configured)
    assert report.ok is False
    assert report.checks["index"]["ok"] is False
    assert report.checks["llm"]["ok"] is False
