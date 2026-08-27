"""광종 마스터(`public.ai_mnrl_mst`) 조회 — report_demo 드롭다운 전용.

report_gen API 자체엔 광종 목록 엔드포인트가 없어(라우트 전수 확인, 2026-08-27)
`data_admin.py`와 같은 패턴으로 Postgres를 직접 읽는다. `mnrknd_unq_cd`가
"MNRL00xx" 형태인 행만 실제 API가 받는 광종코드다(레거시 2글자 코드 CU/NI 등은
`use_yn='N'`이라 자동 제외됨, 실측 확인).

`prc_cat_cd == 'HP001'`이 비철금속(니켈·동·아연·알루미늄·연·주석 6종, 실측으로
`report_gen/app/routers/report_data.py`의 "비철금속(LME, 니켈·동·아연·알루미늄·
연·주석)" 문구와 정확히 일치 확인) — 그 외(HP002~004)는 희소금속으로 묶는다.
이 매핑은 `ai_mnrl_mst`에 "비철금속"/"희소금속" 문자열 컬럼이 없어서 코드값으로
역산한 것이라, `ai_mnrl_mst`의 `prc_cat_cd` 체계가 바뀌면 같이 갱신해야 한다."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Literal

import streamlit as st

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

_log = logging.getLogger(__name__)

MineralGroup = Literal["base_metals", "minor_metals"]
_BASE_METALS_PRC_CAT = "HP001"


@st.cache_data(ttl=300, show_spinner="광종 목록을 불러오는 중…")
def load_minerals() -> list[dict]:
    """[{code, name_ko, name_en, group}, ...] — 정렬순(sort_ordr). 실패하면
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
        {
            "code": row.code, "name_ko": row.name_ko, "name_en": row.name_en,
            "group": "base_metals" if row.prc_cat_cd == _BASE_METALS_PRC_CAT else "minor_metals",
        }
        for row in df.itertuples()
    ]


def mineral_options(group: MineralGroup | None = None) -> list[dict]:
    minerals = load_minerals()
    return [m for m in minerals if group is None or m["group"] == group]


def mineral_label(m: dict) -> str:
    return f"{m['name_ko']} ({m['code']})"
