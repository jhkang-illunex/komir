# -*- coding: utf-8 -*-
"""DMZ msr_collectors 자체 설정 — env 주도, in-house `msr/config.py`(DB 경로·HS맵 등)에는
의존하지 않는다(2026-08-06 물리분리: dmz/·inhouse/가 서로 다른 서버/트리로 나뉜다는 전제).

DMZ 존 원칙: LLM 없음·DB 직접 접근 없음 — 외부 API/사이트에서 원본을 받아 로컬 파일(parquet)
로만 떨어뜨린다. 그래서 인증키(관세청·ECOS)는 여기(수집부)에서 직접 필요하다 — in-house에는
더 이상 이 키들이 필요 없다(살아있는 API 호출을 하지 않으므로).

.env 로딩: 배포 단위 루트 dmz/.env 하나(2026-08-06 정정 — 패키지별로 흩어두지 않음).
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# 인증키 (dmz 전용 — inhouse/mineral_supply_risk/msr/config.py에도 같은 이름이 있었으나
# inhouse는 더 이상 라이브 API를 호출하지 않으므로 그쪽 값은 미사용이 됨)
DATA_GO_KR_KEY_ENC = os.environ.get("DATA_GO_KR_SERVICE_KEY_ENCODING", "")
DATA_GO_KR_KEY_DEC = os.environ.get("DATA_GO_KR_SERVICE_KEY_DECODING", "")
ECOS_API_KEY = os.environ.get("ECOS_API_KEY", "")

# 수집 산출물(parquet) 출력 루트. in-house 쪽 로더가 이 경로를 그대로(공유 마운트) 또는
# rsync/NAS로 옮겨받은 사본을 같은 상대구조로 읽는다 — 경로 자체는 코드 계약이 아니라
# 파일 형식·이름 규칙만 계약(collect/README 패턴과 동일).
COLLECT_OUT = Path(os.environ.get("MSR_COLLECT_OUT", "./msr_collect_out")).resolve()

# HS10 → 5대 광종 매핑 CSV. 수집 대상 HS코드를 결정하려면 DMZ 쪽도 이 매핑이 필요하다
# (attach_commodity 자체는 in-house 로더가 적재 직전에 다시 수행 — 여기서는 core_hs_list()만
# 사용). inhouse/mineral_supply_risk/data/raw/hs_commodity_map.csv 의 동기화 사본이다 —
# 원본이 바뀌면 이 사본도 갱신할 것(2026-08-06 분리 시점 스냅샷).
HS_MAP_CSV = os.environ.get(
    "MSR_HS_MAP_CSV", str(Path(__file__).resolve().parent / "data" / "hs_commodity_map.csv"))
