"""Hash-chained audit events for run and project actions.

Events are appended inside the caller's write transaction (``BEGIN IMMEDIATE``),
which serializes sequence numbers. Each event carries the digest of the event
before it in the same scope, so an edited, removed, or reordered event breaks
``verify_chain``. This is local tamper-evidence, not an immutable external sink.

Scope is the run id for run actions and ``""`` for project-level actions such as
membership changes. Events written before chaining existed have no ``scope`` and
are reported separately as legacy.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


def _scope(key: tuple) -> str:
    return key[2] if len(key) > 2 else ""


def _digest(event: dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "digest"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def append_audit(
    db, key: tuple, user: str, action: str, reference: str,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append one chained event using the caller's open write transaction."""

    scope = _scope(key)
    row = db.execute(
        "SELECT payload FROM entities WHERE kind='audit' AND tenant_id=? AND project_id=? "
        "AND json_extract(payload,'$.scope')=? "
        "ORDER BY json_extract(payload,'$.sequence') DESC LIMIT 1",
        (key[0], key[1], scope),
    ).fetchone()
    previous = json.loads(row[0]) if row else None
    event = {
        # user_id/action/reference/at are the pre-chain fields; keep them as-is.
        "user_id": user,
        "action": action,
        "reference": reference,
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "sequence": (previous["sequence"] + 1) if previous else 1,
        "prev_digest": previous["digest"] if previous else "",
        "detail": detail or {},
    }
    event["digest"] = _digest(event)
    db.execute(
        "INSERT INTO entities(kind,tenant_id,project_id,entity_id,payload) VALUES(?,?,?,?,?)",
        ("audit", key[0], key[1], uuid.uuid4().hex, json.dumps(event)),
    )
    return event


def record_audit(store, key: tuple, user: str, action: str, reference: str,
                 detail: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Append an event in its own transaction (for callers without one open)."""

    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        return append_audit(db, key, user, action, reference, detail)


def read_audit(store, tenant_id: str, project_id: str, scope: str = "") -> dict[str, Any]:
    """Return chained events for a scope in order, plus a count of legacy events."""

    chained, legacy = [], 0
    for payload in store.list("audit", tenant_id, project_id, limit=100000):
        if "scope" not in payload:
            legacy += 1
        elif payload["scope"] == scope:
            chained.append(payload)
    chained.sort(key=lambda event: event["sequence"])
    return {"events": chained, "legacy_events": legacy, "chain_valid": verify_chain(chained)}


def verify_chain(events: list[dict[str, Any]]) -> bool:
    prev = ""
    for expected, event in enumerate(events, start=1):
        if (
            event.get("sequence") != expected
            or event.get("prev_digest") != prev
            or event.get("digest") != _digest(event)
        ):
            return False
        prev = event["digest"]
    return True
