# 사용자 제공 Q&A 쌍 라이브 점검 결과

- 실행 시각: 20260928_024048 (Asia/Seoul)
- 대상: `http://127.0.0.1:18002/pubchat`
- 질문 수: 56
- DEBUG 처리 진단 기록: 활성
- 집계: BLOCKED_DATA 25, FAIL 1, PARTIAL 8, PASS 22

판정: `PASS`는 SSE 종료 계약과 질문별 기대 표지가 확인된 응답, `PARTIAL`은 응답은 있으나 기대 표지 일부가 없는 경우, `BLOCKED_DATA`는 `source_unavailable` 안전 종료, `FAIL`은 요청/종료 계약 오류 또는 기타 기권입니다. 키워드 검사는 형식 점검 보조 수단이며 사실성의 최종 판정은 아닙니다.

|ID|판정|질문|Action / Source|표·차트|비고|
|---|---|---|---|---|---|
|MI01|PASS|니켈은 어디에 쓰여?|document.retrieve, Royal Society of Chemistry|표 0 / 차트 0|-|
|MI02|BLOCKED_DATA|니켈은 어떤 금속이야?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: mineral_info/document.retrieve (advisor_rejected)|
|MI03|BLOCKED_DATA|구리 기본 특성을 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: mineral_info/document.retrieve (advisor_rejected)|
|MI04|BLOCKED_DATA|망간 주요 광석 종류는?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: req_001/document.retrieve (advisor_rejected)|
|DOC01|BLOCKED_DATA|이번달 전략 광종 월간 동향 요약해줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: publication_search/document.retrieve (advisor_rejected)|
|DOC02|BLOCKED_DATA|최근 월간동향 제목 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: req_001/document.retrieve (advisor_rejected)|
|DOC03|BLOCKED_DATA|최근 3개월 월간 동향에서 니켈 관련 내용 찾아줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: publication_search/document.retrieve (advisor_rejected)|
|DOC04|PASS|월간 동향 게시판 검색은 어떻게 해?|-|표 0 / 차트 0|-|
|NEWS01|BLOCKED_DATA|최근 자원 뉴스 뭐 있어?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: req_001/document.retrieve (advisor_rejected)|
|NEWS02|BLOCKED_DATA|이번주 주간 자원뉴스 요약해줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: publication_search/document.retrieve (advisor_rejected)|
|NEWS03|BLOCKED_DATA|최근 중국 수출통제 관련 뉴스 있어?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: publication_search/document.retrieve (advisor_rejected)|
|PF01|PARTIAL|니켈 현재 가격이랑 다음달 전망 같이 알려줘|price.series, KOMIS 공식 데이터|표 1 / 차트 0|기대 표지 미검출: 전망; DEBUG 처리 실패: next_month_forecast/forecast.price (advisor_rejected); DEBUG 경고: action_failed:next_month_forecast:forecast.price:advisor_rejected|
|PF02|PARTIAL|니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘|price.series, KOMIS 공식 데이터|표 1 / 차트 1|기대 표지 미검출: 전망; DEBUG 처리 실패: forecast_timeline/forecast.price (advisor_rejected); DEBUG 경고: action_failed:forecast_timeline:forecast.price:advisor_rejected|
|PF03|PARTIAL|니켈 지금 가격이 전망치 보다 높은 편이야?|price.series, KOMIS 공식 데이터|표 1 / 차트 0|기대 표지 미검출: 현재, 전망; DEBUG 처리 실패: forecast_compare/forecast.price (advisor_rejected); DEBUG 경고: action_failed:forecast_compare:forecast.price:advisor_rejected|
|IX01|BLOCKED_DATA|광물지수 오를때 같이 오른 광종은 뭐야?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: req_001/document.retrieve (advisor_rejected)|
|IX02|PASS|니켈 가격 추세랑 광물 종합지수 추세 비교해주세요|price.series, KOMIS 공식 데이터|표 1 / 차트 1|DEBUG 처리 실패: composite_index_trend/indicator.series (advisor_rejected); DEBUG 경고: action_failed:composite_index_trend:indicator.series:advisor_rejected|
|MP01|PASS|니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘|price.series, trade.country_rank, KOMIS 공식 데이터|표 2 / 차트 1|-|
|MP02|PARTIAL|중국 수입 비중 높은 광종 중 최근 가격 오른건 뭐야?|trade.price_cross_rank, KOMIS 공식 데이터|표 1 / 차트 1|기대 표지 미검출: 점유율|
|MP03|PASS|니켈 수입 상위국이랑 현재가격 알려줘|price.series, trade.country_rank, KOMIS 공식 데이터|표 2 / 차트 1|-|
|MP04|PASS|니켈 가격이랑 세계 생산량 변화 같이 보여줘|price.series, resource.rank, KOMIS 공식 데이터|표 2 / 차트 1|-|
|MP05|PASS|생산 1위국 비중이 높은 광종들 가격 변동 어때?|resource.price_cross_rank, KOMIS 공식 데이터|표 1 / 차트 1|-|
|MP06|PASS|니켈은 어디에 쓰이고 지금 가격은 얼마야?|document.retrieve, price.series, KOMIS 공식 데이터, Royal Society of Chemistry|표 2 / 차트 0|-|
|MP07|PASS|전략광종 가격 현황 한눈에 보여줘|price.overview, KOMIS 공식 데이터|표 1 / 차트 0|-|
|MP08|BLOCKED_DATA|이번달 희소금속 월간 동향에 나온 광종들 가격 어때?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: monthly_rare_metals/document.retrieve (advisor_rejected)|
|MP09|PARTIAL|니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘|price.series, KOMIS 공식 데이터|표 1 / 차트 0|기대 표지 미검출: 월간; DEBUG 처리 실패: req_2/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:req_2:document.retrieve:advisor_rejected|
|CN01|PARTIAL|니켈 가격 크게 오른 날 관련 뉴스 있어?|-|표 0 / 차트 0|기대 표지 미검출: 가격, 뉴스|
|CN02|BLOCKED_DATA|이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: weekly_price_volatility/price.volatility_rank (advisor_rejected)|
|CN03|BLOCKED_DATA|광물종합지수 구성 광종 중 상승 전망인 건 뭐야?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: composite_constituents_forecast/document.retrieve (advisor_rejected)|
|CN04|BLOCKED_DATA|수입 의존도 높은 광종들 가격 전망 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable|
|CN05|PARTIAL|리튬 주요 수입국이랑 가격 전망 같이 보여줘|trade.country_rank, KOMIS 공식 데이터|표 1 / 차트 1|기대 표지 미검출: 전망; DEBUG 처리 실패: forecast/forecast.price (advisor_rejected); DEBUG 경고: action_failed:forecast:forecast.price:advisor_rejected|
|CN06|BLOCKED_DATA|구리 가격 전망이랑 월간동향 시장 전망 내용 비교해줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: forecast/forecast.price (advisor_rejected); DEBUG 처리 실패: monthly/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:forecast:forecast.price:advisor_rejected; DEBUG 경고: action_failed:monthly:document.retrieve:advisor_rejected|
|CN07|BLOCKED_DATA|리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: forecast/forecast.price (advisor_rejected); DEBUG 처리 실패: news/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:forecast:forecast.price:advisor_rejected; DEBUG 경고: action_failed:news:document.retrieve:advisor_rejected|
|CN08|BLOCKED_DATA|지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: monthly_composite_index/indicator.series (advisor_rejected); DEBUG 처리 실패: monthly_trend/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:monthly_composite_index:indicator.series:advisor_rejected; DEBUG 경고: action_failed:monthly_trend:document.retrieve:advisor_rejected|
|CN09|BLOCKED_DATA|광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: weekly_index/indicator.series (advisor_rejected)|
|GM01|PASS|코발트 세계 생산국이랑 우리나라 수입국 비교해줘|resource.rank, trade.country_rank, KOMIS 공식 데이터|표 2 / 차트 2|-|
|GM02|PASS|리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?|resource.rank, trade.country_rank, KOMIS 공식 데이터|표 2 / 차트 2|-|
|GM03|PASS|흑연 생산 집중도랑 수입 집중도 비교해줘|trade.concentration, KOMIS 공식 데이터|표 1 / 차트 1|DEBUG 처리 실패: production_concentration/resource.rank (advisor_rejected); DEBUG 경고: action_failed:production_concentration:resource.rank:advisor_rejected|
|GM04|PASS|2차전지 광물 수입국 구성 알려줘|trade.country_rank, KOMIS 공식 데이터|표 5 / 차트 0|-|
|GM05|PASS|망간 용도랑 주요 수입국 알려줘|document.retrieve, trade.country_rank, KOMIS 공식 데이터, Royal Society of Chemistry|표 2 / 차트 1|-|
|GM06|BLOCKED_DATA|이번 달 전략광종 월간동향에 나온 광종들 우리 수입 구조 어때?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: monthly_trend/document.retrieve (advisor_rejected)|
|GM07|BLOCKED_DATA|중국 수출통제 뉴스에 나온 광종 중국 수입 비중 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: export_control_news/document.retrieve (advisor_rejected)|
|GM08|PASS|텅스텐 용도랑 세계 생산국 알려줘|document.retrieve, resource.rank, KOMIS 공식 데이터, Royal Society of Chemistry|표 2 / 차트 1|-|
|GM09|BLOCKED_DATA|이번 달 전략광종 월간동향에서 다룬 광종 기본 정보 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: req_001/document.retrieve (advisor_rejected); DEBUG 처리 실패: req_002/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:req_001:document.retrieve:advisor_rejected; DEBUG 경고: action_failed:req_002:document.retrieve:advisor_rejected|
|GM10|BLOCKED_DATA|이번 달 월간동향이랑 이번 주 뉴스에 공통으로 나온 이슈는?|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: monthly_trend/document.retrieve (advisor_rejected); DEBUG 처리 실패: weekly_news/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:monthly_trend:document.retrieve:advisor_rejected; DEBUG 경고: action_failed:weekly_news:document.retrieve:advisor_rejected|
|GM11|PASS|흑연 공급 현황 종합해서 알려줘|price.series, resource.rank, trade.concentration, KOMIS 공식 데이터|표 3 / 차트 2|DEBUG 처리 실패: monthly/document.retrieve (advisor_rejected); DEBUG 경고: action_failed:monthly:document.retrieve:advisor_rejected|
|GM12|PARTIAL|2차전지 광물 5종 가격이랑 전망 한 번에 보여줘|price.series, KOMIS 공식 데이터|표 5 / 차트 0|기대 표지 미검출: 전망; DEBUG 처리 실패: battery_forecast_리튬/forecast.price (advisor_rejected); DEBUG 처리 실패: battery_forecast_니켈/forecast.price (advisor_rejected); DEBUG 처리 실패: battery_forecast_코발트/forecast.price (advisor_rejected); DEBUG 처리 실패: battery_forecast_망간/forecast.price (advisor_rejected); DEBUG 처리 실패: battery_forecast_흑연/forecast.price (advisor_rejected); DEBUG 경고: action_failed:battery_forecast_리튬:forecast.price:advisor_rejected; DEBUG 경고: action_failed:battery_forecast_니켈:forecast.price:advisor_rejected; DEBUG 경고: action_failed:battery_forecast_코발트:forecast.price:advisor_rejected; DEBUG 경고: action_failed:battery_forecast_망간:forecast.price:advisor_rejected; DEBUG 경고: action_failed:battery_forecast_흑연:forecast.price:advisor_rejected|
|GM13|PASS|코발트 현황 브리핑해줘|price.series, resource.rank, trade.country_rank, KOMIS 공식 데이터|표 3 / 차트 0|DEBUG 처리 실패: forecast/forecast.price (advisor_rejected); DEBUG 경고: action_failed:forecast:forecast.price:advisor_rejected|
|GM14|BLOCKED_DATA|중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: export_control_news/document.retrieve (advisor_rejected)|
|REG01|FAIL|리튬 주요 수출국을 알려줘|-|표 0 / 차트 0|abstain_reason=no_data_for_period|
|REG02|PASS|오늘 니켈 가격 얼마야?|-|표 1 / 차트 0|-|
|REG03|PASS|최근 니켈 가격 얼마야?|-|표 1 / 차트 0|-|
|REG04|PASS|니켈 가격 년도별 평균 가격을 알려줘|-|표 0 / 차트 0|-|
|REG05|PASS|니켈 LME 재고량 알려줘|-|표 1 / 차트 1|-|
|REG06|BLOCKED_DATA|니켈 텅스텐 가격 같이 비교해줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: two_mineral_price_comparison/price.compare (source_unavailable:unverified_or_incomplete_observation); DEBUG 경고: aggregate_incomplete:komis_price_comparison; DEBUG 경고: source_unavailable:price_comparison_requires_a_common_price_basis; DEBUG 경고: source_unavailable:unverified_or_incomplete_observation|
|REG07|BLOCKED_DATA|니켈 다음달 가격 전망 알려줘|-|표 0 / 차트 0|abstain_reason=source_unavailable; DEBUG 처리 실패: forecast_price_next_month_value/forecast.price (advisor_rejected)|
|REG08|PASS|니켈 수입 집중도를 알려줘요|trade.concentration, KOMIS 공식 데이터|표 1 / 차트 1|-|

