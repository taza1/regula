# Regula project completion plan

Last reviewed: 2026-09-26

## Outcome

Deliver Regula as a repeatable, evidence-backed research application that works locally, can use either a direct Azure model or a packaged Microsoft Foundry hosted agent, measures retrieval and model quality, and releases reports only through authenticated human approval. Production Azure deployment is a later gate because it adds persistent infrastructure cost and operational responsibility.

## Current verified baseline

The merged `master` branch includes the dashboard, durable local execution, scholarly discovery, model-backed synthesis, semantic fact-checking, critical review, local approval/release controls, Entra API token validation, Foundry client and packaging code, and Bicep definitions. Local release remains disabled by default.

The clean `feature/research-quality-evals` worktree contains two additional local commits that have not been pushed:

- `5097419` improves provider-specific queries, arXiv ranking, licensed full-text selection, and adds retrieval/model evaluation fixtures plus a guarded live Playwright test.
- `09367e1` sets the hosted-agent session idle timeout to the minimum supported two minutes to limit idle compute.

The branch is two commits ahead of and one merge commit behind `origin/master`. The merge commit brings in documentation already present in the branch history, but the branch should still be rebased or merged before opening its pull request. The original checkout remains on the older `feature/research-dashboard-execution` branch with preserved uncommitted copies of work already merged by PR #2.

Verification performed on this plan's baseline:

- Python suite: **66 passed, 1 warning** on 2026-09-26.
- Previous live dashboard verification reached real OpenAlex/Crossref evidence and correctly entered `adjudication_required` when evidence quality was insufficient.
- Direct Azure model access to `gpt-5.6-sol` has been verified.
- The hosted-agent package and deployment definition can be built locally, but `regula-research-review` has not been deployed or executed in Foundry.
- The repeatable live Playwright and quality-evaluation commands exist, but fresh result artifacts still need to be produced after the quality branch is integrated.

## Current Azure inventory and cost posture

The subscription inventory was checked on 2026-09-26. Eleven Azure Resource Manager resources are provisioned:

| Resource group | Resource | Purpose/status |
| --- | --- | --- |
| `rg-foundry-agent-dev` | Foundry account `foundry-agent-90af7e99` and project `foundry-agent-dev` | Intended Regula development target. Contains `gpt-5-mini` and `gpt-5.6-sol`, both Global Standard capacity 10. |
| `rg-foundry-personal-new` | Foundry account/project `foundry-personal-new/personal-coding` | No model deployment. Data-plane agent inventory requires access through its VNet. |
| `rg-foundry-personal-new` | Foundry account/project `tazfoundrye/tazfoundry` | No model deployment. Data-plane agent inventory requires access through its VNet. |
| `cloud-shell-storage-northeurope` | Storage account `newa` | Persistent Cloud Shell storage; may incur a small storage/transaction charge. |
| `rg-foundry-personal-new` | VNets `vnet01` and `vnet01-1` | Network configuration in North Europe and West US 3. |
| `NetworkWatcherRG` | Network Watchers for North Europe and West US 3 | Network management resources; enabled features can generate usage charges. |

No VM, Container Instance, Web App, AKS cluster, Container App, or always-running Regula hosted-agent compute was found. The accessible development project contains saved agent definitions named `coding-helper` and `product-helper`; these are not the packaged `regula-research-review` hosted agent and should not be modified as part of this project. Model deployments are available to receive requests and charge for token usage, while a saved agent definition does not continuously execute by itself.

Before creating production infrastructure, identify an owner and retention decision for the two older Foundry accounts, their VNets, Network Watchers, and Cloud Shell storage. Deletion is a separate, explicitly approved cleanup action.

## Delivery plan

### Milestone 1: integrate the quality branch

Priority: P0. This is the next pull request and does not require new Azure infrastructure.

- [ ] Rebase `feature/research-quality-evals` onto the current `origin/master` without touching the dirty original checkout.
- [ ] Run the full Python suite and deterministic Playwright suite after the rebase.
- [ ] Review the two commits for credentials, generated evaluation output, local databases, and build archives; none should enter Git.
- [ ] Push the branch, open a focused pull request, and require the hosted CI checks to pass.
- [ ] Update `TODO.md` and status documentation in that pull request so completed synthesis, review, licensed full-text safeguards, and evaluation scaffolding are no longer listed as wholly missing.

Exit criteria:

