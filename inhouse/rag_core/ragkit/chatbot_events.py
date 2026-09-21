# -*- coding: utf-8 -*-
"""챗봇 이벤트 타입 + 구조화 블록(table·chart) 생성 유틸.

chatbot.py가 만드는 이벤트를 각 서빙 레이어(rag_chat의 SSE, 향후 CLI 등)가
그대로 실어나를 수 있게 프레임워크 독립적인 dataclass로 표준화한다. `data`는 그
서빙 레이어가 그대로 JSON 직렬화해서 보내는 payload — 필드명을 기존
rag_chat SSE 계약(session_id·delta·done·citations·bogus_citations)과
하위호환되게 맞췄다.

2026-09-13: private(/prichat) 전용으로 PNG `image` 대신 구조화 블록(`table`
확장 + `chart` 스펙)을 도입. 2026-09-16(사용자 지시): 같은 블록을 public
(/pubchat)에도 적용하고 `image`(matplotlib PNG) 경로는 제거 — 표·차트를 그리는
주체는 프론트이므로 서버는 "데이터 + 표현 힌트"만 낸다. 같은 날 표 블록에
추천 차트 종류(`chart_hint`)를 함께 기재하도록 `recommend_chart()` 신설.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
_NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?%?$")
#: 근거 표는 DB 행을 `str(value)`로 옮긴 것이라 NULL이 "None" 문자열로 온다
#: (rag_core/retrieval/evidence.py::from_komis_raw). 이런 셀은 "숫자가 아님"이
#: 아니라 "값 없음"으로 봐야 그 열이 통째로 문자열 취급돼 차트에서 빠지는 일이
#: 없다(2026-09-16 실측: 가격표의 uplmt/lwlmt·prvmm_cprs 등).
_NULL_CELLS = frozenset({"", "none", "null", "nan"})


@dataclass(frozen=True)
class ChatEvent:
    """type: session|status|delta|table|chart|done. sse_name은 SSE `event:` 필드에
    쓸 이름(None이면 무명 기본 이벤트 — 기존 계약에서 session/delta가 그랬다).
    `table`·`chart`는 인용된 근거의 표에서 서버가 결정론적으로 만드는 구조화
    블록(`table_block()`·`chart_spec()`)."""

    type: str
    data: dict

    @property
    def sse_name(self) -> str | None:
        return None if self.type in ("session", "delta") else self.type


def extract_markdown_tables(text: str) -> list[dict]:
    """GFM 스타일 표(`| a | b |` + `| --- | --- |` 구분선)를 파싱해
    [{"columns": [...], "rows": [[...], ...], "markdown": "..."}] 로 돌려준다.

    rag_core/ragkit/ingest.py가 docx·opendataloader-pdf 산출물을 마크다운으로 펼쳐서
    청킹하므로(§chunk.py), 청크 본문에 이 형태의 표가 그대로 남아 있다 — 별도
    표 추출 파이프라인을 새로 만들 필요 없이 정규식 파싱만으로 충분하다."""

    lines = text.splitlines()
    tables: list[dict] = []
    i = 0
    n = len(lines)
    while i < n - 1:
        header_line = lines[i].strip()
        sep_line = lines[i + 1].strip()
        if not (header_line.startswith("|") and header_line.endswith("|")):
            i += 1
            continue
        if not sep_line.startswith("|"):
            i += 1
            continue
        sep_cells = [c.strip() for c in sep_line.strip("|").split("|")]
        if not sep_cells or not all(_TABLE_SEP_CELL_RE.match(c) for c in sep_cells):
            i += 1
            continue

        columns = [c.strip() for c in header_line.strip("|").split("|")]
        rows: list[list[str]] = []
        j = i + 2
        while j < n and lines[j].strip().startswith("|"):
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            if len(cells) == len(columns):
                rows.append(cells)
            j += 1
        if rows:
            # `markdown`(2026-09-13 신설) — 원문 조각. 블록 이벤트를 받는
            # 프론트가 답변 텍스트 안의 이 표를 자기 컴포넌트로 치환할 때 쓴다.
            tables.append({"columns": columns, "rows": rows, "markdown": "\n".join(lines[i:j])})
        i = j
    return tables


#: `komis_raw.py::_PAGE_DATASETS`의 `period_column`이 전 page_id에 걸쳐 쓰는
#: 두 이름뿐이다(실측 확인, grep "period_column=" 전수조사) — YYYYMMDD/YYYYMM
#: 숫자문자열이라 `_NUM_RE`에 그대로 걸려 아래 숫자열 탐색에서 가격·지표
#: 같은 진짜 수치로 오인되던 버그(2026-09-03, 사용자 실측 제보 — 니켈 가격
#: 차트의 X축이 날짜(crtr_ymd)가 아니라 광종 식별자(mnrl_prc_crtr_sn)로,
#: Y축은 가격이 아니라 crtr_ymd 자체로 그려짐). 이 열은 (1) 라벨(X축) 후보로
#: 최우선하고 (2) 숫자열(Y축) 후보에서는 무조건 제외한다.
_DATE_COLUMN_NAMES = {
    "crtr_ymd", "crtr_yr", "first_date", "last_date", "price_date", "month",
}
_NON_MEASURE_KEYS = frozenset({
    "rank", "transaction_count", "record_count", "n", "count", "price_criterion_serial",
})
_PRICE_KEYS = frozenset({"lowst_prc", "hghst_prc", "cmerc_prc"})


def _unit_from_header(header: str) -> str | None:
    """표 헤더의 DB 메타데이터에 실제로 표시된 단위만 노출한다.

    숫자의 크기나 컬럼명으로 통화/중량을 추정하지 않는다. 예를 들어 가격
    테이블의 단위가 DB 코멘트에 없으면 차트에도 단위를 만들어 내지 않는다.
    """

    # 단위가 `total(수입금액합계(USD))`처럼 중첩 괄호 안에 있거나
    # `수입중량 kg`처럼 설명 뒤에 붙는 경우를 모두 허용한다. 단위 표기는
    # 원문 헤더에서 확인된 것만 반환해 임의의 차원 추정을 피한다.
    match = re.search(
        r"(?<![A-Za-z가-힣])(?:천USD|USD|kg|톤|%|지수(?:\([^)]*\))?)(?![A-Za-z가-힣])",
        header, re.IGNORECASE,
    )
    if match:
        return match.group(0)
    # `share_pct(비중(%, 전체 국가 합계 대비))`처럼 사람이 읽는 설명 안에
    # 괄호가 한 번 더 들어간 헤더는 `%` 다음에 바로 닫는 괄호가 없다. 이 경우
    # 데이터셋 전체 단위(예: USD)를 비중 축에 물려 쓰면 차원이 뒤바뀌므로,
    # 명시된 %를 우선 인식한다.
    return "%" if "%" in header else None


def _is_date_column(header: str) -> bool:
    """정확히 일치("crtr_ymd")하거나, 컬럼 라벨이 붙은 형태("crtr_ymd(기준일자)",
    2026-09-07 — evidence.py::from_komis_raw가 Postgres COMMENT ON COLUMN을
    표 헤더에 같이 보여주기 시작하면서 헤더가 순수 컬럼명이 아닐 수 있게
    됐다)로 시작하면 날짜열로 본다."""

    normalized = header.strip().lower()
    return any(
        normalized == name or normalized.startswith(f"{name}(") for name in _DATE_COLUMN_NAMES
    )


def _numeric_series(rows: list[list[str]], col_idx: int) -> list[float | None] | None:
    """col_idx 열의 모든 셀이 숫자(콤마·% 허용) 또는 빈 값(_NULL_CELLS)이고
    숫자가 하나 이상이면 [float|None] 리스트, 하나라도 다른 문자열이면 None
    (그 열은 차트 후보에서 제외 — 범주형 라벨 열을 숫자로 억지로 해석하지
    않는다)."""

    values: list[float | None] = []
    for row in rows:
        raw = row[col_idx].strip()
        if raw.lower() in _NULL_CELLS:
            values.append(None)
            continue
        if not _NUM_RE.match(raw):
            return None
        values.append(float(raw.replace(",", "").replace("%", "")))
    return values if any(v is not None for v in values) else None


# ---- 구조화 블록(2026-09-13 private 도입 → 2026-09-16 public 공통) ------------
#: 표·차트를 그리는 주체는 챗봇이 아니라 프론트여야 한다는 원칙으로, PNG 대신
#: "데이터 + 표현 힌트"를 준다. 블록 형태는 콘텐츠 블록 패턴(타입별 객체 +
#: schema_version) — `<json></json>` 같은 HTML 태그를 마크다운에 끼우는 방식은
#: 렌더러 sanitize·SSE 청크 분절 문제로 채택하지 않았다.
BLOCK_SCHEMA_VERSION = 1

#: 프론트에 추천하는 차트 종류(스펙 `kind` / `chart_hint.recommended` 값)와 뜻.
#: 규칙은 `recommend_chart()` 한 곳에서만 판정한다 — 표 블록의 `chart_hint`와
#: `chart` 이벤트의 `spec`이 같은 판정을 공유해 어긋나지 않는다.
CHART_KINDS = {
    "line": "시계열 추이 — 날짜열이 X축이고 시점이 4개 이상",
    "bar": "범주 비교(국가·품목 등) 또는 시점 3개 이하의 시계열 — 계열이 여럿이면 묶음막대",
    "pie": "단일 계열의 구성비 — 범주 2~8개, 값이 전부 양수일 때 bar의 대안으로만 추천",
}


def _column_types(table: dict) -> list[dict]:
    """헤더마다 {key, label, display, type(date|number|string), unit(%|None)}.
    `key`는 헤더에서 `(설명)`을 뗀 컬럼 키, `display`는 그 괄호 안 설명(없으면
    key) — 차트 제목·범례처럼 사람이 읽는 자리에 쓴다."""

    columns, rows = table["columns"], table["rows"]
    out = []
    for idx, header in enumerate(columns):
        key = header.split("(", 1)[0].strip() or f"col{idx}"
        display = header[len(key) + 1:-1].strip() if "(" in header and header.endswith(")") else key
        if _is_date_column(header):
            ctype, unit = "date", None
        elif _numeric_series(rows, idx) is not None:
            ctype = "number"
            unit = _unit_from_header(header)
            if unit is None and rows and all(r[idx].strip().endswith("%") for r in rows if r[idx].strip().lower() not in _NULL_CELLS):
                unit = "%"
        else:
            ctype, unit = "string", None
        out.append({"key": key, "label": header, "display": display or key, "type": ctype, "unit": unit})
    return out


def _date_format(values: list[str]) -> str | None:
    normalized = [v.strip() for v in values]
    if normalized and all(re.fullmatch(r"\d{4}-\d{2}", value) for value in normalized):
        return "YYYY-MM"
    lengths = {len(v) for v in normalized}
    return {8: "YYYYMMDD", 6: "YYYYMM", 4: "YYYY"}.get(next(iter(lengths))) if len(lengths) == 1 else None


def _distinct_text_values(table: dict, key: str) -> list[str]:
    """표의 보조 문자열 열에서 표시용 고유값을 순서대로 추출한다."""

    meta = _column_types(table)
    idx = next((i for i, m in enumerate(meta) if m["key"] == key), None)
    if idx is None or meta[idx]["type"] != "string":
        return []
    values: list[str] = []
    for row in table["rows"]:
        value = row[idx].strip()
        if value.lower() in _NULL_CELLS or value in values:
            continue
        values.append(value)
    return values


def _price_unit_from_codes(currency_codes: list[str], weight_codes: list[str]) -> str | None:
    """명시된 통화·중량 코드가 검증된 경우에만 가격 단위를 만든다."""

    currencies = {"USD", "KRW", "EUR", "CNY", "JPY", "GBP"}
    weights = {"KG": "kg", "G": "g", "T": "톤", "TON": "톤", "MT": "톤", "LB": "lb", "OZ": "oz"}
    currency = currency_codes[0].upper() if len(currency_codes) == 1 else None
    weight = weight_codes[0].upper() if len(weight_codes) == 1 else None
    if currency not in currencies:
        return None
    if weight is None:
        return currency
    normalized_weight = weights.get(weight)
    return f"{currency}/{normalized_weight}" if normalized_weight else None


def recommend_chart(table: dict, columns_meta: list[dict] | None = None) -> dict:
    """표 모양만 보고 추천 차트를 결정론적으로 판정한다(LLM 관여 없음).

    반환: {recommended: line|bar|pie|None, alternatives: [...], x, x_type
    (date|category), x_format, series: [key], group: key|None,
    sort_x_ascending, reason}. `recommended`가 None이면 차트를 그리지 않는다
    (억지 차트 금지 원칙 — 숫자 계열이 없거나 행이 2개 미만).

    판정 순서:
    1. 계열(Y) = 숫자열 중 값이 갈리는 열. 전 행이 같은 값(식별자·고정 코드)이나
       전부 빈 값인 열은 제외.
    2. 날짜열(crtr_ymd/crtr_yr)이 있고 시점당 1행이면 시계열 — 시점 4개 이상
       line, 그 미만 bar. X는 날짜, 과거→최근 오름차순.
    3. 날짜열이 있는데 시점이 1개뿐이면(단일 연도 국가별 매장량 등) 범주형 —
       X는 구분 열(문자열 열 중 값이 갈리는 것, `_cd`로 끝나지 않는 사람이 읽는
       열 우선), bar. 계열이 하나고 범주 2~8개·전부 양수면 pie를 대안으로.
    4. 날짜열이 있고 시점도 여럿·구분 열도 있으면(연도×국가) X는 날짜,
       `group`=구분 열(프론트가 그룹별 계열로 펼친다), 시점 4개 이상 line 아니면 bar.
    5. 날짜열이 없으면 X는 구분 열(없으면 첫 열), bar(+pie 대안)."""

    columns, rows = table["columns"], table["rows"]
    meta = columns_meta or _column_types(table)
    none = {
        "recommended": None, "alternatives": [], "x": None, "x_type": None, "x_format": None,
        "series": [], "group": None, "sort_x_ascending": False,
    }
    if len(rows) < 2 or len(columns) < 2:
        return {**none, "reason": "행 2개 미만 또는 열 1개"}

    series_keys: list[str] = []
    seen_values: list[tuple[list[float | None], str | None]] = []
    for idx, m in enumerate(meta):
        if m["type"] != "number":
            continue
        key = m["key"].lower()
        # 순위·거래/레코드 건수·코드/일련번호는 식별·보조 정보이지 Y축에서
        # 비교할 측정값이 아니다. 값이 변한다는 이유만으로 계열에 넣지 않는다.
        if (key in _NON_MEASURE_KEYS or key.endswith(("_cd", "_sn", "_id"))
                or key.startswith("hs") or key in {"invt", "inventory"}):
            continue
        values = _numeric_series(rows, idx) or []
        # 값이 갈리지 않는 열(식별자·고정 코드)과, 앞선 계열과 값이 완전히 같은
        # 열(KOMIS `*_quty` ↔ `*_quty_ton` 톤환산 중복 열)은 계열에서 뺀다.
        # 원시값이 우연히 같은 total=80/20과 share_pct=80/20이라도 단위가
        # 다르면 중복 계열이 아니다. 동일 단위의 톤환산 중복만 제거한다.
        duplicate = any(
            values == prior_values and m["unit"] == prior_unit
            for prior_values, prior_unit in seen_values
        )
        if len({v for v in values if v is not None}) > 1 and not duplicate:
            series_keys.append(m["key"])
            seen_values.append((values, m["unit"]))
    # 가격표는 가격과 재고의 차원이 다르다. 단일 chart 스펙에 둘을 섞으면
    # 축의 의미가 사라지므로 가격 계열을 우선하고 재고는 별도 표로만 보존한다.
    price_series = [key for key in series_keys if key.lower() in _PRICE_KEYS]
    if price_series:
        series_keys = price_series
    # 시작·종료 가격과 변동률은 서로 다른 차원이다. 비교 결과 표는 변동률을
    # 시각화하고 시작/종료값은 표에서 검증하게 해 한 Y축에 섞지 않는다.
    if "pct_change" in series_keys:
        series_keys = ["pct_change"]
    # 국가별 교역 랭킹의 total(금액/중량)과 share_pct(%)는 같은 모집단의 서로
    # 다른 표현이다. 한 축에 섞지 않고, 비중 컬럼이 있는 교역표는 %만 그린다.
    total_meta = next((m for m in meta if m["key"] == "total"), None)
    if "share_pct" in series_keys and total_meta and any(term in total_meta["display"] for term in ("수입", "수출")):
        series_keys = ["share_pct"]
    elif "total" in series_keys and total_meta and any(term in total_meta["display"] for term in ("생산", "매장")):
        series_keys = ["total"]
    if not series_keys:
        return {**none, "reason": "값이 갈리는 숫자 계열 없음"}

    date_idx = next((i for i, m in enumerate(meta) if m["type"] == "date"), None)
    cat_candidates = [
        i for i, m in enumerate(meta)
        if m["type"] == "string" and len({row[i] for row in rows}) > 1
    ]
    cat_idx = next((i for i in cat_candidates if not meta[i]["key"].lower().endswith("_cd")),
                   cat_candidates[0] if cat_candidates else None)

    def _series_positive() -> bool:
        idx = next(i for i, m in enumerate(meta) if m["key"] == series_keys[0])
        return all(v is not None and v > 0 for v in (_numeric_series(rows, idx) or []))

    def _categorical(x_idx: int, reason: str) -> dict:
        pie_ok = len(series_keys) == 1 and 2 <= len(rows) <= 8 and _series_positive()
        return {
            "recommended": "bar", "alternatives": ["pie"] if pie_ok else [],
            "x": meta[x_idx]["key"], "x_type": "category", "x_format": None,
            "series": series_keys, "group": None, "sort_x_ascending": False, "reason": reason,
        }

    if date_idx is not None:
        date_values = [row[date_idx] for row in rows]
        n_dates = len(set(date_values))
        x_format = _date_format(date_values)
        if n_dates == len(rows):
            kind = "line" if len(rows) >= 4 else "bar"
            return {
                "recommended": kind, "alternatives": [], "x": meta[date_idx]["key"], "x_type": "date",
                "x_format": x_format, "series": series_keys, "group": None, "sort_x_ascending": True,
                "reason": f"시점당 1행인 시계열, 시점 {n_dates}개",
            }
        if cat_idx is None:
            return {**none, "reason": "시점이 중복되는데 구분(범주) 열이 없음"}
        if n_dates == 1:
            return _categorical(cat_idx, f"단일 시점({date_values[0]}) 스냅샷 — {meta[cat_idx]['key']}별 비교")
        kind = "line" if n_dates >= 4 else "bar"
        return {
            "recommended": kind, "alternatives": [], "x": meta[date_idx]["key"], "x_type": "date",
            "x_format": x_format, "series": series_keys, "group": meta[cat_idx]["key"],
            "sort_x_ascending": True,
            "reason": f"시점 {n_dates}개 × {meta[cat_idx]['key']} 구분 — 구분값별 계열",
        }
    x_idx = cat_idx if cat_idx is not None else 0
    return _categorical(x_idx, f"날짜열 없음 — {meta[x_idx]['key']}별 비교")


def table_block(table: dict, *, block_id: str, source_index: int | None, source_label: str | None,
                as_of: str | None = None, unit: str | None = None) -> dict:
    """`table` 이벤트 payload. 기존 키(columns·rows·source_index·source)는
    그대로 두고(구 클라이언트 호환) 구조화 필드를 덧붙인다. `chart_hint`
    (2026-09-16)는 이 표에 추천하는 차트 종류 — 같은 판정으로 만든 `chart`
    이벤트가 뒤따르므로 프론트는 둘 중 편한 쪽을 쓰면 된다."""

    columns_meta = _column_types(table)
    typed_rows = []
    for row in table["rows"]:
        typed = []
        for cell, meta in zip(row, columns_meta):
            raw = cell.strip()
            if raw.lower() in _NULL_CELLS:
                typed.append(None)  # DB NULL("None")은 타입과 무관하게 null
            elif meta["type"] == "number":
                typed.append(float(raw.replace(",", "").replace("%", "")))
            else:
                typed.append(cell)
        typed_rows.append(typed)
    hint = recommend_chart(table, columns_meta)
    return {
        "schema_version": BLOCK_SCHEMA_VERSION,
        "block_id": block_id,
        "columns": table["columns"],
        "rows": table["rows"],
        "columns_meta": columns_meta,
        "rows_typed": typed_rows,
        "markdown": table.get("markdown"),
        "chart_hint": {
            "recommended": hint["recommended"], "alternatives": hint["alternatives"], "reason": hint["reason"],
        },
        "meta": {"source_index": source_index, "source": source_label, "row_count": len(table["rows"]),
                 "as_of": as_of, "unit": unit},
        "source_index": source_index,
        "source": source_label,
    }


def chart_spec(table: dict, *, block_id: str, data_ref: str, source_index: int | None, source_label: str | None,
               as_of: str | None = None, unit: str | None = None) -> dict | None:
    """`chart` 이벤트 payload — `recommend_chart()` 판정을 선언적 스펙으로 낸다.
    데이터는 싣지 않고 `data_ref`가 가리키는 `table` 블록의 rows_typed/
    columns_meta를 쓴다. 추천 차트가 없으면 None(억지 차트 금지)."""

    columns_meta = _column_types(table)
    hint = recommend_chart(table, columns_meta)
    if hint["recommended"] is None:
        return None
    display = {m["key"]: m["display"] for m in columns_meta}
    # Q05 가격 비교 long-form 표는 `group=mineral`, `series=price`로
    # 광종별 계열을 표현한다. 가격 기준·단위는 표의 보조 열을 함께 내보내
    # 프론트가 동일한 가격 기준을 범례/축 설명에 표시할 수 있게 한다.
    price_criteria = _distinct_text_values(table, "price_criterion")
    price_units = _distinct_text_values(table, "price_unit")
    currency_codes = _distinct_text_values(table, "price_currency_code")
    weight_codes = _distinct_text_values(table, "weight_unit_code")
    inferred_unit = next((m["unit"] for m in columns_meta
                          if m["key"] == hint["series"][0] and m["unit"]), None)
    coded_unit = _price_unit_from_codes(currency_codes, weight_codes)
    has_code_columns = any(m["key"] in {"price_currency_code", "weight_unit_code"} for m in columns_meta)
    y_unit = inferred_unit or coded_unit
    if not has_code_columns:
        y_unit = y_unit or unit or (price_units[0] if len(price_units) == 1 else None)
    spec = {
        "schema_version": BLOCK_SCHEMA_VERSION,
        "block_id": block_id,
        "data_ref": data_ref,
        "spec": {
            "kind": hint["recommended"],
            "alternatives": hint["alternatives"],
            "x": hint["x"],
            "x_type": hint["x_type"],
            "x_format": hint["x_format"],
            "series": hint["series"],
            "group": hint["group"],
            "sort_x_ascending": hint["sort_x_ascending"],
            "title": " · ".join(display[k] for k in hint["series"]),
            "y_unit": y_unit,
            "as_of": as_of,
        },
        "meta": {"source_index": source_index, "source": source_label},
        "source_index": source_index,
        "source": source_label,
    }
    if price_criteria:
        spec["spec"]["price_criterion"] = price_criteria[0] if len(price_criteria) == 1 else price_criteria
    if price_units:
        spec["spec"]["price_unit"] = price_units[0] if len(price_units) == 1 else price_units
    if currency_codes:
        spec["spec"]["price_currency_code"] = currency_codes[0] if len(currency_codes) == 1 else currency_codes
    if weight_codes:
        spec["spec"]["weight_unit_code"] = weight_codes[0] if len(weight_codes) == 1 else weight_codes
    return spec