## 응답 원문 발췌

### MI01 — PASS

질문: 니켈은 어디에 쓰여?

니켈의 주요 용도는 스테인리스강·합금, 금속 도금, 충전식 배터리입니다.

### MI02 — BLOCKED_DATA

질문: 니켈은 어떤 금속이야?

데이터를 찾을 수 없습니다.

### MI03 — BLOCKED_DATA

질문: 구리 기본 특성을 알려줘

데이터를 찾을 수 없습니다.

### MI04 — BLOCKED_DATA

질문: 망간 주요 광석 종류는?

데이터를 찾을 수 없습니다.

### DOC01 — BLOCKED_DATA

질문: 이번달 전략 광종 월간 동향 요약해줘

데이터를 찾을 수 없습니다.

### DOC02 — BLOCKED_DATA

질문: 최근 월간동향 제목 알려줘

데이터를 찾을 수 없습니다.

### DOC03 — BLOCKED_DATA

질문: 최근 3개월 월간 동향에서 니켈 관련 내용 찾아줘

데이터를 찾을 수 없습니다.

### DOC04 — PASS

질문: 월간 동향 게시판 검색은 어떻게 해?

기간(전체, 1/3/6/12개월 또는 직접입력)과 검색어(제목+내용, 제목, 내용)로 검색할 수 있습니다.

