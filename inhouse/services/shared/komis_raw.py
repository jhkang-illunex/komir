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

_SERVICES_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICES_ROOT))

from shared.db import read_sql_pg  # noqa: E402

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
    limit: int = Field(default=5, ge=1, le=20)

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
    """원천 테이블 1개에서 읽어온 행과 컬럼 메타."""

    source_table: str
    columns: list[str]
    row_count: int = Field(ge=0)
    rows: list[dict[str, Any]]


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
    fixed_conditions=("STATUS = 'Y'",),
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
        return RawDataset(
            source_table=spec.table,
            columns=column_names,
            row_count=len(rows),
            rows=rows,
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

    def resolve_hs_codes(self, mineral_code: str) -> list[str]:
        """`ai_hs_mnrl_map`에서 광종의 HS코드(들)를 찾는다(오름차순)."""

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT hs_cd FROM {KOMIS_SCHEMA}.ai_hs_mnrl_map"
            f" WHERE mnrknd_unq_cd = {code} AND use_yn = 'Y'"
            f" ORDER BY hs_cd"
        )
        return [str(value) for value in frame["hs_cd"]]

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

    def resolve_data_source(self, mineral_code: str) -> str | None:
        """`ai_mnrl_mst`에서 광종의 `ko_data_src_cd`(예: `KOMIS_SAMPLE`·
        `DEV_DUMMY`)를 찾는다 — 2026-08-31 스키마매핑 조사에서 발주 5광종
        (CU/NI/CO/LI/REE)의 `ko_*` 데이터가 대부분 개발용 더미로 확인되어
        (`documents/산출물/2026-W36_0831-0906/KOMIS_public_ko테이블_
        스키마매핑_260831.md` 참고), MCP 도구가 조회 결과에 더미 경고를
        동봉할 수 있게 추가했다. 값이 없거나 광종이 없으면 None."""

        code = _literal(mineral_code)
        frame = read_sql_pg(
            f"SELECT ko_data_src_cd FROM {KOMIS_SCHEMA}.ai_mnrl_mst"
            f" WHERE mnrknd_unq_cd = {code}"
        )
        if frame.empty:
            return None
        value = frame.iloc[0]["ko_data_src_cd"]
        return None if value is None else str(value)

    def resolve_mineral_meta(self, mineral_code: str) -> tuple[str, str | None] | None:
        """`ai_mnrl_mst`에서 (한글명, `ko_data_src_cd`)를 한 번의 조회로 찾는다.

        `resolve_mineral()`(코드→한글명)과 `resolve_data_source()`(코드→
        데이터출처코드)가 완전히 같은 테이블·같은 WHERE 조건(`mnrknd_unq_cd`
        = code)을 각각 별도 `read_sql_pg()` 왕복으로 조회하던 걸 하나로
        합친다 — `komis_raw_lookup`(rag/ragkit/_mcp_tools_common.py)이 근거
        라벨(한글명)과 더미데이터 경고(데이터출처코드)를 매 호출마다 함께
        필요로 하면서 mineral_code 하나당 DB 왕복이 최대 3~4회까지 쌓이던
        것의 일부를 줄인다(skeptic-code DEEP 감사 SC-001, 2026-09-01, 사용자
        승인). `resolve_mineral()`은 `report_gen/app/analysis/data_sources/
        extra.py`에서 별도로 쓰이고 있어 그대로 남겨뒀다(이 메서드가 그걸
        대체하지 않는다) — `resolve_data_source()`는 이 변경 이후 호출부가
        없어졌지만, 리포지토리의 공개 API로 남겨두는 것 자체는 이번 지시
        범위 밖이라 함께 손대지 않았다."""

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
