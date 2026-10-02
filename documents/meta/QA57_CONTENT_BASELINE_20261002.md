# QA57 Content Baseline 및 Fast Regression 목록

작성 기준: 2026-10-02. 이 문서는 `/tmp/capability-r3-57/user_qa_pair_audit_20261002_164100.json`의 57개 QA 원문·실행 관찰값을 보존한 메타 artifact입니다. `CONTENT_PASS`는 공식 oracle 기준 집합(27/57)을 별도로 표시하며, 실행 `PASS`와 동일한 의미가 아닙니다. 이번 fast regression은 전체 57건을 재실행하지 않았습니다.

## 공식 기준

- `CONTENT_PASS`: 27/57 (47.37%)
- Fast target: MP01, ADD27
- Fast sentinel: ADD45, REG02, GM04, CN09, DOC02, MI01, MP06
- 운영 18002: 변경 없음
- 검증 이미지: `komir-rag-chat:aast-content-r6`

## QA 목록

| # | QA ID | 질문 | 원본 실행 상태 | 공식 content baseline |
|---:|---|---|---|---|
| 1 | MI01 | 니켈은 어디에 쓰여? | PASS | CONTENT_PASS |
| 2 | MI02 | 니켈은 어떤 금속이야? | PARTIAL | NOT_CONTENT_PASS |
| 3 | MI03 | 구리 기본 특성을 알려줘 | PASS | CONTENT_PASS |
| 4 | MI04 | 망간 주요 광석 종류는? | PASS | CONTENT_PASS |
| 5 | DOC02 | 최근 월간동향 제목 알려줘 | PASS | NOT_CONTENT_PASS |
| 6 | DOC04 | 월간 동향 게시판 검색은 어떻게 해? | PARTIAL | NOT_CONTENT_PASS |
| 7 | NEWS01 | 최근 자원 뉴스 뭐 있어? | PASS | CONTENT_PASS |
| 8 | NEWS03 | 최근 중국 수출통제 관련 뉴스 있어? | PASS | NOT_CONTENT_PASS |
| 9 | PF01 | 니켈 현재 가격이랑 다음달 전망 같이 알려줘 | PARTIAL | NOT_CONTENT_PASS |
| 10 | PF02 | 니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘 | PARTIAL | NOT_CONTENT_PASS |
| 11 | PF03 | 니켈 지금 가격이 전망치 보다 높은 편이야? | FAIL | NOT_CONTENT_PASS |
| 12 | IX01 | 광물지수 오를때 같이 오른 광종은 뭐야? | FAIL | NOT_CONTENT_PASS |
| 13 | IX02 | 니켈 가격 추세랑 광물 종합지수 추세 비교해주세요 | FAIL | NOT_CONTENT_PASS |
| 14 | MP01 | 니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘 | PARTIAL | CONTENT_PASS |
| 15 | MP03 | 니켈 수입 상위국이랑 현재가격 알려줘 | PARTIAL | NOT_CONTENT_PASS |
| 16 | MP04 | 니켈 가격이랑 세계 생산량 변화 같이 보여줘 | FAIL | NOT_CONTENT_PASS |
| 17 | MP05 | 생산 1위국 비중이 높은 광종들 가격 변동 어때? | BLOCKED_DATA | NOT_CONTENT_PASS |
| 18 | MP06 | 니켈은 어디에 쓰이고 지금 가격은 얼마야? | PARTIAL | CONTENT_PASS |
| 19 | MP07 | 전략광종 가격 현황 한눈에 보여줘 | PASS | CONTENT_PASS |
| 20 | MP09 | 니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘 | PARTIAL | CONTENT_PASS |
| 21 | CN01 | 니켈 가격 크게 오른 날 관련 뉴스 있어? | PASS | CONTENT_PASS |
| 22 | CN04 | 수입 의존도 높은 광종들 가격 전망 알려줘 | PARTIAL | NOT_CONTENT_PASS |
| 23 | CN05 | 리튬 주요 수입국이랑 가격 전망 같이 보여줘 | FAIL | NOT_CONTENT_PASS |
| 24 | CN07 | 리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘 | PARTIAL | NOT_CONTENT_PASS |
| 25 | CN08 | 지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘 | FAIL | NOT_CONTENT_PASS |
| 26 | CN09 | 광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어? | PARTIAL | CONTENT_PASS |
| 27 | GM01 | 코발트 세계 생산국이랑 우리나라 수입국 비교해줘 | FAIL | NOT_CONTENT_PASS |
| 28 | GM02 | 리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는? | FAIL | NOT_CONTENT_PASS |
| 29 | GM04 | 2차전지 광물 수입국 구성 알려줘 | PASS | CONTENT_PASS |
| 30 | GM05 | 망간 용도랑 주요 수입국 알려줘 | FAIL | NOT_CONTENT_PASS |
| 31 | GM08 | 텅스텐 용도랑 세계 생산국 알려줘 | PARTIAL | NOT_CONTENT_PASS |
| 32 | GM11 | 흑연 공급 현황 종합해서 알려줘 | FAIL | NOT_CONTENT_PASS |
| 33 | GM12 | 2차전지 광물 5종 가격이랑 전망 한 번에 보여줘 | FAIL | NOT_CONTENT_PASS |
| 34 | GM13 | 코발트 현황 브리핑해줘 | FAIL | NOT_CONTENT_PASS |
| 35 | GM14 | 중국 수출통제 대상 광종 가격이랑 수입 비중 같이 보여줘 | PASS | CONTENT_PASS |
| 36 | REG02 | 오늘 니켈 가격 얼마야? | PASS | CONTENT_PASS |
| 37 | REG03 | 최근 니켈 가격 얼마야? | PASS | CONTENT_PASS |
| 38 | REG04 | 니켈 가격 년도별 평균 가격을 알려줘 | PASS | CONTENT_PASS |
| 39 | REG05 | 니켈 LME 재고량 알려줘 | PASS | CONTENT_PASS |
| 40 | REG06 | 니켈 텅스텐 가격 같이 비교해줘 | PASS | NOT_CONTENT_PASS |
| 41 | ADD01 | 리튬 최신 가격 얼마야? | FAIL | NOT_CONTENT_PASS |
| 42 | ADD03 | 아연 가격 2010년 이후 최고가와 그 날짜 알려줘 | FAIL | NOT_CONTENT_PASS |
| 43 | ADD06 | 니켈 가격 전년 동월 대비 변화율은? | PARTIAL | CONTENT_PASS |
| 44 | ADD12 | 방금 답변 원본 데이터는 KOMIS 어디서 확인해? | PASS | CONTENT_PASS |
| 45 | ADD15 | 희토류 생산량과 매장량 상위 5개국을 각각 차트로 보여줘 | FAIL | NOT_CONTENT_PASS |
| 46 | ADD16 | 세계 리튬 매장량 중 칠레 비중은? | PARTIAL | CONTENT_PASS |
| 47 | ADD18 | 광물종합지수 최근 12개월 추이 보여줘 | PASS | CONTENT_PASS |
| 48 | ADD25 | 구리, 니켈, 코발트 최근 1년 가격 추이 비교해줘 | PARTIAL | CONTENT_PASS |
| 49 | ADD27 | 니켈 가격 추이 좀 보여줘 | PASS | NOT_CONTENT_PASS |
| 50 | ADD32 | 중국 희토류 수출통제 관련 최신 내용 요약하고 출처 달아줘 | PASS | CONTENT_PASS |
| 51 | ADD38 | 7개 광종의 최신 가격, 기준일, 단위, 출처를 한 표로 정리해줘 | PASS | CONTENT_PASS |
| 52 | ADD40 | 우드맥킨지 보고서 기준 리튬 전망 알려줘 | PASS | CONTENT_PASS |
| 53 | ADD45 | 리튬 가격 화면으로 가줘 | PASS | NOT_CONTENT_PASS |
| 54 | ADD46 | 수급지도 대한민국 페이지 어디서 봐? | PASS | CONTENT_PASS |
| 55 | ADD47 | 핵심광물이 뭐야? 왜 중요해? | PARTIAL | CONTENT_PASS |
| 56 | ADD48 | 여기서 뭘 물어볼 수 있어? | PARTIAL | CONTENT_PASS |
| 57 | ADD49 | 구리 가격 알려줘 | FAIL | NOT_CONTENT_PASS |

## 판정 주의

- `원본 실행 상태`는 기존 QA pair audit의 실행 관찰값(`PASS/PARTIAL/FAIL/BLOCKED`)입니다.
- `공식 content baseline`은 oracle 비교 결과이며, 표의 원본 실행 상태로 재계산하지 않습니다.
- 본 artifact는 production runtime이 참조하지 않는 QA/evaluation 기록입니다.

