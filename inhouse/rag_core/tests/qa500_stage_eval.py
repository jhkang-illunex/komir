"""Focused failed-case and preregistered holdout evaluation; no production SSE."""
import argparse
import gzip
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path

from inhouse.rag_core.tests.qa500_linkage_eval import collect
from inhouse.rag_core.tests.qa500_stability_eval import summarize


def failed_cases():
    selected = {}
    for path in sorted(Path("documents/meta/qa500_trace_boundary_20261002").glob("*rejudged*.gz")):
        for line in gzip.open(path, "rt"):
            row = json.loads(line)
            if row["status"] not in {"PASS", "UNSUPPORTED_CORRECT"}:
                selected[row["case"]["id"]] = row["case"]
    assert len(selected) == 7
    return list(selected.values())


def holdout_cases():
    # Frozen before the first model call. No new synthetic rows or production rules.
    return [
        dict(id="W1", question="2021년 아연의 통상가격을 기준으로 가장 낮았던 날과 가장 높았던 날을 적고 두 값의 차이(최대-최소)도 계산해 줘.",
             family="extrema", mineral="아연", year=2021, month=None, measure="value"),
        dict(id="W2", question="2024년 텅스텐 통상가격의 최대 관측값과 최소 관측값은 날짜가 언제야? 두 값의 차액도 함께 부탁해.",
             family="extrema", mineral="텅스텐", year=2024, month=None, measure="value"),
        dict(id="W3", question="2022년 리튬 가격 자료를 월별로 묶어서 관측 횟수와 산술평균을 빠짐없이 보여 줘.",
             family="monthly", mineral="리튬", year=2022, month=None, measure="value"),
        dict(id="W4", question="2023년 구리 생산 기록의 국가별 평균과 관측 건수를 각각 정리해 줘.",
             family="monthly", mineral="구리", year=2023, month=None, measure="value", metric="production", domain="production", dimension="country"),
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    cases = holdout_cases() if args.holdout else failed_cases()
    records = []
    with args.output.open("x") as stream, ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        futures = {pool.submit(collect, case): repeat for repeat in (1, 2) for case in cases}
        for future in as_completed(futures):
            row = future.result()
            row["repeat"] = futures[future]
            records.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            print(row["case"]["id"], row["repeat"], row["status"], flush=True)
    print(json.dumps(summarize(records, [c["id"] for c in cases], 2), ensure_ascii=False))
