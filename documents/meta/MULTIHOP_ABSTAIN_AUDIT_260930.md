# Q01~Q30 ABSTAIN_VALID 원인 감사

기준 실행은 `komir-rag-chat:multihop-work-r5` enabled 컨테이너의 2026-09-30
Q01~Q30 결과이며, 각 요청의 session_id와 `multihop_shadow_compare` AST/Pipe/Step
로그를 결합했다. 이후 r8~r10에서 bridge alias·field binding·Langfuse 연결을
재검증했지만, 이 표의 baseline 분포 자체는 PASS 8 / ABSTAIN_VALID 22이다.

## 1차 원인 분포

| 1차 원인 | 문항 | 건수 | 실제 데이터 부족과의 관계 |
|---|---|---:|---|
| DATA_UNAVAILABLE | Q05, Q17, Q21, Q24, Q26, Q27 | 6 | 원천에 요청 기간·대상·직접 문서가 없거나 지원 대상이 아님 |
| AST_INCOMPLETE | Q07, Q18 | 2 | `flow=trend`, `scope=summary_report`처럼 semantic slot이 물리 contract와 불일치 |
| BINDING_FAILURE | Q25 | 1 | 이전 비교 결과에 downstream 계산 field가 없어 selector가 실패 |
| TOOL_CAPABILITY_MISSING | Q02, Q08, Q09, Q10, Q14, Q20, Q22 | 7 | 기존 Action/Tool이 해당 metric을 제공하지 않음. 일부는 도메인 원천 자체도 없음 |
| EVIDENCE_INSUFFICIENT | Q03, Q13, Q15, Q19, Q28 | 5 | 일부 자료는 있으나 질문의 순위·비교·주장까지 직접 지지하지 못함 |
| 기타(OUT_OF_SCOPE) | Q30 | 1 | 광물 BI 범위 밖 질문 |
| **합계** |  | **22** |  |

### 데이터 부족과 architecture 한계의 구분

- 순수 데이터 부족: 6건. 이 문항들은 실행 가능한 AST가 있어도 실제 기간·대상·문서가
  없어 계속 abstain해야 한다.
- architecture/contract 우선 수정 대상: 10건(AST_INCOMPLETE 2 + BINDING_FAILURE 1 +
  TOOL_CAPABILITY_MISSING 7). 이 중 metric이 운영 데이터에 존재하는지는 별도 확인해야
  하며, Action/Tool이 제공하지 않는다고 값을 추정하지 않는다.
- 근거 충분성 문제: 5건. 검색 결과가 일부 존재해도 요청한 비교·순위·주장을 직접
  검증하지 못하면 성공으로 승격하지 않는다.
- 범위 밖: 1건.

Q03은 리튬 수입금액 일부가 관측되었지만 상위 5개국이라는 결과를 직접 뒷받침하는
근거가 없어 EVIDENCE_INSUFFICIENT으로 분류했다. Q24는 코발트 동일 기간 가격 근거가
없어 DATA_UNAVAILABLE이다. Q25는 이전 turn의 typed result에 `price_change_rate`,
`start_value`, `end_value`가 없어서 BINDING_FAILURE이며, 새 AST completeness 검사에서
실행 전 `ast_incomplete`로 검출하는 대상이다.

## 수정 후 정책

`SemanticProgram.validate()`가 구조 검증 뒤 downstream `filter/sort/rank/arg_max/
arg_min/project`와 `field` selector의 요구 field가 upstream retrieve/entity/project
contract에 존재하는지 검사한다. 없으면 Pipe를 실행하지 않고 `ast_incomplete`로 종료한다.
`mineral` selector는 `광종/광물/원소/entity`의 typed column alias만 허용하며, 질문별
문구 분기는 추가하지 않는다.

Q30 전체를 새 이미지에서 재실행할 때 PASS가 늘지 않더라도 정상이다. 데이터 부족과
근거 부족 abstain은 유지하고, unseen paraphrase에서 같은 AST completeness·abstain
판단이 재현되는지를 성공 기준으로 삼는다.

## 후속 실행 결과

r13 enabled Docker 재실행에서는 30/30건이 terminal `done`에 도달했고 `PASS 7 / ABSTAIN_VALID 23`이었다.
r5 기준선의 `PASS 8 / ABSTAIN_VALID 22`보다 PASS를 높이지 않았다. Gemma의 동일 질문
계획 변동으로 Q03과 Q04의 실행 결과가 교대했으며, Q03/Q12 관련 로그에는 실제 무역
결과의 `country/period/unit` metadata와 AST project dependency를 구분하기 위한 contract
검증이 남는다. 이 변동을 데이터가 없는 성공으로 보정하지 않았다.

이번 라운드의 직접 수정은 다음과 같다.

- downstream field/selector가 upstream에서 생성되지 않으면 실행 전에 `ast_incomplete`로
  닫는다. `top_n=unknown`과 잘못된 root dependency도 같은 경계에서 차단한다.
- 실제 무역 결과의 canonical metadata와 `국가/비중/기간/단위/수입액` column alias를
  binding에 선언했다. 기존 leaf Calculate handler는 회귀 호환을 위해 허용한다.
- volatility 후속의 `광종` field selector는 typed alias로 resolve되며 실제 r15 SSE에서
  `result field not found in sequence: mineral` 오류가 재현되지 않았다.

따라서 기존 22건의 원인 분포는 기준선 감사값으로 보존하고, 최신 23건 실행은
재현성/모델 계획 변동을 포함한 운영 관측값으로 별도 보고한다. 순수 데이터 부족과
근거 부족은 여전히 정상 abstain이며, PASS 비율을 높이기 위해 정책을 완화하지 않았다.
