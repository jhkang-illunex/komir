# -*- coding: utf-8 -*-
"""public/private MCP 서버 두 파일이 공유하는 tool 6개 — 정형 3종(structured
산출물, 라이선스 이슈 없음)·komis_raw_lookup·komis_resolve_mineral(KOMIS
공개원천 public.KO_*, 2026-08-31/09-01 추가)·pageindex_agentic(USGS 코퍼스만
스캔, Argus를 애초에 안 건드림)은 여기 한 번만 구현하고 두 서버 파일이 그대로
등록만 한다(재구현 금지).

다섯(정형 3종·komis_resolve_mineral·pageindex_agentic)은 타 팀 소유이거나
라이선스 제한 콘텐츠(Argus)가 아니라 public/private 결과가 완전히 같다
(2026-08-26 smoke_mcp_access.py 실측 확인). **komis_raw_lookup만 예외**다 —
2026-09-01 사용자 지시로 `page_id` 11개 중 `indicator_market`(시장동향지표)·
`indicator_supply`(수급동향지표)·`indicator_composite`(광물종합지수) 3개는
private 프로필 전용이 됐다(`shared.retrieval.access.PRIVATE_ONLY_KOMIS_PAGES`,
`indicator_composite`는 같은 날 사용자 정정으로 뒤늦게 추가됨). `register_common_tools()`가
호출자로부터 `private_only_pages`를 받아 komis_raw_lookup 안에서 검사한다 —
hybrid_search·pageindex_lookup처럼 서버 파일 자체를 물리적으로 나누지 않은
이유는 이 도구가 다단계 번역 로직(가격기준/HS코드 자동매핑, 150줄)을 갖고
있어 파일을 통째로 복제하면 그 로직이 두 곳에서 갈라질 위험이 더 커서다 —
대신 `private_only_pages` 인자는 **호출 시점에 각 서버 파일이 소스코드로
직접 박아 넣는 값**이라(런타임 env var 아님) 신뢰 경계는 여전히 "어느 파일을
실행했는가"에 있다(mcp_server_public.py만 이 상수를 넘긴다, private.py는
아예 import하지 않고 기본값 빈 집합 그대로 쓴다).

**라이선스 제한 소스(Argus)가 갈리는 hybrid_search·pageindex_lookup 두
도구는 여기 없다** — 그 둘은 `mcp_server_public.py`/`mcp_server_private.py`
각자 파일에 직접 쓴다(공유 함수·런타임 플래그 없이). 처음엔 이 넷과 같은
방식으로 `MCP_PROFILE` 환경변수 하나로 단일 파일에서 분기했었는데, 사용자
요청(2026-08-26)으로 "코드 자체가 물리적으로 분리"되도록 바꿨다 — 그
방식은 서버 프로세스가 여전히 "Argus를 안 거르고 조회하는 코드 경로"를
소스상 담고 있고 런타임 값(env var) 하나가 그걸 막는 구조라, env 전달이
깨지거나(오탈자·오케스트레이터가 커스텀 env를 지운다거나) 미래에 실수로
플래그를 잘못 넘기면 public 프로세스가 조용히 private처럼 동작할 여지가
있었다. 지금은 `mcp_server_public.py`를 처음부터 끝까지 읽어도 Argus를
포함시키는 코드 자체가 존재하지 않는다 — 신뢰 경계가 "런타임 플래그가
항상 올바름"에서 "어느 파일을 실행했는가"로 옮겨갔다."""
from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from pydantic import ValidationError

from common.config import get_settings
from common.komis_raw import (
    AnalysisPreviewPageId,
    AnalysisPreviewRequest,
    KomisRawDataRepository,
    RawDataAccessError,
    RawDataset,
)
from common.llm_client import KomirJsonLLM
from common import structured
from rag_core.retrieval import pageindex_agent
from rag_core.retrieval.evidence import Evidence, from_komis_raw, from_komis_ranking, from_komis_aggregate, from_structured


def _evidence_dict(ev: Evidence | None) -> dict[str, Any] | None:
    return dataclasses.asdict(ev) if ev is not None else None


# 2026-08-31 skeptic 발견(advisor) — komis_raw._PAGE_DATASETS의 price_* 4종은
# filter_columns에 mineral_code가 없다(price_criterion_serial만 있음). map_korea도
# hs_code만 있고, map_global의 mineral_code 컬럼(MNRKND_UNQ_CD)은 실측상 전 행
# NULL이라 사실상 죽은 필터다(komis_raw.py 자체 주석 참고). 그냥 mineral_code를
# AnalysisPreviewRequest에 실어 보내면 이 6개 page_id에선 **조용히 무시**되고
# WHERE 절 없이(또는 hs_code 없이) 최신 N행이 그대로 나온다 — 그 최신 N행이
# 지금은 전부 5광종 개발용 더미라, "텅스텐을 요청했는데 더미가 텅스텐인 것처럼
# 나오고 더미 경고도 안 붙는" 최악의 조합이 실제로 재현됐다(실측 확인). 그래서
# komis_raw_lookup은 이 페이지들에 한해 mineral_code를 매핑 테이블
# (ai_prc_mnrl_map/ai_hs_mnrl_map)로 먼저 실제 필터값으로 번역한 뒤 조회한다.
_PRICE_PAGES = frozenset({"price_base_metals", "price_minor_metals", "price_iron_energy", "price_other"})
_HS_TRANSLATE_PAGES = frozenset({"map_korea", "map_global"})

#: 2026-09-07("니켈 최근 6개월 가격" 사용자 제보 후속) — start_period·
#: end_period가 둘 다 있으면 그 범위 전체를 봐야 "추이" 질문에 답이 되는데,
#: 일별 가격(~130행)도 다 못 온다. 기간이 명시된 조회는 `fetch_complete()`로
#: 범위 내 모든 행을 반환한다. 기간이 없는 조회만
#: `Settings.KOMIS_RAW_MAX_TIMESTAMPS`(기본 60) 이하로 제한한다.

