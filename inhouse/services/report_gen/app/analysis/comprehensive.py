# -*- coding: utf-8 -*-
""""AI 종합분석 및 관련뉴스" 오케스트레이션 — 화면 기획안 ver.1.3(11페이지) 신규 구현.

`documents/산출물/2026-W33_0810-0816/화면기획안_v1.3_기능단위_AI작업_구현현황_
260813.md` §3 항목13(미구현)을 채우는 작업이다. 데이터는 전부 komir 자체
산출물(`shared/retrieval/structured.py`, MSR_DB=DuckDB 정본)에서 온다 —
`mineral_risk`(PG) 쪽은 2026-08-10 1회성 이관 스냅샷이라 새 조회 경로를
거기 붙이지 않는다(기존 `latest_diagnosis`/`geo_index_trend`가 이미 DuckDB를
쓰고 있어 그대로 재사용).

**대응전략은 LLM이 아니라 고정 카탈로그에서 규칙기반으로 고른다** — 정부기관
대상 정책 조언을 LLM이 지어내면 안 된다는 판단(리스크 카테고리→전략 매핑은
화면기획 13p 문구를 그대로 옮긴 5개 전략을 카테고리별로 배정한 것이며, 원본
슬라이드가 카테고리-전략 1:1 매핑을 명시하지 않아 이 파일이 임의로 정한
초안이다 — 실제 배정은 발주처/도메인 검토가 필요, §역할 표기 참고).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.llm_client import LLMError  # noqa: E402
from shared.retrieval.structured import (  # noqa: E402
    VALID_COMMODITIES,
    geo_index_trend,
    latest_diagnosis,
    weekly_geo_events,
)

from .comprehensive_models import (  # noqa: E402
    ComprehensiveDashboardResponse,
    ComprehensiveOverview,
    RiskTag,
    WeeklyNewsCard,
)
from .comprehensive_prompts import (  # noqa: E402
    NEWS_CARD_INSTRUCTIONS,
    OVERVIEW_INSTRUCTIONS,
    NewsCardNarrative,
    OverviewNarrative,
    build_news_card_payload,
    build_overview_payload,
)

#: 발주 5광종 한글명(generator.py의 COMMODITY_NAMES와 동일 값 — 순환import 방지로
#: 여기 별도 유지. 값이 바뀌면 두 곳 다 고칠 것).
COMMODITY_NAMES: dict[str, str] = {
    "CU": "동(구리)",
    "NI": "니켈",
    "CO": "코발트",
    "LI": "리튬",
    "REE": "희토류(네오디뮴)",
}

#: 리스크 태그 분류 키워드(1차 휴리스틱 — event_type·target 텍스트가 GKG/LLM
#: 추출기마다 표기가 달라 완전한 분류는 못 한다, 확인·개선 필요).
_GEOPOLITICAL_KEYWORDS = (
    "war", "conflict", "sanction", "export control", "export_control", "embargo",
    "tariff", "unrest", "protest", "분쟁", "제재", "전쟁", "정책", "policy",
    "regulation", "규제", "수출통제",
)
_SUPPLY_TARGETS = {"supply", "production", "resource", "resource_base", "volume", "inventory"}
_MARKET_TARGETS = {"price", "market", "market_value", "market_size"}

#: 리스크 카테고리 → 대응전략 후보(화면기획 13p 5개 문구, 카테고리 배정은 초안).
RESPONSE_STRATEGY_CATALOG: dict[str, list[str]] = {
    "지정학적": ["해외수입선의 다변화", "위기대응체계 고도화 추진"],
    "공급망": ["해외자원개발 확대", "국가 비축 확대"],
    "시장": ["핵심광물 모니터링 강화"],
    "산업영향": ["국가 비축 확대", "핵심광물 모니터링 강화"],
}


def _classify_risk_category(event_type: str, target: str) -> str:
    et = (event_type or "").lower()
    tg = (target or "").lower()
    if any(k in et for k in _GEOPOLITICAL_KEYWORDS):
        return "지정학적"
    if tg in _SUPPLY_TARGETS:
        return "공급망"
    if tg in _MARKET_TARGETS:
        return "시장"
    return "산업영향"


def _select_response_strategies(categories: list[str]) -> list[str]:
    seen: list[str] = []
    for cat in categories:
        for strategy in RESPONSE_STRATEGY_CATALOG.get(cat, []):
            if strategy not in seen:
                seen.append(strategy)
    return seen


class ComprehensiveAnalysisService:
    """대시보드 "AI 종합분석 및 관련뉴스" 1건을 조립한다."""

    def __init__(self, llm=None) -> None:
        self._llm = llm

    def build_dashboard(self) -> ComprehensiveDashboardResponse:
        overview, top_events_by_commodity = self._build_overview()
        news = [
            self._build_news_card(code, overview.as_of, top_events_by_commodity.get(code, []))
            for code in VALID_COMMODITIES
        ]
        return ComprehensiveDashboardResponse(
            overview=overview,
            news=news,
            generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )

    # ── 종합진단(현황→원인→대응) ──────────────────────────────────────

    def _build_overview(self) -> tuple[ComprehensiveOverview, dict[str, list[dict[str, Any]]]]:
        per_commodity: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        as_of: str | None = None
        for code in VALID_COMMODITIES:
            trend = geo_index_trend(code, freq="W", limit=2)
            if not trend:
                warnings.append(f"{COMMODITY_NAMES[code]}({code}) 위기지수 데이터 없음")
                continue
            current = trend[-1]
            prior = trend[-2] if len(trend) > 1 else None
            period = str(current["period"])[:10]  # duckdb가 timestamp로 돌려줄 수 있어 날짜만 자름
            if as_of is None or period > as_of:
                as_of = period
            diag = latest_diagnosis(code)
            per_commodity[code] = {
                "idx_value": float(current["idx_value"]),
                "prior_idx_value": float(prior["idx_value"]) if prior else None,
                "alert_level": diag["alert_level"] if diag else None,
                "diag_obs_date": str(diag["obs_date"])[:10] if diag else None,
            }

        if not per_commodity:
            raise RuntimeError("5광종 전체 위기지수 데이터 없음 — geo publish 여부 확인 필요")
        if as_of is None:
            raise RuntimeError("위기지수 기준일(as_of)을 확정할 수 없음")

        values = [v["idx_value"] for v in per_commodity.values()]
        composite_index = sum(values) / len(values)
        prior_values = [v["prior_idx_value"] for v in per_commodity.values() if v["prior_idx_value"] is not None]
        composite_change = None
        if len(prior_values) == len(per_commodity):
            prior_composite = sum(prior_values) / len(prior_values)
            composite_change = composite_index - prior_composite
        else:
            warnings.append("일부 광종의 전주 위기지수가 없어 전주 대비 값을 생략함")

        top_code = max(per_commodity, key=lambda c: per_commodity[c]["idx_value"])
        for code, v in per_commodity.items():
            if v["diag_obs_date"] and v["diag_obs_date"] < as_of:
                warnings.append(
                    f"{COMMODITY_NAMES[code]} 경보 기준일({v['diag_obs_date']})이 "
                    f"위기지수 기준일({as_of})보다 오래됨 — 진단 파이프라인 재실행 필요"
                )

        # 이번 주 이벤트 → 리스크 태그(광종 통합, severity 상위) + 광종별 뉴스카드 원재료
        top_events_by_commodity: dict[str, list[dict[str, Any]]] = {}
        all_events: list[dict[str, Any]] = []
        for code in VALID_COMMODITIES:
            events = weekly_geo_events(code, week_end=as_of, top_n=8)
            top_events_by_commodity[code] = events
            all_events.extend(events)
        all_events.sort(key=lambda e: (e.get("severity") or 0, e.get("confidence") or 0), reverse=True)

        categories_seen: list[str] = []
        risk_tags: list[RiskTag] = []
        for event in all_events[:12]:
            category = _classify_risk_category(event.get("event_type", ""), event.get("target", ""))
            if category in categories_seen:
                continue
            categories_seen.append(category)
            text = (event.get("evidence_quote") or "").strip()
            if len(text) > 70:
                text = text[:69] + "…"
            risk_tags.append(RiskTag(category=category, text=text or category))
            if len(risk_tags) >= 4:
                break

        response_strategies = _select_response_strategies(categories_seen)

        alerts_payload = [
            {
                "name": COMMODITY_NAMES[code],
                "alert_level": v["alert_level"] or "미상",
                "idx_value": round(v["idx_value"], 1),
            }
            for code, v in per_commodity.items()
        ]
        core_diagnosis, llm_refined = self._refine_core_diagnosis(
            composite_index=composite_index,
            composite_index_change=composite_change,
            top_commodity_name=COMMODITY_NAMES[top_code],
            alerts=alerts_payload,
        )

        overview = ComprehensiveOverview(
            as_of=as_of,
            composite_index=composite_index,
            composite_index_change=composite_change,
            top_commodity=top_code,
            core_diagnosis=core_diagnosis,
            risk_tags=risk_tags,
            response_strategies=response_strategies,
            llm_refined=llm_refined,
            warnings=warnings,
        )
        return overview, top_events_by_commodity

    def _refine_core_diagnosis(
        self,
        *,
        composite_index: float,
        composite_index_change: float | None,
        top_commodity_name: str,
        alerts: list[dict[str, Any]],
    ) -> tuple[str, bool]:
        fallback = (
            f"종합 위기지수 {composite_index:.1f}"
            + (
                f", 전주 대비 {composite_index_change:+.1f}p"
                if composite_index_change is not None
                else ""
            )
            + f", {top_commodity_name}이(가) 가장 높은 수준입니다."
        )
        if self._llm is None:
            return fallback, False
        try:
            invocation = self._llm.invoke(
                task="comprehensive_overview",
                instructions=OVERVIEW_INSTRUCTIONS,
                payload=build_overview_payload(
                    composite_index=composite_index,
                    composite_index_change=composite_index_change,
                    top_commodity_name=top_commodity_name,
                    alerts=alerts,
                ),
                output_model=OverviewNarrative,
                max_tokens=300,
            )
            return invocation.output.core_diagnosis, True
        except (LLMError, RuntimeError, OSError):
            # KomirJsonLLM은 전송계층 오류를 LLMError로 감싸지 않는다(summary.py:1075와
            # 동일 사유 — vLLM 미도달 시 폴백 대신 500을 내지 않기 위해 넓게 잡는다).
            return fallback, False

    # ── 광종별 주간 뉴스카드 ──────────────────────────────────────────

    def _build_news_card(
        self, code: str, as_of: str, events: list[dict[str, Any]]
    ) -> WeeklyNewsCard:
        name = COMMODITY_NAMES[code]
        if not events:
            return WeeklyNewsCard(
                commodity_code=code,
                commodity_name=name,
                headline="이번 주 관련 이벤트 없음",
                driver_up=None,
                driver_down=None,
                as_of=as_of,
                llm_refined=False,
                source_count=0,
            )
        top = events[0]
        fallback_headline = (top.get("evidence_quote") or name)[:25]
        fallback = WeeklyNewsCard(
            commodity_code=code,
            commodity_name=name,
            headline=fallback_headline,
            driver_up=top.get("evidence_quote"),
            driver_down=events[1].get("evidence_quote") if len(events) > 1 else None,
            as_of=as_of,
            llm_refined=False,
            source_count=len(events),
        )
        if self._llm is None:
            return fallback
        try:
            invocation = self._llm.invoke(
                task="comprehensive_news_card",
                instructions=NEWS_CARD_INSTRUCTIONS,
                payload=build_news_card_payload(commodity_name=name, events=events),
                output_model=NewsCardNarrative,
                max_tokens=400,
            )
            narrative = invocation.output
            return WeeklyNewsCard(
                commodity_code=code,
                commodity_name=name,
                headline=narrative.headline,
                driver_up=narrative.driver_up,
                driver_down=narrative.driver_down,
                as_of=as_of,
                llm_refined=True,
                source_count=len(events),
            )
        except (LLMError, RuntimeError, OSError):
            return fallback

    def close(self) -> None:
        """서비스 소유 자원 해제(현재 LLM 클라이언트는 요청마다 커넥션을 새로 여는
        `OpenAICompatChat`라 명시적으로 닫을 게 없다 — 다른 서비스와의 인터페이스
        일관성을 위해 메서드만 유지)."""
