"""Real model repeated evaluation. No best-of selection and no Gold in prompts."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
import json
from pathlib import Path

from inhouse.rag_core.tests.qa500_linkage_eval import (
    cases, fresh_holdout_cases, repair_holdout_cases, collect,
)


def holdout_cases():
    # Declared once before invocation, never used for production tuning.
    return [
        dict(id="S1", question="2020년 텅스텐 가격 기록을 월 단위 평균과 관측 건수로 나눠 적어 줘.",
             family="monthly", mineral="텅스텐", year=2020, month=None, measure="value"),
        dict(id="S2", question="2024년 리튬 통상가격의 가장 큰 값과 작은 값의 날짜, 큰 값에서 작은 값을 뺀 차이를 알고 싶어.",
             family="extrema", mineral="리튬", year=2024, month=None, measure="value"),
        dict(id="S3", question="2021년 망간 생산량 기록의 나라별 산술평균과 자료 개수를 함께 정리해 줘.",
             family="monthly", mineral="망간", year=2021, month=None, measure="value", metric="production", domain="production", dimension="country"),
        dict(id="S4", question="니켈 2022년 수입액을 국가별로 묶어 평균과 관측 건수를 각각 적어 줘.",
             family="monthly", mineral="니켈", year=2022, month=None, measure="value", metric="import_value", domain="trade", dimension="country"),
    ]


def final_holdout_cases():
    """Reserved after the arithmetic metadata/column wording correction."""
    return [
        dict(id="T1", question="2025년 니켈은 매월 가격 평균과 관측 건수를 한 표에 정리해 줘.",
             family="monthly", mineral="니켈", year=2025, month=None, measure="value"),
        dict(id="T2", question="2020년 코발트 통상가격의 최대 관측일과 최소 관측일, 두 가격의 차액을 차례로 적어 줘.",
             family="extrema", mineral="코발트", year=2020, month=None, measure="value"),
        dict(id="T3", question="2019년 흑연 생산량을 나라별 평균값과 기록 건수로 함께 정리해 줘.",
             family="monthly", mineral="흑연", year=2019, month=None, measure="value", metric="production", domain="production", dimension="country"),
        dict(id="T4", question="2024년 리튬 수입액의 평균과 관측 횟수를 나라별로 보고 싶어.",
             family="monthly", mineral="리튬", year=2024, month=None, measure="value", metric="import_value", domain="trade", dimension="country"),
    ]


def summarize(records, expected_ids, repeats):
    """Question accounting, never best-of or an incomplete batch as success."""
    expected_ids = set(expected_ids)
    groups = {ident: {} for ident in expected_ids}
    for record in records:
        ident, repeat = record["case"]["id"], record["repeat"]
        if ident not in groups or repeat not in range(1, repeats + 1) or repeat in groups[ident]:
            raise ValueError("invalid or duplicate repeated QA record")
        groups[ident][repeat] = record["status"]
    classifications = {}
    for ident, runs in sorted(groups.items()):
        statuses = list(runs.values())
        if len(runs) != repeats:
            verdict = "PENDING"
        elif all(s == "PASS" for s in statuses):
            verdict = "STABLE_PASS"
        elif all(s == "UNSUPPORTED_CORRECT" for s in statuses):
            verdict = "STABLE_UNSUPPORTED"
        elif any(s in {"PASS", "UNSUPPORTED_CORRECT"} for s in statuses):
            verdict = "VARIABLE"
        else:
            verdict = "FAILED_ALL_REPEATS"
        classifications[ident] = {"verdict": verdict, "runs": runs}
    return {"total_questions": len(groups), "model_requests": len(records),
            "question_counts": dict(Counter(v["verdict"] for v in classifications.values())),
            "request_counts": dict(Counter(r["status"] for r in records)), "questions": classifications}


def constrained_holdout_cases():
    """Frozen before constrained-mode repeats; no production tuning on these."""
    return [
        dict(id="U1", question="구리 2023년 가격 자료는 월마다 몇 건씩 있고 산술평균은 얼마인지 함께 써 줘.",
             family="monthly", mineral="구리", year=2023, month=None, measure="value"),
        dict(id="U2", question="2022년 텅스텐 통상가격이 제일 낮았던 날과 높았던 날을 적고, 높은 값에서 낮은 값을 빼 줘.",
             family="extrema", mineral="텅스텐", year=2022, month=None, measure="value"),
        dict(id="U3", question="2020년 코발트 생산 기록을 나라별로 나누어 평균 생산량과 관측 개수를 같이 보여 줘.",
             family="monthly", mineral="코발트", year=2020, month=None, measure="value", metric="production", domain="production", dimension="country"),
        dict(id="U4", question="2021년 망간 수입액 자료에서 국가마다 관측 횟수와 평균 금액을 정리해 줘.",
             family="monthly", mineral="망간", year=2021, month=None, measure="value", metric="import_value", domain="trade", dimension="country"),
    ]


def boundary_holdout_cases():
    """Frozen before trace/alignment round inference; not used for tuning."""
    return [
        dict(id="V1", question="2020년 코발트 가격을 월별로 정리하되 각 달의 평균과 데이터 개수를 함께 적어 줘.",
             family="monthly", mineral="코발트", year=2020, month=None, measure="value"),
        dict(id="V2", question="알루미늄 2023년 통상가격의 최저와 최고가 관측된 날짜를 각각 적고 최고값에서 최저값을 뺀 결과도 알려줘.",
             family="extrema", mineral="알루미늄", year=2023, month=None, measure="value"),
        dict(id="V3", question="아연의 2022년 생산 자료에서 나라별 기록 수와 평균 생산량을 나란히 정리해 줘.",
             family="monthly", mineral="아연", year=2022, month=None, measure="value", metric="production", domain="production", dimension="country"),
        dict(id="V4", question="흑연 2019년 수입액 자료를 국가마다 묶어 관측 개수와 평균 금액을 보고 싶어.",
             family="monthly", mineral="흑연", year=2019, month=None, measure="value", metric="import_value", domain="trade", dimension="country"),
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--final-holdout", action="store_true")
    parser.add_argument("--structured-output-mode", choices=["json_object", "json_schema"], default="json_object")
    parser.add_argument("--constrained-holdout", action="store_true")
    parser.add_argument("--boundary-holdout", action="store_true")
    args = parser.parse_args()
    selected = boundary_holdout_cases() if args.boundary_holdout else constrained_holdout_cases() if args.constrained_holdout else final_holdout_cases() if args.final_holdout else holdout_cases() if args.holdout else cases() + fresh_holdout_cases() + repair_holdout_cases()
    assert len({c["id"] for c in selected}) == len(selected)
    assert args.repeats > 0
    with args.output.open("x") as stream, ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        futures = {pool.submit(collect, c, args.structured_output_mode): repeat for repeat in range(1, args.repeats + 1) for c in selected}
        for future in as_completed(futures):
            row = future.result()
            row["repeat"] = futures[future]
            stream.write(json.dumps(row, ensure_ascii=False) + "\n"); stream.flush()
            print(row["case"]["id"], row["repeat"], row["status"], flush=True)
