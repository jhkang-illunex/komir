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
    """type: session|delta|table|image|done. sse_name은 SSE `event:` 필드에 쓸
    이름(None이면 무명 기본 이벤트 — 기존 계약에서 session/delta가 그랬다)."""

    type: str
    data: dict

    @property
    def sse_name(self) -> str | None:
        return None if self.type in ("session", "delta") else self.type


def extract_markdown_tables(text: str) -> list[dict]:
    """GFM 스타일 표(`| a | b |` + `| --- | --- |` 구분선)를 파싱해
    [{"columns": [...], "rows": [[...], ...]}] 로 돌려준다.

    rag/ragkit/ingest.py가 docx·opendataloader-pdf 산출물을 마크다운으로 펼쳐서
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
            tables.append({"columns": columns, "rows": rows})
        i = j
    return tables


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
    """표에서 첫 번째 완전 숫자열을 찾아 즉석 차트(PNG bytes, 캡션)로 렌더링한다.
    숫자열이 하나도 없으면 None(표 이벤트만 보내고 차트는 만들지 않는다 — 강제로
    억지 차트를 그리지 않는게 원칙, 근거 없는 시각화가 오히려 오해를 부른다).
    행이 4개 이상이면 추이로 보고 선그래프, 그보다 적으면 막대그래프.

    matplotlib은 이 함수를 실제로 쓸 때만 임포트한다(차트 후보가 없는 대다수
    턴에서는 무거운 임포트 비용을 안 치르게)."""

    columns, rows = table["columns"], table["rows"]
    if len(rows) < 2 or len(columns) < 2:
        return None
    for idx in range(1, len(columns)):
        series = _numeric_series(rows, idx)
        if series is None:
            continue
        labels = [row[0] for row in rows]

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        matplotlib.rcParams["axes.unicode_minus"] = False
        _apply_korean_font()

        fig, ax = plt.subplots(figsize=(6, 3.2))
        if len(rows) >= 4:
            ax.plot(labels, series, marker="o")
        else:
            ax.bar(labels, series)
        ax.set_title(columns[idx])
        ax.tick_params(axis="x", labelrotation=30)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110)
        plt.close(fig)
        return buf.getvalue(), columns[idx]
    return None


def png_to_data_uri_payload(png_bytes: bytes, caption: str, source_index: int | None = None) -> dict:
    """image 이벤트 payload — 프론트가 바로 `data:image/png;base64,...`로 붙여
    쓸 수 있게 mime+base64를 분리해서 준다."""

    return {
        "mime": "image/png",
        "data_base64": base64.b64encode(png_bytes).decode("ascii"),
        "caption": caption,
        "source_index": source_index,
    }
