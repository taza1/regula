"""Local append-only audit trail for run, review, approval and release actions."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime
from typing import Any, Optional

from src.local_store import LocalStateStore

# Serializes the read-previous/append step across AuditService instances.
_APPEND_LOCK = threading.Lock()


class AuditService:
    """Write and read tenant/project-scoped audit events.

    Events are never updated. Each event carries the digest of the previous
    event for the same run so deletions or edits are detectable by
    ``verify_chain``. This is tamper-evidence for local development, not a
    substitute for an immutable external audit sink.
    """

    def __init__(self, store: LocalStateStore):
        self.store = store

    def record(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        actor: str,
        action: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        with _APPEND_LOCK:
            previous = self.list_events(tenant_id, project_id, run_id)
            prev_digest = previous[-1]["digest"] if previous else ""
            event = {
                "event_id": f"AUD-{uuid.uuid4().hex[:12].upper()}",
                "tenant_id": tenant_id,
                "project_id": project_id,
                "run_id": run_id,
                "sequence": len(previous) + 1,
                "actor": actor,
                "action": action,
                "detail": detail or {},
                "timestamp": datetime.utcnow().isoformat(),
                "prev_digest": prev_digest,
            }
            event["digest"] = self._digest(event)
            self.store.put("audit", tenant_id, project_id, event["event_id"], event)
        return event

    def list_events(
        self, tenant_id: str, project_id: str, run_id: str
    ) -> list[dict[str, Any]]:
        events = [
            payload
            for payload in self.store.list("audit", tenant_id, project_id, limit=5000)
            if payload.get("run_id") == run_id
        ]
        return sorted(events, key=lambda event: event["sequence"])

    def verify_chain(self, tenant_id: str, project_id: str, run_id: str) -> bool:
        prev_digest = ""
        for expected_sequence, event in enumerate(
            self.list_events(tenant_id, project_id, run_id), start=1
        ):
            body = {k: v for k, v in event.items() if k != "digest"}
            if (
                event["sequence"] != expected_sequence
                or event["prev_digest"] != prev_digest
                or event["digest"] != self._digest(body)
            ):
                return False
            prev_digest = event["digest"]
        return True

    @staticmethod
    def _digest(event: dict[str, Any]) -> str:
        body = {k: v for k, v in event.items() if k != "digest"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
