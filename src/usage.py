from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class UsageLimitError(RuntimeError):
    pass


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class UsageTracker:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS question_usage (
                    day TEXT PRIMARY KEY,
                    count INTEGER NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def daily_count(self, day: str | None = None) -> int:
        day = day or _today()
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT count FROM question_usage WHERE day = ?",
                (day,),
            ).fetchone()
        finally:
            connection.close()
        return int(row[0]) if row else 0

    def check_and_increment(self, cap: int, day: str | None = None) -> int:
        if cap < 1:
            raise ValueError("cap must be at least 1")
        day = day or _today()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT count FROM question_usage WHERE day = ?",
                (day,),
            ).fetchone()
            current = int(row[0]) if row else 0
            if current >= cap:
                connection.rollback()
                raise UsageLimitError(
                    f"The daily question limit ({cap}) has been reached. Please try again tomorrow."
                )
            next_count = current + 1
            connection.execute(
                """
                INSERT INTO question_usage (day, count) VALUES (?, ?)
                ON CONFLICT(day) DO UPDATE SET count = excluded.count
                """,
                (day, next_count),
            )
            connection.commit()
            return next_count
        finally:
            connection.close()