#: 2026-09-07 — komis_raw_lookup이 0건을 받았는데 `_PERIOD_BOUNDS_LEAD`
#: 대상 page_id가 아니거나(예: price_forecast는 텅스텐 외 광종은 원본 테이블
#: 자체에 행이 없다) 가용기간 계산이 안 되면, 이 마커 하나만 붙인다 — "이
#: 광종만 지원합니다" 류의 근거 없는 주장을 만들지 않는다(사용자 지시).
#: chatbot_graph.py::_has_deterministic_abstain_signal·chatbot.py::
#: _resolve_abstain이 이 문자열을 그대로 찾는다(값이 바뀌면 세 곳 다 같이).
_NO_DATA_FOUND_MARKER = "조회하신 조건에 해당하는 데이터를 찾지 못했습니다."

#: 2026-09-03(발주처 문서 대화형검색시스템 예상질문 고도화.pdf ②-1·②-3·④-나,
#: 사용자 승인 — "3곳 전부 한번에") — 0건 조회 시 "조회 가능 기간은
#: YYYY.MM.DD~YYYY.MM.DD입니다"류 안내에 쓸 실제 범위를 붙이는 대상 page_id와
#: 그 안내 문구의 선행절. 문서가 딱 이 두 갈래만 예시로 들었다(가격=일단위
#: "조회 가능 기간", 지표=월단위 "지표 산출 가능 기간") — 교역(map_korea 등,
#: "기간을 다시 지정해 주십시오"만 요구)·매장량/생산량(기간 언급 자체 없음)
#: 은 문서에 근거가 없어 이번 스코프에 안 넣었다(과잉 확장 금지).
_PERIOD_BOUNDS_LEAD: dict[str, str] = {
    "price_base_metals": "조회 가능 기간",
    "price_minor_metals": "조회 가능 기간",
    "price_iron_energy": "조회 가능 기간",
    "price_other": "조회 가능 기간",
    "indicator_market": "지표 산출 가능 기간",
    "indicator_supply": "지표 산출 가능 기간",
}


def _format_period_bound(value: str, precision: str) -> str:
    if precision == "day" and len(value) >= 8:
        return f"{value[:4]}.{value[4:6]}.{value[6:8]}"
    if len(value) >= 6:
        return f"{value[:4]}.{value[4:6]}"
    return value[:4]


