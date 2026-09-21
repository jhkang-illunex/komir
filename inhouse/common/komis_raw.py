# -*- coding: utf-8 -*-
"""KOMIS 공개 원천 테이블(`public.KO_*`, komis_demo) **읽기 전용** 접근 계층.

외부 저장소 komis-report-generator-main의
`src/komis_report_generator/analysis/scaffold.py`에 있던 `PostgresRawDataRepository`
+ `_DatasetSpec`/`_PAGE_DATASETS`/`_coerce_period`/`AnalysisPreviewRequest`/
`RawDataset`를 komir 규약에 맞춰 이식한 것이다(2026-08-11, 병합계획
`documents/산출물/2026-W33_0810-0816/병합계획_komis-report-generator_260811.md`
결정② "코드 직접 이식").

**이식 시 바뀐 점 3가지**

1. **접속**: 원본은 `psycopg.connect(...)`로 직접 커넥션을 열었다. 여기서는
   `services/shared/db.read_sql_pg()`만 쓴다(서비스 코드가 psycopg2/sqlalchemy를
   직접 임포트하지 않는다는 원칙). 그 대신 원본이 커넥션 옵션으로 걸던
   `default_transaction_read_only=on`이 사라지므로, **SELECT 외의 SQL을 이
   모듈에서 만들지 않는 것**으로 읽기 전용을 보장한다 — 아래 쿼리 조립부는
   정적 스펙(`_PAGE_DATASETS`)의 테이블·컬럼명과 검증된 리터럴만 조합한다.

2. **파라미터 바인딩 → 검증 후 리터럴 삽입**: 원본은 `%s` 플레이스홀더를 썼다.
   `read_sql_pg`는 `pandas.read_sql(str, engine)` → `exec_driver_sql` 경로라
   **바인딩 파라미터를 받지 않고, 쿼리 문자열 안의 `%`를 플레이스홀더로 오인**한다
   (실측: `SELECT ... ILIKE 'ko\\_%'` → `TypeError: immutabledict is not a sequence`).
   그래서 (a) 모든 사용자 입력은 `AnalysisPreviewRequest`의 pydantic 패턴으로 1차
   검증하고, (b) SQL에 넣기 직전 `_literal()`이 화이트리스트 정규식으로 2차 검증한
   뒤 리터럴로 박는다. (c) `LIKE`/`%`는 쓰지 않는다.
   → rag_chat의 `retrieval/structured.py`와 같은 "템플릿 질의 전용, 자유형 SQL
   생성 금지" 원칙.

3. **스키마**: `KO_*`는 `public` 소유(**타 팀 자산 — 절대 쓰기 금지**)라
   `public.`을 그대로 명시한다. `services/shared/db.py`의 "PG_SCHEMA를 쓰고
   public을 하드코딩하지 말 것"은 *komir 자신의 산출물*에 대한 규칙이지, 타 팀
   테이블을 읽는 경우가 아니다(komir 산출물은 `mineral_risk` 스키마·`MSR_DB`).

**2026-08-11 실측(문서·원본코드 예시를 믿지 않고 직접 조회)**
- `information_schema.columns` 조회 결과 9개 테이블의 컬럼명·개수가 원본
  `_DatasetSpec`과 **전부 일치**(대소문자만 다름 — PG가 미인용 식별자를
  소문자로 접으므로 원본의 대문자 SQL도 그대로 동작).
- 다만 **적재된 데이터는 텅스텐(MNRL0018) 단일 광종 demo 슬라이스**다:
  ko_mrkt_prspect_idct 170행/ko_spdm_stbt_indx 98행/ko_mnrl_prc_predc 76행/
  ko_rsrc_*_quty 56·63행이 전부 MNRL0018, ko_cstm_cmmrc·ko_un_cmmrc의 HS도
  8101*(텅스텐)·820900 계열뿐. komir 5광종(CU/NI/CO/LI/REE)은 **한 건도 없다**.
- `ko_un_cmmrc.mnrknd_unq_cd`는 **전 행 NULL**(25,342행) — 원본 코드의
  `map_global` 광종 필터(`MNRKND_UNQ_CD = %s`)는 항상 0행을 돌려준다.
  이식본은 이 사실을 `map_global` 스펙 주석에 남기고 동작은 원본과 동일하게 뒀다
  (조용히 hs_cd only로 바꾸면 호출자가 광종 필터가 먹은 줄 착각한다).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import read_sql_pg

AnalysisPreviewPageId = Literal[
    "price_base_metals",
    "price_minor_metals",
    "price_iron_energy",
    "price_other",
    "indicator_composite",
    "indicator_market",
    "indicator_supply",
    "forecast_price",
    "map_korea",
    "map_global",
    "map_mineral",
]
Period = Literal["year", "month", "day"]

#: `KO_*`가 사는 스키마. 타 팀(public) 소유 — 읽기 전용.
KOMIS_SCHEMA = "public"

#: 2026-09-07(사용자 요청) — `COMMENT ON COLUMN`으로 이미 달려있는 한글
#: 설명(예: KO_MNRL_PRC.lowst_prc="최저가격")을 테이블당 한 번만 조회해
#: 캐싱한다. 스키마 코멘트는 런타임에 안 바뀌므로 프로세스 생애주기 동안
#: 재조회할 이유가 없다 — 매 komis_raw_lookup 호출마다 다시 물으면 조회
#: 1건이 SQL 2번(본 쿼리+코멘트 쿼리)이 된다.
_COLUMN_COMMENT_CACHE: dict[str, dict[str, str]] = {}


def _column_comments(table: str) -> dict[str, str]:
    """`table`(KOMIS_SCHEMA 기준)의 컬럼명 -> 코멘트 매핑. 코멘트가 없는
    컬럼은 결과에서 빠진다(호출측이 `.get(column)`으로 조회, 없으면 원본
    컬럼명만 쓰면 됨). 조회 자체가 실패해도(권한 문제 등) 빈 dict로 조용히
    열화 — 컬럼 라벨은 부가정보라 실패해도 본 조회를 막을 이유가 없다."""

    if table in _COLUMN_COMMENT_CACHE:
        return _COLUMN_COMMENT_CACHE[table]
    # _DatasetSpec.table은 SQL 안에서 부호 없는 식별자로 쓰여(예: "KO_MNRL_PRC")
    # Postgres가 파싱 시 자동으로 소문자로 접기 때문에 실제 pg_class.relname은
    # 항상 소문자다("ko_mnrl_prc") — 여기 c.relname 비교는 리터럴 문자열이라
    # 자동 접기가 안 일어나므로 직접 소문자로 맞춰야 한다(2026-09-07 실측
    # 발견 — 안 맞추면 늘 빈 dict만 돌아와 라벨이 조용히 하나도 안 붙었다).
    table_lower = table.lower()
    query = (
        "SELECT a.attname AS column_name, d.description "
        "FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_catalog.pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum "
        f"WHERE n.nspname = {_literal(KOMIS_SCHEMA)} AND c.relname = {_literal(table_lower)} "
        "AND a.attnum > 0 AND NOT a.attisdropped"
    )
    try:
        frame = read_sql_pg(query)
    except Exception:  # noqa: BLE001 — 부가정보 조회 실패는 조용히 열화
        _COLUMN_COMMENT_CACHE[table] = {}
        return {}
    comments = {
        str(row["column_name"]).lower(): str(row["description"])
        for row in frame.to_dict("records")
        if row.get("description")
    }
    _COLUMN_COMMENT_CACHE[table] = comments
    return comments


class RawDataAccessError(RuntimeError):
    """KO_* 원천 조회에 실패했을 때(원본 `scaffold.RawDataAccessError` 이식)."""


class StrictModel(BaseModel):
    """정의되지 않은 필드를 거부하는 기반 모델(원본 `analysis.models.StrictModel`)."""

    model_config = ConfigDict(extra="forbid")


class AnalysisPreviewRequest(StrictModel):
    """읽기 전용 원천 미리보기 필터(원본 그대로 — 패턴 검증이 1차 방어선)."""

    page_id: AnalysisPreviewPageId
    mineral_code: str | None = Field(default=None, min_length=1, max_length=32)
    hs_code: str | None = Field(default=None, min_length=1, max_length=32)
    index_type_code: str | None = Field(default=None, min_length=1, max_length=32)
    price_criterion_serial: int | None = Field(default=None, ge=1)
    start_period: str | None = Field(default=None, pattern=r"^\d{4}(?:\d{2}(?:\d{2})?)?$")
    end_period: str | None = Field(default=None, pattern=r"^\d{4}(?:\d{2}(?:\d{2})?)?$")
    # 미리보기 쿼리의 안전장치. 명시된 기간은 fetch_complete()가 limit 없이
    # 조회하고, 기간 미지정 조회는 환경변수 상한도 적용한다.
    limit: int = Field(default=5, ge=1, le=200)

    @model_validator(mode="after")
    def validate_period(self) -> "AnalysisPreviewRequest":
        if self.start_period and self.end_period:
            if len(self.start_period) != len(self.end_period):
                raise ValueError("start_period and end_period must use the same precision")
            if self.start_period > self.end_period:
                raise ValueError("start_period must not be after end_period")
        return self

    def requested_filters(self) -> dict[str, str | int]:
        """호출자가 명시적으로 준 필터만 돌려준다."""

        return {
            key: value
            for key, value in {
                "mineral_code": self.mineral_code,
                "hs_code": self.hs_code,
                "index_type_code": self.index_type_code,
                "price_criterion_serial": self.price_criterion_serial,
                "start_period": self.start_period,
                "end_period": self.end_period,
            }.items()
            if value is not None
        }


class RawDataset(StrictModel):
    """원천 테이블 1개에서 읽어온 행과 컬럼 메타.

    2026-09-07(사용자 요청) — `column_labels`는 Postgres `COMMENT ON COLUMN`
    으로 이미 달려있는 한글 설명(예: `lowst_prc`="최저가격")을 컬럼명별로
    담는다. `columns`(row dict 키·필터·날짜열 판정 등 코드 전반이 참조하는
    원본 컬럼명)는 그대로 두고, 화면·근거 표시용 라벨만 별도 필드로 분리했다
    — 표시 형식을 나중에 바꾸더라도 원본 컬럼명에 의존하는 로직(예:
    chatbot_events.py의 날짜열 판정)이 깨지지 않는다."""

    source_table: str
    columns: list[str]
    column_labels: dict[str, str] = Field(default_factory=dict)
    row_count: int = Field(ge=0)
    rows: list[dict[str, Any]]
    # 집계 결과는 원시 행에서 기간을 다시 유추할 수 없다. 조회가 실제로 사용한
    # 기간과 측정 단위를 결과 계약에 함께 보관해 Evidence/표/차트가 같은 기준을
    # 보게 한다. 기존 원시 조회는 기본값(None)으로 하위 호환된다.
    as_of: str | None = None
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class _DatasetSpec:
    table: str
    columns: tuple[str, ...]
    period_column: str
    period_precision: Period
    filter_columns: Mapping[str, str]
    fixed_conditions: tuple[str, ...] = ()


_PRICE_SPEC = _DatasetSpec(
    table="KO_MNRL_PRC",
    columns=(
        "MNRL_PRC_CRTR_SN",
        "CRTR_YMD",
        "LOWST_PRC",
        "HGHST_PRC",
        "CMERC_PRC",
        "INVT",
    ),
    period_column="CRTR_YMD",
    period_precision="day",
    filter_columns={"price_criterion_serial": "MNRL_PRC_CRTR_SN"},
    # 2026-09-16 실측: STATUS='Y'인데 LAST_DEL_DT(최종삭제일시)가 채워진 소프트삭제
    # 행 11건이 있고 전부 기준일자 20270703(미래)·최저/최고가 NULL이다 — 최신순
    # 조회에서 맨 앞에 와 "니켈 최신 가격 2027-07-03 15,250"처럼 답변·차트를
    # 오염시켰다. 삭제된 행은 KOMIS 원천 어디서도 살아있는 데이터가 아니므로 뺀다.
    fixed_conditions=("STATUS = 'Y'", "LAST_DEL_DT IS NULL"),
)

_PAGE_DATASETS: dict[str, tuple[_DatasetSpec, ...]] = {
    "price_base_metals": (_PRICE_SPEC,),
    "price_minor_metals": (_PRICE_SPEC,),
    "price_iron_energy": (_PRICE_SPEC,),
    "price_other": (_PRICE_SPEC,),
    "indicator_composite": (
        _DatasetSpec(
            table="KO_MNRL_SNTHS_INDX",
            columns=("INDX_SE_CD", "CRTR_YMD", "INDX", "PRVDY_CPRS", "UPLMT", "LWLMT", "CENTER"),
            period_column="CRTR_YMD",
            period_precision="day",
            filter_columns={"index_type_code": "INDX_SE_CD"},
        ),
    ),
    "indicator_market": (
        _DatasetSpec(
            table="KO_MRKT_PRSPECT_IDCT",
            columns=("MNRKND_UNQ_CD", "CRTR_YMD", "MRKT_PRSPECT_IDCT", "REAL_PRC", "PRVMM_CPRS"),
            period_column="CRTR_YMD",
            # 실측: 이 테이블의 crtr_ymd는 8자리(YYYYMMDD, 예 20250201)라 day가 맞다.
            period_precision="day",
            filter_columns={"mineral_code": "MNRKND_UNQ_CD"},
        ),
    ),
    "indicator_supply": (
        _DatasetSpec(
            table="KO_SPDM_STBT_INDX",
            columns=(
                "MNRKND_UNQ_CD",
                "CRTR_YMD",
                "SPDM_STBT_INDX",
                "REAL_PRC",
                "PRVMM_CPRS",
                "PRC",
                "INCM_WEIG",
                "INCM_AMT",
            ),
            period_column="CRTR_YMD",
            # 실측: 이 테이블만 crtr_ymd가 6자리(YYYYMM, 예 202502) — month가 맞다.
            period_precision="month",
            filter_columns={"mineral_code": "MNRKND_UNQ_CD"},
        ),
    ),
    "forecast_price": (
        _DatasetSpec(
            table="KO_MNRL_PRC_PREDC",
            columns=(
                "MNRL_PRC_PREDC_SN",
                "MNRKND_UNQ_CD",
                "CRTR_YMD",
                "PRD_SE_CD",
                "PRC_UNIT_CD",
                "CMERC_PRC",
                "PREDC_PRC",
            ),
            period_column="CRTR_YMD",
            period_precision="day",
            filter_columns={"mineral_code": "MNRKND_UNQ_CD"},
        ),
    ),
    "map_korea": (
        _DatasetSpec(
            table="KO_CSTM_CMMRC",
            columns=(
                "HS_CD",
                "CRTR_YMD",
                "TRGT_NTN_CD",
                "INCM_WEIG",
                "INCM_AMT",
                "EXP_WEIG",
                "EXP_AMT",
                "TRGT_NTN",
                "ITEM_NM",
            ),
            period_column="CRTR_YMD",
            period_precision="day",
            filter_columns={"hs_code": "HS_CD"},
        ),
    ),
    "map_global": (
        _DatasetSpec(
            table="KO_UN_CMMRC",
            columns=(
                "HS_CD",
                "CRTR_YMD",
                "INCM_NTN_CD",
                "EXP_NTN_CD",
                "IMXPRT_SE_CD",
                "CRTR_NTN_NM",
                "TRGT_NTN_NM",
                "WEIG",
                "AMT",
                "MNRKND_UNQ_CD",
            ),
            period_column="CRTR_YMD",
            period_precision="day",
            # ⚠ 2026-08-11 실측: MNRKND_UNQ_CD는 25,342행 전부 NULL이다 —
            #   mineral_code 필터를 주면 항상 0행. hs_code로 거를 것.
            filter_columns={"mineral_code": "MNRKND_UNQ_CD", "hs_code": "HS_CD"},
        ),
    ),
    "map_mineral": (
        _DatasetSpec(
            table="KO_RSRC_BURUDG_QUTY",
            columns=(
                "MNRKND_UNQ_CD",
                "CRTR_YR",
                "NTN_ENG_CD",
                "MASS_UNIT_CD",
                "RSRC_INVT_CD",
                "BURUDG_QUTY",
                "SE_CD",
                "BURUDG_QUTY_TON",
            ),
            period_column="CRTR_YR",
            period_precision="year",
            filter_columns={"mineral_code": "MNRKND_UNQ_CD"},
        ),
        _DatasetSpec(
            table="KO_RSRC_PRDCTN_QUTY",
            columns=(
                "MNRKND_UNQ_CD",
                "CRTR_YR",
                "NTN_ENG_CD",
                "MASS_UNIT_CD",
                "PRDCTN_QUTY",
                "SE_CD",
                "PRDCTN_QUTY_TON",
            ),
            period_column="CRTR_YR",
            period_precision="year",
            filter_columns={"mineral_code": "MNRKND_UNQ_CD"},
        ),
    ),
}

#: 2026-09-18(챗봇 피드백통합 QA B2 후속) — 국가별 랭킹(GROUP BY+ORDER+LIMIT)
#: 전용 스펙. `_PAGE_DATASETS`(필터+정렬+LIMIT만, 집계 없음)와 별개 경로다 —
#: "리튬 수입 상위 5개국" 같은 질문이 komis_raw로 라우팅돼도 기존
#: `_fetch_dataset`은 "최근 N건" 원자료만 돌려줘 순위를 만들 수 없었다(실측
#: 확인: `KO_CSTM_CMMRC.trgt_ntn`(대상국가)이 28만행 전부 채워져 있어 집계
#: 자체는 가능한데 도구가 안 했을 뿐). map_korea(관세청, 한국↔상대국)·
#: map_global(UN Comtrade, 임의 두 나라 간 교역 — `imxprt_se_cd`로 수입/수출
#: 관점을 가른다, 'I'=수입국 관점 crtr_ntn_nm이 수입국·'O'=수출국 관점
#: crtr_ntn_nm이 수출국) 두 페이지만 국가 컬럼이 있어 대상이다. map_mineral
#: (매장량·생산량)은 국가 컬럼(`ntn_eng_cd`)이 있지만 이번 범위 밖(§리스트업
#: 참고 — 후속 후보로만 기록).
_RANKING_SPECS: dict[str, dict[str, Any]] = {
    "map_korea": {
        "table": "KO_CSTM_CMMRC",
        "country_column": "TRGT_NTN",
        "period_column": "CRTR_YMD",
        "period_precision": "day",
        "metrics": {
            "import_amount": "INCM_AMT", "import_weight": "INCM_WEIG",
            "export_amount": "EXP_AMT", "export_weight": "EXP_WEIG",
        },
        "direction_column": None,
        "direction_values": {},
    },
    "map_global": {
        "table": "KO_UN_CMMRC",
        "country_column": "CRTR_NTN_NM",
        "period_column": "CRTR_YMD",
        "period_precision": "day",
        "metrics": {
            "import_amount": "AMT", "import_weight": "WEIG",
            "export_amount": "AMT", "export_weight": "WEIG",
        },
        "direction_column": "IMXPRT_SE_CD",
        "direction_values": {
            "import_amount": "I", "import_weight": "I",
            "export_amount": "O", "export_weight": "O",
        },
    },
}

#: metric -> (한글 라벨, 단위) — Evidence 표 헤더·section 문구에 재사용.
_RANKING_METRIC_LABELS = {
    "import_amount": ("수입금액", "USD"),
    "import_weight": ("수입중량", "kg"),
    "export_amount": ("수출금액", "USD"),
    "export_weight": ("수출중량", "kg"),
}

#: 2026-09-18(챗봇 RDB 결정적쿼리 후보리스트 1순위) — 매장량·생산량 국가
#: 랭킹. `_RANKING_SPECS`(교역, HS코드 번역 필요)와 달리 이 두 테이블은
#: map_mineral의 기존 필터(mnrknd_unq_cd)로 광종을 바로 거른다 — HS코드
#: 매핑을 거치지 않는다. `*_ton` 컬럼은 KOMIS가 이미 톤 단위로 환산해둔
#: 값이라(컬럼 코멘트 "[샘플확장] 생산량/매장량(톤환산)") mine_aggregate처럼
#: 별도 단위정규화 로직을 새로 만들 필요가 없다(2026-09-18 실측 확인 —
#: WT002 단위 행도 prdctn_quty==prdctn_quty_ton으로 이미 톤 기준이었음).
_RESERVES_PRODUCTION_RANKING_SPECS: dict[str, dict[str, str]] = {
    "production": {
        "table": "KO_RSRC_PRDCTN_QUTY", "country_column": "NTN_ENG_CD",
        "metric_column": "PRDCTN_QUTY_TON", "period_column": "CRTR_YR",
        "metric_label": "생산량",
    },
    "reserves": {
        "table": "KO_RSRC_BURUDG_QUTY", "country_column": "NTN_ENG_CD",
        "metric_column": "BURUDG_QUTY_TON", "period_column": "CRTR_YR",
        "metric_label": "매장량",
    },
}

#: 흔한 광종 동의어 -> `ai_mnrl_mst.mnrl_nm_ko`에 실제로 저장된 정본 명칭.
#: 그 컬럼엔 동의어 컬럼이 따로 없어(정본 하나만) `resolve_mineral_full()`이
#: 이 목록으로 원래 표현이 안 잡히면 정본으로도 같이 시도한다(2026-09-01,
#: main-agent가 "구리"/"납"/"희토류"가 안 잡히는 회귀를 실측으로 발견해
#: 추가). "동/연/네오디뮴"은 이미 DB 실조회로 잡히므로 넣지 않는다 — 여긴
#: "DB에 없는 다른 이름"만 다룬다.
_MINERAL_SYNONYMS = {"구리": "동", "납": "연", "희토류": "네오디뮴"}

#: `_literal()`이 허용하는 값 모양 — 이 밖의 문자는 SQL에 못 들어간다.
#: 2026-09-01: 한글 음절(가~힣, U+AC00~U+D7A3) 범위를 추가했다 —
#: `resolve_mineral_full()`이 `ai_mnrl_mst.mnrl_nm_ko`(한글 광종명)를 그대로
#: 조회 조건으로 써야 해서다. 화이트리스트 성격은 그대로다: 여전히 따옴표·
#: 세미콜론·백슬래시·공백 등 SQL 메타문자는 전부 제외되고, 순수 한글
#: 음절+영숫자+밑줄만 허용한다 — 인젝션 방어력이 약해지는 게 아니라 허용
#: 문자 "집합"만 넓어진 것이다.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_가-힣]{1,32}$")


def _literal(value: str | int) -> str:
    """검증된 필터 값을 SQL 리터럴로 만든다(바인딩 불가 경로의 2차 방어선)."""

    if isinstance(value, bool):  # bool은 int의 하위형 — 먼저 막는다
        raise RawDataAccessError(f"허용되지 않는 필터 값 타입: {value!r}")
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if not _SAFE_VALUE.match(text):
        raise RawDataAccessError(f"허용되지 않는 필터 값: {value!r}")
    return f"'{text}'"


def _coerce_period(value: str, precision: Period, upper: bool) -> str:
    """요청 기간 문자열을 스펙의 정밀도(year/month/day)에 맞춰 자르거나 채운다."""

    expected_length = {"year": 4, "month": 6, "day": 8}[precision]
    if len(value) == expected_length:
        return value
    if len(value) > expected_length:
        return value[:expected_length]
    if precision == "day":
        suffix = ("1231" if upper else "0101") if len(value) == 4 else ("31" if upper else "01")
    else:
        suffix = "12" if upper else "01"
    return (value + suffix)[:expected_length]


def _format_period_value(value: Any, precision: Period) -> str:
    """DB 집계의 실제 기간값을 Evidence에 쓸 일관된 표기로 바꾼다."""

    raw = str(value)
    if precision == "day" and len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if precision == "month" and len(raw) >= 6 and raw[:6].isdigit():
        return f"{raw[:4]}-{raw[4:6]}"
    return raw[:4] if precision == "year" and len(raw) >= 4 else raw


class KomisRawDataRepository:
    """`public.KO_*` 페이지 단위 원천 데이터셋 읽기 전용 리포지토리.

    원본 `PostgresRawDataRepository`와 메서드 시그니처가 같다(fetch/fetch_complete/
    fetch_indicator_dataset/close) — 원본의 `RawDataRepository`·
    `IndicatorDatabaseRepository`·`CompleteRawDataRepository` Protocol을 그대로
    만족한다. 커넥션을 들고 있지 않으므로(`read_sql_pg`가 매 호출 엔진 생성)
    `close()`는 no-op다.
    """

    def fetch(self, request: AnalysisPreviewRequest) -> list[RawDataset]:
        """limit이 걸린 미리보기용 데이터셋을 페이지 스펙 수만큼 읽는다."""

        return self._fetch_page(request, apply_limit=True)

    def fetch_complete(self, request: AnalysisPreviewRequest) -> list[RawDataset]:
        """미리보기 limit 없이 요청 조건의 전 행을 읽는다."""

        return self._fetch_page(request, apply_limit=False)

    def fetch_indicator_dataset(
        self,
        *,
        page_id: str,
        mineral_code: str,
        start_month: str | None,
        end_month: str | None,
    ) -> RawDataset:
        """지표(시장전망/수급안정) 계열을 limit 없이 읽는다(계산용)."""

        request = AnalysisPreviewRequest(
            page_id=page_id,
            mineral_code=mineral_code,
            start_period=start_month.replace("-", "") if start_month else None,
            end_period=end_month.replace("-", "") if end_month else None,
        )
        try:
            return self._fetch_dataset(_PAGE_DATASETS[page_id][0], request, apply_limit=False)
        except RawDataAccessError:
            raise
        except Exception as exc:  # noqa: BLE001 — 원본과 같은 사용자 노출 메시지
            raise RawDataAccessError("분석 원천데이터 조회에 실패했습니다.") from exc

    def _fetch_page(self, request: AnalysisPreviewRequest, *, apply_limit: bool) -> list[RawDataset]:
        try:
            return [
                self._fetch_dataset(spec, request, apply_limit=apply_limit)
                for spec in _PAGE_DATASETS[request.page_id]
            ]
        except RawDataAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("분석 원천데이터 조회에 실패했습니다.") from exc

    @staticmethod
    def _fetch_dataset(
        spec: _DatasetSpec,
        request: AnalysisPreviewRequest,
        *,
        apply_limit: bool = True,
    ) -> RawDataset:
        """정적 스펙 + 검증된 리터럴만으로 SELECT 한 문장을 조립·실행한다."""

        conditions = list(spec.fixed_conditions)
        requested_filters = request.requested_filters()
        for filter_name, column in spec.filter_columns.items():
            if filter_name not in requested_filters:
                continue
            conditions.append(f"{column} = {_literal(requested_filters[filter_name])}")
        if request.start_period:
            bound = _coerce_period(request.start_period, spec.period_precision, False)
            conditions.append(f"{spec.period_column} >= {_literal(bound)}")
        if request.end_period:
            bound = _coerce_period(request.end_period, spec.period_precision, True)
            conditions.append(f"{spec.period_column} <= {_literal(bound)}")

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        columns = ", ".join(spec.columns)
        query = (
            f"SELECT {columns} FROM {KOMIS_SCHEMA}.{spec.table}{where_clause}"
            f" ORDER BY {spec.period_column} DESC"
        )
        if apply_limit:
            query = f"{query} LIMIT {int(request.limit)}"

        frame = read_sql_pg(query)
        column_names = [str(name).lower() for name in frame.columns]
        rows = [
            {column: _json_value(value) for column, value in zip(column_names, record)}
            for record in frame.itertuples(index=False, name=None)
        ]
        comments = _column_comments(spec.table)
        column_labels = {c: comments[c] for c in column_names if c in comments}
        return RawDataset(
            source_table=spec.table,
            columns=column_names,
            column_labels=column_labels,
            row_count=len(rows),
            rows=rows,
            metadata={"period_range_complete": not apply_limit},
        )

    def close(self) -> None:
        """no-op — 커넥션은 read_sql_pg가 호출 단위로 관리한다."""

    # ────────────────────────────────────────────────────────────────
    # 아래 3개 메서드는 외부repo 이식이 아니다(komir 자체 추가, 2026-08-19) —
    # `/prices`·`/domestic-trade`·`/global-trade`는 원본도 501 스텁이라 참고할
    # 원본 구현이 없다. `ai_mnrl_mst`(광종 마스터)·`ai_prc_mnrl_map`(광종→가격
    # 기준일련번호)·`ai_hs_mnrl_map`(광종→HS코드)은 KOMIS가 이 3개 신규 엔드포인트를
    # 위해 최근 채운 매핑 테이블이라 `_PAGE_DATASETS`(고정 스펙 1건당 필터 1종)
    # 방식으로는 못 담는다 — 광종 하나가 가격기준·HS코드 여러 건에 매핑되기 때문에
    # 별도 조회로 분리했다. 위 SELECT 조립부와 동일하게 `_literal()` 화이트리스트를
    # 거친다(자유형 SQL 생성 금지 원칙은 그대로).
    # ────────────────────────────────────────────────────────────────

    def resolve_mineral(self, mineral_code: str) -> tuple[str, str] | None:
        """`ai_mnrl_mst`에서 (코드, 한글명)을 찾는다. 없으면 None."""

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT mnrknd_unq_cd, mnrl_nm_ko FROM {KOMIS_SCHEMA}.ai_mnrl_mst"
            f" WHERE mnrknd_unq_cd = {code}"
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        return str(row["mnrknd_unq_cd"]), str(row["mnrl_nm_ko"])

    def resolve_price_criterion_serials(self, mineral_code: str) -> list[int]:
        """`ai_prc_mnrl_map`에서 광종의 가격기준일련번호(들)를 찾는다(오름차순)."""

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT mnrl_prc_crtr_sn FROM {KOMIS_SCHEMA}.ai_prc_mnrl_map"
            f" WHERE mnrknd_unq_cd = {code} AND use_yn = 'Y'"
            f" ORDER BY mnrl_prc_crtr_sn"
        )
        return [int(value) for value in frame["mnrl_prc_crtr_sn"]]

    def resolve_price_criterion_metadata(self, serial: int) -> tuple[str | None, str | None, str | None] | None:
        """선택 가격기준의 표시명과 원시 단위 코드를 돌려준다."""

        frame = read_sql_pg(
            f"SELECT prc_crtr, prc_unit_cd, weig_unit_cd "
            f"FROM {KOMIS_SCHEMA}.KO_MNRL_PRC_CRTR "
            f"WHERE mnrl_prc_crtr_sn = {_literal(serial)}"
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        return (
            None if row["prc_crtr"] is None else str(row["prc_crtr"]),
            None if row["prc_unit_cd"] is None else str(row["prc_unit_cd"]),
            None if row["weig_unit_cd"] is None else str(row["weig_unit_cd"]),
        )

    def price_criteria_have_dummy_rows(self, serials: list[int]) -> dict[int, bool]:
        """선택 가격기준별 ``KO_MNRL_PRC`` 더미 추적 행 존재를 확인한다.

        광종 마스터의 출처 표식은 같은 광종의 다른 가격기준까지 포괄한다.
        가격 원시행 추적키의 첫 토큰인 가격기준 일련번호만 사용한다.
        """

        if not serials:
            return {}
        # SPLIT_PART는 text를 반환한다. PostgreSQL이 text와 integer를 자동
        # 비교하지 않으므로 serial도 명시적으로 text 리터럴로 맞춘다.
        values = ", ".join(_literal(str(int(serial))) for serial in serials)
        frame = read_sql_pg(
            "SELECT CAST(SPLIT_PART(nat_key, '|', 1) AS INTEGER) AS serial "
            f"FROM {KOMIS_SCHEMA}.ai_dev_dummy_load "
            "WHERE tbl_nm = 'ko_mnrl_prc' "
            f"AND SPLIT_PART(nat_key, '|', 1) IN ({values}) "
            "GROUP BY 1"
        )
        found = {int(value) for value in frame["serial"]}
        return {int(serial): int(serial) in found for serial in serials}

    def resolve_hs_codes(self, mineral_code: str) -> list[str]:
        """`ai_hs_mnrl_map`에서 광종의 HS코드(들)를 찾는다(오름차순)."""

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT hs_cd FROM {KOMIS_SCHEMA}.ai_hs_mnrl_map"
            f" WHERE mnrknd_unq_cd = {code} AND use_yn = 'Y'"
            f" ORDER BY hs_cd"
        )
        return [str(value) for value in frame["hs_cd"]]

    def fetch_monthly_trade_summary(
        self, *, hs_codes: list[str], start_period: str | None, end_period: str | None,
    ) -> RawDataset:
        """HS 모집단의 한국 수입을 월별 금액·중량으로 집계한다.

        ``KO_CSTM_CMMRC``의 기준일은 일/월 혼재 가능하므로 월 키를
        ``LEFT(CRTR_YMD, 6)``으로 명시한다. 미래월을 0으로 채우지 않고 실제
        관측된 월만 반환한다. 명시 HS 질의도 호출자가 한 코드만 넘겨 이 메서드로
        처리하므로, 광종 HS 묶음과 혼동되지 않는다.
        """

        if not hs_codes:
            raise RawDataAccessError("월별 수입 집계에는 hs_codes가 최소 1개 필요합니다.")
        conditions = [f"HS_CD IN ({', '.join(_literal(code) for code in hs_codes)})"]
        if start_period:
            conditions.append(f"CRTR_YMD >= {_literal(_coerce_period(start_period, 'day', False))}")
        if end_period:
            conditions.append(f"CRTR_YMD <= {_literal(_coerce_period(end_period, 'day', True))}")
        where_clause = " AND ".join(conditions)
        try:
            frame = read_sql_pg(
                f"SELECT LEFT(CRTR_YMD, 6) AS month, SUM(INCM_AMT) AS import_amount, "
                f"SUM(INCM_WEIG) AS import_weight, COUNT(*) AS transaction_count "
                f"FROM {KOMIS_SCHEMA}.KO_CSTM_CMMRC WHERE {where_clause} "
                "GROUP BY LEFT(CRTR_YMD, 6) ORDER BY month"
            )
            summary = read_sql_pg(
                f"SELECT MIN(CRTR_YMD) AS available_start, MAX(CRTR_YMD) AS available_end, "
                "SUM(INCM_AMT) AS period_total_amount, SUM(INCM_WEIG) AS period_total_weight, "
                "COUNT(*) AS period_transaction_count, "
                "STRING_AGG(DISTINCT ITEM_NM, ', ' ORDER BY ITEM_NM) AS item_names "
                f"FROM {KOMIS_SCHEMA}.KO_CSTM_CMMRC WHERE {where_clause}"
            )
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("월별 수입금액·중량 집계 조회에 실패했습니다.") from exc

        rows = [
            {
                "month": _format_period_value(month, "month"),
                "import_amount": _json_value(amount),
                "import_weight": _json_value(weight),
                "transaction_count": int(count),
            }
            for month, amount, weight, count in frame.itertuples(index=False, name=None)
        ]
        meta = summary.iloc[0] if not summary.empty else None
        available_start = meta["available_start"] if meta is not None else None
        available_end = meta["available_end"] if meta is not None else None
        return RawDataset(
            source_table="KO_CSTM_CMMRC",
            columns=["month", "import_amount", "import_weight", "transaction_count"],
            column_labels={
                "month": "월", "import_amount": "수입금액합계(USD)",
                "import_weight": "수입중량합계(kg)", "transaction_count": "거래건수",
            },
            row_count=len(rows), rows=rows,
            as_of=(f"{_format_period_value(available_start, 'day')}~"
                   f"{_format_period_value(available_end, 'day')}"
                   if available_start is not None and available_end is not None else None),
            unit="USD, kg",
            metadata={
                "hs_codes": list(hs_codes),
                "item_names": meta["item_names"] if meta is not None else None,
                "available_start": _format_period_value(available_start, "day") if available_start is not None else None,
                "available_end": _format_period_value(available_end, "day") if available_end is not None else None,
                "requested_start": start_period,
                "requested_end": end_period,
                "period_total_amount": _json_value(meta["period_total_amount"]) if meta is not None else None,
                "period_total_weight": _json_value(meta["period_total_weight"]) if meta is not None else None,
                "period_transaction_count": int(meta["period_transaction_count"]) if meta is not None and meta["period_transaction_count"] is not None else 0,
            },
        )

    def fetch_explicit_hs_import_summary(
        self, *, hs_code: str, start_period: str | None, end_period: str | None,
    ) -> RawDataset:
        """명시한 한 HS 코드의 수입 월별 집계 래퍼다.

        광종→HS 매핑을 적용하지 않는다. 따라서 사용자가 지정한 HS와 광종 전체
        HS 모집단을 구별해야 하는 Q14 같은 질의에서 안전하다.
        """

        dataset = self.fetch_monthly_trade_summary(
            hs_codes=[hs_code], start_period=start_period, end_period=end_period,
        )
        return dataset.model_copy(update={"metadata": {
            "scope": "explicit_hs_only", "hs_code": hs_code,
            **dataset.metadata,
        }})

    def fetch_price_comparison(
        self, *, mineral_names: list[str], start_period: str | None, end_period: str | None,
    ) -> RawDataset:
        """선택 광종의 대표 가격기준을 공통 실제 가용기간에서 비교한다.

        가격기준마다 시작·종료일이 달라 각 광종의 최초/최종 행을 바로 비교하면
        기간이 달라진다. 먼저 광종별 가용범위를 구하고 그 교집합을 계산한 뒤,
        그 범위의 시계열과 양 끝 가격·변동률을 함께 반환한다. ``PRC_UNIT_CD``와
        ``WEIG_UNIT_CD``도 결과에 유지해 서로 다른 통화·중량 기준의 가격을
        절대값으로 순위화하지 못하게 한다.
        """

        if not mineral_names:
            raise RawDataAccessError("가격 비교에는 mineral_names가 최소 1개 필요합니다.")
        # 질문 표현(구리 등)과 ai_mnrl_mst 정본명(동 등)을 맞춘다. 결과에는
        # 사용자가 요청한 표현을 복원해 표·차트에서 광종이 사라진 것처럼 보이지
        # 않게 한다.
        requested_by_canonical = {
            _MINERAL_SYNONYMS.get(name, name): name
            for name in mineral_names
        }
        names = ", ".join(_literal(name) for name in requested_by_canonical)
        requested_conditions: list[str] = ["p.status = 'Y'", "p.last_del_dt IS NULL", "p.cmerc_prc IS NOT NULL"]
        if start_period:
            requested_conditions.append(
                f"p.crtr_ymd >= {_literal(_coerce_period(start_period, 'day', False))}"
            )
        if end_period:
            requested_conditions.append(
                f"p.crtr_ymd <= {_literal(_coerce_period(end_period, 'day', True))}"
            )
        price_where = " AND ".join(requested_conditions)
        try:
            criteria = read_sql_pg(f"""
                WITH candidate_criteria AS (
                    SELECT ms.mnrl_nm_ko AS mineral, pm.mnrl_prc_crtr_sn AS serial,
                           c.prc_crtr, c.prc_unit_cd, c.weig_unit_cd,
                           MIN(p.crtr_ymd) AS available_start, MAX(p.crtr_ymd) AS available_end
                    FROM {KOMIS_SCHEMA}.ai_prc_mnrl_map pm
                    JOIN {KOMIS_SCHEMA}.ai_mnrl_mst ms ON ms.mnrknd_unq_cd = pm.mnrknd_unq_cd
                    JOIN {KOMIS_SCHEMA}.KO_MNRL_PRC_CRTR c ON c.mnrl_prc_crtr_sn = pm.mnrl_prc_crtr_sn
                    JOIN {KOMIS_SCHEMA}.KO_MNRL_PRC p ON p.mnrl_prc_crtr_sn = pm.mnrl_prc_crtr_sn
                    WHERE pm.use_yn = 'Y' AND ms.mnrl_nm_ko IN ({names}) AND {price_where}
                    GROUP BY ms.mnrl_nm_ko, pm.mnrl_prc_crtr_sn, c.prc_crtr, c.prc_unit_cd, c.weig_unit_cd
                ), ranked_criteria AS (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY mineral
                               ORDER BY serial
                           ) AS criterion_rank
                    FROM candidate_criteria
                )
                SELECT rc.mineral, rc.serial, rc.prc_crtr, rc.prc_unit_cd, rc.weig_unit_cd,
                       rc.available_start, rc.available_end
                FROM ranked_criteria rc
                WHERE rc.criterion_rank = 1
                ORDER BY rc.mineral
            """)
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("광종 간 가격 비교의 가용기간 조회에 실패했습니다.") from exc

        if criteria.empty:
            return RawDataset(source_table="KO_MNRL_PRC", columns=[], row_count=0, rows=[], metadata={
                "requested_start": start_period, "requested_end": end_period,
                "missing_minerals": list(mineral_names),
            })
        available = criteria.dropna(subset=["available_start", "available_end"])
        found = set(str(value) for value in available["mineral"])
        common_start = max(str(value) for value in available["available_start"])
        common_end = min(str(value) for value in available["available_end"])
        if common_start > common_end:
            raise RawDataAccessError("선택 광종의 가격 가용기간에 공통 구간이 없습니다.")
        serials = ", ".join(_literal(int(value)) for value in available["serial"])
        try:
            series = read_sql_pg(f"""
                SELECT ms.mnrl_nm_ko AS mineral, p.crtr_ymd AS price_date, p.cmerc_prc AS price,
                       pm.mnrl_prc_crtr_sn AS price_criterion_serial, c.prc_crtr AS price_criterion,
                       c.prc_unit_cd AS price_currency_code, c.weig_unit_cd AS weight_unit_code
                FROM {KOMIS_SCHEMA}.KO_MNRL_PRC p
                JOIN {KOMIS_SCHEMA}.ai_prc_mnrl_map pm ON pm.mnrl_prc_crtr_sn = p.mnrl_prc_crtr_sn
                JOIN {KOMIS_SCHEMA}.ai_mnrl_mst ms ON ms.mnrknd_unq_cd = pm.mnrknd_unq_cd
                JOIN {KOMIS_SCHEMA}.KO_MNRL_PRC_CRTR c ON c.mnrl_prc_crtr_sn = pm.mnrl_prc_crtr_sn
                WHERE p.status = 'Y' AND p.last_del_dt IS NULL AND p.cmerc_prc IS NOT NULL
                  AND pm.use_yn = 'Y' AND pm.mnrl_prc_crtr_sn IN ({serials})
                  AND p.crtr_ymd >= {_literal(common_start)} AND p.crtr_ymd <= {_literal(common_end)}
                ORDER BY ms.mnrl_nm_ko, p.crtr_ymd
            """)
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("광종 간 가격 시계열 조회에 실패했습니다.") from exc

        rows = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in series.to_dict("records"):
            row = {
                "mineral": requested_by_canonical.get(str(record["mineral"]), str(record["mineral"])),
                "price_date": _format_period_value(record["price_date"], "day"),
                "price": _json_value(record["price"]),
                "price_criterion_serial": _json_value(record["price_criterion_serial"]),
                "price_criterion": record["price_criterion"],
                "price_currency_code": record["price_currency_code"],
                "weight_unit_code": record["weight_unit_code"],
            }
            rows.append(row)
            grouped.setdefault(row["mineral"], []).append(row)
        # 가용기간 교집합만으로는 휴장일·개별 결측 때문에 양 끝의 실제
        # 관측일이 다를 수 있다. 비교 대상 모두에 존재하는 날짜의 교집합으로
        # endpoint를 다시 고정해 변동률 분모·분자가 같은 날짜를 가리키게 한다.
        date_sets = [{point["price_date"] for point in points} for points in grouped.values()]
        common_dates = set.intersection(*date_sets) if date_sets else set()
        if not common_dates:
            raise RawDataAccessError("선택 광종의 가격 시계열에 공통 실제 관측일이 없습니다.")
        common_actual_start, common_actual_end = min(common_dates), max(common_dates)
        comparison = []
        for mineral in sorted(grouped):
            points = grouped[mineral]
            by_date = {point["price_date"]: point for point in points}
            first, last = by_date[common_actual_start], by_date[common_actual_end]
            first_price, last_price = float(first["price"]), float(last["price"])
            comparison.append({
                "mineral": mineral, "start_date": first["price_date"], "start_price": first["price"],
                "end_date": last["price_date"], "end_price": last["price"],
                "pct_change": round((last_price - first_price) / first_price * 100, 2) if first_price else None,
                "price_criterion": first["price_criterion"],
                "price_currency_code": first["price_currency_code"], "weight_unit_code": first["weight_unit_code"],
            })
        return RawDataset(
            source_table="KO_MNRL_PRC",
            columns=["mineral", "price_date", "price", "price_criterion", "price_currency_code", "weight_unit_code"],
            column_labels={
                "mineral": "광종", "price_date": "가격일자", "price": "통상가격",
                "price_criterion": "가격기준", "price_currency_code": "가격통화코드",
                "weight_unit_code": "중량단위코드",
            },
            row_count=len(rows), rows=rows,
            as_of=f"{common_actual_start}~{common_actual_end}",
            metadata={
                "comparison": comparison, "common_available_start": _format_period_value(common_start, "day"),
                "common_available_end": _format_period_value(common_end, "day"),
                "common_actual_start": common_actual_start, "common_actual_end": common_actual_end,
                "requested_start": start_period, "requested_end": end_period,
                "missing_minerals": [
                    name for name in mineral_names
                    if _MINERAL_SYNONYMS.get(name, name) not in found
                ],
                "resolved_mineral_names": requested_by_canonical,
            },
        )

    def fetch_country_ranking(
        self, *, page_id: str, hs_codes: list[str], metric: str,
        start_period: str | None, end_period: str | None, top_n: int = 5,
    ) -> RawDataset:
        """국가별 합계 상위 N(결정적 GROUP BY+ORDER BY+LIMIT, 2026-09-18 신설).

        `_fetch_dataset`(위)는 필터+정렬+LIMIT만 지원해 "최근 N건" 원자료를
        돌려줄 뿐 "상위 N개국"을 만들 수 없었다 — 이 메서드가 그 갭을 메운다.
        `_literal()`/`_coerce_period()` 화이트리스트를 그대로 거치므로 자유형
        SQL 생성 금지 원칙은 동일하게 유지된다(page_id·metric은 `_RANKING_SPECS`
        키만 허용, hs_codes는 호출측이 `resolve_hs_codes()`로 이미 얻은 값)."""

        spec = _RANKING_SPECS.get(page_id)
        if spec is None or metric not in spec["metrics"]:
            raise RawDataAccessError(f"'{page_id}'/{metric}은 국가 랭킹 조회를 지원하지 않습니다.")
        if not hs_codes:
            raise RawDataAccessError("국가 랭킹 조회에는 hs_codes가 최소 1개 필요합니다.")

        conditions = [f"HS_CD IN ({', '.join(_literal(c) for c in hs_codes)})"]
        direction_column = spec["direction_column"]
        if direction_column:
            conditions.append(f"{direction_column} = {_literal(spec['direction_values'][metric])}")
        period_column = spec["period_column"]
        period_precision = spec["period_precision"]
        if start_period:
            conditions.append(f"{period_column} >= {_literal(_coerce_period(start_period, period_precision, False))}")
        if end_period:
            conditions.append(f"{period_column} <= {_literal(_coerce_period(end_period, period_precision, True))}")
        where_clause = " AND ".join(conditions)

        table = spec["table"]
        country_column = spec["country_column"]
        metric_column = spec["metrics"][metric]
        try:
            frame = read_sql_pg(
                f"SELECT {country_column} AS country, SUM({metric_column}) AS total, COUNT(*) AS n"
                f" FROM {KOMIS_SCHEMA}.{table} WHERE {where_clause}"
                f" GROUP BY {country_column} ORDER BY total DESC NULLS LAST LIMIT {int(top_n)}"
            )
            total_frame = read_sql_pg(
                f"SELECT SUM({metric_column}) AS grand_total, "
                f"MIN({period_column}) AS period_start, MAX({period_column}) AS period_end "
                f"FROM {KOMIS_SCHEMA}.{table} WHERE {where_clause}"
            )
        except Exception as exc:  # noqa: BLE001 — 원본과 같은 사용자 노출 메시지
            raise RawDataAccessError("국가별 랭킹 조회에 실패했습니다.") from exc

        grand_total_value = total_frame["grand_total"].iloc[0] if not total_frame.empty else None
        grand_total = float(grand_total_value) if grand_total_value is not None else 0.0
        period_start = total_frame["period_start"].iloc[0] if not total_frame.empty else None
        period_end = total_frame["period_end"].iloc[0] if not total_frame.empty else None

        rows: list[dict[str, Any]] = []
        for rank, record in enumerate(frame.itertuples(index=False, name=None), start=1):
            country, total, n = record
            total_value = float(total) if total is not None else 0.0
            share_pct = round(total_value / grand_total * 100, 2) if grand_total else None
            rows.append({
                "rank": rank, "country": country, "total": _json_value(total),
                "share_pct": share_pct, "transaction_count": int(n),
            })

        metric_label, unit = _RANKING_METRIC_LABELS[metric]
        return RawDataset(
            source_table=table,
            columns=["rank", "country", "total", "share_pct", "transaction_count"],
            column_labels={
                "rank": "순위", "country": "국가", "total": f"{metric_label}합계({unit})",
                "share_pct": "비중(%, 같은 기간·조건의 전체 국가 합계 대비)", "transaction_count": "거래건수",
            },
            row_count=len(rows), rows=rows,
            as_of=(f"{_format_period_value(period_start, period_precision)}~"
                   f"{_format_period_value(period_end, period_precision)}"
                   if period_start is not None and period_end is not None else None),
            unit=unit,
            metadata={"grand_total": _json_value(grand_total_value), "metric": metric},
        )

    def fetch_country_concentration(
        self, *, page_id: str, hs_codes: list[str], metric: str,
        start_period: str | None, end_period: str | None,
    ) -> RawDataset:
        """전체 국가 모집단으로 교역 집중도(HHI)를 결정적으로 계산한다.

        상위 5행 미리보기는 순위 표시에는 충분하지만 HHI의 분모·분자에는
        쓸 수 없다. 이 메서드는 같은 HS/기간/수입·수출 조건에서 국가별 합계를
        먼저 만든 뒤 그 **전체** 행으로 비중과 HHI를 계산한다.
        """

        spec = _RANKING_SPECS.get(page_id)
        if spec is None or metric not in spec["metrics"]:
            raise RawDataAccessError(f"'{page_id}'/{metric}은 국가 집중도 조회를 지원하지 않습니다.")
        if not hs_codes:
            raise RawDataAccessError("국가 집중도 조회에는 hs_codes가 최소 1개 필요합니다.")
        conditions = [f"HS_CD IN ({', '.join(_literal(c) for c in hs_codes)})"]
        direction_column = spec["direction_column"]
        if direction_column:
            conditions.append(f"{direction_column} = {_literal(spec['direction_values'][metric])}")
        period_column = spec["period_column"]
        period_precision = spec["period_precision"]
        if start_period:
            conditions.append(f"{period_column} >= {_literal(_coerce_period(start_period, period_precision, False))}")
        if end_period:
            conditions.append(f"{period_column} <= {_literal(_coerce_period(end_period, period_precision, True))}")
        where_clause = " AND ".join(conditions)
        table = spec["table"]
        country_column = spec["country_column"]
        metric_column = spec["metrics"][metric]
        try:
            frame = read_sql_pg(
                f"SELECT {country_column} AS country, SUM({metric_column}) AS total "
                f"FROM {KOMIS_SCHEMA}.{table} WHERE {where_clause} "
                f"GROUP BY {country_column} ORDER BY total DESC NULLS LAST"
            )
            period_frame = read_sql_pg(
                f"SELECT MIN({period_column}) AS period_start, MAX({period_column}) AS period_end "
                f"FROM {KOMIS_SCHEMA}.{table} WHERE {where_clause}"
            )
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("국가 집중도 조회에 실패했습니다.") from exc

        totals = [float(row[1]) for row in frame.itertuples(index=False, name=None) if row[1] is not None]
        grand_total = sum(totals)
        hhi = round(sum((value / grand_total * 100) ** 2 for value in totals), 2) if grand_total else None
        rows = [
            {"country": country, "total": _json_value(total),
             "share_pct": round(float(total) / grand_total * 100, 4) if total is not None and grand_total else None}
            for country, total in frame.itertuples(index=False, name=None)
        ]
        period_start = period_frame["period_start"].iloc[0] if not period_frame.empty else None
        period_end = period_frame["period_end"].iloc[0] if not period_frame.empty else None
        metric_label, unit = _RANKING_METRIC_LABELS[metric]
        return RawDataset(
            source_table=table, columns=["country", "total", "share_pct"],
            column_labels={
                "country": "국가", "total": f"{metric_label}합계({unit})",
                "share_pct": "비중(%, 전체 국가 합계 대비)",
            },
            row_count=len(rows), rows=rows,
            as_of=(f"{_format_period_value(period_start, period_precision)}~"
                   f"{_format_period_value(period_end, period_precision)}"
                   if period_start is not None and period_end is not None else None),
            unit=unit,
            metadata={
                "grand_total": _json_value(grand_total), "hhi": hhi,
                "formula": "Σ(국가별 비중[%]^2)", "metric": metric,
            },
        )

    def fetch_mineral_country_ranking(
        self, *, metric: str, mineral_code: str,
        start_period: str | None, end_period: str | None, top_n: int = 5,
    ) -> RawDataset:
        """매장량/생산량 국가별 상위 N(결정적 GROUP BY, 2026-09-18 신설,
        `fetch_country_ranking`(교역)과 같은 원칙). metric: "production"|
        "reserves".

        매장량(reserves)은 연도별 **스냅샷**이라 여러 연도를 SUM하면 안 된다
        (2024년 매장량 + 2025년 매장량을 더하는 건 의미가 없다 — 2025년 값이
        2024년을 대체한 것이다) — 그래서 reserves는 항상 연도 하나(요청
        기간의 끝, 없으면 그 광종의 최신 연도)만 본다. 생산량(production)은
        **흐름값**이라 명시 기간이 있으면 그 범위를 SUM해도 "그 기간 총
        생산량"으로 의미가 성립하지만, 기간이 없으면 똑같이 최신 연도
        하나로 좁힌다(과도한 다년 누적을 기본값으로 만들지 않는다 —
        "생산량 1위 국가"라고만 물으면 보통 최신 연도를 기대한다)."""

        spec = _RESERVES_PRODUCTION_RANKING_SPECS.get(metric)
        if spec is None:
            raise RawDataAccessError(f"'{metric}'은 매장량/생산량 랭킹을 지원하지 않습니다.")

        table = spec["table"]
        country_column = spec["country_column"]
        metric_column = spec["metric_column"]
        period_column = spec["period_column"]
        code = _literal(mineral_code)
        conditions = [f"mnrknd_unq_cd = {code}"]

        single_year_only = metric == "reserves" or not (start_period or end_period)
        if single_year_only:
            if start_period or end_period:
                target_year = _coerce_period(end_period or start_period, "year", True)
            else:
                latest = read_sql_pg(
                    f"SELECT MAX({period_column}) AS latest_year FROM {KOMIS_SCHEMA}.{table}"
                    f" WHERE mnrknd_unq_cd = {code}"
                )
                latest_year_value = latest["latest_year"].iloc[0] if not latest.empty else None
                if latest_year_value is None:
                    return RawDataset(
                        source_table=table, columns=["rank", "country", "total", "share_pct"],
                        column_labels={}, row_count=0, rows=[],
                    )
                target_year = str(int(latest_year_value))
            conditions.append(f"{period_column} = {_literal(target_year)}")
        else:
            if start_period:
                conditions.append(f"{period_column} >= {_literal(_coerce_period(start_period, 'year', False))}")
            if end_period:
                conditions.append(f"{period_column} <= {_literal(_coerce_period(end_period, 'year', True))}")

        where_clause = " AND ".join(f"t.{c}" for c in conditions)
        # 2026-09-18: NTN_ENG_CD는 "CN"·"AU" 같은 2자리 코드뿐이라(컬럼명은
        # eng_cd지만 실제 값은 국가명이 아니다) `ai_ntn_mst`(25개국 코드↔한글/
        # 영문명 마스터, 다른 테이블과 같은 원리)로 조인해 한글명을 붙인다.
        # LEFT JOIN이라 마스터에 없는 코드("OT"=기타 등)는 원본 코드가 그대로
        # 나온다(행을 잃지 않음).
        try:
            frame = read_sql_pg(
                f"SELECT COALESCE(m.ntn_nm_ko, t.{country_column}) AS country,"
                f" SUM(t.{metric_column}) AS total, COUNT(*) AS n"
                f" FROM {KOMIS_SCHEMA}.{table} t"
                f" LEFT JOIN {KOMIS_SCHEMA}.ai_ntn_mst m ON m.ntn_cd = t.{country_column}"
                f" WHERE {where_clause}"
                f" GROUP BY COALESCE(m.ntn_nm_ko, t.{country_column})"
                f" ORDER BY total DESC NULLS LAST LIMIT {int(top_n)}"
            )
            total_frame = read_sql_pg(
                f"SELECT SUM(t.{metric_column}) AS grand_total, "
                f"MIN(t.{period_column}) AS period_start, MAX(t.{period_column}) AS period_end "
                f"FROM {KOMIS_SCHEMA}.{table} t WHERE {where_clause}"
            )
        except Exception as exc:  # noqa: BLE001 — 원본과 같은 사용자 노출 메시지
            raise RawDataAccessError("매장량/생산량 국가별 랭킹 조회에 실패했습니다.") from exc

        grand_total_value = total_frame["grand_total"].iloc[0] if not total_frame.empty else None
        grand_total = float(grand_total_value) if grand_total_value is not None else 0.0
        period_start = total_frame["period_start"].iloc[0] if not total_frame.empty else None
        period_end = total_frame["period_end"].iloc[0] if not total_frame.empty else None

        rows: list[dict[str, Any]] = []
        for rank, record in enumerate(frame.itertuples(index=False, name=None), start=1):
            country, total, n = record
            total_value = float(total) if total is not None else 0.0
            share_pct = round(total_value / grand_total * 100, 2) if grand_total else None
            rows.append({
                "rank": rank, "country": country, "total": _json_value(total),
                "share_pct": share_pct, "record_count": int(n),
            })

        metric_label = spec["metric_label"]
        return RawDataset(
            source_table=table,
            columns=["rank", "country", "total", "share_pct", "record_count"],
            column_labels={
                "rank": "순위", "country": "국가", "total": f"{metric_label}합계(톤)",
                "share_pct": "비중(%, 같은 기간·조건의 전체 국가 합계 대비)", "record_count": "레코드건수",
            },
            row_count=len(rows), rows=rows,
            as_of=(f"{_format_period_value(period_start, 'year')}~"
                   f"{_format_period_value(period_end, 'year')}"
                   if period_start is not None and period_end is not None else None),
            unit="톤",
            metadata={"grand_total": _json_value(grand_total_value), "metric": metric},
        )

    def fetch_price_volatility_ranking(
        self, *, mineral_names: list[str] | None,
        start_period: str | None, end_period: str | None, top_n: int = 5,
    ) -> RawDataset:
        """광종 간 가격 변동률 비교/랭킹(결정적 window function, 2026-09-18
        신설 — RDB 결정적쿼리 후보리스트 2순위). `KO_MNRL_PRC`엔
        mnrknd_unq_cd가 없어(가격기준일련번호로만 연결) `ai_prc_mnrl_map`으로
        먼저 광종을 번역한다 — 한 광종이 여러 가격기준에 매핑되면
        (`komis_raw_lookup`과 같은 원칙) 가장 작은 일련번호 하나만 대표로
        쓴다. 기간 시작·끝 각각 최초/최근 1건(ROW_NUMBER 윈도우함수)을 뽑아
        변동률(%)을 코드로 계산한다(LLM이 스스로 계산하지 않는다 — 더
        정확하다). 정렬은 항상 변동폭의 **절댓값** 기준이다("변동성이 큰"은
        방향과 무관 — 오른 것도 내린 것도 변동성이다, 부호는 결과의
        pct_change 값으로 그대로 보여준다).

        `mineral_names`(한글명 리스트)가 있으면 그 광종들만 비교(예: "니켈과
        리튬 중"), 없으면 가격 매핑이 있는 전 광종을 대상으로 상위 N개
        랭킹("가격이 가장 많이 움직인 광종은?")."""

        # 명시 광종 비교는 2026-09-21부터 공통 실제 가용구간을 강제한다.
        # 아래의 기존 전체 광종 랭킹은 서로 공통 기간이 없는 광종까지 포함할 수
        # 있어 대표 질문(명시 광종 비교)과 계약이 다르므로 호환 경로로만 남긴다.
        if mineral_names:
            comparison_dataset = self.fetch_price_comparison(
                mineral_names=mineral_names,
                start_period=start_period,
                end_period=end_period,
            )
            candidates = sorted(
                comparison_dataset.metadata.get("comparison", []),
                key=lambda row: abs(row["pct_change"]) if row["pct_change"] is not None else -1,
                reverse=True,
            )[:max(1, int(top_n))]
            rows = [
                {
                    "rank": rank,
                    "mineral": row["mineral"],
                    "first_date": row["start_date"], "first_price": row["start_price"],
                    "last_date": row["end_date"], "last_price": row["end_price"],
                    "pct_change": row["pct_change"],
                }
                for rank, row in enumerate(candidates, start=1)
            ]
            return RawDataset(
                source_table="KO_MNRL_PRC",
                columns=["rank", "mineral", "first_date", "first_price", "last_date", "last_price", "pct_change"],
                column_labels={
                    "rank": "순위", "mineral": "광종", "first_date": "시작일자", "first_price": "시작가격",
                    "last_date": "종료일자", "last_price": "종료가격", "pct_change": "변동률(%)",
                },
                row_count=len(rows), rows=rows, as_of=comparison_dataset.as_of,
                metadata={**comparison_dataset.metadata, "ranking_order": "absolute_pct_change_desc"},
            )

        name_filter = ""
        if mineral_names:
            names_literal = ", ".join(_literal(n) for n in mineral_names)
            name_filter = f" AND ms.mnrl_nm_ko IN ({names_literal})"

        period_conditions = []
        if start_period:
            period_conditions.append(f"p.crtr_ymd >= {_literal(_coerce_period(start_period, 'day', False))}")
        if end_period:
            period_conditions.append(f"p.crtr_ymd <= {_literal(_coerce_period(end_period, 'day', True))}")
        period_clause = (" AND " + " AND ".join(period_conditions)) if period_conditions else ""

        try:
            frame = read_sql_pg(f"""
                WITH representative_serial AS (
                    SELECT pm.mnrknd_unq_cd AS mineral_code, ms.mnrl_nm_ko AS mineral,
                           MIN(pm.mnrl_prc_crtr_sn) AS serial
                    FROM {KOMIS_SCHEMA}.ai_prc_mnrl_map pm
                    JOIN {KOMIS_SCHEMA}.ai_mnrl_mst ms ON ms.mnrknd_unq_cd = pm.mnrknd_unq_cd
                    WHERE pm.use_yn = 'Y'{name_filter}
                    GROUP BY pm.mnrknd_unq_cd, ms.mnrl_nm_ko
                ),
                bounded AS (
                    SELECT rs.mineral, p.crtr_ymd, p.cmerc_prc,
                           ROW_NUMBER() OVER (PARTITION BY rs.mineral ORDER BY p.crtr_ymd ASC) AS rn_first,
                           ROW_NUMBER() OVER (PARTITION BY rs.mineral ORDER BY p.crtr_ymd DESC) AS rn_last
                    FROM representative_serial rs
                    JOIN {KOMIS_SCHEMA}.KO_MNRL_PRC p ON p.mnrl_prc_crtr_sn = rs.serial
                    WHERE p.status = 'Y' AND p.last_del_dt IS NULL{period_clause}
                )
                SELECT mineral,
                       MAX(CASE WHEN rn_first = 1 THEN crtr_ymd END) AS first_date,
                       MAX(CASE WHEN rn_first = 1 THEN cmerc_prc END) AS first_price,
                       MAX(CASE WHEN rn_last = 1 THEN crtr_ymd END) AS last_date,
                       MAX(CASE WHEN rn_last = 1 THEN cmerc_prc END) AS last_price
                FROM bounded
                WHERE rn_first = 1 OR rn_last = 1
                GROUP BY mineral
            """)
        except Exception as exc:  # noqa: BLE001 — 원본과 같은 사용자 노출 메시지
            raise RawDataAccessError("광종 간 가격 변동률 비교 조회에 실패했습니다.") from exc

        candidates: list[dict[str, Any]] = []
        for record in frame.itertuples(index=False, name=None):
            mineral, first_date, first_price, last_date, last_price = record
            if first_price is None or last_price is None or float(first_price) == 0.0:
                continue
            pct_change = round((float(last_price) - float(first_price)) / float(first_price) * 100, 2)
            candidates.append({
                "mineral": mineral, "first_date": str(first_date), "first_price": _json_value(first_price),
                "last_date": str(last_date), "last_price": _json_value(last_price), "pct_change": pct_change,
            })
        candidates.sort(key=lambda row: abs(row["pct_change"]), reverse=True)
        rows = candidates[: max(1, int(top_n))]
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        rows = [
            {k: row[k] for k in ("rank", "mineral", "first_date", "first_price", "last_date", "last_price", "pct_change")}
            for row in rows
        ]

        return RawDataset(
            source_table="KO_MNRL_PRC",
            columns=["rank", "mineral", "first_date", "first_price", "last_date", "last_price", "pct_change"],
            column_labels={
                "rank": "순위", "mineral": "광종", "first_date": "시작일자", "first_price": "시작가격",
                "last_date": "종료일자", "last_price": "종료가격", "pct_change": "변동률(%)",
            },
            row_count=len(rows), rows=rows,
        )

    #: 2026-09-18(RDB 결정적쿼리 후보리스트 2순위) — 광종 간 지표 비교/랭킹
    #: 대상 두 page_id. 값이 클수록 좋은/나쁜 방향이 지표마다 달라(수급동향
    #: 지표는 낮을수록 위험 쪽, 시장전망지표는 방향성이 문서에 명시 안 돼
    #: 있음) 정렬 방향(ascending)은 호출측(ROUTE_PROMPT 판단)이 고른다 —
    #: 여기서 임의로 "좋다/나쁘다"를 단정하지 않는다.
    _LATEST_INDICATOR_RANKING_SPECS: dict[str, dict[str, str]] = {
        "indicator_supply": {
            "table": "KO_SPDM_STBT_INDX", "value_column": "SPDM_STBT_INDX",
            "period_column": "CRTR_YMD", "value_label": "수급동향지표",
        },
        "indicator_market": {
            "table": "KO_MRKT_PRSPECT_IDCT", "value_column": "MRKT_PRSPECT_IDCT",
            "period_column": "CRTR_YMD", "value_label": "시장전망지표",
        },
    }

    def fetch_latest_indicator_ranking(
        self, *, page_id: str, ascending: bool, mineral_names: list[str] | None, top_n: int = 5,
    ) -> RawDataset:
        """지표(수급동향/시장전망) 최신값 기준 광종 간 랭킹(결정적, 2026-09-18
        신설). 각 광종의 가장 최근 1건(`DISTINCT ON`)만 골라 비교한다.
        `mineral_names`가 있으면 그 광종들만, 없으면 지표가 있는 전 광종
        대상 상위 N개."""

        spec = self._LATEST_INDICATOR_RANKING_SPECS.get(page_id)
        if spec is None:
            raise RawDataAccessError(f"'{page_id}'는 광종 간 지표 랭킹을 지원하지 않습니다.")
        table, value_column, period_column = spec["table"], spec["value_column"], spec["period_column"]

        name_filter = ""
        if mineral_names:
            names_literal = ", ".join(_literal(n) for n in mineral_names)
            name_filter = f" AND ms.mnrl_nm_ko IN ({names_literal})"

        order = "ASC" if ascending else "DESC"
        try:
            frame = read_sql_pg(f"""
                SELECT latest.mineral, latest.as_of, latest.value
                FROM (
                    SELECT DISTINCT ON (t.mnrknd_unq_cd)
                           ms.mnrl_nm_ko AS mineral, t.{period_column} AS as_of, t.{value_column} AS value
                    FROM {KOMIS_SCHEMA}.{table} t
                    JOIN {KOMIS_SCHEMA}.ai_mnrl_mst ms ON ms.mnrknd_unq_cd = t.mnrknd_unq_cd
                    WHERE t.{value_column} IS NOT NULL{name_filter}
                    ORDER BY t.mnrknd_unq_cd, t.{period_column} DESC
                ) latest
                ORDER BY latest.value {order} NULLS LAST
                LIMIT {int(top_n)}
            """)
        except Exception as exc:  # noqa: BLE001 — 원본과 같은 사용자 노출 메시지
            raise RawDataAccessError("광종 간 지표 랭킹 조회에 실패했습니다.") from exc

        rows = [
            {"rank": i + 1, "mineral": mineral, "as_of": str(as_of), "value": _json_value(value)}
            for i, (mineral, as_of, value) in enumerate(frame.itertuples(index=False, name=None))
        ]
        value_label = spec["value_label"]
        return RawDataset(
            source_table=table,
            columns=["rank", "mineral", "as_of", "value"],
            column_labels={
                "rank": "순위", "mineral": "광종", "as_of": "기준시점(광종별 최신)", "value": value_label,
            },
            row_count=len(rows), rows=rows,
        )

    def resolve_mineral_full(self, korean_name: str) -> tuple[str, str | None] | None:
        """한글 광종명(질문에 쓰인 표현 그대로, 예: "텅스텐")으로 `ai_mnrl_mst`
        에서 (mnrknd_unq_cd, prc_cat_cd)를 찾는다 — `resolve_mineral()`(코드→
        이름)의 반대 방향. `use_yn='Y'`인 것만(알파코드 CU/NI 등은 use_yn='N'
        이라 애초에 안 걸림, §모듈 docstring 2026-08-11 실측 참고). 못 찾으면
        None. `prc_cat_cd`는 가격 조회 시 어느 서브메뉴(price_base_metals 등
        4종)로 가야 하는지 고르는 데 쓰인다 — 없으면 None.

        2026-09-01: `komis_raw_lookup`을 발주 5광종 밖으로 열면서 필요해졌다
        (사용자 지시 — "5광종 제한은 이 프로젝트 일부 기능용이지 챗봇
        전체는 아니다"). 하드코딩된 광종명→코드 딕셔너리 대신 이 조회를
        쓰면 `ai_mnrl_mst`에 새 광종이 추가돼도 코드를 안 고쳐도 된다.

        같은 날 후속(main-agent 발견) — `ai_mnrl_mst.mnrl_nm_ko`는 정본
        명칭 하나만 담고 동의어 컬럼이 없어서(예: "동"만 있고 "구리"는
        없음), `_MINERAL_SYNONYMS`로 흔한 다른 표현 몇 개만 같이 시도한다.
        이건 "광종 자체를 하드코딩"하는 게 아니라 "같은 광종을 부르는
        다른 말"만 다루는 것이라, 새 광종 추가는 여전히 DB만 갱신하면
        된다(이 목록에 넣을 필요 없음)."""

        candidates = [korean_name]
        canonical = _MINERAL_SYNONYMS.get(korean_name)
        if canonical:
            candidates.append(canonical)
        literals = ", ".join(_literal(c) for c in candidates)
        frame = read_sql_pg(
            f"SELECT mnrknd_unq_cd, prc_cat_cd FROM {KOMIS_SCHEMA}.ai_mnrl_mst"
            f" WHERE mnrl_nm_ko IN ({literals}) AND use_yn = 'Y'"
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        prc_cat_cd = row["prc_cat_cd"]
        return str(row["mnrknd_unq_cd"]), (None if prc_cat_cd is None else str(prc_cat_cd))

    def resolve_mineral_meta(self, mineral_code: str) -> tuple[str, str | None] | None:
        """`ai_mnrl_mst`에서 (한글명, `ko_data_src_cd`)를 한 번의 조회로 찾는다.

        `resolve_mineral()`(코드→한글명)과 (코드→데이터출처코드) 조회가
        완전히 같은 테이블·같은 WHERE 조건(`mnrknd_unq_cd` = code)을 각각
        별도 `read_sql_pg()` 왕복으로 조회하던 걸 하나로 합친다 —
        `komis_raw_lookup`(rag_core/ragkit/_mcp_tools_common.py)이 근거
        라벨(한글명)과 더미데이터 경고(데이터출처코드)를 매 호출마다 함께
        필요로 하면서 mineral_code 하나당 DB 왕복이 최대 3~4회까지 쌓이던
        것의 일부를 줄인다(skeptic-code DEEP 감사 SC-001, 2026-09-01, 사용자
        승인). `resolve_mineral()`은 `report_gen/app/analysis/data_sources/
        extra.py`에서 별도로 쓰이고 있어 그대로 남겨뒀다(이 메서드가 그걸
        대체하지 않는다)."""

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT mnrl_nm_ko, ko_data_src_cd FROM {KOMIS_SCHEMA}.ai_mnrl_mst"
            f" WHERE mnrknd_unq_cd = {code}"
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        data_source = row["ko_data_src_cd"]
        return str(row["mnrl_nm_ko"]), (None if data_source is None else str(data_source))

    def resolve_period_bounds(
        self,
        page_id: str,
        *,
        mineral_code: str | None = None,
        hs_code: str | None = None,
        price_criterion_serial: int | None = None,
        index_type_code: str | None = None,
    ) -> tuple[str, str, Period] | None:
        """`page_id`가 실제로 조회 가능한 기간(MIN~MAX `period_column`)을 돌려준다
        — (시작, 끝, 정밀도) 또는 데이터가 아예 없으면 None. 2026-09-03,
        발주처 문서(대화형검색시스템 예상질문 고도화.pdf) ②-1/②-3/④-나가
        요구하는 "조회 가능 기간은 YYYY.MM.DD~YYYY.MM.DD입니다" 안내에 쓴다
        — `komis_raw_lookup`이 0건을 받았을 때 호출측(_mcp_tools_common.py)이
        이 메서드로 실제 범위를 채운다(하드코딩 문구 금지 원칙 유지).

        필터 인자가 주어지면(예: 특정 광종의 가격기준일련번호) 그 필터가
        걸린 상태의 범위를, 주어지지 않으면 페이지 테이블 전체 범위를
        돌려준다 — `_fetch_dataset`과 같은 `_SAFE_VALUE`/`_literal()` 화이트리스트
        경로만 쓴다(자유형 SQL 금지 원칙 동일). `_PAGE_DATASETS[page_id]`의
        첫 번째 데이터셋만 본다(map_mineral처럼 2개인 page도 첫 번째로 충분 —
        이 메서드는 정밀 데이터가 아니라 안내 문구용 범위 참고치라서다)."""

        spec = _PAGE_DATASETS[page_id][0]
        conditions = list(spec.fixed_conditions)
        candidate_filters: dict[str, str | int | None] = {
            "mineral_code": mineral_code,
            "hs_code": hs_code,
            "price_criterion_serial": price_criterion_serial,
            "index_type_code": index_type_code,
        }
        for filter_name, column in spec.filter_columns.items():
            value = candidate_filters.get(filter_name)
            if value is not None:
                conditions.append(f"{column} = {_literal(value)}")
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            f"SELECT MIN({spec.period_column}) AS mn, MAX({spec.period_column}) AS mx "
            f"FROM {KOMIS_SCHEMA}.{spec.table}{where_clause}"
        )
        frame = read_sql_pg(query)
        if frame.empty or frame.iloc[0]["mn"] is None:
            return None
        row = frame.iloc[0]
        return str(row["mn"]), str(row["mx"]), spec.period_precision


def _json_value(value: Any) -> Any:
    """DB 값을 JSON 직렬화 가능한 스칼라로 정규화(원본 `_json_value` 이식).

    원본은 psycopg가 돌려주는 Decimal/date를 다뤘다. 여기서는 pandas를 거치므로
    NaN(결측)·numpy 스칼라가 추가로 들어온다 — NaN은 None으로 접는다(원본에서
    `_finite_float`가 걸러주던 자리인데, 그 전에 pydantic JSON 직렬화가 깨진다).
    """

    import datetime as _dt
    import decimal as _decimal
    import math

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, _decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    item = getattr(value, "item", None)  # numpy 스칼라 → 파이썬 스칼라
    if callable(item):
        try:
            value = item()
        except (ValueError, TypeError):
            return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float)):
        return value
    return str(value)
