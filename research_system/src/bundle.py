"""Release bundle assembly and digest for the local approval/release workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from src.local_store import LocalStateStore

_BLOCKING_SEVERITIES = {"high", "critical"}


def load_bundle(
    store: LocalStateStore, tenant_id: str, project_id: str, run_id: str
) -> Optional[dict[str, Any]]:
    """Collect the draft, claims, findings and evidence hashes for one run."""

    draft = store.get("draft", tenant_id, project_id, run_id)
    if not draft:
        return None
    claims = sorted(
        (
            payload
            for payload in store.list("claim", tenant_id, project_id, limit=1000)
            if payload.get("run_id") == run_id
        ),
        key=lambda item: item["claim_id"],
    )
    findings = sorted(
        (
            payload
            for payload in store.list("finding", tenant_id, project_id, limit=1000)
            if payload.get("run_id") == run_id
        ),
        key=lambda item: item["finding_id"],
    )
    evidence_hashes: dict[str, Optional[str]] = {}
    for reference in draft.get("references", []):
        evidence_id = reference.get("evidence_id")
        if evidence_id:
            evidence = store.get("evidence", tenant_id, project_id, evidence_id)
            evidence_hashes[evidence_id] = evidence.get("content_hash") if evidence else None
    return {
        "draft": draft,
        "claims": claims,
        "findings": findings,
        "evidence_hashes": evidence_hashes,
    }


def bundle_digest(bundle: dict[str, Any]) -> str:
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def blocking_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open findings at high or critical severity block approval."""

    return [
        finding
        for finding in findings
        if finding.get("status") == "open"
        and finding.get("severity") in _BLOCKING_SEVERITIES
    ]
