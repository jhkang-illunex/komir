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
   `resources/komis_data_schema.yml`에서 로드·검증한 테이블·컬럼명과 검증된
   리터럴만 조합한다.

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
from datetime import datetime
import math
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, get_args

import yaml

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import read_sql_pg
from .trade_indicators import RcaInputs, TiiInputs, calculate_rca, calculate_tii

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
    hs_codes: list[str] | None = None
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

    @model_validator(mode="after")
    def validate_hs_codes(self) -> "AnalysisPreviewRequest":
        if self.hs_codes is not None:
            if not self.hs_codes or any(not re.fullmatch(r"[A-Za-z0-9_]+", code) for code in self.hs_codes):
                raise ValueError("hs_codes must contain at least one safe code")
            if self.hs_code is not None:
                raise ValueError("hs_code and hs_codes are mutually exclusive")
        return self

    def requested_filters(self) -> dict[str, str | int]:
        """호출자가 명시적으로 준 필터만 돌려준다."""

        filters = {
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
        if self.hs_codes:
            filters["hs_code"] = "__multiple__"
        return filters


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
    fixed_conditions: tuple[Mapping[str, str | None], ...] = ()


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILTER_NAMES = {"mineral_code", "hs_code", "index_type_code", "price_criterion_serial"}
_CATALOG_PATH = Path(__file__).with_name("resources") / "komis_data_schema.yml"


def _identifier(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid SQL identifier in {_CATALOG_PATH}: {context}={value!r}")
    return value


def _load_data_schema_catalog() -> tuple[
    str, dict[str, tuple[_DatasetSpec, ...]], dict[str, dict[str, Any]],
    dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, tuple[str, str]],
]:
    """SQL 식별자 카탈로그를 읽고, 안전한 정적 스펙인지 시작 시 검증한다."""
    raw = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError(f"invalid KOMIS data schema catalog: {_CATALOG_PATH}")
    schema = _identifier(raw.get("schema"), context="schema")

    disabled_raw = raw.get("disabled_pages", [])
    if not isinstance(disabled_raw, list) or not all(isinstance(page_id, str) for page_id in disabled_raw):
        raise ValueError(f"invalid disabled_pages in KOMIS catalog: {_CATALOG_PATH}")
    disabled_pages = set(disabled_raw)
    expected_pages = set(get_args(AnalysisPreviewPageId))
    if disabled_pages - expected_pages:
        raise ValueError(
            f"KOMIS catalog disabled page_id mismatch: {sorted(disabled_pages - expected_pages)}"
        )

    raw_pages = raw.get("datasets")
    active_pages = expected_pages - disabled_pages
    if not isinstance(raw_pages, dict) or set(raw_pages) != active_pages:
        raise ValueError(
            f"KOMIS catalog page_id mismatch: expected={sorted(active_pages)}, "
            f"actual={sorted(raw_pages) if isinstance(raw_pages, dict) else type(raw_pages).__name__}"
        )

    pages: dict[str, tuple[_DatasetSpec, ...]] = {}
    for page_id, entries in raw_pages.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"KOMIS catalog dataset must be a non-empty list: {page_id}")
        specs: list[_DatasetSpec] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"invalid dataset definition: {page_id}")
            table = _identifier(entry.get("table"), context=f"{page_id}.table")
            columns_raw = entry.get("columns")
            if not isinstance(columns_raw, list) or not columns_raw:
                raise ValueError(f"dataset columns must be a non-empty list: {page_id}.{table}")
            columns = tuple(_identifier(col, context=f"{page_id}.{table}.columns") for col in columns_raw)
            period_column = _identifier(entry.get("period_column"), context=f"{page_id}.{table}.period_column")
            if period_column not in columns:
                raise ValueError(f"period column missing from selected columns: {page_id}.{table}.{period_column}")
            precision = entry.get("period_precision")
            if precision not in {"day", "month", "year"}:
                raise ValueError(f"invalid period precision: {page_id}.{table}={precision!r}")
            filters = entry.get("filter_columns", {})
            if not isinstance(filters, dict) or set(filters) - _FILTER_NAMES:
                raise ValueError(f"invalid filters in KOMIS catalog: {page_id}.{table}")
            filter_columns = {
                str(name): _identifier(column, context=f"{page_id}.{table}.filter_columns.{name}")
                for name, column in filters.items()
            }
            if set(filter_columns.values()) - set(columns):
                raise ValueError(f"filter column missing from selected columns: {page_id}.{table}")
            fixed_raw = entry.get("fixed_conditions", [])
            fixed: list[dict[str, str | None]] = []
            if not isinstance(fixed_raw, list):
                raise ValueError(f"invalid fixed conditions: {page_id}.{table}")
            for condition in fixed_raw:
                if not isinstance(condition, dict) or condition.get("operator") not in {"=", "IS NULL"}:
                    raise ValueError(f"unsupported fixed condition: {page_id}.{table}")
                column = _identifier(condition.get("column"), context=f"{page_id}.{table}.condition.column")
                operator = str(condition["operator"])
                value = condition.get("value")
                if operator == "=" and not isinstance(value, str):
                    raise ValueError(f"fixed equality requires a string value: {page_id}.{table}.{column}")
                if operator == "=" and not re.fullmatch(r"[A-Za-z0-9_가-힣]{1,32}", value):
                    raise ValueError(f"unsafe fixed condition value: {page_id}.{table}.{column}")
                if operator == "IS NULL" and value is not None:
                    raise ValueError(f"IS NULL condition cannot set a value: {page_id}.{table}.{column}")
                fixed.append({"column": column, "operator": operator, "value": value})
            specs.append(_DatasetSpec(
                table=table, columns=columns, period_column=period_column,
                period_precision=precision, filter_columns=filter_columns,
                fixed_conditions=tuple(fixed),
            ))
        pages[str(page_id)] = tuple(specs)

    columns_by_table: dict[str, set[str]] = {}
    for specs in pages.values():
        for spec in specs:
            columns_by_table.setdefault(spec.table, set()).update(spec.columns)

    rankings: dict[str, dict[str, Any]] = {}
    for page_id, item in (raw.get("rankings") or {}).items():
        if page_id not in pages or not isinstance(item, dict):
            raise ValueError(f"invalid ranking page in KOMIS catalog: {page_id}")
        table = _identifier(item.get("table"), context=f"rankings.{page_id}.table")
        country = _identifier(item.get("country_column"), context=f"rankings.{page_id}.country_column")
        period = _identifier(item.get("period_column"), context=f"rankings.{page_id}.period_column")
        metrics = item.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError(f"ranking metrics must be a non-empty mapping: {page_id}")
        metrics = {str(k): _identifier(v, context=f"rankings.{page_id}.metrics.{k}") for k, v in metrics.items()}
        direction_column = item.get("direction_column")
        if direction_column is not None:
            direction_column = _identifier(direction_column, context=f"rankings.{page_id}.direction_column")
        direction_values = item.get("direction_values", {})
        if set(direction_values) - set(metrics):
            raise ValueError(f"ranking direction values do not match metrics: {page_id}")
        if item.get("period_precision") not in {"day", "month", "year"}:
            raise ValueError(f"invalid ranking period precision: {page_id}")
        required_columns = {country, period, *metrics.values()}
        if direction_column:
            required_columns.add(direction_column)
        if table not in columns_by_table or required_columns - columns_by_table[table]:
            raise ValueError(f"ranking columns are not declared in datasets: {page_id}.{table}")
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_가-힣]{1,32}", value)
               for value in direction_values.values()):
            raise ValueError(f"unsafe ranking direction value: {page_id}")
        rankings[str(page_id)] = {
            "table": table, "country_column": country, "period_column": period,
            "period_precision": item.get("period_precision"), "metrics": metrics,
            "direction_column": direction_column, "direction_values": dict(direction_values),
        }

    reserves: dict[str, dict[str, str]] = {}
    for metric, item in (raw.get("reserves_production_rankings") or {}).items():
        if not isinstance(item, dict):
            raise ValueError(f"invalid reserves/production ranking: {metric}")
        spec = {
            key: _identifier(item[key], context=f"reserves_production_rankings.{metric}.{key}")
            for key in ("table", "country_column", "metric_column", "period_column")
        } | {"metric_label": str(item.get("metric_label", metric))}
        if spec["table"] not in columns_by_table or {
            spec["country_column"], spec["metric_column"], spec["period_column"]
        } - columns_by_table[spec["table"]]:
            raise ValueError(f"reserve/production columns are not declared in datasets: {metric}")
        reserves[str(metric)] = spec

    latest_indicators: dict[str, dict[str, str]] = {}
    for page_id, item in (raw.get("latest_indicator_rankings") or {}).items():
        if page_id not in pages or not isinstance(item, dict):
            raise ValueError(f"invalid latest indicator ranking: {page_id}")
        spec = {
            key: _identifier(item[key], context=f"latest_indicator_rankings.{page_id}.{key}")
            for key in ("table", "value_column", "period_column")
        } | {"value_label": str(item.get("value_label", page_id))}
        if spec["table"] not in columns_by_table or {
            spec["value_column"], spec["period_column"], "MNRKND_UNQ_CD"
        } - columns_by_table[spec["table"]]:
            raise ValueError(f"latest indicator columns are not declared in datasets: {page_id}")
        latest_indicators[str(page_id)] = spec

    labels_raw = raw.get("ranking_metric_labels") or {}
    labels: dict[str, tuple[str, str]] = {}
    for metric, item in labels_raw.items():
        if not isinstance(item, dict) or not item.get("label") or not item.get("unit"):
            raise ValueError(f"invalid ranking metric label: {metric}")
        labels[str(metric)] = (str(item["label"]), str(item["unit"]))
    if set(labels) != {metric for ranking in rankings.values() for metric in ranking["metrics"]}:
        raise ValueError("ranking labels and ranking metrics do not match")
    return schema, pages, rankings, reserves, latest_indicators, labels


