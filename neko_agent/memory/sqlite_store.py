from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MemoryRow:
    path: str
    title: str
    content: str


class SQLiteMemoryStore:
    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.memory_dir / "memory.db"
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_updated_at
                ON memories(updated_at DESC)
                """
            )
            conn.commit()

    def upsert(self, path: str, title: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(path, title, content)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (path, title, content),
            )
            conn.commit()

    def get(self, path: str) -> MemoryRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path, title, content FROM memories WHERE path = ?",
                (path,),
            ).fetchone()
        if not row:
            return None
        return MemoryRow(path=row["path"], title=row["title"], content=row["content"])

    def search(self, query: str, limit: int = 5) -> list[MemoryRow]:
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT path, title, content
                FROM memories
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
        return [MemoryRow(path=row["path"], title=row["title"], content=row["content"]) for row in rows]

    def recent(self, limit: int = 10) -> list[MemoryRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT path, title, content
                FROM memories
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [MemoryRow(path=row["path"], title=row["title"], content=row["content"]) for row in rows]
