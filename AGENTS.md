# AGENTS.md — 핵심광물 수급위기 진단·수요예측 시스템

## 기본 응답 언어

- 코드 또는 사용자가 입력한 원문이 아닌 한 항상 한국어로 응답한다.

## 프로젝트 현황과 정본

- 발주처는 광해광업공단/KOMIS이며, 대상 광종은 CU·NI·CO·LI·REE(대표 원소 Nd)다.
- 현재 가동 대상은 `inhouse/rag_chat`, `inhouse/report_gen`, `inhouse/streamlit_demo`,
  문서 정제·색인(`inhouse/ingest`), 통합보고서(`inhouse/mnrl_report`)다.
- `expired/`는 2026-09-07에 격리된 진단·예측·지정학 파이프라인이다. 라이브 코드에서
  이를 import하거나 참조하지 않는다. 재가동은 명시 요청이 있을 때만 검토한다.
- 현재 상태의 정본은 이 파일, `documents/meta/WORKLOG.md`(최신 항목이 위),
  `documents/meta/DATA_REGISTRY.md`, `documents/meta/CONTAINER_ARCHITECTURE.md`다.
  `README.md`와 `documents/CLAUDE.md`는 초기 프로토타입 스냅샷이므로 현재 상태 판단에
  사용하지 않는다.
- 발주처 보고 문서는 `documents/산출물/<ISO 주차>/`의 최신 날짜 버전이 정본이다.
  `mine_ws/komis/`와 `documents/dev/`는 이 저장소의 작업 근거로 사용하지 않는다.

## 구조와 의존성

- `dmz/`는 외부망 수집기 전용, `inhouse/`는 air-gapped 분석·서빙 전용이다. 수집기 코드를
  in-house 패키지에 다시 결합하지 않는다.
- 의존 방향은 앱/도메인 → `inhouse/common` 단방향이다. `inhouse/rag_core`는 RAG 도메인
  코어로서 의도된 예외이며, 앱·ingest가 이를 참조할 수 있다.
- 컨테이너 구성과 실제 서비스 소스는 `documents/meta/CONTAINER_ARCHITECTURE.md`를 먼저
  확인한다. 소스 변경만으로 배포 반영을 가정하지 말고, 대상 컨테이너 이미지·프로세스를
  확인한 뒤 검증한다.

## 작업 시작과 실행

1. 이 파일과 `documents/meta/WORKLOG.md`의 최신 항목을 읽어 현재 제약을 파악한다.
2. 변경 전에는 대상 서비스·DB·실행 경로가 라이브인지 `expired/`인지 확인한다.
3. 파일 기반 정제·색인은 `inhouse/`에서 `python -m ingest.<submodule>`로 실행한다.
4. RAG 챗봇과 요약보고서는 컨테이너로, Streamlit 데모는
   `inhouse/streamlit_demo`에서 실행한다.

`.env`의 값 줄에 인라인 주석을 넣지 않는다. 이 프로젝트의 env-file 파서는 주석까지
값으로 읽을 수 있다.

## 변경·검증 원칙

- 변경은 최소 범위로 하고, 기존에 검증된 공용 로직을 수정할 때는 회귀 검증 계획을 함께
  마련한다.
- 수치·행 수·데이터 존재 여부는 문서의 과거 수치를 재인용하지 말고 실제 쿼리 또는 실행으로
  재확인한다.
- 새로운 지표·시리즈 이름을 만들기 전 `fact_indicator`와 관련 `SERIES_SPEC`에 동일 이름이
  있는지 확인한다. 해당 PK에는 `src`가 없어 조용한 덮어쓰기가 발생할 수 있다.
- 진단·예측 파이프라인을 명시적으로 재가동하는 작업에서만, 신규 피처·모델 후보를
  `r10_retune_harness.py`의 스크리닝→부트스트랩→예측 exog 절차로 검정한다. QWK/FAR/WAPE
  같은 구체 기준과 기준선을 정의하지 않은 채 채택하지 않는다.
- `챔피언_스코어보드_*.md`와 작업 이력에 실패로 기록된 접근은 재시도하지 않는다.
- 배포·재검증 시 캐시 영향을 확인한다. 필요하면 대상 프로세스/컨테이너를 재시작해
  `st.cache_*`, `lru_cache`, 모듈 전역 캐시를 비운 뒤 같은 조건에서 전후 결과를 비교한다.

## 다중 에이전트 작업

- 병렬 작업은 파일 소유권이 겹치지 않을 때만 사용한다. Codex 서브에이전트는 공유 작업공간을
  사용하므로 동일 파일을 동시에 수정하게 하지 않는다.
- 실제 배포, 공유 DB의 비가역 변경, 병합·커밋은 명시된 담당자만 수행한다.
- 감사 결과와 수정 완료 주장은 코드 인용, 실제 요청·응답, 테스트 출력 등 재현 가능한
  근거를 포함해야 한다.
