# -*- coding: utf-8 -*-
"""보고서 지시문과 페이지별 출력 설정.

기본 지시문은 resources/prompts/*.md가 정본이며 PROMPTS는 시드/기존 호출자용
동일 문자열을 제공한다. DB 편집·reload·잘못된 설정의 기본값 폴백을 유지한다.
page_prompt_scope에서 한 요청의 설정과 지시문을 확정해 계산·LLM·검증이 공유한다.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import prompt_store
from .additional_summary import ADDITIONAL_PAGE_CONTEXTS, SummaryPageContext
from .komir_summary import KOMIR_PAGE_CONTEXTS
from .models import (
    CORE_DIAGNOSIS_MAX_SENTENCES,
    CURRENT_POSITION_MAX_SENTENCES,
    MAJOR_CHANGES_MAX_SENTENCES,
    AnalysisSummaryResponse,
)
from .policy import PagePolicy, load_page_policy

def _read_prompt(filename: str) -> str:
    return (Path(__file__).parent / "resources" / "prompts" / filename).read_text(encoding="utf-8")


# 아래 10개 상수 + `PROMPTS`가 분석요약 프롬프트의 **단일 소스**다(2026-08-27,
# skeptic 감사 SC-004). 이전에는 `seed_prompts.py`(DB 시드)와 이 파일(DB 미접속
# 폴백)이 같은 문구를 따로 들고 있어 10키 중 9키가 조용히 어긋나 있었다 — 예:
# price 폴백은 "연속기간 언급 금지"였는데 계산기는 `price_streak` 근거를 만들고
# 검증기는 모든 evidence_id 사용을 요구하므로, DB가 죽은 동안 price LLM 출력이
# 항상 검증 실패→규칙기반으로 떨어졌다. 이제 `seed_prompts.py`가 여기 `PROMPTS`를
# import해 DB에 심는다(런타임 모듈이 시딩 스크립트에 의존하지 않는 방향).
# 2026-08-26: 발주처 제공 KOMIS 템플릿 PDF 2종 + 8개 페이지 실데이터 덤프를
# 근거로 다시 썼다(위 모듈 docstring "실제 반영 범위" 참고). 계산 레이어가
# 만드는 EvidenceClaim 범위를 벗어나는 지시는 넣지 않았다 — 검증기
# (`summary.py::_validate_llm_summary`)가 근거 밖 숫자·단계명·원인 서술을
# 걸러 규칙기반으로 되돌리기 때문에, 지어내도 실제로 적용되지 않는다.
SUMMARY_COMMON_INSTRUCTIONS = _read_prompt("summary_common.md")

MARKET_SUMMARY_INSTRUCTIONS = _read_prompt("market_summary.md")

SUPPLY_SUMMARY_INSTRUCTIONS = _read_prompt("supply_summary.md")

COMPOSITE_SUMMARY_INSTRUCTIONS = _read_prompt("composite_summary.md")

MINERAL_MAP_SUMMARY_INSTRUCTIONS = _read_prompt("mineral_map_summary.md")

PRICE_FORECAST_SUMMARY_INSTRUCTIONS = _read_prompt("price_forecast_summary.md")

# 2026-08-26: `price`/`map_korea`/`map_global` LLM 배선 추가와 함께 실제
# 지시문으로 채웠다(위 모듈 docstring "실제 반영 범위" 참고). `komir_summary.py`가
# 만드는 EvidenceClaim id(current_state·day_over_day·week_avg/month_avg/
# year_avg·period_range, 또는 current_state·top1_country·top3_concentration·
# period_total_change) 범위 안에서만 쓰도록 지시한다.
PRICE_SUMMARY_INSTRUCTIONS = _read_prompt("price_summary.md")

MAP_KOREA_SUMMARY_INSTRUCTIONS = _read_prompt("map_korea_summary.md")

MAP_GLOBAL_SUMMARY_INSTRUCTIONS = _read_prompt("map_global_summary.md")

PRICE_GROUP_SUMMARY_INSTRUCTIONS = _read_prompt("price_group_summary.md")

PROMPTS = {
    "summary_common": SUMMARY_COMMON_INSTRUCTIONS,
    "indicator_market": MARKET_SUMMARY_INSTRUCTIONS,
    "indicator_supply": SUPPLY_SUMMARY_INSTRUCTIONS,
    "indicator_composite": COMPOSITE_SUMMARY_INSTRUCTIONS,
    "map_mineral": MINERAL_MAP_SUMMARY_INSTRUCTIONS,
    "forecast_price": PRICE_FORECAST_SUMMARY_INSTRUCTIONS,
    # 2026-08-27 price page_id 분리 — 비철금속/희소금속 지시문 내용은 그룹에 무관하게
    # 동일하다(비교광종 조건절은 데이터가 없으면 그냥 트리거되지 않는다, §models.py
    # validate_period가 이제 요청 단계에서 강제) — 그래서 같은 상수를 공유한다.
    "price_base_metals": PRICE_SUMMARY_INSTRUCTIONS,
    "price_minor_metals": PRICE_SUMMARY_INSTRUCTIONS,
    # 2026-08-28 — 같은 이유로 공유(§komir_summary.py::KOMIR_PAGE_CONTEXTS 주석).
    "price_iron_energy": PRICE_SUMMARY_INSTRUCTIONS,
    "price_other": PRICE_SUMMARY_INSTRUCTIONS,
    "map_korea": MAP_KOREA_SUMMARY_INSTRUCTIONS,
    "map_global": MAP_GLOBAL_SUMMARY_INSTRUCTIONS,
    "price_group": PRICE_GROUP_SUMMARY_INSTRUCTIONS,
}


#: 페이지별 섹션 문장수 계약 (최소, 최대) — LLM에 보내는 `output_contract`와
#: `summary.py::_validate_llm_summary`가 **같은 상수**를 쓴다(2026-08-27 skeptic
#: 감사 SC-005: 이전엔 두 파일에 복제돼 "글자 그대로 일치해야 한다"는 주석으로만
#: 묶여 있었다). map_mineral은 select_and_synthesize 모드라 별도 상수.
SECTION_SENTENCE_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    # 2026-08-27 반복 루프 1회차: 실 vLLM 384건 파일럿에서 major_changes 근거
    # 3개(grade_streak·grade_transition·largest_monthly_score_change)를 1문장에
    # 넣지 못해 근거 누락/절 이동으로 폴백하는 사례 → (1,2)로 완화.
    "indicator_market": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
    # current_position 상한 4 — 2026-09-10 사용자 후속 지시로 supply_key_factors
    # 결합 문장(300자 상한 초과 위험, HHI 해석문 추가로 확정)을 요인별 4개
    # 개별 근거(supply_factor_price_risk 등)로 분리하면서 상향(기존 2).
    "indicator_supply": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 4)},
    # core_diagnosis: 2026-09-10 발주처 피드백([3])으로 신설된
    # period_value_comparison(전주/전월/전년동기 값+등락률)까지 더하면 최대
    # 3개(current_state·medium_long_term_contrast·period_value_comparison)라
    # (1,1)→(1,3).
    # major_changes: 2026-09-10 발주처 피드백([4]) — 기존 composite_recent_
    # changes·weekly/monthly/yearly_subindex_comparison·index_top_weighted_
    # minerals(최대 5개, 세 지수를 한 문장에 섞어 비교)를 `summary.py::
    # _replace_composite_subindex_narrative`가 광물종합·메이저금속·희소금속
    # 지수별 자기완결 문장 3개로 통째로 대체했다 — 지수별 문장은 서로 다른
    # evidence_id 1개씩만 인용해야 하므로(섞지 말라는 요청 취지) 문장 수는
    # 항상 claim 수(최대 3)와 같다. (1,5)→(1,3).
    "indicator_composite": {"core_diagnosis": (1, 3), "major_changes": (1, 3), "current_position": (1, 1)},
    "forecast_price": {"core_diagnosis": (1, 1), "major_changes": (1, 1), "current_position": (1, 1)},
    # price의 current_position은 (1,2) — 비교광종(compare_observations)이 있으면
    # compare_overall_change 근거 1문장이 더 붙는다(2026-08-26. 2026-08-30 확인:
    # 비교광종은 price_* 4종 공통 기능이라 base_metals/iron_energy/other도
    # 동일하게 해당). major_changes는 근거가 최대 5개(전일·전주·전월·전년·
    # 연속)라 (1,3)(루프 1회차 완화).
    # 2026-08-31 사용자 통계확장 피드백으로 current_position이 (1,2)→(1,9)로
    # 커졌다 — 신규 6개 층(변동성·이동평균+RSI·백분위·낙폭국면·재고해석·
    # 상대가치)은 각각 이질적인 주제라 major_changes(동질적 등락률 반복)와
    # 달리 1근거=1문장으로 쓰는 게 자연스럽다(PRICE_SUMMARY_INSTRUCTIONS의
    # 해당 지시 참고). `models.py::SummaryNarrative.current_position`
    # max_length=9와 `komir_summary.py::_CURRENT_POSITION_HARD_CAP=9`를 반드시
    # 같이 맞춘다 — 위 ⚠ 미해결이던 (1,2) vs 하드제약 3의 불일치는 이번에
    # 상한을 정확히 맞춰 해소했다(9=9).
    "price_base_metals": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "price_minor_metals": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "price_iron_energy": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    "price_other": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 9)},
    # 2026-09-01 skeptic 감사 SC-RG-001: komir_summary.py::calculate_domestic_trade_summary
    # 기본 경로(국가필터 없음)가 top1_country/top3_concentration/top5_concentration
    # 최대 3개 근거를 만드는데 상한이 2였다 — 3번째 근거 누락/폴백 위험 → (1,3)로 확대.
    "map_korea": {"core_diagnosis": (1, 1), "major_changes": (1, 3), "current_position": (1, 1)},
    # map_global major_changes는 근거 4개(1~3위 루트·CR3·CR5·한국 순위)인데
    # 상한이 3이라 4번째 근거(CR5 또는 한국 순위)가 누락될 수 있었다 —
    # map_korea SC-RG-001과 같은 패턴(2026-09-10 사용자 지적으로 발견,
    # top5_concentration·korea_route_rank를 required=True로 바꾼 것과 짝) →
    # (1,3)→(1,4).
    "map_global": {"core_diagnosis": (1, 1), "major_changes": (1, 4), "current_position": (1, 1)},
    # 2026-08-27 신설 — group_movers·extreme_movers 2건까지 major_changes에.
    "price_group": {"core_diagnosis": (1, 1), "major_changes": (1, 2), "current_position": (1, 1)},
}
#: 2026-09-09 발주처 업무지시서 §3.3 대응 — `summary.py::
#: _append_mineral_map_extreme_change`가 "매장량/생산량 최대 증가·감소
#: 국가"(extreme_change_countries) 근거를 major_changes에 추가하면서
#: 실측 최대 개수가 3→4로 늘었다(current_leaders·third_country·
#: cross_measure_comparison·extreme_change_countries가 전부 있는 경우) —
#: `models.py::MAJOR_CHANGES_MAX_SENTENCES`(전역, 현재 7)는 이미 여유가
#: 있어 규칙기반 폴백엔 영향 없지만, 이 페이지 전용 LLM 출력계약은 그대로
#: 두면 4번째 근거가 있을 때 검증 실패로 폴백된다 — 여기도 맞춰 올린다.
MINERAL_MAP_SECTION_SENTENCE_RANGES: dict[str, tuple[int, int]] = {
    "core_diagnosis": (1, 2),
    "major_changes": (2, 4),
    "current_position": (2, 3),
}
MINERAL_MAP_TOTAL_SENTENCE_RANGE: tuple[int, int] = (5, 9)
MAX_EVIDENCE_IDS_PER_SENTENCE = 3
#: 페이지별 예외 — price는 PDF 1-1 템플릿이 전일·전주·전월·전년(·연속) 비교를 한
#: 문장에 담으므로 5(2026-08-27 반복 루프 4회차). `SummarySentence.evidence_ids`
#: pydantic 상한(5)이 절대 상한이다.
MAX_EVIDENCE_IDS_PER_SENTENCE_BY_PAGE: dict[str, int] = {
    "price_base_metals": 5,
    "price_minor_metals": 5,
    "price_iron_energy": 5,
    "price_other": 5,
}
_EVIDENCE_IDS_HARD_CAP = 5

_SECTIONS = ("core_diagnosis", "major_changes", "current_position")
#: `_parse_output_contract`가 DB `section_sentence_ranges`를 받아들이기 전에
#: 대조하는 절대 상한 — `models.py::SummaryNarrative`의 각 섹션 `max_length`와
#: 같은 값(2026-09-08 SC-002). 이 검사가 없으면 DB에 이 상한을 넘는 hi를 넣어도
#: 그대로 받아들여져 LLM 출력이 항상 `SummaryNarrative` 생성에서 ValidationError로
#: 죽는 영구 무언 폴백이 생긴다(실측 재현됨).
_SECTION_SENTENCE_HARD_CAP: dict[str, int] = {
    "core_diagnosis": CORE_DIAGNOSIS_MAX_SENTENCES,
    "major_changes": MAJOR_CHANGES_MAX_SENTENCES,
    "current_position": CURRENT_POSITION_MAX_SENTENCES,
}


# ────────────────────────────────────────────────────────────────────
# 페이지 정책·출력 계약의 "코드 기본값 + DB 오버레이" — 프롬프트 DB화 2단계
# (2026-08-27). 이전엔 지시문(content)만 DB였고 페이지 이름·정의·작성 제약·
# 정책버전은 YAML(indicator_market/supply)·dataclass(나머지 7종)에, 섹션 문장수
# 범위는 위 상수에 있었다. 이제 `ai_cfg.cfg_prompt`의 page_name/page_definition/
# analysis_constraints/policy_version/output_contract 컬럼이 값 단위로 이를
# 덮어쓴다(NULL = 코드 기본값). 코드 기본값은 그대로 남아 DB 없이도 동작한다.
# ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PageConfig:
    """한 페이지의 유효 정책·출력 계약(코드 기본값에 DB 컬럼을 덮은 결과)."""

    page_id: str
    name: str
    definition: str
    analysis_constraints: tuple[str, ...]
    policy_version: str
    section_sentence_ranges: dict[str, tuple[int, int]]
    total_sentence_range: tuple[int, int] | None
    max_evidence_ids_per_sentence: int
    #: 필드별 출처("db"|"code") — 검증 스크립트·디버깅용.
    source: dict[str, str]

    def as_context(self) -> SummaryPageContext:
        return SummaryPageContext(
            page_id=self.page_id,  # type: ignore[arg-type]
            name=self.name,
            definition=self.definition,
            analysis_constraints=list(self.analysis_constraints),
            policy_version=self.policy_version,
        )

    def output_contract_json(self) -> dict[str, Any]:
        """DB `output_contract` 컬럼(JSONB)에 그대로 저장되는 모양."""

        payload: dict[str, Any] = {
            "section_sentence_ranges": {k: list(v) for k, v in self.section_sentence_ranges.items()},
            "max_evidence_ids_per_sentence": self.max_evidence_ids_per_sentence,
        }
        if self.total_sentence_range is not None:
            payload["total_sentence_range"] = list(self.total_sentence_range)
        return payload


def code_page_config(page_id: str) -> PageConfig:
    """DB를 보지 않은 코드 기본값 — YAML 정책(2종)·dataclass 컨텍스트(7종)·위 상수."""

    if page_id in ("indicator_market", "indicator_supply"):
        policy = load_page_policy(page_id)  # type: ignore[arg-type]
        name, definition = policy.name, policy.definition
        constraints, version = policy.analysis_constraints, policy.policy_version
    elif page_id in ADDITIONAL_PAGE_CONTEXTS:
        ctx = ADDITIONAL_PAGE_CONTEXTS[page_id]
        name, definition, constraints, version = ctx.name, ctx.definition, ctx.analysis_constraints, ctx.policy_version
    elif page_id in KOMIR_PAGE_CONTEXTS:
        ctx = KOMIR_PAGE_CONTEXTS[page_id]
        name, definition, constraints, version = ctx.name, ctx.definition, ctx.analysis_constraints, ctx.policy_version
    else:
        raise KeyError(f"unknown summary page_id: {page_id}")
    if page_id == "map_mineral":
        ranges, total = dict(MINERAL_MAP_SECTION_SENTENCE_RANGES), MINERAL_MAP_TOTAL_SENTENCE_RANGE
    else:
        ranges, total = dict(SECTION_SENTENCE_RANGES[page_id]), None
    return PageConfig(
        page_id=page_id,
        name=name,
        definition=definition,
        analysis_constraints=tuple(constraints),
        policy_version=version,
        section_sentence_ranges=ranges,
        total_sentence_range=total,
        max_evidence_ids_per_sentence=MAX_EVIDENCE_IDS_PER_SENTENCE_BY_PAGE.get(page_id, MAX_EVIDENCE_IDS_PER_SENTENCE),
        source={k: "code" for k in ("name", "definition", "analysis_constraints", "policy_version", "section_sentence_ranges", "total_sentence_range", "max_evidence_ids_per_sentence")},
    )


def _parse_range(value: Any, max_hi: int | None = None) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lo, hi = value
    if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int):
        return None
    if lo < 1 or hi < lo:
        return None
    if max_hi is not None and hi > max_hi:
        return None
    return (lo, hi)


def _parse_output_contract(page_id: str, raw: Any) -> tuple[dict[str, tuple[int, int]] | None, tuple[int, int] | None, int | None]:
    """DB `output_contract` JSON을 검증해 (섹션범위, 총범위, 문장당 근거수)로.
    형식이 틀린 항목은 None(=코드 기본값)으로 두고 경고만 남긴다 — 운영 중
    DB 값 하나가 틀렸다고 보고서 생성이 멈추면 안 된다."""

    log = logging.getLogger(__name__)
    if not isinstance(raw, dict):
        log.warning("%s: output_contract가 객체가 아니라 무시한다: %r", page_id, raw)
        return None, None, None
    ranges: dict[str, tuple[int, int]] | None = None
    raw_ranges = raw.get("section_sentence_ranges")
    if raw_ranges is not None:
        parsed = (
            {section: _parse_range(raw_ranges.get(section), _SECTION_SENTENCE_HARD_CAP[section]) for section in _SECTIONS}
            if isinstance(raw_ranges, dict)
            else {}
        )
        if all(parsed.get(section) is not None for section in _SECTIONS):
            ranges = {section: parsed[section] for section in _SECTIONS}  # type: ignore[misc]
        else:
            log.warning(
                "%s: output_contract.section_sentence_ranges 형식 오류 또는 상한(%s) 초과 — 코드 기본값 사용: %r",
                page_id,
                _SECTION_SENTENCE_HARD_CAP,
                raw_ranges,
            )
    total: tuple[int, int] | None = None
    if raw.get("total_sentence_range") is not None:
        total = _parse_range(raw.get("total_sentence_range"))
        if total is None:
            log.warning("%s: output_contract.total_sentence_range 형식 오류 — 코드 기본값 사용", page_id)
    max_ids: int | None = None
    raw_max = raw.get("max_evidence_ids_per_sentence")
    if raw_max is not None:
        if isinstance(raw_max, int) and not isinstance(raw_max, bool) and 1 <= raw_max <= _EVIDENCE_IDS_HARD_CAP:
            max_ids = raw_max  # `SummarySentence.evidence_ids` max_length(5)가 절대 상한
        else:
            log.warning("%s: output_contract.max_evidence_ids_per_sentence는 1~%d이어야 한다 — 코드 기본값 사용", page_id, _EVIDENCE_IDS_HARD_CAP)
    # 2026-09-02 skeptic 2차 감사 PA-003: 위 3개 키 이외의 키(오타 등, 예:
    # "section_sentence_range")는 그냥 무시돼 로그조차 없었다 — 저장은
    # json.loads 문법만 검증하고 reload도 "성공"으로 보이니, 운영자는 계약을
    # 바꿨다고 믿지만 실제로는 아무 변화가 없어도 알 방법이 없었다. 동작은
    # 그대로(여전히 무시 — 코드 기본값 유지) 두고 경고 로그만 남긴다.
    unknown_keys = set(raw) - {
        "section_sentence_ranges",
        "total_sentence_range",
        "max_evidence_ids_per_sentence",
    }
    if unknown_keys:
        log.warning(
            "%s: output_contract에 인식하지 못하는 키 %s — 무시하고 코드 기본값 유지",
            page_id,
            sorted(unknown_keys),
        )
    return ranges, total, max_ids


def _resolve_page_config(page_id: str, row: prompt_store.PromptRow | None) -> PageConfig:
    """검증된 DB 필드만 기본 설정에 덮는다. NULL/잘못된 값은 기존 기본값 유지."""
    base = code_page_config(page_id)
    if row is None:
        return base
    updates: dict[str, Any] = {}
    for field, value in (("name", row.page_name), ("definition", row.page_definition),
                         ("policy_version", row.policy_version)):
        if value and value.strip():
            updates[field] = value.strip()
    if row.analysis_constraints is not None:
        if isinstance(row.analysis_constraints, list) and all(isinstance(item, str) for item in row.analysis_constraints):
            updates["analysis_constraints"] = tuple(row.analysis_constraints)
        else:
            logging.getLogger(__name__).warning("%s: analysis_constraints는 문자열 배열이어야 한다 — 코드 기본값 사용", page_id)
    if row.output_contract is not None:
        values = _parse_output_contract(page_id, row.output_contract)
        updates.update((key, value) for key, value in zip(
            ("section_sentence_ranges", "total_sentence_range", "max_evidence_ids_per_sentence"), values
        ) if value is not None)
    return replace(base, **updates, source={**base.source, **{key: "db" for key in updates}})


# 각 요청에서 계산·프롬프트·검증이 같은 설정을 사용한다. 동시 reload는 다음 요청에 반영.
_active_prompt: ContextVar[tuple[PageConfig, str] | None] = ContextVar("analysis_prompt", default=None)


@contextmanager
def page_prompt_scope(page_id: str):
    rows = prompt_store.snapshot()
    cfg = _resolve_page_config(page_id, rows.get(page_id))
    common, page = rows.get("summary_common"), rows.get(page_id)
    instructions = (common.content if common else PROMPTS["summary_common"]) + (
        page.content if page else PROMPTS[page_id]
    )
    token = _active_prompt.set((cfg, instructions))
    try:
        yield
    finally:
        _active_prompt.reset(token)


def resolve_page_config(page_id: str) -> PageConfig:
    active = _active_prompt.get()
    if active is not None and active[0].page_id == page_id:
        return active[0]
    return _resolve_page_config(page_id, prompt_store.get_page_row(page_id))


def effective_page_context(page_id: str) -> SummaryPageContext:
    """`summary.py`가 응답의 policy_version/page_definition/notices에 쓰는 컨텍스트."""

    return resolve_page_config(page_id).as_context()


def apply_page_config(policy: PagePolicy) -> PagePolicy:
    """YAML 등급 정책(indicator_market/supply)에 DB 오버레이를 입힌다 — 등급 밴드
    (grade_rules)는 판정 로직이라 DB화 대상이 아니고, 이름·정의·제약·버전만 덮는다."""

    cfg = resolve_page_config(policy.page_id)
    return policy.model_copy(
        update={
            "name": cfg.name,
            "definition": cfg.definition,
            "analysis_constraints": list(cfg.analysis_constraints),
            "policy_version": cfg.policy_version,
        }
    )


def summary_instructions(page_id: str) -> str:
    """Select narrative instructions appropriate for a summary page.

    DB(`cfg_prompt`) 캐시에 `prompt_key`가 있으면 그 값을, 없으면 `PROMPTS`의
    하드코드 상수를 쓴다 — `prompt_key`는 공통 서두가 "summary_common", 페이지별
    지시문은 `page_id` 그대로다."""

    active = _active_prompt.get()
    if active is not None and active[0].page_id == page_id:
        return active[1]
    common = prompt_store.get_prompt("summary_common", default=PROMPTS["summary_common"])
    page_text = prompt_store.get_prompt(page_id, default=PROMPTS[page_id])
    return common + page_text


def build_summary_payload(
    *,
    response: AnalysisSummaryResponse,
    allowed_evidence: list[dict[str, str]],
    previous_validation_error: str | None = None,
) -> dict[str, Any]:
    """Build an evidence-bounded payload for summary refinement.

    페이지 정책·출력 계약은 `resolve_page_config()`(코드 기본값 + DB 오버레이)에서
    가져온다(2026-08-27) — 호출부가 따로 정책 객체를 넘길 필요가 없다."""

    cfg = resolve_page_config(response.page_id)
    if response.page_id == "map_mineral":
        required_ids = [
            item["evidence_id"]
            for item in allowed_evidence
            if item.get("required") is True
        ]
        output_contract: dict[str, Any] = {
            "mode": "select_and_synthesize",
            "required_evidence_ids": required_ids,
            "optional_evidence_ids": [
                item["evidence_id"]
                for item in allowed_evidence
                if item.get("required") is not True
            ],
            "max_evidence_ids_per_sentence": cfg.max_evidence_ids_per_sentence,
            "section_sentence_ranges": {
                section: list(bounds) for section, bounds in cfg.section_sentence_ranges.items()
            },
            "total_sentence_range": list(cfg.total_sentence_range or MINERAL_MAP_TOTAL_SENTENCE_RANGE),
        }
    else:
        output_contract = {
            "mode": "synthesize_all",
            "required_evidence_ids": [
                item["evidence_id"] for item in allowed_evidence
            ],
            "max_evidence_ids_per_sentence": cfg.max_evidence_ids_per_sentence,
            "section_sentence_ranges": {
                section: list(bounds) for section, bounds in cfg.section_sentence_ranges.items()
            },
            "require_combined_evidence_sentence": True,
        }
    payload: dict[str, Any] = {
        "page_policy": {
            "page_id": cfg.page_id,
            "name": cfg.name,
            "definition": cfg.definition,
            "analysis_constraints": list(cfg.analysis_constraints),
            "policy_version": cfg.policy_version,
        },
        "analysis_scope": response.analysis_scope,
        "mineral": response.mineral.model_dump(mode="json"),
        "applied_filters": response.applied_filters,
        "data_quality": response.data_quality.model_dump(mode="json"),
        # 2026-08-27(SC-006): 프롬프트가 참조하는 패턴(예: price의 near_period_high/
        # low)을 LLM이 실제로 볼 수 있게 code·label만 싣는다 — `evidence` 문자열은
        # 숫자를 담을 수 있어, 근거 문장에 없는 숫자를 LLM이 베끼면 검증기에
        # 걸리므로 일부러 뺀다.
        "detected_patterns": [
            {"code": pattern.code, "label": pattern.label} for pattern in response.detected_patterns
        ],
        "output_contract": output_contract,
        "allowed_evidence": allowed_evidence,
    }
    if previous_validation_error:
        payload["previous_validation_error"] = previous_validation_error
    return payload
