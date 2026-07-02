# -*- coding: utf-8 -*-
"""데이터 계약(pydantic). [1]→[2]=ManifestRecord, [2]→[3]=GeoEvent."""
from __future__ import annotations
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field

COMMODITIES = ("CU", "NI", "LI", "CO", "REE")
Commodity = Literal["CU", "NI", "LI", "CO", "REE"]
Direction = Literal["supply_down", "supply_up", "price_up", "price_down", "neutral"]
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
    commodity_hint: Optional[str] = None
    fmt: str = ""                    # pdf/hwp/xlsx
    n_chars: int = 0
    status: str = "archived"         # archived/failed/unclassified/duplicate
    ingested_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    error_msg: str = ""


class GeoEvent(BaseModel):
    """[2] 추출 산출. 지수([3])의 원자 레코드."""
    event_id: str
    doc_id: str
    commodity: Commodity
    country: Optional[str] = None
    event_type: str                  # 수출규제/제재/파업/분쟁/재해/정책/증설/감산/가격전망 ...
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
    analyzed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))


class IndexConfig(BaseModel):
    """[3] 지수 공식 파라미터(index.yaml)."""
    half_life_weeks: float = 4.0
    half_life_months: float = 3.0
    normalize: Literal["zscore", "minmax0_100"] = "minmax0_100"
    direction_sign: dict = Field(default_factory=lambda: {
        "supply_down": 1.0, "price_up": 1.0, "supply_up": -0.5,
        "price_down": -0.5, "neutral": 0.2})
    # 발행처 신뢰도·공급집중 가중은 sources.yaml / HHI에서 로드
