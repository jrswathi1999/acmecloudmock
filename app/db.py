"""SQLite storage for products, orders and the revenue rollup."""
import sqlite3
from pathlib import Path

from app import config

PRODUCTS = [
    (1, "Starter", 1900),
    (2, "Team", 4900),
    (3, "Business", 9900),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    qty INTEGER NOT NULL,
    currency TEXT,
    amount_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue_daily (
    day TEXT NOT NULL,
    region TEXT NOT NULL,
    revenue_cents INTEGER NOT NULL,
    orders INTEGER NOT NULL,
    PRIMARY KEY (day, region)
);
"""


def connect() -> sqlite3.Connection:
    path = Path(config.db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Create tables and seed products. Runs on every server startup."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO products (id, name, price_cents) VALUES (?, ?, ?)",
            PRODUCTS,
        )
        conn.commit()
    finally:
        conn.close()
