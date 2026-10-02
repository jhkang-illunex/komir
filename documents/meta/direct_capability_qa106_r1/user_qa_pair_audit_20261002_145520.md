# 사용자 제공 Q&A 쌍 라이브 점검 결과

- 실행 시각: 20261002_145520 (Asia/Seoul)
- 대상: `http://127.0.0.1:18012/pubchat`
- 질문 수: 57
- DEBUG 처리 진단 기록: 비활성
- 집계: BLOCKED_DATA 1, FAIL 16, PARTIAL 17, PASS 23

판정: `PASS`는 SSE 종료 계약과 질문별 기대 표지가 확인된 응답, `PARTIAL`은 응답은 있으나 기대 표지 일부가 없는 경우, `BLOCKED_DATA`는 `source_unavailable` 안전 종료, `FAIL`은 요청/종료 계약 오류 또는 기타 기권입니다. 키워드 검사는 형식 점검 보조 수단이며 사실성의 최종 판정은 아닙니다.

|ID|판정|질문|Action / Source|표·차트|비고|
|---|---|---|---|---|---|
|MI01|PASS|니켈은 어디에 쓰여?|document.retrieve, Royal Society of Chemistry|표 0 / 차트 0|-|
|MI02|PARTIAL|니켈은 어떤 금속이야?|document.retrieve, 공식 문서 원문|표 0 / 차트 0|기대 표지 미검출: 원소, 특성|
|MI03|PASS|구리 기본 특성을 알려줘|document.retrieve, Royal Society of Chemistry|표 0 / 차트 0|-|
|MI04|PASS|망간 주요 광석 종류는?|document.retrieve, Royal Society of Chemistry|표 0 / 차트 0|-|
|DOC02|PASS|최근 월간동향 제목 알려줘|document.retrieve, PageIndex 파생 사실 · 전략광종 월간동향|표 1 / 차트 0|-|
|DOC04|PARTIAL|월간 동향 게시판 검색은 어떻게 해?|-|표 0 / 차트 0|기대 표지 미검출: 검색, 개월|
|NEWS01|PASS|최근 자원 뉴스 뭐 있어?|document.retrieve, KOMIS 공식 데이터|표 1 / 차트 0|-|
|NEWS03|PASS|최근 중국 수출통제 관련 뉴스 있어?|document.retrieve, KOMIS 공식 데이터|표 1 / 차트 0|-|
|PF01|PARTIAL|니켈 현재 가격이랑 다음달 전망 같이 알려줘|public.KO_MNRL_PRC|표 2 / 차트 1|기대 표지 미검출: 전망|
|PF02|PARTIAL|니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘|public.KO_MNRL_PRC|표 2 / 차트 2|기대 표지 미검출: 전망|
|PF03|FAIL|니켈 지금 가격이 전망치 보다 높은 편이야?|-|표 0 / 차트 0|abstain_reason=no_comparable_rows|
|IX01|FAIL|광물지수 오를때 같이 오른 광종은 뭐야?|-|표 0 / 차트 0|abstain_reason=semantic_plan_incomplete|
|IX02|FAIL|니켈 가격 추세랑 광물 종합지수 추세 비교해주세요|-|표 0 / 차트 0|abstain_reason=comparison_field_required|
|MP01|PARTIAL|니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘|public.KO_MNRL_PRC|표 1 / 차트 1|기대 표지 미검출: 수입|
|MP03|PARTIAL|니켈 수입 상위국이랑 현재가격 알려줘|public.KO_MNRL_PRC|표 1 / 차트 0|기대 표지 미검출: 수입, 가격|
|MP04|FAIL|니켈 가격이랑 세계 생산량 변화 같이 보여줘|-|표 0 / 차트 0|abstain_reason=projection_field_unavailable:date|
|MP05|BLOCKED_DATA|생산 1위국 비중이 높은 광종들 가격 변동 어때?|-|표 0 / 차트 0|abstain_reason=source_unavailable|
|MP06|PARTIAL|니켈은 어디에 쓰이고 지금 가격은 얼마야?|nas_document/학습데이터/철광석/Iron Ore_Vale_Form 20-F - 2025.pdf, public.KO_MNRL_PRC|표 1 / 차트 0|기대 표지 미검출: 용도|
|MP07|PASS|전략광종 가격 현황 한눈에 보여줘|price.overview, KOMIS 공식 데이터|표 1 / 차트 0|-|
|MP09|PARTIAL|니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘|public.KO_MNRL_PRC|표 2 / 차트 1|기대 표지 미검출: 월간|
|CN01|PASS|니켈 가격 크게 오른 날 관련 뉴스 있어?|price.series, KOMIS 공식 데이터|표 0 / 차트 0|-|
|CN04|PARTIAL|수입 의존도 높은 광종들 가격 전망 알려줘|trade.country_rank, KOMIS 공식 데이터|표 5 / 차트 0|기대 표지 미검출: 전망|
|CN05|FAIL|리튬 주요 수입국이랑 가격 전망 같이 보여줘|-|표 0 / 차트 0|abstain_reason=all_roots_failed|
|CN07|FAIL|리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘|-|표 0 / 차트 0|abstain_reason=all_roots_failed|
|CN08|FAIL|지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘|-|표 0 / 차트 0|abstain_reason=all_roots_failed|
|CN09|PARTIAL|광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?|indicator.series, KOMIS 공식 데이터|표 1 / 차트 1|기대 표지 미검출: 뉴스|
|GM01|FAIL|코발트 세계 생산국이랑 우리나라 수입국 비교해줘|-|표 0 / 차트 0|abstain_reason=dependency_unavailable|
|GM02|FAIL|리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?|-|표 0 / 차트 0|abstain_reason=projection_field_unavailable:country|
|GM04|PASS|2차전지 광물 수입국 구성 알려줘|trade.country_rank, KOMIS 공식 데이터, 공식 문서 원문|표 5 / 차트 3|-|
|GM05|PARTIAL|망간 용도랑 주요 수입국 알려줘|documents/3. 생산매장량(USGS)/USGS_2019.pdf, documents/3. 생산매장량(USGS)/USGS_2022.pdf, documents/3. 생산매장량(USGS)/USGS_2023.pdf, documents/3. 생산매장량(USGS)/USGS_2024.pdf, documents/3. 생산매장량(USGS)/USGS_2025.pdf|표 0 / 차트 0|기대 표지 미검출: 용도, 수입, 필수 Action 미성공: document.retrieve, 필수 Action 미성공: trade.country_rank|
|GM08|PARTIAL|텅스텐 용도랑 세계 생산국 알려줘|documents/3. 생산매장량(USGS)/USGS_2022.pdf, documents/3. 생산매장량(USGS)/USGS_2023.pdf|표 0 / 차트 0|기대 표지 미검출: 용도, 생산, 필수 Action 미성공: document.retrieve, 필수 Action 미성공: resource.rank|
|GM11|FAIL|흑연 공급 현황 종합해서 알려줘|-|표 0 / 차트 0|abstain_reason=all_roots_failed|
|GM12|FAIL|2차전지 광물 5종 가격이랑 전망 한 번에 보여줘|-|표 0 / 차트 0|abstain_reason=semantic_plan_incomplete|
|GM13|FAIL|코발트 현황 브리핑해줘|-|표 0 / 차트 0|abstain_reason=all_roots_failed|
|GM14|PASS|중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘|document.retrieve, price.series, trade.indicator, KOMIS 공식 데이터|표 3 / 차트 1|-|
|REG02|PASS|오늘 니켈 가격 얼마야?|price.series, KOMIS 공식 데이터|표 1 / 차트 0|-|
|REG03|PASS|최근 니켈 가격 얼마야?|price.series, KOMIS 공식 데이터|표 1 / 차트 0|-|
|REG04|PASS|니켈 가격 년도별 평균 가격을 알려줘|price.series, KOMIS 공식 데이터|표 0 / 차트 0|-|
|REG05|PASS|니켈 LME 재고량 알려줘|inventory.latest, KOMIS 공식 데이터|표 0 / 차트 0|-|
|REG06|PASS|니켈 텅스텐 가격 같이 비교해줘|price.series, KOMIS 공식 데이터|표 1 / 차트 0|-|
|ADD01|FAIL|리튬 최신 가격 얼마야?|-|표 0 / 차트 0|abstain_reason=ambiguous|
|ADD03|FAIL|아연 가격 2010년 이후 최고가와 그 날짜 알려줘|-|표 0 / 차트 0|abstain_reason=ambiguous|
|ADD06|PARTIAL|니켈 가격 전년 동월 대비 변화율은?|price.series, KOMIS 공식 데이터|표 0 / 차트 0|기대 표지 미검출: 변화율|
|ADD12|PASS|방금 답변 원본 데이터는 KOMIS 어디서 확인해?|-|표 0 / 차트 0|-|
|ADD15|FAIL|희토류 생산량과 매장량 상위 5개국을 각각 차트로 보여줘|-|표 0 / 차트 0|abstain_reason=all_roots_failed|
|ADD16|PARTIAL|세계 리튬 매장량 중 칠레 비중은?|resource.rank, KOMIS 공식 데이터|표 1 / 차트 1|기대 표지 미검출: 리튬, 비중|
|ADD18|PASS|광물종합지수 최근 12개월 추이 보여줘|indicator.series, KOMIS 공식 데이터|표 1 / 차트 1|-|
|ADD25|PARTIAL|구리, 니켈, 코발트 최근 1년 가격 추이 비교해줘|price.series, KOMIS 공식 데이터|표 1 / 차트 1|기대 표지 미검출: 구리, 코발트|
|ADD27|PASS|니켈 가격 추이 좀 보여줘|price.series, KOMIS 공식 데이터|표 1 / 차트 0|-|
|ADD32|PASS|중국 희토류 수출통제 관련 최신 내용 요약하고 출처 달아줘|document.retrieve, KOMIS 공식 데이터|표 1 / 차트 0|-|
|ADD38|PASS|7개 광종의 최신 가격, 기준일, 단위, 출처를 한 표로 정리해줘|price.series, KOMIS 공식 데이터|표 1 / 차트 0|-|
|ADD40|PASS|우드맥킨지 보고서 기준 리튬 전망 알려줘|document.retrieve, 공식 문서 원문|표 1 / 차트 1|-|
|ADD45|PASS|리튬 가격 화면으로 가줘|-|표 0 / 차트 0|-|
|ADD46|PASS|수급지도 대한민국 페이지 어디서 봐?|-|표 0 / 차트 0|-|
|ADD47|PARTIAL|핵심광물이 뭐야? 왜 중요해?|-|표 0 / 차트 0|기대 표지 미검출: 중요|
|ADD48|PARTIAL|여기서 뭘 물어볼 수 있어?|-|표 0 / 차트 0|기대 표지 미검출: 질문|
|ADD49|FAIL|구리 가격 알려줘|-|표 0 / 차트 0|abstain_reason=ambiguous|

