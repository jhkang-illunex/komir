# acceptance integration 수정 전 조사 — 2026-09-23

## 실행 경계

- 읽기 전용으로 AGENTS.md, WORKLOG, 색인기, PageIndex, pgvector, 고정 fixture를 대조했다.
- DB write, 재색인, 배포, commit은 수행하지 않았다.
- 기존 dirty 파일은 변경하지 않았다.

## 확인된 식별자 계약

- OKF/PageIndex `doc_id`: `doc_<24 hex>`.
- pgvector `doc_chunk.doc_id`: `front.doc_id.removeprefix("doc_")[:16]`.
- `doc_chunk.source_path`: OKF frontmatter의 `resource`.
- 따라서 tree ID를 그대로 dense hit 및 `_chunk_count`와 비교하는 현재 검사는 잘못이다.

실측 DB 청크:

| tree doc_id | pgvector doc_id | embedding 청크 수 |
|---|---:|---:|
| `doc_738ead83c52ecab761f68fb4` | `738ead83c52ecab7` | 768 |
| `doc_51886c72704a2c9017503e3c` | `51886c72704a2c90` | 1 |
| `doc_d623918d8502f6dc962570c0` | `d623918d8502f6dc` | 2 |
| `doc_c756024d734b611ff55d7b23` | `c756024d734b611f` | 23 |

## 고정 fixture와 실제 결과

- AC28 고정 원본 tree: `doc_e09bbbbdac2e3b3a0b95915f`, OKF
  `조달청보고서/2009년_1월_로이터_비철금속_가격_전망_자료_2.md`.
  원본 SHA-256은 `a0c6de0f68488efc4d75ded4487f9169d33d7bddce11b75e9d2b6960fdabf32b`,
  OKF 본문 및 tree hash는 `c2dce9a9e2d5ad2cc59670733b63d1f2f0ea25abba3ad068983ea7c18e3cadee`다.
  `설문참여자수 41`은 OKF 본문에 존재한다.
- AC28~30은 public 제외 조건을 적용한 고정 query dense top 10에서 기대 문서가 없다.
  이는 데이터/환경 차단이 아니라 현재 수락 실패다.
- AC39는 public 제외 조건을 적용하면 기대 pgvector ID `738ead83c52ecab7`가 top 1이다.
  동일 검색의 top 10 전체에는 고정 exact fact가 없다. 기대 문서 검색 성공과 exact fact
  검색 실패를 별도 subcheck 증거로 남기되, 기존 fixture 계약에 따라 케이스는 FAIL이다.
  현재 tree full ID 비교만 false FAIL 원인이다.
- AC39에서 `exclude_src`를 생략하면 top 10의 2위에 Argus private 원천이 1건 포함됐다.
  `PRIVATE_ONLY_SOURCE_GROUPS={"Argus_비철금속_일일"}` 적용 시 0건이었다.
- 임베딩 계약은 `intfloat/multilingual-e5-small`, 384차원이다.
- AC40 고정 사실은 현재 OKF 본문 49~60행에 있고 search top 5에는 없다. top 10에서는
  7위 node `0007`, line 49에 있다. 현재 검사는 fixture hash만 보며 tree 저장 hash와
  hit의 resource/okf_path/line 범위를 검증하지 않는다.
- AC40 현재 tree에는 `okf_body_sha256`가 없다. 누락/STALE 모두 freshness 실패여야 한다.
- AC41 세 현재 OKF hash와 tree 저장 hash는 일치하고 고정 사실도 지정 범위에 있다.
  pgvector에는 정규화된 16자 ID로 청크가 있으며 각 사실을 포함한 청크도 1개 이상이다.
- AC29 원본 HWP에는 `추가 하락 전망`, `가격 추가 하락`이 니켈 행 문맥에 함께 있다.
  현재 검사는 원본의 두 문구와 downstream의 `니 켈`을 따로 보므로 내용 연결이 없다.
  현재 OKF/청크에는 두 전망 문구가 실제로 존재하므로 같은 문맥 연결 검사가 가능하다.
  front/tree `minerals=[]`는 현 상태이며, 이를 기대 정상값으로 강제하지 않고 parser→front→tree
  전달 일치 여부를 증거로 남긴다.
- AC30 원본 `산출결과` 시트 3행의 헤더와 4행의 단일 레코드가 연결된다.
  D3=`광석`, D4=`41875`; L3=`최종 금속량`, L4=`303.7481341598289`;
  B4=`광석 생산량(kwmt)`. 현재 flattened membership는 값을 다른 행으로 섞어도 통과한다.
- AC30 PageIndex 고정 query 결과는 0건이다. 현 상태는 FAIL이어야 한다.

## required_checks 구현 계획

각 YAML `checks`를 사전 정의 ID에 1:1로 매핑한다. 모든 ID를 정확히 한 번 기록하며,
선행 실패로 실행하지 못한 검사는 `SKIPPED`와 이유를 기록하고 최종 PASS를 금지한다.

- AC28~30: `original_metadata_provenance`, `fixed_document_chain`,
  `dense_expected_document`, `format_sample_policy`.
- AC39: `embedding_model_dimension`, `dense_candidate_metadata`,
  `dense_expected_document_topk`, `vector_only_no_fallback`.
- AC40: `fixed_doc_filter`, `node_okf_range_identity`, `node_original_text`.
- AC41: `three_nonempty_bodies`, `three_tree_hashes_fresh`,
  `three_valid_roots_and_node_text`, `three_latest_chunk_texts`, `all_three_atomic`.

각 체크에는 fixture 입력, 실행 여부, 실제 식별자/경로/hash/range/count 또는 skip 이유를
남긴다. 최종 PASS 조건은 전체 ID가 한 번씩 PASS인 경우뿐이다.

## 수정 범위

- `inhouse/rag_chat/tests/acceptance_integrations.py`
- `inhouse/rag_chat/tests/acceptance_fixtures.json`
- 신규 `inhouse/rag_chat/tests/test_acceptance_integrations.py`

수정 직전 fixture는 같은 증거 디렉터리에 `acceptance_fixtures.json.before`로 복사한다.
