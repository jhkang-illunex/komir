# -*- coding: utf-8 -*-
"""정형(structured)·dense(pgvector)·PageIndex 세 검색 도구의 공통 근거 계약.

`인수인계서_TODO_대조_260813.md`(documents/산출물/2026-W33_0810-0816/) §1-2 —
"DB/VDB 결과를 공통 근거 계약(단위·기준시점·출처)으로 통일" 항목에 대한 구현.
세 도구(structured.py/dense_pg.py/pageindex.py)가 각각 다른 모양을 반환해
rag/ragkit/chatbot_graph.py가 그대로는 하나의 인용 프롬프트에 섞어 넣을 수
없었다 — 이 모듈이 그 통일 지점이다. 각 도구의 원본 결과를 `Evidence`로
변환하는 어댑터 함수만 두고, 조회 로직 자체(structured.py/dense_pg.py/
pageindex.py)는 건드리지 않는다(재구현 금지).

`text`는 항상 사람이 읽는 근거 발췌문 — 구조화 결과(다건)는 마크다운 표로
렌더링해 넣는다. 이렇게 하면 rag/ragkit/chatbot_events.py의 표·차트 추출
(GFM 파싱)이 kind에 상관없이 동일하게 동작한다(structured/dense/pageindex를
구분하는 별도 분기가 필요 없다 — 오히려 structured 결과가 markdown 스크래핑
결과보다 완전한 숫자열이라 차트 재료로 더 낫다)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Evidence:
    """인용 프롬프트 [n]번 근거 1건. 몇 번인지(index)는 각 도구가 아니라
    chatbot_graph가 병합한 뒤에 매긴다."""

    kind: str  # "structured" | "dense" | "pageindex"
    source: str  # 출처 표시(파일 경로 / 템플릿명 / 문서 제목)
    section: str  # 섹션·템플릿 세부·노드 제목
    text: str  # 근거 발췌문(구조화 결과는 마크다운 표로 렌더링됨)
    as_of: str | None = None  # 기준시점(있으면)
    unit: str | None = None  # 단위(있으면)


def _forecast_month_label(base_date: Any, horizon: Any) -> str:
    """base_date(예: 2025-12-01) + horizon개월 → "2026-01" 같은 연월 라벨.

    base_date나 horizon이 없으면(방어적) horizon 원값을 그대로 문자열화 —
    표가 비거나 깨지는 것보다는 옛 동작(숫자만 표시)으로 물러나는 쪽이 낫다."""

    if base_date is None or horizon is None:
        return str(horizon)
    try:
        offset = int(horizon)
        zero_based_month = base_date.month - 1 + offset
        year = base_date.year + zero_based_month // 12
        month = zero_based_month % 12 + 1
        return f"{year:04d}-{month:02d}"
    except (TypeError, ValueError, AttributeError):
        return str(horizon)


def _markdown_table(columns: list[str], rows: list[list[str]]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join([header, sep, body])


def from_structured(template: str, commodity_code: str, result: Any) -> Evidence | None:
    """`shared.retrieval.structured`의 템플릿 함수 반환값(dict 1건 또는
    list[dict])을 Evidence로 변환한다.

    result가 비어 있으면(해당 광종에 데이터가 없음 — public.KO_* 텅스텐-only
    같은 공백이 실제로 있다, WORKLOG 2026-08-13 참고) None을 돌려준다 — "정형
    데이터 없음"을 억지 텍스트로 채우지 않고, 호출자가 그냥 건너뛴다."""

    source = f"정형데이터 · {template}({commodity_code})"

    if template == "latest_diagnosis":
        if not result:
            return None
        row = result
        text = (
            f"{commodity_code} 최근 수급위기 진단 등급: {row.get('alert_level')} "
            f"(위험점수 {row.get('risk_score')}, 사유: {row.get('reason')})"
        )
        return Evidence(
            kind="structured", source=source, section="수급위기 진단 경보", text=text,
            as_of=str(row.get("obs_date") or "") or None,
        )

    if template == "import_forecast":
        rows = result or []
        if not rows:
            return None
        is_volume = rows[0].get("target") == "volume"
        base_date = rows[0].get("base_date")
        # 2026-08-27: 기존엔 horizon(1~12, "개월 후")만 행 라벨이었다 — 몇 년 몇 월을
        # 가리키는지가 표·차트(첫 컬럼을 그대로 x축 라벨로 쓴다, chatbot_events.py::
        # render_chart_png)에 안 보여 사용자가 "날짜가 애매하다"고 지적했다. base_date
        # 기준월 자체는 Evidence.as_of 에만 있어 표만 봐서는 알 수 없었던 것 — 실제
        # 예측 대상월(base_date + horizon개월)을 행 라벨로 계산해 넣는다.
        columns = ["예측월", "yhat", "yhat_lo", "yhat_hi"]
        table_rows = [
            [
                _forecast_month_label(base_date, r.get("horizon")),
                str(r.get("yhat")), str(r.get("yhat_lo")), str(r.get("yhat_hi")),
            ]
            for r in rows
        ]
        section = f"{len(rows)}개월 수입{'물량' if is_volume else '금액'} 예측"
        text = f"{section}(기준월 {base_date} 기준 향후 예측)\n\n{_markdown_table(columns, table_rows)}"
        return Evidence(
            kind="structured", source=source, section=section, text=text,
            as_of=str(rows[0].get("base_date") or "") or None,
            unit="물량(톤)" if is_volume else "금액(천USD)",
        )

    if template == "geo_index_trend":
        rows = result or []
        if not rows:
            return None
        columns = ["period", "idx_value", "n_events"]
        table_rows = [[str(r.get("period")), str(r.get("idx_value")), str(r.get("n_events"))] for r in rows]
        section = f"지정학 위기지수 추이({rows[0].get('freq')}, 오래된순)"
        text = f"{section}\n\n{_markdown_table(columns, table_rows)}"
        return Evidence(
            kind="structured", source=source, section=section, text=text,
            as_of=str(rows[-1].get("period") or "") or None, unit="지수(0~100)",
        )

    return None


def from_dense_chunk(chunk: Any) -> Evidence:
    """`dense_pg.PgRetrievedChunk` -> Evidence."""

    return Evidence(
        kind="dense", source=chunk.source_path, section=chunk.section_heading,
        text=chunk.text, as_of=chunk.week or None,
    )


def from_pageindex_hit(hit: dict[str, Any]) -> Evidence:
    """`pageindex.search_nodes()`/`lookup()`이 낸 노드 1건(text 채워진 상태) ->
    Evidence."""

    return Evidence(
        kind="pageindex", source=hit.get("doc_title") or hit.get("okf_path", ""),
        section=hit.get("node_path") or hit.get("title", ""),
        text=hit.get("text", ""),
    )