## 응답 원문 발췌

### MI01 — PASS

질문: 니켈은 어디에 쓰여?

니켈의 주요 용도는 스테인리스강·합금, 금속 도금, 충전식 배터리입니다.

### MI02 — PARTIAL

질문: 니켈은 어떤 금속이야?

니켈은 배터리의 4대 구성요소인 양극재, 음극재, 분리막, 전해질 중 양극재의 핵심 원료광물로서 에너지 밀도를 향상시키는 데 중요한 역할을 하는 금속입니다 [2].

니켈의 산업 가치 사슬(Value Chain)에 따른 분류와 용도는 다음과 같습니다.

1. 품위 및 광석 종류에 따른 구분
* 황화광(Class 1): 고품위 광석으로, 제련을 통해 니켈파우더 또는 니켈브리켓으로 생산할 수 있습니다 [1]. 또한 니켈 매트를 만든 뒤 재가공하여 황산니켈 형태로 변환하면 배터리 원자재로 사용됩니다 [2].
* 산화광(Class 2): 저품위 광석으로, 라테라이트(Laterite)가 이에 해당합니다 [1][2].

2. 제련 제품 및 용도
* 황산니켈: 리튬-이온 배터리 소재로 사용됩니다 [1].
* 니켈 캐소드: 합금철강용으로 사용됩니다 [1].
* 니켈선철(NPI) 및 페로니켈: 스테인리스 소재로 사용됩니다 [1][2].
* 산화니켈: 연막제로 사용됩니다 [1].

현재 니켈 용도의 70%는 스테인리스이며, 배터리용은 5%에 불과합니다 [2].

출처:
- [1] 공식 문서 원문 · ❙2.  니켈  공급구조  분석  및  인니내  니켈제련소  현황 (기준시점 자원정보포커스)
- [2] 공식 문서 원문 · ❙니켈 최대 생산국, 라테라이트(Laterite)의 재발견으로 외국투자 러쉬 (기준시점 자원정보포커스)

### MI03 — PASS

질문: 구리 기본 특성을 알려줘

구리는 원소기호 Cu, 원자번호 29의 금속이며, 주요 특성은 적갈색 금속, 열과 전기를 잘 전도, 가늘게 뽑아 전선으로 가공 가능입니다.

### MI04 — PASS

질문: 망간 주요 광석 종류는?

망간의 주요 광석은 파이롤루사이트(pyrolusite, MnO₂), 로도크로사이트(rhodochrosite, MnCO₃)입니다.

### DOC02 — PASS

질문: 최근 월간동향 제목 알려줘

최근 월간동향의 제목은 '2026-06_전략광종월간동향_KOMIS'입니다. [1]

출처:
- [1] PageIndex 파생 사실 · 전략광종 월간동향 · 2026-06_전략광종월간동향_KOMIS (기준시점 2026-06)

### DOC04 — PARTIAL

질문: 월간 동향 게시판 검색은 어떻게 해?

질문만으로는 페이지를 하나로 확정하기 어려워 관련 페이지를 함께 안내합니다.
- `KOMIS > 광물자원동향 > 전략광종 월간동향`: 전략광종 인사이트 월간 자료를 조회하는 게시판
  주소: https://www.komis.or.kr/Komis/Board/STRGMONTH
- `KOMIS > 광물자원동향 > 희소금속 월간동향`: 희소금속 더프라임 월간 자료를 조회하는 게시판
  주소: https://www.komis.or.kr/Komis/Board/RAREMONTH
