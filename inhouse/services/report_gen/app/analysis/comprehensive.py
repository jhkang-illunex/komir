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
import re
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

#: 리스크 태그 분류 키워드(2026-08-13 실측 재검토 후 개정 — 1차판은 "policy"/
#: "protest"가 너무 광범위해 국내 광산 인허가·생산확대 정책(카자흐스탄 제련
#: 확장, 캐나다 광산 승인)까지 지정학적으로 잘못 분류하고, 정작 소스가 이미
#: "geopolitical"이라 명시한 이벤트(`geopolitical_competition` 등)는 키워드
#: 목록에 그 단어 자체가 없어 공급망으로 샜다(실측 확인, `geo_event` 다건).
#: 여전히 event_type 자유텍스트 휴리스틱이라 완전한 분류는 못 한다.
_GEOPOLITICAL_KEYWORDS = (
    "geopolitical", "지정학", "war", "conflict", "분쟁", "전쟁",
    "sanction", "제재", "embargo", "금수",
    "export control", "export ban", "export restriction", "export_control",
    "수출통제", "수출금지", "수출규제",
    "trade restriction", "무역제재", "무역규제", "tariff", "관세",
    "resource nationalism", "자원무기화", "자원민족주의",
    # "ban"/"quota" 단독 키워드 — 이 데이터셋은 핵심광물 뉴스 코퍼스로 범위가
    # 좁아 오탐 위험이 낮다고 보고 포함(예: "Zimbabwe's raw lithium ban").
    "ban", "quota", "쿼터",
)
#: 국내 행정절차성 이벤트(광산 인허가·생산정책 등)는 "policy"/"protest"가
#: 섞여 있어도 지정학적으로 보지 않는다 — 이런 이벤트는 대개 target이
#: supply/production류라 아래 _SUPPLY_TARGETS로 정확히 걸린다. 시위·사회갈등
#: (protest/unrest)은 화면기획 산업영향 정의("ESG 리스크")에 더 가까워
#: 지정학적에서 뺐다(전쟁·수출통제처럼 국가간 갈등이 아니라 개별 프로젝트
#: 단위 이슈이기 때문).
_SUPPLY_TARGETS = {"supply", "production", "resource", "resource_base", "volume", "inventory"}
_MARKET_TARGETS = {"price", "market", "market_value", "market_size"}
_INDUSTRY_IMPACT_KEYWORDS = ("protest", "unrest", "환경", "시위", "사회", "esg")


def _compile_keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """단일 영단어(공백 없음)는 `\\bword\\b`로, 그 외(구·한글)는 그대로 substring
    매칭한다 — 단일 영단어를 substring으로 찾으면 "ban"이 "Kabanga"(지명)
    안에서 걸리는 식의 오탐이 생긴다(실측 확인, Tanzania Kabanga 니켈 사례)."""

    parts = [
        rf"\b{re.escape(kw)}\b" if kw.isascii() and " " not in kw else re.escape(kw)
        for kw in keywords
    ]
    return re.compile("|".join(parts), flags=re.IGNORECASE)


_GEOPOLITICAL_PATTERN = _compile_keyword_pattern(_GEOPOLITICAL_KEYWORDS)

#: 리스크 카테고리 → 대응전략 후보(화면기획 13p 5개 문구, 카테고리 배정은 초안).
RESPONSE_STRATEGY_CATALOG: dict[str, list[str]] = {
    "지정학적": ["해외수입선의 다변화", "위기대응체계 고도화 추진"],
    "공급망": ["해외자원개발 확대", "국가 비축 확대"],
    "시장": ["핵심광물 모니터링 강화"],
    "산업영향": ["국가 비축 확대", "핵심광물 모니터링 강화"],
}


def _classify_risk_category(event_type: str, target: str, evidence_quote: str = "") -> str:
    et = (event_type or "").lower()
    tg = (target or "").lower()
    # event_type 라벨이 일반적(예: 'policy')이어도 evidence_quote 본문에 실제
    # 수출통제·금수 신호가 있는 사례가 실측으로 확인됐다(예: "Zimbabwe's raw
    # lithium ban" — event_type='policy'뿐이라 라벨만으론 안 잡힘, 과거 화면
    # 기획서 예시의 "짐바브웨 리튬 정광 금수조치"와 같은 유형). 그래서 지정학적
    # 키워드만 evidence_quote까지 함께 본다(다른 카테고리는 오탐 위험이 커서
    # event_type만 본다).
    # event_type이 'geopolitical_competition'처럼 언더스코어 복합어인 경우가
    # 흔한데, "_"는 regex \b 기준으로 단어문자라 경계가 안 생겨 매칭이 깨진다
    # (실측 확인) — 공백으로 치환해 \b가 정상적으로 단어를 나눠 인식하게 한다.
    combined = f"{et} {(evidence_quote or '').lower()}".replace("_", " ")
    if _GEOPOLITICAL_PATTERN.search(combined):
        return "지정학적"
    # target만으로는 시위·환경이슈도 대개 supply/production으로 잡혀 공급망에
    # 묻힌다 — event_type에 이런 신호가 있으면 target보다 먼저 산업영향으로 뺀다.
    if any(k in et for k in _INDUSTRY_IMPACT_KEYWORDS):
        return "산업영향"
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
            category = _classify_risk_category(
                event.get("event_type", ""), event.get("target", ""), event.get("evidence_quote", "")
            )
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
