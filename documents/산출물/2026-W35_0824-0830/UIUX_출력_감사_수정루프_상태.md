# 프롬프트관리·요약보고서데모·챗봇 감사→수정→재검증 루프 상태

## 개요
- **참여**: streamlit-agent(streamlit_demo UI), report-summary-agent(report_gen 백엔드),
  chatbot-agent(rag_chat 룰 준수) 3개 병렬 세션 + main-agent(조율·머지·배포).
- **루프**: 에이전트가 자기 워크트리에 커밋 → main-agent가 수정 방향 지시 → 수정·커밋 →
  main-agent가 main에 머지+재배포 → main-agent가 재검사 지시 → 반복.
- **종료 조건**: (a) 재검사에서 제외목록 밖의 신규 P0/P1이 없거나, (b) 라운드 5회 도달.
- **세션 리밯 대응**: 각 에이전트에게 "풀릴 때까지 대기 후 이어서 진행" 지시함, main-agent도 동일.
- **근거 기반 원칙(사용자 지시, 2026-08-28 라운드1 도중 추가)**: 감사·수정 전부 실측 근거로
  뒷받침한다. 감사는 추측 대신 재현된 캡처(스크린샷·응답 원문·docker exec 결과)로,
  수정은 "고쳤다"는 주장이 아니라 수정 전/후 대조 재현으로 검증한다. 각 에이전트에게
  라운드1 진행 중 추가 안내 발송 완료 — 이후 라운드 지시에도 계속 포함할 것.
- **세션 사용량 애매 시 대기 옵션(사용자 지시, 2026-08-28 추가)**: 리밋에 걸렸는지
  불확실한 상황에서도 무리하게 진행하지 말고 "일단 대기"를 선택할 수 있음을 각
  에이전트에게 명시. 다음 라운드 지시부터 포함.
