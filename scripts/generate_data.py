from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_AS_OF = date(2026, 11, 1)
DEFAULT_SEED = 42
SCHEMA_VERSION = "1.0"

WAREHOUSES: list[tuple[str, float]] = [
    ("Mumbai", 0.45),
    ("Delhi", 0.30),
    ("Bengaluru", 0.25),
]

CITIES: list[tuple[str, str]] = [
    ("Mumbai", "Maharashtra"),
    ("Pune", "Maharashtra"),
    ("Nagpur", "Maharashtra"),
    ("Delhi", "Delhi"),
    ("Noida", "Uttar Pradesh"),
    ("Lucknow", "Uttar Pradesh"),
    ("Kanpur", "Uttar Pradesh"),
    ("Bengaluru", "Karnataka"),
    ("Mysuru", "Karnataka"),
    ("Hyderabad", "Telangana"),
    ("Chennai", "Tamil Nadu"),
    ("Coimbatore", "Tamil Nadu"),
    ("Ahmedabad", "Gujarat"),
    ("Surat", "Gujarat"),
    ("Jaipur", "Rajasthan"),
    ("Kolkata", "West Bengal"),
    ("Indore", "Madhya Pradesh"),
    ("Bhopal", "Madhya Pradesh"),
    ("Chandigarh", "Chandigarh"),
    ("Kochi", "Kerala"),
]

FIRST_NAMES = [
    "Aarav",
    "Aditi",
    "Aisha",
    "Ananya",
    "Arjun",
    "Deepa",
    "Dhruv",
    "Diya",
    "Farhan",
    "Gaurav",
    "Ishaan",
    "Isha",
    "Kabir",
    "Kavya",
    "Meera",
    "Mohit",
    "Naina",
    "Nikhil",
    "Pooja",
    "Rahul",
    "Riya",
    "Rohan",
    "Saanvi",
    "Sahil",
    "Sara",
    "Shreya",
    "Siddharth",
    "Tara",
    "Varun",
    "Zoya",
]

LAST_NAMES = [
    "Agarwal",
    "Bansal",
    "Bhat",
    "Chandra",
    "Desai",
    "Gupta",
    "Iyer",
    "Jain",
    "Kapoor",
    "Khan",
    "Kulkarni",
    "Malhotra",
    "Mehta",
    "Menon",
    "Nair",
    "Patel",
    "Rao",
    "Reddy",
    "Sethi",
    "Sharma",
    "Singh",
    "Sinha",
    "Verma",
    "Vijay",
    "Yadav",
]

COMPANY_SUFFIXES = ["Enterprises", "Traders", "Facilities", "Hospitality", "Industries", "Services"]

