"""보고서 계산 모듈이 함께 쓰는 지표 목록 유틸리티."""
from __future__ import annotations

import logging

from .models import KEY_METRICS_MAX_COUNT, Metric

_log = logging.getLogger(__name__)


def capped_key_metrics(key_metrics: list[Metric], *, page_id: str) -> list[Metric]:
    """응답 상한에 맞춰 핵심 지표를 자르고 실제 누락이 생기면 기록한다."""

    if len(key_metrics) > KEY_METRICS_MAX_COUNT:
        _log.warning(
            "%s: key_metrics %d개 중 %d개가 상한(%d)을 넘어 잘렸다: %s",
            page_id,
            len(key_metrics),
            len(key_metrics) - KEY_METRICS_MAX_COUNT,
            KEY_METRICS_MAX_COUNT,
            [metric.id for metric in key_metrics[KEY_METRICS_MAX_COUNT:]],
        )
    return key_metrics[:KEY_METRICS_MAX_COUNT]
