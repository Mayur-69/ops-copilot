from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed_documents(self, documents: Iterable[str]) -> list[list[float]]: ...

    def embed_query(self, query: str) -> list[float]: ...


class FastEmbedder:
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: str | Path | None = None,
        threads: int = 1,
    ) -> None:
        self.model_name = model_name
        self.threads = threads
        default_cache = Path(os.environ.get("FASTEMBED_CACHE_PATH", "data/.fastembed_cache"))
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=str(self.cache_dir),
                threads=self.threads,
            )
        return self._model

    def embed_documents(self, documents: Iterable[str]) -> list[list[float]]:
        texts = list(documents)
        if not texts:
            return []
        model = self._load()
        vectors = model.embed(texts, batch_size=16)
        return [[float(value) for value in vector] for vector in vectors]

    def embed_query(self, query: str) -> list[float]:
        model = self._load()
        vector = next(iter(model.query_embed(query)))
        return [float(value) for value in vector]


class DeterministicEmbedder:
    def __init__(self, dimension: int = 96) -> None:
        if dimension < 8:
            raise ValueError("dimension must be at least 8")
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        tokens = TOKEN_PATTERN.findall(text.lower())
        if not tokens:
            tokens = [text.lower() or "empty"]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[index] += sign
            if len(token) >= 4:
                for offset in range(len(token) - 2):
                    trigram = token[offset : offset + 3]
                    tri_digest = hashlib.blake2b(trigram.encode("utf-8"), digest_size=8).digest()
                    tri_index = int.from_bytes(tri_digest[:4], "little") % self.dimension
                    tri_sign = 1.0 if tri_digest[4] % 2 == 0 else -1.0
                    values[tri_index] += 0.25 * tri_sign
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def embed_documents(self, documents: Iterable[str]) -> list[list[float]]:
        return [self._vector(document) for document in documents]

    def embed_query(self, query: str) -> list[float]:
        return self._vector(query)
