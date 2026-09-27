"""복합 질의의 답변 형식 계약.

이 모듈은 수치를 계산하지 않는다. Planner가 만든 Action 집합에 맞는
출력 순서와 필드만 LLM에 전달하며, 원천이 없는 계약은 작업 목록에 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerContract:
    contract_id: str
    action_ids: frozenset[str]
    format_rule: str


CONTRACTS = (
    AnswerContract(
        "OC01", frozenset({"price.series", "forecast.price"}),
        "광물 가격 : {기준일} {광물} 가격 {가격} {단위}\n"
        "가격 예측 : {예측월} 전망치 {전망값} (현재 대비 {변동률}%)\n"
        "리튬이면 마지막 줄에 자료원 변경 주의 문구를 별도 표시한다.",
    ),
    AnswerContract(
        "OC02", frozenset({"price.series", "forecast.price"}),
        "광물 가격 : {기준일} {광물} 실적 추이\n"
        "가격 예측 : {예측기간} 전망치를 연결한 차트이며 실적 구간과 전망 구간을 구분한다.",
    ),
    AnswerContract(
        "OC03", frozenset({"price.series", "forecast.price"}),
        "광물 가격 : 현재가 {값}\n가격 예측 : {예측월} 전망치 {전망값}\n"
        "현재가가 전망치 대비 {차이}({차이율}%) {높습니다/낮습니다}.",
    ),
    AnswerContract(
        "OC04", frozenset({"indicator.series", "price.series"}),
        "광물종합지수 : {기간} {변동률}% {상승/하락}\n"
        "광물가격 : 동 기간 광종별 변동률과 동반상승·동반하락 여부를 기술한다.",
    ),
    AnswerContract(
        "OC05", frozenset({"indicator.series", "price.series"}),
        "{기간} {광물} 가격 {변동률}%, 광물 종합지수 {변동률}% 변동했습니다. 비교차트를 표시한다.",
    ),
    AnswerContract(
        "OC06", frozenset({"price.series", "trade.country_rank"}),
        "광물가격 : {기간} {광물} 가격 {변동률}% 변동 고점 {값}({월})\n"
        "수급지도 : {기준연도} 수입국 상위 국가와 점유율을 표시한다.",
    ),
    AnswerContract(
        "OC07", frozenset({"trade.price_cross_rank"}),
        "수급지도 : {국가} 점유율 상위 광종과 점유율\n"
        "광물가격 : 그 광종 중 최근 상승 광종과 변동률",
    ),
    AnswerContract(
        "OC08", frozenset({"trade.country_rank", "price.series"}),
        "수급지도 : {기준연도} 수입 상위국 {국가목록}\n"
        "광물가격 : {기준일} 가격 {값}, 전월 평균 대비 {등락율}%",
    ),
    AnswerContract(
        "OC09", frozenset({"price.series", "resource.yoy"}),
        "광물가격 : 연도별 평균 가격 {연도} {값}\n"
        "광물지도 : 같은 연도 생산량 전년 대비 {증감률}%\n"
        "두 지표를 나란히 제시하며 상호 인과관계로 해석하지 않는다.",
    ),
    AnswerContract(
        "OC10", frozenset({"resource.price_cross_rank"}),
        "광물지도 : 생산 1위국 비중 상위 광종·국가·비중\n"
        "광물가격 : 같은 광종의 기간별 가격 변동률",
    ),
    AnswerContract(
        "OC11", frozenset({"document.retrieve", "price.series"}),
        "광물정보 : 주요 용도 {용도1}, {용도2}\n광물가격 : {기준일} 가격 {값} {단위}, 전일 대비 {등락률}%",
    ),
    AnswerContract(
        "OC12", frozenset({"price.overview"}),
        "광물정보 : 전략광종 목록 기준\n광물가격 : {기준일} 광종별 가격·전월 평균 대비 등락률 표",
    ),
    AnswerContract(
        "OC13", frozenset({"document.retrieve", "price.series"}),
        "월간동향 : {월호} 희소금속 동향에 나온 광종 목록\n"
        "광물가격 : {기준일} 광종별 가격·전월 평균 대비 등락률 표",
    ),
    AnswerContract(
        "OC14", frozenset({"document.retrieve", "price.series"}),
        "광물정보 : {기간} {광물} {변동률}% 변동\n"
        "월간동향 : {월호} 해당 광물 관련 서술 요약 {요약}",
    ),
)


def matching_contracts(action_ids: list[str]) -> list[AnswerContract]:
    """Action 집합에 적용 가능한 계약을 반환한다(순서·중복은 무시)."""
    actual = frozenset(action_ids)
    return [contract for contract in CONTRACTS if contract.action_ids == actual]
