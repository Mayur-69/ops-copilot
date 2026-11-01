from __future__ import annotations

import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.chunking import chunk_markdown
from src.rag import RagStore

ALLOWED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_CHARS = 200_000
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


class UploadError(ValueError):
    pass


@dataclass(frozen=True)
class UploadedDocument:
    source: str
    original_name: str
    characters: int
    chunks: int


def _file_bytes(file: Any) -> bytes:
    if hasattr(file, "getvalue"):
        data = file.getvalue()
    elif hasattr(file, "read"):
        data = file.read()
    else:
        raise UploadError("Unsupported uploaded file object.")
    if not isinstance(data, bytes):
        raise UploadError("Uploaded file did not provide bytes.")
    if not data:
        raise UploadError("Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"Each upload must be smaller than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return data


def extract_uploaded_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadError(f"Unsupported file type '{suffix or 'unknown'}'. Use .md, .txt, or .pdf.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"Each upload must be smaller than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except Exception as exc:
            raise UploadError(f"Could not read PDF: {str(exc)[:200]}") from None
        if not text:
            raise UploadError("This PDF contains no extractable text. Try a text-based PDF.")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        text = text.strip()
        if not text:
            raise UploadError("Uploaded file contains no readable text.")
    if len(text) > MAX_UPLOAD_CHARS:
        raise UploadError(
            f"Uploaded text is too long ({len(text):,} characters). Limit is {MAX_UPLOAD_CHARS:,}."
        )
    return text


def _safe_source(filename: str, used: set[str]) -> str:
    name = SAFE_NAME.sub("_", Path(filename).name).strip(" ._")
    if not name:
        name = "upload.md"
    suffix = Path(name).suffix.lower() or ".md"
    stem = Path(name).stem or "upload"
    candidate = f"{stem}{suffix}"
    counter = 2
    while candidate.lower() in used:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used.add(candidate.lower())
    return candidate


def add_uploads(
    store: RagStore,
    files: Iterable[Any],
    *,
    max_files: int = 5,
    existing_sources: set[str] | None = None,
) -> list[UploadedDocument]:
    items = list(files)
    if not items:
        raise UploadError("Choose at least one file to upload.")
    if len(items) > max_files:
        raise UploadError(f"Upload at most {max_files} files per session.")
    used = {name.lower() for name in (existing_sources or set())}
    added: list[UploadedDocument] = []
    for file in items:
        original_name = str(getattr(file, "name", "upload"))
        data = _file_bytes(file)
        text = extract_uploaded_text(original_name, data)
        source = _safe_source(original_name, used)
        chunks = chunk_markdown(text, source=source, max_chars=900)
        if not chunks:
            raise UploadError(f"No readable content found in {original_name}.")
        store.add_chunks(chunks, uploaded=True)
        added.append(
            UploadedDocument(
                source=source,
                original_name=original_name,
                characters=len(text),
                chunks=len(chunks),
            )
        )
    return added