설명을 비교한 뒤 원하는 관점의 페이지에서 직접 확인해 주세요.

### NEWS01 — PASS

질문: 최근 자원 뉴스 뭐 있어?

최근 자원뉴스 : 확인된 기사
- 미국, 핵심광물 공급망 확대 속 광업 전문인력 양성 지원 강화 (2026-09-30)
- 인도, 전력수요 증가 대응 위해 자가소비용 석탄발전소 가동 최대화 지시 (2026-09-29)
- 칠레 Escondida 동 광산, 사망사고로 조업중단 후 단계적 재개 돌입 (2026-09-29)
- 인도네시아 Morowali 산업단지, 가뭄으로 니켈선철 생산 감축 (2026-09-28)
- 인도네시아, 니켈 생산쿼터 축소에도 수입 증가로 공급조절 효과 제한 (2026-09-23)

### NEWS03 — PASS

질문: 최근 중국 수출통제 관련 뉴스 있어?

최근 자원뉴스 : 확인된 기사
- 미국, 핵심광물 공급망 확대 속 광업 전문인력 양성 지원 강화 (2026-09-30)
- 인도, 전력수요 증가 대응 위해 자가소비용 석탄발전소 가동 최대화 지시 (2026-09-29)
- 칠레 Escondida 동 광산, 사망사고로 조업중단 후 단계적 재개 돌입 (2026-09-29)
- 인도네시아 Morowali 산업단지, 가뭄으로 니켈선철 생산 감축 (2026-09-28)
- 인도네시아, 니켈 생산쿼터 축소에도 수입 증가로 공급조절 효과 제한 (2026-09-23)

### PF01 — PARTIAL

질문: 니켈 현재 가격이랑 다음달 전망 같이 알려줘

node_nickel_price_current
| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) | value | status | reason | output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261001 | 22599.94 | 23623.44 | 23111.69 | None | 23111.69 | success | None | latest_value |
node_nickel_price_forecast
| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) | value | status | reason | output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261001 | 22599.94 | 23623.44 | 23111.69 | None | 23111.69 | success | None | time_series |
| 20260930 | 22775.99 | 23057.47 | 22916.73 | None | 22916.73 | success | None | time_series |
| 20260929 | 22166.46 | 22359.63 | 22263.05 | None | 22263.05 | success | None | time_series |
| 20260928 | 21407.2 | 21656.74 | 21531.97 | None | 21531.97 | success | None | time_series |
| 20260925 | 20778.6 | 20949.93 | 20864.26 | None | 20864.26 | success | None | time_series |
| 20260924 | 20568.83 | 20924.02 | 20746.42 | None | 20746.42 | success | None | time_series |
| 20260923 | 20150.44 | 20487.6 | 20319.02 | None | 20319.02 | success | None | time_series |
| 20260922 | 19902.94 | 20063.19 | 19983.07 | None | 19983.07 | success | None | time_series |
| 20260921 | 20655.57 | 20963.46 | 20809.51 | None | 20809.51 | success | None | time_series |
| 20260918 | 20105.44 | 20345.6 | 20225.52 | None | 20225.52 | success | None | time_series |
| 20260917 | 19984.29 | 20099.48 | 20041.88 | None | 20041.88 | success | None | time_series |
| 20260916 | 19565.86 | 19606.55 | 19586.21 | None | 19586.21 | success | None | time_series |
| 20260915 | 18756.64 | 19066.46 | 18911.55 | None | 18911.55 | success | None | time_series |
| 20260914 | 18422.75 | 18500.98 | 18461.86 | None | 18461.86 | succes…(생략)

### PF02 — PARTIAL

질문: 니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘

node_1
| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) | value | status | reason | output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261001 | 22599.94 | 23623.44 | 23111.69 | None | 23111.69 | success | None | time_series |
| 20260930 | 22775.99 | 23057.47 | 22916.73 | None | 22916.73 | success | None | time_series |
| 20260929 | 22166.46 | 22359.63 | 22263.05 | None | 22263.05 | success | None | time_series |
| 20260928 | 21407.2 | 21656.74 | 21531.97 | None | 21531.97 | success | None | time_series |
| 20260925 | 20778.6 | 20949.93 | 20864.26 | None | 20864.26 | success | None | time_series |
| 20260924 | 20568.83 | 20924.02 | 20746.42 | None | 20746.42 | success | None | time_series |
| 20260923 | 20150.44 | 20487.6 | 20319.02 | None | 20319.02 | success | None | time_series |
| 20260922 | 19902.94 | 20063.19 | 19983.07 | None | 19983.07 | success | None | time_series |
| 20260921 | 20655.57 | 20963.46 | 20809.51 | None | 20809.51 | success | None | time_series |
| 20260918 | 20105.44 | 20345.6 | 20225.52 | None | 20225.52 | success | None | time_series |
| 20260917 | 19984.29 | 20099.48 | 20041.88 | None | 20041.88 | success | None | time_series |
| 20260916 | 19565.86 | 19606.55 | 19586.21 | None | 19586.21 | success | None | time_series |
| 20260915 | 18756.64 | 19066.46 | 18911.55 | None | 18911.55 | success | None | time_series |
| 20260914 | 18422.75 | 18500.98 | 18461.86 | None | 18461.86 | success | None | time_series |
| 20260911 | 17707.21 | 17959.62 | 17833.41 | None | 17833.41 | success | None | time_series |
| 20260910 | 17195.19 | 17472.86 | 17334.02 | None | 17334.02 | success | None | time_series |
| 20260909 | 16931.06 | 17215.59 | 17073.32 | None | 17073.32 | success | None | time_series |
| 20260…(생략)

### PF03 — FAIL

질문: 니켈 지금 가격이 전망치 보다 높은 편이야?

no_comparable_rows

### IX01 — FAIL

질문: 광물지수 오를때 같이 오른 광종은 뭐야?

질문을 처리할 실행 계획을 생성하지 못했습니다. 데이터가 없다는 의미는 아닙니다.

### IX02 — FAIL

질문: 니켈 가격 추세랑 광물 종합지수 추세 비교해주세요

comparison_field_required

### MP01 — PARTIAL

질문: 니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘

