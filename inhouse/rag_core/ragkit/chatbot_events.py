# -*- coding: utf-8 -*-
"""챗봇 이벤트 타입 + 다중매체(표·차트) 추출 유틸.

chatbot.py가 만드는 이벤트를 각 서빙 레이어(services/rag_chat의 SSE, 향후 CLI 등)가
그대로 실어나를 수 있게 프레임워크 독립적인 dataclass로 표준화한다. `data`는 그
서빙 레이어가 그대로 JSON 직렬화해서 보내는 payload — 필드명을 기존
services/rag_chat SSE 계약(session_id·delta·done·citations·bogus_citations)과
하위호환되게 맞췄다. table·image는 이번에 추가하는 신규 이벤트.
"""
from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass

_TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
_NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?%?$")

# matplotlib 기본 폰트(DejaVu Sans)는 한글 글리프가 없다 — 캡션·라벨이 전부
# 한국어라(니켈/수입액 등) 못 고치면 PNG에 네모(tofu)만 찍힌다.
# 1순위: koreanize_matplotlib(NanumGothic 번들, MIT, 순수 파이썬+정적 폰트파일이라
# airgap 안전) — import 자체가 rcParams["font.family"]를 설정해준다(2026-08-13
# 실측: 이 dev 환경에 이미 설치돼 있어 바로 동작 확인, requirements.txt에도 추가).
# 2순위(그 패키지가 없는 환경 대비): 시스템에 설치된 CJK 폰트를 fontconfig로 탐색.
# 둘 다 없으면 조용히 기본 폰트로 진행(네모 글리프 감수 — 이 함수만으로는 못
# 고치는 인프라 문제).
_KOREAN_FONT_CANDIDATES = (
    "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", "Malgun Gothic", "AppleGothic",
)
_korean_font_checked = False


def _apply_korean_font() -> None:
    global _korean_font_checked
    if _korean_font_checked:
        return
    _korean_font_checked = True
    try:
        import koreanize_matplotlib  # noqa: F401 — import 자체가 font.family를 설정

        return
    except ImportError:
        pass

    import matplotlib
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _KOREAN_FONT_CANDIDATES:
        if name in available:
            matplotlib.rcParams["font.family"] = name
            return


@dataclass(frozen=True)
class ChatEvent:
    """type: session|delta|table|image|chart|done. sse_name은 SSE `event:` 필드에
    쓸 이름(None이면 무명 기본 이벤트 — 기존 계약에서 session/delta가 그랬다).
    `chart`(2026-09-13 신설)는 private 프로필 전용 — PNG 대신 프론트가 직접
    그릴 선언적 차트 스펙(`chart_spec()` 참고)."""

    type: str
    data: dict

    @property
    def sse_name(self) -> str | None:
        return None if self.type in ("session", "delta") else self.type


