# 챗봇 수락검사 후속 반복 근거

- 날짜: 2026-09-23
- 조정/독립 감사: Astra
- 검사 구현: Sol (`sol_acceptance_integration`)
- 추출 메타데이터 조사·수정: Terra (`terra_ingest_metadata`)
- 목적: 이전 Cycle 2 Round 4에서 발견한 검사 결함과 추출 오류를 서로 분리하여 수정·재검증한다. 새 반복 상한은 5라운드다.
- 입력: `baseline.json`, `acceptance_fixtures.json.before`, `acceptance_integrations.py.before`, `tree_metadata_before.json`.
- 이전 실행 원본: `komir-astra-cycle2-round3/`, `komir-astra-cycle2-round4/`는 같은 이름의 `/tmp/` 결과를 내용 변경 없이 복사 보존했다.
- 제외: DB 쓰기, 재색인, 배포, 커밋, live 32건 전체 실행, intent/action 구조 변경.
- 현재 서비스: 18002 `komir-rag-chat-test`, 이미지 `komir-rag-chat:260923-trade-global-port-r1`(root 확인). 본 디렉토리의 로컬 검증은 서비스 배포 완료를 의미하지 않는다.
- 캐시: 실제 재실행은 별도 Python subprocess로 수행하여 PageIndex `lru_cache`와 임베딩 모듈 전역 모델 캐시를 초기화한다.
- 판정: 미구현·검사 결함·실제 검색 누락은 FAIL. 원본 또는 실행환경이 없어 검증할 수 없다는 근거가 있는 경우만 BLOCKED_DATA/ENV. 기대 질문·top_k를 결과에 맞춰 완화하지 않는다.

## 최종 결과

- 조정·구현·감사 3라운드로 종료. 상세 최종 보고는 [상위 디렉토리 보고서](../챗봇_후속반복감사_최종결과_260923.md).
- `astra_acceptance_unit_final.log`: 33건 PASS.
- `astra_ingest_round2_raw.log`: 46건 PASS.
- `astra_module/chatbot_acceptance_20260923_195003.json`: module 10건 PASS.
- `astra_integration_final/chatbot_acceptance_20260923_200341.json`: AC41 PASS, AC28/29/30/39/40 FAIL.
- `astra_integration_audit.py`와 `astra_integration_negative_final.log`: 실제/독립 정상 대조군과 19개 오류 변형, HWP/Excel 문맥·public dense 호출 경계.
- `astra_ingest_audit.py`와 `astra_ingest_audit.log`: 광종·날짜 부정 입력 및 실제 SQL 전달 제거 mutation. SQL은 전부 mock이며 공유 DB에 쓰지 않는다.
- `final_verification.json`: core 3파일 SHA 불변, 기존 fixture 모든 값 불변, 최종 수정 소스 SHA.
- 기존 `/tmp` JSON 안의 원래 로그 경로는 당시 실행의 provenance로 보존했다. 실제 사본은 이 디렉토리의 같은 이름 하위 폴더에 있다.
