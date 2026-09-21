# PageIndex·OKF 조회 intent 설계 (2026-09-22)

## 현행 경로와 확인한 빈틈

라이브 소스는 `inhouse/rag_core/ragkit/action_contract.py`와 `chatbot_graph.py`, `inhouse/rag_core/retrieval/{pageindex.py,dense_pg.py}`다. `inhouse/rag_chat/Containerfile`은 이 코드를 `/app/rag_core`로 복사한다. `inhouse/services/rag_chat/Containerfile`은 구 `rag/ragkit` 경로이므로 이번 배포 대상이 아니다. 기존 `document`/`concept` intent는 `document.retrieve`로 바뀌고, route가 dense+PageIndex를 켠다. 조회 노드는 public/private MCP의 `call_pageindex_lookup(..., with_text=True)`를 호출한다. PageIndex는 트리 후보를 찾고 OKF 본문을 읽으며, 본문이 빈 노드는 제외한다.

`document.retrieve`는 일반 개념·원인 설명에 맞지만, 특정 문서·절을 찾아달라는 요청과 특정 광산의 위치·소유 등 단건 사실 조회를 구별하지 못한다. `mine.rank`는 순위·집계 전용이므로 단건 광산 조회에 사용하면 기존 집계 변경을 침범한다. `pageindex.lookup('Kazatomprom 우라늄 광산 위치')` 실조회는 관련 문서 후보 점수 0.8을 찾지만 `nodes=[]`다. 문서 후보 제목만으로 위치 사실을 답할 수 없다. 반면 실제 OKF `광산자료/우라늄/20260813_Kazatomprom_우라늄_광산_정리자료.md` 28~42행에는 광산별 위도·경도 표가 있다. 이 사례는 문서 후보 뒤 본문 선택이 끊긴 명확한 수리 대상이다.

## 최소 설계와 파일 소유권

1. `action_contract.py`: closed intent `okf_lookup`과 `mine_profile`, action `document.lookup`과 `mine.profile`을 추가한다. `okf_lookup`은 “어느 OKF 문서/원문/절에 있나” 또는 문서명을 지정한 내용 확인, `mine_profile`은 **한 광산의** 위치·소유·현황을 다룬다. 두 action 모두 확인된 광산명 또는 topic을 필수 슬롯으로 하되, 없는 광종·국가·기간을 추측해 채우지 않는다. 일반 설명은 현행 `document.retrieve`, 광산 순위·비교·집계는 현행 `mine.rank`, 국가 순위는 `resource.rank`로 유지한다. 프롬프트에 이 경계와 예시를 적고 다중 action 허용은 별도 검증 전까지 열지 않는다.
2. `chatbot_graph.py`: 두 새 action을 typed 슬롯에서 기존 public/private MCP 검색 route로 바꾼다. `document.lookup`은 PageIndex 우선, `mine.profile`은 PageIndex와 dense 병행이다. 관련 문서 후보가 있지만 `nodes=[]`인 경우 **후보가 명확하고 접근 가능한 OKF 문서에만** 기존 `pageindex.get_tree/read_node_text` 또는 동일 MCP 도구를 통해 해당 문서의 제한된 본문을 읽는 결정적 폴백을 둔다. 이는 인덱스/OKF 자료를 다시 구축하지 않고 기존 경로를 연결하는 변경이다. 제목·파일명만을 수치나 위치의 근거로 쓰지 않는다. 공용 조회가 private 문서를 열지 못하게 MCP profile/source-group 필터를 그대로 적용한다.
3. `mcp_client.py`·public/private MCP server·`pageindex.py`: 현행 API로 본문 선택이 불가능한 경우에만 작은 typed `doc` 선택 인자를 확장한다. public 접근 필터와 `with_text=True` 계약을 유지한다. `mine_aggregate.py`, `mine.rank`, 광산 집계의 단위·정렬·기간 로직은 수정하지 않는다.
4. 테스트: mapper/validator에서 세 intent의 경계, route에서 새 action의 도구 선택, MCP에서 후보만 있는 경우 본문 유무와 public/private 필터, 최종 응답에서 근거 귀속·기권을 검증한다. 반환 근거는 실제 OKF path·절·본문·기준시점과 requirement/action ID를 보존한다.

## 수용 질의

| 질문 | 수용 기준 |
| --- | --- |
| “Kazatomprom 우라늄 광산 정리자료의 JV Inkai 위치는?” | `mine.profile` 또는 명시 문서 `document.lookup`으로 진입. 위 OKF 32행의 위도 45.281·경도 67.536을 해당 행 출처와 함께 제시. 다른 법인 좌표와 혼합하지 않음. |
| “BHP 보고서에서 Escondida 광산은 어느 나라에 있나? 원문도 알려줘.” | `mine.profile`로 진입. `광산자료/동_구리/Cu_Escondida_Pampa_Norte_BHP.md` 33행의 “Escondida in Chile” 근거로 칠레를 답하고 원문 문서/절을 인용. |
| “Kazatomprom 우라늄 광산 위치 알려줘.” | 복수 광산을 하나의 좌표로 합치지 않음. 문서 28~42행의 행별 명칭·좌표를 구별해 제시하거나 어느 광산인지 확인이 필요한 경우 범위를 명시. `mine.rank` 호출 금지. |
| 관련 문서 후보만 있고 해당 사실의 본문이 없거나 public에서 접근 불가 | 후보 제목으로 답을 생성하지 않고 `source_unavailable` 기권. 표·차트·인용 0건. |

## r10f 회귀와 배포

`/tmp/sol_action_eval.py`가 참조하는 평가 XLSX는 현재 작업공간에 없다. 새 재실행 스크립트는 `/tmp/sol-action-full-r10f-260921/Q*.json`의 `request.message`를 질문 원문으로 읽고 동일 `/pubchat` payload를 사용한다. Q23→Q24→Q25는 **새 응답의** `session_id`를 차례로 전달한다. 30개 전부 실행하고 원본 JSON의 답변·`done.abstain_reason`·출처·표·차트와 비교한다. Q01/03/04/07/14/17/23 정상 경로, Q02/05/09/13/25 실데이터 부족 기권, Q30 범위 밖, Q06/10의 기존 `unsupported_combination` 및 나머지 원천 부족 기권을 새 문서 action 때문에 바꾸지 않는다. Q15/Q21/Q22는 원문상 각각 희토류·Nd 데이터 범위, 재활용 역할·한계, HHI/수입의존도/가격변동성 설명이다. r10f에서 이미 `document.retrieve`로 진입했으나 `source_unavailable`이었다. 로컬 PageIndex 직접 조회도 무관 문서만 상위 hit였으므로 새 intent만으로 성공 처리하지 않는다.

코드 반영 뒤 `inhouse/rag_chat/Containerfile`로 새 이미지를 빌드하고 실제 테스트 컨테이너의 이미지 ID·프로세스·코드 해시를 확인한다. PageIndex `load_trees()`는 `lru_cache(maxsize=1)`이고 MCP 세션은 프로세스별 singleton이다. OKF/트리 내용 또는 검색 코드를 바꾼 뒤에는 컨테이너 재시작으로 캐시를 비우고 동일 질문을 재실행한다. `mine.rank` 정상 질문과 단건 광산 위치 질문을 함께 회귀시킨다. 감사는 최대 5회로 제한하고 각 회차에 질문·응답·원문 행·테스트 출력을 남긴다.
