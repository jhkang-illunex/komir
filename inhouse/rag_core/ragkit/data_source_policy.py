# -*- coding: utf-8 -*-
"""KOMIS 정형 원천의 반환 정책.

원천 상태는 DB의 ``public.ai_mnrl_mst.ko_data_src_cd``에서 온다. ``DEV_DUMMY``는
개발·수락검사를 위해 결과를 보여 줄 수는 있으나, 실제 값으로 오인되면 안 된다.
따라서 이 모듈은 이를 ``ALLOW_DUMMY``로 명시하고 호출부가 Evidence caveat을
반드시 붙이게 한다. 출처가 없거나 알 수 없는 값은 더미 허용으로 추정하지 않는다.
"""
from __future__ import annotations

from enum import Enum


class DataSourcePolicy(str, Enum):
    """원천 상태별 챗봇 결과 노출 정책."""

    ALLOW = "ALLOW"
    ALLOW_DUMMY = "ALLOW_DUMMY"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


def policy_for_data_source(data_source: str | None) -> DataSourcePolicy:
    """DB 출처 코드를 fail-closed 정책으로 변환한다."""

    normalized = str(data_source or "").strip().upper()
    if normalized == "KOMIS_SAMPLE":
        return DataSourcePolicy.ALLOW
    if normalized == "DEV_DUMMY":
        return DataSourcePolicy.ALLOW_DUMMY
    return DataSourcePolicy.SOURCE_UNAVAILABLE


def allows_result(data_source: str | None) -> bool:
    """결과 반환이 허용되는 원천인지 판단한다."""

    return policy_for_data_source(data_source) is not DataSourcePolicy.SOURCE_UNAVAILABLE


def is_allowed_dummy(data_source: str | None) -> bool:
    """경고를 강제하면서 반환할 수 있는 명시적 개발 더미인지 판단한다."""

    return policy_for_data_source(data_source) is DataSourcePolicy.ALLOW_DUMMY
