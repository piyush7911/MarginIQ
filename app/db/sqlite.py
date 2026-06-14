import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.core.config import DATABASE_PATH


def initialize_database() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS promotion_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product TEXT NOT NULL,
                category TEXT NOT NULL,
                discount INTEGER NOT NULL,
                timing TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                confidence REAL NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH)
    try:
        yield connection
    finally:
        connection.close()


def save_run(
    product: str,
    category: str,
    discount: int,
    timing: str,
    recommendation: str,
    confidence: float,
    payload: dict,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO promotion_runs (
                product, category, discount, timing,
                recommendation, confidence, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product,
                category,
                discount,
                timing,
                recommendation,
                confidence,
                json.dumps(payload),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
