# 챗봇 MCP komis_raw_lookup public/private 테이블 분류 + 라우팅 버그 수정 (2026-09-01)

## 배경
사용자 요청: 챗봇 MCP의 postgres 도구(`komis_raw_lookup`, `public.KO_*` 9개
테이블 조회)에서 일부 테이블은 public MCP 프로필(`/pubchat`)에서, 일부는
private MCP 프로필(`/prichat`)에서만 조회 가능하도록 분류해달라는 요청으로
시작해, 진행 중 라우팅 버그 발견·수정, 전체 데이터 식별표 작성으로 이어졌다.
worktree-chatbot 세션(코드/문서 작성)과 main-agent(병합·재빌드·재배포·
라이브 재현)가 릴레이로 진행 — 아래 각 항목의 커밋은 모두 main 병합+
`komir-rag-chat` 컨테이너 재배포+실측 검증까지 완료됐다.

## 1. public/private 테이블 분류

| 분류 | page_id | 테이블 |
|---|---|---|
| public | `price_base_metals`/`_minor_metals`/`_iron_energy`/`_other` | KO_MNRL_PRC(광종가격) |
| public | `forecast_price` | KO_MNRL_PRC_PREDC(가격예측) |
| public | `map_korea` | KO_CSTM_CMMRC(관세청_수출입) |
| public | `map_global` | KO_UN_CMMRC(UN_수출입) |
| public | `map_mineral` | KO_RSRC_BURUDG_QUTY(매장량)·KO_RSRC_PRDCTN_QUTY(생산량) |
| **private** | `indicator_market` | KO_MRKT_PRSPECT_IDCT(시장동향지표) |
| **private** | `indicator_supply` | KO_SPDM_STBT_INDX(수급동향지표) |
| **private** | `indicator_composite` | KO_MNRL_SNTHS_INDX(광물종합지수) — 최초 public으로 지정했다가 사용자가 같은 날 정정 |
| 공통(메타) | (page_id 없음, 내부 번역용) | ai_mnrl_mst·ai_prc_mnrl_map(SN-광종간 매핑정보)·ai_hs_mnrl_map(HS코드-광종간 매핑 정보) |

**구현**: `services/shared/retrieval/access.py`에 `PRIVATE_ONLY_KOMIS_PAGES`
상수 신설(기존 Argus 라이선스 제외 상수 `PRIVATE_ONLY_SOURCE_GROUPS`와 같은
파일 — "public/private MCP 프로필 데이터 접근 경계 단일 진리원"). `rag/ragkit/
_mcp_tools_common.py::register_common_tools()`에 `private_only_pages` 인자를
추가해 `komis_raw_lookup` 진입 시 즉시 거부(`{"evidence": [], "warnings":
["'...'는 private 전용 데이터입니다..."]}`). `mcp_server_public.py`만 이
상수를 소스코드로 넘기고 `mcp_server_private.py`는 아예 import하지 않는다 —
기존 `hybrid_search`/`pageindex_lookup`의 "런타임 플래그가 아니라 어느
서버 파일을 실행했는가" 신뢰경계 원칙을 그대로 따랐다.

**검증**: `komir-rag-chat-test` 컨테이너에 stdio MCP 서브프로세스로 직접
호출 — 3개 private page_id 전부 public에서 조회 없이 거부(evidence 0건+
경고), private에서 정상 조회(evidence 1건). 기존 public 페이지(예:
`price_base_metals`)는 회귀 없이 public/private 완전 동일 유지 확인.
`smoke_mcp_access.py`에 회귀 케이스 3건 추가, main-agent가 실컨테이너
재빌드 후 전체 9/9 재확인.

**커밋**: `25b7ad0d9`(indicator_market/supply 도입) → `ba7d8eb74`(indicator_
composite 정정 추가).

## 2. 전체 데이터 식별표(RDB·VectorDB·OKF/PageIndex)

사용자 요청으로 챗봇이 쓰는 4개 데이터원 전체를 public/private/common으로
정리 — `documents/meta/CHATBOT_POSTGRES_MCP_SPEC.md` §0-2에 신설(커밋
`8d66f48af`). 요지: private 전용은 정확히 6곳뿐(RDB의 indicator_market/
supply/composite 3개 + VectorDB·OKF/PageIndex 각각의 `Argus_비철금속_일일`
1개씩), 나머지는 전부 common. RDB 16개 테이블·VectorDB 5개 소스그룹·
OKF/PageIndex 5개 소스그룹 전부 건수/파일수 실측 포함. 부가 발견: VectorDB엔
있는 `documents/산출물` 소스그룹이 OKF/PageIndex엔 없고, 반대로 OKF/
PageIndex의 `기타` 그룹은 VectorDB엔 없음(원인 미조사, 각주로만 남김).