### NEWS01 — BLOCKED_DATA

질문: 최근 자원 뉴스 뭐 있어?

데이터를 찾을 수 없습니다.

### NEWS02 — BLOCKED_DATA

질문: 이번주 주간 자원뉴스 요약해줘

데이터를 찾을 수 없습니다.

### NEWS03 — BLOCKED_DATA

질문: 최근 중국 수출통제 관련 뉴스 있어?

데이터를 찾을 수 없습니다.

### PF01 — PARTIAL

질문: 니켈 현재 가격이랑 다음달 전망 같이 알려줘

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))

### PF02 — PARTIAL

질문: 니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-03-27\~2026-09-08, 지정 기간 내 관측 118건 전체)

### PF03 — PARTIAL

질문: 니켈 지금 가격이 전망치 보다 높은 편이야?

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))

### IX01 — BLOCKED_DATA

질문: 광물지수 오를때 같이 오른 광종은 뭐야?

데이터를 찾을 수 없습니다.

### IX02 — PASS

질문: 니켈 가격 추세랑 광물 종합지수 추세 비교해주세요

- OC04: 광물종합지수 : 제공된 문서에서 근거를 찾지 못했습니다.

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2025-09-29\~2026-09-08, 지정 기간 내 관측 247건 전체)

광물지표: 확인 가능한 자료가 없어 답변할 수 없습니다.

