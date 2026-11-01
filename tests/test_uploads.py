from __future__ import annotations

import io
from uuid import uuid4

import pytest

from src.embeddings import DeterministicEmbedder
from src.rag import RagStore
from src.uploads import MAX_UPLOAD_BYTES, UploadError, add_uploads, extract_uploaded_text


class FakeUpload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


@pytest.fixture
def store() -> RagStore:
    return RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"uploads_{uuid4().hex}")


def test_extract_text_formats() -> None:
    assert extract_uploaded_text("notes.txt", b"hello") == "hello"
    assert extract_uploaded_text("notes.md", b"# Title\n\nBody") == "# Title\n\nBody"
    with pytest.raises(UploadError):
        extract_uploaded_text("notes.exe", b"x")
    with pytest.raises(UploadError):
        extract_uploaded_text("notes.txt", b"")
    with pytest.raises(UploadError):
        extract_uploaded_text("notes.txt", b"x" * (MAX_UPLOAD_BYTES + 1))


def test_pdf_without_text_is_rejected() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(UploadError):
        extract_uploaded_text("blank.pdf", buffer.getvalue())


def test_add_uploads_and_citations(store: RagStore) -> None:
    documents = add_uploads(
        store,
        [FakeUpload("local-policy.md", b"# Local Policy\n\n## Warranty\n\nThe local warranty is 36 months.")],
    )
    assert len(documents) == 1
    assert documents[0].source == "local-policy.md"
    assert documents[0].chunks >= 1
    results = store.query("local warranty", top_k=2)
    assert any(item.source == "local-policy.md" and item.uploaded for item in results)


def test_duplicate_names_are_unique_and_limits_enforced(store: RagStore) -> None:
    first = add_uploads(store, [FakeUpload("policy.md", b"# A\n\nFirst policy.")])
    second = add_uploads(
        store,
        [FakeUpload("policy.md", b"# B\n\nSecond policy.")],
        existing_sources={item.source for item in first},
    )
    assert first[0].source == "policy.md"
    assert second[0].source == "policy-2.md"
    with pytest.raises(UploadError):
        add_uploads(store, [])
    with pytest.raises(UploadError):
        add_uploads(
            store,
            [FakeUpload(f"{index}.md", b"# X\n\nText.") for index in range(3)],
            max_files=2,
        )
