# -*- coding: utf-8 -*-
"""정형(RDB) 템플릿 조회 — rag_chat·report_gen 공용 정본 구현.

`documents/meta/CONTAINER_ARCHITECTURE.md` §5-4·§6("RAG 챗봇과 Report 생성기가
동일한 3개 조회 도구를 쓴다 — services/shared/retrieval/에 한 번만 구현")대로,
2026-08-11에 각 서비스가 따로 만들었던 두 벌(rag_chat/app/retrieval/structured.py,
report_gen/app/generator.py의 `_latest_diagnosis`/`_import_forecast`/
`_geo_index_trend`)을 여기로 합쳤다. 두 호출자는 이제 얇은 어댑터다.

조회 대상은 전부 komir 자체 산출물: `out_diagnosis_alert`·`out_import_forecast`·
`geo_index`. KOMIS 공개원천(`public.KO_*`, 타 팀 소유)은 이 모듈 소관이 아니다 —
report_gen의 `_komis_supply_indicator`가 계속 담당한다.

**2026-08-19 데이터소스 PostgreSQL로 전환**: 원래 `read_sql_msr()`(MSR_DB)를
썼는데, 이 브랜치(워크트리)의 `.env`엔 MSR_DB가 아예 설정돼 있지 않아
`config.py` 기본값(워크트리 로컬의 **빈** duckdb 스톱갭)으로 조용히 폴백하고
있었다(실측 확인 — `.env` 자체에 "structured 도구는 이번 검증 범위 밖"이라고
명시돼 있었음, 즉 지금까지 2-1 통계조회 시나리오는 코드는 있어도 실제로는 빈
결과만 내고 있었던 상태). MSR_DB(전체 시스템 cutover 대상, cron·streamlit
등이 아직 duckdb에 의존 — `config.py` 주석 참고)는 그대로 두고, 이 모듈만
독립적으로 `read_sql_pg()`(PG_DSN, `mineral_risk` 스키마 — dense_pg.py·
bm25_pg.py가 이미 쓰는 같은 접속)로 전환한다. `postgres_migration_260810`
메모리 기준 36개 테이블이 이 스키마로 이관 완료돼 있어 즉시 사용 가능.

⚠ **PG mineral_risk 스키마는 실시간 동기화가 아니다**(2026-08-19 실측):
`out_diagnosis_alert`·`out_import_forecast`는 우연히 라이브 duckdb와 행수·
최신일자가 완전히 일치했지만(그 파이프라인들이 08-10 이관 이후 재실행된 적이
없어서), `geo_index`는 **PG가 라이브보다 약 1주 뒤처짐**(PG 최신주 2026-08-02
vs 라이브 2026-08-09, 오늘 진행한 geo_prob/geo_index expanding-window
리팩터 반영분도 PG엔 없음). 정기 동기화(cron 등) 없이는 이 격차가 계속
벌어진다 — 운영 전 별도 결정 필요(이번 변경 범위 밖, 정기동기화 도입은 후속 과제).

⚠ SQL 작성 규약(두 벌 모두 동일했던 규약을 그대로 승계):
- 자유형 NL→SQL은 구현하지 않는다. LLM은 "어떤 템플릿+어떤 광종"만 고른다.
- 광종 코드는 `VALID_COMMODITIES` 화이트리스트로만 받고, 그 외 파라미터는
  리터럴 집합 검사 또는 `int()` 캐스팅 후 삽입한다(`dbio.read_sql`은 바인딩
  파라미터를 받지 않는다).

반환 형태는 두 호출자를 모두 덮도록 "여러 행 + 상위 컬럼 합집합"으로 잡았다 —
최신 1건만 필요한 쪽(rag_chat)은 어댑터에서 마지막/첫 행을 뽑아 쓴다.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..db import read_sql_pg


def _schema() -> str:
    return get_settings().PG_SCHEMA

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
    frame = read_sql_pg(
        f"""
        SELECT commodity_code, obs_date, risk_score, alert_level, reason, model_version,
               generated_at
        FROM {_schema()}.out_diagnosis_alert
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
    schema = _schema()
    frame = read_sql_pg(
        f"""
        SELECT commodity_code, target, base_date, horizon, yhat, yhat_lo, yhat_hi,
               model_version
        FROM {schema}.out_import_forecast
        WHERE commodity_code = '{code}'
          AND target = '{target}'
          AND base_date = (
              SELECT max(base_date) FROM {schema}.out_import_forecast
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
    frame = read_sql_pg(
        f"""
        SELECT commodity_code, freq, period, idx_value, raw_score, n_events,
               index_config_version
        FROM {_schema()}.geo_index
        WHERE commodity_code = '{code}' AND freq = '{freq}'
        ORDER BY period DESC
        LIMIT {int(limit)}
        """
    )
    return list(reversed(frame.to_dict("records")))