node_nickel_price_ts
| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) | value | status | reason | output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261001 | 22599.94 | 23623.44 | 23111.69 | None | 23111.69 | success | None | time_series |
| 20260930 | 22775.99 | 23057.47 | 22916.73 | None | 22916.73 | success | None | time_series |
| 20260929 | 22166.46 | 22359.63 | 22263.05 | None | 22263.05 | success | None | time_series |
| 20260928 | 21407.2 | 21656.74 | 21531.97 | None | 21531.97 | success | None | time_series |
| 20260925 | 20778.6 | 20949.93 | 20864.26 | None | 20864.26 | success | None | time_series |
| 20260924 | 20568.83 | 20924.02 | 20746.42 | None | 20746.42 | success | None | time_series |
| 20260923 | 20150.44 | 20487.6 | 20319.02 | None | 20319.02 | success | None | time_series |
| 20260922 | 19902.94 | 20063.19 | 19983.07 | None | 19983.07 | success | None | time_series |
| 20260921 | 20655.57 | 20963.46 | 20809.51 | None | 20809.51 | success | None | time_series |
| 20260918 | 20105.44 | 20345.6 | 20225.52 | None | 20225.52 | success | None | time_series |
| 20260917 | 19984.29 | 20099.48 | 20041.88 | None | 20041.88 | success | None | time_series |
| 20260916 | 19565.86 | 19606.55 | 19586.21 | None | 19586.21 | success | None | time_series |
| 20260915 | 18756.64 | 19066.46 | 18911.55 | None | 18911.55 | success | None | time_series |
| 20260914 | 18422.75 | 18500.98 | 18461.86 | None | 18461.86 | success | None | time_series |
| 20260911 | 17707.21 | 17959.62 | 17833.41 | None | 17833.41 | success | None | time_series |
| 20260910 | 17195.19 | 17472.86 | 17334.02 | None | 17334.02 | success | None | time_series |
| 20260909 | 16931.06 | 17215.59 | 17073.32 | None | 17073.32 | success | None | time_se…(생략)

### MP03 — PARTIAL

질문: 니켈 수입 상위국이랑 현재가격 알려줘

node_top_importers
projection_field_unavailable:country
node_current_price
| value |
| --- |
| 23111.69 |
| 22916.73 |
| 22263.05 |
| 21531.97 |
| 20864.26 |
| 20746.42 |
| 20319.02 |
| 19983.07 |
| 20809.51 |
| 20225.52 |
| 20041.88 |
| 19586.21 |
| 18911.55 |
| 18461.86 |
| 17833.41 |
| 17334.02 |
| 17073.32 |
| 16745.53 |
| 16405.16 |
| 16438.86 |
| 16331.02 |
| 16135.56 |
| 16536.59 |
| 16378.2 |
| 16286.18 |
| 16766.76 |
| 17024.8 |
| 16904.21 |
| 16184.15 |
| 16671.14 |
| 16872.35 |
| 17026.25 |
| 16357.7 |
| 16310.73 |
| 16479.55 |
| 16630.31 |
| 16573.06 |
| 17205.58 |
| 17223.79 |
| 16706.64 |
| 16429.84 |
| 16684.1 |
| 17395.01 |
| 16421.12 |
| 16725.28 |
| 16478.99 |
| 17078.02 |
| 17315.74 |
| 17278.71 |
| 17034.39 |
| 16973.68 |
| 17070.2 |
| 16596.39 |
| 16293.86 |
| 16818.53 |
| 16945.23 |
| 16521.13 |
| 16420.28 |
| 16665.72 |
| 16597.22 |
일부 요청 결과만 확인되었습니다.

### MP04 — FAIL

질문: 니켈 가격이랑 세계 생산량 변화 같이 보여줘

projection_field_unavailable:date

### MP05 — BLOCKED_DATA

질문: 생산 1위국 비중이 높은 광종들 가격 변동 어때?

데이터를 찾을 수 없습니다.

### MP06 — PARTIAL

질문: 니켈은 어디에 쓰이고 지금 가격은 얼마야?

node_1
- • nickel content and purity level: (i) intermediates have various levels of nickel content, (ii) nickel pig iron has 1.5-15% nickel, (iii) ferronickel has 15-40% nickel, (iv) refined nickel with less than 99.8% nickel, including products such as Tonimet™ nickel, (v) standard LME-grade nickel has a minimum of 99.8% nickel, and (vi) high-purity nickel has a minimum of 99.9% nickel and does not contain specific elemental impurities;
- • shape (such as discrete or filamentary powders, pellets, discs, squares and strips);
- • size (from micron powder particles to large full-sized cathodes); and
- • packaging (such as bulk, 2-ton bags, 250 kg drums, 10 kg bags).

In 2025, the principal first-use applications for primary nickel were:

- • stainless steel (63% of global nickel consumption);
- • non-ferrous alloys, alloy steels and foundry applications (14% of global nickel consumption);
- • nickel plating (5% of global nickel consumption);
- • battery precursors (15% of global nickel consumption); and
- • others (3% of global nickel consumption).
node_3
| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) | value | status | reason | output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261001 | 22599.94 | 23623.44 | 23111.69 | None | 23111.69 | success | None | latest_value |

### MP07 — PASS

질문: 전략광종 가격 현황 한눈에 보여줘

광물정보 : 전략광종 목록 기준
광물가격 : 광종별 최신 가격·기준일·단위·출처
| 광종 | 기준일 | 가격 | 가격기준 | 단위 | 출처 |
|---|---|---:|---|---|---|
| 유연탄 | - | - | - | - | - |
| 우라늄 | - | - | - | - | - |
| 철광석 | - | - | - | - | - |
| 구리 | - | - | - | - | - |
| 아연 | - | - | - | - | - |
| 니켈 | 2026-10-01 | 23111.69 | LME CASH | USD/톤 | price_base_metals |
| 리튬 | - | - | - | - | - |
| 니켈 | 2026-10-01 | 23111.69 | LME CASH | USD/톤 | price_base_metals |
| 코발트 | - | - | - | - | - |
| 망간 | 2026-10-01 | 919.89 | 페로망간 | USD/mt | price_minor_metals |
| 흑연 | 2026-10-01 | 500.19 | -194 FOB China | USD/mt | price_other |
| 네오디윰 | 2026-10-01 | 95.03 | 산화네오디뮴 | USD/kg | price_minor_metals |
| 디스프로슘 | 2026-10-01 | 360.8 | 산화디스프로슘 | USD/kg | price_minor_metals |
| 터븀 | 2026-10-01 | 609.75 | 산화터븀 | USD/kg | price_minor_metals |
| 세륨 | 2026-10-01 | 1.36 | 산화세륨 | USD/kg | price_minor_metals |
| 란탄 | 2026-10-01 | 1.94 | 산화란탄 | USD/kg | price_minor_metals |
※ 광종별 가격기준과 관측일이 다르므로 절대가격을 서로 직접 비교하지 않습니다.

출처:
- [1] KOMIS 공식 데이터 · 구조화 데이터

### MP09 — PARTIAL

질문: 니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘

node_price_ts
| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) | value | status | reason | output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261001 | 22599.94 | 23623.44 | 23111.69 | None | 23111.69 | success | None | time_series |
| 20260930 | 22775.99 | 23057.47 | 22916.73 | None | 22916.73 | success | None | time_series |
| 20260929 | 22166.46 | 22359.63 | 22263.05 | None | 22263.05 | success | None | time_series |
| 20260928 | 21407.2 | 21656.74 | 21531.97 | None | 21531.97 | success | None | time_series |
| 20260925 | 20778.6 | 20949.93 | 20864.26 | None | 20864.26 | success | None | time_series |
| 20260924 | 20568.83 | 20924.02 | 20746.42 | None | 20746.42 | success | None | time_series |
| 20260923 | 20150.44 | 20487.6 | 20319.02 | None | 20319.02 | success | None | time_series |
| 20260922 | 19902.94 | 20063.19 | 19983.07 | None | 19983.07 | success | None | time_series |
| 20260921 | 20655.57 | 20963.46 | 20809.51 | None | 20809.51 | success | None | time_series |
| 20260918 | 20105.44 | 20345.6 | 20225.52 | None | 20225.52 | success | None | time_series |
| 20260917 | 19984.29 | 20099.48 | 20041.88 | None | 20041.88 | success | None | time_series |
| 20260916 | 19565.86 | 19606.55 | 19586.21 | None | 19586.21 | success | None | time_series |
| 20260915 | 18756.64 | 19066.46 | 18911.55 | None | 18911.55 | success | None | time_series |
| 20260914 | 18422.75 | 18500.98 | 18461.86 | None | 18461.86 | success | None | time_series |
| 20260911 | 17707.21 | 17959.62 | 17833.41 | None | 17833.41 | success | None | time_series |
| 20260910 | 17195.19 | 17472.86 | 17334.02 | None | 17334.02 | success | None | time_series |
| 20260909 | 16931.06 | 17215.59 | 17073.32 | None | 17073.32 | success | None | time_series |
…(생략)

