# -*- coding: utf-8 -*-
"""KOMIS 공개 원천(`public.KO_*`) 기반 분석 — 외부 저장소
komis-report-generator-main의 `analysis/` 패키지 이식본(2026-08-11).

**이식 범위와 그 이유**

| 원본 파일 | 처리 |
|---|---|
| `data_sources/database.py`·`_shared.py` | 이식(정규화기 실물) |
| `models.py` | 정규화기가 쓰는 계열 타입만 이식(요약문 전용 모델 제외) |
| `indicators.py` | 무수정 이식 |
| `scaffold.py` | SQL 리포지토리는 `services/shared/komis_raw.py`로, 스텁 서비스는 `scaffold.py`로 |
| `summary.py`·`additional_summary.py`·`policy.py`·`prompts.py`·`resources/policies/` | **이식하지 않음** |

요약문 엔진(`summary.py` 33KB + `additional_summary.py` 30KB + 정책 YAML)은
스텁이 아니라 실물이지만 이번엔 가져오지 않았다. 사유 3가지:

1. **대상 데이터가 없다.** `public.KO_*`에 적재된 광종은 텅스텐(MNRL0018)
   하나뿐이라(2026-08-11 실측, `services/shared/komis_raw.py` 참고) komir 5광종
   (CU/NI/CO/LI/REE) 어느 것에도 요약문을 만들 수 없다 — 지금 이식해도 검증할
   경로가 없다.
2. **`search/` 패키지에 물려 있다.** `summary.py`는 `search.llm.JsonLLM`과
   `search.metadata`의 전체 스냅샷을 import한다. 그쪽은 별도 작업(rag_chat 이식)
   소관이라, 이식 중인 파일 위에 또 이식을 얹는 게 된다.
3. **요청 범위 밖이다.** 이번 과업은 "DB 조회 계층 이식 + 실제 동작하는 템플릿×
   정형데이터 경로 1개 + 나머지는 정직한 스텁"이다(CLAUDE.md §4 최소·외과적 변경).

향후 필요해지면 위 1·2가 풀린 뒤 별도 사이클로 이식할 것.
"""

from .data_sources import (
    DatabaseCompositeIndexDataSource,
    DatabaseIndicatorDataSource,
    DatabaseMineralMapDataSource,
    DataSourceError,
)
from .scaffold import (
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
    AnalysisScaffoldService,
    KomisRawDataRepository,
)

__all__ = [
    "AnalysisPreviewRequest",
    "AnalysisPreviewResponse",
    "AnalysisScaffoldService",
    "DataSourceError",
    "DatabaseCompositeIndexDataSource",
    "DatabaseIndicatorDataSource",
    "DatabaseMineralMapDataSource",
    "KomisRawDataRepository",
]
