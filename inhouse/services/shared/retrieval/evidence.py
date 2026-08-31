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
    # 2026-08-31(komis_raw_lookup 신설) — 이 근거가 실제로 인용됐을 때 생성
    # 텍스트와 무관하게 코드가 강제로 덧붙여야 하는 경고(예: "개발용 더미
    # 데이터"). LLM이 [근거] 텍스트를 읽고 스스로 이 사실을 문장으로 옮겨
    # 적는다는 보장이 없고(_strip_uncited_sentences가 인용 없는 문장은
    # 지워버림), 안전에 직결되는 경고라 chatbot.py가 인용 스트리퍼 통과
    # 이후 코드로 무조건 붙인다(_caution_notice·_source_footer와 같은 원칙).
    caveat: str | None = None


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
        # 2026-08-28(챗봇_룰준수_감사_260828.md §7) — 원래 라벨이 "사유:"였다.
        # 챗봇(rag/ragkit/chatbot.py)은 [근거] 발췌문을 그대로 인용하도록
        # 강제되어 있어("오직 [근거] 섹션에만 근거", CHATBOT_SYSTEM_PROMPT
        # 규칙1) 이 라벨을 그대로 옮겨 답하는데, chatbot_rule.txt 유형5
        # 유의사항("인과 단정 금지, 동시 발생 흐름으로 서술")과 충돌한다 —
        # "사유"는 단정적 인과 표현이라, 실측(위 감사 §7)에서 "사유:
        # 국제 핵심광물 시장의 가격 변동성 급증"처럼 인과관계를 확정하는
        # 문장으로 그대로 노출됐다. 실제로는 진단모델의 risk_score 기여
        # 요인 중 상위 항목일 뿐이므로 라벨을 순화한다(수치·의미는 그대로,
        # 표현만 변경 — row.get('reason')이 담는 값 자체는 msr 진단 모델
        # 소관이라 건드리지 않음).
        text = (
            f"{commodity_code} 최근 수급위기 진단 등급: {row.get('alert_level')} "
            f"(위험점수 {row.get('risk_score')}, 주요 변동 요인: {row.get('reason')})"
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


#: komis_raw_lookup이 실제 KOMIS 표본이 아닐 때 인용 근거에 강제로 붙이는
#: 경고 문구(Evidence.caveat) — chatbot.py가 코드로 이 문구를 답변에 덧붙인다.
KOMIS_RAW_DUMMY_CAVEAT = "이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다."


def from_komis_raw(
    page_id: str, datasets: list[Any], *, mineral_code: str | None = None, is_dummy: bool | None = None,
) -> list[Evidence]:
    """`komis_raw.KomisRawDataRepository.fetch()`가 돌려준 RawDataset 목록
    (page_id당 원천 테이블 1~2개, 예: map_mineral은 매장량+생산량 2개) ->
    Evidence 목록(테이블당 1건). 다른 from_* 어댑터와 달리 이건 komir가 계산한
    결과가 아니라 KOMIS 원천(public.KO_*) 원자료를 그대로 표로 옮기는
    패스스루다 — 해석·가공 없음.

    2026-08-31: 발주 5광종의 `ko_*` 데이터가 대부분 개발용 더미(DEV_DUMMY)로
    확인되어(스키마매핑 문서 참고), 더미 여부는 호출측(MCP tool)이
    `komis_raw.resolve_data_source()`로 미리 확인해 `is_dummy`로 넘긴다 —
    True면 모든 Evidence에 `caveat`(KOMIS_RAW_DUMMY_CAVEAT)을 심어서, 이
    근거가 실제로 인용되면 chatbot.py가 그 사실을 코드로 강제 경고하게 한다
    (LLM이 [근거] 텍스트만 보고 알아서 옮겨 적을 거라 기대하지 않는다 —
    인용 스트리퍼가 근거 없는 문장은 지운다)."""

    evidence: list[Evidence] = []
    for ds in datasets:
        if not ds.rows:
            continue
        columns = ds.columns
        table_rows = [[str(row.get(c, "")) for c in columns] for row in ds.rows]
        suffix = f"({mineral_code})" if mineral_code else ""
        section = f"KOMIS 원천 · {ds.source_table}{suffix}"
        evidence.append(
            Evidence(
                kind="structured", source=f"public.{ds.source_table}", section=section,
                text=_markdown_table(columns, table_rows),
                caveat=KOMIS_RAW_DUMMY_CAVEAT if is_dummy else None,
            )
        )
    return evidence
