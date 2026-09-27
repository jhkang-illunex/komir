# 챗봇 미배선 출력 계약 작업 목록

갱신일: 2026-09-27

아래 항목은 답변 문장 형식만 확정했으며, 원천·adapter가 연결되기 전에는
값·제목·링크·요약을 생성하지 않고 `source_unavailable`로 종료한다.

| 우선순위 | 모듈 | 상태 | 필요한 배선 및 완료 조건 |
|---|---|---|---|
| P1 | `mineral_info` | 부분 연결 | `ai_mnrl_mst`의 활성 46종 코드·국문/영문명은 resource에 반영했다. 광종별 용도(최대 3), 원소기호, 원자번호, 주요특성, 망간 주요광석은 `ai_mnrl_sect`가 0행이라 `get_mineral_info` adapter가 아직 제공할 수 없다. 누락·미검증·DEV_DUMMY는 기권한다. |
| P1 | `weekly_trend` | adapter 구현 | 조달청보고서 `doc_chunk`에서 파일명 YYYYMMDD가 확인된 문서만 최신순으로 선택한다. 현재 최신 보유 문서는 2026-06-16이며, 정확한 게시물 URL·검증 요약은 코퍼스에 없으므로 게시판 URL만 제공하고 현재 주차를 과장하지 않는다. |
| P1 | `document.retrieve` 월간동향 | 부분 연결 | 월호, 게시일, 제목, 원문 URL, 광종 태그와 검증된 요약 bullet을 가진 게시물 index adapter를 추가한다. 그 뒤에만 이번 달 전략광종 월간동향 요약, 최신 보고서 제목, 최근 N개월 광종 관련 게시물(최대 5)을 각 출력 계약으로 렌더링한다. |
| P1 | `document.retrieve` 자원뉴스 | 부분 연결 | 일일·주간·테마별 뉴스의 게시일/주차, 제목, URL, 검증된 요약 bullet을 구조화해 반환한다. 그 뒤에만 일일 3건 제목, 주간 3개 요약, 최근 테마 기사 수·최대 3건 목록을 렌더링한다. |
| P1 | `forecast.price` | 미배선 | 미래 예측 adapter가 `forecast_date`, `forecast_period`, `predicted_price`, `current_price`, `unit` 및 provenance를 정규화해 반환한다. 구현된 다음 달 전망치·방향 renderer를 활성화한다. 현 KOMIS 과거 예측 테이블은 대체 원천으로 사용하지 않는다. |

현재 연결된 범위:

- 월간동향 게시판 검색 FAQ는 `resources/messages.yml`의 `monthly_board_search`로 즉시 제공한다.
- 월간동향·뉴스 일반 문서 검색은 기존 `document.retrieve`가 수행하지만, 위의 게시물 단위 출력 형식을 보장하지는 않는다.
