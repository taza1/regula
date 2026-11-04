"""Production report governance, local part (FUT-080).

Transactional withdrawal with a tombstone, evidence revocation that reports which
releases it touches, a claim-to-passage-to-approval provenance chain, and an
executable promotion checklist. Policy documents live in
``docs/REPORT_GOVERNANCE.md``; this module only enforces mechanisms. It does not
enable release, choose retention periods, or decide who owns what - those are
reviewer decisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.audit import append_audit, read_audit, record_audit
from src.publication import PublicationService
from src.review_pipeline import digest, read_entity, write_entity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernanceService:
    def __init__(self, store):
        self.store = store

    def withdraw(self, tenant_id: str, project_id: str, user: str, release_id: str, reason: str) -> dict:
        """Withdraw a release. The artifact is kept (tombstone); reads return 410."""

        if not reason or not reason.strip():
            raise ValueError("A withdrawal reason is required.")
        key = (tenant_id, project_id)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            PublicationService._role(db, key, user, ["publisher", "admin"])
            release = read_entity(db, "release", key, release_id)
            if not release:
                raise ValueError("Release not found.")
            if release.get("is_withdrawn"):
                raise ValueError("Release is already withdrawn.")
            run_id = release["run_id"]
            run_key = (tenant_id, project_id, run_id)
            tombstone = {"is_withdrawn": True, "withdrawal_reason": reason.strip(),
                         "withdrawn_at": _now(), "withdrawn_by": user}
            release.update(tombstone)
            write_entity(db, "release", key, release_id, release)
            by_run = read_entity(db, "release_by_run", run_key, run_id)
            if by_run and by_run.get("release_id") == release_id:
                by_run.update(tombstone)
                write_entity(db, "release_by_run", run_key, run_id, by_run)
            run = read_entity(db, "run", run_key, run_id)
            if run and run.get("state") == "released":
                run["state"] = "withdrawn"
                write_entity(db, "run", run_key, run_id, run)
            append_audit(db, run_key, user, "release.withdrawn", release_id, {"reason": reason.strip()})
            write_entity(db, "outbox", run_key, f"WD-{release_id}",
                         {"event": "report.withdrawn", "release_id": release_id, "dispatched": False},
                         insert=True)
            return release

    def revoke_evidence(self, tenant_id: str, project_id: str, user: str,
                        evidence_id: str, reason: str) -> dict[str, Any]:
        """Make evidence unusable (retraction, licence withdrawal) and list affected releases.

        Revoked evidence immediately blocks new approvals and releases for its run
        (the evidence digest changes). Releases that already used it are NOT
        withdrawn automatically; they are returned for a human withdraw/correct decision.
        """
        if not reason or not reason.strip():
            raise ValueError("A revocation reason is required.")
        key = (tenant_id, project_id)
        with self.store._connect() as db:
            PublicationService._role(db, key, user, ["reviewer", "admin"])
        payload = self.store.get("evidence", tenant_id, project_id, evidence_id)
        if not payload:
            raise ValueError("Evidence not found.")
        payload.update(source_use_decision="blocked", eligibility_status="ineligible",
                       revocation={"reason": reason.strip(), "by": user, "at": _now()})
        self.store.put("evidence", tenant_id, project_id, evidence_id, payload)  # also updates FTS
        affected = []
        for release in self.store.list("release", tenant_id, project_id, limit=1000):
            if release.get("is_withdrawn"):
                continue
            artifact = self.store.get("release_artifact", tenant_id, project_id, release["release_id"])
            if artifact and any(e.get("evidence_id") == evidence_id
                                for e in artifact["bundle"].get("evidence", [])):
                affected.append(release["release_id"])
        record_audit(self.store, (tenant_id, project_id, payload["run_id"]), user,
                     "evidence.revoked", evidence_id,
                     {"reason": reason.strip(), "affected_releases": affected})
        return {"evidence_id": evidence_id, "affected_releases": affected}

    def provenance(self, tenant_id: str, project_id: str, release_id: str) -> dict[str, Any]:
        """Reproduce claim -> cited passage -> review -> approval for a release."""

        release = self.store.get("release", tenant_id, project_id, release_id)
        artifact = self.store.get("release_artifact", tenant_id, project_id, release_id)
        if not release or not artifact:
            raise ValueError("Release not found.")
        bundle = artifact["bundle"]
        if digest(bundle) != artifact["bundle_digest"] or artifact["bundle_digest"] != release.get("bundle_digest"):
            raise ValueError("Release artifact failed its integrity check.")
        approval = artifact["approval"]
        evidence = {e["evidence_id"]: e for e in bundle["evidence"]}
        review = bundle["review"]
        claims = []
        for claim in review["claims"]:
            claims.append({
                "claim_id": claim["claim_id"], "text": claim["text"],
                "verdict": next((v["verdict"] for v in review["fact_check"]["verdicts"]
                                 if v["claim_id"] == claim["claim_id"]), None),
                "passages": [{k: evidence[i].get(k) for k in
                              ("evidence_id", "passage_id", "source_snapshot_id", "content_hash",
                               "license", "doi", "url")}
                             for i in claim["evidence_ids"] if i in evidence]})
        return {
            "release": {k: release.get(k) for k in ("release_id", "run_id", "released_at", "released_by",
                                                   "is_withdrawn", "withdrawal_reason", "withdrawn_by")},
            "bundle_digest": artifact["bundle_digest"],
            "approval": {k: approval.get(k) for k in ("approval_id", "approver_id", "approved_at",
                                                      "approval_rationale", "approved_bundle_digest")},
            "review": {k: review.get(k) for k in ("provider", "model", "prompt_version", "policy", "passed")},
            "verification": review.get("verification"),
            "adjudication": bundle.get("adjudication"),
            "claims": claims,
            "audit": read_audit(self.store, tenant_id, project_id, release["run_id"]),
        }


def release_readiness(research_config, api_config) -> dict[str, Any]:
    """Executable promotion checklist. ``ready`` is true only when every item is met.

    Items marked ``not implemented`` describe platform work (FUT-040/050/070) that
    does not exist yet, so ``ready`` is false today by design.
    """
    items = [
        ("human_approval", "A human approval is required before release", research_config.require_human_approval, ""),
        ("separate_publisher", "Publisher must differ from approver", research_config.require_separate_publisher, ""),
        ("separate_adjudicator", "Approver must differ from blocker adjudicators",
         research_config.require_separate_adjudicator, "REQUIRE_SEPARATE_ADJUDICATOR=true"),
        ("licence_required", "Every source must declare a licence to be approved or released",
         research_config.release_require_licence, "RELEASE_REQUIRE_LICENCE=true"),
        ("independent_verification", "Independent verification is enabled",
         research_config.independent_verification != "off", "INDEPENDENT_VERIFICATION=deterministic|model|both"),
        ("evidence_policy", "Peer review and at least two independent source groups are required",
         research_config.require_peer_review and research_config.min_independence_groups >= 2, ""),
        ("authenticated_identity", "Validated Entra identity, not local headers",
         api_config.auth_mode == "entra", "AUTH_MODE=entra"),
        ("production_persistence", "Production persistence and background execution (FUT-040)", False,
         "not implemented: local SQLite only"),
        ("browser_sso", "Browser sign-in and session security (FUT-050)", False, "not implemented"),
        ("observability_recovery", "Monitoring, SLOs, backup and restore (FUT-070)", False, "not implemented"),
    ]
    rows = [{"id": i, "requirement": r, "met": bool(m), "detail": d if not m else ""} for i, r, m, d in items]
    return {"ready": all(row["met"] for row in rows),
            "release_enabled": api_config.enable_report_release, "items": rows}
