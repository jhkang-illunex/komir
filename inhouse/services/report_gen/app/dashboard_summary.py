# -*- coding: utf-8 -*-
"""화면기획안 ver.1.3 "텍스트 보고서" 화면 2종 생성기 (2026-08-19 신설).

대상 화면(원본 PDF `documents/기획문서/260731 핵심광물 수급위기 진단 화면 기획안
ver.1.3.pdf`, p.4·p.11·p.18·p.24 실측 확인 — 슬라이드 문구 그대로 스키마화):
  - A화면(종합 모니터링) §6 "AI 보고서 다운로드" + §13 "AI 종합분석 및 관련뉴스"
    → scope='overall'(광종 구분 없음, 5광종 통합 1행)
  - B화면(광종별 모니터링) Step6 §21 "AI 종합판단"
    → scope='commodity'(광종별 1행 × 5)

원칙(report_gen/app/analysis/summary.py의 "LLM 정제 + 규칙기반 폴백"과 동일):
  숫자(crisis_index·wow_delta·key_factor_contrib)는 전부 이미 검증된 원천
  (out_diagnosis_alert·geo_index·geo_prob·out_import_forecast_unit·geo_event)에서
  그대로 가져온다 — LLM은 그 숫자를 근거로 서술만 만든다(숫자를 지어내지 않음).
  LLM 실패(장애·스키마 검증 실패)해도 규칙기반 문장으로 폴백해 항상 행이 생성된다.

실행: cd inhouse/services/report_gen && python -m app.dashboard_summary
      (MSR_DB env로 대상 DB 지정, .env 기본값은 duckdb)
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel, Field

from ._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import read_sql_msr, upsert_df_msr  # noqa: E402
from shared.config import get_settings  # noqa: E402

CCS = ["CU", "NI", "CO", "LI", "REE"]
CC_KO = {"CU": "동", "NI": "니켈", "CO": "코발트", "LI": "리튬", "REE": "네오디뮴"}
MODEL_VERSION = "dashboard_summary_v1(2026-08-19, out_diagnosis_alert+geo+forecast 원천)"


# ─────────────────────────── LLM 구조화 출력 스키마 ───────────────────────────
class RiskTag(BaseModel):
    tag: str = Field(description="리스크 유형 키워드 1~4자(예: 지정학적, 공급망, 가격변동)")
    evidence: str = Field(description="그 태그의 구체적 근거 1문장(제공된 사실만 사용)")


class NewsItem(BaseModel):
    commodity_code: str
    headline: str = Field(description="25자 내외 핵심 결론 1줄")
    driver_up: str = Field(description="가격을 움직인 주된 요인(상승 또는 하락 압력)")
    driver_down: str | None = Field(default=None, description="반대요인/제약요인, 없으면 null")


class OverallNarrative(BaseModel):
    diagnosis_text: str = Field(description="현황 서술 1~2문장, 종합위기지수·전주대비 수치 인용")
    risk_tags: list[RiskTag]
    response_strategies: list[str] = Field(description="대응전략 문구 2~5개")
    weekly_news: list[NewsItem] = Field(description="5광종 각 1건씩 총 5건")


class CommodityNarrative(BaseModel):
    ai_comment: str = Field(description="AI 종합분석 코멘트 2~3문장, 제공된 수치·이벤트만 근거로")
    risk_tags: list[RiskTag]
    supply_chain_summary: str = Field(description="수입 의존국 구조 요약 1~2문장")
    event_news_summary: str = Field(description="최근 위기 이벤트 요약 1~2문장, 이벤트 없으면 그렇게 서술")


# ─────────────────────────── 원천 데이터 조회(전부 read_sql_msr, SELECT만) ───────────────────────────
def _latest_alerts() -> pd.DataFrame:
    df = read_sql_msr(
        """SELECT commodity_code, obs_date, alert_level AS alert_name, risk_score AS crisis_index,
        evidence_json FROM out_diagnosis_alert ORDER BY commodity_code, obs_date"""
    )
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def _latest_geo() -> pd.DataFrame:
    df = read_sql_msr(
        """SELECT commodity_code, CAST(period AS DATE) AS week, CAST(idx_value AS DOUBLE PRECISION) idx_value
        FROM geo_index WHERE freq='W' ORDER BY commodity_code, week"""
    )
    df["week"] = pd.to_datetime(df["week"])
    return df


def _latest_forecast() -> pd.DataFrame:
    try:
        return read_sql_msr(
            """SELECT commodity_code, target_month, h, pred_ton, pred_unit_usd_per_ton
            FROM out_import_forecast_unit WHERE h=1"""
        )
    except Exception:
        return pd.DataFrame(columns=["commodity_code", "target_month", "h", "pred_ton", "pred_unit_usd_per_ton"])


def _recent_events(commodity_code: str | None, limit: int = 5) -> pd.DataFrame:
    where = "severity >= 2 AND direction = 'supply_down'"
    if commodity_code:
        where += f" AND commodity_code = '{commodity_code}'"
    df = read_sql_msr(
        f"""SELECT commodity_code, obs_date, event_type, country, severity, evidence_quote
        FROM geo_event WHERE {where} ORDER BY obs_date DESC LIMIT {int(limit)}"""
    )
    return df


def _wow_delta(alerts: pd.DataFrame, cc: str) -> float | None:
    g = alerts[alerts["commodity_code"] == cc].sort_values("obs_date")
    if len(g) < 2:
        return None
    a, b = g["crisis_index"].iloc[-1], g["crisis_index"].iloc[-2]
    if pd.isna(a) or pd.isna(b):
        return None
    return round(float(a) - float(b), 2)


# ─────────────────────────── 규칙기반 폴백 서술 ───────────────────────────
def _fallback_overall(period_week: date, ci_mean: float, deltas: dict) -> OverallNarrative:
    worst = max(deltas.items(), key=lambda kv: (kv[1] or -999))
    return OverallNarrative(
        diagnosis_text=(
            f"{period_week:%Y-%m-%d} 기준 5광종 평균 위기지수는 {ci_mean:.1f}이며, "
            f"전주 대비 변화가 가장 큰 광종은 {CC_KO.get(worst[0], worst[0])}({worst[1]:+.1f}p)입니다."
        ),
        risk_tags=[RiskTag(tag="자동생성", evidence="LLM 생성 실패로 규칙기반 요약만 제공됨")],
        response_strategies=["핵심광물 모니터링 강화", "위기대응체계 고도화 추진"],
        weekly_news=[
            NewsItem(commodity_code=cc, headline=f"{CC_KO.get(cc, cc)} 위기지수 변화 데이터 확인 필요",
                      driver_up="LLM 미생성 — out_diagnosis_alert 원자료 직접 확인 권장")
            for cc in CCS
        ],
    )


def _fallback_commodity(cc: str, alert_name: str, ci: float) -> CommodityNarrative:
    return CommodityNarrative(
        ai_comment=f"{CC_KO.get(cc, cc)}의 현재 경보 단계는 '{alert_name}'(위기지수 {ci:.1f})입니다. "
                   "LLM 서술 생성에 실패해 규칙기반 요약만 제공됩니다.",
        risk_tags=[RiskTag(tag="자동생성", evidence="LLM 생성 실패로 규칙기반 요약만 제공됨")],
        supply_chain_summary="원자료(agg_trade_annual) 직접 확인이 필요합니다.",
        event_news_summary="원자료(geo_event) 직접 확인이 필요합니다.",
    )


# ─────────────────────────── LLM 호출(공용) ───────────────────────────
def _call_llm(task: str, instructions: str, payload: dict, output_model, fallback):
    try:
        from shared.llm_client import KomirJsonLLM, LLMError

        llm = KomirJsonLLM()
        invocation = llm.invoke(task=task, instructions=instructions, payload=payload,
                                 output_model=output_model, max_tokens=1200)
        return invocation.output, True
    except (Exception,):  # noqa: BLE001 — LLMError/RuntimeError/OSError 전부 폴백 대상
        return fallback(), False


# ─────────────────────────── 생성기 ───────────────────────────
def generate_overall(period_week: date | None = None) -> dict:
    alerts = _latest_alerts()
    geo = _latest_geo()
    latest_by_cc = alerts.sort_values("obs_date").groupby("commodity_code").tail(1).set_index("commodity_code")
    period_week = period_week or latest_by_cc["obs_date"].max().date()

    ci_mean = float(latest_by_cc["crisis_index"].mean())
    deltas = {cc: _wow_delta(alerts, cc) for cc in CCS if cc in latest_by_cc.index}
    events = _recent_events(None, limit=8)

    payload = {
        "period_week": str(period_week),
        "commodities": [
            {
                "commodity_code": cc, "name_ko": CC_KO[cc],
                "alert_name": latest_by_cc.loc[cc, "alert_name"] if cc in latest_by_cc.index else None,
                "crisis_index": round(float(latest_by_cc.loc[cc, "crisis_index"]), 1) if cc in latest_by_cc.index else None,
                "wow_delta": deltas.get(cc),
                "geo_index_latest": round(float(geo[geo.commodity_code == cc]["idx_value"].iloc[-1]), 1)
                if len(geo[geo.commodity_code == cc]) else None,
            }
            for cc in CCS
        ],
        "recent_high_severity_events": [
            {"commodity_code": r.commodity_code, "country": r.country, "event_type": r.event_type,
             "evidence_quote": str(r.evidence_quote)[:200]}
            for r in events.itertuples()
        ],
    }
    instructions = (
        "너는 핵심광물 공급망 위기 모니터링 대시보드의 '종합 진단' 섹션을 작성하는 애널리스트다. "
        "제공된 payload의 수치·이벤트만 근거로 사용하고 새로운 숫자를 만들어내지 마라. "
        "diagnosis_text는 '현황'을 요약하고(수치 인용 필수), risk_tags는 crisis_index가 높거나 "
        "wow_delta가 큰 광종·최근 이벤트에서 뽑아라. weekly_news는 5광종 각 1건씩, headline은 "
        "25자 내외로 압축하고 driver_up/driver_down은 payload에 근거가 없으면 '데이터 부족'이라고 써라."
    )
    narrative, llm_refined = _call_llm(
        "dashboard_overall", instructions, payload, OverallNarrative,
        lambda: _fallback_overall(period_week, ci_mean, deltas),
    )

    row = {
        "summary_id": uuid.uuid5(uuid.NAMESPACE_URL, f"dashboard:overall:{period_week}").hex,
        "scope": "overall", "commodity_code": None, "period_week": period_week,
        "alert_level": None, "crisis_index": round(ci_mean, 2), "wow_delta": None,
        "diagnosis_text": narrative.diagnosis_text[:2000],
        "ai_comment": None,
        "risk_tags_json": json.dumps([t.model_dump() for t in narrative.risk_tags], ensure_ascii=False)[:2000],
        "response_strategies_json": json.dumps(narrative.response_strategies, ensure_ascii=False)[:1000],
        "key_factor_contrib_json": None,
        "weekly_news_json": json.dumps([n.model_dump() for n in narrative.weekly_news], ensure_ascii=False)[:4000],
        "supply_chain_summary": None, "event_news_summary": None,
        "llm_refined": llm_refined, "model_version": MODEL_VERSION,
        "generated_at": datetime.utcnow(),
    }
    return row


def generate_commodity(cc: str, period_week: date | None = None) -> dict:
    alerts = _latest_alerts()
    g = alerts[alerts["commodity_code"] == cc].sort_values("obs_date")
    if g.empty:
        raise ValueError(f"{cc}: out_diagnosis_alert에 데이터 없음")
    latest = g.iloc[-1]
    period_week = period_week or latest["obs_date"].date()
    ci = float(latest["crisis_index"])
    delta = _wow_delta(alerts, cc)

    evidence = json.loads(latest["evidence_json"]) if latest.get("evidence_json") else {}
    contrib = evidence.get("contrib", {})
    top_contrib = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:6]

    geo = _latest_geo()
    geo_g = geo[geo.commodity_code == cc]
    geo_latest = round(float(geo_g["idx_value"].iloc[-1]), 1) if len(geo_g) else None

    fc = _latest_forecast()
    fc_g = fc[fc.commodity_code == cc]
    fc_row = fc_g.iloc[0].to_dict() if len(fc_g) else None

    events = _recent_events(cc, limit=5)

    payload = {
        "commodity_code": cc, "name_ko": CC_KO.get(cc, cc), "period_week": str(period_week),
        "alert_name": latest["alert_name"], "crisis_index": round(ci, 1), "wow_delta": delta,
        "geo_index_latest": geo_latest,
        "top_contrib_factors": [{"factor": k, "value": v} for k, v in top_contrib],
        "forecast_h1": ({"target_month": str(fc_row["target_month"]), "pred_ton": round(float(fc_row["pred_ton"]), 1)}
                        if fc_row else None),
        "recent_high_severity_events": [
            {"country": r.country, "event_type": r.event_type, "evidence_quote": str(r.evidence_quote)[:200]}
            for r in events.itertuples()
        ],
    }
    instructions = (
        "너는 특정 핵심광물 1종의 'AI 종합판단' 섹션을 작성하는 애널리스트다. "
        "제공된 payload의 수치·이벤트만 근거로 쓰고 새 숫자를 만들지 마라. "
        "ai_comment는 현재 경보 단계·위기지수·전주대비·주요 기여요인을 종합해 2~3문장으로, "
        "risk_tags는 top_contrib_factors와 최근 이벤트에서, supply_chain_summary는 이벤트/기여요인 중 "
        "수입구조 관련 신호가 있으면 언급하고 없으면 '뚜렷한 신규 신호 없음'이라고 써라. "
        "event_news_summary는 recent_high_severity_events가 비어있으면 '최근 고심각도 이벤트 없음'이라고 써라."
    )
    narrative, llm_refined = _call_llm(
        f"dashboard_commodity_{cc}", instructions, payload, CommodityNarrative,
        lambda: _fallback_commodity(cc, latest["alert_name"], ci),
    )

    row = {
        "summary_id": uuid.uuid5(uuid.NAMESPACE_URL, f"dashboard:commodity:{cc}:{period_week}").hex,
        "scope": "commodity", "commodity_code": cc, "period_week": period_week,
        "alert_level": latest["alert_name"], "crisis_index": round(ci, 2), "wow_delta": delta,
        "diagnosis_text": None,
        "ai_comment": narrative.ai_comment[:2000],
        "risk_tags_json": json.dumps([t.model_dump() for t in narrative.risk_tags], ensure_ascii=False)[:2000],
        "response_strategies_json": None,
        "key_factor_contrib_json": json.dumps(
            [{"factor": k, "value": v} for k, v in top_contrib], ensure_ascii=False)[:1000],
        "weekly_news_json": None,
        "supply_chain_summary": narrative.supply_chain_summary[:1500],
        "event_news_summary": narrative.event_news_summary[:1500],
        "llm_refined": llm_refined, "model_version": MODEL_VERSION,
        "generated_at": datetime.utcnow(),
    }
    return row


def run(period_week: date | None = None) -> dict:
    """overall 1행 + commodity 5행을 생성해 out_ai_dashboard_summary에 upsert.
    del_where는 같은 (scope, commodity_code, period_week) 조합의 과거 실행분만 지운다
    (summary_id가 그 조합의 결정적 해시라 재실행해도 같은 행을 덮어씀 — 멱등)."""

    rows = [generate_overall(period_week)]
    for cc in CCS:
        try:
            rows.append(generate_commodity(cc, period_week))
        except ValueError as e:
            print(f"  [skip] {cc}: {e}")

    df = pd.DataFrame(rows)
    n_llm = int(df["llm_refined"].sum())
    ids = "','".join(df["summary_id"])
    upsert_df_msr(df, "out_ai_dashboard_summary", del_where=f"summary_id IN ('{ids}')")
    print(f"[dashboard-summary] {len(df)}행 적재(LLM 서술 {n_llm}/{len(df)}) — "
          f"MSR_DB={get_settings().MSR_DB}")
    return {"rows": len(df), "llm_refined": n_llm}


if __name__ == "__main__":
    run()
