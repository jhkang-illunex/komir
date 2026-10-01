# Live multihop 수정 감사 — 2026-10-01

범위: 직전 미커밋 live_multihop / retrieval verifier / renderer 변경.
위험도 HIGH. 운영 18002는 self-contained16 그대로 유지하고 18011에서 검증했다.
별도 ASTRA 모델 호출 결과는 아니다. iterative-audit에 따라 재현 테스트와
실제 Gemma/SSE를 사용했다.

## 재현 및 수정

- 거절된 document evidence가 non-empty라는 이유로 SUCCESS가 되는 bypass 제거.
  root 검증은 evidence 존재와 sufficient만 확인하므로 이전 bypass는 안전하지 않았다.
- asyncio.gather 항목 예외가 전체 ForEach를 중단하는 문제 수정. 취소는 전파하고
  일반 호출 예외는 failed 항목으로 남긴다. 일부 성공은 PARTIAL, 전체 실패는 FAILED.
- 부분 모집단 aggregate/rank/compare/calculation은 incomplete_population으로 보류.
- 빈 composite presentation을 abstained=false로 완료하는 오류 수정.
- EMPTY root의 원인을 generic evidence validation failed로 덮어쓰지 않음.
- 임의 history reference 및 self-reference를 최신 결과로 바꾸지 않음.
  history가 있을 때만 validation 노드를 삭제하던 코드를 제거.
- 본문 alias 부분 문자열로 광종을 추측하던 ForEach fallback 제거.
  '동향'의 '동'은 구리 목록 근거가 아니다. 명시적인 광종 컬럼만 추출한다.
- 기존 document_facts 문서군 판별을 retrieval routing에서도 재사용.
  '희소금속 보고서'와 '희소금속 월간 보고서'의 source 선택 불일치 수정.
- project(field=minerals) 및 fields=[minerals]를 명시적인 MineralSet으로 변환.
  쉼표 광종 목록을 개별 항목으로 전달하고 evidence/provenance 보존.
- 가격기준 번호를 가격으로 표시하는 느슨한 컬럼 선택 제거.
  날짜가 있는 시계열은 미래 행을 제외하고 최신 관측행을 선택.
- 광종별 단위·출처를 보존하고 기존 단위 코드 변환을 재사용.
- history materialization의 RequirementNode 누락 import 수정.

GroundingCheck.reason=null 허용은 유지했다. sufficient와 evidence index 검증은
그대로이며 설명 null 때문에 rejection을 success로 바꾸지 않는 회귀를 추가했다.

## 검사

새 안전성 회귀: 최초 4개 모두 수정 전 FAIL → 수정 후 PASS.
확장 후 신규 13개 PASS. 전체 rag_core 695 PASS / 143 subtests PASS.
compileall 및 git diff --check 통과. 기존 테스트 삭제/skip 없음.

audit18에서 안전성 수정 후 일반 보고서 질의는 실제로
upstream MineralSet is empty가 됐다. 이 실패를 숨기지 않고 source routing과
projection을 고친 후 audit21에서 fresh/동일 세션 재질문/월간 표현 3회 응답을 확인했다.

최종 검증 이미지: komir-rag-chat:audit-safety22
SHA256: 31b7ed55fded35d8e4a7f172e5882fc394c05bded47075417e85894bc468e9e9
검증 포트: 18011. SSE 원본: /tmp/komir-audit22-{fresh,existing,monthly}.sse.

최종 이미지 실제 세션 `4e19e5d6-a362-44e5-afe3-83bf2f375cd7`:

| 실행 | 시간(초) | root 상태 | SSE 결과 |
|---|---:|---|---|
| fresh | 7.02 | partial | 리튬·희토류 가격, 개별 표, 단위, citation, 일부 실패 안내 |
| 같은 세션 동일 질문 | 8.22 | partial | 동일 가격·관측일·표 |
| 같은 세션 월간 보고서 표현 | 8.14 | partial | 동일 가격·관측일·표 |

개발 DB 반환: 리튬 13335.89 USD/톤, 희토류 15541.34 USD/톤,
관측일 20260930. 세 실행 모두 doc/project success → ForEach partial.
모든 광종 성공으로 판정하지 않았다. 독립 SQL 기반 시장가격 정확성 검증은 이번 범위 밖이다.

## 해석 범위와 남은 사항

- 개발 설정 RAG_ALLOW_DUMMY=1을 복제했다. 반환값의 공식 실측 진위를 검증한 것은 아니다.
- static invalid mineral은 기권하지만 unsupported_commodity 분류 보완은 남아 있다.
- 같은 질문 재요청과 genuine follow-up은 다르다. 이번 live 세션 비교를 모든 후속
  질문/서버 재시작 복원 성공으로 일반화하지 않는다.
- 전체 문서 선택 정확성, 원문 checksum 및 fact freshness 검증까지 완료한 것은 아니다.
- 일반 Composite를 가격 전용 presentation이 처리하는 범위에는 여전히 제약이 있다.
  비가격 composite를 blank success로 반환하지 않도록 닫았지만 범용 rendering 완료는 아니다.
- 소스 변경을 운영 반영으로 간주하지 않는다. 운영 18002는 이번 라운드에 교체하지 않았다.
