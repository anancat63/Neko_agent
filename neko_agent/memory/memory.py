from __future__ import annotations

from pathlib import Path
from typing import Any

from .sqlite_store import SQLiteMemoryStore


class Memory:
    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.store = SQLiteMemoryStore(str(self.memory_dir))
        self._bootstrap_defaults()

    def _bootstrap_defaults(self) -> None:
        if self.store.recent(limit=1):
            return
        self.add_memory(
            path="bootstrap/project-overview",
            title="Project Overview",
            content=(
                "Claw Agent is a provider-agnostic Python agent framework with tool calling, "
                "sub-agents, coordinator orchestration, MCP integration, and auto-compact support."
            ),
        )
        self.add_memory(
            path="bootstrap/memory-module",
            title="Memory Module",
            content=(
                "This project currently uses a minimal SQLite-backed memory implementation. "
                "Relevant notes are retrieved with simple LIKE search and injected into context."
            ),
        )

    def build_prompt(self) -> str:
        recent = self.store.recent(limit=3)
        if not recent:
            return "Persistent memory is enabled."
        bullets = "\n".join(f"- {row.title}" for row in recent)
        return (
            "Persistent memory is enabled. You may use recalled notes when they are relevant.\n"
            "Recent memory topics:\n"
            f"{bullets}"
        )

    async def find_relevant(self, query: str, provider: Any = None, model: str = "") -> list[dict[str, Any]]:
        rows = self.store.search(query=query, limit=5)
        return [{"path": row.path, "title": row.title} for row in rows]

    def load_memory_content(self, path: str) -> str:
        row = self.store.get(path)
        if not row:
            return "(memory not found)"
        return f"# {row.title}\n\n{row.content}"

    def add_memory(self, path: str, title: str, content: str) -> None:
        self.store.upsert(path=path, title=title, content=content)