### MP01 — PASS

질문: 니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘

- OC06: 광물가격 : 2026-09-07\~2026-09-08 니켈 가격 2.07% 변동 고점 17080.44(2026-09-08) [1] 수급지도 : 2026-06-01\~2026-09-09 수입국 상위 국가와 점유율을 표시한다.

최근 1년간 니켈 상위 5개국은 1위 [인도네시아 37.12%], 2위 [호주 26.87%], 3위 [칠레 10.18%], 4위 [콩고민주공화국 7.09%], 5위 [미국 5.55%] 순입니다. [2]

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

최근 1년간 니켈 상위 5개국은 1위 [인도네시아 37.12%], 2위 [호주 26.87%], 3위 [칠레 10.18%], 4위 [콩고민주공화국 7.09%], 5위 [미국 5.55%] 순입니다. [2]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [2] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(니켈) · 국가별 수입금액 상위 5개 (기준시점 2026-06-01\~2026-09-09)

### MP02 — PARTIAL

질문: 중국 수입 비중 높은 광종 중 최근 가격 오른건 뭐야?

수급지도 : 2025-10-01\~2026-07-01 중국 수입금액 비중 상위 광종: 텅스텐(57.86%), 동(32%), 인듐(32%), 리튬(26.27%), 백금(22.62%)
광물가격 : 이 중 요청기간 내 실제 관측일 기준 상승 광종: 텅스텐(+90.18%) [2025-09-30\~2026-01-08], 동(+45.56%) [2026-07-07\~2026-09-09], 인듐(+10.12%) [2026-05-08\~2026-09-04], 백금(+9.11%) [2026-05-08\~2026-09-04]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

### MP03 — PASS

질문: 니켈 수입 상위국이랑 현재가격 알려줘

최근 1년간 니켈 상위 5개국은 1위 [인도네시아 37.12%], 2위 [호주 26.87%], 3위 [칠레 10.18%], 4위 [콩고민주공화국 7.09%], 5위 [미국 5.55%] 순입니다. [1]

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [2]

최근 1년간 니켈 상위 5개국은 1위 [인도네시아 37.12%], 2위 [호주 26.87%], 3위 [칠레 10.18%], 4위 [콩고민주공화국 7.09%], 5위 [미국 5.55%] 순입니다. [1]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(니켈) · 국가별 수입금액 상위 5개 (기준시점 2026-06-01\~2026-09-09)
- [2] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))

