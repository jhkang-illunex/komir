# 피드백 Q&A iterative audit 결과 (2026-09-27)

## 1. 분류

### 현 데이터·기능 계약상 실패가 정상인 문항

- FBQ02, FBQ07, FBQ08, FBQ13, FBQ14, FBQ17, FBQ19, FBQ20
- FBQ27, FBQ28, FBQ29, FBQ31, FBQ41, FBQ42
- FBQ47~FBQ49, FBQ51, FBQ61~FBQ67
- 멀티홉 `price_anaphora` 2턴

주요 근거는 다음과 같다.

- 가격예측 테이블에는 735행이 있으나 공개 provenance와 실행 adapter가 연결되지 않아
  `forecast.*`는 의도적으로 `source_unavailable`이다.
- 광물종합지수에는 12,105행(2011-01-04~2026-09-05)이 있으나 현재 원천의 실제 표본
  여부를 자동 검증하지 못해 fail-closed다.
- 일부 가격·순위·무역·생산 원천은 `DEV_DUMMY`다. 현재 정책은 단건 결과에는 경고를
  붙여 반환하되, 가격 비교처럼 공식 실측을 전제로 하는 계산은 차단하는 것이다.
- `price_anaphora` 후속 실패는 문맥 소실이 아니라 리튬 더미 가격 비교 차단이다.

### 코드 결함으로 확인해 이번에 수정한 문항·경계

- FBQ12: 엑셀 다운로드 FAQ가 페이지 추천으로 빠지던 경로
- FBQ18, FBQ36: FAQ 미치환 템플릿과 정의 응답 경로
- FBQ25: 세계 수출 순위를 한국 수급지도 원천으로 대체하던 범위 오류
- FBQ37, FBQ43: 월간동향·뉴스 단일 질의 라우팅과 게시일 최신성
- FBQ40: 검색 방법 FAQ가 페이지 안내로 처리되던 경로
- FBQ60: 복합 전망 질문을 단순 정의 FAQ가 선점하던 경로
- 라이브 게이트 Q26: 미래 실측 가격의 LLM 분류가 매 실행 달라지던 문제
- 무역 순위 후속: `최근 2년으로 바꿔줘` 같은 생략형 후속에서 세계 범위를 한국으로
  덮어쓰던 문제

### 추가 계약·원천 결정이 필요해 보류한 항목

- 멀티홉 `multi_action` 2턴: 기간·대상·지표를 typed state로 보존하는 별도 계약 작업이
  필요하다.
- FBQ38, FBQ39, FBQ44~FBQ46: 라우팅 수정 후 현재 문서 보유기간·LLM 계획을 다시
  측정해야 하며, 응답 부재만으로 코드 결함으로 확정하지 않는다.

## 2. 변경 원칙

- 가격예측·광물종합지수의 provenance gate를 완화하지 않았다.
- `DEV_DUMMY` 경고 후 반환 정책을 유지했다.
- 문서 shortcut은 질문 전체가 승인된 단일 문형과 일치할 때만 적용한다.
- 세계/한국 무역 모집단은 typed `trade_scope`로 분리하고, 범위 생략 후속은 직전
  typed scope를 보존한다.
- FAQ 정의 근거가 없으면 placeholder나 추정 목록 대신 근거 부재를 명시한다.

## 4. FBQ22 후속 구현 (2026-09-27)

FBQ22는 보류를 해제했다. `country_dependency`에만 최근 N기간과 ISO 일자 range를
허용하고, `denominator_scope=reporter_product_trade`를 Action→MCP→repository까지
전달한다. 분자와 분모는 같은 HS·수출입 방향·기간 SQL 조건에서 함께 집계한다.
range의 날짜는 실제 YYYY-MM-DD/YYYYMMDD만 허용한다.

단일국 비중 질문만 한국/최근 12개월 기본값으로 닫고, 국가별·복수국·순위·복합
질의는 planner로 보낸다. 원천에서 상대국 이름/코드가 매칭되지 않으면 0% 대신
source error를 반환한다. 2025 연간 계획의 새 분모 슬롯은 하위호환 기본값으로
채우며, TSI 등 비의존도 지표의 최근 기간 후속은 지원되지 않는 기간으로 명확화한다.

- 회귀: action/adapter 경계 109건 통과, `py_compile`, `git diff --check` 통과
- Astra 최종 감사: HIGH/CRITICAL 없음
- 배포: `komir-rag-chat:20260927-trade-indicator-r4`, `komir-rag-chat-test:18002`
- 라이브 FBQ22: HTTP 200, done 정확히 1회, `trade.indicator` 인용, 6.0%; 관측기간
  2026-06-01~2026-09-09와 DEV_DUMMY 경고를 함께 표시

## 5. FBQ55 후속 구현 (2026-09-27)

사용자가 제공한 `strategic_price_groups.yaml`에서 6대·10대 전략광종과 원천 가격광종
별칭을 읽어 `price.overview` 전용으로 실행한다. 이 YAML은 집계 대상 구성이며, 가격의
공식 기준이나 원천 품질을 보증하는 정의로 사용하지 않는다. 활성 가격 기준만 조회하고
행마다 실제 관측일·가격기준·통화·중량단위·KOMIS 메뉴·원천 상태를 유지한다.

가격 기준/관측값이 없는 유연탄·우라늄·철광석은 빈 가격의 상태행으로 남긴다. 더미
판정 불가 행은 값 없이 `provenance_unverified`로 처리하고, 전부 미확인이면
`source_unavailable`로 닫는다. 6대와 10대에 공통인 니켈은 그룹 키를 포함한 join으로
각 그룹에서만 나타나며, 서로 다른 기준·통화·단위를 비교·평균·순위·차트로 만들지
않는다.

- 회귀: 관련 경계·계약 검사 75건, `py_compile`, `git diff --check` 통과
- Astra 최종 감사: HIGH/CRITICAL 없음
- 배포: `komir-rag-chat:20260927-strategic-overview-r6`, `komir-rag-chat-test:18002`
- 라이브 FBQ55: HTTP 200, done 정확히 1회, `price.overview` 인용, 25개 표 행,
  더미·미매핑 경고, LME CASH 관측 행, 차트와 chart_hint 없음

## 3. 검증·배포

- 최종 단위 회귀: `test_action_contract_audit` 48건 통과
- 정적 검사: `git diff --check` 통과
- 후보 전체 라이브 수락검사: 통과
- 후보 피드백 선택 10문항: HTTP 200, done 정확히 1회
- 배포 후 전체 라이브 수락검사: 통과
- 배포 이미지: `komir-rag-chat:20260927-feedback-audit-r1`
- 이미지 ID: `sha256:a5ec2c12ea40b476f933290e8073ab84917a87f0d584f8f00034b21c05558086`
- 현재 컨테이너: `komir-rag-chat-test`, 포트 18002
- 롤백 컨테이너: `komir-rag-chat-test-pre-feedback-20260927`

DB와 문서 색인은 변경하지 않았다.
