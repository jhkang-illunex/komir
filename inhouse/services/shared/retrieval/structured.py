# -*- coding: utf-8 -*-
"""정형(RDB) 템플릿 조회 — rag_chat·report_gen 공용 정본 구현.

`documents/meta/CONTAINER_ARCHITECTURE.md` §5-4·§6("RAG 챗봇과 Report 생성기가
동일한 3개 조회 도구를 쓴다 — services/shared/retrieval/에 한 번만 구현")대로,
2026-08-11에 각 서비스가 따로 만들었던 두 벌(rag_chat/app/retrieval/structured.py,
report_gen/app/generator.py의 `_latest_diagnosis`/`_import_forecast`/
`_geo_index_trend`)을 여기로 합쳤다. 두 호출자는 이제 얇은 어댑터다.

조회 대상은 전부 komir 자체 산출물(MSR_DB): `out_diagnosis_alert`·
`out_import_forecast`·`geo_index`. KOMIS 공개원천(`public.KO_*`, 타 팀 소유)은
이 모듈 소관이 아니다 — report_gen의 `_komis_supply_indicator`가 계속 담당한다.

⚠ SQL 작성 규약(두 벌 모두 동일했던 규약을 그대로 승계):
- 자유형 NL→SQL은 구현하지 않는다. LLM은 "어떤 템플릿+어떤 광종"만 고른다.
- 광종 코드는 `VALID_COMMODITIES` 화이트리스트로만 받고, 그 외 파라미터는
  리터럴 집합 검사 또는 `int()` 캐스팅 후 삽입한다(`dbio.read_sql`은 바인딩
  파라미터를 받지 않는다).

반환 형태는 두 호출자를 모두 덮도록 "여러 행 + 상위 컬럼 합집합"으로 잡았다 —
최신 1건만 필요한 쪽(rag_chat)은 어댑터에서 마지막/첫 행을 뽑아 쓴다.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from ..db import read_sql_msr

#: 발주 5광종(CLAUDE.md §0). 순서 있는 튜플 — report_gen 스케줄러가 이 순서로 순회한다.
VALID_COMMODITIES: tuple[str, ...] = ("CU", "NI", "CO", "LI", "REE")

#: geo_index.freq에 실제로 존재하는 값(W=주간·M=월간·Y=연간).
VALID_FREQS: tuple[str, ...] = ("W", "M", "Y")

#: out_import_forecast.target 실측값 — 문서 예시의 'ton'/'usd'가 아니라 'volume'/'value'.
VALID_TARGETS: tuple[str, ...] = ("volume", "value")


class StructuredQueryError(ValueError):
    """템플릿 이름이나 파라미터가 잘못됐을 때."""


def check_commodity(commodity_code: str) -> str:
    """광종 코드 화이트리스트 검사 — SQL에 문자열을 넣기 전 유일한 관문."""

    code = (commodity_code or "").strip().upper()
    if code not in VALID_COMMODITIES:
        raise StructuredQueryError(f"알 수 없는 광종 코드: {commodity_code!r}")
    return code


def latest_diagnosis(commodity_code: str) -> dict[str, Any] | None:
    """"{cc} 현재 등급?" — 가장 최근 수급위기 진단 경보 1건(없으면 None)."""

    code = check_commodity(commodity_code)
    frame = read_sql_msr(
        f"""
        SELECT commodity_code, obs_date, risk_score, alert_level, reason, model_version,
               generated_at
        FROM out_diagnosis_alert
        WHERE commodity_code = '{code}'
        ORDER BY obs_date DESC
        LIMIT 1
        """
    )
    return frame.iloc[0].to_dict() if len(frame) else None


def import_forecast(
    commodity_code: str,
    target: str = "volume",
    horizon: int | None = None,
) -> list[dict[str, Any]]:
    """"{cc} 12개월 물량/금액 예측?" — 항상 **최신 기준월(base_date)** 한 벌만 돌려준다.

    - `target`: 'volume'(물량) | 'value'(금액)
    - `horizon`: None이면 그 기준월의 전 시계(1~12개월, 오름차순), 정수면 그 시점 1건.

    (통합 전 rag_chat판은 `ORDER BY base_date DESC, horizon ASC LIMIT 12`라
    horizon을 지정하면 여러 기준월이 섞여 나왔다 — 자기 docstring의 "그 시점만"과
    어긋나던 부분이라 report_gen판의 max(base_date) 서브쿼리 방식으로 통일했다.
    현재 데이터는 광종·target별 기준월이 2025-12-01 하나뿐이라 horizon 미지정
    결과는 두 판이 완전히 동일하다 — 2026-08-11 실측 확인.)
    """

    code = check_commodity(commodity_code)
    if target not in VALID_TARGETS:
        raise StructuredQueryError(f"target은 volume|value만 지원: {target!r}")
    where_horizon = f"AND horizon = {int(horizon)}" if horizon is not None else ""
    frame = read_sql_msr(
        f"""
        SELECT commodity_code, target, base_date, horizon, yhat, yhat_lo, yhat_hi,
               model_version
        FROM out_import_forecast
        WHERE commodity_code = '{code}'
          AND target = '{target}'
          AND base_date = (
              SELECT max(base_date) FROM out_import_forecast
              WHERE commodity_code = '{code}' AND target = '{target}'
          )
          {where_horizon}
        ORDER BY horizon ASC
        """
    )
    return frame.to_dict("records")


def geo_index_trend(
    commodity_code: str,
    freq: str = "W",
    limit: int = 8,
) -> list[dict[str, Any]]:
    """"{cc} 최근 위기지수 추이?" — 최근 `limit`개를 **오래된 순**으로.

    최신 1건만 필요하면 호출자가 `limit=1` + `[-1]`로 뽑는다(rag_chat 어댑터의
    `latest_geo_index`가 그 형태).
    """

    code = check_commodity(commodity_code)
    if freq not in VALID_FREQS:
        raise StructuredQueryError(f"freq는 W|M|Y만 지원: {freq!r}")
    frame = read_sql_msr(
        f"""
        SELECT commodity_code, freq, period, idx_value, raw_score, n_events,
               index_config_version
        FROM geo_index
        WHERE commodity_code = '{code}' AND freq = '{freq}'
        ORDER BY period DESC
        LIMIT {int(limit)}
        """
    )
    return list(reversed(frame.to_dict("records")))


def weekly_geo_events(
    commodity_code: str,
    week_end: str,
    top_n: int = 8,
) -> list[dict[str, Any]]:
    """"{cc} 이번 주 관련 뉴스/이벤트?" — `week_end`(포함) 기준 직전 7일 구간을
    severity·confidence 내림차순으로 최대 `top_n`건.

    `week_end`는 반드시 `geo_index`(freq='W')의 `period` 값을 그대로 넘길 것 —
    이 함수가 주 경계를 독자적으로 계산하지 않는 이유는, geo 파이프라인이 이미
    pandas `to_period("W")`(주 종료일=일요일) 관례로 주를 나누고 있어(`geo/
    indexer.py`), 여기서 다른 앵커(예: 월요일 시작)로 재계산하면 `geo_index`가
    말하는 "이번 주"와 이 함수가 돌려주는 뉴스의 "이번 주"가 어긋난다
    (`geo_prob` 발행 때 실제로 겪은 요일앵커 버그와 같은 종류의 함정, WORKLOG
    참고) — 항상 같은 값을 공유해 정의 불일치를 원천 차단한다.

    `evidence_quote`에 GKG 원시 신호(`[GKG tone=...] https://...` 형태, 기사
    본문이 아니라 크롤러 메타데이터)가 섞여 있어 SQL이 아니라 여기서 걸러낸다
    — `read_sql_msr`가 pandas `read_sql`(PG 경로에서 `%` 리터럴을 파라미터로
    오인하는 기존 버그, `db.py` 참고)을 거치므로 `LIKE '%...%'` 자체를 SQL에
    쓰지 않는다."""

    code = check_commodity(commodity_code)
    # geo_event.obs_date는 VARCHAR(ISO 'YYYY-MM-DD') 컬럼이라 DATE 리터럴과
    # 직접 비교하면 duckdb가 타입 바인딩 오류를 낸다(실측 확인) — 경계를
    # 파이썬에서 미리 문자열로 계산해 같은 VARCHAR끼리 비교한다.
    end_date = _dt.date.fromisoformat(str(week_end)[:10])
    start_date = end_date - _dt.timedelta(days=6)
    frame = read_sql_msr(
        f"""
        SELECT commodity_code, obs_date, event_type, direction, target,
               severity, confidence, evidence_quote, source, published_at
        FROM geo_event
        WHERE commodity_code = '{code}'
          AND obs_date > '{start_date.isoformat()}'
          AND obs_date <= '{end_date.isoformat()}'
        ORDER BY severity DESC, confidence DESC
        """
    )
    rows = frame.to_dict("records")
    rows = [
        row
        for row in rows
        if row.get("evidence_quote")
        and "GKG tone=" not in row["evidence_quote"]
        and not str(row["evidence_quote"]).strip().startswith("http")
    ]
    return rows[: int(top_n)]