### CN01 — PASS

질문: 니켈 가격 크게 오른 날 관련 뉴스 있어?

연속 가격 관측 구간에서 전일 대비 5% 이상 상승한 날을 찾지 못해 같은 날 관련 뉴스는 조회하지 않았습니다.

### CN04 — PARTIAL

질문: 수입 의존도 높은 광종들 가격 전망 알려줘

광물정보 : 2차전지 원료 광종 리튬, 니켈, 코발트, 망간, 흑연
핵심광물 수급지도 : 실제 확인된 자료 기간 2025-11-01\~2026-07-01 기준 광종별 수입 1위국
구리 : 칠레 (22.38%)
니켈 : 인도네시아 (25.47%)
코발트 : 중국 (24%)
리튬 : 중국 (37.68%)
희토류 : 중국 (49.83%)

### CN05 — FAIL

질문: 리튬 주요 수입국이랑 가격 전망 같이 보여줘

all_roots_failed

### CN07 — FAIL

질문: 리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘

all_roots_failed

### CN08 — FAIL

질문: 지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘

all_roots_failed

### CN09 — PARTIAL

질문: 광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?

2026-07-02\~2026-09-05 광물종합지수는 3,361.28에서 3,651.45으로 +8.63% 상승했습니다.

### GM01 — FAIL

질문: 코발트 세계 생산국이랑 우리나라 수입국 비교해줘

dependency_unavailable

### GM02 — FAIL

질문: 리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?

projection_field_unavailable:country

### GM04 — PASS

질문: 2차전지 광물 수입국 구성 알려줘

제공된 문서의 근거를 바탕으로 2차전지 관련 주요 광물(리튬, 니켈, 코발트, 흑연)의 수입국 구성 현황을 정리해 드립니다.

### 1. 리튬 수입국 구성
*   **분모:** 전체 국가 합계 1,181,219,931.0 USD [1] | 순위 | 국가 | 수입금액 합계 (USD) | 수입금액 비중 (%) | 거래건수 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 중국 | 445,140,228.0 | 37.68 | 36 |
| 2 | 칠레 | 318,389,207.0 | 26.95 | 18 |
| 3 | 인도네시아 | 233,440,644.0 | 19.76 | 21 |
| 4 | 호주 | 101,811,750.0 | 8.62 | 17 |
| 5 | 아르헨티나 | 40,038,292.0 | 3.39 | 14 | [1] 또한, 2024년 기준 산화리튬, 수산화리튬, 탄산리튬의 수입국 비중은 다음과 같습니다. [6] *   **산화리튬:** 미국 55%, 중국 44%, 일본 1% 등 [6] *   **수산화리튬:** 중국 83%, 칠레 13%, 미국 2% 등 [6] *   **탄산리튬:** 칠레 76%, 아르헨티나 22%, 중국 2% 등 [6] ### 2. 니켈 수입국 구성
*   **분모:** 전체 국가 합계 1,470,007,048.0 USD [8]

집계 기간 2025-11-01\~2026-07-01의 한국 해당 광종 수입금액(USD) 기준 상위 5개국은 1위 중국(37.68%), 2위 칠레(26.95%), 3위 인도네시아(19.76%), 4위 호주(8.62%), 5위 아르헨티나(3.39%) 순입니다. 국가별 비중은 2025-11-01\~2026-07-01 조회 대상 해당 광종 HS 품목의 한국 수입금액(USD) 합계에서 각 국가가 차지하는 비율입니다.

※ 위 설명은 지표 변동과 동시에 나타난 문서상 흐름을 정리한 것으로, 직접적인 인과관계를 단정하는 내용이 아닙니다.

출처:
- [1] KOMIS 공식 데이터 · KOMIS 핵심광물지도 > 수급지도 > 대한민국 (기준시점 2025-11-01\~2026-07-01)
- [6] 공식 문서 원문 · 1 리튬 (기준시점 시장동향보고서)
- [8] KOMIS 공식 데이터 · KOMIS 핵심광물지도 > 수급지도 > 대한민국 (기준시점 2025-11-01\~2026-07-01)
- [15] KOMIS 공식 데이터 · KOMIS 핵심광물지도 > 수급지도 > 대한민국 (기준시점 2025-11-01\~2026-07-01)
- [22] 공식 문서 원문 · 품목 HS CODE 구분 2018 2019 2020 2021 2022 (기준시점 시장동향보고서)
- [28] 공식 문서 원문 · 국내 흑연 주요 품목 수출입 추이(단위 : 톤, 천$) (기준시점 시장동향보고서)

### GM05 — PARTIAL

질문: 망간 용도랑 주요 수입국 알려줘

node_usage_doc
Domestic Production and Use: Manganese ore containing 20% or more manganese has not been produced domestically since 1970. Manganese ore was consumed mainly by five companies: three companies produced manganese dioxide for pig iron manufacture and two companies produced silicomanganese and ferromanganese. Other companies consumed ore for nonmetallurgical purposes, such as in the production of animal feed, brick colorant, dry cell batteries, and fertilizers.

Salient Statistics—United States:1 2020 2021 2022 2023 2024e Production, mine — — — — Imports for consumption:

Manganese ores and concentrates 367 497 566 245 320 Ferromanganese 223 329 330 320 310 Silicomanganese 269 313 420 257 370

Exports:

Manganese ores and concentrates 1 1 1 2 3 Ferromanganese 5 9 3 2 2 Silicomanganese 2 5 3 4 4

Shipments from Government stockpile:2

Manganese ore — 2 — NA NA Ferromanganese and manganese metal, electrolytic 54 21 14 NA NA

Consumption, reported:

Manganese ore3 378 399 357 321 320 Ferromanganese 325 335 339 336 300 Silicomanganese 229 237 234 230 230

Consumption, apparent, manganese content4 621 717 804 653 680 Price, average, manganese content, cost, insurance, and freight,

4.58 5.27 5.97 4.80 5.80 Stocks, producer and consumer, yearend:

China, dollars per metric ton unit5

Manganese ore3 143 220 312 233 230 Ferromanganese 35 40 50 27 30 Silicomanganese 31 34 26 18 20

