# Sol 후속 검색 개선 및 격리 재색인 계획

## 현재 판정

- 공유 DB·운영 OKF·운영 Tree에는 쓰지 않았다.
- 동일 조건 acceptance: AC41만 PASS, AC28·29·30·39·40은 FAIL이다.
  - AC28: 기존 dense top 10 exact fact 누락만 남았다.
  - AC29: 기존 DB 청크가 새 행 경계 청킹과 다르고 dense top 10 fact가 없다.
  - AC30: 운영 Tree hash 누락과 기존 dense top 10 fact 누락이 남았다.
  - AC39: 기존 dense top 10에 고정 exact fact가 없다.
  - AC40: 운영 Tree hash 누락만 남았다. 본문 점수화 후 fact node 자체는 top 1이다.
- 격리 Tree 재생성 결과 AC29·30·40은 모두 현재 OKF hash와 일치했고 고정 fact node가 top 1이었다.
- 재색인 대상 신규 청크 1,654개 전체와 기존 대상 4문서를 제외한 공개 코퍼스를
  합산한 격리 실임베딩 순위는 AC28=1, AC29=1, AC30=1, AC39=2다. 네 case 모두
  고정 exact fact가 top 10 안에 남는다.

## 변경된 검색 계약

- 임베딩 입력에 문서 제목과 절 제목을 붙인다. DB `txt`에는 원문 청크를 그대로 저장한다.
- OCR로 띄어진 핵심 광종명은 임베딩 입력에서만 정규화한다.
- HWP의 광종별 불릿 행은 다른 광종 행과 분리한다.
- 100,000자 이상 대용량 보고서의 영어 산문은 문장 경계를 지켜 800자까지 병합한다.
  80자 이하이며 수치가 2개 이상인 짧은 사실 문장은 독립 청크로 둔다.
- USGS_2026 청크 수는 기존 768건에서 1,639건으로 늘어난다. 최초 문장 단위안 4,173건보다 2,534건 적다.
- PageIndex는 제목·요약뿐 아니라 실제 node 범위의 OKF 본문도 점수화한다.

## DB 변경 대상과 예상 영향

현재 대상은 정확히 4개 vector doc ID, 776행이다.

| case | src | vector doc_id | 현재 | 예상 |
|---|---|---:|---:|---:|
| AC28 | 조달청보고서 | `e09bbbbdac2e3b3a` | 4 | 4 |
| AC29 | 조달청보고서 | `c5ba28f3421c6bb1` | 2 | 9 |
| AC30 | 광산자료 | `3b3b60baa05e7715` | 2 | 2 |
| AC39 | 생산매장량_USGS | `738ead83c52ecab7` | 768 | 1,639 |

합계는 776행에서 1,654행으로 878행 증가한다. 새 `--doc-id` 경로는 이 네 ID만 같은 트랜잭션에서 삭제·삽입하며 같은 source group의 다른 문서를 지우지 않는다.

## 승인 후 실행 명령

먼저 DB 원복용 테이블을 만든다.

```sql
CREATE TABLE mineral_risk.doc_chunk_backup_acceptance_260923 AS
SELECT *
FROM mineral_risk.doc_chunk
WHERE doc_id = ANY (ARRAY[
  'e09bbbbdac2e3b3a',
  'c5ba28f3421c6bb1',
  '3b3b60baa05e7715',
  '738ead83c52ecab7'
]);
```

OKF와 Tree 파일은 별도 백업 디렉터리에 복사한 다음 메타데이터와 Tree를 갱신한다.

```bash
cd inhouse
python -m ingest.okf.build_okf_documents \
  --enrich-metadata \
  --metadata-pattern 1019_LME_Seminar에서_발표한_품목별_동향_및_전망

python -m ingest.pageindex.build_pageindex_trees \
  --pattern 1019_LME_Seminar에서_발표한_품목별_동향_및_전망 \
  --no-summary --force
python -m ingest.pageindex.build_pageindex_trees \
  --pattern Ni_Weda_Bay_2025_Prod_AR_260814__2 \
  --no-summary --force
python -m ingest.pageindex.build_pageindex_trees \
  --pattern 생산매장량_USGS/USGS_2026.md \
  --no-summary --force
```

네 문서만 재임베딩한다.

```bash
cd inhouse
python -m ingest.vectorize.build_pgvector_okf \
  --source-group 조달청보고서 \
  --source-group 광산자료 \
  --source-group 생산매장량_USGS \
  --doc-id doc_e09bbbbdac2e3b3a0b95915f \
  --doc-id doc_c5ba28f3421c6bb14b086a0b \
  --doc-id doc_3b3b60baa05e7715521b4901 \
  --doc-id doc_738ead83c52ecab761f68fb4
```

## DB 원복 SQL

```sql
BEGIN;
DELETE FROM mineral_risk.doc_chunk
WHERE doc_id = ANY (ARRAY[
  'e09bbbbdac2e3b3a',
  'c5ba28f3421c6bb1',
  '3b3b60baa05e7715',
  '738ead83c52ecab7'
]);
INSERT INTO mineral_risk.doc_chunk
SELECT * FROM mineral_risk.doc_chunk_backup_acceptance_260923;
COMMIT;
```

OKF·Tree 원복은 실행 전에 복사한 네 파일을 같은 경로로 되돌린다. acceptance와 서비스 검증이 끝난 뒤에만 백업 테이블을 삭제한다.
