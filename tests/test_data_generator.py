from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from scripts.generate_data import DEFAULT_AS_OF, build_database

TABLES = {
    "products",
    "customers",
    "orders",
    "order_items",
    "inventory",
    "support_tickets",
    "meta",
}


def _rows(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        connection.close()


def _count(path: Path, table: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def test_build_database_small_and_consistent(tmp_path: Path) -> None:
    database = tmp_path / "ops.db"
    summary = build_database(
        database,
        as_of=DEFAULT_AS_OF,
        seed=7,
        order_count=120,
        customer_count=40,
        ticket_count=40,
    )

    assert summary["orders"] == 120
    assert summary["customers"] == 40
    assert summary["products"] == 40
    assert summary["tickets"] == 40
    assert summary["low_stock_rows"] >= 3

    connection = sqlite3.connect(database)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= TABLES
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM orders WHERE total < 0").fetchone()[0] == 0
        mismatch = connection.execute(
            """
            SELECT COUNT(*)
            FROM orders o
            WHERE ABS(o.subtotal - COALESCE((
                SELECT SUM(line_total) FROM order_items oi WHERE oi.order_id = o.order_id
            ), 0)) > 0.01
            """
        ).fetchone()[0]
        assert mismatch == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o USING (order_id) WHERE o.order_id IS NULL"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM orders WHERE order_date < '2025-11-02' OR order_date > '2026-11-01'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE category NOT IN "
            "('installation','defect','return','filter_replacement','billing','other')"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_generator_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    kwargs = {
        "as_of": date(2026, 11, 1),
        "seed": 42,
        "order_count": 80,
        "customer_count": 25,
        "ticket_count": 20,
    }
    build_database(first, **kwargs)
    build_database(second, **kwargs)

    for table in ("products", "customers", "orders", "order_items", "inventory", "support_tickets", "meta"):
        assert _rows(first, table) == _rows(second, table), table


def test_committed_database_meets_demo_requirements() -> None:
    root = Path(__file__).resolve().parents[1]
    database = root / "data" / "ops_copilot.db"
    assert database.exists()
    assert _count(database, "products") == 40
    assert _count(database, "orders") == 5000
    assert _count(database, "support_tickets") >= 500
    assert _count(database, "inventory") == 120

    connection = sqlite3.connect(database)
    try:
        meta = dict(connection.execute("SELECT key, value FROM meta"))
        assert meta["data_as_of"] == "2026-11-01"
        assert meta["seed"] == "42"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        low_stock = connection.execute(
            "SELECT COUNT(*) FROM inventory WHERE quantity_on_hand <= reorder_point"
        ).fetchone()[0]
        assert low_stock >= 8
        date_span = connection.execute(
            "SELECT CAST(julianday(MAX(order_date)) - julianday(MIN(order_date)) AS INTEGER) FROM orders"
        ).fetchone()[0]
        assert date_span >= 360
    finally:
        connection.close()


def test_document_set_is_complete_and_structured() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = sorted((root / "data" / "docs").glob("*.md"))
    assert 10 <= len(docs) <= 15
    for document in docs:
        text = document.read_text(encoding="utf-8")
        assert text.startswith("# "), document.name
        assert text.count("\n## ") >= 2, document.name
        assert len(text) > 1000, document.name
