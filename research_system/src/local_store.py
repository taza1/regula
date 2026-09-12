"""Small SQLite-backed state store for local development.

The production design targets Cosmos DB.  This adapter gives the API durable,
tenant-scoped behavior locally without pretending that it provides Cosmos DB's
distributed transactions or production authorization guarantees.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional


class LocalStateStore:
    """Persist versioned Pydantic payloads in a tenant/project-scoped SQLite DB."""

    def __init__(self, database_path: str):
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    kind TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (kind, tenant_id, project_id, entity_id)
                )
                """
            )

    def put(
        self,
        kind: str,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            if kind == "source_snapshot":
                connection.execute(
                    "INSERT OR IGNORE INTO entities "
                    "(kind, tenant_id, project_id, entity_id, payload) VALUES (?, ?, ?, ?, ?)",
                    (kind, tenant_id, project_id, entity_id, serialized),
                )
                existing = json.loads(connection.execute(
                    "SELECT payload FROM entities WHERE kind=? AND tenant_id=? AND project_id=? AND entity_id=?",
                    (kind, tenant_id, project_id, entity_id),
                ).fetchone()["payload"])
                # A retry preserves the first retrieval timestamp and all stored bytes.
                def comparable(value: Any) -> Any:
                    if isinstance(value, dict):
                        return {key: comparable(item) for key, item in value.items()
                                if key not in {"created_at", "retrieved_at"}}
                    if isinstance(value, list):
                        return [comparable(item) for item in value]
                    return value
                if comparable(existing) != comparable(payload):
                    changed = sorted(key for key in set(existing) | set(payload)
                                     if comparable(existing.get(key)) != comparable(payload.get(key)))
                    raise ValueError(f"Immutable snapshot conflict: {', '.join(changed)}")
                return
            connection.execute(
                """
                INSERT INTO entities (kind, tenant_id, project_id, entity_id, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kind, tenant_id, project_id, entity_id)
                DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (kind, tenant_id, project_id, entity_id, serialized),
            )

    def get(
        self,
        kind: str,
        tenant_id: str,
        project_id: str,
        entity_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM entities
                WHERE kind = ? AND tenant_id = ? AND project_id = ? AND entity_id = ?
                """,
                (kind, tenant_id, project_id, entity_id),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list(
        self,
        kind: str,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM entities
                WHERE kind = ? AND tenant_id = ? AND project_id = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (kind, tenant_id, project_id, limit, offset),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]