## 3. ROUTE_PROMPT 라우팅 버그 수정

**발견 경위**: main-agent가 위 1번 작업의 라이브 재현("니켈 수급동향지표
알려줘")을 시도하며 라우터가 매번 `komis_raw=False`로 판단하는 것을 관측 —
조사 결과 `chatbot_graph.py::ROUTE_PROMPT`(2026-08-31 `c80a74379`에서
market_outlook/supply_stability topic을 도입할 때 같이 들어간 문구)가
"수급동향지표"·"시장동향지표"라는 표현을 "komis_topic에 없는 합성지수"로
취급해 명시적으로 komis_raw를 끄도록 지침이 걸려 있었다 — 그런데 바로 위에서
정의한 실제 topic 이름은 다른 한글 표현("시장전망지표"/"수급안정지수")이라,
프롬프트 작성자가 스스로 만든 topic의 동의어를 별개 미지원 지표로 착각해
자기가 만든 경로를 자기가 막은 버그였다. 또한 광물종합지수(KO_MNRL_SNTHS_
INDX)는 애초에 komis_topic 항목 자체가 없어 public/private 무관하게 라우팅
경로가 없었다.

**수정**(사용자 승인 후): market_outlook/supply_stability 설명에 동의어
명시, `composite_index` topic 신설(`RetrievalRoute.komis_topic` Literal +
`_KOMIS_TOPIC_TO_PAGE`). "위기지수"(komir 자체 지정학 위기지수, structured의
`geo_index_trend` 담당)는 광물종합지수와 다른 지표라 계속 제외 — 프롬프트에
헷갈리지 말라고 명시.

**검증**: `komir-rag-chat-test`에서 실 LLM 라우터를 직접 호출(스크립트
더블 아님) — "수급동향지표"/"시장동향지표"/"광물종합지수" 3개 문구 전부
정확한 topic으로 `komis_raw=True`, "위기지수"·"가격"은 회귀 없이 기존대로
유지. main-agent가 `smoke_chat_routing.py`(6/6)·`smoke_mcp_access.py`
(9/9) 재실행 + `/pubchat`·`/prichat` 라이브 재현까지 완료 — public은 라우팅은
성공하되 private-only 게이팅으로 정상 거부→dense로 답변, private은 실제
데이터+더미경고 정상 수신.

**커밋**: `c13d9560a`.

## 4. 광물종합지수 광종 미지정 조회 허용

사용자 지시: "광물종합지수는 광종이 없어도 조회 가능하지만 private
모드에서만 조회 가능해야 한다." `KO_MNRL_SNTHS_INDX`는 애초에 광종 필터
컬럼이 없는 테이블인데, `_retrieve_node`가 `komis_mineral_name`이 없으면
`komis_raw` 자체를 안 켜는 공통 규칙 때문에 광종 미지정 질문이 막혀 있었다.
`komis_topic=="composite_index"`만 예외로 분리해 광종 없이도 `page_id=
"indicator_composite"`를 바로 확정하도록 수정(다른 topic은 여전히 광종
필수 유지) — private 전용 게이팅은 별개 축이라 그대로 유지.

**검증**: "광물종합지수 알려줘"(광종 미지정) → `topic=composite_index,
mineral=None`으로 정상 라우팅(수정 전엔 안 켜졌음), public은 여전히 private
전용 거부, private은 실조회 성공. main-agent 재확인: smoke 전체 통과 +
라이브 재현("최근 광물종합지수 수치를 알려줘")으로 `public.KO_MNRL_SNTHS_
INDX` 근거가 실제로 인용되는 것까지 확인.

**커밋**: `d399ef614`.

## 5. 이슈로 남김 — 다단계 대화 교차턴 추론 vs "데이터 조회 우선" 원칙 (미결정)

라이브 재현 과정에서 main-agent가 "광물종합지수 알려줘"(시점 표현 없는 짧은
질문)에서 근거 조회는 성공했는데도 답변 생성 LLM이 스스로 `abstained=true,
reason=ambiguous`로 기권하는 것을 관측했다("최근"이라는 단어를 붙이면
정상 답변됨). 이를 계기로 사용자와 챗봇의 다단계(멀티턴) 대화 처리 방식을
점검했다.

**현재 구조** (`chatbot_graph.py`·`chatbot.py`):
- 라우팅 단계는 최근 4개 메시지+직전 어시스턴트 답변을 라우터 LLM에 줘서
  "그 나라"·"거기"·"그 광종" 같은 대용어를 실제 개체명으로 해소한다
  (`_recent_history`/`_last_assistant_answer`, `HISTORY_WINDOW=4`).
- 답변 생성 단계는 최근 12개 메시지(6턴)를 `[이전 대화]` 블록으로 통째로
  준다(`_history_block`, `MAX_HISTORY_MESSAGES=12`).
- 단, `[이전 대화]` 블록은 **명시적으로 인용 대상이 아니다**로 못박혀
  있다 — "증명 가능한 것만 말하고 나머지는 기권"이 이 챗봇의 핵심 인용
  규율이라, 답변에 들어가는 모든 사실은 **이번 턴에 새로 조회한 [근거]**
  에서만 인용하도록 강제한다.

**애매한 지점**: 문맥 파악(무엇을 묻는지 이해, 대용어 해소)은 다단계로 잘
되지만, "직전 턴에서 이미 답한 수치를 이번 답변에서 재사용해 계산/비교하는"
식의 교차턴 추론(예: "그럼 작년보다 몇 % 늘었어?")은 막혀 있을 가능성이
높다 — 이번 턴에 그 수치를 다시 검색해서 근거로 확보하지 못하면 인용 규율에
걸려 답을 못 하거나 기권한다. 사용자 코멘트: "데이터 조회를 우선으로 하는데
좀 애매하네요" — **매 턴 신선한 근거로만 답변한다는 원칙**과 **다단계
대화에서 이전 턴 정보를 신뢰하고 재사용하는 추론 능력** 사이 우선순위가
명확히 정해지지 않은 상태다.

**검토된 방향(결정 안 됨, 구현 안 함)**:
1. 이전 턴에서 인용됐던 근거를 세션 상태에 캐시해 다음 턴 evidence
   리스트에 다시 포함시킨다 — 인용 규율은 유지하면서 재사용 가능하지만,
   근거 신선도(가격처럼 자주 바뀌는 값)를 어떻게 관리할지 별도 설계 필요.
2. reformulate 단계에서 이전 답변의 핵심 수치/조건을 이번 턴 재질의어에
   포함시켜 "다시 검색"하게 한다 — 인용 규율은 그대로, 매 턴 신선한 근거
   원칙도 유지되지만 왕복 검색 비용이 늘고 정확히 어떤 값을 다시 찾아야
   하는지 판단이 LLM에 맡겨진다.
3. 현행 유지 — 대용어 해소만 다단계로 지원하고, 계산/비교가 필요한 질문은
   사용자가 필요한 숫자를 다시 명시하도록 유도(안내문 개선 정도만 고려).

짧은/모호한 질문에 고정 템플릿 대신 "무엇이 불명확한지" 구체적으로 되묻는
안(`_classify_abstain`/`_abstain_reason_text` 확장)도 같은 대화에서 함께
거론됐으나, 이 역시 결정 보류 — 생성 단계에 LLM 호출이 하나 늘어 지연·비용이
증가하고, "라우팅은 결정적, 생성만 LLM"이라는 기존 설계 원칙과의 균형을
사용자가 먼저 판단해야 한다.

**다음 단계**: 위 3가지 방향 중 하나를 사용자가 결정하면 후속 세션에서
구현 착수.

## 커밋 계보
```
25b7ad0d9  feat(chatbot-mcp): komis_raw_lookup에 private 전용 page_id 2개 도입
ba7d8eb74  fix(chatbot-mcp): 광물종합지수(indicator_composite)도 private 전용으로 정정
8d66f48af  docs: 챗봇 4개 데이터원 전체 public/private/common 식별표 신설(§0-2)
c13d9560a  fix(chatbot): ROUTE_PROMPT의 수급동향지표/시장동향지표 오배제 수정 + 광물종합지수 topic 신설
d399ef614  fix(chatbot): 광물종합지수(composite_index) 광종 미지정 조회 허용
```
전부 worktree-chatbot에서 커밋 → main-agent가 main 병합·`komir-rag-chat`
컨테이너 4회 재빌드/재배포·매 라운드 실측 검증(smoke_mcp_access.py·
smoke_chat_routing.py·`/pubchat`·`/prichat` 라이브 재현)까지 완료.
