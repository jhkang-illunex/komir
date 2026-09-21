# PageIndex·OKF 조회 r16 변경 및 배포 기록

## 변경 범위

- `inhouse/rag_core/ragkit/action_contract.py`: `document.lookup`, `mine.profile`, `mine.rank`의 닫힌 intent·slot 계약과 중복 요구 정규화. 광산 단위 질문을 광종·HS 교역 집계로 오분류해 발생하던 `slot_unresolved`를 제거했다.
- `inhouse/rag_core/ragkit/chatbot_graph.py`: PageIndex·OKF 본문과 명시 문서 선택을 기존 MCP 경로에 연결했다. 공개 접근 필터를 유지하며, 출처가 없는 경우 답변을 보류한다. 명시 HS 코드의 금액·중량 근거가 같은 코드·원천·단위를 충족하면 모델 출력 형식 오류로 근거가 소실되지 않도록 결정적으로 확인한다.
- `inhouse/rag_core/retrieval/pageindex.py`, `evidence.py`: 지정 문서의 실제 표 행을 선택하고 광산명·위치 열과 OKF 경로·행 번호를 인용에 보존한다. 회사명처럼 여러 광산에 걸친 질문은 단일 위치로 답하지 않는다.
- `inhouse/rag_core/retrieval/mine_aggregate.py`: 개별 광산의 국가 필터, 생산량·매장량 순위, 기간 내 생산량 증가 순위를 조회한다.
- `inhouse/rag_chat` 및 MCP 클라이언트·서버: 새 action의 공개/비공개 라우팅과 응답을 연결했다.

설계와 질문별 독립 판정은 [intent 설계](챗봇_PageIndex_OKF_intent_설계_260922.md), [독립검증](챗봇_PageIndex_OKF_독립검증_260922.md)에 있다.

## 배포 전 검증

- 격리 이미지 `sha256:91457daf43306a7671f814dd4312a653a3aa4b5e961dc6e5fddbe2b2fbbef76c`(r16), 18021 포트에서 수용했다.
- r10f 원문 30건 모두 완료. 답변 7, 실제 원천 부족 22, 질문 자체가 범위 밖인 Q30 1. `slot_unresolved`와 `unsupported_combination`은 0.
- JV Inkai·Escondida는 OKF 원문 32·33행을 인용했다. 근거 없는 개별 광산 수입액 질문은 7/7회 무인용 `source_unavailable`이었다. HS 2603000000은 별도 3회와 전체 회귀 1회에서 금액·중량 원천 2건으로 답했다.
- 관련 rag_core 단위 테스트 66건, rag_chat 테스트 23건, `git diff --check` 통과.

## Git·서버 반영 및 후속 수정