Domestic Production and Use: Manganese ore containing 20% or more manganese has not been produced domestically since 1970. Manganese ore was consumed mainly by five companies at six facilities with plants principally in the Eastern and Midwestern States. Most ore consumption was related to steel production, either directly in pig iron manufacture or indirectly through upgrading the ore to f…(생략)

### GM08 — PARTIAL

질문: 텅스텐 용도랑 세계 생산국 알려줘

node_1
- World Resources:9 World tungsten resources are geographically widespread. China ranks first in the world in terms of tungsten resources and reserves and has some of the largest deposits. Canada, Kazakhstan, Russia, and the United States also have significant tungsten resources.

Substitutes: Potential substitutes for cemented tungsten carbides include cemented carbides based on molybdenum carbide, niobium carbide, or titanium carbide; ceramics; ceramic-metallic composites (cermets); and tool steels. Most of these options reduce, rather than replace, the amount of tungsten used. Potential substitutes for other applications are as follows: molybdenum for certain tungsten mill products; molybdenum steels for tungsten steels, although most molybdenum steels still contain tungsten; lighting based on carbon nanotube filaments, induction technology, and light-emitting diodes for lighting based on tungsten electrodes or filaments; depleted uranium or lead for tungsten or tungsten alloys in applications requiring high density or the ability to shield radiation; and depleted uranium alloys or hardened steel for cemented tungsten carbides or tungsten alloys in armor-piercing projectiles. In some applications, substitution would result in increased cost or a loss in product performance.

World Resources:11 World tungsten resources are geographically widespread. China ranks first in the world in terms of tungsten resources and reserves and has some of the largest deposits. Significant tungsten resources have been identified on every continent except Antarctica.

Substitutes: Potential substitutes for cemented tungsten carbides include cemented carbides based on molybdenum carbide, niobium carbide, or titanium carbide; ceramics; ceramic-metallic composites (cermets); and too…(생략)

### GM11 — FAIL

질문: 흑연 공급 현황 종합해서 알려줘

all_roots_failed

### GM12 — FAIL

질문: 2차전지 광물 5종 가격이랑 전망 한 번에 보여줘

질문을 처리할 실행 계획을 생성하지 못했습니다. 데이터가 없다는 의미는 아닙니다.

### GM13 — FAIL

질문: 코발트 현황 브리핑해줘

all_roots_failed

### GM14 — PASS

질문: 중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘

자원뉴스 : 수출통제 관련 기사에서 언급된 광종
핵심광물 수급지도 : 광종별 중국 수입 점유율은 함께 조회한 표를 참조
광물가격 : 최근 1개월 변동률 디스프로슘 (+44.84%)
※ 동반 관측 정보이며 가격 변동 원인으로 단정하지 않습니다.

### REG02 — PASS

질문: 오늘 니켈 가격 얼마야?

2026-10-01 기준 니켈 가격은 23,111.69 USD/톤입니다. 전일 대비 +194.96(+0.85%) 변동했습니다.

### REG03 — PASS

질문: 최근 니켈 가격 얼마야?

2026-10-01 기준 니켈 가격은 23,111.69 USD/톤입니다. 전일 대비 +194.96(+0.85%) 변동했습니다.

### REG04 — PASS

질문: 니켈 가격 년도별 평균 가격을 알려줘

니켈 연도별 평균 가격은 [2026 YTD 17,354.5, 2025 15,003.51, 2024 16,811.63, 2023 21,473.88, 2022 25,604.52, 2021 18,487.78, 2020 13,789.31, 2019 13,936.44, 2018 13,122.27, 2017 10,411.35, 2016 9,608.7, 2015 11,807.23, 2014 16,867.13, 2013 15,003.5, 2012 17,526.05, 2011 22,830.54, 2010 21,809.29, 2009 14,700.02, 2008 21,027.22, 2007 37,195.48, 2006 24,286.81, 2005 14,732.72, 2004 13,851.65, 2003 9,640.34, 2002 6,770.92]입니다. 단위: USD/톤

### REG05 — PASS

질문: 니켈 LME 재고량 알려줘

2026-09-08 기준 니켈 LME CASH 재고량은 272380 톤입니다.

### REG06 — PASS

질문: 니켈 텅스텐 가격 같이 비교해줘

| 광종 | 가격 비교 (2026-09-30 \~ 2026-10-01) |
| :--- | :--- |
| 니켈 | 통상가격 기준 22,916.73(2026-09-30) \~ 23,111.69(2026-10-01) [1] |
| 텅스텐 | 제공된 문서에서 근거를 찾지 못했습니다. |

니켈의 가격은 2026-09-30부터 2026-10-01까지의 실제 조회기간 동안 LME CASH 기준 통상가격이 22,916.73에서 23,111.69로 변동하였습니다 [1]

가격 기준은 LME CASH이며, 통화는 USD이며, 중량 단위는 톤입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 광물자원가격 > 비철금속

광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.

### ADD01 — FAIL

질문: 리튬 최신 가격 얼마야?

요청 범위가 넓습니다. 기간·정보 유형(가격/수입·수출/생산·매장/지표)을 지정해 주십시오.

### ADD03 — FAIL

질문: 아연 가격 2010년 이후 최고가와 그 날짜 알려줘

요청 범위가 넓습니다. 기간·정보 유형(가격/수입·수출/생산·매장/지표)을 지정해 주십시오.

### ADD06 — PARTIAL

질문: 니켈 가격 전년 동월 대비 변화율은?

2026-10 기준 니켈 가격은 23,111.69 USD/톤이며, 전년 동월(2025-10) 14,307.41 USD/톤 대비 +61.54% 변동했습니다. 비교 기준: 일별 가격의 월평균.

### ADD12 — PASS

질문: 방금 답변 원본 데이터는 KOMIS 어디서 확인해?

추천 페이지는 `KOMIS > 알림마당 > FAQ`입니다.
제공 정보: 광종·가격·국가정보와 Open API 등 KOMIS 이용 관련 공개 질문·답변을 조회하는 FAQ
확인 가능한 데이터: 질문, 답변
별도 언급이 없어 적용한 기준: 검색 대상 `질문` · 페이지 크기 `15개`
사용 방법 및 제약:
이동 방법: 페이지 주소 열기
- 화면 구성: 9개 FAQ 질문을 아코디언으로 제공하며 각 항목을 펼쳐 답변을 읽는다.
- FAQ 질문·답변: 질문을 선택해 해당 답변을 펼쳐 읽는다.
- 확인할 점:
  - 질문과 답변은 비로그인 조회가 가능하며 화면에서 9건을 아코디언으로 제공한다.
  - 화면에는 기간 필터가 없고 질문 또는 답변을 선택해 검색한다.
  - 조사 시점 FAQ는 제3자 제공 가격 데이터의 Open API 제공과 사전 동의 없는 사이트 구축용 재사용이 어렵다고 안내한다.
  - 화면 필터는 search_field→srchField(질문=ttl, 답변=cnts), query→srchValue, page_size→listCount로 전달된다.
  - 목록 조회는 boardType=F, boardCd=FAQ, regDate 내림차순을 사용하며 답변은 목록 응답에 포함된다.
