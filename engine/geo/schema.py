# -*- coding: utf-8 -*-
"""데이터 계약(pydantic). [1]→[2]=ManifestRecord, [2]→[3]=GeoEvent."""
from __future__ import annotations
from typing import Optional, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, Field

COMMODITIES = ("CU", "NI", "LI", "CO", "REE")
Commodity = Literal["CU", "NI", "LI", "CO", "REE"]
Direction = Literal["supply_down", "supply_up", "price_up", "price_down", "neutral",
                    "demand_up", "demand_down"]
# demand_up/demand_down은 2026-07-18까지 이 Literal에 없었으나 실제 DB에는 이미 3,214건
# (demand_up 2,019 · demand_down 1,195) 존재 — LLM이 유효하게 판단해 왔음에도 검증 계약에서
# 빠져 있던 스키마 드리프트를 바로잡음(A-5 라벨 품질 검증 표본 구성 중 발견).
Target = Literal["supply", "price", "production", "demand", "mixed"]
Category = Literal["주간동향", "월간전망", "수급밸런스", "가격", "정책·규제", "지정학·뉴스", "기타"]


class ManifestRecord(BaseModel):
    """[1] 입력·정리 원장. inbox→archive 이동 이력."""
    doc_id: str                      # file_hash[:16]
    file_hash: str
    orig_name: str
    archive_path: str
    source: str                      # 발행처 (WoodMac/KOMIS/AsianMetal/Argus/IEA/ETC)
    category: str = "기타"
    pub_date: Optional[str] = None   # YYYY-MM-DD
    pub_date_method: str = "filename"  # filename/pdf_metadata/content/source_default/unresolved
    commodity_hint: Optional[str] = None
    fmt: str = ""                    # pdf/hwp/xlsx
    n_chars: int = 0
    status: str = "archived"         # archived/failed/unclassified/duplicate
    ingested_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    error_msg: str = ""


class GeoEvent(BaseModel):
    """[2] 추출 산출. 지수([3])의 원자 레코드."""
    event_id: str
    doc_id: str
    commodity: Commodity
    country: Optional[str] = None
    event_type: str                  # 수출규제/제재/파업/분쟁/재해/정책/증설/감산/가격전망 ...
    dimension: Optional[str] = None  # 경보 계열2(시설·수송) 판별용, event_type 규칙매핑으로 후행
                                      # 산출(추출 시점 미설정) — ops/corridor/trade/input/policy 중 하나.
                                      # 값 정의·매핑 규칙: geo/dimension.py (피드백기반_수정플랜 A-2,
                                      # 2026-07-16). 기존 event 백필은 update_geo_event_dimension.py.
    direction: Direction = "neutral"
    target: Target = "mixed"
    severity: float = Field(0, ge=0, le=3)      # 0=배경 1=경미 2=중대 3=심각
    horizon_months: Optional[int] = None
    obs_date: Optional[str] = None              # 사건 시점 YYYY-MM-DD
    confidence: float = Field(0.5, ge=0, le=1)
    evidence_quote: str = ""
    # provenance
    extractor: str = "rule"          # rule/llm/mock
    provider: str = ""               # openai_compat/anthropic/...
    model: str = ""
    prompt_version: str = ""
    schema_version: str = "1.0"
    analyzed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class IndexConfig(BaseModel):
    """[3] 지수 공식 파라미터(index.yaml)."""
    half_life_weeks: float = 4.0
    half_life_months: float = 3.0
    # tanh0_100: index = 50 + 50·tanh(raw/scale_k). 절대 스케일(히스토리 불변·광종 간 비교 가능).
    #   0=강한 호재, 50=중립(이벤트 없음), 100=심각. 새 기간이 와도 과거 지수가 재척도되지 않음.
    # minmax0_100(구): 광종별 자기 히스토리 min-max — 매 실행 전체 재척도되는 결함으로 비권장.
    normalize: Literal["tanh0_100", "zscore", "minmax0_100"] = "tanh0_100"
    scale_k: float = 10.0            # tanh 스케일(대략 '심각 수준' raw 크기) — 폴백/기본값
    # 광종별 스케일(2026-07-12 도입): GKG는 CU/NI만 전용 테마코드가 있어 광종 간 raw_score
    # 규모가 최대 70배 차이(실측 P50: CU 220 vs LI 3) — 단일 k로는 CU 포화·LI/CO/REE 무반응.
    # 각 광종의 2016~2026 전체 주간 |raw_score| P90을 k로 앵커링(P90 주간=지수 88) 후 동결 —
    # 동결이므로 절대 스케일(발행값 불변) 성질은 유지된다. 비어 있으면 scale_k 단일값 사용.
    scale_k_by_commodity: dict = Field(default_factory=dict)
    direction_sign: dict = Field(default_factory=lambda: {
        "supply_down": 1.0, "price_up": 1.0, "supply_up": -0.5,
        "price_down": -0.5, "neutral": 0.2})
    # 발행처 신뢰도·공급집중 가중은 sources.yaml / HHI에서 로드
