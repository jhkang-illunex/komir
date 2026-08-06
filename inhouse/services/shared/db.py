# -*- coding: utf-8 -*-
"""서빙 레이어(commodity_api·rag_chat·report_gen) 공통 DB 접근점.

TODO(구현 단계): mineral_supply_risk/db/dbio.py를 그대로 재노출한다(재구현 금지).
착수 전 dbio.apply_schema()의 DuckDB 분기 버그(정의 안 된 `schema` 변수 참조,
40~42행) 먼저 수정 — docs/CONTAINER_ARCHITECTURE.md §1 참고.

설계 의도: 이 모듈이 유일한 DB 진입점이 되어 서비스 코드가 duckdb/sqlalchemy를
직접 임포트하지 않게 한다(엔진 쪽 mineral_supply_risk/scripts/*는 예외 —
배치 파이프라인은 별도 사이클로 이관).

사용 예정 형태:
    from mineral_supply_risk.db import dbio
    def read_sql(query: str): return dbio.read_sql(query, target=settings.MSR_DB)
    def write_df(df, table, **kw): return dbio.write_df(df, table, settings.MSR_DB, **kw)
"""
raise NotImplementedError("설계 단계 스켈레톤 — 구현은 다음 세션(docs/CONTAINER_ARCHITECTURE.md §8)")
