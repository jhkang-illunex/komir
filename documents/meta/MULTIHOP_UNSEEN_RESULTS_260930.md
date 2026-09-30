# Unseen / paraphrase QA 실행 기록

fixture: `MULTIHOP_UNSEEN_QA_260930.json`

목적은 원본 Q 문구를 규칙으로 맞추는 것이 아니라, 의미가 같은 표현에서 AST/typed
history/reference 판단이 유지되는지 확인하는 것이다. 실행은 실제 enabled Docker의
Gemma→AST→Pipe→기존 Action/Tool→evidence→SSE 경로로 수행했다.

| 묶음 | 검증 대상 | 관측 결과 | 판정 |
|---|---|---|---|
| U01 | rank→TopK→retrieve, 두 번째 reference | 1턴 ranking은 table/chart로 완료, 2턴 수입 evidence 부족으로 abstain | 정상 fail-closed |
| U02 | rank→filter→metric replacement→country share | 첫 턴 evidence abstain, 후속은 slot unresolved/unsupported metric으로 종료 | capability/evidence 제한 |
| U03 | ranking list projection, ordinal, metric/period replacement | 첫 턴 ranking 완료, 후속 생산량/기간 질의는 evidence 또는 unsupported commodity로 종료 | 정상 제한 |
| U04 | country list, 첫 항목 제외/재포함 context mutation | `top_n=unknown` parser 출력은 AST validation 대상으로 확인, 후속 subset 실행은 SSE done, 근거 부족은 abstain | AST 수정 대상 확인 |
| U05 | 가격 filter→수입 filter→병렬 생산/국가비중 | 입력 없는 calculate와 evidence 부족이 관측됨 | AST/evidence fail-closed |
| U06 | entity carry-over, same-period compare, ordinal document | 1턴 text/table 완료, 2~3턴은 직접 근거 부족으로 abstain | 정상 제한 |

모든 실행 turn은 기존 SSE의 terminal `done`까지 도달했다. 숫자·순위·표를 evidence
검증 전에 확정하지 않았고, unsupported metric이나 빈 intermediate result를 자연어
추론으로 채우지 않았다. U04의 `top_n=unknown`, U05의 입력 없는 계산은 이후
`SemanticProgram.completeness_issues()`와 top-k type 검증의 회귀로 고정했다.

검증된 contract 범위:

- ordinal은 raw assistant 답변 재파싱이 아니라 이전 TypedResult의 index binding을 사용한다.
- metric/period replacement는 semantic history의 active binding을 입력으로 사용한다.
- context mutation은 기존 result subset을 Pipe input으로 재사용하며, 필요한 결과가 없으면
  deterministic abstain/failure로 닫는다.
- list projection은 upstream row field가 존재하는지 검사하고 한국어/영문 canonical alias를
  binding한다.

이 결과는 PASS율을 높이기 위한 성공 집계가 아니다. 실제 데이터/evidence가 없는 후속은
unseen 표현에서도 계속 abstain하는 것이 의도된 결과다.
