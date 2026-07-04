# -*- coding: utf-8 -*-
"""
한국은행 ECOS OpenAPI 수집기 (JSON)
 - StatisticSearch: 시계열 조회
 - 헬퍼: search_tables(kw), search_items(stat_code)  — 정확한 코드 탐색용
"""
import requests, pandas as pd
from ..config import ECOS_API_KEY
BASE = "https://ecos.bok.or.kr/api"

def _get(path):
    r = requests.get(f"{BASE}/{path}", timeout=30); r.raise_for_status()
    j = r.json()
    # ECOS는 HTTP 200 + {"RESULT":{"CODE":..,"MESSAGE":..}} 로 에러/무자료를 알림.
    # INFO-200(해당 자료 없음)은 정상적 빈 결과로 처리, 그 외 코드는 예외로 표면화.
    res = j.get("RESULT")
    if isinstance(res, dict) and res.get("CODE"):
        code, msg = res.get("CODE"), res.get("MESSAGE", "")
        if str(code).upper() == "INFO-200":
            return {}
        raise RuntimeError(f"ECOS API error {code}: {msg}")
    return j

def search_tables(keyword="", start=1, end=100):
    j = _get(f"StatisticTableList/{ECOS_API_KEY}/json/kr/{start}/{end}/")
    rows = j.get("StatisticTableList", {}).get("row", [])
    df = pd.DataFrame(rows)
    if keyword and not df.empty:
        df = df[df["STAT_NAME"].str.contains(keyword, na=False)]
    return df

def search_items(stat_code, start=1, end=100):
    j = _get(f"StatisticItemList/{ECOS_API_KEY}/json/kr/{start}/{end}/{stat_code}/")
    return pd.DataFrame(j.get("StatisticItemList", {}).get("row", []))

def fetch_series(stat_code, cycle, start, end, item1="", item2="", item3="", n=10000):
    """cycle: A/Q/M/D. start/end: 형식 맞춰(연 YYYY, 분기 YYYYQn→YYYYQ, 월 YYYYMM)."""
    path = f"StatisticSearch/{ECOS_API_KEY}/json/kr/1/{n}/{stat_code}/{cycle}/{start}/{end}/{item1}/{item2}/{item3}/"
    j = _get(path)
    rows = j.get("StatisticSearch", {}).get("row", [])
    if len(rows) >= n:   # 단일 페이지 상한 도달 → 절단 가능(페이지네이션 필요)
        print(f"  [warn] ECOS {stat_code}: {len(rows)}행 = 상한(n={n}) 도달 → 절단 가능(기간/주기 축소 또는 페이지 처리 필요)")
    df = pd.DataFrame(rows)
    if not df.empty:
        df["DATA_VALUE"] = pd.to_numeric(df["DATA_VALUE"], errors="coerce")
    return df

def key_statistics():
    j = _get(f"KeyStatisticList/{ECOS_API_KEY}/json/kr/1/100/")
    return pd.DataFrame(j.get("KeyStatisticList", {}).get("row", []))
