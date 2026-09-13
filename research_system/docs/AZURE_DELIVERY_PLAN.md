# Azure Delivery Plan

Last reviewed: 2026-09-12

## Outcome

Move the current local research-system slice to an Azure-backed, authenticated, end-to-end internal research pilot without weakening the original Microsoft Foundry design.

This is a plan-only review. No Azure resources were created or changed as part of this document.

## Current Baseline

The repo is no longer just the original scaffold. The research branch now includes the merged scholarly connector and local hardening work:

- FastAPI project and run lifecycle.
- Mock and Azure planner clients.
- SQLite-backed local persistence.
- Deterministic offline source discovery and ingestion.
- OpenAlex, Crossref, and arXiv discovery with provider outcomes, retry handling, throttling, and recency handling.
- Allowlisted HTML/PDF retrieval with redirect and resolved-address checks, bounded streaming, text extraction, and chunking.
- Insert-only local source snapshots that reject conflicting writes.
- Tenant/project/run-scoped evidence storage.
- SQLite FTS5 evidence search with BM25 ranking and tenant/project/run/eligibility filters.
- Python tests passing on 2026-09-12: `41 passed, 1 warning`.
- A GitHub Actions workflow defines deterministic Python and Playwright checks; its first hosted run remains pending push.

The Azure inventory below was last verified on 2026-09-11 and was not refreshed during the 2026-09-12 code-validation round. At that verification point, Azure CLI could access the subscription and the Foundry resource group contained a Foundry account/project with these model deployments:

| Deployment | Model | Version | SKU | State |
| --- | --- | --- | --- | --- |
| `gpt-5-mini` | `gpt-5-mini` | `2025-08-07` | `GlobalStandard` | `Succeeded` |
| `gpt-5.6-sol` | `gpt-5.6-sol` | `2026-07-09` | `GlobalStandard` | `Succeeded` |

At the 2026-09-11 verification point, `rg-foundry-agent-dev` showed only the Foundry account/project. Cosmos DB, Blob Storage, Azure AI Search, Service Bus, Key Vault, and monitoring resources still need to be provisioned for the full system.

## Current Gaps

The local app is useful for development, but it is not yet an end-to-end research platform:

- The API uses header-based local development identity and project membership checks; production Entra token validation is not implemented.
- Planning, scholarly discovery, deterministic draft synthesis, and structural citation validation exist as local services. Independent semantic fact-checking, critical review, safety review, evaluators, and hosted agent orchestration are not implemented.
- `execute-local` can use deterministic local fixtures or scholarly metadata discovery. Full-document ingestion is an explicit service path and is not yet wired into the default API execution flow.
- Evidence storage is SQLite JSON records, not immutable Blob originals plus Cosmos metadata and Azure AI Search indexes.
- Search has scoped local FTS5/BM25 retrieval; embeddings, semantic retrieval, Azure AI Search, and measured precision/recall are not implemented.
- Cross-provider publication deduplication is implemented, but evidence independence still does not identify shared studies or datasets reliably enough for publication gates.
- Release is intentionally blocked at the API with `501`. Lower-level release service stubs still contain placeholder Blob URLs and must not be exposed.
- State updates are unconditional local upserts, not ETag/epoch-guarded transitions.
- Azure deployment assets, Azure DevOps pipelines, IaC, observability, and fault-injection tests are not in place.

## Azure Design Decisions

Keep the original spec direction:

- Runtime: Microsoft Foundry Agent Service, with Hosted Agents for custom multi-agent code.
- Orchestration: Microsoft Agent Framework or an equivalent explicit orchestration layer that preserves deterministic run states.
- State: Cosmos DB for authoritative project/run/control/release state.
- Evidence artifacts: private Blob Storage for immutable source snapshots, extracted text, manifests, and report artifacts.
- Retrieval: Azure AI Search with keyword, vector, semantic, and metadata-filtered retrieval.
- Work queues: Azure Service Bus with retries, dead-letter handling, stable message IDs, and idempotent handlers.
- Identity: Microsoft Entra ID, managed identity, project membership, and Azure RBAC. No API keys in source.
- Secrets/configuration: Key Vault plus environment-specific deployment parameters.
- Telemetry: Application Insights/OpenTelemetry with prompt/source/report redaction.
- Delivery: Bicep plus `azd`, and Azure DevOps Pipelines as the primary CI/CD path because that is what the original plan specifies.

