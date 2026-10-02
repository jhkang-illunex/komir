"""Offline replay separates oracle corrections from compiler corrections.

No model call/reparse and no raw-query repair; immutable captured requirements.
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from inhouse.rag_core.ragkit.semantic_v2 import (
    V2ShadowTrace, SemanticRequirementPlanV2, requirement_contract_issues,
    logical_program_from_requirements, LegacyActionLowerer,
)
from inhouse.rag_core.tests.qa500_linkage_eval import evaluate_trace


def compile_captured(trace):
    if not trace.semantic_plan:
        return trace
    candidate = SemanticRequirementPlanV2.model_validate(trace.semantic_plan)
    if candidate.request_class != "DATA_QUERY":
        return trace
    try:
        issues = requirement_contract_issues(candidate)
        logical = logical_program_from_requirements(candidate)
        if issues:
            raise ValueError("; ".join(issues))
    except ValueError as exc:
        return trace.model_copy(update={"failure_class":"LOGICAL_PLAN_INCOMPLETE", "failure_reason":str(exc),
                                        "logical_program":None, "lowering":[]})
    try:
        calls = LegacyActionLowerer().lower(logical)
    except ValueError as exc:
        return trace.model_copy(update={"failure_class":"LOWERING_FAILURE", "failure_reason":str(exc)})
    return trace.model_copy(update={"failure_class":None, "failure_reason":None,
        "logical_program":logical.to_dict(), "roots":logical.roots,
        "intermediate_nodes":[n.node_id for n in logical.nodes if n.node_id not in logical.roots],
        "lowering":[c.model_dump(mode="json") for c in calls]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    counts = {key: Counter() for key in ("archived", "oracle_only", "compiler_replay")}
    with args.output.open("x") as out:
        for name in ("object", "schema", "unseen-object", "unseen-schema"):
            path = Path('documents/meta/qa500_constrained_20261002')/(name+'.jsonl.gz')
            for line in gzip.decompress(path.read_bytes()).decode().splitlines():
                row = json.loads(line)
                trace = V2ShadowTrace.model_validate(row["trace"])
                oracle = evaluate_trace(row["case"], trace)
                compiled = evaluate_trace(row["case"], compile_captured(trace))
                result = {"source":name, "repeat":row["repeat"], "case":row["case"],
                          "archived_status":row["status"], "oracle_only":oracle, "compiler_replay":compiled}
                counts["archived"][row["status"]] += 1
                counts["oracle_only"][oracle["status"]] += 1
                counts["compiler_replay"][compiled["status"]] += 1
                out.write(json.dumps(result, ensure_ascii=False)+'\n'); out.flush()
    print(json.dumps(counts, indent=2))
