# 106개 QA 원천 근거·서버 응답 비교

## 대상

- 질문 원본: 챗봇_전체_QA_106건_결과_20260930.docx
- 비교 대상:
  - 18002: komir-rag-chat:audit-safety22
  - 18012: komir-rag-chat:qa-reference-boundary34-r6
- 현재 서버 호출: 2026-10-02, 질문별 신규 session_id
- 원천 기준 스냅샷: 2026-09-30 14:00:07 KST의 실제 DB/PageIndex/OKF source-backed 감사 결과

## 원천 기준 산출 방법

기존 106건 감사 결과의 실제 Action, source, 응답 근거를 원천 기준 스냅샷으로
연결했다. 정형 원천은 가격·무역·생산·재고·지수 Action과 KOMIS DB source,
비정형 원천은 document/PageIndex/OKF/Royal Society 등으로 구분했다.

원천 기준은 production 코드나 질문별 정답 분기가 아니다. 가격·뉴스·전망은
기준일과 문서 발행시점이 달라질 수 있으므로 숫자나 문장 완전 일치만으로 PASS를
판정하지 않고, CSV에 oracle timestamp·source·Action·응답 원문을 함께 보존했다.

## 집계

- 전체 질문: 106
- source-backed oracle 연결: 57
- 원천 스냅샷에서 기권/외부 의존: 49
- 18002: DONE 29 / ABSTAIN 77
- 18012: DONE 30 / ABSTAIN 76
- 두 서버 상태 차이: 33
- 양쪽 응답 텍스트 완전 동일: 7

서버별 원천 비교는 다음 의미다.

- CONSISTENT_BLOCKED: 원천 기준도 기권이고 서버도 기권
- ORACLE_MISS: 원천 답변이 있었으나 서버가 기권
- NUMERIC_SUPPORT_REVIEW: 원천 숫자 일부가 응답에 존재하나 기간·단위·계산식 확인 필요
- CONTENT_REVIEW: 응답은 있으나 자동 비교만으로 의미 일치 확정 불가
- UNEXPECTED_SUCCESS_REVIEW: 원천 기준은 기권인데 서버가 성공; 새 데이터 또는 과잉 응답 여부 확인 필요

자동 비교는 사실성 PASS를 선언하기 위한 것이 아니라, 사람이 재검토할 우선순위를
정하는 보조 판정이다. 특히 NUMERIC_SUPPORT_REVIEW와 CONTENT_REVIEW는 PASS가 아니다.

## 파일

- 원천 근거와 양쪽 응답 CSV: qa106_grounded_comparison_20261002.csv
- 원천 근거와 양쪽 응답 Excel: qa106_grounded_comparison_20261002.xlsx
- 양쪽 서버 원시 비교 CSV: qa106_server_comparison_20261002.csv
- 양쪽 서버 원시 실행 JSONL: qa106_server_comparison_20261002.jsonl

각 QA 행에는 질문, 원천 기준 답변, source/Action, 기준시각, 두 서버의 SSE 본문·표·차트·
기권 사유·응답시간·세션 ID·oracle 비교 판정이 들어 있다.

## 주의할 항목

원천 스냅샷에서 기권한 49건을 모두 실제 데이터 없음으로 확정하지 않았다.
당시 PageIndex/OKF fixture, 외부 전망 데이터, 최신 뉴스, capability 또는 원천 계약이
부족했던 경우가 섞여 있으므로 BLOCKED_ORACLE로만 기록했다.

또한 이 라운드에서는 운영 DB를 쓰지 않았고, 두 서버는 읽기 전용 질의만 수행했다.
