from __future__ import annotations

import pytest

from src.sql_validator import SQLValidationError, validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select count(*) from orders;",
        "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
        "SELECT p.name, SUM(oi.line_total) FROM products p JOIN order_items oi USING (product_id) GROUP BY p.name",
        "SELECT 'DELETE; DROP TABLE orders' AS harmless",
        "SELECT 1 /* DROP TABLE orders; */",
        "SELECT 1 -- comment with DELETE\n",
        "SELECT \"drop\" FROM products",
        "SELECT `select` FROM products",
        "SELECT [delete] FROM products",
        "SELECT 1 WHERE 1 = 1 -- ; DROP TABLE orders",
        "SELECT 1 WHERE 1 = 1 /* ; DROP TABLE orders */",
    ],
)
def test_valid_select_queries(sql: str) -> None:
    assert validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "INSERT INTO orders VALUES (1)",
        "UPDATE orders SET status = 'completed'",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN x TEXT",
        "PRAGMA table_info(orders)",
        "ATTACH DATABASE 'x.db' AS x",
        "SELECT 1; SELECT 2",
        "SELECT 1;;",
        "SELECT * FROM sqlite_master",
        "SELECT load_extension('evil')",
        "SELECT readfile('/etc/passwd')",
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
        "EXPLAIN SELECT 1",
        "SELECT 'unterminated",
        "SELECT 1 /* unterminated",
        "SELECT 1 WHERE 1 = 1; DROP TABLE orders",
        "SELECT " + "1, " * 3000 + "1",
        "SELECT 1\x00",
    ],
)
def test_invalid_or_unsafe_sql(sql: str) -> None:
    with pytest.raises(SQLValidationError):
        validate_sql(sql)


def test_comments_and_strings_are_stripped_before_keyword_checks() -> None:
    assert validate_sql("SELECT 'insert update delete' AS words") == "SELECT 'insert update delete' AS words"
    assert validate_sql("SELECT 1 -- harmless") == "SELECT 1"
    with pytest.raises(SQLValidationError):
        validate_sql("SELECT 1 /* harmless */; DELETE FROM orders")
