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
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                    title, passage, authors, doi, url,
                    tenant_id UNINDEXED, project_id UNINDEXED,
                    run_id UNINDEXED, entity_id UNINDEXED,
                    tokenize = 'porter unicode61'
                )
                """
            )
            self._backfill_evidence_fts(connection)

    @staticmethod
    def _index_evidence(
        connection: sqlite3.Connection,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            DELETE FROM evidence_fts
            WHERE tenant_id = ? AND project_id = ? AND entity_id = ?
            """,
            (tenant_id, project_id, entity_id),
        )
        connection.execute(
            """
            INSERT INTO evidence_fts (
                title, passage, authors, doi, url,
                tenant_id, project_id, run_id, entity_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("title") or "",
                payload.get("passage") or "",
                " ".join(payload.get("authors") or []),
                payload.get("doi") or "",
                payload.get("url") or "",
                tenant_id,
                project_id,
                payload.get("run_id") or "",
                entity_id,
            ),
        )

    def _backfill_evidence_fts(self, connection: sqlite3.Connection) -> None:
        """Index evidence written before the FTS table existed."""

        rows = connection.execute(
            """
            SELECT tenant_id, project_id, entity_id, payload FROM entities
            WHERE kind = 'evidence' AND NOT EXISTS (
                SELECT 1 FROM evidence_fts f
                WHERE f.tenant_id = entities.tenant_id
                  AND f.project_id = entities.project_id
                  AND f.entity_id = entities.entity_id
            )
            """
        ).fetchall()
        for row in rows:
            self._index_evidence(
                connection,
                row["tenant_id"],
                row["project_id"],
                row["entity_id"],
                json.loads(row["payload"]),
            )

    def search_evidence_fts(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        match_query: str,
        limit: int = 100,
    ) -> list[tuple[str, float]]:
        """Return (evidence_id, bm25) pairs, best match first.

        FTS5 ``bm25()`` is lower for better matches, so the score is negated:
        callers see larger-is-better. Title is weighted above passage, and
        passage above authors, DOI and URL.
        """

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT entity_id, -bm25(evidence_fts, 5.0, 1.0, 2.0, 1.0, 0.5) AS score
                FROM evidence_fts
                WHERE evidence_fts MATCH ?
                  AND tenant_id = ? AND project_id = ? AND run_id = ?
                ORDER BY score DESC
                LIMIT ?
                """,
                (match_query, tenant_id, project_id, run_id, limit),
            ).fetchall()
        return [(row["entity_id"], float(row["score"])) for row in rows]

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
            connection.execute(
                """
                INSERT INTO entities (kind, tenant_id, project_id, entity_id, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kind, tenant_id, project_id, entity_id)
                DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
                """,
                (kind, tenant_id, project_id, entity_id, serialized),
            )
            if kind == "evidence":
                self._index_evidence(
                    connection, tenant_id, project_id, entity_id, payload
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