### MP04 — PASS

질문: 니켈 가격이랑 세계 생산량 변화 같이 보여줘

[price.series]
니켈 가격(LME CASH, 단위 미표기)의 실제 조회기간은 2026-09-07부터 2026-09-08까지입니다. [1] - 2026-09-08: 통상가격 16,745.53 [1] - 2026-09-07: 통상가격 16,405.16 [1] [resource.rank]

| 순위 | 국가 | 생산량 합계(톤) | 비중(%) |
| --- | --- | --- | --- |
| 1 | 중국 | 27,376.0 | 62.37 |
| 2 | 호주 | 5,664.0 | 12.9 |
| 3 | 인도네시아 | 3,776.0 | 8.6 |
| 4 | 칠레 | 2,832.0 | 6.45 |
| 5 | 콩고민주공화국 | 2,360.0 | 5.38 | [2]

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [2] KOMIS 공식 데이터 · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(니켈) · 국가별 생산량 상위 5개 (기준시점 2026\~2026)

### MP05 — PASS

질문: 생산 1위국 비중이 높은 광종들 가격 변동 어때?

광물지도 : 생산 1위국 비중 상위 광종: 텅스텐(중국 78.82%, 2025년), 동(페루 11.74%, 2025년), 아연(페루 11.54%, 2025년), 리튬(ZW 9.66%, 2025년), 니켈(필리핀 6.92%, 2025년)
광물가격 : 같은 광종 각 광종 실제 관측기간 기준 가격 변동률: 텅스텐(+90.18%) [2025-09-30\~2026-01-08], 동(+45.56%) [2026-07-07\~2026-09-09], 아연(-33.79%) [2026-07-07\~2026-09-09], 리튬(-4.77%) [2026-07-07\~2026-09-09], 니켈(+13.57%) [2025-09-29\~2026-09-08]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

### MP06 — PASS

질문: 니켈은 어디에 쓰이고 지금 가격은 얼마야?

광물정보 : 주요 용도 : 스테인리스강·합금, 금속 도금, 충전식 배터리
광물가격 : 2026-09-08 니켈 가격 16,745.53 USD/톤, 전일 대비 +2.07%

### MP07 — PASS

질문: 전략광종 가격 현황 한눈에 보여줘

광물정보 : 전략광종 목록 기준
광물가격 : 기준일 기준 광종별 가격·전월 평균 대비 등락률 표입니다. [1]

⚠ 표의 원천 상태가 dev_dummy인 행은 개발용 예시 데이터이며 실제 가격이 아닙니다; 가격 기준 또는 관측값이 없는 광종은 가격을 생성하지 않았습니다: 유연탄, 우라늄, 철광석.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC · 전략광종 가격 현황(광종별 최신 관측)

### MP08 — BLOCKED_DATA

질문: 이번달 희소금속 월간 동향에 나온 광종들 가격 어때?

데이터를 찾을 수 없습니다.

### MP09 — PARTIAL

질문: 니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘

- OC11: 광물정보 : 주요 용도 정보가 제공된 문서에 없습니다.

선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))

문서 내용: 확인 가능한 자료가 없어 답변할 수 없습니다.

### CN01 — PARTIAL

질문: 니켈 가격 크게 오른 날 관련 뉴스 있어?

전일 대비 5% 이상 상승한 관측일을 최근 조회기간에서 찾지 못했습니다.

### CN02 — BLOCKED_DATA

질문: 이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘

데이터를 찾을 수 없습니다.

### CN03 — BLOCKED_DATA

질문: 광물종합지수 구성 광종 중 상승 전망인 건 뭐야?

데이터를 찾을 수 없습니다.

### CN04 — BLOCKED_DATA

질문: 수입 의존도 높은 광종들 가격 전망 알려줘

제공된 문서에서 근거를 찾지 못했습니다.

데이터를 찾을 수 없습니다.

### CN05 — PARTIAL

질문: 리튬 주요 수입국이랑 가격 전망 같이 보여줘

### 리튬 주요 수입국
2026-06-01부터 2026-09-09까지의 기간 동안 리튬 수입금액 상위 5개국 현황은 다음과 같습니다. [1] | 순위 | 국가 | 수입금액합계 (USD) | 비중 (%) | 거래건수 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 호주 | 72,385,760.0 | 37.6 | 6 |
| 2 | 중국 | 50,575,600.0 | 26.27 | 6 |
| 3 | 인도네시아 | 19,685,440.0 | 10.23 | 6 |
| 4 | 칠레 | 13,692,640.0 | 7.11 | 6 |
| 5 | 콩고민주공화국 | 10,696,240.0 | 5.56 | 6 |

