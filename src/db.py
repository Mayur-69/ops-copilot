from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_DESCRIPTION = """
Tables and columns in the AquaPure operations database:

products(product_id, sku, name, category, model, price, cost, warranty_months, launched_on, is_active)
customers(customer_id, name, email, phone, city, state, segment, created_at)
orders(order_id, order_number, customer_id, order_date, channel, status, payment_method,
       shipping_city, subtotal, discount, shipping_fee, total, created_at)
order_items(order_item_id, order_id, product_id, quantity, unit_price, line_total)
inventory(inventory_id, product_id, warehouse, quantity_on_hand, reorder_point,
          lead_time_days, last_restock_date)
support_tickets(ticket_id, customer_id, order_id, product_id, created_at, category,
                priority, status, subject, description, resolved_at, resolution_days, csat)
meta(key, value)

Notes:
- order_date is an ISO date (YYYY-MM-DD). created_at is an ISO timestamp.
- orders.status is one of processing, shipped, completed, cancelled, returned.
- Revenue means SUM(orders.total) for orders with status completed or shipped.
- support_tickets.category is one of installation, defect, return, filter_replacement, billing, other.
- The demo data's as-of date is stored in meta where key = 'data_as_of'.
- Use that meta value for relative date calculations instead of the wall clock.
- Joins should use the integer IDs (order_id, product_id, customer_id).
""".strip()


def read_meta(database_path: str | Path) -> dict[str, str]:
    connection = connect_readonly(database_path)
    try:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}
    finally:
        connection.close()


def data_as_of(database_path: str | Path) -> str:
    meta = read_meta(database_path)
    return meta.get("data_as_of", "")


def connect_readonly(database_path: str | Path, timeout: float = 5.0) -> sqlite3.Connection:
    path = Path(database_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 2000")
    return connection
