# QA500: 실제 Gemma shadow 및 결정론적 backend 검증

## 범위와 판정

`qa_build_order2_4_500.txt` 500건 전부를 등록하고 실제 Gemma에 호출했다.
스킬은 `qa-build`를 적용했다. 기준 커밋은 `0e77c5989`이며 변경은 미커밋·미배포다.
운영 PostgreSQL, 18002, 검증 18011은 수정·재시작하지 않았다.
18002는 `komir-rag-chat:audit-safety22`, 18011은 `audit-relations30`을 유지한다.

이 보고서는 **500개 자연어 질문이 모두 성공했다는 보고서가 아니다.**
실제 모델의 V2 shadow 출력, 현재 코드로 다시 만든 LogicalProgram,
격리 SQLite에서 실행한 runtime, 독립 SQL Gold 결과를 단계별로 구분한다.
V2→live IR 변환은 테스트 전용 adapter이며 운영 HTTP/SSE E2E가 아니다.
fixture/adapter 미지원은 production capability 부재로 단정하지 않았다.

질문별 원장: [corpus_results.csv](qa500_validation_20261002/corpus_results.csv),
상세 원장: [corpus_results.json](qa500_validation_20261002/corpus_results.json).
원문의 validation 필드는 질문 생성 당시 기준선을 보존하고, 현재 결과는
`execution_report` 링크와 동일 QA ID로 별도 연결했다.

## 실제 실행량

| 항목 | 결과 |
|---|---:|
| 고유 QA / 등록 | 500 / 500 |
| order 2 / 3 / 4 | 160 / 180 / 160 |
| 단일 질문 / 3턴 시나리오 | 460 / 40 |
| 최초 실제 Gemma 호출 | 500 QA / 580 발화 |
| 수정 후 추가 실제 호출 | 151 QA / 171 발화 |
| 총 모델 실행 기록 | 651 QA 실행 / 751 발화 |
| 최신 기록의 현재 runtime 진입 | 491 QA / 555 턴 |
| 모든 턴 runtime 진입 | 478 QA |
| 운영 HTTP/SSE E2E | 0 |

모델: `gemma-4-26b-a4b`, endpoint `127.0.0.1:52302/v1`.
고정 평가 기준시점은 2026-10-01. Gold/정답/질문 ID는 프롬프트에 넣지 않았다.
모델 자체 복구 재시도는 위 발화 수와 별도로 raw attempts에 보존했다.

수정 후 전체 500건을 새 모델 출력으로 교체한 것은 아니다.
각 QA의 마지막 실행을 실패도 포함하여 채택했다: 최초 기록 355건,
125 패턴 대표 재호출 기록 119건, 추가 24건, 재확인 2건.
이 기록을 현재 schema/planner/lowerer로 재생한 결과다.
따라서 서로 다른 실행 집합의 수치를 엄밀한 동일조건 전후 성공률로 표현하지 않는다.

## Gold 계획의 backend 검증 — 모델 성공과 별개

| 구분 | QA 수 |
|---|---:|
| 일반 집계·관계·문서 연결 Gold 통과 | 172 |
| 시계열 Gold 전체 요구 통과 | 24 |
| 3턴 Gold 전체 요구 통과 | 36 |
| **Gold backend 전체 요구 통과 합계** | **232** |
| 시계열 계산 부분 통과, 의미 계약 미확정 | 8 |
| snapshot→InputRef 연결 gap | 4 |
| 별도 수치 Gold 실행계획 없음 | 256 |

합계 500. 별도 Gold가 없는 256건도 모델 호출·계획 재생·가능한 runtime 실행·실패
분류는 수행했다. Gold 232건을 실제 자연어 E2E 232 PASS로 승격하지 않았다.
172건에는 불완전 모집단/단위 불일치에서 올바르게 기권한 8건이 포함된다.
pytest에서 gap 재현을 확인하는 테스트가 통과해도 해당 QA는 gap이다.

## 실제 모델 계획의 실행 상태

다음은 의미 PASS가 아니라 QA별 runtime 주 상태의 상호 배타적 집계다.

| 상태 | QA |
|---|---:|
| runtime 완료 — 별도 의미 검증 필요 | 15 |
| 실제 계획의 필수 계약 부족 | 378 |
| runtime 실패 | 38 |
| 테스트 IR adapter 연결 한계 | 44 |
| synthetic fixture adapter 한계 | 3 |
| 적격 조회 후 실제 행 부재 | 0 |
| 모델의 unsupported 반환 | 8 |
| planner 실패 | 13 |
| parsing/schema 실패 | 1 |
| 합계 | 500 |