PRODUCT_ROWS: list[tuple[str, str, str, str, float, float, int]] = [
    ("AP-RO-500", "AquaPure RO 500", "RO Purifier", "RO-500", 12999, 7200, 24),
    ("AP-RO-750", "AquaPure RO 750", "RO Purifier", "RO-750", 16999, 9400, 24),
    ("AP-RO-1000P", "AquaPure RO 1000 Pro", "RO Purifier", "RO-1000P", 22999, 12800, 24),
    ("AP-UV-300", "AquaPure UV 300", "UV Purifier", "UV-300", 7999, 4300, 24),
    ("AP-UV-500P", "AquaPure UV 500 Plus", "UV Purifier", "UV-500P", 10499, 5800, 24),
    ("AP-GR-20", "AquaPure Gravity 20L", "Gravity Purifier", "GR-20", 3499, 1900, 12),
    ("AP-GR-25S", "AquaPure Gravity 25L Steel", "Gravity Purifier", "GR-25S", 5499, 3100, 12),
    ("AP-WH-2000", "AquaPure Whole-House 2000", "Whole House", "WH-2000", 45999, 28500, 36),
    ("AP-WH-3000", "AquaPure Whole-House 3000", "Whole House", "WH-3000", 59999, 37000, 36),
    ("AP-CRO-2000", "AquaPure Commercial RO 2000", "Commercial", "CRO-2000", 89999, 58000, 12),
    ("AP-CRO-5000", "AquaPure Commercial RO 5000", "Commercial", "CRO-5000", 149999, 96000, 12),
    ("AP-ALK-600", "AquaPure Alkaline RO 600", "RO Purifier", "ALK-600", 19999, 11500, 24),
    ("AP-CU-550", "AquaPure Copper RO 550", "RO Purifier", "CU-550", 18999, 10900, 24),
    ("AP-SRO-800", "AquaPure Smart RO 800", "RO Purifier", "SRO-800", 24999, 14500, 24),
    ("AP-RO-400C", "AquaPure RO 400 Compact", "RO Purifier", "RO-400C", 9999, 5600, 24),
    ("AP-F-SED5", "Sediment Filter 5 Micron", "Filter", "F-SED5", 299, 120, 3),
    ("AP-F-CB", "Carbon Block Filter", "Filter", "F-CB", 499, 210, 3),
    ("AP-M-80", "RO Membrane 80 GPD", "Membrane", "M-80", 1899, 950, 6),
    ("AP-M-100", "RO Membrane 100 GPD", "Membrane", "M-100", 2299, 1150, 6),
    ("AP-S-UV11", "UV Lamp 11W", "Spare Part", "S-UV11", 899, 420, 6),
    ("AP-S-UV18", "UV Lamp 18W", "Spare Part", "S-UV18", 1199, 560, 6),
    ("AP-F-PC", "Post Carbon Filter", "Filter", "F-PC", 599, 260, 3),
    ("AP-F-ALK", "Alkaline Filter Cartridge", "Filter", "F-ALK", 1299, 620, 6),
    ("AP-F-CU", "Copper Filter Cartridge", "Filter", "F-CU", 1499, 700, 6),
    ("AP-F-MIN", "Mineral Cartridge", "Filter", "F-MIN", 899, 410, 6),
    ("AP-S-BP100", "Booster Pump 100 GPD", "Spare Part", "S-BP100", 2499, 1350, 12),
    ("AP-S-SV", "Solenoid Valve", "Spare Part", "S-SV", 749, 350, 12),
    ("AP-S-SMPS", "SMPS Adapter 24V", "Spare Part", "S-SMPS", 999, 480, 12),
    ("AP-S-PG", "Pressure Gauge", "Spare Part", "S-PG", 549, 240, 12),
    ("AP-A-TDS", "TDS Meter", "Accessory", "A-TDS", 699, 300, 12),
    ("AP-A-TAP", "Tap Faucet Chrome", "Accessory", "A-TAP", 899, 410, 12),
    ("AP-A-TANK12", "Water Storage Tank 12L", "Accessory", "A-TANK12", 1599, 780, 12),
    ("AP-A-BRKT", "Wall Mounting Bracket", "Accessory", "A-BRKT", 399, 150, 6),
    ("AP-S-HOUS", "Pre-Filter Housing", "Spare Part", "S-HOUS", 1099, 520, 12),
    ("AP-S-FR", "Flow Restrictor", "Spare Part", "S-FR", 349, 120, 6),
    ("AP-S-FV", "Float Valve", "Spare Part", "S-FV", 449, 180, 6),
    ("AP-A-LEAK", "Leak Detector Sensor", "Accessory", "A-LEAK", 1299, 600, 12),
    ("AP-F-WH10", "Whole-House Pre-Filter 10in", "Filter", "F-WH10", 1899, 850, 6),
    ("AP-M-4040", "Commercial Membrane 4040", "Membrane", "M-4040", 8999, 4800, 6),
    ("AP-F-DESC", "Descaling Cartridge", "Filter", "F-DESC", 1599, 720, 6),
]

TICKET_CATEGORIES = [
    ("installation", 28),
    ("defect", 24),
    ("return", 18),
    ("filter_replacement", 12),
    ("billing", 8),
    ("other", 10),
]

CHANNELS = [("website", 45), ("app", 30), ("marketplace", 15), ("dealer", 10)]
PAYMENT_METHODS = [("UPI", 42), ("credit_card", 24), ("net_banking", 14), ("COD", 12), ("EMI", 8)]

