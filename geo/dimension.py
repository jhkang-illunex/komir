# -*- coding: utf-8 -*-
"""[3보조] event_type → dimension 규칙 매핑 (경보 3계열 병렬 구조의 계열2 판별용).

피드백기반_수정플랜(2026-07-16) A-2. 법정 경보기준(붙임2)의 3계열 — ①정세불안 ②시설·수송
③가격변동성 — 중 계열2(시설·수송)를 판별하려면 GeoEvent.event_type(자유텍스트, 한글·영문·
대소문자 혼재)을 먼저 4개 dimension으로 정규화해야 한다. 계열2 트리거는 dimension이
{ops, corridor}인 고심각 이벤트로 정의한다(alert.py의 trigger_c2()가 사용).

dimension 값:
- ops:      광산·제련소 등 생산현장 운영 차질(폐쇄·가동중단·파업·사고·화재·감산)
- corridor: 운송·물류 경로 차질(항만·철도·해협 봉쇄, 수송 제한)
- trade:    실물 흐름 급변(재고 급감, 선적·수출입 물량 급변) — 정책이 아닌 물동량 자체
- input:    상류 원료·투입재 조달 차질
- policy:   위 4종에 해당하지 않는 나머지(수출규제·제재·외교·시장전망 등 — 계열1 정세불안 성격)
"""
import re

_OPS = re.compile(
    r"광산\s*폐쇄|제련소\s*사고|가동\s*중단|생산\s*중단|감산|폭발|화재|shutdown|closure|curtail"
    r"|force\s*majeure|shut-?in|smelter\s*accident|mine\s*closure"
    r"|파업|strike|사고|accident"
    r"|재해|natural[\s_]?disaster|disaster",
    re.IGNORECASE,
)
_CORRIDOR = re.compile(
    r"항만|물류\s*차질|운송\s*제한|철도|해협|봉쇄|port\s*(disruption|congestion|closure)"
    r"|logistics|shipping\s*(disruption|delay)|transport\s*restrict|blockade|rail\s*disrupt"
    r"|strait|route\s*disrupt",
    re.IGNORECASE,
)
_TRADE = re.compile(
    r"재고\s*급감|재고\s*감소|inventory\s*(drop|decline|drawdown)|stockpile\s*decline"
    r"|선적\s*(차질|중단)|shipment\s*(disrupt|halt)|수출\s*(급감|급증)|수입\s*(급감|급증)",
    re.IGNORECASE,
)
_INPUT = re.compile(
    r"원료\s*(부족|조달)|투입재\s*부족|feedstock\s*shortage|raw\s*material\s*shortage"
    r"|concentrate\s*shortage|정광\s*부족",
    re.IGNORECASE,
)

# 판별 순서: ops → corridor → trade → input → policy(기본값). 하나의 event_type이 복수 패턴에
# 매치될 수 있어(예: "파업으로 항만 봉쇄") 우선순위를 둔다 — 생산현장(ops) 직접 차질이 가장
# 강한 신호이므로 최우선.
_ORDER = (("ops", _OPS), ("corridor", _CORRIDOR), ("trade", _TRADE), ("input", _INPUT))


def classify_dimension(event_type: str) -> str:
    """자유텍스트 event_type(한글/영문/대소문자 혼재) → dimension 4+1종 중 하나."""
    t = (event_type or "")
    for name, pat in _ORDER:
        if pat.search(t):
            return name
    return "policy"


def is_c2_dimension(dimension: str) -> bool:
    """경보 계열2(시설·수송) 판별: 생산현장·운송경로 차질만 해당(trade/input/policy는 계열1·3에 귀속)."""
    return dimension in ("ops", "corridor")
