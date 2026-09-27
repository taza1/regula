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
from src.quality_evals import ModelEvalCase, RetrievalEvalCase, evaluate_model_case, evaluate_retrieval
from src.services import create_source_connector


async def run(suite: str, selected_cases: set[str] | None = None) -> dict:
    report = {"retrieval": [], "model": []}
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
            report["retrieval"].append(evaluate_retrieval(case, sources))
    if suite in {"model", "all"}:
        model = create_model_client(get_model_config())
        if model.provider == "mock":
            raise RuntimeError("Model evaluations require MODEL_PROVIDER=azure, foundry, or local_proxy")
        cases = [ModelEvalCase.model_validate(item) for item in json.loads(
            (ROOT / "evals" / "model_cases.json").read_text(encoding="utf-8")
        )]
        if selected_cases:
            cases = [case for case in cases if case.case_id in selected_cases]
        for case in cases:
            report["model"].append(await evaluate_model_case(model, case))
    report["passed"] = all(
        item["passed"] for group in (report["retrieval"], report["model"]) for item in group
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("retrieval", "model", "all"), default="retrieval")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", dest="cases",
                        help="Run only this case ID; repeat for multiple cases")
    args = parser.parse_args()
    report = asyncio.run(run(args.suite, set(args.cases or [])))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
