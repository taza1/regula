"""Human adjudication of review blockers, bound to the exact review it answers.

A review with blockers leaves the run in ``adjudication_required``. The review
record itself stays immutable. A reviewer records one decision per blocker in a
separate ``adjudication`` record that stores the digest of the review it
answers; approval and release then fold that record into the bundle digest, so
a decision can neither be reused for a different review nor altered after
approval. A new review replaces the model_review and thereby orphans any older
decisions.

What a reviewer may do depends on the blocker category assigned by the review:
  * model, fact_check - may be accepted_limitation or false_positive
  * security          - false_positive only (a suspected injection is never an
                        acceptable limitation)
  * integrity, policy - cannot be waived; fix the cause and re-review
Every decision needs a written rationale and a reviewer/admin role.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.audit import append_audit
from src.review_pipeline import digest, read_entity, write_entity

DECISIONS = {"accepted_limitation", "false_positive"}
ALLOWED_DECISIONS = {
    "model": DECISIONS,
    "fact_check": DECISIONS,
    "verification": DECISIONS,  # independent verifier disagreement: a human weighs it
    "security": {"false_positive"},
    "integrity": set(),
    "policy": set(),
}


def _decision_error(item: dict, decision: str) -> Optional[str]:
    allowed = ALLOWED_DECISIONS.get(item["category"], set())
    if decision in allowed:
        return None
    if not allowed:
        return (f"A {item['category']} blocker cannot be waived; "
                "fix the cause and run a new review.")
    return f"A {item['category']} blocker may only be cleared as: {', '.join(sorted(allowed))}."


def valid_adjudication(db, key, review: dict) -> Optional[dict]:
    """Return the adjudication only if it fully and validly answers ``review``."""

    record = read_entity(db, "adjudication", key, key[2])
    items = review.get("blocker_items") or []
    if not record or not items or record.get("review_digest") != digest(review):
        return None
    decisions = {d["blocker_id"]: d for d in record.get("decisions", [])}
    for item in items:
        decision = decisions.get(item["id"])
        if (not decision or not (decision.get("rationale") or "").strip()
                or _decision_error(item, decision["decision"])):
            return None
    return record


class AdjudicationService:
    def __init__(self, store):
        self.store = store

    def status(self, key) -> dict:
        with self.store._connect() as db:
            run = read_entity(db, "run", key, key[2])
            review = read_entity(db, "model_review", key, key[2])
            if not run or not review:
                raise ValueError("No review exists for this run.")
            record = read_entity(db, "adjudication", key, key[2])
        current = record if record and record.get("review_digest") == digest(review) else None
        decided = {d["blocker_id"]: d for d in (current or {}).get("decisions", [])}
        items = [{**item, "decision": decided.get(item["id"]),
                  "allowed_decisions": sorted(ALLOWED_DECISIONS.get(item["category"], set()))}
                 for item in review.get("blocker_items", [])]
        return {"state": run["state"], "passed": review.get("passed", False), "items": items,
                "resolved": bool(items) and all(item["decision"] for item in items)}

    def decide(self, key, user: str, blocker_id: str, decision: str, rationale: str) -> dict:
        if not rationale or not rationale.strip():
            raise ValueError("A written rationale is required for every adjudication decision.")
        if decision not in DECISIONS:
            raise ValueError(f"Decision must be one of: {', '.join(sorted(DECISIONS))}.")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = read_entity(db, "project", key, key[1])
            if not project or not set(project.get("members", {}).get(user, [])) & {"reviewer", "admin"}:
                raise PermissionError("Current project membership does not authorize this action.")
            run = read_entity(db, "run", key, key[2])
            review = read_entity(db, "model_review", key, key[2])
            if not run or run["state"] != "adjudication_required" or not review:
                raise ValueError("The run is not awaiting adjudication.")
            item = next((i for i in review.get("blocker_items", []) if i["id"] == blocker_id), None)
            if not item:
                raise ValueError("Unknown blocker for the current review.")
            error = _decision_error(item, decision)
            if error:
                raise ValueError(error)

            review_digest = digest(review)
            record = read_entity(db, "adjudication", key, key[2])
            if not record or record.get("review_digest") != review_digest:
                record = {"tenant_id": key[0], "project_id": key[1], "run_id": key[2],
                          "report_revision": run["report_revision"],
                          "review_digest": review_digest, "decisions": []}
            record["decisions"] = [d for d in record["decisions"] if d["blocker_id"] != blocker_id]
            record["decisions"].append({
                "blocker_id": blocker_id, "decision": decision, "rationale": rationale.strip(),
                "reviewer_id": user, "at": datetime.now(timezone.utc).isoformat()})
            write_entity(db, "adjudication", key, key[2], record)
            append_audit(db, key, user, "blocker.adjudicated", blocker_id,
                         {"decision": decision, "category": item["category"]})

            if valid_adjudication(db, key, review):
                run["state"] = "awaiting_approval"
                run["updated_time"] = datetime.now(timezone.utc).isoformat()
                write_entity(db, "run", key, key[2], run)
                append_audit(db, key, user, "adjudication.completed", key[2],
                             {"review_digest": review_digest})
            return record
