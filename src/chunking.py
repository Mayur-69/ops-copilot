from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WORD_PATTERN = re.compile(r"\S+")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    section: str
    text: str
    chunk_index: int
    doc_title: str
    content_hash: str


@dataclass
class _Section:
    path: str
    title: str
    body: list[str]


def _normalise(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    words = WORD_PATTERN.findall(text)
    if not words:
        return []
    pieces: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        addition = len(word) + (1 if current else 0)
        if current and current_length + addition > max_chars:
            pieces.append(" ".join(current))
            carry: list[str] = []
            carry_length = 0
            for existing in reversed(current):
                if carry_length + len(existing) + 1 > overlap:
                    break
                carry.insert(0, existing)
                carry_length += len(existing) + 1
            current = carry
            current_length = sum(len(item) + 1 for item in current)
        current.append(word)
        current_length += addition
    if current:
        pieces.append(" ".join(current))
    return pieces


def _split_section_body(body: str, max_chars: int, overlap: int) -> list[str]:
    body = _normalise(body)
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    pieces: list[str] = []
    current: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                pieces.append("\n\n".join(current))
                current = []
                current_length = 0
            pieces.extend(_split_long_text(paragraph, max_chars, overlap))
            continue
        addition = len(paragraph) + (2 if current else 0)
        if current and current_length + addition > max_chars:
            previous = "\n\n".join(current)
            pieces.append(previous)
            carry = previous[-overlap:] if overlap > 0 else ""
            carry = carry.lstrip()
            current = [carry, paragraph] if carry else [paragraph]
            current_length = sum(len(item) + 2 for item in current)
        else:
            current.append(paragraph)
            current_length += addition
    if current:
        pieces.append("\n\n".join(current))
    return [piece.strip() for piece in pieces if piece.strip()]


def chunk_markdown(
    text: str,
    *,
    source: str,
    max_chars: int = 900,
    overlap: int = 120,
    min_chars: int = 80,
) -> list[Chunk]:
    if max_chars < 200:
        raise ValueError("max_chars must be at least 200")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be between 0 and max_chars")

    lines = text.replace("\r\n", "\n").split("\n")
    headings: list[tuple[int, str]] = []
    sections: list[_Section] = []
    current_lines: list[str] = []
    doc_title = source
    in_code = False

    def flush() -> None:
        nonlocal current_lines
        body = "\n".join(current_lines).strip()
        if body:
            path = " > ".join(title for _, title in headings) if headings else doc_title
            sections.append(_Section(path=path, title=headings[-1][1] if headings else doc_title, body=[body]))
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            current_lines.append(line)
            continue
        match = None if in_code else HEADING_PATTERN.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            if level == 1:
                doc_title = title
            current_lines.append(line)
        else:
            current_lines.append(line)
    flush()

    if not sections:
        sections = [_Section(path=doc_title, title=doc_title, body=[_normalise(text)])]

    chunks: list[Chunk] = []
    chunk_index = 0
    for section in sections:
        body = "\n".join(section.body)
        body = re.sub(r"^#+\s+.*$", "", body, count=0, flags=re.MULTILINE).strip()
        prefix = section.path
        budget = max(200, max_chars - len(prefix) - 2)
        for piece in _split_section_body(body, budget, overlap):
            if len(piece) < min_chars and chunks:
                previous = chunks[-1]
                merged_text = f"{previous.text}\n\n{piece}".strip()
                if len(merged_text) <= max_chars + overlap:
                    chunks[-1] = Chunk(
                        chunk_id=previous.chunk_id,
                        source=previous.source,
                        section=previous.section,
                        text=merged_text,
                        chunk_index=previous.chunk_index,
                        doc_title=previous.doc_title,
                        content_hash=hashlib.sha256(merged_text.encode("utf-8")).hexdigest(),
                    )
                    continue
            content = f"{prefix}\n\n{piece}".strip()
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            digest = hashlib.sha1(
                f"{source}|{section.path}|{chunk_index}|{content_hash}".encode()
            ).hexdigest()[:16]
            chunks.append(
                Chunk(
                    chunk_id=digest,
                    source=source,
                    section=section.path,
                    text=content,
                    chunk_index=chunk_index,
                    doc_title=doc_title,
                    content_hash=content_hash,
                )
            )
            chunk_index += 1
    return chunks


def load_markdown_documents(docs_dir: Path, **kwargs: object) -> list[Chunk]:
    docs_dir = Path(docs_dir)
    if not docs_dir.exists():
        raise FileNotFoundError(f"Document directory not found: {docs_dir}")
    chunks: list[Chunk] = []
    for document in sorted(docs_dir.glob("*.md")):
        text = document.read_text(encoding="utf-8")
        chunks.extend(chunk_markdown(text, source=document.name, **kwargs))
    if not chunks:
        raise ValueError(f"No markdown documents found in {docs_dir}")
    return chunks


def docs_fingerprint(docs_dir: Path) -> str:
    docs_dir = Path(docs_dir)
    digest = hashlib.sha256()
    for document in sorted(docs_dir.glob("*.md")):
        digest.update(document.name.encode("utf-8"))
        digest.update(document.read_bytes())
    return digest.hexdigest()
