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
DB_PATH = os.environ.get("MSR_DB", str(PROC / "minerals.duckdb"))  # 공유 볼륨/서버DB 주입용
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
    "REE":{"ko": "네오디뮴","en": "Neodymium"},  # REE 대상 1종 = Nd(2026-07-02 확정). HS바스켓 9코드(2805.30·2846.90·8505.11)
}
# HS코드 -> 광종 매핑 파일(감사·검증본). data/raw 에 두거나 절대경로 지정.
HS_MAP_CSV = os.environ.get("HS_MAP_CSV", str(RAW / "hs_commodity_map.csv"))

# ECOS 주요 시계열 (StatisticSearch용). 2026-07-01 web 실수집으로 코드·기간·item 검증 완료.
#   dict: stat / cycle(A·Q·M) / start·end(주기별 형식) / item1 / item2
#   - 산업생산: 901Y033/M, A00(전산업생산지수 농림어업제외), item2=1(원계열; 2는 계절조정)
#   - 실질GDP: 200Y102/Q, item1=10211(실질·원계열·전년동기비 %)
ECOS_SERIES = {
    "KR_industrial_production": {"stat": "901Y033", "cycle": "M",
                                 "start": "201001", "end": "202512",
                                 "item1": "A00", "item2": "1"},
    "KR_gdp_real":             {"stat": "200Y102", "cycle": "Q",
                                 "start": "2010Q1", "end": "2026Q1",
                                 "item1": "10211", "item2": ""},
}
