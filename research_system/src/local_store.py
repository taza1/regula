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
        self.fts_enabled = False
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
            try:
                existing_columns = [row[1] for row in connection.execute(
                    "PRAGMA table_info(evidence_fts)"
                ).fetchall()]
                expected_columns = ["tenant_id", "project_id", "run_id", "evidence_id",
                                    "source_use_decision", "eligibility_status", "title",
                                    "passage", "authors", "url", "doi"]
                if existing_columns and existing_columns != expected_columns:
                    connection.execute("DROP TABLE evidence_fts")
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                        tenant_id UNINDEXED, project_id UNINDEXED, run_id UNINDEXED,
                        evidence_id UNINDEXED, source_use_decision UNINDEXED,
                        eligibility_status UNINDEXED, title, passage, authors, url, doi,
                        tokenize='unicode61'
                    )
                    """
                )
                self.fts_enabled = True
                self._rebuild_evidence_fts(connection)
            except sqlite3.OperationalError:
                self.fts_enabled = False

    @staticmethod
    def _index_evidence(connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        connection.execute(
            "DELETE FROM evidence_fts WHERE tenant_id=? AND project_id=? AND evidence_id=?",
            (payload["tenant_id"], payload["project_id"], payload["evidence_id"]),
        )
        connection.execute(
            "INSERT INTO evidence_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (payload["tenant_id"], payload["project_id"], payload["run_id"],
             payload["evidence_id"], payload.get("source_use_decision", "blocked"),
             payload.get("eligibility_status", "ineligible"),
             payload.get("title", ""), payload.get("passage", ""),
             " ".join(payload.get("authors", [])), payload.get("url", ""), payload.get("doi") or ""),
        )

    def _rebuild_evidence_fts(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM evidence_fts")
        rows = connection.execute("SELECT payload FROM entities WHERE kind='evidence'").fetchall()
        for row in rows:
            self._index_evidence(connection, json.loads(row["payload"]))

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
            if kind == "evidence" and self.fts_enabled:
                self._index_evidence(connection, payload)

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

    def search_evidence(
        self, tenant_id: str, project_id: str, run_id: str, terms: list[str], limit: int
    ) -> Optional[list[dict[str, Any]]]:
        """Return BM25-ranked evidence, or None when SQLite lacks FTS5."""
        if not self.fts_enabled or not terms:
            return None
        match_query = " OR ".join(f'"{term}"' for term in terms)
        with self._lock, self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT entities.payload
                    FROM evidence_fts
                    JOIN entities ON entities.kind='evidence'
                      AND entities.tenant_id=evidence_fts.tenant_id
                      AND entities.project_id=evidence_fts.project_id
                      AND entities.entity_id=evidence_fts.evidence_id
                    WHERE evidence_fts MATCH ? AND evidence_fts.tenant_id=?
                      AND evidence_fts.project_id=? AND evidence_fts.run_id=?
                      AND evidence_fts.source_use_decision='allowed'
                      AND evidence_fts.eligibility_status='eligible'
                    ORDER BY bm25(evidence_fts, 0, 0, 0, 0, 0, 0, 5.0, 2.0, 1.0, 0.2, 1.0)
                    LIMIT ?
                    """,
                    (match_query, tenant_id, project_id, run_id, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return None
        return [json.loads(row["payload"]) for row in rows]
