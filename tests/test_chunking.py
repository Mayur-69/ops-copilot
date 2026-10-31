from __future__ import annotations

from pathlib import Path

from src.chunking import chunk_markdown, docs_fingerprint, load_markdown_documents


def test_chunker_preserves_heading_paths() -> None:
    text = """# Warranty Policy

Introductory text about the policy.

## Warranty Period

The standard residential warranty is 24 months.

### Exclusions

Physical damage and unauthorised repairs are excluded.
"""
    chunks = chunk_markdown(text, source="warranty.md", max_chars=400, min_chars=10)
    sections = {chunk.section for chunk in chunks}
    assert "Warranty Policy" in sections
    assert "Warranty Policy > Warranty Period" in sections
    assert "Warranty Policy > Warranty Period > Exclusions" in sections
    assert all(chunk.source == "warranty.md" for chunk in chunks)
    assert all(chunk.doc_title == "Warranty Policy" for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_chunker_ignores_headings_inside_code_fences() -> None:
    text = """# Guide

```bash
# This is a shell comment, not a heading
echo hello
```

## Real Section

Content for the real section.
"""
    chunks = chunk_markdown(text, source="guide.md", max_chars=400, min_chars=10)
    sections = {chunk.section for chunk in chunks}
    assert "Guide > Real Section" in sections
    assert not any("shell comment" in section for section in sections)


def test_chunker_splits_long_sections_with_bounded_size() -> None:
    paragraph = " ".join(["warranty coverage replacement filter membrane"] * 80)
    text = f"# Policy\n\n## Long Section\n\n{paragraph}\n\n{paragraph}"
    chunks = chunk_markdown(text, source="policy.md", max_chars=500, overlap=80, min_chars=20)
    assert len(chunks) > 1
    assert all(chunk.text.strip() for chunk in chunks)
    assert all(len(chunk.text) <= 650 for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_chunker_is_deterministic() -> None:
    text = "# Doc\n\n## Section\n\n" + "word " * 300
    first = chunk_markdown(text, source="doc.md", max_chars=300, overlap=50)
    second = chunk_markdown(text, source="doc.md", max_chars=300, overlap=50)
    assert first == second


def test_load_markdown_documents_and_fingerprint(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# A\n\n## One\n\nAlpha content about filters.", encoding="utf-8")
    (docs / "b.md").write_text("# B\n\n## Two\n\nBeta content about warranties.", encoding="utf-8")
    chunks = load_markdown_documents(docs, max_chars=400)
    assert {chunk.source for chunk in chunks} == {"a.md", "b.md"}
    first = docs_fingerprint(docs)
    (docs / "a.md").write_text("# A\n\n## One\n\nChanged content.", encoding="utf-8")
    assert docs_fingerprint(docs) != first
