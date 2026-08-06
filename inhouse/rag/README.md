# RAG 서비스 — 구현 노트

`documents/산출물/` 보고서를 지식베이스로 삼는 사내 RAG 챗봇의 기반 구현. 사용자가 공유한
"RAG 구현 핵심 가이드"(2026-08-05)의 원칙을 그대로 따름 — 기술을 먼저 고르지 않고 실패
유형을 먼저 진단하고, 스키마는 역량질문에서 역산하고, 인용 강제+기권으로 환각을 억제.

## 디렉토리
```
rag/
  docs/estimate_question/   # 68개 원문서 → 예상질문 2,830개(골든셋 겸용). README.md가 인덱스.
  ragkit/                   # 파이프라인 코드 (python -m rag.ragkit.<module>로 실행)
    ingest.py                # documents/산출물 md+docx 로드(pdf는 md 중복이라 스킵)
    chunk.py                 # 마크다운 헤딩 기준 청킹 + 긴 섹션 문단분할
    tokenize_ko.py            # 한글 BM25용 글자 바이그램+ASCII토큰 전처리
    embed.py                  # dense 임베딩(intfloat/multilingual-e5-small, 로컬)
    build_index.py            # 위 전부 -> rag/index/rag.duckdb 적재 + FTS 인덱스
    retrieve.py                # 하이브리드 검색(BM25+dense, RRF 융합)
    generate.py                 # 인용강제 답변 생성 + 날조인용 제거 + 기권
    eval_retrieval.py            # 골든셋(estimate_question) 기반 recall@k/MRR 평가
  eval_reports/               # 평가 실행 결과(삭제 금지 — artifact-provenance-policy)
  index/rag.duckdb              # 로컬 전용 산출물(gitignore, *.duckdb 규칙 적용)
```

## 아키텍처 결정 (가이드 §1 진단표 적용)

`estimate_question` 2,830문항을 키워드로 스캔한 결과:
- "왜/근거" 17.2%, "수치/사실확인" 13.9%, "절차/방법" 10.9%, "문서내 비교" 8.2%
  — 대부분 **단일 문서·단일 섹션 안에서 답 가능한 단일홉 질문**.
- "버전비교/변경"(다른 날짜의 개정판을 대조해야 답 가능)은 1.1%로 소수.
- "구조화 데이터 계산"형 질문(매출·통계를 즉석 계산)은 사실상 없음 — 이 코퍼스는
  이미 DuckDB(`warehouse/minerals.duckdb`)에 정형 데이터가 별도로 있고, 보고서 문서
  자체는 서술형이라 RAG 스코프에 자연스럽게 들어맞음.

→ **하이브리드 바닐라 RAG**(BM25+dense+RRF, 문서 내 헤딩 구조를 그대로 청크 경계로 재사용)로
시작. GraphRAG는 진단상 정당화되지 않아 도입하지 않음 — 평가에서 실제 다중홉/관계형
실패모드가 확인되면 그때 재검토(가이드 §6: "복잡도는 확인된 실패모드만큼만").

## 스키마 (가이드 §3: 역량질문에서 역산, 온톨로지 새로 안 만듦)
```
doc(doc_id, source_path, week, series_key, doc_date, title, ext)
chunk(chunk_id, doc_id, chunk_order, section_heading, text, fts_text, char_len, embedding FLOAT[384])
```
`series_key`/`doc_date`는 같은 제목이 날짜만 바뀌어 재등장하는 개정판(예:
`핵심광물_시스템구성_요약본_260713` → `_260716` → `_260722`)을 묶기 위한 최소 필드 —
"도메인에 대해 아는 모든 것"을 모델링하지 않고, 실제로 필요가 확인된 딱 이만큼만 넣었다.

## 실행
```bash
# 1) 인덱스 빌드(재실행 시 전체 재빌드, 멱등) — 첫 실행 시 임베딩 모델 다운로드
python3 -m rag.ragkit.build_index

# 2) 검색만 확인
python3 -m rag.ragkit.retrieve "fact_indicator에서 제거된 PRICE 중복 행수는?"

# 3) 검색 품질 평가(골든셋 전체 or 샘플 n건)
python3 -m rag.ragkit.eval_retrieval        # 전체 2,830문항
python3 -m rag.ragkit.eval_retrieval 200    # 무작위 200문항 샘플

# 4) 답변 생성(로컬 LLM 서버 필요 — 아래 한계 참고)
python3 -m rag.ragkit.generate "진단모델 AUC는 얼마인가?"
```

## 현재 상태(2026-08-05)
- 문서 68건 → 청크 977개, `rag/index/rag.duckdb`에 적재 완료.
- 검색 품질(전체 2,830문항 평가, 상세는 `eval_reports/retrieval_eval_260805.md`):
  recall@5 78.9% / recall@10 89.1% / MRR 0.624. 미스는 무작위가 아니라 **버전 개정판
  문서군**과 **종합요약 문서**에 집중 — 원인과 다음 레버 후보는 리포트 참고.
- 생성(인용강제+기권) 로직은 스텁으로 단위검증 완료(정상 인용 유지 / 무인용 절 폐기 /
  존재하지 않는 근거번호 인용 시 전체 기권 — 모두 의도대로 동작 확인).
  **실LLM 종단 테스트는 아직 못함** — 이 워크트리에 `.env`가 없고(gitignore, 로컬 전용)
  `LLM_BASE_URL`(예: 11434) 로컬 서버도 기동돼 있지 않음. `.env.example`을 복사해
  `LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL` 채우고 서버를 띄우면 `generate.py`가 바로 동작하는
  구조(geo 파이프라인과 동일한 `geo/llm/openai_compat.py`를 그대로 재사용해 provider
  전환도 geo와 동일하게 됨).

## 신규 의존성 없음
sentence-transformers·duckdb(+fts extension)·python-docx·python-dotenv 모두 기존 환경에
이미 설치돼 있었음 — 새 패키지 설치 0건. DuckDB FTS 확장은 최초 실행 시 자동 설치(`INSTALL
fts`, 네트워크 필요, 이후 로컬 캐시).

## 다음 단계 후보 (미착수, 판단 필요)
1. `.env` 구성 + 로컬 LLM 기동 후 생성 파이프라인 종단 검증 + Faithfulness/기권율 측정.
2. 버전 계열 중복 완화(최신판 우선 노출 또는 "이 문서의 다른 버전" 병기) — 그래프 없이
   기존 `series_key`/`doc_date`만으로 가능.
3. 크로스인코더 리랭커 도입 여부 — 실제 recall@1 개선폭을 A/B로 먼저 확인 후 결정.
4. 규제/컴플라이언스 요건(가이드 §8)은 사내 문서 한정 RAG라 이번 라운드 범위 밖으로 판단 —
   접근제어가 실제로 필요해지면(다른 부서 공유 등) 그때 설계에 반영.
