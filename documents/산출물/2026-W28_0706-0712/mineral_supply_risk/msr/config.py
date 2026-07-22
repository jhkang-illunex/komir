# -*- coding: utf-8 -*-
"""전역 설정 · 상수 · 키 로드"""
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"; RAW = DATA/"raw"; INTERIM = DATA/"interim"; PROC = DATA/"processed"
OUT = ROOT / "outputs"
DB_PATH = str(PROC / "minerals.duckdb")
for p in (RAW, INTERIM, PROC, OUT): p.mkdir(parents=True, exist_ok=True)

# 인증키
DATA_GO_KR_KEY_ENC = os.environ.get("DATA_GO_KR_SERVICE_KEY_ENCODING", "")
DATA_GO_KR_KEY_DEC = os.environ.get("DATA_GO_KR_SERVICE_KEY_DECODING", "")
ECOS_API_KEY = os.environ.get("ECOS_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# 5대 핵심광물
CORE_COMMODITIES = {
    "CU": {"ko": "동",   "en": "Copper"},
    "NI": {"ko": "니켈", "en": "Nickel"},
    "LI": {"ko": "리튬", "en": "Lithium"},
    "CO": {"ko": "코발트","en": "Cobalt"},
    "REE":{"ko": "희토류","en": "Rare earths"},
}
# HS코드 -> 광종 매핑 파일(감사·검증본). data/raw 에 두거나 절대경로 지정.
HS_MAP_CSV = os.environ.get("HS_MAP_CSV", str(RAW / "hs_commodity_map.csv"))

# ECOS 주요 시계열 코드 (StatisticSearch용). 정확 코드는 msr.collectors.ecos_api.search_* 로 확인·보정.
ECOS_SERIES = {
    # name: (stat_code, cycle, item_code1)  — cycle: A/Q/M
    # ✅ 검증완료(web): 전산업생산지수(농림어업제외) 원계열, 월간 200001~
    "KR_industrial_production": ("901Y033", "M", "A00"),
    # ⚠️ 실행 전 `python -m scripts.run ecos-search 국민계정`으로 코드·item 확인 권장
    "KR_gdp_real":             ("200Y102", "Q", ""),
}