def extract_markdown_tables(text: str) -> list[dict]:
    """GFM 스타일 표(`| a | b |` + `| --- | --- |` 구분선)를 파싱해
    [{"columns": [...], "rows": [[...], ...]}] 로 돌려준다.

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
            # `markdown`(2026-09-13 신설) — 원문 조각. private 블록 이벤트를 받는
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
_DATE_COLUMN_NAMES = {"crtr_ymd", "crtr_yr"}


def _is_date_column(header: str) -> bool:
    """정확히 일치("crtr_ymd")하거나, 컬럼 라벨이 붙은 형태("crtr_ymd(기준일자)",
    2026-09-07 — evidence.py::from_komis_raw가 Postgres COMMENT ON COLUMN을
    표 헤더에 같이 보여주기 시작하면서 헤더가 순수 컬럼명이 아닐 수 있게
    됐다)로 시작하면 날짜열로 본다."""

    normalized = header.strip().lower()
    return any(
        normalized == name or normalized.startswith(f"{name}(") for name in _DATE_COLUMN_NAMES
    )


def _numeric_series(rows: list[list[str]], col_idx: int) -> list[float] | None:
    """col_idx 열의 모든 셀이 숫자(콤마·% 허용)로 읽히면 float 리스트, 하나라도
    아니면 None(그 열은 차트 후보에서 제외 — 범주형 라벨 열을 숫자로 억지로
    해석하지 않는다)."""

    values = []
    for row in rows:
        raw = row[col_idx].strip()
        if not _NUM_RE.match(raw):
            return None
        values.append(float(raw.replace(",", "").replace("%", "")))
    return values


def render_chart_png(table: dict) -> tuple[bytes, str] | None:
    """표의 완전 숫자열 **전부**를 한 차트에 겹쳐 그리고 범례로 구분한다
    (2026-09-03 변경 — 예전엔 처음 만나는 숫자열 하나만 그려서, 니켈 가격표
    처럼 최저가·최고가·선물가격이 나란히 있어도 최저가만 보이고 나머지는
    표에만 남았다. 사용자 지적으로 다중 계열 지원). 숫자열이 하나도 없으면
    None(표 이벤트만 보내고 차트는 만들지 않는다 — 강제로 억지 차트를 그리지
    않는게 원칙, 근거 없는 시각화가 오히려 오해를 부른다). 행이 4개 이상이면
    추이로 보고 선그래프(계열별 겹쳐그리기), 그보다 적으면 막대그래프(계열별
    묶음막대).

    X축 라벨은 날짜열(crtr_ymd/crtr_yr, 위치 무관)이 있으면 그걸 최우선 —
    없으면 기존대로 첫 번째 열을 쓴다(국가·광종명 등 범주형 첫 열이 라벨로
    맞는 표가 더 많다). **날짜열일 때만** 과거→최근 오름차순으로 재정렬한다
    (KOMIS 원본은 최신순으로 내려오는 경우가 많아 차트가 거꾸로 읽혔다,
    사용자 지적) — 날짜가 아닌 라벨(랭킹 순위 등)은 원본 순서가 이미 의미가
    있어 재정렬하지 않는다.

    matplotlib은 이 함수를 실제로 쓸 때만 임포트한다(차트 후보가 없는 대다수
    턴에서는 무거운 임포트 비용을 안 치르게)."""

    columns, rows = table["columns"], table["rows"]
    if len(rows) < 2 or len(columns) < 2:
        return None
    label_idx = next((i for i, c in enumerate(columns) if _is_date_column(c)), 0)
    is_date_axis = _is_date_column(columns[label_idx])

    series_list: list[tuple[str, list[float]]] = []
    for idx in range(len(columns)):
        if idx == label_idx or _is_date_column(columns[idx]):
            continue
        series = _numeric_series(rows, idx)
        # 값이 전부 같으면(예: mnrl_prc_crtr_sn처럼 조회 전체에 걸쳐 고정된
        # 식별자 열) 정보량이 0인 평평한 선이라 후보에서 뺀다 — 여러 행에
        # 걸쳐 값이 갈리는 진짜 수치열(가격 등)만 그린다.
        if series is None or len(set(series)) <= 1:
            continue
        series_list.append((columns[idx], series))
    if not series_list:
        return None

    labels = [row[label_idx] for row in rows]
    if is_date_axis:
        order = sorted(range(len(labels)), key=lambda i: labels[i])
        labels = [labels[i] for i in order]
        series_list = [(name, [values[i] for i in order]) for name, values in series_list]

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matplotlib.rcParams["axes.unicode_minus"] = False
    _apply_korean_font()

    fig, ax = plt.subplots(figsize=(6, 3.2))
    if len(rows) >= 4:
        for name, values in series_list:
            ax.plot(labels, values, marker="o", label=name)
    else:
        x = range(len(labels))
        n = len(series_list)
        width = 0.8 / n
        for i, (name, values) in enumerate(series_list):
            offsets = [xi + (i - (n - 1) / 2) * width for xi in x]
            ax.bar(offsets, values, width=width, label=name)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
    caption = " · ".join(name for name, _ in series_list)
    ax.set_title(caption)
    if len(series_list) > 1:
        ax.legend(fontsize="small")
    ax.tick_params(axis="x", labelrotation=30)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue(), caption


def png_to_data_uri_payload(png_bytes: bytes, caption: str, source_index: int | None = None) -> dict:
    """image 이벤트 payload — 프론트가 바로 `data:image/png;base64,...`로 붙여
    쓸 수 있게 mime+base64를 분리해서 준다."""

    return {
        "mime": "image/png",
        "data_base64": base64.b64encode(png_bytes).decode("ascii"),
        "caption": caption,
        "source_index": source_index,
    }


# ---- private 프로필 전용 구조화 블록(2026-09-13, 사용자 지시) ----------------
#: 표·차트를 그리는 주체는 챗봇이 아니라 프론트여야 한다는 원칙으로, PNG 대신
#: "데이터 + 표현 힌트"를 준다. 우선 /prichat에만 적용하고 프론트가 쓰기 좋으면
#: /pubchat에도 넓힌다. 블록 형태는 콘텐츠 블록 패턴(타입별 객체 + schema_version)
#: — `<json></json>` 같은 HTML 태그를 마크다운에 끼우는 방식은 렌더러 sanitize·
#: SSE 청크 분절 문제로 채택하지 않았다.
BLOCK_SCHEMA_VERSION = 1


def _column_types(table: dict) -> list[dict]:
    """헤더마다 {key, label, type(date|number|string), unit(%|None)}. 판정 규칙은
    render_chart_png와 동일(_is_date_column·_numeric_series)이라 차트 스펙과
    표 타입이 어긋나지 않는다."""

    columns, rows = table["columns"], table["rows"]
    out = []
    for idx, header in enumerate(columns):
        key = header.split("(", 1)[0].strip() or f"col{idx}"
        if _is_date_column(header):
            ctype, unit = "date", None
        elif _numeric_series(rows, idx) is not None:
            ctype = "number"
            unit = "%" if rows and all(r[idx].strip().endswith("%") for r in rows) else None
        else:
            ctype, unit = "string", None
        out.append({"key": key, "label": header, "type": ctype, "unit": unit})
    return out


def table_block(table: dict, *, block_id: str, source_index: int | None, source_label: str | None) -> dict:
    """private `table` 이벤트 payload. 기존 키(columns·rows·source_index·source)는
    그대로 두고(구 클라이언트 호환) 구조화 필드를 덧붙인다."""

    columns_meta = _column_types(table)
    typed_rows = []
    for row in table["rows"]:
        typed = []
        for cell, meta in zip(row, columns_meta):
            if meta["type"] == "number":
                typed.append(float(cell.strip().replace(",", "").replace("%", "")))
            else:
                typed.append(cell)
        typed_rows.append(typed)
    return {
        "schema_version": BLOCK_SCHEMA_VERSION,
        "block_id": block_id,
        "columns": table["columns"],
        "rows": table["rows"],
        "columns_meta": columns_meta,
        "rows_typed": typed_rows,
        "markdown": table.get("markdown"),
        "meta": {"source_index": source_index, "source": source_label, "row_count": len(table["rows"])},
        "source_index": source_index,
        "source": source_label,
    }


def chart_spec(table: dict, *, block_id: str, data_ref: str, source_index: int | None, source_label: str | None) -> dict | None:
    """private `chart` 이벤트 payload — render_chart_png와 같은 판정(숫자열 전부,
    값이 전부 같은 열 제외, 날짜열 우선 X축, 4행 이상이면 line 아니면 bar,
    날짜축이면 오름차순 정렬)을 PNG 대신 선언적 스펙으로 낸다. 그릴 계열이
    없으면 None(억지 차트 금지 원칙 동일)."""

    columns, rows = table["columns"], table["rows"]
    if len(rows) < 2 or len(columns) < 2:
        return None
    columns_meta = _column_types(table)
    label_idx = next((i for i, c in enumerate(columns) if _is_date_column(c)), 0)
    is_date_axis = _is_date_column(columns[label_idx])
    series_keys = []
    for idx in range(len(columns)):
        if idx == label_idx or _is_date_column(columns[idx]):
            continue
        series = _numeric_series(rows, idx)
        if series is None or len(set(series)) <= 1:
            continue
        series_keys.append(columns_meta[idx]["key"])
    if not series_keys:
        return None
    return {
        "schema_version": BLOCK_SCHEMA_VERSION,
        "block_id": block_id,
        "data_ref": data_ref,
        "spec": {
            "kind": "line" if len(rows) >= 4 else "bar",
            "x": columns_meta[label_idx]["key"],
            "x_type": "date" if is_date_axis else "category",
            "series": series_keys,
            "sort_x_ascending": is_date_axis,
            "title": " · ".join(series_keys),
        },
        "meta": {"source_index": source_index, "source": source_label},
        "source_index": source_index,
        "source": source_label,
    }
