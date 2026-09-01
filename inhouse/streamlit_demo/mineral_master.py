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
— `PRICE_CATEGORY_BY_PAGE`로 page_id→prc_cat_cd(HP001~004) 매핑.

2026-09-01(사용자 지시): 시장동향지표/수급동향지표(indicator_market/supply)는
`ai_mnrl_mst`로 광종을 고르면 안 된다는 게 드러났다 — 이 테이블은 이
프로젝트가 가격·진단 계산에 직접 쓰는 19종(사용 중)뿐인 "AI 설정성" 목록이라,
사용자가 KOMIS 실제 화면에서 확인해 알려준 시장동향지표 39종/수급동향지표
36종(갈륨·규소·니오븀 등, 5대 핵심광물 밖 다수 포함)과 크게 어긋난다(실측:
라이브검증에 쓴 갈륨 MNRL0024조차 `ai_mnrl_mst`엔 없었다). 사용자가 "기존에
있는 광종명 및 코드로 맵핑하자"고 지시해 찾아보니, `services/rag_chat/app/
page_recommend/resources/metadata/komis-metadata.snapshot.json`(2026-07-16
KOMIS 브라우저 실측 프로브 `artifacts/browser/page-probe/metadata-catalog.json`
그대로, report_gen_client.py의 `section` 필드 출처와 같은 registry — report_gen
서버가 쓰는 `services/report_gen/app/analysis/resources/komis-metadata.subset.json`
은 이 전체 스냅샷에서 5개 ref만 추린 파생본이라 아래 map_korea 추가 시점부터
파생본 대신 전체 스냅샷을 직접 읽는다)에 26개 메뉴별 ref로 이미 정본이 있었다
— `KOMIS_METADATA_REGISTRY_PATH`로 이 파일을 그대로 읽어 DB 무관하게 메뉴별
드롭다운을 만든다(ai_mnrl_mst 손 안 댐).

2026-09-01 확장(사용자 제공 목록): 핵심광물지도>수급지도>대한민국(map_korea)도
같은 문제 — 사용자가 알려준 74종(갈륨~황철석, "기타광물"·"인광석" 포함)이
registry의 `metadata.maps.trade_minerals`(73종)와 71종이 정확히 일치해(나머지는
"인"(registry) vs "인광석"(사용자) 표기차 + 사용자쪽 "기타광물" 1건 추가뿐)
이 ref가 정본임을 확인, `_KOMIS_REGISTRY_REF`에 추가했다. map_korea/global(둘 다
KOMIS "수급지도" 하위, HS코드 기반 무역통계)은 같은 광종 집합을 쓸 가능성이 높지만
map_global은 이번 요청 범위 밖이라 아직 안 바꿨다."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import streamlit as st

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

_log = logging.getLogger(__name__)

KOMIS_METADATA_REGISTRY_PATH = (
    _INHOUSE_ROOT / "services" / "rag_chat" / "app" / "page_recommend" / "resources" / "metadata"
    / "komis-metadata.snapshot.json"
)


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
    반환한다 — §모듈 docstring 2026-08-31 재도입 참고.

    indicator_market/indicator_supply/map_korea는 이 함수를 쓰지 않는다 —
    `komis_registry_mineral_options()`(§2026-09-01 docstring 참고)가 대신
    KOMIS 실측 registry로 채운다."""
    options = load_minerals()
    prc_cat_cd = PRICE_CATEGORY_BY_PAGE.get(page_id)
    if prc_cat_cd is None:
        return options
    return [m for m in options if m["prc_cat_cd"] == prc_cat_cd]


_KOMIS_REGISTRY_REF: dict[str, str] = {
    "indicator_market": "metadata.indicators.market_minerals",
    "indicator_supply": "metadata.indicators.supply_minerals",
    "map_korea": "metadata.maps.trade_minerals",
}


@st.cache_data(ttl=300, show_spinner=False)
def komis_registry_mineral_options(page_id: str) -> list[dict]:
    """`ai_mnrl_mst`(DB, 이 프로젝트가 쓰는 19종뿐)로는 부족한 메뉴 전용 —
    KOMIS 실측 registry(§모듈 docstring 2026-09-01)에서 [{code, name_ko}, ...]를
    돌려준다. page_id가 `_KOMIS_REGISTRY_REF`에 없거나 파일을 못 읽으면 빈
    리스트(호출부가 코드 직접입력으로 폴백, §mineral_master.py 기존 관례와 동일)."""

    ref = _KOMIS_REGISTRY_REF.get(page_id)
    if ref is None:
        return []
    try:
        data = json.loads(KOMIS_METADATA_REGISTRY_PATH.read_text(encoding="utf-8"))
        raw_options = data["refs"][ref]["options"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        _log.exception(
            "komis_registry_mineral_options 읽기 실패(page_id=%s, path=%s) — 코드 직접입력으로 폴백",
            page_id, KOMIS_METADATA_REGISTRY_PATH,
        )
        return []
    return [{"code": o["external_value"], "name_ko": o["label"]} for o in raw_options]


def mineral_label(m: dict) -> str:
    return f"{m['name_ko']} ({m['code']})"
