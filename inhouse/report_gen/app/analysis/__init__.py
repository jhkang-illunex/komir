"""요청 데이터 기반 보고서 생성. 과거 DB/미리보기 API는 요청될 때만 로드한다."""
from importlib import import_module

from .errors import DataSourceError
from .models import AnalysisSummaryRequest, AnalysisSummaryResponse
from .policy import PolicyError, load_page_policy
from .summary import AnalysisSummaryService

_LEGACY_EXPORTS = {
    "DatabaseCompositeIndexDataSource": ".data_sources",
    "DatabaseIndicatorDataSource": ".data_sources",
    "DatabaseMineralMapDataSource": ".data_sources",
    "DatabasePriceForecastDataSource": ".data_sources",
    "AnalysisPreviewRequest": ".scaffold",
    "AnalysisPreviewResponse": ".scaffold",
    "AnalysisScaffoldService": ".scaffold",
    "KomisRawDataRepository": ".scaffold",
}


def __getattr__(name: str):
    if name not in _LEGACY_EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_LEGACY_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value


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