The existing localhost proxy remains a development adapter only. Production should use managed identity / Entra authentication from Azure-hosted code to Foundry.

## Documentation Checks

The plan was checked against current Microsoft documentation:

- Foundry Agent Service supports prompt agents, Hosted Agents, managed identity, toolboxes, tracing, and hosted custom code as containers or source packages: https://learn.microsoft.com/en-us/azure/foundry/agents/overview
- Foundry models sold by Azure include `gpt-5.6-sol` and document model/deployment availability by region and deployment type: https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure
- Deployment type matters for residency. `GlobalStandard` routes through global infrastructure and should not be documented as single-region processing: https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types
- Cosmos DB transactional batches are ACID within one logical partition; the release protocol must keep transactional control records in one project partition: https://learn.microsoft.com/en-us/azure/cosmos-db/transactional-batch
- Cosmos DB ETags support optimistic concurrency and conditional writes: https://learn.microsoft.com/en-us/azure/cosmos-db/database-transactions-optimistic-concurrency
- Service Bus production queues should use dead-letter handling, duplicate detection where appropriate, and monitored recovery: https://learn.microsoft.com/en-us/azure/well-architected/service-guides/azure-service-bus

## Delivery Sequence

### Milestone 1: Hardening the Local Vertical Slice

Goal: one real local research loop that can discover real scholarly metadata, ingest permitted abstracts/passages, search evidence, and produce an unreleased cited draft or an `insufficient_evidence` outcome.

Required work:

- Replace caller-supplied tenant/user placeholders with a local auth abstraction that can later map to Entra.
- Add a state machine with legal transitions and revision/epoch checks.
- Harden the OpenAlex connector, then add Crossref and arXiv connectors with rate limits, retries, provenance, and source-use metadata.
- Store source originals or source snapshots immutably, even in local dev.
- Add passage records with section/offset/page fields where available.
- Establish retrieval evaluation fixtures, then add embeddings and move retrieval to Azure AI Search.
- Implement a synthesis pass that creates a draft plus a material claim ledger.
- Extend deterministic citation integrity validation with semantic fact-checking and release-blocking review gates.
- Preserve `/release` as `501` until approval, manifest, artifact verification, and conditional commit are implemented.

Exit criteria:

- A new run can go from project creation to real source discovery, evidence search, cited draft, and blocked release.
- Unsupported claims produce `insufficient_evidence`, not a polished unsupported answer.
- Tests cover source failure, no evidence, contradictory evidence, cancellation before worker result, and direct API authorization checks.

### Milestone 2: Azure Foundation

Goal: reproducible dev Azure environment that can host the same flow with real Azure state and storage.

Required resources:

- Foundry account/project and model deployments.
- Cosmos DB account/database/container using project-scoped partitioning for transactional control records.
- Storage account with private containers for sources, extracted text, reports, and manifests.
- Azure AI Search service and indexes for evidence/passages/metadata.
- Service Bus namespace and queues/topics for run work, review work, release outbox, and dead letters.
- Key Vault for configuration secrets and signing keys.
- Application Insights / Log Analytics.
- Managed identities and role assignments for API, agents/workers, and pipelines.

Exit criteria:

- `azd up` or an Azure DevOps environment deployment creates a dev environment from an empty resource group.
- The API can run against Azure Cosmos/Blob/Search/Service Bus without connection strings or embedded keys.
- Readiness checks verify each dependency and model deployment before accepting research work.

### Milestone 3: Azure Research Pipeline

Goal: background research execution in Azure with durable work, retries, and scoped retrieval.

Required work:

- Move run execution out of request/response into Service Bus-backed workers or Foundry Hosted Agent sessions.
- Persist every worker output with run epoch, project guard version, configuration snapshot, and idempotency key.
- Store originals and derived passages in Blob/Cosmos, then index accepted evidence in Azure AI Search.
- Add embedding generation and hybrid search.
- Pin model, prompt, tool, index, schema, and policy versions per run.
- Add cancellation/revocation logic that rejects stale worker outputs.

