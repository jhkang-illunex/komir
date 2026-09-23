"""무역지표의 원천 독립 계산 계약.

RCA·TII의 세계 분모 원천은 아직 연결하지 않았지만, 계산식과 필수 입력 계약은
여기서 완성한다. 이후 데이터 공급자는 이 모듈에 검증된 분자·분모만 넘기면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass


class TradeIndicatorInputError(ValueError):
    """분모가 0이거나 필요한 입력이 없는 경우."""


@dataclass(frozen=True)
class RcaInputs:
    reporter_product_exports: float
    reporter_total_exports: float
    world_product_exports: float
    world_total_exports: float


@dataclass(frozen=True)
class TiiInputs:
    reporter_partner_exports: float
    reporter_total_exports: float
    world_partner_imports: float
    world_total_imports: float


def calculate_rca(inputs: RcaInputs) -> float:
    """현시비교우위: (국가 품목 수출/국가 총수출)/(세계 품목 수출/세계 총수출)."""
    if inputs.reporter_total_exports <= 0 or inputs.world_product_exports <= 0 or inputs.world_total_exports <= 0:
        raise TradeIndicatorInputError("RCA 계산에 필요한 수출 분모가 0이거나 없습니다.")
    return round(
        (inputs.reporter_product_exports / inputs.reporter_total_exports)
        / (inputs.world_product_exports / inputs.world_total_exports), 6,
    )


def calculate_tii(inputs: TiiInputs) -> float:
    """무역결합도: (기준국의 상대국 수출/기준국 총수출)/(세계의 상대국 수입/세계 총수입)."""
    if inputs.reporter_total_exports <= 0 or inputs.world_partner_imports <= 0 or inputs.world_total_imports <= 0:
        raise TradeIndicatorInputError("TII 계산에 필요한 교역 분모가 0이거나 없습니다.")
    return round(
        (inputs.reporter_partner_exports / inputs.reporter_total_exports)
        / (inputs.world_partner_imports / inputs.world_total_imports), 6,
    )
