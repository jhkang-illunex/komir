"""광종 마스터(`public.ai_mnrl_mst`) 조회 — report_demo 드롭다운 전용.

report_gen API 자체엔 광종 목록 엔드포인트가 없어(라우트 전수 확인, 2026-08-27)
`data_admin.py`와 같은 패턴으로 Postgres를 직접 읽는다. `mnrknd_unq_cd`가
"MNRL00xx" 형태인 행만 실제 API가 받는 광종코드다(레거시 2글자 코드 CU/NI 등은
`use_yn='N'`이라 자동 제외됨, 실측 확인).

2026-08-31 삭제: `prc_cat_cd` 기반 비철금속/희소금속 그룹 분류(`mineral_options`의
`group` 필터)는 시장동향지표(indicator_market) 전용 UI 분리를 위해 있었는데,
그 UI 자체가 실제 KOMIS 화면 구조에 안 맞아 걷어내면서(§report_demo.py 참고)
같이 죽은 코드가 됐다 — 삭제.

2026-08-31 재도입(사용자 지시): 광물자원가격 4개 서브메뉴(비철금속/희소금속/
철광석 및 에너지/기타)는 실제 KOMIS에서도 서로 다른 광종 집합이라(§komis_fetch.py
BASE_METALS_CODES와 DB `prc_cat_cd` 값이 정확히 일치함을 확인) 서브메뉴가
바뀌면 광종·비교광종 드롭다운도 그 서브메뉴 소속 광종만 보여야 한다. 이번엔
indicator_market과 달리 실제로 KOMIS 구조에 대응되는 분류라 삭제 대상이 아니다
— `PRICE_CATEGORY_BY_PAGE`로 page_id→prc_cat_cd(HP001~004) 매핑."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

_log = logging.getLogger(__name__)


# DB 실측(2026-08-31): public.ai_mnrl_mst.prc_cat_cd 값 HP001~HP004가
# komis_fetch.py의 getMnrlPriceCrtr HP000 파라미터(HP001=비철/HP002=희소/
# HP003=철광석·에너지/HP004=기타)와 정확히 일치 — KOMIS 자체 분류 코드다.
PRICE_CATEGORY_BY_PAGE = {
    "price_base_metals": "HP001",
    "price_minor_metals": "HP002",
    "price_iron_energy": "HP003",
    "price_other": "HP004",
}


@st.cache_data(ttl=300, show_spinner="광종 목록을 불러오는 중…")
def load_minerals() -> list[dict]:
    """[{code, name_ko, name_en, prc_cat_cd}, ...] — 정렬순(sort_ordr). 실패하면
    빈 리스트(호출부가 코드 직접입력으로 폴백)."""

    try:
        from shared.db import read_sql_pg
    except Exception:
        _log.exception("shared.db import 실패 — 광종 목록 없이 코드 직접입력으로 폴백")
        return []
    try:
        df = read_sql_pg(
            "SELECT mnrknd_unq_cd AS code, mnrl_nm_ko AS name_ko, mnrl_nm_en AS name_en, "
            "prc_cat_cd FROM public.ai_mnrl_mst WHERE use_yn = 'Y' ORDER BY sort_ordr"
        )
    except Exception:
        _log.exception("public.ai_mnrl_mst 조회 실패 — 광종 목록 없이 코드 직접입력으로 폴백")
        return []
    return [
        {"code": row.code, "name_ko": row.name_ko, "name_en": row.name_en, "prc_cat_cd": row.prc_cat_cd}
        for row in df.itertuples()
    ]


def mineral_options() -> list[dict]:
    return load_minerals()


def mineral_options_for_page(page_id: str) -> list[dict]:
    """광물자원가격 4종(price_*)이면 그 서브메뉴 소속 광종만, 아니면 전체 목록을
    반환한다 — §모듈 docstring 2026-08-31 재도입 참고."""
    options = load_minerals()
    prc_cat_cd = PRICE_CATEGORY_BY_PAGE.get(page_id)
    if prc_cat_cd is None:
        return options
    return [m for m in options if m["prc_cat_cd"] == prc_cat_cd]


def mineral_label(m: dict) -> str:
    return f"{m['name_ko']} ({m['code']})"
