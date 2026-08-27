# RAG 문서 코퍼스 — 데이터 유형·수량·public/private 할당 (2026-08-26 실측)

## 범위

이 문서는 `/pubchat`·`/prichat`의 hybrid_search·pageindex_lookup이 조회하는
**RAG 문서 코퍼스**(OKF 텍스트 → doc_chunk 청크 / PageIndex 트리)만 다룬다 —
public/private 분리가 실제로 걸리는 대상이 이 코퍼스이기 때문이다.

**범위 밖(참고)**: 진단·예측·위기지수 등 구조화(정형) 산출물(`out_diagnosis_alert`·
`out_import_forecast`·`geo_index` 등, 관세청·ECOS·USGS 수치 데이터가 원천)은
별도 파이프라인이고 라이선스 이슈가 없어 **public/private 구분 없이 동일하게
제공**된다(`latest_diagnosis`/`import_forecast`/`geo_index_trend` 도구, 두
프로필 모두 `_mcp_tools_common.py`에서 같은 코드로 서빙). 원천 상세는
`documents/meta/DATA_REGISTRY.md` 참고.

## 1. 문서군별 수량·파일유형 (OKF 원문 기준, 2026-08-26 직접 스캔)

전체 **1,642건**(`data_lake/semi_structure/okf_documents/**/*.md`, 각 문서의
YAML 프론트매터 `fmt` 필드를 전수 집계).

| 문서군 | 건수 | 파일유형 | public/private |
|---|---:|---|---|
| Argus_비철금속_일일 | 690 | PDF 690건 | **private 전용** |
| 조달청보고서 | 868 | PDF 867건 · HWP 1건 | public |
| 산출물(komir 자체 산출물) | 72 | Markdown 58건 · DOCX 14건 | public |
| 생산매장량_USGS | 8 | PDF 8건 | public |
| 외부자료(KOMIS 해외투자가이드 4개국) | 4 | Markdown 4건 | public |
| **합계** | **1,642** | | |

파일유형 합계: **PDF 1,565건**(95.3%) · **Markdown 62건**(3.8%, 자체 산출물+
외부자료) · **DOCX 14건**(0.9%) · **HWP 1건**(0.1%). 이번 코퍼스엔 **Excel(xlsx)
소스 문서가 없다** — 참고로 WoodMac 등 엑셀 원장 데이터는 이 RAG 문서 코퍼스가
아니라 별도 구조화(정형) 파이프라인 쪽에서 다룬다(범위 밖 각주 참고).

## 2. public/private 할당 근거

- **판정 기준**: 라이선스 재배포 제한이 있는 제3자 문서만 private 전용 —
  현재는 **Argus 비철금속 일일동향 하나**(`shared.retrieval.access.
  PRIVATE_ONLY_SOURCE_GROUPS`). 나머지(조달청·USGS·komir 자체 산출물·KOMIS
  외부자료)는 공개 가능한 원천이라 public.
- **강제 지점**: `mcp_server_public.py`(hybrid_search·pageindex_lookup 두
  도구가 이 상수를 하드코딩으로 하위 함수에 넘김) vs `mcp_server_private.py`
  (같은 상수를 아예 import 안 함) — 물리적으로 분리된 코드 경로(2026-08-26,
  상세는 `rag/ragkit/mcp_server_public.py` 모듈독스트링).
- **검증**: `services/rag_chat/tests/smoke_mcp_access.py`가 실 데이터로
  public 응답에 Argus 소스 0건, private 응답엔 포함됨을 매 실행마다 확인.

## 3. 검색 단위(doc_chunk, pgvector+BM25) 기준 수량

OKF 문서는 청킹돼 Postgres `mineral_risk.doc_chunk`에 dense(e5-small 임베딩)+
BM25(tsvector) 색인으로 들어간다 — 실제 hybrid_search가 도는 단위는 문서
건수가 아니라 이 청크 건수다.

| 문서군(=`doc_chunk.src`) | 청크 수 | 비중 |
|---|---:|---:|
| Argus_비철금속_일일 | 77,648 | 55.4% |
| 조달청보고서 | 55,530 | 39.6% |
| 생산매장량_USGS | 5,647 | 4.0% |
| documents/산출물 | 1,084 | 0.8% |
| 외부자료 | 176 | 0.1% |
| **합계** | **140,085** | 100% |

**public 프로필이 실제로 조회 가능한 청크는 62,437건**(140,085 − Argus
77,648) — 전체의 약 44.6%다. Argus가 전체 코퍼스의 절반 이상(55.4%)을 차지해,
private 전용 처리로 제외되는 비중이 결코 작지 않다는 점은 감안할 필요가
있다(용량·문서건수 대비 청크가 특히 많은 이유는 Argus가 일간 발행물이라
발행 빈도가 조달청 주간·USGS 연간보다 훨씬 높기 때문).

## 4. PageIndex 트리(목차 색인) 기준

문서군별 건수는 §1과 동일(1건당 트리 1개, `pageindex_trees/**/*.tree.json`)
— 위치 포인터만 가지므로 별도 수량 지표는 없다. §1의 public/private 열이
`pageindex_lookup` 도구에도 그대로 적용된다.

## 참고

- 실측 방법: OKF 프론트매터 `fmt` 필드 전수 스캔(1,642건) + `doc_chunk.src`
  GROUP BY(140,085행) — 둘 다 이 문서 작성 시점에 직접 재쿼리했다(기존 문서
  수치 재인용 아님).
- 관련 문서: `OKF_PageIndex_색인구조_저장소사용량_설명_260826.md`(같은 폴더,
  저장소 용량 관점), `rag/ragkit/mcp_server_public.py`/`mcp_server_private.py`
  (강제 지점 코드), `services/shared/retrieval/access.py`(할당 기준 상수).