- 실제 수치나 게시물 내용은 원 화면에서 확인해야 합니다.
페이지 주소: https://www.komis.or.kr/Komis/Board/FAQ
바로 이동하시겠어요? 위 페이지 주소를 눌러 이동하실 수 있습니다.

### ADD15 — FAIL

질문: 희토류 생산량과 매장량 상위 5개국을 각각 차트로 보여줘

all_roots_failed

### ADD16 — PARTIAL

질문: 세계 리튬 매장량 중 칠레 비중은?

칠레의 production 값은 2,256.00톤입니다.

### ADD18 — PASS

질문: 광물종합지수 최근 12개월 추이 보여줘

광물종합지수의 최근 12개월 추이에 대한 정보입니다. 제공된 근거의 실제 조회기간은 2025-10-02부터 2026-09-05까지입니다 [1].

| 기준일자 | 지수 |
| --- | --- |
| 2026-09-05 | 3651.45 |
| 2026-08-05 | 3398.6 |
| 2026-07-01 | 3383.72 |
| 2026-06-01 | 3586.97 |
| 2026-05-01 | 3471.33 |
| 2026-04-01 | 3383.4 |
| 2026-03-03 | 3252.76 |
| 2026-02-02 | 3216.64 |
| 2026-01-02 | 2929.01 |
| 2025-12-01 | 2789.42 |
| 2025-11-03 | 2801.23 |
| 2025-10-02 | 2663.84 |

광물종합지수는 해당 조회기간 동안 전반적인 상승 추세를 보였습니다 [1]. 2025년 10월 2일 기준 2,663.84였던 지수는 2026년 9월 5일 기준 3,651.45로 기록되었습니다 [1].

출처:
- [1] KOMIS 공식 데이터 · KOMIS 광물전망지표 > 광물종합지수 (기준시점 2025-10-02\~2026-09-05, 지정 기간 내 관측 241건 전체)

### ADD25 — PARTIAL

질문: 구리, 니켈, 코발트 최근 1년 가격 추이 비교해줘

### 니켈 가격 추이
니켈의 최근 1년 가격 추이는 제공된 근거의 실제 조회기간인 2025-10-02부터 2026-10-01까지의 데이터를 기준으로 합니다 [1] .

| 광종 | 조회 기간 | 가격 기준 | 단위 |
| :--- | :--- | :--- | :--- |
| 니켈 | 2025-10-02 \~ 2026-10-01 | LME CASH | (근거에 명시되지 않음) |

니켈의 통상가격(cmerc_prc)은 2025-10-02 기준 14,271.22에서 2026-10-01 기준 23,111.69로 변동하였습니다 [1]

가격 기준은 LME CASH이며, 통화는 USD이며, 중량 단위는 톤입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 광물자원가격 > 비철금속

광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.
광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.

### ADD27 — PASS

질문: 니켈 가격 추이 좀 보여줘

2026-10-01 기준 니켈 가격은 23,111.69 USD/톤입니다. 전일 대비 +194.96(+0.85%) 변동했습니다.

### ADD32 — PASS

질문: 중국 희토류 수출통제 관련 최신 내용 요약하고 출처 달아줘

중국 희토류 수출통제와 관련된 최신 내용은 다음과 같습니다. 해당 내용은 2026-07-21부터 2026-08-24까지의 자료를 바탕으로 작성되었습니다. [1]

* **대미 수출 현황**: 2026년 7월 기준 중국의 대미 산화이트륨 수출량은 29톤을 기록하였으며, 이는 2025년 4월 희토류 수출통제 시행 이후 두 번째로 높은 수준입니다. [1] 또한, 동월 대미 희토류 영구자석 수출량도 647톤으로 수출통제 이후 두 번째로 높은 수준을 기록하였습니다. [1]
* **대일 수출 제한**: 중국이 희토류 수출통제를 대외 정치외교적 수단으로 활용하는 가운데, 일본에 대한 희토류 및 전략광물 수출 제한은 지속되고 있습니다. [1] 7월 기준 산화디스프로슘과 산화터븀의 대일 수출은 각각 9개월, 8개월 연속 중단되었습니다. [1]
* **글로벌 공급망 대응**: 중국의 희토류 수출 규제로 인해 중국 외 안정적인 공급망을 확보하려는 수요가 확대되고 있습니다. [1] 이에 따라 호주의 Lynas Rare Earths는 2026 회계연도 4분기(4\~6월) 매출이 전년 동기 대비 69.7% 증가한 A$2.89억을 기록하였으며, 분기 평균 판매가격은 전년 동기 A$60.2/kg에서 A$98.2/kg으로 63.1% 상승하였습니다. [1] 스웨덴 정부는 중국의 수출통제에 대응하여 핵심광물 개발을 '국가안보 사안'으로 지정하고 신규 광업 전략을 추진하고 있습니다. [1]

출처:
- [1] KOMIS 공식 데이터 · 일일 자원뉴스 (기준시점 2026-07-21\~2026-08-24)

### ADD38 — PASS

질문: 7개 광종의 최신 가격, 기준일, 단위, 출처를 한 표로 정리해줘

| 광종 | 최신 가격 | 기준일 | 단위 | 출처 |
| :--- | :--- | :--- | :--- | :--- |
| 니켈 | 23,111.69 | 2026-10-01 | LME CASH | public.KO_MNRL_PRC [1] |

니켈의 경우, 실제 조회기간은 2026-09-30부터 2026-10-01까지입니다 [1]

가격 기준은 LME CASH이며, 통화는 USD이며, 중량 단위는 톤입니다. [1]

출처:
- [1] KOMIS 공식 데이터 · KOMIS 광물자원가격 > 비철금속

광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.
광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.
광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.
광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.
광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.
광물가격: 확인 가능한 자료가 없어 답변할 수 없습니다.

### ADD40 — PASS

질문: 우드맥킨지 보고서 기준 리튬 전망 알려줘

우드맥킨지(Wood Mackenzie) 보고서에 따른 리튬 전망은 다음과 같습니다.

**1. 수요 전망**
* **글로벌 리튬 수요:** 2035년까지 연평균 9.4% 수준으로 증가할 것으로 예상되며, 이후 2050년까지 연평균 3.3% 증가하여 수요량은 5,755천톤(LCE)에 도달할 것으로 전망됩니다. [1]
* **배터리 분야 수요:** 글로벌 전기차 및 ESS 시장의 성장과 이차전지의 지속적인 수요 증가로 인해 배터리 분야 리튬은 연평균 6.0% 증가할 것으로 전망됩니다. [1]
* **배터리 산업 비중:** 2025년 수요량 중 배터리 산업의 비율은 89.5%(1,296천톤 LCE)이며, 매년 지속적으로 증가하여 2050년에는 95.7%(5,508천톤 LCE)까지 도달할 것으로 전망됩니다. [1]
* **리튬이온배터리 수요:** 2020년 371GWh 규모에서 2032년 3.7TWh 규모로 연평균 21% 성장할 것으로 전망되며, 이 중 전기차 수요가 대다수를 차지할 것으로 예상됩니다. [2]
* **리튬 수요 및 배터리 비중(2022년 기준 전망):** 2022년 리튬 수요는 694천톤(LCE)으로 배터리 수요가 80%를 차지할 것으로 전망되었으며, 2032년 리튬 수요는 2,224천톤(LCE), 배터리 수요 비율은 92%로 증가할 것으로 전망되었습니다. [2]

