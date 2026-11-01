from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from src.chunking import chunk_markdown
from src.embeddings import DeterministicEmbedder
from src.periods import resolve_period
from src.rag import RagStore
from src.tools import ToolRegistry


def _scalar(database: Path, sql: str, params: tuple[object, ...] = ()) -> object:
    connection = sqlite3.connect(database)
    try:
        return connection.execute(sql, params).fetchone()[0]
    finally:
        connection.close()


def test_run_sql_query_reads_and_reports_columns(registry: ToolRegistry) -> None:
    result = registry.execute("run_sql_query", {"sql": "SELECT COUNT(*) AS n FROM orders"})
    assert result.ok
    assert result.result["columns"] == ["n"]
    assert result.result["rows"][0][0] == 100
    assert result.result["truncated"] is False
    assert json.loads(result.as_json())["ok"] is True


def test_run_sql_query_enforces_row_limit(demo_database: Path, demo_rag: RagStore, settings) -> None:
    limited_settings = replace(settings, sql_row_limit=5)
    limited = ToolRegistry(demo_database, demo_rag, limited_settings)
    result = limited.execute("run_sql_query", {"sql": "SELECT order_id FROM orders ORDER BY order_id"})
    assert result.ok
    assert result.result["row_count"] == 5
    assert result.result["truncated"] is True


def test_run_sql_query_rejects_writes_and_bad_arguments(registry: ToolRegistry) -> None:
    write = registry.execute("run_sql_query", {"sql": "DELETE FROM orders"})
    assert not write.ok
    assert "SELECT" in (write.error or "")
    multiple = registry.execute("run_sql_query", {"sql": "SELECT 1; SELECT 2"})
    assert not multiple.ok
    missing = registry.execute("run_sql_query", {})
    assert not missing.ok
    unknown = registry.execute("not_a_tool", {})
    assert not unknown.ok
    assert "Unknown tool" in (unknown.error or "")


def test_get_low_stock_items(registry: ToolRegistry) -> None:
    result = registry.execute("get_low_stock_items", {"limit": 5})
    assert result.ok
    assert result.result["count"] >= 1
    assert len(result.result["items"]) <= 5
    assert all(item["quantity_on_hand"] <= item["reorder_point"] for item in result.result["items"])
    assert all(item["shortfall"] >= 0 for item in result.result["items"])
    zero = registry.execute("get_low_stock_items", {"threshold": 0, "limit": 100})
    assert zero.ok
    assert all(item["quantity_on_hand"] == 0 for item in zero.result["items"])


def test_sales_summary_matches_direct_sql(demo_database: Path, registry: ToolRegistry) -> None:
    as_of = date(2026, 11, 1)
    for period_name in ("last_7_days", "last_30_days", "last_90_days", "last_12_months", "this_month", "last_month", "ytd"):
        period = resolve_period(period_name, as_of)
        assert period.start is not None
        direct = _scalar(
            demo_database,
            "SELECT COALESCE(SUM(total), 0) FROM orders WHERE order_date BETWEEN ? AND ? "
            "AND status IN ('completed', 'shipped')",
            (period.start.isoformat(), period.end.isoformat()),
        )
        result = registry.execute("get_sales_summary", {"period": period_name})
        assert result.ok, result.error
        assert result.result["revenue"] == round(float(direct), 2)
        assert result.result["start"] == period.start.isoformat()
        assert result.result["end"] == period.end.isoformat()


def test_sales_summary_month_and_invalid_period(registry: ToolRegistry) -> None:
    month = registry.execute("get_sales_summary", {"period": "2026-09"})
    assert month.ok
    assert month.result["start"] == "2026-09-01"
    invalid = registry.execute("get_sales_summary", {"period": "yesterday"})
    assert not invalid.ok
    assert "Invalid period" in (invalid.error or "")


def test_search_documents_and_session_uploads(demo_database: Path, demo_rag: RagStore, settings) -> None:
    registry = ToolRegistry(demo_database, demo_rag, settings)
    result = registry.execute("search_documents", {"query": "residential warranty", "top_k": 2})
    assert result.ok
    assert result.result["results"]
    assert result.result["results"][0]["source"] == "warranty-policy.md"
    assert result.result["results"][0]["section"]

    session = RagStore.ephemeral(DeterministicEmbedder(), collection_name=f"test_{uuid4().hex}")
    session.add_chunks(
        chunk_markdown(
            "# Local Policy\n\n## Local Warranty\n\nThe local demo warranty is 36 months.",
            source="local-policy.md",
            max_chars=400,
        ),
        uploaded=True,
    )
    with_session = registry.with_session(session)
    uploaded = with_session.execute("search_documents", {"query": "local warranty 36 months", "top_k": 3})
    assert uploaded.ok
    assert any(item["uploaded"] for item in uploaded.result["results"])
    empty = registry.execute("search_documents", {"query": ""})
    assert not empty.ok
