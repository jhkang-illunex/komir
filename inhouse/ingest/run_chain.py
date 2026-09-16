# -*- coding: utf-8 -*-
"""ingest 체인 진입점(2026-09-16) — 컨테이너 supercronic이든 호스트 crontab이든 이 한 줄로 부른다.

    cd inhouse && python -m ingest.run_chain [--trigger cron|manual] [--steps a,b,...] [--skip x]
                                             [--prune-apply] [--no-lock] [--list]

단계(순서 고정 — README "doc_chunk writer 2개" 불변식: pgvector_index(전량) → pgvector_okf(src 단위)):
  shareable        외부공개 PDF zip → processing/shareable (extract.pdf_extract_shareable)
  restricted       비축월보 zip → processing/restricted_diagnosis_only (RAG 금지 분리 유지)
  okf              landing 전체 → data_lake/okf_documents (okf.build_okf_documents --what all,
                   원본이 없는 그룹은 건너뜀)
  pageindex        okf → data_lake/pageindex_trees. LLM 헬스체크 통과 시 노드 요약 포함, 미응답이면
                   `--no-summary`(구조만)로 진행 — 예전엔 통째로 건너뛰어 그 주 신규 문서가 PageIndex
                   조회에서 빠졌다
  pgvector_index   artifacts 갈래 doc_chunk 재적재(source_type 단위)
  pgvector_okf     PDF 그룹 갈래 doc_chunk 재적재(src 단위)
  backfill         doc_chunk.pub_date 백필
  prune            landing에서 사라진 원본의 okf/pageindex/doc_chunk 정리 — 기본 dry-run 보고,
                   `--prune-apply`일 때만 삭제(ingest/prune.py의 안전장치 적용)

각 단계는 서브프로세스(`python -m ingest.<module>`)로 돌려 모듈별 `ingest.pipeline_run` 상태
기록이 그대로 남는다. okf·pgvector_* 실패는 체인 중단(이후 단계가 빈 입력으로 지우는 일 방지),
pageindex·backfill·prune 실패는 기록만 하고 계속. 동시 실행은 processing/_locks/chain.lock(flock)으로
막고, 표준출력은 processing/_logs/chain_<시각>.log에 함께 남긴다(cron 환경에서 stdout이 사라져도
추적 가능). `INGEST_TRIGGERED_BY`는 `--trigger`로 export(모듈들이 trigger='cron'|'manual' 기록).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest import status as ingest_status  # noqa: E402
from ingest.paths import get_paths  # noqa: E402
from ingest.registry import describe  # noqa: E402


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]
    critical: bool          # True면 실패 시 체인 중단


def _llm_alive(timeout: float = 10.0) -> bool:
    base = (os.environ.get("LLM_BASE_URL") or "").rstrip("/")
    if not base:
        try:
            from common.config import get_settings

            base = (get_settings().LLM_BASE_URL or "").rstrip("/")
        except Exception:  # noqa: BLE001
            return False
    if not base:
        return False
    try:
        urllib.request.urlopen(base + "/models", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def build_steps(*, prune_apply: bool, llm_alive: bool | None = None) -> list[Step]:
    """단계 목록(순서 고정). llm_alive=None이면 헬스체크를 실제로 수행."""
    alive = _llm_alive() if llm_alive is None else llm_alive
    pageindex_argv: tuple[str, ...] = ("ingest.pageindex.build_pageindex_trees",)
    if not alive:
        pageindex_argv += ("--no-summary",)
    prune_argv: tuple[str, ...] = ("ingest.prune",) + (("--apply",) if prune_apply else ())
    return [
        Step("shareable", ("ingest.extract.pdf_extract_shareable",), critical=False),
        Step("restricted", ("ingest.extract.pdf_extract_restricted",), critical=False),
        Step("okf", ("ingest.okf.build_okf_documents", "--what", "all"), critical=True),
        Step("pageindex", pageindex_argv, critical=False),
        Step("pgvector_index", ("ingest.vectorize.build_pgvector_index",), critical=True),
        Step("pgvector_okf", ("ingest.vectorize.build_pgvector_okf",), critical=True),
        Step("backfill", ("ingest.vectorize.backfill_doc_chunk_pub_date",), critical=False),
        Step("prune", prune_argv, critical=False),
    ]


STEP_NAMES = tuple(s.name for s in build_steps(prune_apply=False, llm_alive=True))


class _Tee:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")

    def write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        self._f.write(text)
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def run(steps: list[Step], *, log: _Tee, env: dict[str, str]) -> dict:
    results: dict[str, dict] = {}
    for step in steps:
        started = time.monotonic()
        log.write(f"\n--- [{step.name}] python -m {' '.join(step.argv)} — {datetime.now():%F %T}\n")
        proc = subprocess.run([sys.executable, "-m", *step.argv], cwd=str(_INHOUSE_ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.write(proc.stdout or "")
        took = round(time.monotonic() - started, 1)
        ok = proc.returncode == 0
        results[step.name] = {"rc": proc.returncode, "sec": took}
        log.write(f"--- [{step.name}] {'OK' if ok else 'FAIL'} rc={proc.returncode} {took}s\n")
        if not ok and step.critical:
            log.write(f"!!! 필수 단계 {step.name} 실패 — 이후 단계 중단(빈 입력으로 기존 데이터를 지우는 일 방지)\n")
            results["aborted_at"] = step.name
            break
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ingest 체인(landing → processing → data_lake → pgvector)")
    ap.add_argument("--trigger", choices=("cron", "manual"), default="manual")
    ap.add_argument("--steps", default=None, help=f"쉼표 목록(순서는 고정): {','.join(STEP_NAMES)}")
    ap.add_argument("--skip", action="append", default=[], help="건너뛸 단계(반복 가능)")
    ap.add_argument("--prune-apply", action="store_true", help="prune 단계에서 실제 삭제(기본 dry-run)")
    ap.add_argument("--no-lock", action="store_true", help="동시 실행 락 생략(테스트용)")
    ap.add_argument("--list", action="store_true", help="경로·그룹·단계만 출력하고 종료")
    a = ap.parse_args(argv)

    paths = get_paths()
    steps = build_steps(prune_apply=a.prune_apply, llm_alive=True if a.list else None)
    if a.steps:
        wanted = {s.strip() for s in a.steps.split(",") if s.strip()}
        unknown = wanted - set(STEP_NAMES)
        if unknown:
            ap.error(f"unknown steps: {sorted(unknown)}")
        steps = [s for s in steps if s.name in wanted]
    steps = [s for s in steps if s.name not in set(a.skip)]

    if a.list:
        print(json.dumps({"paths": paths.as_dict(), "groups": describe(),
                          "steps": [{"name": s.name, "argv": list(s.argv), "critical": s.critical} for s in steps]},
                         ensure_ascii=False, indent=1))
        return 0

    env = dict(os.environ)
    env["INGEST_TRIGGERED_BY"] = a.trigger
    # .env의 PDF_MAXPAGES=40(geo GKG용)이 그대로 주입되면 연간보고서가 40쪽에서 잘린다(2026-08-11 실측).
    env.setdefault("PDF_MAXPAGES", "500")
    env.setdefault("OCR_MAXPAGES", "60")
    if env["PDF_MAXPAGES"] == "40":
        env["PDF_MAXPAGES"] = "500"

    lock_fh = None
    if not a.no_lock:
        paths.locks.mkdir(parents=True, exist_ok=True)
        lock_fh = (paths.locks / "chain.lock").open("w")
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"{datetime.now():%F %T} 이미 실행 중(lock) — 종료")
            return 0

    log = _Tee(paths.logs / f"chain_{datetime.now():%Y%m%d_%H%M%S}.log")
    try:
        log.write(f"=== {datetime.now():%F %T} ingest 체인 시작 trigger={a.trigger}\n경로: {json.dumps(paths.as_dict(), ensure_ascii=False)}\n"
                  f"그룹: {json.dumps(describe(), ensure_ascii=False)}\n단계: {[s.name for s in steps]}\n")
        with ingest_status.pipeline_run("chain.run_chain", args={"trigger": a.trigger, "steps": [s.name for s in steps],
                                                             "prune_apply": a.prune_apply}) as run_handle:
            results = run(steps, log=log, env=env)
            run_handle.metrics.update(results)
        log.write(f"=== {datetime.now():%F %T} 종료 — {json.dumps(results, ensure_ascii=False)}\n")
        return 1 if "aborted_at" in results else 0
    finally:
        log.close()
        if lock_fh is not None:
            lock_fh.close()


if __name__ == "__main__":
    raise SystemExit(main())
