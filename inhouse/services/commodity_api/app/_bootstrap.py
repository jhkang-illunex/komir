# -*- coding: utf-8 -*-
"""`shared/*`와 `mineral_supply_risk` 엔진 패키지(msr/scripts)를 import할 수 있게
sys.path를 잡아준다.

소스트리(`inhouse/services/commodity_api/app/...`)와 컨테이너 배포본
(Containerfile이 평평하게 COPY)의 상대 깊이가 달라 고정 depth 대신 위로 훑어
찾는다 — `services/report_gen/app/_bootstrap.py`·`services/shared/db.py`의
`_find_msr_root`와 같은 패턴(재구현 금지 원칙, 신규 패턴 만들지 않음)."""
from __future__ import annotations

import sys
from pathlib import Path


def ensure_shared_on_path() -> Path:
    """`shared/db.py`를 담은 디렉토리를 sys.path에 넣고 그 경로를 돌려준다."""

    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "shared" / "db.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate
    raise ImportError(f"shared/db.py를 {here} 상위에서 찾지 못함")


def ensure_msr_engine_on_path() -> Path:
    """`mineral_supply_risk/msr/config.py`를 담은 디렉토리를 sys.path에 넣는다.

    dashboards/streamlit_app.py의 로직(Ridge 진단·alert 규칙엔진·ExtraTrees
    예측)이 `msr.*`·`scripts.*`를 최상위 패키지로 import하므로(예:
    `from msr.models.nowcast import ...`), `mineral_supply_risk/` 디렉토리
    자체가 sys.path에 있어야 한다 — `services/shared/db.py`는 `db/dbio.py`만
    필요해 같은 디렉토리를 이미 path에 넣지만(부수효과에 의존하지 않기 위해
    여기서 명시적으로 한번 더 보장한다)."""

    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "mineral_supply_risk" / "msr" / "config.py").is_file():
            root = candidate / "mineral_supply_risk"
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            return root
    raise ImportError(f"mineral_supply_risk/msr/config.py를 {here} 상위에서 찾지 못함")


SHARED_PARENT = ensure_shared_on_path()
MSR_ENGINE_ROOT = ensure_msr_engine_on_path()