- **파일 소유권 원칙(라운드 내내 유지)**: 같은 파일을 두 에이전트가 동시에 고치지 않는다.
  - streamlit-agent 전담: `inhouse/streamlit_demo/**` (report_demo.py·prompt_admin.py·
    report_gen_client.py 포함)
  - report-summary-agent 전담: `inhouse/services/report_gen/**` (additional_summary.py·
    komir_summary.py·report_render.py·routers/** 등)
  - chatbot-agent 전담: `inhouse/rag/ragkit/chatbot.py`·`inhouse/services/rag_chat/**`
- **배포 소유권**: docker rebuild/restart·git merge to main은 main-agent만 수행.
  에이전트는 자기 워크트리 커밋까지만 하고 공유 컨테이너를 직접 재기동하지 않는다
  (라운드1 감사 중 report-gen-test 컨테이너가 다른 세션에 의해 재기동돼 재현 실패한
  사례 있음 — 재발 방지).
- **배포 실측(2026-08-28, 라운드1 착수 전 확인)**:
  - streamlit(:8501, PID 707992)의 cwd는 **main 체크아웃**
    (`/home/nuri/dev/git/ws/mine_ws/komir/inhouse/streamlit_demo`) — worktree가 아님.
    즉 main에 머지되면 streamlit이 파일 변경을 즉시 참조(자동 리로드 또는 재시작 필요,
    라운드마다 재확인).
  - `komir-report-gen-test` 컨테이너는 이미지 `komir-report-gen:260828-structfix`
    (2026-08-27 15:49 빌드) — main 머지 후 **반드시 재빌드** 필요, 재빌드 안 하면
    재검사가 구코드를 검사하는 오류 발생.
  - **캐시 인벤토리(2026-08-28, 사용자 지시로 라운드마다 클리어)**: streamlit_demo는
    `mineral_master.py:32`(광종목록, ttl=300)·`prompt_admin.py:88`(ai_cfg.cfg_prompt,
    ttl=30)·`etl_status.py`(ttl=15/30)·`data_admin.py`(ttl=300) 전부 `@st.cache_data` —
    프로세스 재시작 전엔 TTL 만료까지 구데이터를 보여줄 수 있음. report_gen은
    `prompt_store.py::_cache`(프로세스 전역 dict)·`policy.py::@lru_cache(maxsize=2)` —
    둘 다 프로세스 재시작으로만 완전히 비워짐(reload 엔드포인트는 `_cache`만 갱신,
    `policy.py` lru_cache는 재시작해야 비워짐). **라운드마다 절차**: streamlit
    프로세스 kill+재기동(session_state까지 함께 초기화되는 효과 있음), report-gen-test·
    rag-chat-test(코드 변경 있었으면)는 rebuild 자체가 새 프로세스라 자동으로 비워짐 —
    별도 캐시 클리어 명령 불필요, 다만 재기동 후 정말 새 코드/캐시인지 확인(§실측
    절차 재실행).
  - 워크트리 동기화 상태(라운드1 착수 시점): `worktree-streamlit`은 main과 동일 tip
    (`1822c7fab`). `worktree-report_gen`(`b04ab3091`)은 main보다 7커밋 뒤처짐,
    `worktree-chatbot`(`fb854dbd4`)은 3커밋 뒤처짐 — 두 워크트리 모두 작업 시작 전
    `git merge main` 지시함.

## 제외 목록(구조적으로 이번 루프 범위 밖 — 재보고 불필요, 종료 판정에서 무시)
- price 계열 "가격 변동의 주요 요인" 절 영구 공백 — 계산 레이어가 원인 분해 근거를
  만들지 않는 한 불가([[report_gen_prompt_content_260826]] 기존 확인 갭).
- zombie(analysis_lock) in-flight LLM 호출 1건 강제취소 불가 — 클라이언트 미지원,
  아키텍처 한계(연쇄는 이미 막힘).
- 프롬프트 선택 UI 2단/1단 혼재(목록 expander·기능테스트 드롭다운) — 사용자가 기존에
  "범위 밖"으로 보류 확정한 항목.
- report_gen `main.py` PG_DSN 가드, 죽은 DB 경로 주석 보존 — 사용자가 유지 결정
  ([[report_gen_skeptic_audit_260827]]).
- SC-018의 근본 해법(공개 `{status,report}` 계약 자체를 바꿔 llm_refined 여부 노출) —
  발주처 프론트 계약 변경이 필요해 이번 루프에서 임의로 하지 않음. 대신 **내부 전용
  필드/디버그 헤더 추가(공개 계약 불변)까지만** 진행하고, 계약 확장 여부는 루프 종료 후
  사용자 확인 필요 항목으로 남긴다.
- ~~(2026-08-28 라운드1 후 추가) 고정질문 "니켈 가격추이"·"리튬 수입상위국" —
  새 데이터 필요한 구조적 갭으로 분류했었으나, 사용자 지적으로 재검토 후
  **제외목록에서 제거·라운드3으로 편입**(아래 참고) — page_recommend 레지스트리에
  해당 KOMIS 페이지가 이미 존재해 데이터 문제가 아니라 의도분류(`intent.py`)
  라우팅 문제로 재판정됨.~~
- (2026-08-28 라운드1 후 추가) `documents/산출물/` 내부 진행상황 문서가 public
  챗봇 근거로 노출되는 문제 — `inhouse/ingest/source_policy.py` 등 색인 정책 변경
  필요, 이번 루프 어느 에이전트의 파일 소유권에도 없어 범위 밖(사용자 논의 필요
  항목으로만 기록).
- P2 항목 전반(유형6/7 렌더러 공유, 표시텍스트≠검증텍스트 경계케이스, price
  "주요 요인" 절 공백, zombie 부분해소, 프롬프트 UI 2단/1단 등) — 이번 루프
  종료 판정(신규 P0/P1 유무)에 영향 없음, 재발생해도 재보고 불필요.

## 라운드 1 (2026-08-28 착수)

### streamlit-agent 지시 내용(파일: inhouse/streamlit_demo/**)
1. [P0] report_demo.py — observations JSON 파싱 실패 시 `st.session_state["report_demo_result"]`
   를 None으로 초기화(§3.1 원문 참고).
2. [P1] report_demo.py·prompt_admin.py 공통 — JSON 파싱 실패 메시지에 사용자 친화적 한 줄 요약
   + 원문은 expander로 접기(§3.2/§4.2).
3. [P1] report_gen_client.py `PageSpec.extra_fields` 한글 라벨 매핑 추가
   (measure/trade_direction/forecast_horizon/price_group 등, §3.3).
4. [P1] report_demo.py — `compare_mineral`을 기존 `_mineral_picker` 드롭다운으로 교체(§3.4).
5. [P1] prompt_admin.py — content textarea 근처에 required-evidence 설계 특성 안내 문구
   추가(§4.4, description 필드 "⚠ 참고용 메모" 톤 재사용).
6. [P1] report_demo.py·prompt_admin.py 공통 — 리포트 렌더링 최상위 헤딩 레벨 조정
   (`# ` → `### ` 등) 또는 컨테이너 테두리(§3.5).
7. [P1, report-summary-agent 감사에서 이관] `report_gen_client.py::PAGE_SPECS["map_mineral"]
   .observations_example`을 연도 1개→2개 이상으로 교체(서버 최소요건 충족).
8. [P1, report-summary-agent 감사에서 이관] `forecast_horizon="long"` 선택 시 기간 필드가
   연도(YYYY) 형식이어야 함을 placeholder 분기 또는 캡션으로 안내.
9. [P2, 여유 있으면] 광종 드롭다운 기본값 5대 핵심광물 중 하나로, reload 성공 메시지
   자연어화.

### report-summary-agent 지시 내용(파일: inhouse/services/report_gen/**, 백엔드만)
1. [P1] `additional_summary.py:511,560,602` 대조 접속사("반면"/"-지만") 오용 — 두 change
   값의 부호(같은 방향인지)를 비교해 같으면 순접, 다르면 역접을 고르는 조건 분기 추가.
2. [P1, 계약 불변 범위로 한정] SC-018 — 규칙기반 폴백 여부를 **공개 {status,report} 계약은
   그대로 두고** 내부 전용 필드/로그로만 노출(예: 관리자 헤더, 또는 서버 로그 강화) —
   공개 API 스키마 변경 금지, 변경 필요하면 코드 대신 "다음 주 논의 필요" 항목으로 기록만.
2. [P2] SC-016 — `## 참고` 절의 검증기/계산기 내부 사유 노출 제거 또는 완화.
3. [P2] `komir_summary.py:329-341` `_avg_before` — 관측치 희소 시 30일/365일 창이 같은
   단일 관측치로 수렴하면 중복 인용(전월평균/전년평균 두 문장)하지 않도록 통합 또는 안내.

### chatbot-agent 지시 내용(파일: inhouse/rag/ragkit/chatbot.py·inhouse/services/shared/retrieval/evidence.py)
감사 완료·커밋(`0c8f1ead1`, main 1822c7fab 위에 FF). 도입부 고정질문 4개 중 3개 실패,
유형8 사유분류 사실상 미작동이 핵심 발견.
1. [P0] 도입부 고정질문 3/4 실패("가격 추이"·"수입 상위국"·"지표 변화" 계열) —
   `chatbot_graph.py` 도구 선택 로직이 이 질문 유형에서 왜 정형 시계열 도구를 안 쓰는지
   먼저 추적. **범위 한정**: 라우팅/키워드매칭 버그면 고치고, 새 데이터 커넥터·파이프라인이
   필요한 구조적 갭이면 고치지 말고 main-agent에 보고만(신규 기능 개발은 이 루프 범위 밖).
2. [P0] 유형8 "질문모호" 가드 부재 — "가격 알려줘"처럼 광종 미지정 질문이 범위 밖 광종
   (금·인듐 등) 데이터로 답변되는 문제. 5개 지원 광종(CU/NI/CO/LI/REE) 화이트리스트 가드 +
   광종 미지정 시 되묻기 로직 추가.
3. [P0, 의도적 스코프 확장으로 진행] `_classify_abstain` 호출 조건을 evidence=0 전용에서
   "생성 결과가 ABSTAIN_TEXT인 경우"까지 확장(`chatbot.py:47-49` 기존 "과잉분류 금지"
   주석은 이번 실측 근거로 재검토된 것 — 주석도 갱신).
4. [P1] `_caution_notice`(chatbot.py:335) 트리거 조건 확장 — structured(`latest_diagnosis`)
   단독 인용에도 "인과 단정 아님" 문구가 붙도록.
5. [P1] `evidence.py:77`의 "사유:" 라벨을 "주요 변동 요인" 등으로 순화(인과 단정 인상 완화,
   4번과 세트 처리 시 근본 해결).
6. [P1] `_citation_sources()`(chatbot.py:302)가 `cited_indices`로 필터링 안 해 미인용
   evidence까지 `done.citations`에 노출 — `_source_footer`와 동일 기준으로 필터링하거나
   `cited` 플래그 추가.

**이번 라운드에서 하지 말 것 / 사용자 논의로 남길 것**:
- `documents/산출물/` 내부 진행상황 문서가 public RAG 근거로 잡히는 문제(P1 #7) —
  `inhouse/ingest/source_policy.py` 등 색인 정책 변경이 필요해 당신 전담 파일 밖.
  코드 수정 없이 "다음 주 논의 필요" 항목으로만 기록.
- P2(유형6/7 렌더러 공유, 표시텍스트≠검증텍스트 경계케이스)는 이번 라운드 생략, 재발생 시
  다음 라운드에 재평가.
- docker rebuild/restart는 하지 마세요(main-agent 전담).

수정 다 끝나면 워크트리에 커밋하고 저에게 보고해주세요. 세션 리밋 걸리면 대기 후 이어서
진행해주세요.

### 진행 상태
- [x] streamlit-agent 라운드1 수정 완료·커밋(`03da27ca9` 감사문서, `c78253ff1` 수정 9건,
  본인이 임시 8502 포트로 수정 전/후 대조 스크린샷까지 남김)
- [x] report-summary-agent 라운드1 수정 완료·커밋(`7a8650eaa` 감사문서, `5c4e52947` 수정 4건,
  docker exec로 수정 전/후 대조 근거 남김)
- [x] chatbot-agent 라운드1 감사 결과 수신(커밋 `0c8f1ead1`) → 수정 지시 발송
- [ ] chatbot-agent 라운드1 수정 완료·커밋
- [x] main-agent: streamlit·report_gen 2개 브랜치 main 머지 완료(`c78253ff1` FF,
  이어서 report_gen ort-merge) — chatbot 머지는 수정 완료 후 진행
- [x] main-agent: streamlit 프로세스 재기동 완료(구PID 707992→신PID 812634, cwd 확인,
  curl 200 확인 — st.cache_data 캐시도 재기동으로 클리어됨)
- [x] main-agent: report-gen-test 컨테이너 재빌드+재기동 완료(`komir-report-gen:260828-round1`,
  기존 env 그대로 재구성, `docker inspect`로 이미지 태그 갱신 확인 — prompt_store._cache·
  policy.py lru_cache도 새 프로세스라 클리어됨)
- [x] main-agent: report_gen 수정 4건 전부 직접 curl로 재현·검증 완료 —
  (1) indicator_composite "내리고"(순접) 확인, (2) map_mineral "## 참고" 절 사라짐 확인,
  (3) 손 안 댄 price_base_metals 회귀 없음 확인, (4) 관측치 희소 시 전월평균만 남고
  전년평균 중복 안 됨 확인. report_gen 라운드1 = **main-agent 독립 검증으로 종결**.
- [x] main-agent: streamlit-agent 수정 스크린샷 스팟체크 2건(A2 h1컨테이너, A3 P0수정)
  — 주장과 실제 스크린샷 일치 확인. streamlit 라운드1 = **검증 완료**.
- [x] main-agent: chatbot-agent 라운드1 수정(`ef2003058`) 코드리뷰(chatbot.py·
  evidence.py 전체 diff) → main 머지 → rag-chat-test 컨테이너 재빌드
  (`komir-rag-chat:260828-round1`)+재기동(기존 env·bind mount 2개 그대로 재구성)
- [x] main-agent: chatbot 수정 3건 직접 curl(SSE)로 재현·검증 완료 —
  (1) "가격 알려줘"(광종 미지정) → `abstain_reason:"ambiguous"`+되묻기 문구 확인
  (P0-2/P0-3 화이트리스트+사유분류 라이브 확인), (2) "코발트 수급동향지표 등급이
  왜 주의로 바뀌었어?" → "주요 변동 요인은"(구 "사유:") + 주의문구 정상 발동(구조화
  단독 인용에도) + 출처 1건만 정확히 노출(P1 3건 전부 라이브 확인). "니켈 관련주
  사도 될까?" 재현은 이번엔 abstain 자체가 안 걸림(citations 1건으로 정상 응답) —
  chatbot-agent가 이미 보고한 verify단계 비결정성과 일치, 회귀 아님.
- **결론: streamlit·report_gen 도메인 = 라운드1로 종결(재검사에서 제외목록 밖
  신규 P0/P1 없음 확인). chatbot 도메인만 라운드2 진행** — P0-1에서 발견된
  `chatbot_graph.py` verify 2차 호출 JSON 잘림 버그(`Unterminated string`,
  max_tokens 부족 추정)가 유일한 실사용 가능 잔여 항목.

## 라운드 2 (chatbot-agent 전용, 2026-08-28)

### chatbot-agent 지시 내용(파일: inhouse/rag/ragkit/chatbot_graph.py — 이번 1건
한정으로 파일 소유권 확장, 근거: 본인이 라운드1 조사에서 직접 발견·보고)
1. [P0] verify 2차 호출이 JSON을 자르며(`Unterminated string`) 실패 → reformulate
   반복 → 완전기권("코발트 광물종합지표의 최근 12개월 변화를 보여줘" 등 재현).
   `max_tokens=150` 등 verify 단계 호출의 토큰 상한이 실제 응답 길이보다 작은지
   먼저 실측 확인 후, 부족하면 상한을 늘려 재현 여부 확인.

**근거 기반 원칙 유지**: 원인을 실측(로그·트레이스)으로 먼저 확정한 뒤 수정,
수정 후엔 같은 질문을 재실행해 완전기권이 near-miss/정상응답으로 바뀌는지
대조 근거를 남길 것. 비결정성이 있는 경로라 언급했으니(라운드1 보고 참고)
3회 이상 반복 재현해 안정성도 같이 확인.

**하지 말 것**: 구조적 갭 2건(니켈 가격추이 구조화 템플릿 부재, 리튬 수입상위국
데이터 부재)은 제외목록에 등재 완료 — 재시도 금지. docker rebuild/restart는
main-agent 전담.

세션 사용량 애매하면 무리하지 말고 대기 후 재개.

### 진행 상태
- [x] chatbot-agent 라운드2 수정 완료·커밋(`d11b7af2f`) — `_verify_node` max_tokens
  150→300. 원인 실측(6회 중 4회 재현, finish_reason="length"+completion_tokens=150
  정확히 일치 — JSON 포맷 버그 아니라 순수 토큰 상한 부족으로 확정), 수정 후 10회
  재현 0/10 재발 확인.
- [x] main-agent: 머지(`d11b7af2f`) → rag-chat-test 컨테이너 재빌드
  (`komir-rag-chat:260828-round2`)+재기동 완료
- [x] main-agent: 실제 배포 컨테이너에 "코발트 광물종합지표의 최근 12개월 변화를
  보여줘" 3회 직접 재현 — 결과는 매번 다르지만(정상응답/분류된 기권+안내문구/
  near-miss+대안제시) 구버그 패턴("제공된 문서에서 근거를 찾지 못했습니다"만
  달랑 나오고 안내·대안 전혀 없는 완전기권)은 3회 전부 재현 안 됨 → **수정 확인**.

## 루프 종료 (2026-08-28, 라운드2로 종결 — 5라운드 한도 안 씀)

3개 도메인(streamlit_demo·report_gen·chatbot) 전부 감사→수정→머지→배포→
main-agent 독립 재검증까지 완료. 재검사에서 제외목록 밖 신규 P0/P1 없음 —
종료 조건 (a) 충족으로 루프 종결.

**최종 커밋(main)**: `c78253ff1`(streamlit)·report_gen ort-merge·`ef2003058`+
`d11b7af2f`(chatbot) 전부 main에 반영됨. 3개 컨테이너/프로세스(streamlit:8501,
report-gen-test:18003, rag-chat-test:18002) 전부 최신 코드로 재기동·검증 완료.

**이번 루프에서 다루지 않은 잔여(위 제외 목록 참고, 사용자 논의 필요)**:
- price 계열 "주요 요인" 절 공백, zombie 부분해소, SC-018 계약 확장 여부
- `documents/산출물` 내부문서 public 노출(색인 정책 변경 필요)
- 프롬프트 선택 UI 2단/1단 통일 여부(기존 보류 결정)

## 라운드 3 (2026-08-28, 루프 재개 — 사용자 지적으로 착수)

**계기**: 사용자가 "니켈이나 구리 같은 광종의 가격은 안내 페이지로 해결되지
않나요?"라고 질문 — 라운드1에서 "새 데이터가 필요한 구조적 갭"으로 분류했던
고정질문 2건을 재검토하게 됨.

**main-agent 사전 조사(근거)**: `inhouse/services/rag_chat/app/page_recommend/
resources/registry/pages/`를 확인한 결과, **두 페이지가 이미 정확히 존재**함 —
`price_base_metals.yaml`(use_when: "비철금속의 과거 가격 시계열을 찾을 때",
example_queries에 "최근 동 LME CASH 가격 추이를 보고 싶어" — 고정질문과 표현
거의 동일)·`map_korea.yaml`(use_when: "한국이 특정 광물을 어느 국가에서 얼마나
수입하거나 수출하는지 볼 때... 국가별 교역 금액·중량·점유율·순위"). 즉
page_recommend 기능 자체는 이미 이 질문들을 정확히 답할 수 있는 페이지를
갖고 있다 — 문제는 상류의 `inhouse/services/rag_chat/app/intent.py::
classify_intent()`가 이 질문들을 "document"(문서 Q&A)로 잘못 분류해 애초에
page_recommend로 안 보내는 것. `INTENT_PROMPT`의 document 예시("니켈 2025년
수입량 추이 **설명해줘**")와 고정질문("니켈 가격 추이를 **보여줘**")이 표현상
비슷해 오분류 개연성이 높음. **재판정: 새 데이터가 필요한 구조적 갭이 아니라
의도분류 라우팅 문제로 정정, 제외목록에서 제거.**

### chatbot-agent 지시 내용(파일: `inhouse/services/rag_chat/app/intent.py` —
이번 건 한정 파일 소유권 확장)
1. **먼저 근거 확보**: 아래 두 질문(및 유사 변형 2~3개)을 `classify_intent()`에
   직접 넣어(또는 실제 컨테이너 로그·`mode` 응답 필드로) 정말 "document"로
   분류되는지 확인. 함께 기존 document/page 예시 질문들도 재분류시켜 현재
   분류기의 정확한 경계를 파악.
   - "최근 1년간 니켈 가격 추이를 보여줘"
   - "한국의 리튬 수입 상위국과 국가별 비중을 알려줘"
2. **수정 방향(권장, 최종 표현은 위 근거 확보 후 판단)**: `INTENT_PROMPT`의
   page/document 구분 기준을 "화면·메뉴 위치를 묻는가"에서 "**정확한 수치·표·
   그래프 데이터 조회를 원하는가(page) vs 배경·원인·해석 서술을 원하는가
   (document)**"로 보강 — 위 두 고정질문을 page 예시에 추가하는 정도의 최소
   변경으로 시작. **주의**: "니켈 2025년 수입량 추이 **설명해줘**"처럼 기존
   document 예시는 그대로 document를 유지해야 함(회귀 금지) — "보여줘/알려줘"
   (수치 조회)와 "설명해줘/원인" (서술 요청)의 구분이 핵심이니 이 경계를
   흐리지 않게 예시를 신중히 추가할 것.
3. **회귀 확인 필수**: 수정 후 기존 INTENT_PROMPT의 document·page 예시 질문
   전부(각 3개씩) + 위 2개 고정질문을 재분류시켜 표로 대조 — 기존 예시가
   전부 원래 분류를 유지하는지, 목표 2건이 page로 바뀌는지 확인.
4. **최종 검증**: 실제 배포(재빌드 전이라 워크트리 격리 프로세스로) `/pubchat`에
   두 고정질문을 보내 `mode`가 실제로 page_recommend 경로를 타고, 응답이
   `price_base_metals`/`map_korea` 페이지로 정확히 안내하는지 확인.

**근거 기반 원칙 유지**: 추측으로 프롬프트만 고치고 끝내지 말고, 위 1·3·4
단계의 실측 대조표를 남길 것. 세션 사용량 애매하면 무리하지 말고 대기.
docker rebuild/restart는 main-agent 전담.

### 진행 상태
- [x] chatbot-agent 라운드3 수정 완료·커밋(`cb8b78ca4`) — INTENT_PROMPT 기준 확장,
  14케이스 3회 반복 회귀 없음 확인
- [x] main-agent: 머지 → rag-chat-test 재빌드(`komir-rag-chat:260828-round3`)+재기동
- [x] main-agent: 목표 2건 라이브 재현 — "니켈 가격 추이" → price_base_metals 정확
  추천, "리튬 수입상위국" → map_korea 정확 추천, 회귀 예시("코발트 공급위기
  원인이 뭐야?")는 document 유지 확인
- [x] **main-agent: 회귀 발견** — chatbot-agent가 부수관찰로 보고한 고정질문#3
  ("코발트 광물종합지표의 최근 12개월 변화를 보여줘") 재라우팅을 직접 3회
  재현 → **3/3 전부 `price_minor_metals`(개별 가격 페이지)로 오추천** — 종합지표
  (composite index)와 무관한 페이지. 라운드2 배포 직후 같은 질문을 3회 테스트했을
  때는(§라운드2 진행상태 기록) 전부 document 경로였고 결과가 정상응답/분류된
  기권/near-miss 3갈래로 갈리되 전부 합리적이었다 — **라운드3이 이미 라운드1+2로
  고쳐놓은 고정질문#3의 동작을 page_recommend 오추천으로 되돌리는 회귀**로 확정.

## 라운드 4 (2026-08-28, 라운드3 회귀 수정)

**문제**: `indicator_composite.yaml`(광물종합지수 페이지)이 레지스트리에 이미
있는데도 page_recommend의 페이지 선택 로직(`page_recommend/graph.py` 소관,
이번 루프 범위 밖)이 "코발트 광물종합지표…보여줘"를 `price_minor_metals`로
잘못 고른다. graph.py 페이지선택을 고치는 건 범위 확장이 크고 검증 부담도
커서, **더 보수적인 처방으로 intent.py 쪽에서 막는다** — 고정질문#3은 이미
라운드1+2로 document 경로에서 잘 동작하고 있었으니 그 동작을 그대로 지킨다.

### chatbot-agent 지시 내용(파일: 계속 `intent.py`만)
1. 회귀 재확인: "코발트 광물종합지표의 최근 12개월 변화를 보여줘"를 지금
   `classify_intent()`에 넣어 page로 나오는지 직접 확인(제가 이미 라이브로
   3/3 확인했지만, 원인 파악을 위해 직접 재현 요청).
2. 수정: `INTENT_PROMPT`에 "종합지표·위기지수·수급동향지표·시장동향지표처럼
   여러 지표를 합성·가공한 지수는 원자료 조회가 아니라 산출 배경까지 설명이
   필요하므로 '보여줘/알려줘'여도 document"라는 예외 규칙 추가 + 위 고정질문을
   document 예시에 명시적으로 추가(라운드3에서 page 신호로 넓힌 "보여줘/알려줘"
   동사 규칙의 예외 케이스로 문서화).
3. 회귀 대조표 갱신: 라운드3의 14케이스 + 고정질문#3 변형(예: "니켈 광물종합지수
   추이", "수급동향지표 등급 보여줘")까지 포함해 재분류 — **라운드3에서 되찾은
   2건(가격추이·수입상위국)은 여전히 page 유지**되는지, **고정질문#3류는 다시
   document로 돌아가는지** 둘 다 확인.
4. 최종 확인: 격리 프로세스로 "코발트 광물종합지표…" 3회 재현 → document 경로로
   돌아가 라운드2 검증 때와 같은 패턴(정상/분류된기권/near-miss 중 하나)이 나오는지.

**하지 말 것**: `page_recommend/graph.py` 페이지 선택 로직은 건드리지 않는다
(이번에도 범위 밖 — 고정질문#4 "희토류 생산량·매장량"이 `map_mineral`로 잘
추천된 건 그대로 두고, "종합지표"류만 document로 되돌리는 선에서 처리).

세션 사용량 애매하면 대기. docker rebuild/restart는 main-agent 전담.

### 진행 상태
- [x] chatbot-agent 라운드4 수정 완료·커밋(`69d008442`) — 예외 규칙 추가 +
  커밋 전 자체 재검증으로 룰 원문 예시 2건(유형6·유형7) 추가 회귀까지 발견해
  "예외의 예외"로 선제 수정, 22케이스×3회 반복 전부 일치
- [x] main-agent: 머지 → rag-chat-test 재빌드(`komir-rag-chat:260828-round4`)+재기동
- [x] main-agent: 라이브 3건 재검증 — "코발트 광물종합지표…" document 복귀(회귀
  해소) + "니켈 가격추이" page 유지 + "니켈 수급동향지표 전체 데이터" page/
  indicator_supply 유지(원 감사 판정과 동일) — 전부 기대대로.

**루프 최종 종료(라운드4)**: 3개 도메인 + 챗봇 라우팅 회귀까지 전부 수정·
검증 완료. 신규 P0/P1 없음.
