# -*- coding: utf-8 -*-
"""KOMIS 공개 원천(`public.KO_*`) 기반 분석 — 외부 저장소
komis-report-generator-main의 `analysis/` 패키지 이식본
(2026-08-11 1차 = 조회·정규화 계층, 2026-08-13 2차 = 요약문 엔진 5종).

**이식 범위(2026-08-13 기준 — 완료)**

| 원본 파일 | 처리 |
|---|---|
| `data_sources/{database,_shared}.py` | 이식(정규화기 실물, 08-13에 가격예측 소스 추가) |
| `models.py` | 이식(08-13에 요약문·가격예측·수급보조 모델까지 채움) |
| `indicators.py` | 무수정 이식 |
| `scaffold.py` | SQL 리포지토리는 `services/shared/komis_raw.py`로, 미리보기 서비스는 `scaffold.py`로 |
| `summary.py`·`additional_summary.py`·`policy.py`·`prompts.py`·`resources/policies/` | **이식 완료(2026-08-13)** |

**2026-08-11에 "이식하지 않음"으로 적어둔 사유 3가지는 전부 해소됐다:**

1. ~~대상 데이터가 없다~~ → 5종 중 **광물종합지수(`ko_mnrl_snths_indx`, HI001/2/3,
   2011~2025)는 광종 무관이라 실데이터가 있다** — 실제로 이 경로로 분석문 생성을
   실측 검증했다(2026-08-13). 나머지 4종은 여전히 텅스텐(MNRL0018)뿐이지만,
   데이터가 없을 때 `DataSourceError` → HTTP 422 + 한국어 사유로 우아하게
   응답한다(500이 아니다). 발주처가 5광종 데이터를 채우면 코드 변경 없이 가동된다.
2. ~~`search/` 패키지에 물려 있다~~ → `summary.py`가 쓰던 `search.llm.JsonLLM`을
   `services/shared/llm_client.KomirJsonLLM`으로 갈아끼웠다(시그니처 동일).
   `search.metadata.SNAPSHOT_PATH`는 1차 때 만든 파생 스냅샷
   (`resources/komis-metadata.subset.json`)을 계속 쓴다 — 08-13에 가격예측용
   `metadata.indicators.forecast_minerals` ref 1개를 추가해 5개가 됐다.
3. ~~요청 범위 밖~~ → 이번 과업이 바로 이 이식이다.

**주의**: `scaffold.py`(원천 미리보기)와 `summary.py`(분석요약 5종)는 **서로 다른
경로로 공존한다** — 외부repo도 동일 구조이고, `scaffold.analyze()`는 외부repo
`main` 브랜치에서도 여전히 `analysis=None` 스텁이다(2026-08-13 실측). 임의로
합치지 않았다.
"""

from .data_sources import (
    DatabaseCompositeIndexDataSource,
    DatabaseIndicatorDataSource,
    DatabaseMineralMapDataSource,
    DatabasePriceForecastDataSource,
    DataSourceError,
)
from .models import AnalysisSummaryRequest, AnalysisSummaryResponse
from .policy import PolicyError, load_page_policy
from .scaffold import (
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
    AnalysisScaffoldService,
    KomisRawDataRepository,
)
from .summary import AnalysisSummaryService

__all__ = [
    "AnalysisPreviewRequest",
    "AnalysisPreviewResponse",
    "AnalysisScaffoldService",
    "AnalysisSummaryRequest",
    "AnalysisSummaryResponse",
    "AnalysisSummaryService",
    "DataSourceError",
    "DatabaseCompositeIndexDataSource",
    "DatabaseIndicatorDataSource",
    "DatabaseMineralMapDataSource",
    "DatabasePriceForecastDataSource",
    "KomisRawDataRepository",
    "PolicyError",
    "load_page_policy",
]
