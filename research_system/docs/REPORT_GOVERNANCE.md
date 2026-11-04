# Production report governance (FUT-080) — draft for reviewer approval

Status: **local mechanisms implemented and tested; policies below are PROPOSALS, not decisions.** FUT-080 depends on FUT-040, FUT-050, FUT-060 and FUT-070, none of which is complete, so release stays disabled by default and `TODO.md` is not ticked. Nothing here enables release.

## Mechanisms that exist (each has tests in `tests/test_report_governance.py`)

| Spec item | Mechanism |
|---|---|
| Separate duties | Approver must differ from publisher (`REQUIRE_SEPARATE_PUBLISHER`, default on). New `REQUIRE_SEPARATE_ADJUDICATOR` (default off): an approver may not be a user who adjudicated that run's blockers. Reviewer and publisher roles are checked inside the transaction. |
| Approval bound to content | Approval stores a digest of the draft, review (incl. model, prompt version, policy, verification bundle), evidence, adjudication, and a manifest. Release recomputes it; any change blocks release. The manifest lists each source's licence/hash/snapshot, review provenance, verification mode, and the retrieval configuration in force. |
| Missing licence | `RELEASE_REQUIRE_LICENCE` (default off): every eligible source must declare a licence to approve or release. |
| Revoked/retracted evidence | `POST /projects/{p}/evidence/{id}/revoke` (reviewer/admin, reason required) makes evidence ineligible; new approvals/releases for its run are blocked immediately. Releases already using it are listed, **not** auto-withdrawn — a human decides. |
| Unsupported claim / verifier failure | Review blockers stop approval; verifier failure is a non-waivable blocker (FUT-060). |
| Withdrawal / tombstone | `POST /releases/{id}/withdraw` (publisher/admin, reason required) is one transaction: marks the release and run-release pointer, moves the run to `withdrawn`, writes an audit event and an outbox event. The artifact is retained; reads return 410; the release cannot be re-released without a new review and approval. |
| Authenticated private reads | Release artifact and provenance reads require project membership. No export or public links exist. |
| Reproduce the chain | `GET /projects/{p}/releases/{id}/provenance`: claim → verdict → cited passages (IDs, hashes, licence, snapshot) → review provenance → verification → adjudication → approval → audit chain. Fails closed if the stored artifact no longer matches its digest. |
| Promotion checklist | `GET /projects/{p}/release-readiness` (admin): executable list of required gates. It reports; it cannot enable release. It is not ready today because FUT-040/050/070 are unimplemented. |

## Proposed responsibilities (needs named owners)

| Role | Proposed responsibility |
|---|---|
| researcher | Creates and runs research; cannot approve or publish. |
| reviewer | Runs review, adjudicates blockers with written reasons, approves content, revokes evidence. |
| publisher | Releases an approved report and withdraws releases; must not be the approver. |
| admin | Manages membership and the readiness checklist; should not be the sole approver of their own run. |
| audit | Someone outside the run reads the audit trail and provenance. Not yet assigned. |

Open: the system does not record who created a run, so "the researcher may not approve their own run" cannot be enforced yet.

## Proposed policies (each needs an owner decision)

- **Copyright and licences:** only sources with a declared, allowlisted licence in a released report; store licence and fetch metadata (exists). Quote length limits are undecided.
- **Privacy and acceptable use:** reports must not contain personal data from sources unless the project's data policy allows it; scope of acceptable research topics is undecided.
- **Retention:** keep release artifacts, approvals and audit events for a period to be set by the data owner; deletion vs tombstone for withdrawn reports is undecided.
- **Retraction and licence withdrawal:** revoke evidence immediately; reviewers decide within an agreed time whether affected releases are withdrawn or corrected.
- **Correction:** a corrected report is a new revision with a new review and approval; the old release is withdrawn. A revision workflow does not exist yet.
- **Report withdrawal:** reason mandatory, retained as a tombstone, audited.

## Threat model summary

| Threat | Mitigation in the repo | Gap |
|---|---|---|
| SSRF in document fetch | Redirect and address validation, download limits (HARD-001). | Not re-assessed here. |
| Cross-tenant access | Tenant/project-scoped queries, membership checks on endpoints, scoped vector and search filters, tests. | Local header identity is not authentication (FUT-050). |
| Prompt injection | Deterministic pre-gate + model review; injected text is a security blocker, clearable only as a false positive. | Rule-based scan covers known phrasings only. |
| Model/provider data handling | Embeddings and verifier are off by default; sending text to a provider is opt-in. | Which data may go to which provider is an ADR decision. |
| Queue poisoning | Durable queue with owner heartbeat and cancellation; stale results rejected. | Not fault-injected beyond existing tests. |
| Approval bypass | Digest-bound approval, transactional roles, tamper checks, adjudication rules. | Single SQLite file is the trust boundary. |
| Telemetry leakage | No telemetry pipeline exists yet. | Redaction design belongs to FUT-070. |
| Supply chain | Not assessed. | Dependency pinning and review needed. |

## Promotion checklist (summary; the endpoint is the source of truth)

Before enabling release in any shared environment: owners named and policies above approved; `REQUIRE_SEPARATE_ADJUDICATOR`, `RELEASE_REQUIRE_LICENCE` and `INDEPENDENT_VERIFICATION` turned on and evaluated; Entra identity (FUT-050); production persistence and recovery tested (FUT-040/070); rollback owner and incident path agreed; evidence retention set. Release and external publication each need their own approval.
