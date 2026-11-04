"""Keyword-vs-vector retrieval comparison on labelled evidence (FUT-020).

This reports; it does not decide. Pass thresholds only after reviewers have agreed
them. Without thresholds ``passed`` is None, so a run of this harness can never be
read as having cleared a bar nobody set. Metrics implemented: Precision@K,
Recall@K and MRR, plus latency and how often a mode degraded to keyword. Date
accuracy, duplicate leakage, independence grouping and contradiction discovery
remain in ``quality_evals.py`` for live provider cases.
"""
from __future__ import annotations

import time
from statistics import mean
from typing import Any, Optional, Sequence


def precision_recall_rr(ranked_ids: Sequence[str], relevant: set[str], k: int) -> tuple[float, float, float]:
    top = list(ranked_ids)[:k]
    hits = [i for i in top if i in relevant]
    precision = len(hits) / len(top) if top else 0.0
    recall = len(set(hits)) / len(relevant) if relevant else 0.0
    rr = next((1.0 / rank for rank, item in enumerate(top, start=1) if item in relevant), 0.0)
    return precision, recall, rr


async def compare_retrieval_modes(
    evidence_service,
    tenant_id: str,
    project_id: str,
    run_id: str,
    cases: Sequence[dict[str, Any]],
    k: int = 10,
    modes: Sequence[str] = ("keyword", "semantic", "hybrid"),
    thresholds: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Run every case in every mode and aggregate.

    ``cases``: ``{"case_id", "query", "relevant_evidence_ids", "split"?}``. Keep
    ``split: "held_out"`` cases out of any tuning of weights or thresholds.
    ``thresholds``: optional ``{"precision", "recall", "mrr"}`` minimums.
    """
    report: dict[str, Any] = {"k": k, "cases": len(cases), "modes": {}, "thresholds": thresholds}
    for mode in modes:
        per_case, latencies, degraded = [], [], 0
        for case in cases:
            started = time.perf_counter()
            outcome = await evidence_service.search_evidence_detailed(
                tenant_id, project_id, run_id, case["query"], mode, k)
            latencies.append((time.perf_counter() - started) * 1000)
            degraded += outcome["mode"] != mode
            ranked = [e.evidence_id for e in outcome["results"]]
            p, r, rr = precision_recall_rr(ranked, set(case["relevant_evidence_ids"]), k)
            per_case.append({"case_id": case["case_id"], "split": case.get("split", "tuning"),
                             "precision": p, "recall": r, "rr": rr,
                             "mode_used": outcome["mode"],
                             "degraded_reason": outcome["degraded_reason"]})
        summary = {
            "precision_at_k": mean(c["precision"] for c in per_case) if per_case else 0.0,
            "recall_at_k": mean(c["recall"] for c in per_case) if per_case else 0.0,
            "mrr": mean(c["rr"] for c in per_case) if per_case else 0.0,
            "mean_latency_ms": mean(latencies) if latencies else 0.0,
            "degraded_cases": degraded,
            "per_case": per_case,
        }
        if thresholds:
            summary["passed"] = (
                summary["precision_at_k"] >= thresholds.get("precision", 0.0)
                and summary["recall_at_k"] >= thresholds.get("recall", 0.0)
                and summary["mrr"] >= thresholds.get("mrr", 0.0)
                and degraded == 0)
        else:
            summary["passed"] = None
        report["modes"][mode] = summary
    base = report["modes"].get("keyword")
    if base:
        report["delta_vs_keyword"] = {
            mode: {key: summary[key] - base[key]
                   for key in ("precision_at_k", "recall_at_k", "mrr")}
            for mode, summary in report["modes"].items() if mode != "keyword"}
    return report