최근 1년간 리튬 상위 5개국은 1위 [호주 37.6%], 2위 [중국 26.27%], 3위 [인도네시아 10.23%], 4위 [칠레 7.11%], 5위 [콩고민주공화국 5.56%] 순입니다. [1]

최근 1년간 리튬 상위 5개국은 1위 [호주 37.6%], 2위 [중국 26.27%], 3위 [인도네시아 10.23%], 4위 [칠레 7.11%], 5위 [콩고민주공화국 5.56%] 순입니다. [1]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(리튬) · 국가별 수입금액 상위 5개 (기준시점 2026-06-01\~2026-09-09)

### CN06 — BLOCKED_DATA

질문: 구리 가격 전망이랑 월간동향 시장 전망 내용 비교해줘

데이터를 찾을 수 없습니다.

### CN07 — BLOCKED_DATA

질문: 리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘

데이터를 찾을 수 없습니다.

### CN08 — BLOCKED_DATA

질문: 지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘

데이터를 찾을 수 없습니다.

### CN09 — BLOCKED_DATA

질문: 광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?

데이터를 찾을 수 없습니다.

### GM01 — PASS

질문: 코발트 세계 생산국이랑 우리나라 수입국 비교해줘

광물지도 : 생산 상위국 중국, 호주, 인도네시아, 칠레, 콩고민주공화국
핵심광물 수급지도 : 수입 상위국 칠레, 콩고민주공화국, 인도네시아, 미국, 러시아
비교결과 : 공통 국가 인도네시아, 칠레, 콩고민주공화국

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

### GM02 — PASS

질문: 리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?

광물지도 : 생산 상위국 중국, 호주, 인도네시아, 칠레, 콩고민주공화국
핵심광물 수급지도 : 수입 상위국 호주, 중국, 인도네시아, 칠레, 콩고민주공화국
비교결과 : 공통 국가 중국, 호주, 인도네시아, 칠레, 콩고민주공화국

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

### GM03 — PASS

질문: 흑연 생산 집중도랑 수입 집중도 비교해줘

광물지도 : 생산 1위국 비중 조회 불가

핵심광물 수급지도 : 수입 CR3 52.0%, 1위국 점유율 21.0%
(수입금액 기준, 2026-06-01\~2026-09-09, 단위 USD) [1] - 수입 CR3(러시아, 칠레, 남아프리카공화국) 비중: 52.0% [1] - 1위국(러시아) 점유율: 21.0% [1] - 위 수치는 전체 국가 수입금액 합계 127,120,000.0 USD를 분모로 산출되었습니다. [1]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(흑연) · 국가별 수입금액 집중도(HHI=1307.5, 전체합계=127120000.0, Σ(국가별 비중[%]^2)) 상위 10개 (기준시점 2026-06-01\~2026-09-09)

생산·매장량 순위: 확인 가능한 자료가 없어 답변할 수 없습니다.

### GM04 — PASS

질문: 2차전지 광물 수입국 구성 알려줘

광물정보 : 2차전지 원료 광종 리튬, 니켈, 코발트, 망간, 흑연
핵심광물 수급지도 : 최근 12개월 수입 1위국
리튬 : 호주 (37.6%)
니켈 : 인도네시아 (37.12%)
코발트 : 칠레 (25.55%)
망간 : 미국 (21%)
흑연 : 러시아 (21%)

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

### GM05 — PASS

질문: 망간 용도랑 주요 수입국 알려줘

광물정보 : 주요 용도 : 강철·합금의 강도·내마모성 향상, 철도 레일·금고·공구용 망간강, 배터리·유리·비료·세라믹
핵심광물 수급지도 : 수입 상위국 미국(21%), 인도네시아(18%), 러시아(13%), 남아프리카공화국(10%), 칠레(10%)

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

### GM06 — BLOCKED_DATA

질문: 이번 달 전략광종 월간동향에 나온 광종들 우리 수입 구조 어때?

데이터를 찾을 수 없습니다.

### GM07 — BLOCKED_DATA

질문: 중국 수출통제 뉴스에 나온 광종 중국 수입 비중 알려줘

데이터를 찾을 수 없습니다.

### GM08 — PASS

질문: 텅스텐 용도랑 세계 생산국 알려줘

광물정보 : 주요 용도 : 고온 합금·용접 전극·고온로 발열체, 절삭·천공 공구용 텅스텐 카바이드, 조명용 필라멘트·형광등
광물지도 : 생산 상위국 중국(78.82%), 베트남(3.53%), 카자흐스탄(2.82%), 북한(2.35%), 러시아(2.35%)