계획 실패 뒤에도 독립 branch는 실행했으므로 runtime 진입 수와 전체 성공 수는 다르다.
예: join key, comparison field, 두 입력 등 필수 관계 계약이 없어도 단일 Retrieve는
성공할 수 있다. 이를 복합 질문 성공으로 집계하지 않았다.
모델 unsupported 8건 역시 정상 거절로 자동 인정하지 않았다.
초기 재생에서 데이터 없음으로 분류됐던 6건을 재조사했다. 광종 미바인딩,
목록의 단일 광종 문자열 처리, 재고 필드 미연결이었다. NULL 광종으로 SQL을
실행하거나 field-unavailable EMPTY를 데이터 부재로 분류하지 않도록 평가 경계를
수정했다. 불완전 계획을 정상값으로 치환하지 않았으며 실제 데이터 부재로 남은 건은 0이다.

## 이번에 보완한 공통 경로

- Aggregate: group-by, count, 평균/합계, 표준편차, 최초/최신 및 NULL 처리.
  NULL 제외 합계는 PARTIAL을 유지하여 전체 국가 비중/HHI의 분모로 사용하지 않는다.
- Calculate: share/HHI, 기간 시작·끝 변화율, 월별 수익률, 기준값 100,
  임계점 최초 선택, 명시적 시계열 정렬·상관 계산.
- ISO 날짜 Sort/극값과 동률, Project alias 및 문서 MineralSet 전달.
- 명시적 typed scalar broadcast 비교. 불명확한 implicit broadcast는 계속 거절한다.
- 국가·날짜 InputRef를 목적 슬롯에 연결하며 광종 추출과 분리한다.
- history 결과 ID의 손실 없는 인코딩: `price-CU`/`price_CU` 충돌 제거.
- V2 연도/ISO 기간 normalization, 실제 Aggregate/Calculate node 생성,
  독립 root 보존, 무역 원시 조회의 `trade.monthly` lowering, 매장량 metric 보존,
  ActionSlots 재검증, document 요구를 용도 조회로 바꾸던 기본값 제거.
- 단일 root·단일 명시 output의 fields를 실제 최종 Project로 연결한다.
  다른 source, Composite, 다중 출력의 모호한 참조는 임의로 추정하지 않는다.
- Project의 존재하지 않는 필드를 NULL 성공으로 만들지 않는다. 실제 NULL 값은
  보존하며, 유효 Filter의 빈 결과와 문서 MineralSet 추출도 유지한다.

새 Intent/Action은 추가하지 않았다. production QA ID/질문 문자열 분기,
신규 semantic regex, fixture의 production import는 0이다.
normalization은 typed enum/필드/기간에서만 수행한다.

독립 감사에서 다음 High를 재현하여 수정했다.

1. NULL 제외 합계가 완전 모집단 HHI로 승격됨 → PARTIAL·후속 거절.
2. Gold SQL만 기간을 제한하고 실행 AST는 연간 조회 → 실행 인자로 fixture 조회.
3. oracle가 순서·단위·evidence 오류를 놓침 → mutation 검증 추가.
4. 국가/날짜 binding이 광종을 덮어씀 → 입력 역할 분리 및 실제 ActionSlots 검사.
5. history ID 정규화 충돌 → 원본 ID의 UTF-8 hex 인코딩.
6. Project가 미생성 country_count를 NULL 성공으로 출력하고 평가기가 key 존재만
   확인함 → runtime의 missing-column 거절 + 독립 국가 수의 수치 비교/NULL mutant.

마지막 독립 재감사에서 해당 수정 범위 잔여 High/Critical 없음.
이는 아래에 기록한 전체 기능 gap까지 해소했다는 의미는 아니다.

## 남은 계약과 한계

- V2의 일반 constraints, requested output/source 연결, 명시 Project가 executable
  연산으로 모두 보존되지 않는다. 올바른 수치 한 개만 나와도 전체 의미 PASS가 아니다.
- Join/Compare 입력·key·field·연산이 누락되거나 다항 관계로 생성되는 경우가 남는다.
  Gold나 원문 키워드로 누락된 계획을 몰래 보정하지 않았다.
- V2 EntitySet/ForEach와 저장 snapshot 연결은 live Gold runtime 지원과 별개다.
  실제 Gemma multi-turn 입력에는 이전 requirement가 있었지만 실행 snapshot 연결은
  검증하지 못했다. 36건 Gold multi-turn 성공으로 이를 대체하지 않는다.
- PAT-043: trailing window 기준시점/달력 규칙, PAT-080: 정확 수치 주장 검증의
  허용오차·판정 계약이 미확정이다. 계산 부분만 통과한다.
