# Live contract 재현·수정 검증 (2026-10-01)

## 범위와 배포 상태

- 기준 소스: `1d343bdbc6d3ffe0085b38adeb4f2b97d1850678`.
- iterative-audit HIGH: 결과·근거·기간·binding·부분 실패·SSE 완료 순서.
- 질문/QA ID별 분기, 신규 Intent/Action, 업무 DB 행 변경 없음.
- 운영 `18002`는 `audit-safety22` 그대로 유지. 재시작하지 않았다.
- 검증 포트 `18011`만 재사용. 최종 컨테이너 `komir-rag-chat-audit26`.
- 검증 이미지 `komir-rag-chat:audit-contract26`, SHA256
  `d87099c6d867ab071aec91098e458b7828eb0ecc7937b5ec1d014bdcaec20177`.
- 시작 시각 `2026-10-01T13:32:24.631161418Z`. 핵심 변경 소스 6개와 이미지 내 SHA256 일치.
- 수정 소스는 아직 커밋/운영 반영하지 않았다. 검증 컨테이너는 새 프로세스로 캐시를 초기화했다.

## 재현 결과와 공통 수정

| 항목 | 수정 전 재현 | 수정 및 검증 범위 |
|---|---|---|
| 명시 가격기준/국가 슬롯 | `price_criterion_serial=502`가 None, reporter/partner 유실 | 등록된 ActionSlots 필드를 검증하며 보존 |
| 복수 광종 월별 무역 | nickel,lithium 입력이 nickel,nickel 호출 | 각 mineral binding, 호출 실패 격리와 PARTIAL 보존 |
| NULL 동등 필터 | None > None을 평가하여 TypeError | 비교 연산을 선택적으로 실행 |
| PARTIAL projection | project 뒤 SUCCESS로 변해 불완전 합계 허용 | replace로 상태·기간·단위·경고 보존, 후속 합계 기권 |
| aggregate | 10+20 합계가 원천 두 행 그대로 SUCCESS | 명시 sum/mean/average/count/min/max 실행; 불완전 입력·단위 충돌 거절 |
| compare/join/미지원 계산 | 단순 연결/원천 반환을 성공 처리 | 명시 unsupported contract로 기권. 기능 구현 완료로 집계하지 않음 |
| history 복원 | TimeSeries가 문자열화된 MineralSet으로 변하고 evidence 소실 | 현재 세션의 저장된 TypedResult 자체 사용. 미확인 ctx 참조 거절 |
| 복수 root | 한 root 실패에도 전체 SUCCESS, 빈 일반 문구와 done | 성공/부분/전체실패 상태 구분, root별 본문·표·출처와 단일 done |
| 시계열 표현 | Composite에서 항상 최신 한 행만 표시 | 명시 time_series 출력은 전체 관측행 유지; latest_value와 분리 |
| 단순 경로 위임 | enabled에서 빈 ActionPlan 생성 → Pydantic 오류 | 위임된 기존 parser는 유효 계획 생성; enabled 라우터의 AST 우선 유지 |
| 완료 이벤트 | done 이후 메시지 저장, 저장 오류 때 legacy 재진입 | 메시지 저장 후 응답 방출, enabled 오류는 명시 종료 |
| PageIndex fact | 원문이 바뀌어도 기존 fact 사용 가능 | OKF 경로 경계·본문 SHA256 확인; 불완전 추출의 비일치를 전체 부재로 단정하지 않음 |
| 명시 page 모드 | enabled에서 계획 미생성 → mode_action_conflict | mode=page는 기존 navigation parser/검증 경로 유지 |
| 추가 live 발견 | `entity:nickel` 같은 ID가 LangGraph 예약문자 오류 | 런타임 내부 graph ID만 별도 사용, semantic/result ID는 유지 |
| 추가 live 발견 | metric=price에 domain이 없으면 document.retrieve | typed price metric을 price.series로 연결 |
| 추가 live 발견 | 유효 DocumentEvidence root가 unsupported presentation | 검증된 evidence text 표현 지원 |

가격기준 보존·NULL 비교·PARTIAL 전파·복수 광종 binding은 수정 전 테스트에서 4 FAIL을
확인했다. aggregate·다중 root·미지원 계산의 잘못된 성공도 실패 테스트로 확인했다.
LangGraph 예약문자는 실제 Gemma/SSE 실패 후 동일 runtime 테스트로 재현했다.

## 실제 Gemma/SSE 결과

HTTP 200이나 done만으로 semantic PASS로 집계하지 않았다.

