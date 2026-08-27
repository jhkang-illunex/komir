# -*- coding: utf-8 -*-
"""public/private MCP 서버 두 파일이 공유하는 **라이선스 무관** tool 4개 —
정형 3종(structured 산출물, 라이선스 이슈 없음)과 pageindex_agentic(USGS
코퍼스만 스캔, Argus를 애초에 안 건드림). 이 넷은 public/private가 결과가
완전히 같아야 정상이므로(2026-08-26 smoke_mcp_access.py로 실측 확인) 여기
한 번만 구현하고 두 서버 파일이 그대로 등록만 한다.

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

from shared.llm_client import KomirJsonLLM
from shared.retrieval import pageindex_agent, structured
from shared.retrieval.evidence import Evidence, from_structured


def _evidence_dict(ev: Evidence | None) -> dict[str, Any] | None:
    return dataclasses.asdict(ev) if ev is not None else None


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