MONTH_WEIGHTS = [0.95, 1.05, 0.90, 0.85, 0.95, 1.05, 1.15, 1.25, 1.20, 1.10, 1.00, 1.10]
WEEKDAY_WEIGHTS = [1.00, 1.00, 1.00, 1.00, 1.05, 1.12, 1.06]

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    model TEXT NOT NULL,
    price REAL NOT NULL CHECK (price > 0),
    cost REAL NOT NULL CHECK (cost >= 0),
    warranty_months INTEGER NOT NULL CHECK (warranty_months > 0),
    launched_on TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    segment TEXT NOT NULL CHECK (segment IN ('B2C', 'B2B')),
    created_at TEXT NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    order_number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'shipped', 'completed', 'cancelled', 'returned')),
    payment_method TEXT NOT NULL,
    shipping_city TEXT NOT NULL,
    subtotal REAL NOT NULL CHECK (subtotal >= 0),
    discount REAL NOT NULL CHECK (discount >= 0),
    shipping_fee REAL NOT NULL CHECK (shipping_fee >= 0),
    total REAL NOT NULL CHECK (total >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    line_total REAL NOT NULL CHECK (line_total > 0)
);

CREATE TABLE inventory (
    inventory_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    warehouse TEXT NOT NULL,
    quantity_on_hand INTEGER NOT NULL CHECK (quantity_on_hand >= 0),
    reorder_point INTEGER NOT NULL CHECK (reorder_point >= 0),
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days > 0),
    last_restock_date TEXT NOT NULL,
    UNIQUE (product_id, warehouse)
);