| 이미지/질문 | 관찰 결과 | 판정 범위 |
|---|---|---|
| 23 / 니켈 용도+현재 가격 | 예약문자 예외, execution_failed, 표 0 | 실패 원본 보존 |
| 24 / 동일 복합 질문 | 두 Action 성공, 문서 표현은 unsupported_presentation_type | 렌더링 부분 실패를 추가 발견 |
| 24 / 기준 502 | metric=price가 문서 검색으로 연결되고 validation_failed | 실패 원본 보존 |
| 25 / 복합 질문 | 문서 발췌+가격 표+출처+단일 done | branch 보존 확인, 설명 품질의 완전한 정답 검증 아님 |
| 26 / 복합 질문 | 문서 발췌+가격 표 1개+출처+done, 10.85초 | 실행/표현 경계 통과 |
| 26 / 기준 502 최근 가격 | 2026-09-30 통상가격 22,916.73 등 가격 표+출처, 5.30초 | 기존 단순 경로 위임 성공; 독립 SQL 재검증은 이번 범위에서 미실시 |
| 26 / 희소금속 보고서 광종 가격 | 리튬 13,335.89, 희토류 15,541.34 USD/톤(20260930), 표 2개, 일부 실패 안내, 7.70초 | PARTIAL 유지. 전체 광종 성공 아님 |
| 26 / 한국 리튬 교역지도(mode=page) | 대한민국 수급지도 추천, status=recommended, 3.45초 | 명시 page 경로 통과 |

최종 요청 session ID:

- composite: `93799fb1-583e-407b-861b-6f9b3a006db1`
- criterion: `45ced5d6-a497-4407-8ca5-2af25c59c365`
- doc: `5f5fcee7-8d02-4cb4-9049-81680975feae`
- page: `3f82698c-6e4a-4776-bbd0-286fa2373b11`

SSE 원본: `/tmp/komir-contract{23,24,25,26}-{case}.sse`.
임시 파일이므로 장기 보관 artifact가 아니며, 위 표/세션 ID는 재검증 근거로 문서화했다.
검증에 사용한 데이터의 기존 개발용 더미 허용 설정은 변경하지 않았다.

## 회귀

- 전체 `inhouse/rag_core/tests`: **710 passed / 146 subtests passed / 0 failed**.
- 이전 전체 결과 695 passed 대비 신규 테스트 15개, 기존 PASS→FAIL 0.
- `smoke_chat_routing.py`: enabled page, 기존 page/document, 소유권 거절, 광산 후속 경로 모두 통과.
- compileall / git diff --check / Docker build / healthz 통과.
- production source에 신규 질문 문자열별 조건 또는 semantic regex 추가 없음.
- 문서 경계/ID 정규화는 lexical 처리이며 QA fixture는 production에서 읽지 않는다.

## 남은 한계 — 전체 해결로 주장하지 않는 항목

1. Compare/Join의 실제 키·피연산자 계산 계약은 여전히 미구현이다. 잘못된 SUCCESS를
   막았지만 해당 연산을 지원하게 된 것은 아니다. group_by 집계도 명시 기권한다.
2. 복수 root의 `previous` 같은 모호한 참조를 어떤 출력으로 해석할지, 여러 root를 묶은
   result_id 전체 복원 계약은 이번 테스트로 해결을 증명하지 않았다. 정확한 step 참조와
   단일 root snapshot 보존만 검증했다.
3. 문서 조회의 '최신 문서에서 포함 여부 확인'과 '포함 문서 중 최신 선택'의 순서 구분,
   완전 본문 추출 coverage, source_span별 citation 노출은 여전히 추가 계약 검증이 필요하다.
   이번에는 stale fact 사용 방지와 불완전 추출의 잘못된 부재 판단을 수정했다.
4. navigation의 명시 mode=page는 고쳤지만, enabled+auto에서 자연어 메뉴 의도가
   올바르게 분류되는 전체 경로는 검증하지 않았다.
5. Gemma가 문서 광종 추출을 중복 ForEach로 생성하는 변동이 25번 이미지에서 관찰됐다.
   최종 응답이 나왔다는 이유로 해당 계획의 최소성/의미 정확성까지 PASS로 보지 않는다.
6. 복합 문서 응답은 검증된 원문 발췌를 표시한다. 자연스러운 용도 요약, 원문 언어와
   내부 node label의 사용자 친화적 표현까지 완료한 것은 아니다.
7. 실서버 재시작 후 사용자별 history 복원과 저장 장애 주입 E2E는 이번에 실행하지 않았다.

따라서 이번 결과는 재현된 공통 실행 오류의 수정 및 제한된 live 검증이다.
전체 architecture/모든 자연어 질의의 수정 완료 선언이 아니다.