**2. 가격 전망**
* **가격 변동 추이:** 2027년 공급 과잉 현상이 극대화되어 최저가(탄산리튬 톤당 71,800달러, 수산화리튬 77,500달러대)에 도달한 후, 2037년 배터리용/공업용 리튬 원료 전량이 공급 부족 상태로 전환될 때까지 가격 급등은 제한될 것으로 전망됩니다. [3]
* **수산화리튬 전망:** 중국의 LFP/LFMP 배터리 수요 증가로 인해 하이니켈 삼원계(NCM 등) 배터리에 사용되는 수산화리튬은 탄산리튬 대비 상대적으로 수요가 낮아 단기적으로 가격 변동폭이 더 큰 폭으로 급락할 것으로 예상됩니다. [3]
* **장기적 프리미엄 전망:** 2028년 이후 하이니켈 삼원계 배터리 수요가 급증하고, 2030년대에 수요의 중심이 중국에서 유럽과 북미로 이동하면서 NCM 기반 양극재 채택이 증가함에 따라 수산화리튬이 다시 프리미엄 제품으로 자리 잡을 것으로 전망됩니다. [3]

출처:
- [1] 공식 문서 원문 · 2 수요 (기준시점 시장동향보고서)
- [2] 공식 문서 원문 · ❚ 리튬시장 주요 전망(Woodmackenzie,  ’22.9) (기준시점 2022-20-22)
- [3] 공식 문서 원문 · Vol26_2024-12_리튬 (기준시점 시장동향보고서)

### ADD45 — PASS

질문: 리튬 가격 화면으로 가줘

추천 페이지는 `KOMIS > 광물자원가격 > 희소금속`입니다.
제공 정보: 리튬·코발트·희토류 등 희소금속의 품목·규격별 가격을 조회하는 페이지
확인 가능한 데이터: 기준일, 기준가격 또는 상업가격, 최저가, 최고가, 전일·전주·전월·전년 평균 대비 등락가와 등락률, 가격 시계열, 가격기준·규격·단위
조회 조건: 광종 `리튬`
별도 언급이 없어 적용한 기준: 품목·가격기준 `선택 광종의 화면 기본 품목` · 규격 `선택 품목의 화면 기본 규격` · 평균 단위 `일간` · 기간 입력 방식 `연도별` · 조회 기간 `화면 기본 기간`
사용 방법 및 제약:
이동 방법: 페이지 주소 열기
- 화면 구성: 선택한 품목·규격의 가격 선 그래프, 최신 비교표와 상세 원자료 표를 제공한다.
- 가격 추이: 품목·규격이 고정된 가격의 방향과 변곡점을 본다.
- 최신 가격 비교: 최근값을 전일·전주·전월·전년 평균과 비교한다.
- 상세 원자료: 기준일별 정확한 가격과 등락을 확인한다.
- 확인할 점:
  - 광종만 같아도 품목·규격이 다르면 같은 가격 시계열로 취급하지 않는다.
  - API에만 있고 화면에서 숨긴 내부 지표 전용 가격코드는 추천하지 않는다.
- 실제 수치나 게시물 내용은 원 화면에서 확인해야 합니다.
페이지 주소: https://www.komis.or.kr/Komis/RsrcPrice/MinorMetals
바로 이동하시겠어요? 위 페이지 주소를 눌러 이동하실 수 있습니다.

### ADD46 — PASS

질문: 수급지도 대한민국 페이지 어디서 봐?

추천 페이지는 `KOMIS > 핵심광물지도 > 대한민국 수급지도`입니다.
제공 정보: 한국의 광종별 국가별 수입·수출 금액과 중량을 HS 10자리 기준으로 보여주는 페이지
확인 가능한 데이터: 국가, 조회시점, 수입·수출 금액, 수입·수출 중량, 금액 점유율, HS Code, 국가별 Top 5, 기간별 교역규모 추이
조회 조건: 국가 `대한민국`
별도 언급이 없어 적용한 기준: 광종 `광종 전체` · 생산품 유형 `생산품 유형 전체` · 물질흐름 세부 `세부 전체` · HS Code `HS Code 전체` · 수입·수출 기준 `수입` · 기간 단위 `연도별` · 조회 시점 `최신 확정 시점` · 정렬 관점 `금액별` · 금액 표시 단위 `천USD`
사용 방법 및 제약:
이동 방법: 페이지 주소 열기
- 화면 구성: 교역국에서 한국으로 향하는 지도, 기간별 추이 선, 국가별 Top 5 막대와 상세 표를 함께 제공한다.
- 대한민국 교역지도: 교역국과 한국 사이의 방향과 규모를 공간적으로 보여준다.
- 수출입 규모 추이: 기간에 따른 수입·수출 규모 변화를 보여준다.
- 국가별 Top 5: 상위 교역국의 규모와 점유율을 빠르게 비교한다.
- 국가별 상세: 금액·중량·점유율과 HS Code의 정확한 값을 확인한다.
- 화면 사용:
  - 광종 전체 또는 지원 광종을 선택할 수 있다.
  - HS Code 검색어로 후보를 찾은 뒤 실제 HS Code 항목을 선택한다.
- 확인할 점:
  - 생산품 유형·물질흐름 세부·HS Code는 상위 필터에 종속되며 국내 교역은 HS 10자리 기준이다.
  - 월 자료와 연 자료의 확정 시점이 다르므로 최신은 동적 메타데이터로 해석한다.
- 실제 수치나 게시물 내용은 원 화면에서 확인해야 합니다.
페이지 주소: https://www.komis.or.kr/Komis/MnrlMap/Korea
바로 이동하시겠어요? 위 페이지 주소를 눌러 이동하실 수 있습니다.

### ADD47 — PARTIAL

질문: 핵심광물이 뭐야? 왜 중요해?

핵심광물은 국가 첨단산업에 필수적인 원료광물 중 공급 리스크와 경제적 파급력이 있는 광물을 의미합니다. 핵심광물은 배터리·전기모터·전자제품 등 첨단산업과 에너지 전환에 필요하며, 채굴·정제·가공 능력이 특정 국가나 지역에 집중되면 공급 차질 위험이 커질 수 있습니다. 국가·기관별로 선정 기준과 목록은 다를 수 있습니다. (정의 출처: 『월간 통상』 2023년 4월호)

### ADD48 — PARTIAL

질문: 여기서 뭘 물어볼 수 있어?

광물 가격·가격 추이·전망, 생산량·매장량 순위, 한국 수입·수출과 국가별 비중·집중도, 재고·수급지표, 자원뉴스·월간동향·보고서 요약과 원문 확인을 물어볼 수 있습니다. 기간·광종·국가를 함께 적으면 더 정확하게 조회됩니다.

### ADD49 — FAIL

질문: 구리 가격 알려줘

요청 범위가 넓습니다. 기간·정보 유형(가격/수입·수출/생산·매장/지표)을 지정해 주십시오.

원본 SSE terminal·응답 전문: `user_qa_pair_audit_20261002_145520.json`