(
    KOMIS_SCHEMA, _PAGE_DATASETS, _RANKING_SPECS,
    _RESERVES_PRODUCTION_RANKING_SPECS, _LATEST_INDICATOR_RANKING_SPECS,
    _RANKING_METRIC_LABELS,
) = _load_data_schema_catalog()

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


def _parse_trade_indicator_day(value: str, *, field: str) -> str:
    """특정국 의존도 range의 일 경계를 엄격한 실제 날짜로 검증한다."""
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").strftime("%Y%m%d")
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise RawDataAccessError(f"무역지표 {field}일은 YYYY-MM-DD 또는 YYYYMMDD 실제 날짜여야 합니다.") from exc


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

    def __init__(
        self,
        global_trade_indicator_provider: Callable[..., RcaInputs | TiiInputs] | None = None,
    ):
        """RCA/TII 세계 분모 provider의 명시적 주입 지점.

        기본 리포지토리는 현재 연결된 완전 세계 원천이 없으므로 provider 없이
        생성된다. 이 seam은 원천 계약이 검증된 뒤에만 주입하며, KO_UN_CMMRC
        부분 표본으로 자동 대체하지 않는다.
        """
        self._global_trade_indicator_provider = global_trade_indicator_provider

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

        conditions = []
        for fixed in spec.fixed_conditions:
            column, operator, value = fixed["column"], fixed["operator"], fixed["value"]
            if operator == "IS NULL":
                conditions.append(f"{column} IS NULL")
            elif operator == "=":
                conditions.append(f"{column} = {_literal(str(value))}")
            else:  # loader에서도 차단하지만, 모델이 직접 생성되는 경로도 fail closed
                raise RawDataAccessError(f"허용되지 않는 고정 조건 연산자: {operator!r}")
        requested_filters = request.requested_filters()
        for filter_name, column in spec.filter_columns.items():
            if filter_name not in requested_filters:
                continue
            if filter_name == "hs_code" and request.hs_codes:
                values = ", ".join(_literal(code) for code in request.hs_codes)
                conditions.append(f"{column} IN ({values})")
            else:
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
    # 기준일련번호)·`ai_hs_mtrl_flow`(광종→HS코드)은 KOMIS가 이 3개 신규 엔드포인트를
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
        """`ai_hs_mtrl_flow`에서 광종의 HS코드(들)를 찾는다(오름차순).

        품목·연도·수출입 흐름별로 같은 HS코드가 여러 행에 있을 수 있으므로
        ``DISTINCT hs_cd``만 반환한다. 호출자는 반환된 전체 목록을 원천 조회의
        ``IN`` 조건에 전달해야 하며 첫 코드만 선택해서는 안 된다.
        """

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT DISTINCT hs_cd FROM {KOMIS_SCHEMA}.ai_hs_mtrl_flow"
            f" WHERE mnrknd_unq_cd = {code} AND use_yn = 'Y'"
            f" ORDER BY hs_cd"
        )
        return list(dict.fromkeys(str(value) for value in frame["hs_cd"]))

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

    def fetch_price_time_aggregate(
        self, *, mineral_code: str, operation: Literal["monthly_streak", "yearly_average"],
    ) -> RawDataset:
        """대표 가격기준 하나를 DB에서 월/연 단위로 집계해 원 일별 행을 내보내지 않는다."""
        serials = self.resolve_price_criterion_serials(mineral_code)
        if not serials:
            return RawDataset(source_table="KO_MNRL_PRC", columns=[], rows=[], row_count=0)
        serial = serials[0]
        criterion = self.resolve_price_criterion_metadata(serial)
        criterion_name, currency, weight = criterion or (None, None, None)
        if operation == "monthly_streak":
            date_expression = "SUBSTRING(p.crtr_ymd, 1, 6) || '01'"
            extra = "COUNT(*) AS observation_count"
        else:
            date_expression = "SUBSTRING(p.crtr_ymd, 1, 4) || '0101'"
            extra = "COUNT(DISTINCT SUBSTRING(p.crtr_ymd, 1, 6)) AS observation_months"
        try:
            frame = read_sql_pg(f"""
                SELECT {date_expression} AS price_date, AVG(p.cmerc_prc) AS price, {extra}
                FROM {KOMIS_SCHEMA}.KO_MNRL_PRC p
                WHERE p.mnrl_prc_crtr_sn = {_literal(serial)}
                  AND p.status = 'Y' AND p.last_del_dt IS NULL AND p.cmerc_prc IS NOT NULL
                GROUP BY {date_expression}
                ORDER BY {date_expression}
            """)
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("가격 월·연 집계 조회에 실패했습니다.") from exc
        columns = ["price_date", "price", "observation_count" if operation == "monthly_streak" else "observation_months"]
        rows = [
            {key: _json_value(value) for key, value in record.items()}
            for record in frame.to_dict("records")
        ]
        as_of = (f"{rows[0]['price_date']}~{rows[-1]['price_date']}") if rows else None
        return RawDataset(
            source_table="KO_MNRL_PRC", columns=columns, row_count=len(rows), rows=rows, as_of=as_of,
            column_labels={"price_date": "기준일자", "price": "평균가격", columns[-1]: "관측수"},
            unit="; ".join(part for part in (
                f"가격기준={criterion_name}" if criterion_name else None,
                f"통화코드={currency}" if currency else None,
                f"중량단위코드={weight}" if weight else None,
            ) if part) or None,
            metadata={"price_criterion_serial": serial, "operation": operation},
        )

    def fetch_strategic_price_overview(
        self, *, members: list[Mapping[str, str]], as_of_date: str,
    ) -> RawDataset:
        """YAML로 확정된 전략광종별 최신 가격 행을 기준·단위와 함께 반환한다.

        광종마다 가격 기준과 관측일이 달라 공통 기간·평균·순위는 계산하지 않는다.
        ``members``는 RAG 계약이 검증한 label/price_mineral/group만 받는다.
        """
        if not members:
            raise RawDataAccessError("전략광종 가격 현황에는 조회 대상이 필요합니다.")
        values: list[str] = []
        for member in members:
            try:
                label = str(member["label"])
                price_mineral = str(member["price_mineral"])
                group = str(member["group"])
            except (KeyError, TypeError) as exc:
                raise RawDataAccessError("전략광종 가격 대상 설정이 올바르지 않습니다.") from exc
            values.append(f"({_literal(label)}, {_literal(price_mineral)}, {_literal(group)})")
        # 활성 마스터의 모든 활성 가격기준별로 오늘 이하 최신 관측 행 하나만
        # LATERAL로 읽는다. 여러 기준 중 임의 serial 하나를 대표값으로 고르지
        # 않으며, 전체 이력·공통 기간·평균도 만들지 않는다.
        try:
            frame = read_sql_pg(f"""
                WITH requested(label, price_mineral, group_label) AS (
                    VALUES {', '.join(values)}
                ), criteria AS (
                    SELECT r.label, r.price_mineral, r.group_label,
                           pm.mnrl_prc_crtr_sn AS serial, m.prc_cat_cd, c.prc_crtr,
                           c.prc_unit_cd, c.weig_unit_cd
                    FROM requested r
                    JOIN {KOMIS_SCHEMA}.ai_mnrl_mst m ON m.mnrl_nm_ko = r.price_mineral AND m.use_yn = 'Y'
                    JOIN {KOMIS_SCHEMA}.ai_prc_mnrl_map pm
                      ON pm.mnrknd_unq_cd = m.mnrknd_unq_cd AND pm.use_yn = 'Y'
                    JOIN {KOMIS_SCHEMA}.KO_MNRL_PRC_CRTR c ON c.mnrl_prc_crtr_sn = pm.mnrl_prc_crtr_sn
                )
                SELECT r.label, r.price_mineral, r.group_label,
                       s.serial, s.prc_cat_cd, s.prc_crtr AS price_criterion,
                       s.prc_unit_cd AS price_currency_code, s.weig_unit_cd AS weight_unit_code,
                       p.crtr_ymd AS price_date, p.cmerc_prc AS price
                FROM requested r
                LEFT JOIN criteria s ON s.label = r.label AND s.price_mineral = r.price_mineral
                                     AND s.group_label = r.group_label
                LEFT JOIN LATERAL (
                    SELECT crtr_ymd, cmerc_prc
                    FROM {KOMIS_SCHEMA}.KO_MNRL_PRC
                    WHERE mnrl_prc_crtr_sn = s.serial AND status = 'Y' AND last_del_dt IS NULL
                      AND cmerc_prc IS NOT NULL AND crtr_ymd <= {_literal(as_of_date)}
                    ORDER BY crtr_ymd DESC LIMIT 1
                ) p ON TRUE
                ORDER BY r.group_label, r.label
            """)
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("전략광종 가격 현황 원천 조회에 실패했습니다.") from exc
        rows: list[dict[str, Any]] = []
        for record in frame.to_dict("records"):
            serial = record.get("serial")
            price_date = record.get("price_date")
            serial_missing = serial is None or str(serial).strip().casefold() in {"", "nan", "none"}
            date_missing = price_date is None or str(price_date).strip().casefold() in {"", "nan", "none"}
            status = "available" if not serial_missing and not date_missing else (
                "price_criterion_unmapped" if serial_missing else "no_observation"
            )
            rows.append({
                "strategic_group": record["group_label"], "mineral": record["label"],
                "price_mineral": record["price_mineral"], "price_date": _format_period_value(price_date, "day") if price_date is not None else None,
                "price": _json_value(record.get("price")), "price_criterion_serial": None if serial_missing else _json_value(serial),
                "price_criterion": record.get("price_criterion"),
                "price_currency_code": record.get("price_currency_code"),
                "weight_unit_code": record.get("weight_unit_code"),
                "source_menu": {"HP001": "price_base_metals", "HP002": "price_minor_metals",
                                "HP003": "price_iron_energy", "HP004": "price_other"}.get(record.get("prc_cat_cd")),
                "row_status": status,
            })
        available = [row for row in rows if row["row_status"] == "available"]
        member_order = {(str(member["group"]), str(member["label"])): index
                        for index, member in enumerate(members)}
        rows.sort(key=lambda row: (member_order.get((row["strategic_group"], row["mineral"]), len(members)),
                                   str(row.get("price_criterion") or "")))
        return RawDataset(
            source_table="KO_MNRL_PRC",
            columns=["strategic_group", "mineral", "price_date", "price", "price_criterion",
                     "price_currency_code", "weight_unit_code", "source_menu", "row_status"],
            column_labels={
                "strategic_group": "전략광종 그룹", "mineral": "광종", "price_date": "광종별 최신 관측일",
                "price": "통상가격", "price_criterion": "가격기준", "price_currency_code": "통화코드",
                "weight_unit_code": "중량단위코드", "source_menu": "KOMIS 가격 메뉴", "row_status": "조회 상태",
            },
            row_count=len(rows), rows=rows,
            # as_of는 광종별 실제 관측일 하나가 아니므로 비운다. 조회 상한과
            # 각 행의 관측일은 metadata/표에서 별도로 보존한다.
            as_of=None,
            unit="행별 가격기준·통화·중량단위 참조(광종 간 절대가격 비교 금지)",
            metadata={
                "requested_count": len(members), "available_count": len(available),
                "missing_minerals": [row["mineral"] for row in rows if row["row_status"] != "available"],
                "query_upper_bound": as_of_date,
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

        # 관세청 매핑은 HSK 10자리지만 UN Comtrade 원천은 HS 6자리다. 글로벌
        # 수출입국 순위에서 그대로 비교하면 실제 UN 행이 있어도 0건이 된다.
        # 반대로 한국 관세청 경로는 10자리 기준을 그대로 유지한다.
        if page_id == "map_global":
            hs_codes = sorted({str(code)[:6] for code in hs_codes if len(str(code)) >= 6})
        if not hs_codes:
            raise RawDataAccessError("UN 무역 국가 랭킹 조회에 사용할 HS 6자리 코드가 없습니다.")
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
        observed_period = (
            f"{_format_period_value(period_start, period_precision)}~"
            f"{_format_period_value(period_end, period_precision)}"
            if period_start is not None and period_end is not None else "조회 기간 미확인"
        )
        return RawDataset(
            source_table=table,
            columns=["rank", "country", "total", "share_pct", "transaction_count"],
            column_labels={
                "rank": "순위", "country": "국가", "total": f"{metric_label}합계({unit})",
                "share_pct": f"{metric_label} 비중(%, {observed_period} 조회 품목 전체 국가 합계 대비)",
                "transaction_count": "거래건수",
            },
            row_count=len(rows), rows=rows,
            as_of=observed_period if period_start is not None and period_end is not None else None,
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

    def fetch_trade_indicator(
        self, *, trade_metric: str, hs_codes: list[str], reporter_country: str,
        calendar_year: int | None = None, start_period: str | None = None,
        end_period: str | None = None, partner_country: str | None = None,
        flow: str | None = None,
        denominator_scope: Literal["reporter_product_trade"] | None = None,
    ) -> RawDataset:
        """관세청 원천으로 계산 가능한 연간 무역지표를 결정적으로 산출한다.

        현재 ``KO_CSTM_CMMRC``는 한국 기준 교역만 제공한다. RCA/TII의 세계
        전체 분모는 ``KO_UN_CMMRC``가 9개 HS의 부분 표본이라 산출하지 않는다.
        부분 표본을 세계 총교역으로 오인해 수치를 만드는 일을 막기 위한 경계다.
        """
        if reporter_country.casefold() not in {"한국", "korea", "south korea", "republic of korea"}:
            raise RawDataAccessError("현재 무역지표 원천은 한국 기준 교역만 제공합니다.")
        has_calendar_year = calendar_year is not None
        has_range = start_period is not None or end_period is not None
        if has_calendar_year and has_range:
            raise RawDataAccessError("무역지표 기간은 연도 또는 시작·종료일 범위 중 하나만 지정할 수 있습니다.")
        if not has_calendar_year and (start_period is None or end_period is None):
            raise RawDataAccessError("무역지표 기간에는 연도 또는 시작·종료일 범위가 필요합니다.")
        if has_calendar_year:
            assert calendar_year is not None
            start, end = f"{calendar_year}0101", f"{calendar_year}1231"
        else:
            start = _parse_trade_indicator_day(start_period or "", field="시작")
            end = _parse_trade_indicator_day(end_period or "", field="종료")
            if start > end:
                raise RawDataAccessError("무역지표 시작일은 종료일보다 늦을 수 없습니다.")
        if trade_metric != "country_dependency" and not has_calendar_year:
            raise RawDataAccessError("최근 기간 범위 조회는 현재 특정국 의존도에만 지원합니다.")
        if trade_metric in {"rca", "tii"}:
            # 현재 구현은 아래 입력 어댑터가 명시적으로 막는다. 세계 교역 원천이
            # 준비되면 해당 메서드만 구현하면 되며 MCP·HITL·계산식은 바뀌지 않는다.
            inputs = self.fetch_global_trade_indicator_inputs(
                trade_metric=trade_metric, hs_codes=hs_codes, reporter_country=reporter_country,
                partner_country=partner_country, calendar_year=calendar_year,
            )
            if trade_metric == "rca":
                assert isinstance(inputs, RcaInputs)
                value = calculate_rca(inputs)
                rows = [{"year": calendar_year, "rca": value,
                         "reporter_product_exports": inputs.reporter_product_exports,
                         "reporter_total_exports": inputs.reporter_total_exports,
                         "world_product_exports": inputs.world_product_exports,
                         "world_total_exports": inputs.world_total_exports}]
                labels = {"year": "연도", "rca": "현시비교우위지수(RCA)",
                          "reporter_product_exports": "기준국 품목 수출액", "reporter_total_exports": "기준국 총수출액",
                          "world_product_exports": "세계 품목 수출액", "world_total_exports": "세계 총수출액"}
                formula = "(기준국 품목 수출액/기준국 총수출액)/(세계 품목 수출액/세계 총수출액)"
            else:
                assert isinstance(inputs, TiiInputs)
                value = calculate_tii(inputs)
                rows = [{"year": calendar_year, "tii": value,
                         "reporter_partner_exports": inputs.reporter_partner_exports,
                         "reporter_total_exports": inputs.reporter_total_exports,
                         "world_partner_imports": inputs.world_partner_imports,
                         "world_total_imports": inputs.world_total_imports}]
                labels = {"year": "연도", "tii": "무역결합도지수(TII)",
                          "reporter_partner_exports": "기준국의 상대국 수출액", "reporter_total_exports": "기준국 총수출액",
                          "world_partner_imports": "세계의 상대국 수입액", "world_total_imports": "세계 총수입액"}
                formula = "(기준국의 상대국 수출액/기준국 총수출액)/(세계의 상대국 수입액/세계 총수입액)"
            return RawDataset(source_table="GLOBAL_TRADE_DENOMINATOR", columns=list(labels), column_labels=labels,
                              row_count=1, rows=rows, as_of=str(calendar_year), unit="무차원",
                              metadata={"trade_metric": trade_metric, "formula": formula,
                                        "reporter_country": reporter_country, "hs_codes": hs_codes})
        if not hs_codes:
            raise RawDataAccessError("무역지표 계산에 필요한 HS 코드가 없습니다.")
        if trade_metric in {"trade_growth", "country_dependency"} and flow not in {"import", "export"}:
            raise RawDataAccessError("수출입증감률·특정국 의존도는 수입 또는 수출 구분이 필요합니다.")
        if trade_metric == "country_dependency" and not partner_country:
            raise RawDataAccessError("특정국 의존도는 상대국이 필요합니다.")
        hs_clause = ", ".join(_literal(code) for code in hs_codes)
        base = f"HS_CD IN ({hs_clause}) AND CRTR_YMD >= {_literal(start)} AND CRTR_YMD <= {_literal(end)}"
        try:
            if trade_metric == "tsi":
                frame = read_sql_pg(
                    f"SELECT MIN(CRTR_YMD) AS available_start, MAX(CRTR_YMD) AS available_end, "
                    "COUNT(*) AS observation_count, "
                    f"SUM(INCM_AMT) AS import_amount, SUM(EXP_AMT) AS export_amount "
                    f"FROM {KOMIS_SCHEMA}.KO_CSTM_CMMRC WHERE {base}"
                )
                row = frame.iloc[0].to_dict() if not frame.empty else {}
                imports, exports = float(row.get("import_amount") or 0), float(row.get("export_amount") or 0)
                denominator = exports + imports
                value = round((exports - imports) / denominator, 6) if denominator else None
                rows = [{"year": calendar_year, "export_amount": exports, "import_amount": imports,
                         "tsi": value}]
                labels = {"year": "연도", "export_amount": "수출금액(USD)",
                          "import_amount": "수입금액(USD)", "tsi": "무역특화지수(TSI)"}
                formula = "(수출금액-수입금액)/(수출금액+수입금액)"
                unit = "무차원"
            elif trade_metric == "trade_growth":
                column = "INCM_AMT" if flow == "import" else "EXP_AMT"
                prior_start, prior_end = f"{calendar_year - 1}0101", f"{calendar_year - 1}1231"
                frame = read_sql_pg(
                    f"SELECT CASE WHEN CRTR_YMD >= {_literal(start)} THEN 'current' ELSE 'prior' END AS period, "
                    f"MIN(CRTR_YMD) AS available_start, MAX(CRTR_YMD) AS available_end, COUNT(*) AS observation_count, "
                    f"SUM({column}) AS amount FROM {KOMIS_SCHEMA}.KO_CSTM_CMMRC "
                    f"WHERE HS_CD IN ({hs_clause}) AND CRTR_YMD >= {_literal(prior_start)} "
                    f"AND CRTR_YMD <= {_literal(end)} GROUP BY 1"
                )
                values = {row.period: float(row.amount or 0) for row in frame.itertuples(index=False)}
                current, prior = values.get("current", 0), values.get("prior", 0)
                value = round((current - prior) / prior * 100, 4) if prior else None
                rows = [{"year": calendar_year, "flow": flow, "current_amount": current,
                         "prior_amount": prior, "growth_pct": value}]
                labels = {"year": "연도", "flow": "교역방향", "current_amount": "당해금액(USD)",
                          "prior_amount": "전년금액(USD)", "growth_pct": "수출입증감률(%)"}
                formula = "(당해금액-전년금액)/전년금액×100"
                unit = "%"
            elif trade_metric == "country_dependency":
                if denominator_scope not in {None, "reporter_product_trade"}:
                    raise RawDataAccessError("지원하지 않는 특정국 의존도 분모 범위입니다.")
                column = "INCM_AMT" if flow == "import" else "EXP_AMT"
                partner = _literal(partner_country or "")
                frame = read_sql_pg(
                    f"SELECT MIN(CRTR_YMD) AS available_start, MAX(CRTR_YMD) AS available_end, "
                    "COUNT(*) AS observation_count, "
                    f"SUM({column}) AS total_amount, "
                    f"SUM(CASE WHEN TRGT_NTN = {partner} OR TRGT_NTN_CD = {partner} THEN {column} ELSE 0 END) AS partner_amount, "
                    f"STRING_AGG(DISTINCT CASE WHEN TRGT_NTN = {partner} OR TRGT_NTN_CD = {partner} THEN TRGT_NTN END, ', ' ORDER BY "
                    f"CASE WHEN TRGT_NTN = {partner} OR TRGT_NTN_CD = {partner} THEN TRGT_NTN END) AS matched_partner_names, "
                    f"STRING_AGG(DISTINCT CASE WHEN TRGT_NTN = {partner} OR TRGT_NTN_CD = {partner} THEN TRGT_NTN_CD END, ', ' ORDER BY "
                    f"CASE WHEN TRGT_NTN = {partner} OR TRGT_NTN_CD = {partner} THEN TRGT_NTN_CD END) AS matched_partner_codes "
                    f"FROM {KOMIS_SCHEMA}.KO_CSTM_CMMRC WHERE {base}"
                )
                row = frame.iloc[0].to_dict() if not frame.empty else {}
                matched_values = (row.get("matched_partner_names"), row.get("matched_partner_codes"))
                if not any(value is not None and str(value).strip().casefold() not in {"", "nan", "none"}
                           for value in matched_values):
                    raise RawDataAccessError("요청한 상대국은 해당 무역 원천에서 확인되지 않았습니다.")
                total, partner = float(row.get("total_amount") or 0), float(row.get("partner_amount") or 0)
                value = round(partner / total * 100, 4) if total else None
                period_fields = ({"year": calendar_year} if has_calendar_year
                                 else {"period": f"{_format_period_value(start, 'day')}~{_format_period_value(end, 'day')}"})
                rows = [{**period_fields, "flow": flow, "partner_country": partner_country,
                         "partner_amount": partner, "total_amount": total, "dependency_pct": value}]
                labels = ({"year": "연도"} if has_calendar_year else {"period": "요청 기간"}) | {
                          "flow": "교역방향", "partner_country": "상대국",
                          "partner_amount": "특정국 금액(USD)", "total_amount": "전체 금액(USD)",
                          "dependency_pct": "특정국 의존도(%)"}
                formula = "특정국 금액/같은 기준국·광종·방향·기간의 전체 상대국 금액×100"
                unit = "%"
            else:
                raise RawDataAccessError(f"지원하지 않는 무역지표입니다: {trade_metric}")
        except RawDataAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("무역지표 원자료 집계에 실패했습니다.") from exc
        # 집계 결과도 실제 관측일을 같이 보존한다. 연도 필터를 줬더라도 원천이
        # 일부 기간만 적재됐을 수 있으므로, ``2025년``만 Evidence에 남기면
        # 부분 관측을 연간 값처럼 오해하게 된다.
        if trade_metric == "trade_growth":
            current_row = next((item for item in frame.to_dict("records") if item["period"] == "current"), {})
            available_start, available_end = current_row.get("available_start"), current_row.get("available_end")
            observation_count = current_row.get("observation_count")
        else:
            available_start, available_end = row.get("available_start"), row.get("available_end")
            observation_count = row.get("observation_count")
        observed_period = (
            f"{_format_period_value(available_start, 'day')}~{_format_period_value(available_end, 'day')}"
            if available_start is not None and available_end is not None else None
        )
        requested_period = f"{_format_period_value(start, 'day')}~{_format_period_value(end, 'day')}"
        metadata: dict[str, Any] = {
            "trade_metric": trade_metric, "formula": formula,
            "reporter_country": "한국", "hs_codes": hs_codes,
            "requested_period": requested_period, "observed_period": observed_period,
            "observation_count": _json_value(observation_count),
            "period_coverage": (
                "boundary_matched" if not has_calendar_year and observed_period == requested_period
                else "complete" if observed_period == requested_period else "partial"
            ),
        }
        if trade_metric == "country_dependency":
            metadata.update({
                "partner_country_input": partner_country,
                "denominator_scope": denominator_scope or "reporter_product_trade",
                "matched_partner_names": row.get("matched_partner_names"),
                "matched_partner_codes": row.get("matched_partner_codes"),
            })
        return RawDataset(source_table="KO_CSTM_CMMRC", columns=list(labels), column_labels=labels,
                          row_count=len(rows), rows=rows, as_of=observed_period, unit=unit,
                          metadata=metadata)

    def fetch_global_trade_indicator_inputs(
        self, *, trade_metric: str, hs_codes: list[str], reporter_country: str,
        partner_country: str | None, calendar_year: int,
    ) -> RcaInputs | TiiInputs:
        """RCA·TII 세계 분모 원천 어댑터 경계.

        후속 데이터 계약에서 세계 전체 HS·국가·기간이 완전한 테이블 또는 API를
        provider로 주입한다. 현재 ``KO_UN_CMMRC`` 부분 표본을 이 계약에 억지로
        넣지 않는다.
        """
        if self._global_trade_indicator_provider is None:
            raise RawDataAccessError(
                "세계 전체 분모 원천이 아직 연결되지 않아 RCA·TII는 현재 계산할 수 없습니다."
            )
        if trade_metric not in {"rca", "tii"} or not hs_codes or not all(isinstance(code, str) and code for code in hs_codes):
            raise RawDataAccessError("RCA·TII 세계 분모 조회에 필요한 지표와 HS 코드가 없습니다.")
        if not reporter_country or not isinstance(calendar_year, int) or isinstance(calendar_year, bool):
            raise RawDataAccessError("RCA·TII 세계 분모 조회에 필요한 기준국 또는 연도가 없습니다.")
        if trade_metric == "tii" and not partner_country:
            raise RawDataAccessError("TII 세계 분모 조회에 필요한 상대국이 없습니다.")
        try:
            inputs = self._global_trade_indicator_provider(
                trade_metric=trade_metric,
                hs_codes=hs_codes,
                reporter_country=reporter_country,
                partner_country=partner_country,
                calendar_year=calendar_year,
            )
        except RawDataAccessError:
            raise
        except Exception as exc:  # noqa: BLE001 -- provider 오류는 원천 가용성 오류로 닫는다.
            raise RawDataAccessError("RCA·TII 세계 분모 원천 조회에 실패했습니다.") from exc
        expected_type = RcaInputs if trade_metric == "rca" else TiiInputs
        if not isinstance(inputs, expected_type):
            raise RawDataAccessError("RCA·TII 세계 분모 원천이 필요한 입력 형식을 반환하지 않았습니다.")
        return inputs

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
        # ``SU``는 국가가 아니라 KOMIS의 세계 합계 행이고, ``OT``는 기타
        # 집계 행이다. 국가 순위에 포함하면 세계 합계가 1위가 되고 국가 행과
        # 함께 더해져 점유율 분모도 이중 집계된다. 둘은 목록에서 제외한다.
        country_where_clause = (
            f"{where_clause} AND t.{country_column} NOT IN ('SU', 'OT')"
        )
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
                f" WHERE {country_where_clause}"
                f" GROUP BY COALESCE(m.ntn_nm_ko, t.{country_column})"
                f" ORDER BY total DESC NULLS LAST LIMIT {int(top_n)}"
            )
            total_frame = read_sql_pg(
                f"SELECT SUM(t.{metric_column}) AS grand_total, "
                f"MIN(t.{period_column}) AS period_start, MAX(t.{period_column}) AS period_end "
                f"FROM {KOMIS_SCHEMA}.{table} t WHERE {country_where_clause}"
            )
            world_total_frame = read_sql_pg(
                f"SELECT SUM(t.{metric_column}) AS world_total "
                f"FROM {KOMIS_SCHEMA}.{table} t WHERE {where_clause} "
                f"AND t.{country_column} = 'SU'"
            )
        except Exception as exc:  # noqa: BLE001 — 원본과 같은 사용자 노출 메시지
            raise RawDataAccessError("매장량/생산량 국가별 랭킹 조회에 실패했습니다.") from exc

        country_total_value = total_frame["grand_total"].iloc[0] if not total_frame.empty else None
        world_total_value = (world_total_frame["world_total"].iloc[0]
                             if not world_total_frame.empty else None)
        # 공식 세계 합계(SU)가 있으면 그것을 분모로 쓴다. 없는 원천만 국가
        # 합계로 열화하며, 그 경우에도 SU/OT는 국가 행에 포함하지 않는다.
        grand_total_value = world_total_value if world_total_value is not None else country_total_value
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
            metadata={"grand_total": _json_value(grand_total_value), "metric": metric,
                      "share_denominator": "world_total_su" if world_total_value is not None else "country_sum"},
        )

    def fetch_production_yoy(self, *, mineral_code: str, end_year: int | None,
                             current_year: int) -> RawDataset:
        """공식 세계 총계(SU) 생산량의 연속 두 연도 YoY만 반환한다.

        국가별 행을 합산하지 않는다. ``SU``는 통합보고서의 세계 합계 코드이며,
        명시 연도는 절대 대체하지 않는다. 기본값은 현재 연도보다 이른 최신
        공식 세계행이고, 그 바로 전년이 없으면 더 오래된 쌍으로 후퇴하지 않는다.
        """
        code = _literal(mineral_code)
        if end_year is not None and end_year > current_year:
            raise RawDataAccessError("요청 연도는 실행 시점 이후일 수 없습니다.")
        if end_year is None:
            latest = read_sql_pg(
                f"SELECT MAX(p.crtr_yr) AS year FROM {KOMIS_SCHEMA}.ko_rsrc_prdctn_quty p "
                f"JOIN {KOMIS_SCHEMA}.ai_mnrl_mst m ON m.mnrknd_unq_cd=p.mnrknd_unq_cd "
                f"WHERE p.mnrknd_unq_cd={code} AND p.ntn_eng_cd='SU' AND p.se_cd='-' "
                f"AND p.prdctn_quty_ton IS NOT NULL AND m.use_yn='Y' "
                f"AND p.crtr_yr < {_literal(str(int(current_year)))}"
            )
            value = latest["year"].iloc[0] if not latest.empty else None
            if value is None:
                return RawDataset(source_table="KO_RSRC_PRDCTN_QUTY", columns=[], row_count=0, rows=[])
            end_year = int(value)
        start_year = end_year - 1
        frame = read_sql_pg(
            f"SELECT p.crtr_yr, p.prdctn_quty_ton, p.mass_unit_cd, p.se_cd, m.mnrl_nm_ko, "
            f"m.ko_data_src_cd, d.src_cd AS dummy_src "
            f"FROM {KOMIS_SCHEMA}.ko_rsrc_prdctn_quty p "
            f"JOIN {KOMIS_SCHEMA}.ai_mnrl_mst m ON m.mnrknd_unq_cd=p.mnrknd_unq_cd "
            f"LEFT JOIN {KOMIS_SCHEMA}.ai_dev_dummy_load d ON lower(d.tbl_nm)='ko_rsrc_prdctn_quty' "
            f"AND d.mnrknd_unq_cd=p.mnrknd_unq_cd "
            f"AND d.nat_key=p.mnrknd_unq_cd||'|'||p.crtr_yr::text||'|'||p.ntn_eng_cd "
            f"WHERE p.mnrknd_unq_cd={code} AND m.use_yn='Y' AND p.ntn_eng_cd='SU' AND p.se_cd='-' "
            f"AND p.crtr_yr IN ({_literal(str(start_year))},{_literal(str(end_year))})"
        )
        if len(frame) != 2 or set(int(v) for v in frame["crtr_yr"]) != {start_year, end_year}:
            return RawDataset(source_table="KO_RSRC_PRDCTN_QUTY", columns=[], row_count=0, rows=[])
        values = {int(row.crtr_yr): float(row.prdctn_quty_ton) for row in frame.itertuples()}
        prior, current = values[start_year], values[end_year]
        if not all(math.isfinite(value) and value >= 0 for value in (prior, current)):
            raise RawDataAccessError("세계 생산량에 유효하지 않은 음수 값이 있습니다.")
        change = current - prior
        pct = round(change / prior * 100, 4) if prior else None
        mineral = str(frame.iloc[0]["mnrl_nm_ko"])
        return RawDataset(
            source_table="KO_RSRC_PRDCTN_QUTY", columns=["mineral", "prior_year", "prior_tonnes", "year", "tonnes", "change_tonnes", "change_pct"],
            column_labels={"mineral":"광종", "prior_year":"전년", "prior_tonnes":"전년 세계 생산량(톤)", "year":"기준연도", "tonnes":"세계 생산량(톤)", "change_tonnes":"증감량(톤)", "change_pct":"증감률(%)"},
            row_count=1, rows=[{"mineral":mineral, "prior_year":start_year, "prior_tonnes":prior,
                                "year":end_year, "tonnes":current, "change_tonnes":change, "change_pct":pct}],
            as_of=f"{start_year}~{end_year}", unit="톤",
            metadata={"world_total_code":"SU", "data_source": str(frame.iloc[0]["ko_data_src_cd"] or "unverified"),
                      "dummy_source": str(frame.iloc[0]["dummy_src"] or ""),
                      "annual_completion_status":"unverified", "explicit_year": end_year},
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

    def fetch_country_import_mineral_shares(
        self, *, country: str, metric: str, start_period: str,
        end_period: str, top_n: int = 5, mineral_names: list[str] | None = None,
    ) -> RawDataset:
        """같은 기간·광종 HS 모집단에서 특정국 수입 비중 상위 광종을 조회한다."""
        if metric not in {"import_amount", "import_weight"}:
            raise RawDataAccessError("교차 순위는 수입액 또는 수입중량만 지원합니다.")
        column = _RANKING_SPECS["map_korea"]["metrics"][metric]
        partner = _literal(country)
        start = _literal(_coerce_period(start_period, "day", False))
        end = _literal(_coerce_period(end_period, "day", True))
        names = ("AND m.mnrl_nm_ko IN (" + ", ".join(
            _literal(_MINERAL_SYNONYMS.get(name, name)) for name in mineral_names) + ")") if mineral_names else ""
        if start > end:
            raise RawDataAccessError("수입 조회 기간의 시작일이 종료일보다 늦습니다.")
        try:
            frame = read_sql_pg(f"""
                WITH mapping AS (
                    SELECT DISTINCT mnrknd_unq_cd, hs_cd
                    FROM {KOMIS_SCHEMA}.ai_hs_mtrl_flow WHERE use_yn='Y'
                ), totals AS (
                    SELECT m.mnrknd_unq_cd, m.mnrl_nm_ko AS mineral,
                           m.ko_data_src_cd AS data_source,
                           SUM(t.{column}) AS total,
                           SUM(CASE WHEN t.trgt_ntn={partner} OR t.trgt_ntn_cd={partner}
                                    THEN t.{column} ELSE 0 END) AS partner_total,
                           MIN(t.crtr_ymd) AS first_date, MAX(t.crtr_ymd) AS last_date
                    FROM mapping h
                    JOIN {KOMIS_SCHEMA}.ai_mnrl_mst m ON m.mnrknd_unq_cd=h.mnrknd_unq_cd
                    JOIN {KOMIS_SCHEMA}.ko_cstm_cmmrc t ON t.hs_cd=h.hs_cd
                    WHERE m.use_yn='Y' {names} AND t.crtr_ymd >= {start} AND t.crtr_ymd <= {end}
                      AND t.{column} IS NOT NULL AND t.{column} >= 0
                    GROUP BY m.mnrknd_unq_cd, m.mnrl_nm_ko, m.ko_data_src_cd
                )
                SELECT mnrknd_unq_cd AS mineral_code, mineral, data_source,
                       total, partner_total, first_date, last_date,
                       partner_total * 100.0 / NULLIF(total, 0) AS share_pct
                FROM totals WHERE total > 0 AND partner_total > 0
                ORDER BY share_pct DESC, partner_total DESC, mineral_code
                LIMIT {int(top_n)}
            """)
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("특정국 수입 비중의 광종별 조회에 실패했습니다.") from exc
        rows = [
            {"rank": rank, "mineral_code": str(row.mineral_code), "mineral": str(row.mineral),
             "data_source": row.data_source, "country": country,
             "total": _json_value(row.total), "partner_total": _json_value(row.partner_total),
             "share_pct": round(float(row.share_pct), 2),
             "first_date": _format_period_value(row.first_date, "day"),
             "last_date": _format_period_value(row.last_date, "day")}
            for rank, row in enumerate(frame.itertuples(index=False), 1)
        ]
        return RawDataset(source_table="KO_CSTM_CMMRC", columns=list(rows[0]) if rows else [],
                          rows=rows, row_count=len(rows), unit=_RANKING_METRIC_LABELS[metric][1],
                          metadata={"metric": metric, "country": country,
                                    "requested_start": start_period, "requested_end": end_period})

    def fetch_top_producer_mineral_shares(
        self, *, year: int | None = None, top_n: int = 5,
        mineral_names: list[str] | None = None,
    ) -> RawDataset:
        """공식 세계 총계(SU)를 분모로 광종별 1위 생산국 비중을 비교한다."""
        year_filter = f"AND p.crtr_yr={_literal(str(year))}" if year is not None else ""
        names = ("AND m.mnrl_nm_ko IN (" + ", ".join(
            _literal(_MINERAL_SYNONYMS.get(name, name)) for name in mineral_names) + ")") if mineral_names else ""
        try:
            frame = read_sql_pg(f"""
                WITH base AS (
                    SELECT p.mnrknd_unq_cd AS mineral_code, m.mnrl_nm_ko AS mineral,
                           m.ko_data_src_cd AS data_source, p.crtr_yr AS year,
                           p.ntn_eng_cd AS country_code, p.prdctn_quty_ton AS tonnes
                    FROM {KOMIS_SCHEMA}.ko_rsrc_prdctn_quty p
                    JOIN {KOMIS_SCHEMA}.ai_mnrl_mst m ON m.mnrknd_unq_cd=p.mnrknd_unq_cd
                    WHERE m.use_yn='Y' {names} AND p.se_cd='-' AND p.prdctn_quty_ton IS NOT NULL
                      AND p.prdctn_quty_ton >= 0 {year_filter}
                ), latest_year AS (
                    SELECT mineral_code, MAX(year) AS year FROM base
                    WHERE country_code='SU' GROUP BY mineral_code
                ), world AS (
                    SELECT b.mineral_code, b.year, SUM(b.tonnes) AS world_tonnes
                    FROM base b JOIN latest_year y USING (mineral_code, year)
                    WHERE b.country_code='SU' GROUP BY b.mineral_code, b.year
                ), countries AS (
                    SELECT b.mineral_code, b.mineral, b.data_source, b.year,
                           b.country_code, SUM(b.tonnes) AS country_tonnes
                    FROM base b JOIN latest_year y USING (mineral_code, year)
                    WHERE b.country_code NOT IN ('SU','OT')
                    GROUP BY b.mineral_code, b.mineral, b.data_source, b.year, b.country_code
                ), ranked AS (
                    SELECT c.*, w.world_tonnes,
                           ROW_NUMBER() OVER (PARTITION BY c.mineral_code
                                              ORDER BY c.country_tonnes DESC, c.country_code) AS country_rank
                    FROM countries c JOIN world w USING (mineral_code, year)
                    WHERE w.world_tonnes > 0 AND c.country_tonnes <= w.world_tonnes
                )
                SELECT r.mineral_code, r.mineral, r.data_source, r.year,
                       r.country_code, COALESCE(n.ntn_nm_ko, r.country_code) AS country,
                       r.country_tonnes, r.world_tonnes,
                       r.country_tonnes * 100.0 / r.world_tonnes AS share_pct
                FROM ranked r LEFT JOIN {KOMIS_SCHEMA}.ai_ntn_mst n ON n.ntn_cd=r.country_code
                WHERE r.country_rank=1
                ORDER BY share_pct DESC, r.country_tonnes DESC, r.mineral_code
                LIMIT {int(top_n)}
            """)
        except Exception as exc:  # noqa: BLE001
            raise RawDataAccessError("광종별 생산 1위국 비중 조회에 실패했습니다.") from exc
        rows = [
            {"rank": rank, "mineral_code": str(row.mineral_code), "mineral": str(row.mineral),
             "data_source": row.data_source, "year": int(row.year),
             "country": str(row.country), "country_code": str(row.country_code),
             "country_tonnes": _json_value(row.country_tonnes),
             "world_tonnes": _json_value(row.world_tonnes),
             "share_pct": round(float(row.share_pct), 2)}
            for rank, row in enumerate(frame.itertuples(index=False), 1)
        ]
        return RawDataset(source_table="KO_RSRC_PRDCTN_QUTY", columns=list(rows[0]) if rows else [],
                          rows=rows, row_count=len(rows), unit="톤",
                          metadata={"metric": "production", "world_total_code": "SU",
                                    "requested_year": year})

    def fetch_latest_indicator_ranking(
        self, *, page_id: str, ascending: bool, mineral_names: list[str] | None, top_n: int = 5,
    ) -> RawDataset:
        """지표(수급동향/시장전망) 최신값 기준 광종 간 랭킹(결정적, 2026-09-18
        신설). 각 광종의 가장 최근 1건(`DISTINCT ON`)만 골라 비교한다.
        `mineral_names`가 있으면 그 광종들만, 없으면 지표가 있는 전 광종
        대상 상위 N개."""

        spec = _LATEST_INDICATOR_RANKING_SPECS.get(page_id)
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
