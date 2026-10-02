"""Opt-in real Gemma collection; never imported by production or normal pytest.

Records raw structured output, V2 lowering and schema failures. Does NOT equate
schema/lowering success with semantic correctness. Multi-turn requirements are
collected separately; without executed snapshots they are not E2E PASS.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from common.llm_client import KomirJsonLLM
from rag_core.ragkit.semantic_v2 import (
    SemanticRequirementPlanV2, V2_SEMANTIC_PROMPT, logical_program_from_requirements,
    LegacyActionLowerer,
)


def collect(case, endpoint, model):
    llm = KomirJsonLLM({"base_url": endpoint, "model": model,
                       "temperature": 0, "timeout": 75, "retries": 1})
    outputs = []
    for turn in case["turns"]:
        result = {"turn": turn["turn"], "question": turn["question"], "backend_executed": False}
        started = time.monotonic()
        try:
            call = llm.invoke(task="semantic_requirement_v2", instructions=V2_SEMANTIC_PROMPT,
                payload={"question": turn["question"], "semantic_context": {
                    "previous_requirements": [x.get("semantic_plan") for x in outputs],
                    "result_snapshots": [], "as_of": "2026-10-01",
                }}, output_model=SemanticRequirementPlanV2, max_tokens=1200)
            result["record"] = call.record
            result["semantic_plan"] = call.output.model_dump(mode="json")
            result["status"] = "SCHEMA_VALID_NOT_SEMANTIC_PASS"
            try:
                logical = logical_program_from_requirements(call.output)
                result["logical_program"] = logical.to_dict()
                calls = LegacyActionLowerer().lower(logical)
                result["lowered"] = [c.model_dump(mode="json") for c in calls]
            except (ValueError, TypeError) as exc:
                result.update(status="LOWERING_FAILURE", error=str(exc))
        except Exception as exc:
            result.update(status="PARSER_OR_SCHEMA_FAIL", error=f"{type(exc).__name__}: {exc}")
            if getattr(exc, "record", None):
                result["record"] = exc.record
        result["seconds"] = round(time.monotonic() - started, 3)
        outputs.append(result)
    return {"id": case["id"], "pattern_id": case["pattern_id"], "model": model,
            "multiturn_snapshot_validated": False, "turns": outputs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:52302/v1")
    parser.add_argument("--model", default="gemma-4-26b-a4b")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--variant", choices=['V1','V2','V3','V4'])
    parser.add_argument("--patterns", nargs='*', type=int)
    args = parser.parse_args()
    cases = json.loads(Path(__file__).with_name("qa_build_order2_4_500.json").read_text())["cases"]
    done = set()
    if args.output.exists():
        done = {json.loads(line)["id"] for line in args.output.read_text().splitlines() if line}
    pending = [c for c in cases if c["id"] not in done and (not args.variant or c['variant_id']==args.variant)]
    if args.patterns:
        pending=[c for c in pending if int(c['pattern_id'][4:]) in args.patterns]
    # Representatives before parameter variants, not four near-identical calls at once.
    pending.sort(key=lambda c: (c["variant_id"], c["pattern_id"]))
    with args.output.open("a", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(collect, case, args.endpoint, args.model) for case in pending]
        for future in as_completed(futures):
            result = future.result()
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
            done.add(result["id"])
            print(f"{len(done)}/500 {result['id']} " + ",".join(t["status"] for t in result["turns"]), flush=True)


if __name__ == "__main__":
    main()
