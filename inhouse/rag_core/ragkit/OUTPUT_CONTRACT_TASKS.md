# 챗봇 미배선 출력 계약 작업 목록

갱신일: 2026-09-27

아래 항목은 답변 문장 형식만 확정했으며, 원천·adapter가 연결되기 전에는
값·제목·링크·요약을 생성하지 않고 `source_unavailable`로 종료한다.

| 우선순위 | 모듈 | 상태 | 필요한 배선 및 완료 조건 |
|---|---|---|---|
| P1 | `mineral_info` | adapter 연결·데이터 없음 | `retrieval/mineral_info.py`가 검증된 `resources/mineral_info_data.yml`을 우선 읽고, 없으면 `public.ai_mnrl_mst`/`ai_mnrl_sect`를 조회한다. YAML은 `source_verified: true`와 출처가 있는 행만 사용한다. |
| P1 | `weekly_trend` | adapter 구현 | 조달청보고서 `doc_chunk`에서 파일명 YYYYMMDD가 확인된 문서만 최신순으로 선택한다. 현재 최신 보유 문서는 2026-06-16이며, 정확한 게시물 URL·검증 요약은 코퍼스에 없으므로 게시판 URL만 제공하고 현재 주차를 과장하지 않는다. |
| P1 | `document.retrieve` 월간동향 | adapter 연결·부분 데이터 | `retrieval/monthly_trend.py`가 `doc_chunk`에서 최신 월간동향 문서와 본문을 묶고 본문에 실제 등장한 광종만 태그한다. 게시일·원문 URL·검증 bullet을 가진 게시물 index 보강이 필요하다. |
| P1 | `document.retrieve` 자원뉴스 | 부분 연결 | 일일·주간·테마별 뉴스의 게시일/주차, 제목, URL, 검증된 요약 bullet을 구조화해 반환한다. 그 뒤에만 일일 3건 제목, 주간 3개 요약, 최근 테마 기사 수·최대 3건 목록을 렌더링한다. |
| P1 | `forecast.price` | 연결 | `public.KO_MNRL_PRC_PREDC`의 `forecast_date`, `forecast_period`, `predicted_price`, `current_price`, `unit`을 정규화해 반환한다. 원천에 없는 기간·광종은 값을 만들지 않고 조회 불가로 종료한다. |

## 요청된 복합 Q&A 출력 계약

계약 ID와 문장 골격은 `answer_contracts.py`에 보관하고, 복합 Action의 LLM 지시에는
`AnswerComposer`가 해당 계약을 주입한다. 수치 계산·출처 생성은 이 계약이 수행하지 않는다.
따라서 아래의 **미배선** 항목은 근거가 연결되기 전까지 조회 불가로 종료해야 한다.

| 계약 | 질문 요지 | 예상 Action | 상태 | 미배선 모듈/보완 사항 |
|---|---|---|---|---|
| OC01 | 현재 가격 + 다음 달 전망 | `price.series` + `forecast.price` | 연결 | 각 원천의 기준일·단위를 보존해 현재 실측값과 전망치를 함께 표시한다. |
| OC02 | 지난 6개월 실적 + 향후 전망 차트 | `price.series` + `forecast.price` | 미배선 | 실적/전망 시계열 정규화·구간 구분 chart adapter |
| OC03 | 현재가와 전망치 비교 | `price.series` + `forecast.price` | 미배선 | 동일 기준일·단위의 forecast join 및 차이 계산 |
| OC04 | 지수 상승 동반 광종 | `indicator.series` + 복수 `price.series` | 연결 | `composite_renderer`가 동일 기간 변동률과 동반상승·동반하락 여부를 계산한다. |
| OC05 | 광물 가격 추세와 종합지수 비교 | `price.series` + `indicator.series` | 연결 | `composite_renderer`가 공통 기간 변동률과 비교차트 표식을 계산한다. 두 표의 날짜·값 열이 없으면 기권한다. |
| OC06 | 가격 추이 + 한국 수입국 구성 | `price.series` + `trade.country_rank` | 연결 | `composite_renderer`가 가격 변동·고점 월·수입국 상위 3개를 결합한다. |
| OC07 | 특정국 수입 비중 상위 광종 중 가격 상승 | `trade.price_cross_rank` | 연결 | 같은 기간·HS 묶음별 전체 수입을 분모로 특정국 비중을 집계하고, 비중 상위 광종의 요청기간 내 실제 가격 관측일을 광종별로 표시한다. 출처 불명·가격 결측은 기권한다. |
| OC08 | 수입 상위국 + 현재 가격 | `trade.country_rank` + `price.series` | 연결 | `composite_renderer`가 최신가와 실제 전월 평균을 계산한다. 전월 관측이 없으면 기권한다. |
| OC09 | 가격 + 세계 생산량 변화 | `price.series` + `resource.yoy` | 연결 | `renderers/price_blocks.py`가 같은 연도의 가격 평균과 생산량 YoY를 정렬하고 인과관계 주의 문구를 붙인다. |
| OC10 | 생산 1위국 비중 상위 광종 가격 변동 | `resource.price_cross_rank` | 연결 | 광종별 공식 세계 총계 `SU` 대비 실제 1위 생산국 비중을 집계하고 요청기간 내 가격 변동을 결합한다. 가격 관측일과 생산 기준연도를 광종별로 표시한다. |
| OC11 | 광물 용도 + 현재 가격 | `document.retrieve` + `price.series` | 부분 연결 | 문서에 검증된 용도 문장이 있고 가격 표가 있을 때만 결합 renderer가 응답한다. 광물정보 구조화 adapter는 계속 필요하다. |
| OC12 | 전략광종 가격 현황 | `price.overview` | 연결 | 기존 전략광종 가격 adapter와 결정적 안내 문구를 사용한다. 가격기준이 광종별로 다르면 비교하지 않는다. |
| OC13 | 월간동향 광종별 가격 현황 | `document.retrieve` + 복수 `price.series` | 부분 연결 | 게시물의 광종 목록·월호 구조화 index가 필요하다. 현재는 문서와 가격 표가 모두 검증될 때만 표시한다. |
| OC14 | 가격 추이 + 월간동향 서술 | `price.series` + `document.retrieve` | 부분 연결 | 게시물의 광종 태그·요약 bullet·월호 adapter가 필요하다. 원문이 없으면 요약하지 않는다. |

예측 원천에 해당 광종·기간 관측값이 없으면 대체 조회하지 않고 `source_unavailable`로
처리한다. OC07·OC10은 광종별 모집단과
요청기간 내 가격 실측 구간을 검증하는 교차 Action으로 연결했다. 광종별 가격 결측 또는
출처 미확인 시 다른 광종으로 조용히 순위를 바꾸지 않고 조회 불가로 종료한다.

현재 연결된 범위:

- 월간동향 게시판 검색 FAQ는 `resources/messages.yml`의 `monthly_board_search`로 즉시 제공한다.
- 월간동향·뉴스 일반 문서 검색은 기존 `document.retrieve`가 수행하지만, 위의 게시물 단위 출력 형식을 보장하지는 않는다.