### GM09 — BLOCKED_DATA

질문: 이번 달 전략광종 월간동향에서 다룬 광종 기본 정보 알려줘

데이터를 찾을 수 없습니다.

### GM10 — BLOCKED_DATA

질문: 이번 달 월간동향이랑 이번 주 뉴스에 공통으로 나온 이슈는?

데이터를 찾을 수 없습니다.

### GM11 — PASS

질문: 흑연 공급 현황 종합해서 알려줘

[production]
2026년 기준 흑연 생산 현황은 다음과 같습니다. [1] - 세계 생산량 합계: 24,640.0 톤 (2026년) [1] - 생산국 순위 1위: 중국 (8,960.0 톤, 비중 36.36%) [1] [imports]
2026-06-01부터 2026-09-09까지의 흑연 수입 현황은 다음과 같습니다. [2] - 한국 수입금액 합계: 127,120,000.0 USD (2026-06-01\~2026-09-09) [2] - 주요 수입국 비중:
  - 러시아: 26,695,200.0 USD (21.0%) [2] - 칠레: 22,881,600.0 USD (18.0%) [2] - 남아프리카공화국: 16,525,600.0 USD (13.0%) [2] - 캐나다: 12,712,000.0 USD (10.0%) [2] - 콩고민주공화국: 12,712,000.0 USD (10.0%) [2] - 브라질: 9,534,000.0 USD (7.5%) [2] - 미국: 9,534,000.0 USD (7.5%) [2] - 중국: 7,627,200.0 USD (6.0%) [2] - 호주: 5,084,800.0 USD (4.0%) [2] - 인도네시아: 3,813,600.0 USD (3.0%) [2] [price]

선택 가격기준의 단위 표기는 가격기준=흑연 -194 FOB입니다. [3]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(흑연) · 국가별 생산량 상위 1개 (기준시점 2026\~2026)
- [2] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(흑연) · 국가별 수입금액 집중도(HHI=1307.5, 전체합계=127120000.0, Σ(국가별 비중[%]^2)) 상위 10개 (기준시점 2026-06-01\~2026-09-09)
- [3] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(흑연) (기준시점 2026-08-27\~2026-09-04, 지정 기간 내 관측 9건 전체)

문서 내용: 확인 가능한 자료가 없어 답변할 수 없습니다.

### GM12 — PARTIAL

질문: 2차전지 광물 5종 가격이랑 전망 한 번에 보여줘

- OC01: 광물 가격 : 2026-09-09 리튬 가격 12800.0 USD/TON [1] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.
자료원 변경 주의 문구

- OC02: 광물 가격 : 2026-09-08\~2026-09-09 리튬 실적 추이 (조회기간: 2026-09-08\~2026-09-09) [1] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC01: 광물 가격 : 2026-09-08 니켈 가격 16745.53 / [2] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC02: 광물 가격 : 2026-09-07\~2026-09-08 니켈 실적 추이 (조회기간: 2026-09-07\~2026-09-08) [2] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC01: 광물 가격 : 2026-09-09 코발트 가격 14400.0 USD/TON [3] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC02: 광물 가격 : 2026-09-08\~2026-09-09 코발트 실적 추이 (조회기간: 2026-09-08\~2026-09-09) [3] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC01: 광물 가격 : 2026-09-04 망간 가격 1250.77 / [4] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC02: 광물 가격 : 2026-09-03\~2026-09-04 망간 실적 추이 (조회기간: 2026-09-03\~2026-09-04) [4] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

- OC01: 광물 가격 : 2026-09-04 흑연 가격 657.6 / [5] 가격 예측 : 제공된 문서에서 근거를 찾지 못했습니다.