- The quality branch is merged into `master` with green Python and browser checks.
- A fresh checkout can follow the README and run deterministic local mode without Azure credentials or billable calls.

### Milestone 2: establish retrieval quality

Priority: P0. Use direct provider APIs first; OpenAlex, Crossref, and arXiv do not require paid accounts for the current metadata calls. Respect their identification, rate-limit, and usage policies.

- [ ] Run the live retrieval suite and store a dated JSON result as a CI artifact rather than a permanent claim in documentation.
- [ ] Expand the two initial cases into a versioned gold set covering multiple domains, exact-title lookup, recent research, date boundaries, negative results, contradictory evidence, and sparse queries.
- [ ] Record per-provider recall at K, precision at K, reciprocal rank or nDCG, date coverage, duplicate rate, source-independence groups, latency, timeout rate, and contradictory-evidence discovery.
- [ ] Add expected identifiers for stable cases. Cases with no expected IDs test only broad heuristics and cannot establish recall.
- [ ] Test arXiv live pagination, ordering, malformed responses, and timeout recovery from the deployment network. Its offline behavior is covered, but live reliability needs repeated evidence.
- [ ] Tune provider-specific translation and ranking only against held-out cases to avoid overfitting the initial fixtures.
- [ ] Add a clear partial-provider policy: useful results may continue, but the report and UI must identify missing providers.

Exit criteria:

- Agreed minimum thresholds are encoded and CI reports failures.
- Results show relevant, date-correct and independently sourced evidence across every supported provider, including safe behavior during a provider outage.

### Milestone 3: complete licensed full-text retrieval

Priority: P1. Abstract-only evidence remains the default until licensing and retrieval controls are proven.

- [ ] Define the supported licence allowlist and document how each provider signals the licence and canonical full-text URL.
- [ ] Add an open-access resolver such as Unpaywall or provider-native open-access links where appropriate; do not scrape publisher pages that do not grant retrieval rights.
- [ ] Preserve licence, access URL, retrieval time, content hash, MIME type and source provenance with every snapshot.
- [ ] Test redirects, expired links, paywalls, retractions, HTML/PDF extraction, OCR needs, duplicate versions, maximum size, and partial downloads.
- [ ] Measure how often full text changes claim support compared with abstracts and require the UI to label abstract-only conclusions.
- [ ] Obtain a legal/data-governance decision before adding licensed subscription content or retaining publisher PDFs.

Exit criteria:

- Every downloaded document has machine-verifiable permission and provenance.
- A failure to obtain permitted full text cannot silently become supporting evidence.

### Milestone 4: establish model and review quality

Priority: P0 before enabling release.

- [ ] Run the six existing live model cases against the selected deployment and capture model name/version, prompt version, settings, latency, token use and cost.
- [ ] Expand the suite with citation mismatch, numerical inconsistency, source conflict, indirect evidence, retraction, malicious document text, missing evidence, tool failure and cancellation cases.
- [ ] Require the model to block unsupported causal claims, stale evidence, prompt injection, unaddressed conflicts and material selection bias.
- [ ] Add repeated runs and regression tolerances because model outputs are non-deterministic.
- [ ] Evaluate whether fact-checking and critical review need a separate model family or independent deterministic checks. Separate calls to the same model are useful but are not independent verification.
- [ ] Version prompts, schemas, evaluation cases and thresholds together, and fail deployment promotion when a release-critical case regresses.

Exit criteria:

- All release-critical cases pass the agreed threshold over repeated runs.
- Every material claim maps to eligible evidence, and any unsupported or conflicting claim blocks approval.

### Milestone 5: deploy and verify the Foundry hosted agent

Priority: P1. This step creates a chargeable external agent version and therefore requires an approved target and cost envelope immediately before deployment.

- [ ] Use `foundry-agent-dev` as the proposed non-production target unless the owner selects another project.
- [ ] Confirm the selected model deployment, regional/data-residency requirements, quota, spending alert and maximum test budget.
- [ ] Create a dedicated managed identity and grant only the model invocation and telemetry permissions required by the hosted agent.
- [ ] Build the whitelist-only package and record its SHA-256 hash.
- [ ] Run `hosted_agent/deploy.py` first without `--apply`, review the 1 CPU/2 GiB and 120-second idle configuration, then deploy after approval.
- [ ] Verify version activation, endpoint authorization, private DNS/egress, model access, timeout behavior and redacted telemetry.
- [ ] Run the guarded Playwright test with `EXPECTED_MODEL_PROVIDER=foundry` and confirm real scholarly evidence, model review and a safe terminal state.
- [ ] Record tokens, hosted-session duration and cost. Test idle deprovisioning and define rollback/version retirement steps.

