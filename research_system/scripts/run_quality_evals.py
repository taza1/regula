"""Run live retrieval and/or model evaluation fixtures and emit a JSON report."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_model_config
from src.model_client import create_model_client
from src.quality_evals import ModelEvalCase, RetrievalEvalCase, evaluate_model_case, evaluate_retrieval, repeat_model_evaluation
from src.services import create_source_connector


async def run(suite: str, selected_cases: set[str] | None = None, repeats: int = 3) -> dict:
    report = {"retrieval": [], "model": [], "acceptance_policy": {
        "retrieval": "Each case: Precision@K >= configured 0.6, Recall@K >= 0.8 against a non-empty gold set, date accuracy >= 0.9, duplicate rate <= 0.1, at most one failed provider out of three with aggregate results, and explicit independence labels present.",
        "model": f"All cases pass on every one of {repeats} repeats; any mismatch, unsafe review, contract/provider error blocks release."
    }}
    if suite in {"retrieval", "all"}:
        cases = [RetrievalEvalCase.model_validate(item) for item in json.loads(
            (ROOT / "evals" / "retrieval_cases.json").read_text(encoding="utf-8")
        )]
        if selected_cases:
            cases = [case for case in cases if case.case_id in selected_cases]
        connector = create_source_connector()
        for case in cases:
            sources = await connector.search(
                case.query,
                limit=case.limit,
                date_range_start=case.date_range_start,
                date_range_end=case.date_range_end,
            )
            report["retrieval"].append(evaluate_retrieval(case, sources, outcomes=sources.outcomes,
                candidate_count=sources.candidate_count, duplicate_count=sources.duplicate_count))
    if suite in {"model", "all"}:
        model = create_model_client(get_model_config())
        if model.provider == "mock":
            raise RuntimeError("Model evaluations require MODEL_PROVIDER=azure, foundry, or local_proxy")
        report["model_metadata"] = {**model.status(), "evaluation_prompt_version": "quality-evals-v2"}
        cases = [ModelEvalCase.model_validate(item) for item in json.loads(
            (ROOT / "evals" / "model_cases.json").read_text(encoding="utf-8")
        )]
        if selected_cases:
            cases = [case for case in cases if case.case_id in selected_cases]
        repeated = await repeat_model_evaluation(model, cases, repeats=max(1, repeats))
        report["model"] = repeated["runs"]
        report["model_pass_rates"] = repeated["case_pass_rates"]
        report["model_passed"] = repeated["passed"]
    report["passed"] = report.get("model_passed", True) and all(
        item["passed"] for group in (report["retrieval"], report["model"]) for item in group
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("retrieval", "model", "all"), default="retrieval")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", dest="cases",
                        help="Run only this case ID; repeat for multiple cases")
    parser.add_argument("--repeats", type=int, default=3, help="Repeated model-suite runs (release blocks on any failure)")
    args = parser.parse_args()
    report = asyncio.run(run(args.suite, set(args.cases or []), args.repeats))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