def register_common_tools(mcp: FastMCP, *, private_only_pages: frozenset[str] = frozenset()) -> None:
    """호출자(mcp_server_public.py·mcp_server_private.py)가 자기 `FastMCP`
    인스턴스를 넘겨 이 6개 tool을 등록한다. `private_only_pages`는
    komis_raw_lookup에서 거부할 `page_id` 집합 — public.py만 소스코드로
    `PRIVATE_ONLY_KOMIS_PAGES`를 박아 넣어 넘기고, private.py는 기본값(빈
    집합=제한 없음) 그대로 둔다. 모든 tool은 top-level에서 항상
    `dict[str, Any]`(Optional도 list도 아닌 순수 object)를 반환한다 — FastMCP가
    반환 타입이 이미 object 스키마면 `structuredContent`에 그대로 싣고,
    `dict | None`/`list[...]`처럼 top-level이 object가 아니면 `{"result": ...}`
    로 감싸는 걸 실측으로 확인했기 때문(`mcp_client.py`가 도구마다 다른 언랩
    로직 없이 `structuredContent`를 그대로 쓰게 하려는 것)."""

    # 2026-09-08 — 서버 기동 시(이 함수가 호출되는 시점) 한 번만 읽는다.
    # 기간 미지정 조회의 최대 행 수에만 이 값을 쓴다.
    _max_timestamps = get_settings().KOMIS_RAW_MAX_TIMESTAMPS

    @mcp.tool()
    def latest_diagnosis(commodity_code: str) -> dict[str, Any]:
        """{commodity_code} 최근 수급위기 진단 등급 1건 — {"evidence": {...}|null}."""

        result = structured.latest_diagnosis(commodity_code)
        return {"evidence": _evidence_dict(from_structured("latest_diagnosis", commodity_code, result))}

    @mcp.tool()
    def import_forecast(
        commodity_code: str, target: str = "volume", horizon: int | None = None
    ) -> dict[str, Any]:
        """{commodity_code} 수입물량/금액 예측(target: volume|value) — horizon을
        지정하면 1~horizon개월치만, 생략하면 12개월 전체. {"evidence": {...}|null}."""

        result = structured.import_forecast(commodity_code, target, horizon)
        return {"evidence": _evidence_dict(from_structured("import_forecast", commodity_code, result))}

    @mcp.tool()
    def geo_index_trend(commodity_code: str, freq: str = "W", limit: int = 8) -> dict[str, Any]:
        """{commodity_code} 최근 지정학 위기지수 추이(오래된 순 limit개) —
        {"evidence": {...}|null}."""

        result = structured.geo_index_trend(commodity_code, freq, limit)
        return {"evidence": _evidence_dict(from_structured("geo_index_trend", commodity_code, result))}

    @mcp.tool()
    def pageindex_agentic(query: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """PageIndex 에이전틱 국가별 세계생산 조회(USGS 코퍼스만 스캔 — Argus를
        애초에 안 건드리므로 public/private 결과가 같다). 그래프의 route/verify
        LLM 인스턴스를 그대로 못 넘기므로 이 서버가 자체 KomirJsonLLM을 env로
        새로 만든다."""

        evidence, warnings = pageindex_agent.agentic_lookup(query, history=history or [], llm=KomirJsonLLM())
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    @mcp.tool()
    def komis_resolve_mineral(korean_name: str) -> dict[str, Any]:
        """한글 광종명(질문에 쓰인 표현 그대로, 예: "텅스텐")을 `ai_mnrl_mst`에서
        조회해 KOMIS 광종코드(`mineral_code`, komis_raw_lookup에 그대로 넘기면
        됨)와 가격 서브메뉴 분류(`price_category`, HP001~004)를 돌려준다.
        2026-09-01 신설 — 발주 5광종으로 하드코딩하지 않고 `ai_mnrl_mst`를
        직접 조회해서, KOMIS가 광종을 추가로 등록해도 코드 수정 없이 그대로
        반영된다. 못 찾으면 `mineral_code: null`(아직 KOMIS에 등록 안 됐거나
        철자가 다른 경우 — warnings에 안내). {"mineral_code": str|null,
        "price_category": str|null, "warnings": [...]}."""

        repo = KomisRawDataRepository()
        try:
            resolved = repo.resolve_mineral_full(korean_name)
        except RawDataAccessError as exc:
            return {"mineral_code": None, "price_category": None, "warnings": [str(exc)]}
        if resolved is None:
            return {
                "mineral_code": None, "price_category": None,
                "warnings": [f"'{korean_name}'을(를) KOMIS 광종 목록(ai_mnrl_mst)에서 찾지 못했습니다."],
            }
        mineral_code, price_category = resolved
        return {"mineral_code": mineral_code, "price_category": price_category, "warnings": []}

    @mcp.tool()
    def komis_raw_lookup(
        page_id: AnalysisPreviewPageId,
        mineral_code: str | None = None,
        hs_code: str | None = None,
        index_type_code: str | None = None,
        price_criterion_serial: int | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        limit: int = _max_timestamps,
    ) -> dict[str, Any]:
        """KOMIS 공개원천(public.KO_*, 타 팀 소유·읽기전용) 정형 데이터 조회 —
        가격(price_*)·교역(map_korea/map_global)·매장량·생산량(map_mineral)·
        종합지수/시장전망/수급안정(indicator_*)·가격예측(forecast_price) 11개
        page_id별로 정해진 테이블만 조회한다. 자유형 SQL을 생성하지 않는다 —
        page_id가 고르는 건 코드에 고정된 정적 스펙(테이블·컬럼)뿐이고, 필터
        값은 화이트리스트 정규식(영문자·숫자·`_`만)을 통과해야 SQL에 들어간다
        (komis_raw.py 참고). `mineral_code`는 `MNRL0008`처럼 `ai_mnrl_mst`의
        숫자코드를 써야 한다(`CU`/`NI` 같은 약어 코드는 아직 미사용).

        ⚠ 2026-08-31 실측(스키마매핑 문서 참고): 발주 5광종(CU/NI/CO/LI/REE)의
        `ko_*` 데이터는 절반 가까이 아예 0건이고, 나머지도 대부분 개발용
        더미(DEV_DUMMY)다 — 실제 KOMIS 표본은 텅스텐(MNRL0018) 하나뿐이다.
        `mineral_code`를 주면 `ai_mnrl_mst.ko_data_src_cd`를 확인해 `KOMIS_SAMPLE`이
        아니면 `warnings`에 명시한다 — 호출자(챗봇)는 이 경고가 있으면 반드시
        "개발용 더미 데이터"임을 밝히고 실제 수치인 것처럼 답하면 안 된다.

        `page_id`가 price_*·map_korea·map_global 중 하나면 `mineral_code`는
        테이블에 직접 없어(가격기준일련번호·HS코드로만 연결) `ai_prc_mnrl_map`/
        `ai_hs_mnrl_map`으로 먼저 번역해서 조회한다 — 한 광종이 여러 값에
        매핑되면 그중 첫 번째(오름차순)만 미리보기로 쓰고 `warnings`에 명시한다
        (전부 합쳐 보려면 `price_criterion_serial`/`hs_code`를 직접 지정할 것).

        ⚠ 2026-09-01 사용자 지시로 `indicator_market`(시장동향지표,
        KO_MRKT_PRSPECT_IDCT)·`indicator_supply`(수급동향지표,
        KO_SPDM_STBT_INDX)·`indicator_composite`(광물종합지수,
        KO_MNRL_SNTHS_INDX) 3개 page_id는 private 프로필 전용이다 — public
        프로필에서 호출하면 조회 없이 거부되고 warnings에만 사유가 담긴다
        (`shared.retrieval.access.PRIVATE_ONLY_KOMIS_PAGES`).

        2026-09-01 실사용 버그 발견·수정 — 근거(Evidence)의 `section`에
        `mineral_code`(예: "MNRL0018")가 그대로 노출돼 있었다. 실측으로
        재현된 실패: "텅스텐 가격 조회"가 komis_raw로 정상 라우팅·조회까지
        됐는데, 근거 section이 "KOMIS 원천 · KO_MNRL_PRC(MNRL0018)"였던 탓에
        검증(verify) LLM이 "이 근거가 텅스텐인지 알 수 없다"고 오판해 근거를
        버리고 무관한 문서로 대체했다 — 표(text) 안에는 광종명 컬럼이 아예
        없어(가격·날짜·수치뿐) MNRL 코드가 곧 "텅스텐"이라는 걸 LLM이 몰랐던
        것. 처음엔 호출자가 한글명을 별도 파라미터(`mineral_label`)로 넘기게
        고쳤는데, 그 정보가 이미 `ai_mnrl_mst`(코드↔한글명 테이블)에 있고
        `resolve_mineral()`이 그 조회를 이미 구현하고 있어 중복이었다(사용자
        지적) — 그 파라미터는 없애고, `mineral_code`가 있으면 이 tool이
        `resolve_mineral()`로 직접 한글명을 끌어와 라벨을 채운다(호출자는
        여전히 `mineral_code`만 넘기면 된다, API 단순화).
        {"evidence": [...], "warnings": [...]}."""

        if page_id in private_only_pages:
            return {
                "evidence": [],
                "warnings": [f"'{page_id}'는 private 전용 데이터입니다 — public 프로필에서는 조회할 수 없습니다."],
            }

        try:
            request = AnalysisPreviewRequest(
                page_id=page_id, mineral_code=mineral_code, hs_code=hs_code,
                index_type_code=index_type_code, price_criterion_serial=price_criterion_serial,
                start_period=start_period, end_period=end_period, limit=limit,
            )
        except ValidationError as exc:
            return {"evidence": [], "warnings": [f"요청 조건이 올바르지 않습니다: {exc}"]}

        repo = KomisRawDataRepository()
        warnings: list[str] = []

        if mineral_code and page_id in _PRICE_PAGES and price_criterion_serial is None:
            try:
                serials = repo.resolve_price_criterion_serials(mineral_code)
            except RawDataAccessError as exc:
                return {"evidence": [], "warnings": [str(exc)]}
            if not serials:
                return {
                    "evidence": [],
                    "warnings": [f"'{mineral_code}'에 대응하는 가격기준을 ai_prc_mnrl_map에서 찾지 못했습니다."],
                }
            request = request.model_copy(update={"price_criterion_serial": serials[0]})
            if len(serials) > 1:
                warnings.append(
                    f"'{mineral_code}'는 가격기준이 {len(serials)}개{serials}라 "
                    f"그중 첫 번째({serials[0]})만 미리보기로 조회했습니다."
                )
        elif mineral_code and page_id in _HS_TRANSLATE_PAGES and hs_code is None:
            try:
                hs_codes = repo.resolve_hs_codes(mineral_code)
            except RawDataAccessError as exc:
                return {"evidence": [], "warnings": [str(exc)]}
            if not hs_codes:
                return {
                    "evidence": [],
                    "warnings": [f"'{mineral_code}'에 대응하는 HS코드를 ai_hs_mnrl_map에서 찾지 못했습니다."],
                }
            request = request.model_copy(update={"hs_code": hs_codes[0]})
            if len(hs_codes) > 1:
                warnings.append(
                    f"'{mineral_code}'는 HS코드가 {len(hs_codes)}개{hs_codes}라 "
                    f"그중 첫 번째({hs_codes[0]})만 미리보기로 조회했습니다."
                )

        has_period_range = bool(request.start_period or request.end_period)
        if not has_period_range and request.limit > _max_timestamps:
            request = request.model_copy(update={"limit": _max_timestamps})
        try:
            datasets = repo.fetch_complete(request) if has_period_range else repo.fetch(request)
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [*warnings, str(exc)]}

        # 2026-09-03(발주처 문서, 사용자 승인) — price_*/indicator_market/
        # indicator_supply가 0건이면 "조회 가능 기간은 ...입니다"를 실제 DB
        # 범위로 채워 warnings에 붙인다. (2026-09-07 갱신 — 예전엔 "ROUTE_PROMPT가
        # 특정 과거기간·상대기간을 추출하는 경로가 없다"는 이유로 이 분기가
        # 사실상 안 탔는데, 이제 둘 다(komis_start/end_period 명시기간,
        # komis_relative_months 상대기간→_relative_period_bounds()) 배선돼
        # 실제로 0건 응답을 받을 수 있게 됐다.)
        if all(not ds.rows for ds in datasets):
            bounds = None
            if page_id in _PERIOD_BOUNDS_LEAD:
                try:
                    bounds = repo.resolve_period_bounds(
                        page_id, mineral_code=request.mineral_code, hs_code=request.hs_code,
                        price_criterion_serial=request.price_criterion_serial,
                        index_type_code=request.index_type_code,
                    )
                except RawDataAccessError:
                    bounds = None
            if bounds:
                start, end, precision = bounds
                warnings.append(
                    f"{_PERIOD_BOUNDS_LEAD[page_id]}은 "
                    f"{_format_period_bound(start, precision)}~{_format_period_bound(end, precision)}"
                    "입니다."
                )
            else:
                # 2026-09-07(사용자 지시: "값이 없으면 없다고 나오면 되지 왜
                # 이상한 짓을 더하지") — price_forecast처럼 광종별 가용기간
                # 계산이 안 되는(또는 그 페이지가 애초에 _PERIOD_BOUNDS_LEAD
                # 대상이 아닌) 경우, "이 광종만 지원합니다" 같은 추가 주장을
                # 만들어내지 않고 단순히 "조회 결과가 없다"는 사실만 알린다.
                # 이 문구는 chatbot.py::_resolve_abstain이 결정적 마커로 잡아
                # dense 노이즈발 near-miss/오분류(예: "investment_advice"
                # 오판)로 새지 않고 정확한 이유로 곧장 기권하게 한다.
                warnings.append(_NO_DATA_FOUND_MARKER)

        # 근거 라벨용 한글명 + 더미데이터 판정 — ai_mnrl_mst 한 번의 조회로
        # 함께 얻는다(resolve_mineral_meta). 예전엔 resolve_data_source()·
        # resolve_mineral()을 각각 불러 같은 WHERE 조건(mnrknd_unq_cd = code)
        # 으로 두 번 왕복했다(skeptic-code DEEP 감사 SC-001, 2026-09-01, 사용자
        # 승인 — resolve_mineral()은 report_gen 등 다른 호출부가 있어 그대로
        # 남겨두고 이 호출부만 새 메서드로 교체). 못 찾으면(예: mineral_code가
        # 애초에 코드 형식이 아니거나 ai_mnrl_mst에 없음) 코드 그대로 라벨에
        # 쓰고 더미로 간주한다(원래 동작 그대로 — 확인 안 되면 안전한 쪽으로
        # 열화, is_dummy는 KOMIS_SAMPLE로 확인됐을 때만 False).
        is_dummy = None
        mineral_label = mineral_code
        if mineral_code:
            try:
                resolved_meta = repo.resolve_mineral_meta(mineral_code)
            except RawDataAccessError:
                resolved_meta = None
            if resolved_meta:
                mineral_label = resolved_meta[0]
            data_source = resolved_meta[1] if resolved_meta else None
            is_dummy = data_source != "KOMIS_SAMPLE"
            if is_dummy:
                warnings.append(
                    f"⚠ '{mineral_code}' 데이터는 KOMIS 실제 표본이 아니라 개발용 더미"
                    f"(ko_data_src_cd={data_source or '확인불가'})일 수 있습니다 — "
                    "실제 수치인 것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
                )
        unverified = False
        if not mineral_code and page_id == "indicator_composite":
            # 2026-09-02 skeptic 2차감사 SC-CB2-001 수정 — mineral_code가 없는
            # 경로(광물종합지수는 광종과 무관한 지표라 정상적으로 없을 수 있다,
            # composite_index 분기 참고)는 위 if를 안 타 is_dummy가 계속
            # None(=판정 자체를 안 함)이었다 — fail-open. 이 page는 광종 키가
            # 없어(index_type_code뿐) ai_mnrl_mst로 실샘플/더미를 확인할 방법이
            # 구조적으로 없다(KO_MNRL_SNTHS_INDX엔 데이터출처 컬럼 자체가 없음,
            # 2026-09-02 실측 확인 — 오히려 2011~2025 연속 영업일 데이터라
            # 실데이터로 보이지만 확정할 근거가 없다). "확인 안 되면 안전한
            # 쪽으로 열화"는 유지하되, `is_dummy=True`(확정 더미)로 두면
            # KOMIS_RAW_DUMMY_CAVEAT의 "실제 값이 아닙니다"가 그대로 붙어
            # 판정 불가를 확정 더미로 잘못 단정하게 된다(main-agent 결과감사
            # 지적) — 별도의 "판정 불가" caveat(`unverified=True`)로 처리한다.
            unverified = True
            warnings.append(
                "⚠ 광물종합지수(KO_MNRL_SNTHS_INDX)는 광종과 무관한 지표라 KOMIS "
                "실제 표본인지 자동으로 확인할 방법이 없습니다 — 실제 수치인 "
                "것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
            )

        # is_dummy/unverified를 Evidence.caveat에도 심는다(위 warnings는 도구
        # 호출 로그·기권사유 분류용, caveat는 이 근거가 실제로 인용됐을 때
        # 사용자 화면에 강제로 뜨는 경고용 — 둘은 소비처가 달라 둘 다 채운다).
        evidence = from_komis_raw(
            page_id, datasets, mineral_code=mineral_label, is_dummy=is_dummy, unverified=unverified,
        )
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    #: metric -> 근거 section에 쓸 한글 라벨(komis_raw.py::_RANKING_METRIC_LABELS와
    #: 같은 값 — evidence.py가 komis_raw.py를 모르게 하려고(계층 의존 방향
    #: 유지) 이 파일에서 별도로 든다, 값 자체는 동일해야 함).
    _RANKING_METRIC_LABELS = {
        "import_amount": "수입금액", "import_weight": "수입중량",
        "export_amount": "수출금액", "export_weight": "수출중량",
    }

    @mcp.tool()
    def komis_country_ranking(
        mineral_code: str,
        page_id: str,
        metric: str,
        start_period: str | None = None,
        end_period: str | None = None,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """국가별 합계 상위 N개(결정적 GROUP BY+ORDER BY+LIMIT, 2026-09-18
        신설) — "{광종} 수입 상위 5개국", "{광종} 수출 많이 하는 나라" 같은
        순위형 질문 전용. `komis_raw_lookup`(필터+정렬+LIMIT만, 집계 없음)로는
        "최근 N건" 원자료만 나와 순위를 만들 수 없었다 — DB에서 직접 집계해
        비중(%)까지 계산해 돌려준다(LLM이 원자료를 보고 스스로 분모를
        계산하게 하지 않는다 — 그게 더 정확하다).

        page_id: "map_korea"(관세청, 한국 기준 상대국 수입/수출)만 현재 실제
        데이터가 있다. "map_global"(UN Comtrade)은 코드는 동작하지만
        2026-09-18 실측 확인 결과 dev-dummy KO_UN_CMMRC의 HS코드가
        `ai_hs_mnrl_map` 매핑과 겹치지 않아 광종 어느 것을 조회해도 0건이다
        (데이터가 채워지면 별도 코드 변경 없이 그대로 동작).
        metric: "import_amount"|"import_weight"|"export_amount"|"export_weight".
        mineral_code는 `komis_resolve_mineral`로 먼저 얻은 값(예: "MNRL0001").
        {"evidence": [...], "warnings": [...]}."""

        repo = KomisRawDataRepository()
        try:
            hs_codes = repo.resolve_hs_codes(mineral_code)
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}
        if not hs_codes:
            return {
                "evidence": [],
                "warnings": [f"'{mineral_code}'에 대응하는 HS코드를 ai_hs_mnrl_map에서 찾지 못했습니다."],
            }

        try:
            dataset = repo.fetch_country_ranking(
                page_id=page_id, hs_codes=hs_codes, metric=metric,
                start_period=start_period, end_period=end_period, top_n=top_n,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}

        warnings: list[str] = []
        if not dataset.rows:
            warnings.append(_NO_DATA_FOUND_MARKER)

        try:
            resolved_meta = repo.resolve_mineral_meta(mineral_code)
        except RawDataAccessError:
            resolved_meta = None
        mineral_label = resolved_meta[0] if resolved_meta else mineral_code
        data_source = resolved_meta[1] if resolved_meta else None
        is_dummy = data_source != "KOMIS_SAMPLE"
        if is_dummy and dataset.rows:
            warnings.append(
                f"⚠ '{mineral_code}' 데이터는 KOMIS 실제 표본이 아니라 개발용 더미"
                f"(ko_data_src_cd={data_source or '확인불가'})일 수 있습니다 — "
                "실제 수치인 것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
            )

        evidence = from_komis_ranking(
            dataset, mineral_code=mineral_label,
            metric_label=_RANKING_METRIC_LABELS.get(metric, metric), is_dummy=is_dummy,
        )
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    @mcp.tool()
    def komis_country_concentration(
        mineral_code: str,
        page_id: str = "map_korea",
        metric: str = "import_amount",
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> dict[str, Any]:
        """광종 교역의 전체 국가 모집단 HHI를 계산한다.

        국가 순위의 상위 N개 미리보기와 달리, 같은 HS·기간·수입/수출 조건의
        모든 국가를 집계한 뒤 HHI=Σ(국가별 비중[%]^2)를 코드로 계산한다.
        """

        repo = KomisRawDataRepository()
        try:
            hs_codes = repo.resolve_hs_codes(mineral_code)
            dataset = repo.fetch_country_concentration(
                page_id=page_id, hs_codes=hs_codes, metric=metric,
                start_period=start_period, end_period=end_period,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}
        if not dataset.rows:
            return {"evidence": [], "warnings": [_NO_DATA_FOUND_MARKER]}
        try:
            resolved_meta = repo.resolve_mineral_meta(mineral_code)
        except RawDataAccessError:
            resolved_meta = None
        mineral_label = resolved_meta[0] if resolved_meta else mineral_code
        data_source = resolved_meta[1] if resolved_meta else None
        is_dummy = data_source != "KOMIS_SAMPLE"
        hhi = dataset.metadata.get("hhi")
        grand_total = dataset.metadata.get("grand_total")
        formula = dataset.metadata.get("formula")
        evidence = from_komis_ranking(
            dataset, mineral_code=mineral_label,
            metric_label=f"{_RANKING_METRIC_LABELS.get(metric, metric)} 집중도(HHI={hhi}, 전체합계={grand_total}, {formula})",
            is_dummy=is_dummy,
        )
        warnings = []
        if is_dummy:
            warnings.append(
                f"⚠ '{mineral_code}' 데이터는 KOMIS 실제 표본이 아니라 개발용 더미"
                f"(ko_data_src_cd={data_source or '확인불가'})일 수 있습니다 — 실제 수치인 것처럼 안내하지 마세요."
            )
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    @mcp.tool()
    def komis_monthly_trade_summary(
        mineral_code: str | None = None, hs_code: str | None = None,
        start_period: str | None = None, end_period: str | None = None,
        compare_year: str | None = None,
        metric: Literal["import_amount", "import_weight"] | None = None,
    ) -> dict[str, Any]:
        """한국 수입액(USD)·수입중량(kg)의 HS 전체 모집단 월별 합계."""
        repo = KomisRawDataRepository()
        try:
            hs_codes = [hs_code] if hs_code else repo.resolve_hs_codes(mineral_code or "")
            dataset = repo.fetch_monthly_trade_summary(
                hs_codes=hs_codes, start_period=start_period, end_period=end_period,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}
        if not dataset.rows:
            return {"evidence": [], "warnings": [_NO_DATA_FOUND_MARKER]}
        mineral_name = None
        is_dummy = False
        if mineral_code:
            try:
                meta = repo.resolve_mineral_meta(mineral_code)
                mineral_name = meta[0] if meta else mineral_code
                is_dummy = bool(meta and meta[1] != "KOMIS_SAMPLE")
            except RawDataAccessError:
                mineral_name = mineral_code
        evidence = []
        missing_columns = {"import_amount", "import_weight"} - set(dataset.columns)
        for column, label, unit in (
            ("import_amount", "월별 한국 수입금액", "USD"),
            ("import_weight", "월별 한국 수입중량", "kg"),
        ):
            if metric and column != metric:
                continue
            if column not in dataset.columns:
                continue
            view = dataset.model_copy(update={
                "columns": ["month", column],
                "rows": [{"month": row.get("month"), column: row.get(column)} for row in dataset.rows],
                "unit": unit,
            })
            evidence.extend(from_komis_aggregate(view, label=label,
                                                 mineral_name=mineral_name, is_dummy=is_dummy))
        if compare_year and start_period and start_period[:4].isdigit():
            try:
                prior = repo.fetch_monthly_trade_summary(
                    hs_codes=hs_codes, start_period=compare_year, end_period=compare_year,
                )
            except RawDataAccessError as exc:
                return {"evidence": [dataclasses.asdict(e) for e in evidence],
                        "warnings": [f"aggregate_incomplete:prior_year:{exc}"]}
            observed = {str(row["month"])[-2:] for row in dataset.rows}
            this_year = start_period[:4]
            current_first = dataset.metadata.get("available_start")
            current_last = dataset.metadata.get("available_end")
            prior_first = f"{compare_year}{str(current_first)[4:]}" if current_first else None
            prior_last = f"{compare_year}{str(current_last)[4:]}" if current_last else None
            if prior_first and prior_last:
                try:
                    prior_same_period = repo.fetch_monthly_trade_summary(
                        hs_codes=hs_codes, start_period=prior_first.replace("-", ""),
                        end_period=prior_last.replace("-", ""),
                    )
                except RawDataAccessError as exc:
                    return {"evidence": [dataclasses.asdict(e) for e in evidence],
                            "warnings": [f"aggregate_incomplete:prior_same_period:{exc}"]}
            else:
                prior_same_period = None
            today_month = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")
            future_months = [f"{this_year}-{month:02d}" for month in range(1, 13)
                             if f"{this_year}-{month:02d}" > today_month]
            unavailable_months = [f"{this_year}-{month:02d}" for month in range(1, 13)
                                  if f"{this_year}-{month:02d}" <= today_month
                                  and f"{month:02d}" not in observed]
            def amount(rows: list[dict[str, Any]]) -> Decimal:
                return sum((Decimal(str(row["import_amount"])) for row in rows), Decimal(0))
            comparison_rows = [
                {"basis": f"{this_year} 관측기간 {current_first}~{current_last}",
                 "import_amount": float(amount(dataset.rows))},
                {"basis": f"{compare_year} 전년 동기간 {prior_first}~{prior_last}",
                 "import_amount": float(amount(prior_same_period.rows)) if prior_same_period else None},
                {"basis": f"{compare_year} 연간 합계", "import_amount": float(amount(prior.rows))},
            ]
            comparison_note = (
                f"필수 비교: {this_year} 실제 관측기간 {current_first}~{current_last} "
                f"{comparison_rows[0]['import_amount']} USD; "
                f"{compare_year} 전년 동일 날짜 {prior_first}~{prior_last} "
                f"{comparison_rows[1]['import_amount']} USD; "
                f"{compare_year} 연간 {comparison_rows[2]['import_amount']} USD. "
                "전년 동기간과 전년 연간은 수치가 같아도 서로 다른 기간으로 각각 표시해야 합니다."
            )
            prior_same_period_sentence = (
                f"전년 동기간({prior_first}~{prior_last}) 수입금액은 "
                f"{comparison_rows[1]['import_amount']} USD입니다. "
                "전년 연간 합계와 값이 같더라도 비교 기간은 다릅니다."
            )
            comparison_dataset = RawDataset(
                source_table=dataset.source_table, columns=["basis", "import_amount"],
                column_labels={"basis": "비교 기준", "import_amount": "수입금액합계(USD)"},
                row_count=len(comparison_rows), rows=comparison_rows, unit="USD",
                metadata={"current_observed_months": sorted(observed),
                          "required_comparison": comparison_note,
                          "prior_same_period_sentence": prior_same_period_sentence,
                          "future_months": future_months,
                          "unavailable_past_months": unavailable_months,
                          "same_period_basis": "현재 실제 관측 시작일·종료일과 전년도 동일 월일자를 비교(부분월 포함)",
                          "current_period_start": current_first, "current_period_end": current_last,
                          "prior_period_start": prior_first, "prior_period_end": prior_last,
                          "current_year": this_year, "prior_year": compare_year,
                          "hs_codes": hs_codes},
            )
            evidence.extend(from_komis_aggregate(comparison_dataset,
                                                 label="현재 관측기간·전년 동일 날짜·전년 연간 3종 수입금액 비교",
                                                 mineral_name=mineral_name, is_dummy=is_dummy))
            if not prior.rows or prior_same_period is None or not prior_same_period.rows:
                missing_columns.add("prior_year_data")
        return {"evidence": [dataclasses.asdict(e) for e in evidence],
                "warnings": [f"aggregate_incomplete:missing_columns:{','.join(sorted(missing_columns))}"]
                if missing_columns else []}

    @mcp.tool()
    def komis_explicit_hs_import_summary(
        hs_code: str, start_period: str | None = None, end_period: str | None = None,
    ) -> dict[str, Any]:
        """질문에 명시된 HS 한 코드의 품목명·기간 총합·월별 한국 수입 현황."""
        repo = KomisRawDataRepository()
        try:
            dataset = repo.fetch_explicit_hs_import_summary(
                hs_code=hs_code, start_period=start_period, end_period=end_period,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}
        dataset = dataset.model_copy(update={"metadata": {
            **dataset.metadata,
            "population_note": f"이 합계는 HS {hs_code} 한 품목·전체 국가·해당 기간만 포함합니다. 광종 전체 HS 품목 합계와 다릅니다.",
        }})
        evidence = []
        for column, label, unit in (
            ("import_amount", "수입금액", "USD"),
            ("import_weight", "수입중량", "kg"),
        ):
            view = dataset.model_copy(update={
                "columns": ["month", column],
                "rows": [{"month": row.get("month"), column: row.get(column)} for row in dataset.rows],
                "unit": unit,
            })
            evidence.extend(from_komis_aggregate(view, label=f"HS {hs_code} {label} 현황"))
        return {"evidence": [dataclasses.asdict(e) for e in evidence],
                "warnings": [] if evidence else [_NO_DATA_FOUND_MARKER]}

    @mcp.tool()
    def komis_price_comparison(
        mineral_names: list[str], start_period: str | None = None,
        end_period: str | None = None, window_months: int | None = None,
    ) -> dict[str, Any]:
        """같은 실제 기간·각 광종의 고정 가격기준으로 시계열과 변동률을 조회."""
        repo = KomisRawDataRepository()
        try:
            dataset = repo.fetch_price_comparison(
                mineral_names=mineral_names, start_period=start_period, end_period=end_period,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}
        if not dataset.rows:
            return {"evidence": [], "warnings": [_NO_DATA_FOUND_MARKER]}
        is_dummy = _any_dummy(repo, mineral_names)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in dataset.rows:
            grouped.setdefault(str(row["mineral"]), []).append(row)
        window_label = f"최근 {window_months}개월 요청 · " if window_months else ""
        evidence = []
        for mineral, points in grouped.items():
            # 서로 단위가 다른 광종 가격을 한 Y축에 합치지 않는다.
            # 각 광종의 긴 일별 이력은 양끝을 포함해 최대 40시점만 표/차트에 실는다.
            count = min(len(points), 40)
            indexes = {round(i * (len(points) - 1) / (count - 1)) for i in range(count)} if count > 1 else {0}
            sampled = [points[i] for i in sorted(indexes)]
            series_view = dataset.model_copy(update={
                "rows": sampled, "row_count": len(sampled),
                "metadata": {key: value for key, value in dataset.metadata.items() if key != "comparison"},
            })
            evidence.extend(from_komis_aggregate(
                series_view, label=f"{window_label}{mineral} 가격 시계열(최대 40시점)",
                mineral_name=mineral, is_dummy=is_dummy,
            ))
        comparison = dataset.metadata.get("comparison") or []
        if comparison:
            compare_columns = [
                "mineral", "start_date", "start_price", "end_date", "end_price",
                "pct_change", "price_criterion", "price_currency_code", "weight_unit_code",
            ]
            compare_dataset = RawDataset(
                source_table=dataset.source_table, columns=compare_columns,
                column_labels={
                    "mineral": "광종", "start_date": "시작일", "start_price": "시작가격",
                    "end_date": "종료일", "end_price": "종료가격",
                    "pct_change": "변동률(%)", "price_criterion": "가격기준",
                    "price_currency_code": "통화코드", "weight_unit_code": "중량단위코드",
                },
                row_count=len(comparison), rows=comparison, as_of=dataset.as_of,
                metadata={key: value for key, value in dataset.metadata.items() if key != "comparison"},
            )
            evidence.extend(from_komis_aggregate(compare_dataset, label=f"{window_label}동일 기간 가격 변동률",
                                                 is_dummy=is_dummy))
        missing = dataset.metadata.get("missing_minerals") or []
        warnings = [f"aggregate_incomplete:missing_minerals:{','.join(missing)}"] if missing else []
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    _RESERVES_PRODUCTION_METRIC_LABELS = {"production": "생산량", "reserves": "매장량"}

    @mcp.tool()
    def komis_mineral_ranking(
        mineral_code: str,
        metric: str,
        start_period: str | None = None,
        end_period: str | None = None,
        top_n: int = 5,
        share_only: bool = False,
    ) -> dict[str, Any]:
        """매장량/생산량 국가별 상위 N개(결정적 GROUP BY, 2026-09-18 신설) —
        "{광종} 매장량 1위 국가", "{광종} 생산량 상위 5개국" 같은 순위형
        질문 전용. `komis_country_ranking`(교역)과 같은 원칙이지만 이쪽은
        HS코드 번역이 필요 없다(map_mineral은 광종코드로 직접 필터).

        metric: "production"(생산량, 흐름값 — start/end 지정 시 그 기간
        합산, 미지정 시 최신 연도)|"reserves"(매장량, 스냅샷 — 항상 연도
        하나만, start/end 지정 시 end 연도, 미지정 시 최신 연도. 여러 해를
        합산하지 않는다 — 매장량은 누적되는 값이 아니다).
        start_period/end_period: YYYY(연도 4자리)만 받는다(월/일 없음).
        mineral_code는 `komis_resolve_mineral`로 먼저 얻은 값(예: "MNRL0002").
        {"evidence": [...], "warnings": [...]}."""

        repo = KomisRawDataRepository()
        try:
            dataset = repo.fetch_mineral_country_ranking(
                metric=metric, mineral_code=mineral_code,
                start_period=start_period, end_period=end_period, top_n=top_n,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}

        warnings: list[str] = []
        if not dataset.rows:
            warnings.append(_NO_DATA_FOUND_MARKER)

        try:
            resolved_meta = repo.resolve_mineral_meta(mineral_code)
        except RawDataAccessError:
            resolved_meta = None
        mineral_label = resolved_meta[0] if resolved_meta else mineral_code
        data_source = resolved_meta[1] if resolved_meta else None
        is_dummy = data_source != "KOMIS_SAMPLE"
        if is_dummy and dataset.rows:
            warnings.append(
                f"⚠ '{mineral_code}' 데이터는 KOMIS 실제 표본이 아니라 개발용 더미"
                f"(ko_data_src_cd={data_source or '확인불가'})일 수 있습니다 — "
                "실제 수치인 것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
            )

        if share_only:
            # 생산국 비중과 수입국 비중을 비교하는 복합 질문에서는 두 차트를
            # 모두 %로 맞춘다. 분모의 원 단위(톤)는 Evidence 설명에 보존한다.
            dataset = dataset.model_copy(update={
                "columns": ["rank", "country", "share_pct"],
                "rows": [{key: row.get(key) for key in ("rank", "country", "share_pct")}
                         for row in dataset.rows],
            })

        evidence = from_komis_ranking(
            dataset, mineral_code=mineral_label,
            metric_label=_RESERVES_PRODUCTION_METRIC_LABELS.get(metric, metric), is_dummy=is_dummy,
        )
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    def _any_dummy(repo: KomisRawDataRepository, mineral_names: list[str]) -> bool:
        """결과에 실제로 나온 광종들 중 하나라도 더미면 보수적으로 True —
        여러 광종을 한 표에 합치는 비교/랭킹 도구는 행마다 다른 caveat을
        달 수 없어(Evidence 1건에 caveat 1개) 하나라도 더미면 전체를 더미로
        취급한다(2026-09-18, "확인 안 되면 안전한 쪽으로" 기존 원칙 재사용)."""

        for name in mineral_names:
            try:
                resolved = repo.resolve_mineral_full(name)
            except RawDataAccessError:
                return True
            if resolved is None:
                continue
            code = resolved[0]
            try:
                meta = repo.resolve_mineral_meta(code)
            except RawDataAccessError:
                return True
            if meta is None or meta[1] != "KOMIS_SAMPLE":
                return True
        return False

    @mcp.tool()
    def komis_price_volatility_ranking(
        mineral_names: list[str] | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """광종 간 가격 변동률 비교/랭킹(결정적, 2026-09-18 신설) — "니켈과
        리튬 중 가격 변동이 큰 광물은?", "가격이 가장 많이 움직인 광종은?"
        같은 **여러 광종을 가로지르는** 비교 질문 전용(단일 광종 가격
        조회는 `komis_raw_lookup`의 price_* page_id가 그대로 담당).

        ⚠ start_period/end_period를 안 주면 광종마다 KOMIS 가격 이력이
        시작된 시점부터 전체 기간으로 변동률을 계산한다 — 광종별 이력
        길이가 다르면(예: 어떤 광종은 20년치, 어떤 광종은 2개월치) 공정한
        비교가 안 된다. 질문에 "최근"이 있으면 반드시 기간을 채울 것.

        mineral_names: 비교할 광종 한글명 리스트(예: ["니켈","리튬"]) —
        없으면 가격 데이터가 있는 전 광종 대상 상위 N개 랭킹.
        {"evidence": [...], "warnings": [...]}."""

        repo = KomisRawDataRepository()
        try:
            dataset = repo.fetch_price_volatility_ranking(
                mineral_names=mineral_names, start_period=start_period,
                end_period=end_period, top_n=top_n,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}

        warnings: list[str] = []
        if not dataset.rows:
            warnings.append(_NO_DATA_FOUND_MARKER)
            return {"evidence": [], "warnings": warnings}

        is_dummy = _any_dummy(repo, [row["mineral"] for row in dataset.rows])
        if is_dummy:
            warnings.append(
                "⚠ 비교 대상 광종 중 일부는 KOMIS 실제 표본이 아니라 개발용 더미일 수 있습니다 — "
                "실제 수치인 것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
            )

        evidence = from_komis_ranking(
            dataset, metric_label="가격 변동률", is_dummy=is_dummy, row_kind="광종",
        )
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}

    _INDICATOR_RANKING_LABELS = {"indicator_supply": "수급동향지표", "indicator_market": "시장전망지표"}

    @mcp.tool()
    def komis_indicator_ranking(
        page_id: str,
        ascending: bool = True,
        mineral_names: list[str] | None = None,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """지표(수급동향/시장전망) 최신값 기준 광종 간 비교/랭킹(결정적,
        2026-09-18 신설) — "수급동향지표가 가장 낮은 광종은?", "시장전망지표가
        가장 좋은 광종은?" 같은 **여러 광종을 가로지르는** 비교 질문 전용
        (단일 광종 지표 추이는 `komis_raw_lookup`이 담당).

        page_id: "indicator_supply"|"indicator_market"만 지원(private
        프로필 전용 — 이 tool도 그 제약을 그대로 물려받는다).
        ascending: True면 값이 가장 낮은 광종이 1위(예: "가장 위험한/안
        좋은"), False면 가장 높은 광종이 1위("가장 좋은") — 질문 뉘앙스에
        맞춰 호출측(라우터)이 고른다.
        mineral_names: 비교할 광종 한글명 리스트, 없으면 지표가 있는 전
        광종 대상. {"evidence": [...], "warnings": [...]}."""

        if page_id in private_only_pages:
            return {
                "evidence": [],
                "warnings": [f"'{page_id}'는 private 전용 데이터입니다 — public 프로필에서는 조회할 수 없습니다."],
            }

        repo = KomisRawDataRepository()
        try:
            dataset = repo.fetch_latest_indicator_ranking(
                page_id=page_id, ascending=ascending, mineral_names=mineral_names, top_n=top_n,
            )
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [str(exc)]}

        warnings: list[str] = []
        if not dataset.rows:
            warnings.append(_NO_DATA_FOUND_MARKER)
            return {"evidence": [], "warnings": warnings}

        is_dummy = _any_dummy(repo, [row["mineral"] for row in dataset.rows])
        if is_dummy:
            warnings.append(
                "⚠ 비교 대상 광종 중 일부는 KOMIS 실제 표본이 아니라 개발용 더미일 수 있습니다 — "
                "실제 수치인 것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
            )

        evidence = from_komis_ranking(
            dataset, metric_label=_INDICATOR_RANKING_LABELS.get(page_id, page_id),
            is_dummy=is_dummy, row_kind="광종",
        )
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}
