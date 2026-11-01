from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.generate_data import build_database
from src.chunking import chunk_markdown
from src.config import Settings, load_settings
from src.embeddings import DeterministicEmbedder
from src.rag import RagStore
from src.tools import ToolRegistry


@pytest.fixture
def demo_database(tmp_path: Path) -> Path:
    database = tmp_path / "ops_copilot.db"
    build_database(
        database,
        as_of=date(2026, 11, 1),
        seed=11,
        order_count=100,
        customer_count=30,
        ticket_count=30,
    )
    return database


@pytest.fixture
def settings(demo_database: Path) -> Settings:
    return load_settings(
        env={
            "OPS_DATA_DIR": str(demo_database.parent),
            "LLM_PROVIDER": "mock",
            "DAILY_QUESTION_CAP": "25",
            "SESSION_QUESTION_CAP": "10",
        }
    )


@pytest.fixture
def demo_rag() -> RagStore:
    store = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    store.add_chunks(
        chunk_markdown(
            "# Warranty Policy\n\n## Warranty Period\n\nThe residential warranty is 24 months. "
            "Commercial systems have a 12 month warranty.",
            source="warranty-policy.md",
            max_chars=500,
            min_chars=10,
        )
    )
    store.add_chunks(
        chunk_markdown(
            "# Returns Policy\n\n## Return Window\n\nProducts may be returned within 30 days.",
            source="returns-and-refunds-policy.md",
            max_chars=500,
            min_chars=10,
        )
    )
    return store


@pytest.fixture
def registry(demo_database: Path, demo_rag: RagStore, settings: Settings) -> ToolRegistry:
    return ToolRegistry(demo_database, demo_rag, settings)
