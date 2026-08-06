# -*- coding: utf-8 -*-
"""ECOS 코드 탐색 헬퍼(개발자용, 2026-08-06 신설) — 구 in-house `scripts/run.py ecos-search`가
하던 것과 동일(`ecos_api.search_tables(kw)`). 물리분리 후 in-house에서는 더 이상
`ecos_api`를 라이브 호출할 수 없으므로 이 위치로 옮김. DB 저장 없음, 순수 탐색용 — sink/
parquet 계약과 무관.

실행: cd komir/dmz && ECOS_API_KEY=<키> python -m msr_collectors.scripts.ecos_search <키워드>
"""
from __future__ import annotations
import sys

from ..ecos_api import search_tables


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else ""
    print(search_tables(kw).to_string())


if __name__ == "__main__":
    main()
