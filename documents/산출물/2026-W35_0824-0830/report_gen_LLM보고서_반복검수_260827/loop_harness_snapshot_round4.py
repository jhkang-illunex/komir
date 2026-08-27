# -*- coding: utf-8 -*-
"""반복 루프 하네스 — DB 프롬프트 기반(실 vLLM) 보고서 전체 재작성 + 오류 점검 +
지침 준수 체크. 리포지토리는 읽기만 하고(어댑터 재사용), 결과는 스크래치패드에.

실행: python3 loop_harness.py [--limit N] [--pages price,map_korea] [--workers 6] [--out PATH]
출력: JSON(콤보별 status/llm_refined/폴백사유/markdown/violations) + 규칙별 집계.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:52302/v1")
os.environ.setdefault("LLM_MODEL", "gemma-4-26b-a4b")
REPORT_GEN = Path("/home/nuri/dev/git/ws/mine_ws/komir/.claude/worktrees/report_summary/inhouse/services/report_gen")
sys.path.insert(0, str(REPORT_GEN))
sys.path.insert(0, str(REPORT_GEN / "scripts"))

import komis_dump_smoke_test as dump  # noqa: E402  (어댑터 재사용, 읽기 전용)
from app._bootstrap import ensure_shared_on_path  # noqa: E402

ensure_shared_on_path()
from shared.config import get_settings  # noqa: E402
from shared.llm_client import KomirJsonLLM  # noqa: E402

from app.analysis import prompt_store  # noqa: E402
from app.analysis.data_sources import DataSourceError  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402
from app.analysis.report_render import render_markdown_report  # noqa: E402
from app.analysis.summary import AnalysisSummaryService  # noqa: E402

SCRATCH = Path(__file__).resolve().parent
_SENT_SPLIT = re.compile(r"(?<=\.)\s+(?=[가-힣A-Za-z0-9(\[])")  # 마침표+공백 뒤에 새 문장이 시작될 때만 분리
_PARTICLE_RO = re.compile(r"([가-힣])(으로|로)(?=[\s,.)])")


def _bad_ro_particles(text: str) -> list[str]:
    """받침 있는 글자(ㄹ 제외) 뒤 '로', 받침 없는 글자·ㄹ받침 뒤 '으로'를 잡는다(예: 미국로, 독일으로)."""
    bad = []
    for m in _PARTICLE_RO.finditer(text):
        ch, particle = m.group(1), m.group(2)
        code = ord(ch) - 0xAC00
        if not 0 <= code <= 11171:
            continue
        jong = code % 28
        needs_eu = jong not in (0, 8)  # 받침 있음 & ㄹ 아님 → '으로'
        if (needs_eu and particle == "로") or (not needs_eu and particle == "으로"):
            bad.append(text[max(0, m.start() - 6): m.end()])
    return bad
_FORMAL_END = re.compile(r"니다\.?\s*$")  # ~합니다/~입니다/~됩니다/~습니다 전부 '니다'로 끝난다
_CAUSAL = re.compile(r"(요인으로|영향으로|때문에|으로 인해|로 인해|원인으로|견인|기인)")
_RAW_MONTH = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
_INTERNAL = re.compile(r"(evidence|근거 id|current_state|allowed_evidence|output_contract|evidence_id)", re.I)
_GRADE_WORDS = ("신중", "주의", "중립", "관심", "기회", "긴장", "안정", "원활")


def _sections(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current = None
    for line in md.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = ""
        elif current and not line.startswith("|") and line.strip():
            out[current] += (" " if out[current] else "") + line.strip()
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]


def check_report(page_id: str, request: dict, response: dict, md: str, llm_refined: bool) -> list[str]:
    """지침(PDF 템플릿 + DB 프롬프트 공통 규칙) 위반 목록. 규칙 id: 접두 G(공통)/P(페이지)."""

    v: list[str] = []
    secs = _sections(md)
    core = secs.get("핵심 진단", "")
    major = secs.get("주요 변화", "")
    position = secs.get("현재 위치", "")
    body = " ".join([core, major, position])
    sentences = _sentences(body)

    # ── 공통(G) ──
    if not core or not major or not position:
        v.append("G01 3개 절(핵심 진단/주요 변화/현재 위치) 중 누락")
    if _INTERNAL.search(body):
        v.append("G02 내부 용어(evidence/근거 id 등) 본문 노출")
    if _CAUSAL.search(body):
        v.append("G03 원인·요인 서술(evidence에 없는 '요인/영향으로/때문에') 포함")
    if llm_refined:
        informal = [s for s in sentences if not _FORMAL_END.search(s)]
        if informal:
            v.append(f"G04 격식체(~습니다/~입니다) 미준수 문장 {len(informal)}건: {informal[0][:40]}…")
        if _RAW_MONTH.search(body):
            v.append("G05 기준월/일을 'YYYY-MM' 원형으로 표기(YYYY년 M월 요구)")
    # 중복 문구(같은 12자 이상 구절이 2회)
    chunks = re.findall(r"[가-힣0-9.,%+\-\s]{14,}?(?=[,.])", body)
    dup = [c.strip() for c, n in Counter(c.strip() for c in chunks if len(c.strip()) >= 14).items() if n >= 2]
    if dup:
        v.append(f"G06 같은 구절 반복: {dup[0][:40]}…")
    if "추세" in body and page_id != "price":
        v.append("G07 금지어 '추세' 사용")
    bad_ro = _bad_ro_particles(body)
    if bad_ro:
        v.append(f"G08 조사 로/으로 오류 {len(bad_ro)}건: {bad_ro[0]}")

    # ── 페이지별(P) — PDF 템플릿 구조 ──
    name = response["mineral"]["name"]
    if page_id == "price":
        if not re.search(r"기준 .*실거래가", core) or name not in core:
            v.append("P-price-01 핵심진단에 '[기준일] 기준 [광종] 실거래가는 [가격]' 구조 없음")
        if "대비" not in major or "%" not in major:
            v.append("P-price-02 주요변화에 '대비 …%' 등락 서술 없음")
        ids = {c for s in response["summary"]["major_changes"] for c in s["evidence_ids"]}
        if "week_avg" in _claim_ids(response) and "전주평균" not in major:
            v.append("P-price-03 전주평균 근거가 있는데 본문에 '전주평균' 없음")
        if "month_avg" in _claim_ids(response) and "전월평균" not in major:
            v.append("P-price-04 전월평균 근거가 있는데 본문에 '전월평균' 없음")
        if "price_streak" in _claim_ids(response) and "연속" not in major:
            v.append("P-price-05 연속 추세 근거가 있는데 '연속 …세' 문장 없음")
        if "최고" not in position or "최저" not in position:
            if "no_price_range" not in _claim_ids(response):
                v.append("P-price-06 현재위치에 조회기간 최고·최저 서술 없음")
    elif page_id in ("indicator_market", "indicator_supply"):
        label = "시장동향지표" if page_id == "indicator_market" else "수급동향지표"
        if label not in core or "점" not in core:
            v.append(f"P-ind-01 핵심진단에 '{label}는 [점수]점' 구조 없음")
        if response.get("grade") and not any(g in core for g in _GRADE_WORDS):
            v.append("P-ind-02 단계가 있는데 핵심진단에 단계명 없음")
        if response.get("grade") and not (re.search(r"단계로 (상승|하락|전환)", major) or re.search(r"개월(째|간| 연속)", major)):
            v.append("P-ind-03 주요변화에 '단계로 상승/하락' 또는 'N개월째 유지' 없음")
        if "평균" not in position:
            v.append("P-ind-04 현재위치에 조회기간 평균 대비 서술 없음")
    elif page_id == "indicator_composite":
        if "광물종합지수" not in core or "포인트" not in core:
            v.append("P-comp-01 핵심진단에 '광물종합지수 … 포인트' 없음")
        if "메이저" not in major or "희소" not in major:
            v.append("P-comp-02 주요변화에 메이저·희소 하위지수 비교 없음")
        if "최고" not in position and "최저" not in position:
            v.append("P-comp-03 현재위치에 조회기간 고저점 서술 없음")
    elif page_id == "map_korea":
        direction = request.get("trade_direction") or "import"
        want = "수입총액" if direction == "import" else "수출총액"
        if want not in core:
            v.append(f"P-korea-01 핵심진단에 '{want}' 없음(조회방향 라벨)")
        if not re.search(r"1위", major) or "%" not in major:
            v.append("P-korea-02 주요변화에 1위국·비중 없음")
        if "top3_concentration" in _claim_ids(response) and "3개국" not in major:
            v.append("P-korea-03 CR3 근거가 있는데 '상위 3개국' 서술 없음")
    elif page_id == "map_global":
        if "교역 총액" not in core and "총액" not in core:
            v.append("P-global-01 핵심진단에 세계 교역 총액 없음")
        if "→" not in major and not re.search(r"에서 .{1,20}(으로|로) (향하|가|의)", major):
            v.append("P-global-02 주요변화에 원산지→도착지 루트 없음")
        if "대한민국" not in major:
            v.append("P-global-03 대한민국 순위/부재 문장 없음")
    elif page_id == "map_mineral":
        if not 5 <= len(sentences) <= 8 and llm_refined:
            v.append(f"P-map-01 전체 문장수 {len(sentences)} (5~8 요구)")
        if "1위" not in major or "2위" not in major:
            v.append("P-map-02 주요변화에 1·2위 국가 없음")
        if "상위 3개국" not in position and "상위 5개국" not in position:
            v.append("P-map-03 현재위치에 CR3/CR5 집중도 없음")
        if "성장" in body:
            v.append("P-map-04 '성장' 표현(증가/감소 요구)")
    elif page_id == "price_group":
        if "전주 대비 평균" not in core:
            v.append("P-grp-01 핵심진단에 '전주 대비 평균 …%' 없음")
        if "강세" not in major and "하락세" not in major and "보합세" not in major:
            v.append("P-grp-02 주요변화에 강세/약세 광종군 없음")
    return v


def _claim_ids(response: dict) -> set[str]:
    return {c for sec in ("core_diagnosis", "major_changes", "current_position") for s in response["summary"][sec] for c in s["evidence_ids"]} | {
        m["id"] for m in response.get("detected_patterns", []) if False
    } | _metric_claim_ids(response)


def _metric_claim_ids(response: dict) -> set[str]:
    # 규칙기반 응답에는 모든 claim이 문장으로 있으므로 evidence_ids 합집합이 곧 claim 집합.
    # LLM 정제 응답도 검증기가 "모든 id 정확히 1회"를 강제하므로 동일.
    return set()


def build_combos(pages: set[str] | None, limit: int | None) -> list[tuple[str, str, dict]]:
    L = dump._load
    combos: list[tuple[str, str, dict]] = []
    combos += [("price", k, r) for k, r in dump.adapt_price_pages(L("komis_01_base_metals.json"), "base_metals")]
    combos += [("price", k, r) for k, r in dump.adapt_price_pages(L("komis_02_minor_metals.json"), "minor_metals")]
    combos += [("indicator_composite", k, r) for k, r in dump.adapt_mineral_index(L("komis_03_mineral_index.json"))]
    combos += [("indicator_market", k, r) for k, r in dump.adapt_indicator_pages(L("komis_04_market_trend.json"), "indicator_market", "market_trend")]
    combos += [("indicator_supply", k, r) for k, r in dump.adapt_indicator_pages(L("komis_05_supply_trend.json"), "indicator_supply", "supply_trend")]
    combos += [("map_korea", k, r) for k, r in dump.adapt_map_korea(L("komis_06_supply_map_korea.json"))]
    combos += [("map_global", k, r) for k, r in dump.adapt_map_global(L("komis_07_supply_map_global.json"))]
    combos += [("map_mineral", k, r) for k, r in dump.adapt_mineral_map(L("komis_08_mineral_map.json"))]
    if pages:
        combos = [c for c in combos if c[0] in pages]
    if limit:
        per: dict[str, int] = {}
        picked = []
        for c in combos:
            if per.get(c[0], 0) < limit:
                picked.append(c); per[c[0]] = per.get(c[0], 0) + 1
        combos = picked
    return combos


def run(args) -> dict:
    s = get_settings()
    n_prompts = prompt_store.reload()
    import threading

    class Capturing:
        """LLM 시도별 출력(검증 실패해 폴백된 것 포함)을 스레드별로 기록한다 — 진단용."""

        def __init__(self, inner):
            self.inner = inner
            self.local = threading.local()

        def start(self):
            self.local.attempts = []

        def invoke(self, **kw):
            t0 = time.time()
            try:
                inv = self.inner.invoke(**kw)
                self.local.attempts.append({"elapsed": round(time.time() - t0, 1), "output": inv.output.model_dump(mode="json"),
                                            "allowed": [(x["evidence_id"], x["section"]) for x in kw["payload"]["allowed_evidence"]]})
                return inv
            except Exception as exc:  # noqa: BLE001
                self.local.attempts.append({"elapsed": round(time.time() - t0, 1), "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                raise

    llm = Capturing(KomirJsonLLM({**s.llm_cfg(), "timeout": args.llm_timeout, "retries": 1}))
    service = AnalysisSummaryService(None, llm=llm)
    combos = build_combos(set(args.pages.split(",")) if args.pages else None, args.limit)
    print(f"DB prompts loaded: {n_prompts} | combos: {len(combos)} | workers: {args.workers} | model: {s.LLM_MODEL}")

    def one(item):
        page_id, key, request = item
        entry = {"combo_key": key, "page_id": page_id}
        t0 = time.time()
        llm.start()
        try:
            resp = service.analyze(AnalysisSummaryRequest(**request))
            entry["llm_attempts"] = list(llm.local.attempts)
            rd = json.loads(resp.model_dump_json())
            md = render_markdown_report(resp)
            entry.update(status="ok", llm_refined=resp.llm_refined, warnings=resp.data_quality.warnings, markdown=md,
                         violations=check_report(page_id, request, rd, md, resp.llm_refined), summary=rd["summary"])
        except DataSourceError as exc:
            entry.update(status="NO_DATA", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            entry.update(status="INTERNAL_ERROR", error=f"{type(exc).__name__}: {exc}")
        entry["elapsed"] = round(time.time() - t0, 1)
        return entry

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        entries = list(ex.map(one, combos))
    elapsed = time.time() - t0

    by_page: dict[str, dict] = {}
    rule_counter: Counter = Counter()
    fallback_reasons: Counter = Counter()
    for e in entries:
        p = by_page.setdefault(e["page_id"], Counter())
        p["count"] += 1
        p[e["status"]] += 1
        if e["status"] == "ok":
            p["llm_refined"] += int(e["llm_refined"])
            p["violating"] += int(bool(e["violations"]))
            for rule in e["violations"]:
                rule_counter[rule.split(" ")[0]] += 1
            if not e["llm_refined"]:
                for w in e["warnings"]:
                    if w.startswith("LLM "):
                        fallback_reasons[w[:80]] += 1
    result = {"elapsed_s": round(elapsed), "by_page": {k: dict(v) for k, v in by_page.items()},
              "rule_counter": dict(rule_counter), "fallback_reasons": dict(fallback_reasons), "entries": entries}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "entries"}, ensure_ascii=False, indent=1))
    total = len(entries)
    errors = sum(1 for e in entries if e["status"] == "INTERNAL_ERROR")
    fallbacks = sum(1 for e in entries if e["status"] == "ok" and not e["llm_refined"])
    violating = sum(1 for e in entries if e["status"] == "ok" and e["violations"])
    print(f"TOTAL={total} INTERNAL_ERROR={errors} NO_DATA={sum(1 for e in entries if e['status']=='NO_DATA')} "
          f"LLM_FALLBACK={fallbacks} VIOLATING={violating} elapsed={elapsed:.0f}s")
    print("LOOP_CLEAN" if errors == 0 and fallbacks == 0 and violating == 0 else "LOOP_DIRTY")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="페이지당 최대 콤보 수")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--llm-timeout", type=int, default=40)
    ap.add_argument("--out", type=Path, default=SCRATCH / "loop_results.json")
    run(ap.parse_args())