Exit criteria:

- A hosted worker can complete the real evidence loop in Azure and survive retries without duplicate accepted evidence.
- Search results are filtered by tenant/project/run and current authorization.
- Cancelling or revoking access prevents late worker outputs from becoming eligible.

### Milestone 4: Review, Approval, and Gates

Goal: a cited draft cannot be released until mandatory application-owned gates pass.

Required work:

- Implement fact-checker, citation validator, critical reviewer, safety reviewer, and evaluator outputs.
- Add constrained human adjudication records.
- Add separate-Publisher approval bound to the exact approved bundle digest.
- Ensure Publisher/Admin cannot waive unsupported material claims, security/privacy failures, source-use failures, or integrity failures.

Exit criteria:

- Bad citation, unsupported claim, unresolved contradiction, source permission failure, self-approval, stale approval, and role mismatch all block release.
- Correcting the report or evidence invalidates affected approvals and reviews.

### Milestone 5: Release, Withdrawal, and Recovery

Goal: internal publication is transactionally safe and recoverable.

Required work:

- Implement release intent, artifact freeze, private Blob write, manifest signature/hash verification, conditional Cosmos commit, and outbox dispatch.
- Add stable release/artifact/event IDs so retries converge.
- Add internal release read endpoints with current authorization checks.
- Add withdrawal and policy/source revocation handling.
- Add reconciliation for stalled release intents and outbox messages.

Exit criteria:

- Storage failure never exposes a report.
- Lost responses do not duplicate releases.
- Cancellation/revocation races pick one authoritative outcome.
- Withdrawal and permission revocation deny subsequent service-mediated reads.

### Milestone 6: UI and Pilot Readiness

Goal: an authenticated internal pilot can use the system end to end.

Required work:

- Build project, scope confirmation, progress, evidence, draft, review, approval, release, recovery, and withdrawal screens.
- Show partial-source failure, insufficient evidence, budget exhaustion, cancellation, revision invalidation, and recovery states.
- Add operational dashboards for queue age, model errors, source failures, gate failures, releases, and withdrawals.
- Add pilot runbook, rollback plan, data retention policy, and cost budget controls.

Exit criteria:

- Browser tests cover success and non-success journeys.
- Controls are keyboard accessible and authorization is enforced server-side.
- Pilot admission requires passing acceptance evidence, not just a healthy `/docs` page.

## Parallel Workstreams

These workstreams can run in parallel after shared contracts are locked:

| Workstream | Owns | Starts after | Blocks |
| --- | --- | --- | --- |
| Contracts/API | Pydantic models, OpenAPI, state transitions, versioning | Now | All other workstreams |
| Source/Evidence | OpenAlex/Crossref/arXiv, crawling policy, provenance, passage extraction | Contracts draft | Search, synthesis, gates |
| Retrieval | Local FTS, embeddings, Azure AI Search schema/querying | Evidence records draft | Synthesis, evaluator |
| Agents | planner, source search, synthesis, reviewer agents, orchestration | Contracts and retrieval interfaces | End-to-end research |
| Azure/IaC | Bicep, azd, identities, networking, resources | Resource naming and policy decisions | Azure execution |
| Security | AuthN/AuthZ, tenant isolation, source policy, telemetry redaction | Contracts draft | Public/internal pilot |
| Release | approval, manifest, artifact commit, outbox/recovery | Gates and security controls | Publication |
| UI/E2E | workbench flows, status UX, browser tests | API shape stable | Pilot readiness |

## Decisions Needed Before Azure Build

- Target environment names and Azure regions.
- Data classification and residency policy. If single-region or EU-only processing is required, `GlobalStandard` model deployments are not enough.
- Whether to keep Foundry Hosted Agents as mandatory, or approve an ADR to use Azure Container Apps/Functions workers for some background processing.
- Initial source allowlist and source-use policy.
- Pilot audience and role assignments.
- Monthly budget ceiling and quota/rate-limit policy.
- Whether Azure DevOps Pipelines is required, or whether GitHub Actions can be used only as a temporary dev path.

## Review Status

This plan incorporates partial backend, security, and DevOps specialist findings gathered before the specialist runs hit a usage-limit error. It has not received a completed independent specialist signoff in this round.
