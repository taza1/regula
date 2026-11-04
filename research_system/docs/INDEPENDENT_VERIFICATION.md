# Independent verification (FUT-060) — implementation status

Status: **mechanism implemented, off by default; FUT-060 acceptance NOT met.** `TODO.md` is intentionally not ticked.

## What exists

`src/verification.py`, wired into `ReviewPipeline` after the primary fact-check.

- **Modes** (`INDEPENDENT_VERIFICATION`): `off` (default; review output is byte-for-byte unchanged), `deterministic`, `model`, `both`.
- **Independence:** the deterministic checker is independent by mechanism. A model verifier must use a different provider+model than the reviewer (`VERIFIER_PROVIDER`, `VERIFIER_MODEL`); the same pair is refused. This is the minimum rule. A stronger one (model family, data-handling) is an ADR decision.
- **Input:** the claim ledger (id, text, cited evidence IDs) and the cited eligible passages only. No draft, critical review, or other context.
- **Output contract:** strict schema, one finding per claim, labels `supports` / `contradicts` / `uncertain`, rationale codes, and passage references. `supports`/`contradicts` need at least one reference.
- **Application gate:** every quote must appear verbatim in a passage the claim cites and that is eligible; quotes are resolved to offsets. Any violation fails the whole verification as `malformed` (no retry).
- **Advisory only:** findings can add blockers, never remove one. A verifier cannot approve or publish.
- **Disagreement:** if the reviewer found a claim supported and a verifier says contradicts/uncertain, a `verification` blocker is raised. A reviewer may adjudicate it (`accepted_limitation` or `false_positive`, with a rationale); the decision is bound into the approval digest.
- **Fail closed:** when enabled, a missing, unconfigured, non-independent, timed-out, erroring, or malformed verifier raises a `policy` blocker, which cannot be waived. Timeouts and provider errors retry up to `VERIFIER_MAX_ATTEMPTS` within `VERIFIER_TIMEOUT_SECONDS`. No provider error text is recorded.
- **Evidence bundle:** stored in the review (`review.verification`, so it is covered by the approval digest): verifier kind/provider/model/prompt version, settings, input digests, status, attempts, latency, and findings as evidence IDs + offsets + quote hashes. It contains no passage text.
- **Evaluation:** `evaluate_verifier(verifier, cases, repeats)` runs labelled cases (`evals/model_cases.json` shape) repeatedly. Any case not passed on every repeat is a mandatory failure and `blocks_promotion` is true. No partial credit.

## Measured result on the repo's own model cases (deterministic verifier only, 3 repeats)

Passes: unsupported-causal-claim, direct-entailment, evidence-prompt-injection, transient-failure-recovery.
Fails: **selection-bias, stale-evidence, conflicting-results** (these need judgment the rule-based checker does not have).

So `blocks_promotion` is true for the deterministic verifier alone. That is the expected and honest outcome: it is a useful independent floor (citations, figures, explicit negation, term coverage) but not sufficient by itself. A model verifier has not been evaluated because none is configured here.

## Still open (not decided here)

- **ADR (FUT-001):** what qualifies as independent beyond provider+model; what data may be sent to the verifier; choice of verifier provider/model.
- **Paired, held-out evaluation** of the current review path against a configured model verifier, with agreed case-level thresholds, confidence/variation reporting and budget/latency targets. This needs a real verifier endpoint and costs money; it should be an opt-in, redacted run.
- **Adversarial fixtures** still missing for the model path: retracted sources, numerical edge cases beyond exact figure matching, selection bias.
- **Promotion policy:** whether `INDEPENDENT_VERIFICATION` becomes required for release is a release-behavior decision for FUT-080 reviewers; it defaults to `off`.
