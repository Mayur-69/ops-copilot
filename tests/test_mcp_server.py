from __future__ import annotations

import asyncio
import json

from mcp_server import build_server


def _call(server, name: str, arguments: dict):
    result = asyncio.run(server.call_tool(name, arguments))
    payload = json.loads(result.content[0].text)
    return payload


def test_mcp_tools_are_registered_and_read_only(registry) -> None:
    server = build_server(registry)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {"search_documents", "get_sales_summary", "get_low_stock_items", "run_sql_query"}

    sql = _call(server, "run_sql_query", {"sql": "SELECT COUNT(*) AS n FROM orders"})
    assert sql["ok"] is True
    assert sql["result"]["rows"][0][0] == 100

    blocked = _call(server, "run_sql_query", {"sql": "DELETE FROM orders"})
    assert blocked["ok"] is False


def test_mcp_data_and_document_tools(registry) -> None:
    server = build_server(registry)
    sales = _call(server, "get_sales_summary", {"period": "last_30_days"})
    assert sales["ok"] is True
    assert "revenue" in sales["result"]

    stock = _call(server, "get_low_stock_items", {"limit": 2})
    assert stock["ok"] is True
    assert len(stock["result"]["items"]) <= 2

    docs = _call(server, "search_documents", {"query": "warranty", "top_k": 2})
    assert docs["ok"] is True
    assert docs["result"]["results"]
