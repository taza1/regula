# Research review and release status

Verified locally: 2026-09-22. Branch: `feature/research-review-release`, based on merged master `b64aae9`.

## Implemented

- Explicit remote providers run bounded synthesis, a separate semantic fact-checking call, and a separate critical-review call. Each response has a strict schema. The same configured model performs these roles; separate requests are not independent model families or a guarantee of factual correctness.
- Every synthesized claim must cite selected eligible evidence. Fact-checking must cover every claim exactly once. Contradicted/unsupported claims, critical issues, policy violations, and changed content block approval.
- Review output is committed atomically only if the run and eligible evidence are unchanged. Cancellation discards in-flight output.
- The dashboard displays review status and provides explicit human approval/release controls. Approval needs a rationale; a separate publisher is required by default.
- Local release binds approval to the exact draft, review, evidence and policy. One SQLite transaction stores the immutable artifact bundle, release marker, audit, outbox event, and run state. Retries are idempotent. Artifact reads require current project membership.
- `AUTH_MODE=entra` validates signed delegated access tokens against a configured tenant, issuer, audience, expiration and API scope. Local development headers are ignored in this mode. Browser SSO integration remains pending.
- `MODEL_PROVIDER=foundry` invokes a deployed hosted agent through its dedicated endpoint. The hosted role executor and whitelist-only packaging/deployment scripts are supplied. They do not expose publication tools.
- `infra/main.bicep` defines Foundry/project, Cosmos/database/container, private Blob containers, Search, Service Bus queues, Key Vault, monitoring, identity, VNet and private endpoints. Local Bicep compilation and Azure Resource Manager validation succeeded. No deployment was performed.
- Source discovery now supports a pure `scholarly` connector for OpenAlex, Crossref and arXiv without local synthetic fallback. Missing abstracts remain empty instead of becoming placeholder evidence, Crossref type is not treated as peer-review proof, and explicit date windows keep relevance-biased ranking.

## Verification

The baseline had 45 passing Python tests. The full suite passed with 62 tests after review/release and source-hardening implementation. An additional end-to-end API test passed for review, approval, publisher authorization, artifact read and tenant isolation.

A live local dashboard run was exercised with Playwright against `MODEL_PROVIDER=azure`, `SOURCE_CONNECTOR=scholarly`, and `gpt-5.6-sol`. The run produced real Crossref/OpenAlex records and reached `adjudication_required`, correctly blocking release because the evidence was abstract-only, temporally concentrated, and source-fit limited.

The hosted SDK deployment definition can be constructed locally, and the packaged entrypoint imports with its optional dependencies. Live Foundry execution has not been tested. Docker Desktop's engine was unavailable. SDK instrumentation required disabling incompatible automatic OpenAI tracing; hosted telemetry is explicitly disabled until redaction is verified.

## Still required before production

1. Select and approve the Azure target, region, model deployment and cost envelope. The current `rg-foundry-agent-dev` inventory contains only the Foundry account/project. The infrastructure includes chargeable Search replicas, Service Bus Premium, Cosmos throughput and private endpoints; do not apply it without reviewing cost and network design.
2. Deploy and verify the packaged Foundry agent; grant its dedicated identity model access. Validate private DNS, hosted-agent egress, endpoint authorization and model availability. The worker managed identity in Bicep is not the platform-created agent identity.
3. Replace application SQLite persistence/queue with Cosmos transactional state, immutable Blob artifacts, Service Bus workers/outbox delivery, and Search indexing/retrieval. Creating infrastructure does not wire these adapters into the application. The current application is not a production distributed runtime.
4. Add production API hosting, browser Entra sign-in, secrets/configuration delivery, redacted telemetry, alerting, backup/restore exercises and deployment/rollback automation.
5. Run live model evaluations for entailment, contradictions, source independence, bias, prompt injection and failure recovery. Model-assisted checks are fallible. Citation integrity alone is not semantic verification.
6. Obtain approval before publishing a real report or creating Azure/GitHub records.

## Local use

Install `requirements.txt`. Existing mock mode keeps the deterministic draft flow and cannot pass semantic release gates. Explicitly set `MODEL_PROVIDER=azure` and configure the model endpoint/deployment for remote review. These calls incur usage charges.

Set `ENABLE_REPORT_RELEASE=true` only for the approved environment. Complete a run, review its evidence and model findings, then POST `/api/v1/projects/{project}/runs/{run}/request-approval` with `approval_rationale`. A different publisher POSTs `/release` with the resulting `approval_id`. Artifact URLs returned by release require the same authentication as the API. The default remains release-disabled.

An admin can set another user's project roles with PUT `/api/v1/projects/{project}/members/{user}` and `{"roles":["publisher"]}`. The API prevents removal of the last admin. In Entra mode use object IDs, `ENTRA_TENANT_ID`, `ENTRA_AUDIENCE`, and a delegated `ENTRA_SCOPE` (default `Research.Access`). Local identity headers do not provide production authentication.

## Foundry packaging and deployment

Install optional client dependencies with `pip install -r requirements-foundry.txt`. Run `python hosted_agent/package_agent.py` to create `.build/research-agent.zip`; only the handler, model/config files, empty package initializer and requirements are included. Local credentials and databases are excluded.

`hosted_agent/deploy.py --project-endpoint <project-url> --model-endpoint <model-url> --deployment <deployment-name>` prepares the deployment without Azure changes. Adding `--apply` creates an external agent version and incurs costs; use only after approval. The default agent name is `regula-research-review`, with one CPU and 2 GiB memory. On success, set `MODEL_PROVIDER=foundry`, `FOUNDRY_PROJECT_ENDPOINT`, and `FOUNDRY_AGENT_NAME` on the local application.

Sources checked: [Microsoft hosted-agent deployment](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent), [source-code deployment](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-code), and [current endpoint/identity migration](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/migrate-hosted-agent-preview).

## Original checkout audit

The original checkout remains on `feature/research-dashboard-execution` at `c466d58`. Its three modified files (`local_store.py`, `main.py`, `services.py`) and four untracked files (`execution.py` plus dashboard JS/HTML/CSS) match merged master after UTF-8/newline normalization. They are leftover copies of PR #2. No source differences were found, and none were overwritten, removed or stashed. All new work is in the separate `regula.worktrees/research-review-release` worktree.
