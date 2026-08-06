# -*- coding: utf-8 -*-
"""수집 대상 HS10 목록 — in-house `msr/preprocess/hs_mapping.py`의 `core_hs_list()`만 최소
이식(2026-08-06 물리분리). DMZ는 "무엇을 수집할지"만 알면 되고, HS→광종 라벨 부여
(attach_commodity)는 DB 적재 직전 단계라 in-house 로더가 그대로 담당한다 — 여기서는 절대
하지 않는다(원본 msr/preprocess/hs_mapping.py의 attach_commodity는 이 모듈에 없음, 의도적).

⚠️ data/hs_commodity_map.csv는 inhouse/mineral_supply_risk/data/raw/hs_commodity_map.csv의
동기화 사본이다. 원본이 바뀌면(HS코드 추가/재분류) 이 사본도 같이 갱신해야 수집 대상이
어긋나지 않는다 — 자동 동기화 없음, 수동 확인 필요.
"""
import pandas as pd
from .config import HS_MAP_CSV


def load_map() -> pd.DataFrame:
    m = pd.read_csv(HS_MAP_CSV, dtype=str, encoding="utf-8-sig")
    m.columns = [c.strip() for c in m.columns]
    m["hs10"] = m["hs10"].str.strip()
    return m


def core_hs_list(map_df: pd.DataFrame = None) -> list:
    """5대 광종에 해당하는 HS10 목록 반환(수집 대상). in-house hs_mapping.core_hs_list()와
    동일 로직."""
    m = map_df if map_df is not None else load_map()
    return m[m["is_core5"].astype(str).str.upper().isin(["Y", "TRUE", "1"])]["hs10"].tolist()