선택 가격기준의 단위 표기는 가격기준=spot; 통화코드=USD; 중량단위코드=TON입니다. [1]
선택 가격기준의 단위 표기는 가격기준=LME CASH입니다. [2]
선택 가격기준의 단위 표기는 가격기준=spot; 통화코드=USD; 중량단위코드=TON입니다. [3]
선택 가격기준의 단위 표기는 가격기준=페로망간입니다. [4]
선택 가격기준의 단위 표기는 가격기준=흑연 -194 FOB입니다. [5]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(리튬) (기준시점 2026-09-08\~2026-09-09, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [2] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-07\~2026-09-08, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [3] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(코발트) (기준시점 2026-09-08\~2026-09-09, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [4] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(망간) (기준시점 2026-09-03\~2026-09-04, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [5] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(흑연) (기준시점 2026-09-03\~2026-09-04, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))

### GM13 — PASS

질문: 코발트 현황 브리핑해줘

[current_price]

[forecast]
제공된 문서에서 근거를 찾지 못했습니다.

[production]

- 1위 중국: 생산량 합계는 18,176.0 톤이며, 비중은 36.36%입니다 [2] .

[imports]
- 1위 칠레: 수입금액 합계는 71,441,440.0 USD이며, 비중은 25.55%입니다 [3]

최근 1년간 코발트 상위 1개국은 1위 [중국 36.36%] 순입니다. [2]

선택 가격기준의 단위 표기는 가격기준=spot; 통화코드=USD; 중량단위코드=TON입니다. [1]

최근 1년간 코발트 상위 1개국은 1위 [중국 36.36%] 순입니다. [2]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_MNRL_PRC(코발트) (기준시점 2026-09-08\~2026-09-09, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음))
- [2] KOMIS 공식 데이터 · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(코발트) · 국가별 생산량 상위 1개 (기준시점 2026\~2026)
- [3] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(코발트) · 국가별 수입금액 상위 1개 (기준시점 2026-06-01\~2026-09-09)

### GM14 — BLOCKED_DATA

질문: 중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘

데이터를 찾을 수 없습니다.

### REG01 — FAIL

질문: 리튬 주요 수출국을 알려줘

제공된 문서에서 근거를 찾지 못했습니다.

데이터를 찾을 수 없습니다.

### REG02 — PASS

질문: 오늘 니켈 가격 얼마야?

2026-09-08 기준 니켈 가격은 16,745.53 USD/톤입니다. 전일 대비 +340.37(+2.07%) 변동했습니다.

### REG03 — PASS

질문: 최근 니켈 가격 얼마야?

2026-09-08 기준 니켈 가격은 16,745.53 USD/톤입니다. 전일 대비 +340.37(+2.07%) 변동했습니다.

### REG04 — PASS

질문: 니켈 가격 년도별 평균 가격을 알려줘

니켈 연도별 평균 가격은 [2026 YTD 17,092, 2025 15,003.51, 2024 16,811.63, 2023 21,473.88, 2022 25,604.52, 2021 18,487.78, 2020 13,789.31, 2019 13,936.44, 2018 13,122.27, 2017 10,411.35, 2016 9,608.7, 2015 11,807.23, 2014 16,867.13, 2013 15,003.5, 2012 17,526.05, 2011 22,830.54, 2010 21,809.29, 2009 14,700.02, 2008 21,027.22, 2007 37,195.48, 2006 24,286.81, 2005 14,732.72, 2004 13,851.65, 2003 9,640.34, 2002 6,770.92]입니다. 단위: USD/톤

### REG05 — PASS

질문: 니켈 LME 재고량 알려줘

최신 보유 관측일(2026-09-08) 가격 요약입니다. 조회된 값 기준입니다. 가격 기준은 LME CASH이며, 통화는 USD이며, 중량 단위는 톤입니다.

최신 가격은 16,745.53 (2026-09-08). 최고가는 17,395.01 (2026-08-04). 최저가는 16,135.56 (2026-09-02). 고저 차는 1,259.45(최저가 대비 +7.81%). 시작 값 대비 최신 값 변화는 - 517.1 (-3.00%). 최근 가격 흐름은 하락 추세(-1.04%)입니다.

표와 차트는 조회된 가격값으로 작성했습니다.

### REG06 — BLOCKED_DATA

질문: 니켈 텅스텐 가격 같이 비교해줘

데이터를 찾을 수 없습니다.

### REG07 — BLOCKED_DATA

질문: 니켈 다음달 가격 전망 알려줘

데이터를 찾을 수 없습니다.

### REG08 — PASS

질문: 니켈 수입 집중도를 알려줘요

니켈 수입 집중도에 관한 정보는 다음과 같습니다.

| 구분 | 수치 |
| --- | --- |
| HHI (Herfindahl-Hirschman Index) | 2327.98 [1] |
| 전체 수입금액 합계 | 236,080,000.0 USD [1] |

니켈 수입 집중도는 HHI 지수 기준 2327.98입니다 [1]. 해당 데이터의 실제 조회기간은 2026-06-01부터 2026-09-09까지이며, 전체 국가 합계인 236,080,000.0 USD를 분모로 하여 집계되었습니다 [1].

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 원천 · KO_CSTM_CMMRC(니켈) · 국가별 수입금액 집중도(HHI=2327.98, 전체합계=236080000.0, Σ(국가별 비중[%]^2)) 상위 10개 (기준시점 2026-06-01\~2026-09-09)

원본 SSE terminal·응답 전문: `user_qa_pair_audit_20260928_024048.json`
