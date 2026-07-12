# -*- coding: utf-8 -*-
"""수집기 설정 — 전부 env 주도(분석기와 다른 서버에서 독립 실행되는 도커 전제).

출력 계약(분석기 geo 파이프라인과의 유일한 접점 — 코드 의존 없음, 파일 형식만 공유):
  $COLLECT_OUT/inbox/<collector>/*.txt   → 분석 서버의 `geo ingest`가 읽는 inbox 형식 그대로
  $COLLECT_OUT/gkg/<YYYY>/*.gkg.csv.zip  → 분석 서버의 `geo gkg-parse --bulk-root`가 읽는 형식 그대로
  $COLLECT_OUT/_state/                   → 수집기 자체 상태(중복방지·재개)
전송은 공유 NAS 마운트(권장) 또는 rsync — README 참고.
"""
import os
from pathlib import Path

COLLECT_OUT = Path(os.environ.get("COLLECT_OUT", "./collect_out")).resolve()
INBOX = COLLECT_OUT / "inbox"
GKG_OUT = COLLECT_OUT / "gkg"
STATE = COLLECT_OUT / "_state"

UA = os.environ.get("COLLECT_UA", "Mozilla/5.0 (X11; Linux x86_64) komir-collector/1.0")
HTTP_TIMEOUT = int(os.environ.get("COLLECT_HTTP_TIMEOUT", "30"))

# 광종 키워드(영/중) — 태깅 보조용. 실제 광종 판별은 분석기 extract가 다시 한다.
MINERAL_EN = {"CU": "copper", "NI": "nickel", "CO": "cobalt", "LI": "lithium",
              "REE": "rare earth", "ALL": "critical minerals"}
MINERAL_ZH = {"REE": ("稀土", "钕"), "LI": ("锂",), "CO": ("钴",), "NI": ("镍",), "CU": ("铜",)}


def ensure_dirs():
    for p in (INBOX, GKG_OUT, STATE):
        p.mkdir(parents=True, exist_ok=True)
