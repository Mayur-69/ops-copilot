from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.config import Settings
from src.db import SCHEMA_DESCRIPTION, connect_readonly, read_meta
from src.periods import PERIOD_CHOICES, PeriodError, resolve_period
from src.rag import RagStore, merge_results
from src.sql_validator import SQLValidationError, validate_sql


@dataclass
class ToolResult:
    name: str
    arguments: dict[str, Any]
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }

    def as_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)


class ToolExecutionError(RuntimeError):
    pass


def _safe_cell(value: Any, max_chars: int = 2000) -> Any:
    if isinstance(value, bytes):
        return value[:200].hex()
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + "...[truncated]"
    return value


@dataclass
class ToolRegistry:
    database_path: Path
    rag_store: RagStore
    settings: Settings
    session_rag: RagStore | None = None
    data_as_of: str = field(init=False)
    _meta: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.database_path = Path(self.database_path)
        self._meta = read_meta(self.database_path)
        self.data_as_of = self._meta.get("data_as_of", "")

    def with_session(self, session_rag: RagStore | None) -> ToolRegistry:
        return ToolRegistry(
            database_path=self.database_path,
            rag_store=self.rag_store,
            settings=self.settings,
            session_rag=session_rag,
        )

    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "run_sql_query",
                "description": (
                    "Run one read-only SELECT query against the AquaPure SQLite database and return "
                    f"at most {self.settings.sql_row_limit} rows. Only SELECT or WITH ... SELECT is "
                    "allowed. Use this for custom analysis, counts, rankings, joins, and date ranges. "
                    "For relative dates, use the data as-of date "
                    f"{self.data_as_of} from meta where key = 'data_as_of'. Revenue is "
                    "SUM(orders.total) for status completed or shipped.\n\n"
                    + SCHEMA_DESCRIPTION
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"sql": {"type": "string", "description": "A single SELECT query."}},
                    "required": ["sql"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_low_stock_items",
                "description": (
                    "List inventory rows where quantity_on_hand is at or below the reorder point, "
                    "including warehouse, lead time, and suggested reorder quantity. Optionally "
                    "provide a numeric threshold to use instead of each row's reorder point."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "threshold": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Optional stock threshold; omit to use each row's reorder point.",
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_sales_summary",
                "description": (
                    "Summarize revenue, orders, units, average order value, top products, and monthly "
                    "trend for a standard period. Revenue excludes cancelled and returned orders. "
                    "Valid periods: "
                    + ", ".join(PERIOD_CHOICES)
                    + ", or a calendar month such as 2026-09."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "description": "A standard period name or YYYY-MM calendar month.",
                        }
                    },
                    "required": ["period"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "search_documents",
                "description": (
                    "Search AquaPure policy documents, product manuals, SOPs, and FAQs. Use this "
                    "before answering any policy, warranty, return, installation, maintenance, "
                    "shipping, dealer, or troubleshooting question. Results include the source file "
                    "and section for citation."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural-language search query."},
                        "top_k": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "default": self.settings.top_k,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        ]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        arguments = arguments or {}
        start = time.perf_counter()
        try:
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object.")
            if name == "run_sql_query":
                result = self._run_sql_query(arguments)
            elif name == "get_low_stock_items":
                result = self._get_low_stock_items(arguments)
            elif name == "get_sales_summary":
                result = self._get_sales_summary(arguments)
            elif name == "search_documents":
                result = self._search_documents(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")
            return ToolResult(
                name=name,
                arguments=arguments,
                ok=True,
                result=result,
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except (SQLValidationError, PeriodError, ToolExecutionError, ValueError, sqlite3.Error) as exc:
            return ToolResult(
                name=name,
                arguments=arguments,
                ok=False,
                error=str(exc),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as exc:
            return ToolResult(
                name=name,
                arguments=arguments,
                ok=False,
                error=f"Tool failed ({type(exc).__name__}).",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

    def _run_sql_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        sql = arguments.get("sql")
        if not isinstance(sql, str):
            raise ValueError("run_sql_query requires a string 'sql' argument.")
        validated = validate_sql(sql)
        limit = self.settings.sql_row_limit
        connection = connect_readonly(self.database_path, timeout=self.settings.sql_timeout_seconds)
        deadline = time.monotonic() + self.settings.sql_timeout_seconds
        try:
            connection.set_progress_handler(
                lambda: 1 if time.monotonic() > deadline else 0,
                10000,
            )
            wrapped = f"SELECT * FROM (\n{validated}\n) LIMIT {limit + 1}"
            try:
                cursor = connection.execute(wrapped)
                rows = cursor.fetchall()
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise ToolExecutionError("SQL query timed out.") from exc
                raise
            columns = [description[0] for description in cursor.description or []]
            truncated = len(rows) > limit
            rows = rows[:limit]
            return {
                "columns": columns,
                "rows": [[_safe_cell(value) for value in row] for row in rows],
                "row_count": len(rows),
                "truncated": truncated,
                "row_limit": limit,
                "sql": validated,
            }
        finally:
            connection.set_progress_handler(None, 0)
            connection.close()

    def _get_low_stock_items(self, arguments: dict[str, Any]) -> dict[str, Any]:
        threshold = arguments.get("threshold")
        if threshold is not None and (
            isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0
        ):
            raise ValueError("threshold must be a non-negative integer or omitted.")
        limit = arguments.get("limit", 50)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        connection = connect_readonly(self.database_path)
        try:
            where = "i.quantity_on_hand <= COALESCE(?, i.reorder_point)"
            params: tuple[Any, ...] = (threshold,)
            count = connection.execute(
                f"SELECT COUNT(*) FROM inventory i WHERE {where}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT p.product_id, p.sku, p.name, p.category, i.warehouse,
                       i.quantity_on_hand, i.reorder_point, i.lead_time_days,
                       i.last_restock_date,
                       MAX(i.reorder_point - i.quantity_on_hand, 0) AS shortfall,
                       MAX(i.reorder_point * 2 - i.quantity_on_hand, 0) AS suggested_reorder_quantity
                FROM inventory i
                JOIN products p ON p.product_id = i.product_id
                WHERE {where}
                ORDER BY shortfall DESC, p.name, i.warehouse
                LIMIT ?
                """,
                params + (limit,),
            ).fetchall()
            return {
                "as_of": self.data_as_of,
                "count": int(count),
                "items": [dict(row) for row in rows],
            }
        finally:
            connection.close()

    def _get_sales_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        period_value = arguments.get("period")
        if not isinstance(period_value, str) or not period_value.strip():
            raise ValueError("get_sales_summary requires a string 'period' argument.")
        as_of = date.fromisoformat(self.data_as_of)
        period = resolve_period(period_value, as_of)
        connection = connect_readonly(self.database_path)
        try:
            start = period.start
            if start is None:
                row = connection.execute("SELECT MIN(order_date) FROM orders").fetchone()
                start = date.fromisoformat(row[0]) if row and row[0] else as_of
            start_text = start.isoformat()
            end_text = period.end.isoformat()
            summary = connection.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN status IN ('completed', 'shipped') THEN total ELSE 0 END), 0) AS revenue,
                       COUNT(*) AS orders,
                       COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_orders,
                       COALESCE(SUM(CASE WHEN status = 'shipped' THEN 1 ELSE 0 END), 0) AS shipped_orders,
                       COALESCE(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END), 0) AS returned_orders,
                       COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled_orders
                FROM orders
                WHERE order_date BETWEEN ? AND ?
                """,
                (start_text, end_text),
            ).fetchone()
            revenue_orders = int(summary["completed_orders"] + summary["shipped_orders"])
            units = connection.execute(
                """
                SELECT COALESCE(SUM(oi.quantity), 0)
                FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                WHERE o.order_date BETWEEN ? AND ?
                  AND o.status IN ('completed', 'shipped')
                """,
                (start_text, end_text),
            ).fetchone()[0]
            top_rows = connection.execute(
                """
                SELECT p.product_id, p.sku, p.name, p.category,
                       ROUND(SUM(oi.line_total), 2) AS revenue,
                       SUM(oi.quantity) AS units
                FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                JOIN products p ON p.product_id = oi.product_id
                WHERE o.order_date BETWEEN ? AND ?
                  AND o.status IN ('completed', 'shipped')
                GROUP BY p.product_id, p.sku, p.name, p.category
                ORDER BY revenue DESC
                LIMIT 5
                """,
                (start_text, end_text),
            ).fetchall()
            monthly_start = (as_of - timedelta(days=364)).isoformat()
            monthly = connection.execute(
                """
                SELECT substr(order_date, 1, 7) AS month,
                       COUNT(*) AS orders,
                       ROUND(SUM(total), 2) AS revenue
                FROM orders
                WHERE order_date BETWEEN ? AND ?
                  AND status IN ('completed', 'shipped')
                GROUP BY substr(order_date, 1, 7)
                ORDER BY month
                """,
                (monthly_start, as_of.isoformat()),
            ).fetchall()
            revenue = round(float(summary["revenue"]), 2)
            return {
                "period": period.label,
                "start": start_text,
                "end": end_text,
                "data_as_of": self.data_as_of,
                "revenue": revenue,
                "orders": int(summary["orders"]),
                "revenue_orders": revenue_orders,
                "completed_orders": int(summary["completed_orders"]),
                "shipped_orders": int(summary["shipped_orders"]),
                "returned_orders": int(summary["returned_orders"]),
                "cancelled_orders": int(summary["cancelled_orders"]),
                "units_sold": int(units),
                "average_order_value": round(revenue / revenue_orders, 2) if revenue_orders else 0.0,
                "top_products": [dict(row) for row in top_rows],
                "monthly": [dict(row) for row in monthly],
            }
        finally:
            connection.close()

    def _search_documents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search_documents requires a non-empty string 'query' argument.")
        if len(query) > 1000:
            raise ValueError("search query must be 1000 characters or fewer.")
        top_k = arguments.get("top_k", self.settings.top_k)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
            raise ValueError("top_k must be an integer between 1 and 10.")
        persistent = self.rag_store.query(
            query,
            top_k=top_k,
            min_score=self.settings.min_score,
        )
        session = (
            self.session_rag.query(query, top_k=top_k, min_score=self.settings.min_score)
            if self.session_rag
            else None
        )
        merged = merge_results(persistent, session, top_k=top_k)
        results = [
            {
                "source": item.source,
                "section": item.section,
                "score": round(item.score, 4),
                "text": item.text[:1400],
                "uploaded": item.uploaded,
            }
            for item in merged
        ]
        return {
            "query": query,
            "count": len(results),
            "results": results,
            "message": None if results else "No relevant documents found.",
        }
