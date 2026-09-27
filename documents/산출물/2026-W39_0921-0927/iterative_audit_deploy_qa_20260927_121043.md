# 배포 이미지 QA 보완 권고 — 2026-09-27 12:10:43 KST

## 대상·근거

- 기준 이미지: `komir-rag-chat:20260927-composite-citations-r1`
- 컨테이너: `komir-rag-chat-test` (`:18002`), `/healthz` HTTP 200
- QA: 실제 `/pubchat` SSE, `verify_live_chatbot.py`, Sol 감사
- 범위: Planner 계약, 복합 결과 인용/조립, DEV_DUMMY 표기, 라이브 수락 검사
- 제외: DB·문서 색인 변경, 운영 배포, `expired/` 파이프라인

## 관찰 결과

1. 희토류 생산량·매장량 복합 질의는 두 `resource.rank` Action과 별도 인용
   (`KO_RSRC_PRDCTN_QUTY`, `KO_RSRC_BURUDG_QUTY`)으로 성공했다.
2. `구리 광산 생산량 최근 YoY 증가 상위 5개를 보여줘`는
   `abstained=true`, `abstain_reason=slot_unresolved`로 실패했다. Planner가
   `mine_rank`가 아닌 intent를 내면 `_normalize_mine_intent()`가 적용되지 않는다.
3. 실제 가격 기준이 `[DEV_DUMMY] spot`인 경우 기존 제거 조건(정확히
   `[DEV_DUMMY]`)을 통과해 상태가 가격기준으로 노출될 수 있다.
4. 복합 자원순위 답변에서 생산량 요약이 중복되고 매장량 요약은 누락됐다.
5. 라이브 수락 검사는 첫 실패에서 종료하며 `done`의 단 한 번·최종 이벤트 여부를
   보장하지 않는다. 따라서 이후 회귀가 관찰되지 않는다.
6. 요청 기간보다 보유 관측기간이 짧은 가격 응답은 실제 범위를 별도 표시해야 한다.

## 수정 우선순위

| 우선순위 | 항목 | 완료 기준 |
|---|---|---|
| P1 | 광산 YoY intent/slot 정규화 | 실제 문형이 `mine.rank`·`production`·`yoy_increase`·`top_n=5`로 검증된다. |
| P1 | DEV_DUMMY 기준 분리 | `[DEV_DUMMY]` 변형이 가격 기준에 나오지 않고 별도 경고/상태만 남는다. |
| P1 | 복합 자원순위 요약 귀속 | requirement별 요약이 한 번만 나오며 다른 metric 요약을 대체하지 않는다. |
| P2 | 수락 검사 지속 실행·terminal 계약 | 모든 케이스를 실행하고, 각 응답은 terminal `done` 1회만 허용한다. |
| P2 | 실제 관측기간 고지 | 요청기간과 실제 관측기간이 다르면 실제 범위를 함께 표시한다. |

## iterative-audit 실행 계획

- 위험도: **HIGH** (Planner 공개 계약·근거/경고 표현·SSE 회귀)
- 라운드 상한: 3
- 파일 소유: 단일 작업자(`action_contract.py`, `chatbot.py`,
  `verify_live_chatbot.py` 및 대응 테스트)
- 검증: 좁은 단위 테스트 → 라이브 재현 2건 → Sol 차분 감사 1회
- 배포: 사용자가 별도 요청할 때만 이미지 재빌드/재기동

## 실행 결과

### 이번 라운드 수정

- `extract_action_plan()` 앞단에 완결된 `광산 + metric + YoY + 상위 N` 문형의
  `mine.rank` 결정적 계획을 추가했다. Planner 오분류와 repair 실패를 우회하되,
  문형 밖의 광산 질의는 기존 typed planner 경로를 유지한다.
- 가격기준에서 `[DEV_DUMMY]` 접두 토큰을 대소문자·공백 무관하게 제거해 데이터
  상태가 가격기준으로 표시되지 않게 했다. 본문뿐 아니라 citation 단위도 같은
  정규화를 적용해 남은 기준값만 표시한다.
- `_country_rank_summary()`가 복구된 `resource.rank` 계획의 표를 무역 국가순위
  요약으로 재사용하지 않게 차단했다.
- `verify_live_chatbot.py`가 terminal `done`의 단 한 번·마지막 이벤트 조건을
  검사하고, DEV_DUMMY를 가격기준이 아닌 별도 경고로 기대하도록 갱신했다.

### 검증

- `test_action_contract_audit`, `test_mine_ranking_action`,
  `test_resource_rank_citations`, `test_price_unit_disclosure`,
  `test_acceptance_suite_runner`: **99 passed**
- `py_compile` 및 `git diff --check`: 통과
- Sol 차분 감사: HIGH/CRITICAL 잔존 없음. Planner 결정 경로, 본문·citation의
  DEV_DUMMY 제거, 자원순위 요약 귀속, terminal `done` 계약을 확인했다.

### 이미지 재빌드·테스트 배포

- 새 이미지: `komir-rag-chat:20260927-qa-hardening-r1`
  (`sha256:f88c2827c8f8a5e5eacb26e754d85d1b1d0e5df8f4234264e9a8e2eb7b4dda9f`)
- `komir-rag-chat-test`를 새 이미지로 교체하고 `/healthz` HTTP 200을 확인했다.
  콜드 스타트가 약 40초여서 초기 15초 헬스 체크 실패 시에는 자동 롤백되었고,
  대기 시간을 확장한 재시도에서 정상 기동했다. 이전 컨테이너는
  `komir-rag-chat-test-pre-20260927-qa-hardening-r2`로 보존했다.
- 실제 `/pubchat` SSE로 `구리 광산 생산량 최근 YoY 증가 상위 5개를 보여줘`를
  검증했다: terminal `done` 1회·최종 이벤트, `abstained=false`, `mine_yoy_rank`
  인용 1건.

### 후속 P2

- 수락 검사의 케이스별 실패 수집(전체 실행 후 종합 실패) 구조화
- 가격 요청 기간과 실제 보유 관측기간의 병기
