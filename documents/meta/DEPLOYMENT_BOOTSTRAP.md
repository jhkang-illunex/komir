# Deployment Bootstrap / Capability Validation

기준 Agent architecture는 변경하지 않는다. 이 절차는 새 서버의 PostgreSQL, PageIndex,
OKF, embedding/vector 환경 차이를 검사하고, Agent-owned HistoryStore migration만
명시적으로 적용한다.

## 실행

컨테이너 또는 `inhouse/rag_chat` 실행 환경에서 다음처럼 실행한다.

```bash
PYTHONPATH=inhouse/rag_chat:inhouse \
python -m app.deployment_bootstrap \
  --check \
  --manifest /tmp/deployment_capability_manifest.json
```

`--check`는 DB/네트워크/파일을 읽기만 하고 business schema나 vector index를 변경하지
않는다. HistoryStore를 적용할 때만 별도로 실행한다.

```bash
PYTHONPATH=inhouse/rag_chat:inhouse \
python -m app.deployment_bootstrap \
  --migrate \
  --manifest /tmp/deployment_capability_manifest.json
```

실행 중인 서비스까지 smoke 검증하려면 `--smoke-url http://127.0.0.1:8002`를 추가한다.
기본 smoke는 structured table/chart/done과 deterministic abstain/done을 검사하며,
필요하면 `BOOTSTRAP_SMOKE_CASES_JSON`으로 질문과 필수 SSE event/payload field를
명시할 수 있다. `--manifest` 출력은 보고서이므로 dry-run의 유일한 파일 쓰기다.

## 검사 범위

- Application: version, required env, LLM endpoint, service health
- PostgreSQL: connection, configured schemas, capability table/column/row/period coverage
- HistoryStore: `ai_chatbot.schema_migration`과 `multihop_history` version/readiness
- PageIndex/OKF: 실제 mount path, readable, 파일 수, representative file 접근
- Entity binding: 선택적 `BOOTSTRAP_ENTITY_BINDINGS_JSON`의 source alias 검증
- Embedding/vector: backend/model/revision/dimension/preprocessing/normalization/index metadata
- Smoke: 기존 SSE의 terminal `done`, table/chart/citation/abstain 요구

표준 DB capability는 현재 tool이 사용하는 읽기 전용 원천을 기준으로 검사한다.
`BOOTSTRAP_CAPABILITIES_JSON`으로 새 서버의 table/column 계약을 환경별로 바꿀 수 있다.
현재 개발환경의 파일 수나 행 수를 expected constant로 사용하지 않는다.

## Vector compatibility

pgvector 행과 dimension만 확인되고 모델 metadata가 없으면 `REINDEX_REQUIRED`다.
dimension이 같다는 이유로 재사용하지 않는다. 호환성 판단용 sidecar는 다음 형태로
명시한다.

```json
{
  "model": "intfloat/multilingual-e5-small",
  "revision": "<immutable revision>",
  "dimension": 384,
  "preprocessing": "e5-prefix-v1",
  "normalization": "l2"
}
```

`VECTOR_INDEX_METADATA_PATH`가 가리키는 metadata가 현재 embedding 설정과 모두 일치할
때만 `AVAILABLE`이다. 불일치하거나 metadata가 없으면 기존 index는 유지하고 새 snapshot/
index를 별도 version으로 생성한 뒤 검증 후 activate한다. 이 bootstrap 명령은 reindex나
기존 index 삭제를 수행하지 않는다.

## 판정

- `READY`: 필수 dependency, HistoryStore migration, mount, LLM, smoke가 정상이며 제한 없음
- `DEGRADED`: 서비스는 기동 가능하나 vector reindex, 일부 DB capability, entity binding,
  smoke skip 등이 남음
- `NOT_READY`: PostgreSQL/필수 schema/HistoryStore migration/PageIndex·OKF 필수 mount/
  LLM 또는 요구된 smoke가 실패

`manifest.overall.critical_reasons`와 `limitations`를 함께 확인한다. Data capability가
없는 경우 Agent를 수정하지 않고 기존 evidence validation을 통해 deterministic abstain한다.

## Migration 책임

`ai_chatbot.schema_migration`과 `ai_chatbot.multihop_semantic_turn`은 Agent-owned 영역이다.
`--migrate` 또는 `inhouse/data_lake/db/schema_multihop_history.sql`을 명시적으로 적용할
수 있지만, `public`, `mineral_risk`, `doc_chunk` 등 business/data schema는 bootstrap이
생성·수정하지 않는다. migration은 재실행 가능하며, 이미 version 1이면 같은 결과를
유지한다.
