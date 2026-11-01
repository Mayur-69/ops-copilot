from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from src.bootstrap import ensure_index
from src.config import Settings, load_settings
from src.tools import ToolRegistry

SERVER_INSTRUCTIONS = """Ops Copilot exposes read-only tools for the AquaPure operations database and company documents.

Use search_documents for policies, warranties, returns, installation, maintenance, shipping, dealer, troubleshooting, and product-manual questions. Use get_sales_summary, get_low_stock_items, or run_sql_query for data questions. Revenue is SUM(orders.total) for completed or shipped orders. Relative dates must use the data as-of date returned by the tools, never the wall clock. Never attempt writes or DDL."""


def _execute(registry: ToolRegistry, name: str, arguments: dict[str, Any]) -> str:
    result = registry.execute(name, arguments)
    return result.as_json()


def build_server(registry: ToolRegistry) -> MCPServer:
    server = MCPServer(
        name="ops-copilot",
        title="Ops Copilot",
        version="1.0.0",
        instructions=SERVER_INSTRUCTIONS,
    )

    @server.tool(description="Search AquaPure policy, warranty, returns, shipping, dealer, and product documents.")
    def search_documents(query: str, top_k: int = 5) -> str:
        return _execute(registry, "search_documents", {"query": query, "top_k": top_k})

    @server.tool(description="Summarize revenue, orders, units, average order value, top products, and monthly trend.")
    def get_sales_summary(period: str = "last_30_days") -> str:
        return _execute(registry, "get_sales_summary", {"period": period})

    @server.tool(description="List products at or below their reorder point, with suggested reorder quantities.")
    def get_low_stock_items(threshold: int | None = None, limit: int = 20) -> str:
        arguments: dict[str, Any] = {"limit": limit}
        if threshold is not None:
            arguments["threshold"] = threshold
        return _execute(registry, "get_low_stock_items", arguments)

    @server.tool(description="Run one read-only SELECT or WITH ... SELECT query against the AquaPure SQLite database.")
    def run_sql_query(sql: str) -> str:
        return _execute(registry, "run_sql_query", {"sql": sql})

    return server


def create_registry(settings: Settings | None = None) -> ToolRegistry:
    settings = settings or load_settings()
    index = ensure_index(settings)
    return ToolRegistry(settings.database_path, index.rag, settings)


def main() -> None:
    build_server(create_registry()).run("stdio")


if __name__ == "__main__":
    main()