- 진행 중인 `main` 리베이스를 건드리지 않도록 `feature/pageindex-okf-r16-260922` 릴리스 브랜치를 분리했다. 최초 커밋 `44c0f9e73`을 `origin`에 푸시했다.
- 최초 배포 이미지 `sha256:594646084f7109262ece6afc28b0ba4b48ae36bb27a506511c36908bc7b120e3`을 `komir-rag-chat-test`(18002)에 반영했다. 이전 컨테이너는 `komir-rag-chat-test-pre-r16-260922`로 중지·보존했다. 이미지의 환경변수 집합은 이전 컨테이너와 동일했다.
- 운영 포트 첫 점검 원시 `/tmp/komir-r16-postdeploy-260922/`: JV Inkai·Escondida의 실제 OKF 행 인용, 복수 광산 모호성, 근거 없는 수입액·비공개 Argus 기권, 리튬 매장량 순위, 생산량 증가 순위, HS 2603000000 요약은 기대한 경로로 완료했다. 다만 “중국의 생산량이 가장 많은 광산이 어디 있나요? 이름이 뭔가요?”가 `slot_unresolved`로 실패했다.
- 실제 계획 재추출 3회에서 `mine.rank`(production, level, top_n=1, country_scope=중국)와 광산명이 비어 있는 불필요한 `mine.profile`이 함께 생성됐다. 광산명은 순위 결과에서 찾는 값이므로 이 중복 profile을 제거하는 typed 정규화 규칙을 추가했다. 관련 단위 테스트 67건과 `git diff --check`가 통과했다.
- 18023(r17)에서 중국 1위 질문은 슬롯 오류 없이 `mine_no_comparable_values:all`로 기권했다. 중국 필터의 광산별 비교 가능한 생산량이 확인되지 않아 광산명을 만들지 않았다. 그러나 생산량 증가 상위 5개는 모델 검증이 집계표를 한 행으로 오독해 거짓 기권했다.
- 18024(r18)의 단순 순위표 우회는 더 심각한 수치 오류를 드러냈다. Rio Tinto 원문은 `Q4 2024`, `Q1~Q4 2025`, `연간 2024`, `연간 2025` 열을 섞는데, 기존 추출은 Q4 2024 값을 연간 2024로 읽었다. Oyu Tolgoi의 43.8천t→227.8천t 증가 184천t은 잘못된 계산이다. 이 후보는 배포하지 않았다.
- `mine_aggregate.py`에서 증가량은 연간 실적 두 연도만 비교하고, 셀 좌표를 안전하게 복원할 수 없는 분기·연간 혼합 표의 생산 발췌문은 증가 순위에서 제외하도록 수정했다. 남은 집계 5행(Escondida, Tenke Fungurume, Salvador, Radomiro Tomic, Highland Valley Copper)의 시작·끝 값, 기간, 단위를 각각 OKF 원문에 대조했다.
- 집계 5행과 원문 검증 후에도 후속 모델이 표를 한 행으로 오독하는 변동이 있어, `mine.rank` 생산 증가 순위에 한해 연간 검증 표식·요청 행 수·값/증가 산식·출처 경로를 모두 검사하는 결정적 통과 조건을 추가했다. 관련 단위 테스트 70건이 통과했다.
- 최종 후보 이미지 `sha256:0caea6e44b2c3389a7318010547e9725522e7aed6f89c99fd89a7f4129bcdd5e`(r21)를 18027 격리 포트에서 검증했다. `MINE_INCREASE` 반복 2회에서 같은 안전한 5행·연간 수치·개별 OKF path를 반환했고 Rio 혼합 행은 없었다. 원시 `/tmp/komir-r21-predeploy-260922/MINE_INCREASE_{1,2}.json`.
- r21의 기존 OKF·광산·HS 수용 9건은 기대한 답변 또는 근거에 맞는 기권이었다. 중국 1위 광산은 슬롯 오류 없이 `mine_no_comparable_values:all`로 기권했다. 원시 `/tmp/komir-r21-predeploy-260922/`.
- r10f 원문 30건 전체 재실행은 30/30 완료, 답변 7·실원천 부족 22·실제 범위 밖(Q30) 1, `slot_unresolved` 0·`unsupported_combination` 0이었다. HS 2603000000은 USD/kg 근거 2건으로 답했다. 원시 `/tmp/sol-okf-r21-r10f-replay-260922/`.
- 수정 커밋 `e2d7f7e9d`를 같은 원격 릴리스 브랜치에 푸시했다. 이 커밋에서 빌드한 이미지 digest는 위 r21 후보와 동일한 `sha256:0caea6e44b2c3389a7318010547e9725522e7aed6f89c99fd89a7f4129bcdd5e`다.
- 기존 18002 컨테이너는 `komir-rag-chat-test-r16-260922`로 중지·보존하고, 이미지 `komir-rag-chat:e2d7f7e9d`를 같은 `komir-rag-chat-test` 이름과 18002 포트에 기동했다. 새 프로세스의 `/healthz`는 `{"status":"ok"}`를 반환했다. 컨테이너 교체로 프로세스 내 캐시도 비워졌다.
- 운영 포트의 배포 후 점검 원시 `/tmp/komir-r21-postdeploy-260922/`에서 10/10 요청이 exit 0·done이었다. JV Inkai·Escondida는 실제 OKF 32·33행을 인용했고, 복수 Kazatomprom은 광산명 지정을 안내했다. 리튬 매장량 상위 5개와 2024→2025 연간 생산량 증가 상위 5개는 집계 인용과 함께 답했다. 증가량 5행은 앞서 원문 대조한 Escondida 180,000t, Tenke Fungurume 109,951t, Salvador 41,300t, Radomiro Tomic 24,800t, Highland Valley Copper 24,700t과 일치했다.
- HS 2603000000은 금액·중량 실자료 인용 2건으로 답했다. 중국 1위 광산은 `mine.rank`를 수행한 뒤 비교 가능한 생산량 근거가 없어 무인용 `source_unavailable`로 기권했고 `slot_unresolved`는 발생하지 않았다. 원문에 없는 JV Inkai 수입액, 공개 범위 밖 Argus, 데이터·추론 구분 질문도 각각 무인용 출처 부족으로 처리했다.
- `main`은 별도 리베이스가 진행 중이어서 병합하거나 수정하지 않았다. 이번 푸시는 `feature/pageindex-okf-r16-260922` 브랜치에만 반영했다.
