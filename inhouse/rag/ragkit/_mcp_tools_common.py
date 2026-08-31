# -*- coding: utf-8 -*-
"""public/private MCP 서버 두 파일이 공유하는 **라이선스 무관** tool 6개 —
정형 3종(structured 산출물, 라이선스 이슈 없음)·komis_raw_lookup·
komis_resolve_mineral(KOMIS 공개원천 public.KO_*, 2026-08-31/09-01 추가 —
타 팀 소유일 뿐 라이선스 제한 콘텐츠(Argus)는 아니라 여기 둠)·
pageindex_agentic(USGS 코퍼스만 스캔, Argus를 애초에 안 건드림). 이 여섯은
public/private가 결과가 완전히 같아야 정상이므로(2026-08-26
smoke_mcp_access.py로 실측 확인, komis_* 2종은 그 이후 추가라 별도 재검증
필요) 여기 한 번만 구현하고 두 서버 파일이 그대로 등록만 한다.

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
from typing import Any

from mcp.server.fastmcp import FastMCP

from pydantic import ValidationError

from shared.komis_raw import (
    AnalysisPreviewPageId,
    AnalysisPreviewRequest,
    KomisRawDataRepository,
    RawDataAccessError,
)
from shared.llm_client import KomirJsonLLM
from shared.retrieval import pageindex_agent, structured
from shared.retrieval.evidence import Evidence, from_komis_raw, from_structured


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


def register_common_tools(mcp: FastMCP) -> None:
    """호출자(mcp_server_public.py·mcp_server_private.py)가 자기 `FastMCP`
    인스턴스를 넘겨 이 4개 tool을 등록한다. 모든 tool은 top-level에서 항상
    `dict[str, Any]`(Optional도 list도 아닌 순수 object)를 반환한다 — FastMCP가
    반환 타입이 이미 object 스키마면 `structuredContent`에 그대로 싣고,
    `dict | None`/`list[...]`처럼 top-level이 object가 아니면 `{"result": ...}`
    로 감싸는 걸 실측으로 확인했기 때문(`mcp_client.py`가 도구마다 다른 언랩
    로직 없이 `structuredContent`를 그대로 쓰게 하려는 것)."""

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
        limit: int = 5,
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

        try:
            datasets = repo.fetch(request)
        except RawDataAccessError as exc:
            return {"evidence": [], "warnings": [*warnings, str(exc)]}

        is_dummy = None
        if mineral_code:
            try:
                data_source = repo.resolve_data_source(mineral_code)
            except RawDataAccessError:
                data_source = None
            is_dummy = data_source != "KOMIS_SAMPLE"
            if is_dummy:
                warnings.append(
                    f"⚠ '{mineral_code}' 데이터는 KOMIS 실제 표본이 아니라 개발용 더미"
                    f"(ko_data_src_cd={data_source or '확인불가'})일 수 있습니다 — "
                    "실제 수치인 것처럼 안내하지 말고 반드시 이 사실을 함께 밝히세요."
                )

        # 근거 라벨용 한글명 — ai_mnrl_mst에서 직접 끌어온다(위 독스트링
        # 참고, resolve_data_source와 마찬가지로 mineral_code 기준 조회).
        # 못 찾으면(예: mineral_code가 애초에 코드 형식이 아님) 코드 그대로
        # 라벨에 쓴다 — 사람이 못 알아보는 최악의 경우라도 조회 자체는 막지
        # 않는다(안전한 열화).
        mineral_label = mineral_code
        if mineral_code:
            try:
                resolved_name = repo.resolve_mineral(mineral_code)
            except RawDataAccessError:
                resolved_name = None
            if resolved_name:
                mineral_label = resolved_name[1]

        # is_dummy를 Evidence.caveat에도 심는다(위 warnings는 도구 호출 로그·
        # 기권사유 분류용, caveat는 이 근거가 실제로 인용됐을 때 사용자 화면에
        # 강제로 뜨는 경고용 — 둘은 소비처가 달라 둘 다 채운다).
        evidence = from_komis_raw(page_id, datasets, mineral_code=mineral_label, is_dummy=is_dummy)
        return {"evidence": [dataclasses.asdict(e) for e in evidence], "warnings": warnings}
