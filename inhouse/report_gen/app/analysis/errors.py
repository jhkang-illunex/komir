"""분석 입력 오류. HTTP 계층에서 기존 NO_DATA 상태로 변환한다."""


class DataSourceError(RuntimeError):
    """설정된 원천 데이터가 분석 요청을 만족하지 못할 때."""