Exit criteria:

- A new browser-driven run demonstrably uses `MODEL_PROVIDER=foundry` and the packaged agent.
- The same evidence/review gates behave consistently through direct Azure and hosted-agent paths.
- Logs contain no prompts, document text, tokens or personal data unless explicitly allowed by the telemetry policy.

### Milestone 6: production Azure application and data plane

Priority: P2 after the pilot passes. The existing Bicep defines resources but the application does not yet use the production adapters.

- [ ] Review and parameterize infrastructure cost before deployment. In particular, validate whether Service Bus Premium, Azure AI Search replicas, Cosmos throughput and private endpoints are justified for the pilot.
- [ ] Deploy separate development/staging resources using Bicep and `azd`; capture what was actually created and its monthly budget.
- [ ] Replace SQLite state with Cosmos DB using partition design, ETags and transactional batches for run/release invariants.
- [ ] Store immutable source and release artifacts in private Blob Storage with retention, versioning and deletion policy.
- [ ] Implement Azure AI Search keyword/vector/semantic indexes with tenant, project, run, eligibility and revocation filters.
- [ ] Move background execution and outbox delivery to Service Bus with idempotency, retry, dead-letter and recovery procedures.
- [ ] Host the API and worker with managed identities. Put configuration/secrets in Key Vault.
- [ ] Add browser Entra sign-in and map validated users/groups to project roles; test tenant isolation and removal of access.
- [ ] Add redacted OpenTelemetry/Application Insights traces, dashboards, alerts, quotas and cost budgets.
- [ ] Exercise backup/restore, queue replay, deployment rollback, regional/provider failure, cancellation and release recovery.

Exit criteria:

- Staging survives concurrency and fault-injection tests without cross-tenant disclosure, duplicate release or lost state.
- Infrastructure, application deployment and rollback are repeatable from a clean environment.

### Milestone 7: report governance and production release

Priority: P1 for internal publishing; P0 for any external publishing.

- [ ] Define who may research, review, approve, publish, withdraw and audit reports.
- [ ] Bind approval to the exact report, evidence manifest, review output, prompts/models and policy versions.
- [ ] Add production artifact URLs, content hashes, immutable audit records and withdrawal/tombstone behavior.
- [ ] Define copyright, privacy, retention, acceptable-use and human-review policies for source material and generated reports.
- [ ] Conduct security review for SSRF, prompt injection, authorization, tenant boundaries, dependency supply chain and telemetry leakage.
- [ ] Keep release disabled by default until staging acceptance and named owner sign-off are complete.

Exit criteria:

- A reviewer can trace every released material claim to the exact retained evidence passage.
- Approval, publication and withdrawal are authenticated, auditable and recoverable.

## CI and operating cadence

- Run deterministic Python and Playwright suites on every pull request.
- Run retrieval evaluation on a controlled schedule and on connector/ranking changes, with provider outages reported separately from quality failures.
- Run chargeable model and Foundry end-to-end suites manually or on a budget-limited protected workflow; never on every untrusted pull request.
- Publish test/evaluation artifacts with timestamps, commit SHA, provider/model versions and redacted configuration.
- Review Azure inventory, token use, hosted-agent sessions, budgets, security findings and dependency updates monthly during the pilot.

## Recommended execution order

1. Integrate the two quality commits and update stale roadmap claims.
2. Run and strengthen retrieval and model evaluations using direct Azure access.
3. Complete the licensed full-text policy and tests.
4. Deploy the Foundry hosted agent for a bounded development smoke test.
5. Decide whether the measured pilot justifies production Azure infrastructure.
6. Implement production adapters, identity, observability and recovery.
7. Enable report release only after governance and staging gates pass.

## Immediate next command set

Run these from the `research-quality-evals/research_system` worktree after bringing the branch up to date:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest -q
npm run test:e2e
```

The chargeable live commands and required environment variables are documented in [LIVE_INTEGRATION_SMOKE.md](LIVE_INTEGRATION_SMOKE.md). Do not treat a health response, a model-only call, or a deployment status as end-to-end proof; the acceptance run must create a project and research run, retrieve real evidence, synthesize, review, and finish in a safe gated state.
