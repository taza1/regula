"""Local review gates: citation validation, fact-check, security and critical review."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from src.audit import AuditService
from src.bundle import blocking_findings
from src.local_store import LocalStateStore
from src.models import (
    ClaimRecord,
    DraftReport,
    EvidenceRecord,
    EvidenceRelation,
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewFindingStatus,
    RunState,
)
from src.review import SUPPORT_THRESHOLD, scan_for_prompt_injection, support_ratio
from src.services import EvidenceService, ResearchRunService

_RESOLVABLE = {
    ReviewFindingStatus.ACCEPTED_LIMITATION,
    ReviewFindingStatus.FALSE_POSITIVE,
    ReviewFindingStatus.RESOLVED,
}


def _finding_id(tenant_id, project_id, run_id, claim_id, category, key) -> str:
    raw = "|".join([tenant_id, project_id, run_id, claim_id, category, key])
    return "FND-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


class ReviewService:
    """Run the deterministic review gates over a run's draft and claim ledger."""

    def __init__(self, store: LocalStateStore, evidence_service: EvidenceService):
        self.store = store
        self.evidence_service = evidence_service
        self.runs = ResearchRunService(store)
        self.audit = AuditService(store)

    async def run_review(
        self, tenant_id: str, project_id: str, run_id: str, actor: str
    ) -> Optional[dict[str, Any]]:
        """Review a run in REVIEWING or ADJUDICATION_REQUIRED and advance its state.

        Returns None when the run is missing, not reviewable, or has no draft.
        Findings keep a deterministic ID, so re-running after adjudication
        preserves any reviewer decision already recorded for the same finding.
        """

        run = await self.runs.get_run(tenant_id, project_id, run_id)
        if not run or run.state not in (RunState.REVIEWING, RunState.ADJUDICATION_REQUIRED):
            return None
        draft_payload = self.store.get("draft", tenant_id, project_id, run_id)
        if not draft_payload:
            return None
        if run.state == RunState.ADJUDICATION_REQUIRED and not await self.runs.update_run_state(
            tenant_id, project_id, run_id, RunState.REVIEWING,
            revision=run.report_revision, expected_state=RunState.ADJUDICATION_REQUIRED,
        ):
            return None

        draft = DraftReport.model_validate(draft_payload)
        claims = await self.runs.list_claims(tenant_id, project_id, run_id)
        evidence = self._run_evidence(tenant_id, project_id, run_id)

        new_findings = self._citation_and_fact_check(run, claims, evidence)
        new_findings += self._injection_scan(run, claims, evidence)
        new_findings += await self._critical_review(run, claims, evidence, draft)

        findings = [self._merge_existing(finding) for finding in new_findings]
        for finding in findings:
            self.store.put(
                "finding", tenant_id, project_id, finding.finding_id,
                finding.model_dump(mode="json"),
            )
        run = await self.runs.get_run(tenant_id, project_id, run_id)
        run.findings = sorted({f.finding_id for f in findings} | set(run.findings))
        self.store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))

        blockers = blocking_findings([f.model_dump(mode="json") for f in findings])
        next_state = RunState.ADJUDICATION_REQUIRED if blockers else RunState.AWAITING_APPROVAL
        await self.runs.update_run_state(
            tenant_id, project_id, run_id, next_state,
            revision=run.report_revision, expected_state=RunState.REVIEWING,
        )
        self.audit.record(
            tenant_id, project_id, run_id, actor, "review.completed",
            {"findings": len(findings), "blocking": len(blockers), "next_state": next_state.value},
        )
        return {"findings": findings, "blocking": len(blockers), "state": next_state}

    async def resolve_finding(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str,
        finding_id: str,
        status: ReviewFindingStatus,
        reviewer_id: str,
        rationale: str,
    ) -> Optional[ReviewFinding]:
        """Record a reviewer's decision on one finding. Rationale is mandatory."""

        payload = self.store.get("finding", tenant_id, project_id, finding_id)
        if not payload or payload.get("run_id") != run_id or not rationale.strip():
            return None
        finding = ReviewFinding.model_validate(payload)
        if status not in _RESOLVABLE:
            return None
        # A critical finding is never an acceptable limitation: it must be
        # cleared as a false positive or fixed and resolved.
        if (
            finding.severity == ReviewFindingSeverity.CRITICAL
            and status == ReviewFindingStatus.ACCEPTED_LIMITATION
        ):
            return None
        finding.status = status
        finding.reviewer_id = reviewer_id
        finding.explanation = f"{finding.explanation} | Reviewer decision: {rationale.strip()}"
        self.store.put(
            "finding", tenant_id, project_id, finding_id, finding.model_dump(mode="json")
        )
        self.audit.record(
            tenant_id, project_id, run_id, reviewer_id, "finding.resolved",
            {"finding_id": finding_id, "status": status.value},
        )
        return finding

    async def list_findings(
        self, tenant_id: str, project_id: str, run_id: str
    ) -> list[ReviewFinding]:
        return [
            finding
            for payload in self.store.list("finding", tenant_id, project_id, limit=1000)
            if (finding := ReviewFinding.model_validate(payload)).run_id == run_id
        ]

    # ------------------------------------------------------------------ checks

    def _run_evidence(self, tenant_id, project_id, run_id) -> dict[str, EvidenceRecord]:
        return {
            record.evidence_id: record
            for payload in self.store.list("evidence", tenant_id, project_id, limit=1000)
            if (record := EvidenceRecord.model_validate(payload)).run_id == run_id
        }

    def _finding(
        self, run, claim_id, severity, category, control_class, verdict, explanation,
        required_action=None, key="",
    ) -> ReviewFinding:
        return ReviewFinding(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run.run_id,
            report_revision=run.report_revision,
            finding_id=_finding_id(
                run.tenant_id, run.project_id, run.run_id, claim_id, category, key
            ),
            claim_id=claim_id,
            severity=severity,
            category=category,
            control_class=control_class,
            status=ReviewFindingStatus.OPEN,
            verdict=verdict,
            explanation=explanation,
            required_action=required_action,
        )

    def _merge_existing(self, finding: ReviewFinding) -> ReviewFinding:
        """Keep a prior reviewer decision when the same finding is raised again."""

        existing = self.store.get(
            "finding", finding.tenant_id, finding.project_id, finding.finding_id
        )
        if existing and existing.get("status") != ReviewFindingStatus.OPEN.value:
            return ReviewFinding.model_validate(existing)
        return finding

    def _citation_and_fact_check(self, run, claims, evidence) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for claim in claims:
            supporting = [
                link for link in claim.evidence_links
                if link.relation == EvidenceRelation.SUPPORTS
            ]
            if not supporting:
                findings.append(self._finding(
                    run, claim.claim_id, ReviewFindingSeverity.HIGH, "citation-integrity",
                    "evidence", "unsupported",
                    "Claim has no supporting citation.",
                    "Attach a supporting evidence passage or remove the claim.",
                ))
                claim.status = "rejected"
                self._save_claim(claim)
                continue
            best = 0.0
            claim_ok = True
            for link in supporting:
                record = evidence.get(link.evidence_id)
                if (
                    record is None
                    or record.source_use_decision.value != "allowed"
                    or not record.passage.strip()
                ):
                    claim_ok = False
                    findings.append(self._finding(
                        run, claim.claim_id, ReviewFindingSeverity.CRITICAL,
                        "citation-integrity", "evidence", "invalid-citation",
                        f"Citation {link.evidence_id} is missing, not allowed, or has no text.",
                        "Replace the citation with an allowed evidence passage.",
                        key=link.evidence_id,
                    ))
                    continue
                best = max(best, support_ratio(claim.text, record.passage))
            if not claim_ok:
                claim.status = "rejected"
            elif best < SUPPORT_THRESHOLD:
                findings.append(self._finding(
                    run, claim.claim_id, ReviewFindingSeverity.HIGH, "citation-entailment",
                    "evidence", "insufficient_evidence",
                    f"Cited passages cover only {best:.0%} of the claim's content terms.",
                    "Narrow the claim to what the passage states or cite additional evidence.",
                ))
                claim.status = "needs_revision"
            else:
                claim.status = "fact_checked"
            claim.confidence = round(best, 2)
            self._save_claim(claim)
        return findings

    def _injection_scan(self, run, claims, evidence) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        claim_by_evidence: dict[str, str] = {}
        for claim in claims:
            for link in claim.evidence_links:
                claim_by_evidence.setdefault(link.evidence_id, claim.claim_id)
        for record in evidence.values():
            labels = scan_for_prompt_injection(f"{record.title}\n{record.passage}")
            if labels:
                findings.append(self._finding(
                    run, claim_by_evidence.get(record.evidence_id, "RUN"),
                    ReviewFindingSeverity.CRITICAL, "prompt-injection", "security",
                    "suspected-injection",
                    f"Source text for {record.evidence_id} contains instruction-like "
                    f"content ({', '.join(labels)}). Treat it as data, not instructions.",
                    "Inspect the source; exclude it or mark the finding a false positive.",
                    key=record.evidence_id,
                ))
        return findings

    async def _critical_review(self, run, claims, evidence, draft) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for claim in claims:
            origins = {
                evidence[link.evidence_id].source_id
                for link in claim.evidence_links
                if link.evidence_id in evidence
            }
            if claim.material and len(origins) < 2:
                findings.append(self._finding(
                    run, claim.claim_id, ReviewFindingSeverity.WARNING, "methodology",
                    "evidence", "single_source",
                    "Material claim rests on a single source.",
                    "Seek an independent corroborating source.",
                    key="single-source",
                ))
            if origins and all(
                evidence[link.evidence_id].peer_review_status.value != "peer-reviewed"
                for link in claim.evidence_links
                if link.evidence_id in evidence
            ):
                findings.append(self._finding(
                    run, claim.claim_id, ReviewFindingSeverity.WARNING, "methodology",
                    "evidence", "not_peer_reviewed",
                    "Claim is supported only by sources that are not peer reviewed.",
                    key="not-peer-reviewed",
                ))
            cited = {link.evidence_id for link in claim.evidence_links}
            hits = await self.evidence_service.search_contradictory_evidence(
                run.tenant_id, run.project_id, run.run_id, claim.text, limit=3
            )
            for hit in hits:
                if hit.evidence_id not in cited:
                    note = f"{hit.title} [evidence: {hit.evidence_id}]"
                    if note not in draft.contradictory_evidence:
                        draft.contradictory_evidence.append(note)
                    findings.append(self._finding(
                        run, claim.claim_id, ReviewFindingSeverity.HIGH,
                        "contradictory-evidence", "evidence", "contradicted",
                        f"Possible opposing evidence in {hit.evidence_id}.",
                        "Address the opposing evidence in the report or explain why it "
                        "does not apply.",
                        key=hit.evidence_id,
                    ))
        if not draft.contradictory_evidence and claims:
            findings.append(self._finding(
                run, "RUN", ReviewFindingSeverity.INFO, "methodology", "evidence",
                "no_contradictory_found",
                "A contradictory-evidence search found nothing; absence is not proof.",
                key="no-contradictory",
            ))
        self.store.put(
            "draft", run.tenant_id, run.project_id, run.run_id,
            draft.model_dump(mode="json"),
        )
        return findings

    def _save_claim(self, claim: ClaimRecord) -> None:
        self.store.put(
            "claim", claim.tenant_id, claim.project_id, claim.claim_id,
            claim.model_dump(mode="json"),
        )