CREATE TABLE support_tickets (
    ticket_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_id INTEGER REFERENCES orders(order_id),
    product_id INTEGER REFERENCES products(product_id),
    created_at TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('installation', 'defect', 'return', 'filter_replacement', 'billing', 'other')),
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    resolved_at TEXT,
    resolution_days INTEGER,
    csat INTEGER CHECK (csat IS NULL OR csat BETWEEN 1 AND 5)
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_channel ON orders(channel);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE INDEX idx_inventory_product ON inventory(product_id);
CREATE INDEX idx_tickets_created ON support_tickets(created_at);
CREATE INDEX idx_tickets_category ON support_tickets(category);
CREATE INDEX idx_tickets_order ON support_tickets(order_id);
"""


def _weighted_choice(rng: random.Random, choices: list[tuple[str, int]]) -> str:
    population = [item for item, _ in choices]
    weights = [weight for _, weight in choices]
    return rng.choices(population, weights=weights, k=1)[0]


def _build_products(rng: random.Random, as_of: date) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for index, (sku, name, category, model, price, cost, warranty) in enumerate(PRODUCT_ROWS, start=1):
        launched = as_of - timedelta(days=rng.randint(120, 1200))
        products.append(
            {
                "product_id": index,
                "sku": sku,
                "name": name,
                "category": category,
                "model": model,
                "price": float(price),
                "cost": float(cost),
                "warranty_months": warranty,
                "launched_on": launched.isoformat(),
                "is_active": 1,
            }
        )
    return products


def _build_customers(rng: random.Random, as_of: date, count: int) -> list[dict[str, Any]]:
    customers: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        segment = "B2B" if rng.random() < 0.15 else "B2C"
        name = f"{last} {rng.choice(COMPANY_SUFFIXES)}" if segment == "B2B" else f"{first} {last}"
        city, state = rng.choice(CITIES)
        created = as_of - timedelta(days=rng.randint(30, 730))
        customers.append(
            {
                "customer_id": index,
                "name": name,
                "email": f"customer{index:04d}@example.com",
                "phone": f"+91-9{rng.randint(100000000, 999999999)}",
                "city": city,
                "state": state,
                "segment": segment,
                "created_at": created.isoformat(),
            }
        )
    return customers


def _build_dates(rng: random.Random, as_of: date, count: int) -> list[date]:
    start = as_of - timedelta(days=364)
    dates: list[date] = []
    weights: list[float] = []
    for offset in range(365):
        current = start + timedelta(days=offset)
        season = MONTH_WEIGHTS[current.month - 1]
        weekday = WEEKDAY_WEIGHTS[current.weekday()]
        growth = 1.0 + 0.18 * (offset / 364)
        dates.append(current)
        weights.append(season * weekday * growth)
    return rng.choices(dates, weights=weights, k=count)


def _status_for_age(rng: random.Random, age_days: int) -> str:
    if age_days > 45:
        return rng.choices(
            ["completed", "returned", "cancelled"],
            weights=[92, 4, 4],
            k=1,
        )[0]
    if age_days > 14:
        return rng.choices(
            ["completed", "shipped", "processing", "returned", "cancelled"],
            weights=[75, 14, 4, 3, 4],
            k=1,
        )[0]
    return rng.choices(
        ["completed", "shipped", "processing", "returned", "cancelled"],
        weights=[38, 26, 25, 6, 5],
        k=1,
    )[0]


def _build_orders_and_items(
    rng: random.Random,
    as_of: date,
    customers: list[dict[str, Any]],
    products: list[dict[str, Any]],
    order_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    orders: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    order_dates = _build_dates(rng, as_of, order_count)
    purifier_products = [p for p in products if p["category"] in {"RO Purifier", "UV Purifier", "Gravity Purifier", "Whole House", "Commercial"}]
    consumable_products = [p for p in products if p["category"] in {"Filter", "Membrane", "Spare Part", "Accessory"}]

    item_id = 1
    for order_id, order_date in enumerate(order_dates, start=1):
        customer = rng.choice(customers)
        age_days = (as_of - order_date).days
        status = _status_for_age(rng, age_days)
        channel = _weighted_choice(rng, CHANNELS)
        payment = _weighted_choice(rng, PAYMENT_METHODS)
        item_count = rng.choices([1, 2, 3], weights=[70, 22, 8], k=1)[0]
        if customer["segment"] == "B2B":
            item_count = min(3, item_count + 1)
        selected: list[dict[str, Any]] = []
        used: set[int] = set()
        for _ in range(item_count):
            pool = purifier_products if rng.random() < 0.35 else consumable_products
            product = rng.choice(pool)
            if product["product_id"] in used:
                continue
            used.add(product["product_id"])
            selected.append(product)
        if not selected:
            selected = [rng.choice(purifier_products)]

        subtotal = 0.0
        order_items: list[dict[str, Any]] = []
        for product in selected:
            if product["category"] in {"Filter", "Membrane", "Spare Part", "Accessory"}:
                quantity = rng.choices([1, 2, 3, 4], weights=[55, 25, 14, 6], k=1)[0]
            else:
                quantity = 1
            unit_price = round(product["price"] * rng.uniform(0.92, 1.0), 2)
            line_total = round(unit_price * quantity, 2)
            subtotal += line_total
            order_items.append(
                {
                    "order_item_id": item_id,
                    "order_id": order_id,
                    "product_id": product["product_id"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
            )
            item_id += 1
        subtotal = round(subtotal, 2)
        discount_rate = rng.choices([0.0, 0.05, 0.10, 0.15, 0.20], weights=[45, 20, 18, 12, 5], k=1)[0]
        discount = round(subtotal * discount_rate, 2)
        shipping_fee = 0.0 if subtotal >= 15000 else rng.choice([99.0, 149.0, 199.0])
        total = round(subtotal - discount + shipping_fee, 2)
        hour = rng.randint(8, 21)
        minute = rng.randint(0, 59)
        orders.append(
            {
                "order_id": order_id,
                "order_number": f"ORD-{order_date.year}-{order_id:06d}",
                "customer_id": customer["customer_id"],
                "order_date": order_date.isoformat(),
                "channel": channel,
                "status": status,
                "payment_method": payment,
                "shipping_city": customer["city"],
                "subtotal": subtotal,
                "discount": discount,
                "shipping_fee": float(shipping_fee),
                "total": total,
                "created_at": f"{order_date.isoformat()}T{hour:02d}:{minute:02d}:00Z",
            }
        )
        items.extend(order_items)
    return orders, items


def _build_inventory(
    rng: random.Random,
    as_of: date,
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    since = (as_of - timedelta(days=90)).isoformat()
    recent_orders = {
        order["order_id"] for order in orders if order["order_date"] >= since and order["status"] != "cancelled"
    }
    units: dict[int, int] = defaultdict(int)
    for item in items:
        if item["order_id"] in recent_orders:
            units[item["product_id"]] += item["quantity"]

    inventory: list[dict[str, Any]] = []
    inventory_id = 1
    for product in products:
        velocity = units[product["product_id"]] / 90.0
        for warehouse, share in WAREHOUSES:
            lead_time = rng.randint(3, 10)
            reorder_point = max(5, math.ceil(velocity * lead_time * 1.5))
            quantity = max(0, int(velocity * 45 * share) + rng.randint(0, 35))
            inventory.append(
                {
                    "inventory_id": inventory_id,
                    "product_id": product["product_id"],
                    "warehouse": warehouse,
                    "quantity_on_hand": quantity,
                    "reorder_point": reorder_point,
                    "lead_time_days": lead_time,
                    "last_restock_date": (as_of - timedelta(days=rng.randint(1, 60))).isoformat(),
                }
            )
            inventory_id += 1

    low_stock_indices = [0, 5, 11, 17, 23, 29, 35, 41, 47, 53]
    for position, index in enumerate(low_stock_indices):
        row = inventory[index % len(inventory)]
        shortfall = 1 + (position % 5)
        row["quantity_on_hand"] = max(0, row["reorder_point"] - shortfall)
    inventory[5]["quantity_on_hand"] = 0
    inventory[41]["quantity_on_hand"] = 0
    return inventory


def _build_tickets(
    rng: random.Random,
    as_of: date,
    customers: list[dict[str, Any]],
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    items: list[dict[str, Any]],
    ticket_count: int,
) -> list[dict[str, Any]]:
    product_by_id = {product["product_id"]: product for product in products}
    customer_by_id = {customer["customer_id"]: customer for customer in customers}
    first_item_by_order: dict[int, dict[str, Any]] = {}
    for item in items:
        first_item_by_order.setdefault(item["order_id"], item)
    eligible = [order for order in orders if order["status"] in {"completed", "returned", "shipped"}]
    if not eligible:
        eligible = orders

    tickets: list[dict[str, Any]] = []
    for ticket_id in range(1, ticket_count + 1):
        order = rng.choice(eligible)
        order_date = date.fromisoformat(order["order_date"])
        category = _weighted_choice(rng, TICKET_CATEGORIES)
        if category == "installation":
            offset = rng.randint(1, 5)
        elif category == "return":
            offset = rng.randint(1, 20)
        else:
            offset = rng.randint(1, 60)
        created = min(as_of, order_date + timedelta(days=offset))
        item = first_item_by_order.get(order["order_id"])
        product = product_by_id.get(item["product_id"]) if item else rng.choice(products)
        customer = customer_by_id[order["customer_id"]]
        age = (as_of - created).days
        if age <= 7:
            status = rng.choices(["open", "in_progress", "resolved"], weights=[35, 50, 15], k=1)[0]
        else:
            status = rng.choices(["resolved", "closed", "in_progress", "open"], weights=[65, 20, 10, 5], k=1)[0]
        if category in {"defect", "return"}:
            priority = rng.choices(["medium", "high", "urgent"], weights=[45, 40, 15], k=1)[0]
        else:
            priority = rng.choices(["low", "medium", "high"], weights=[30, 55, 15], k=1)[0]

        if category == "installation":
            subject = f"Installation follow-up for {product['name']}"
            description = (
                f"Customer {customer['name']} reported that the installation visit for "
                f"{product['name']} was delayed. Order {order['order_number']} was placed on "
                f"{order['order_date']} and the customer requested a status update."
            )
        elif category == "defect":
            subject = f"Leakage reported on {product['name']}"
            description = (
                f"Customer reported water leakage from {product['name']} (order "
                f"{order['order_number']}). A technician visit has been requested to inspect "
                "the housing, tubing, and inlet connections."
            )
        elif category == "return":
            subject = f"Return request for {product['name']}"
            description = (
                f"Customer raised a return request for {product['name']} from order "
                f"{order['order_number']}. The request is within the return window and needs "
                "pickup scheduling and refund review."
            )
        elif category == "filter_replacement":
            subject = f"Filter replacement guidance for {product['name']}"
            description = (
                f"Customer asked which replacement cartridge is compatible with {product['name']} "
                "and how often the filter should be changed."
            )
        elif category == "billing":
            subject = f"Invoice question for order {order['order_number']}"
            description = (
                f"Customer queried the discount and shipping charge shown on order "
                f"{order['order_number']}. The support team is reviewing the invoice breakdown."
            )
        else:
            subject = f"General enquiry about {product['name']}"
            description = (
                f"Customer contacted support with a general question about {product['name']} "
                f"and order {order['order_number']}."
            )

        resolved_at = None
        resolution_days = None
        csat = None
        if status in {"resolved", "closed"}:
            resolution_days = rng.randint(1, 18)
            resolved = min(as_of, created + timedelta(days=resolution_days))
            resolved_at = f"{resolved.isoformat()}T17:00:00Z"
            csat = rng.choices([3, 4, 5], weights=[15, 45, 40], k=1)[0]
        tickets.append(
            {
                "ticket_id": ticket_id,
                "customer_id": customer["customer_id"],
                "order_id": order["order_id"],
                "product_id": product["product_id"],
                "created_at": f"{created.isoformat()}T10:00:00Z",
                "category": category,
                "priority": priority,
                "status": status,
                "subject": subject,
                "description": description,
                "resolved_at": resolved_at,
                "resolution_days": resolution_days,
                "csat": csat,
            }
        )
    return tickets


def _insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
    connection.executemany(sql, [tuple(row[column] for column in columns) for row in rows])


def build_database(
    output_path: Path,
    *,
    as_of: date = DEFAULT_AS_OF,
    seed: int = DEFAULT_SEED,
    order_count: int = 5000,
    customer_count: int = 1500,
    ticket_count: int = 900,
) -> dict[str, Any]:
    if order_count < 1 or customer_count < 1 or ticket_count < 0:
        raise ValueError("counts must be positive")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    products = _build_products(rng, as_of)
    customers = _build_customers(rng, as_of, customer_count)
    orders, items = _build_orders_and_items(rng, as_of, customers, products, order_count)
    inventory = _build_inventory(rng, as_of, products, orders, items)
    tickets = _build_tickets(rng, as_of, customers, products, orders, items, ticket_count)

    first_order_by_customer: dict[int, date] = {}
    for order in orders:
        customer_id = order["customer_id"]
        order_date = date.fromisoformat(order["order_date"])
        if customer_id not in first_order_by_customer or order_date < first_order_by_customer[customer_id]:
            first_order_by_customer[customer_id] = order_date
    for customer in customers:
        first_order = first_order_by_customer.get(customer["customer_id"])
        if first_order and date.fromisoformat(customer["created_at"]) > first_order:
            customer["created_at"] = (first_order - timedelta(days=1)).isoformat()

    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    connection = sqlite3.connect(temporary_path)
    try:
        connection.executescript(SCHEMA_SQL)
        _insert_rows(connection, "products", products)
        _insert_rows(connection, "customers", customers)
        _insert_rows(connection, "orders", orders)
        _insert_rows(connection, "order_items", items)
        _insert_rows(connection, "inventory", inventory)
        _insert_rows(connection, "support_tickets", tickets)
        meta = {
            "data_as_of": as_of.isoformat(),
            "generated_at": f"{as_of.isoformat()}T00:00:00Z",
            "seed": str(seed),
            "schema_version": SCHEMA_VERSION,
            "order_count": str(len(orders)),
            "product_count": str(len(products)),
            "ticket_count": str(len(tickets)),
        }
        connection.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary_path, output_path)

    summary = {
        "database": str(output_path),
        "as_of": as_of.isoformat(),
        "products": len(products),
        "customers": len(customers),
        "orders": len(orders),
        "order_items": len(items),
        "inventory_rows": len(inventory),
        "tickets": len(tickets),
        "low_stock_rows": sum(1 for row in inventory if row["quantity_on_hand"] <= row["reorder_point"]),
    }
    meta_path = output_path.parent / "meta.json"
    meta_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _read_as_of(data_dir: Path, fallback: date) -> date:
    meta_path = data_dir / "meta.json"
    if not meta_path.exists():
        return fallback
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        return date.fromisoformat(str(payload["as_of"]))
    except (KeyError, ValueError, json.JSONDecodeError):
        return fallback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic Ops Copilot SQLite database.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--orders", type=int, default=5000)
    parser.add_argument("--customers", type=int, default=1500)
    parser.add_argument("--tickets", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--if-missing", action="store_true")
    args = parser.parse_args(argv)

    data_dir = args.out_dir
    database_path = data_dir / "ops_copilot.db"
    if database_path.exists() and not args.force:
        if args.if_missing:
            print(f"Database already exists: {database_path}")
            return 0
        print(f"Database already exists: {database_path}. Use --force to rebuild.")
        return 1
    as_of = args.as_of or _read_as_of(data_dir, date.today())
    summary = build_database(
        database_path,
        as_of=as_of,
        seed=args.seed,
        order_count=args.orders,
        customer_count=args.customers,
        ticket_count=args.tickets,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