- PAT-121 4건: legacy 항목별 snapshot-only turn을 live InputRef로 복원하는 경계.
  권한·근거·부분실패를 보존하는 계약 없이 요약문으로 값을 복원하지 않았다.
- 현재 fixture adapter의 `trade.concentration` 등 미지원은 기존 tool 자체의 부재가
  아니다. 별도 운영 source나 실제 문서 검증도 수행했다고 주장하지 않는다.

## Synthetic 데이터

운영 데이터를 복제하지 않은 공통 SQLite fixture다. 질의별 전용 DB는 없다.

| domain | rows |
|---|---:|
| price | 1,512 |
| inventory | 1,512 |
| indicator | 3,024 |
| trade | 13,608 |
| production | 378 |
| reserves | 378 |
| observations 합계 | 20,412 |
| synthetic documents | 924 |

광종 9, 국가 6, 2019~2025. NULL/0/tie/복수 국가·기간·단위가 포함된다.
fixture 조회는 실제 lowering 슬롯을 소비하고 독립 SQL oracle와 비교한다.
네트워크/실제 ActionTool 호출을 금지하는 tripwire 테스트를 포함한다.

## 재현 및 보존

```bash
PYTHONPATH=inhouse:. pytest -q inhouse/rag_core/tests
PYTHONPATH=inhouse:. python3 -m inhouse.rag_core.tests.qa500_actual_execution --self-test
PYTHONPATH=inhouse:. python3 -m inhouse.rag_core.tests.qa500_semantic_audit --self-test
PYTHONPATH=inhouse:. python3 -m compileall -q inhouse/rag_core/ragkit inhouse/rag_core/tests
git diff --check
```

`qa500_validation_20261002/`에 raw model 응답, current AST/lowering/runtime 결과,
독립 SQL Gold 결과, 질문별 실패 원인, sha256, 회귀 로그를 gzip으로 보존했다.
JSONL을 풀어 `qa500_actual_execution --inputs ... --output ...`으로 모델 재호출 없이
현재 코드의 offline 재생이 가능하다. 새 Gemma 측정은 `qa500_frontend_run`을 사용한다.

최종 숫자는 `execution_summary.json`, `corpus_results.json` 및 보존 회귀 로그가 정본이다.

## 최종 질문별 accounting

이는 **실제 Gemma V2 → 현재 계획 → synthetic runtime → 의미/결과 검증**의
보수적인 질문 전체 판정이다. Gold 수동 계획 통과 수나 pytest 통과 수가 아니다.

```text
SUPPLIED:       500
REGISTERED:     500
PASS:             4
FAILED:         468
CAPABILITY_GAP:   28
UNSUPPORTED:      0
BLOCKED:          0
PENDING:          0
SUM:            500
```

- PASS 4: EXT500-001~004. 실제 모델이 생성한 최고가격·전체 동률 날짜 요구,
  최종 Project, 동일 기간·광종·단위·근거 및 독립 SQL 수치가 일치했다.
- FAILED 468: 의미 불일치 185, 계획 필수 계약 부족 245, runtime 28,
  planner 9, parsing/schema 1. 한 QA의 주 원인 하나만 세어 중복을 피했다.
- GAP 28: 테스트 IR adapter 23, fixture adapter 3, 평가 oracle 경계 2.
  이를 모두 production의 미구현 capability 28개라고 해석하면 안 된다.
- runtime 성공 15건을 독립적으로 재검토: 전체 요구 통과 4, 구체 결함 6,
  평가 경계 미확정 5. 마지막 5건 중 다른 단계에서 확정된 의미 실패도 있어
  최종 상호 배타 집계와 수치가 다르다.
- 모델 unsupported 8건은 정상 거절임이 검증되지 않아 UNSUPPORTED_CORRECT로
  올리지 않고 관련 의미 실패에 포함했다.

미해결 부분은 key·field·operation·입력 관계·출력 lineage를 명확히 표현하는
semantic/planning 계약과 V2/runtime 연결이다. 질문별 규칙, 빈 값을 정상값으로
치환, Gold 계획의 모델 출력 주입으로 성공률을 올리지 않았다.

## 최종 회귀

Baseline: **752 PASS / 146 subtests / 0 FAIL**.
Final: **1,194 PASS / 687 subtests / 0 FAIL**.
Existing PASS→FAIL: **0**. compileall / git diff --check 통과.
회귀에는 gap 재현·평가기 mutant 검증도 포함되므로 테스트 수를 QA PASS로 환산하지 않는다.

**STATUS: DONE** — 이번 corpus 실행·공통 수정·실패 분류 라운드 완료.
500개 기능 지원 완료나 운영 배포 완료를 뜻하지 않는다.
