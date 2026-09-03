# report_gen 구조개선(동시성) + price 주요 요인 계산 로직 — 작업 기록 (2026-08-28)

## 배경
`UIUX_출력_감사_수정루프_상태.md`(라운드1~4) 종료 후, 사용자가 남겨둔 잔여 항목 중
두 건을 실제 작업으로 승인(2026-08-28) — 감사·버그수정 루프가 아니라 기능/구조
작업이라 별도 문서로 기록한다. 담당: report-summary-agent(`worktree-report_gen`).
main-agent는 이번에도 지시·머지·배포·독립검증만 수행, 코드는 안 건드림.

## 작업 A — analysis_lock(Lock) → Semaphore(N) 구조 변경

### 근거(main-agent 사전 조사)
- 현재 `app.state.analysis_lock = threading.Lock()`(`main.py:223`)이 LLM을 쓰는
  분석 요청 전체를 시스템 전역에서 동시 1건으로 강제 직렬화한다
  (`routers/_common.py::run_summary._call()`).
- 그런데 실제 LLM HTTP 클라이언트 `OpenAICompatChat`(`inhouse/geo/llm/openai_compat.py`,
  report_gen·rag_chat·geo 공유)은 `requests.Session`+커넥션풀(`pool_size =
  max(32, concurrency*2)`)로 이미 동시 호출을 지원하도록 설계·실측 튜닝돼 있다
  (코드 주석: "2026-07-08 실측 — 매 호출마다 새 커넥션을 맺으면 처리량이 떨어짐,
  풀링으로 해결"). `LLM_CONCURRENCY=8`도 이 배포 env에 이미 설정됨.
- `AnalysisSummaryService.analyze()`는 `threading.local()`로 스레드별 deadline을
  관리해 애초에 동시 호출을 염두에 뒀고, `prompt_store._cache`도 dict 통째
  스왑이라 락 없이 안전.
- **결론**: 완전 직렬화 락은 원본 이식 코드(ApiRuntime)의 과잉 방어로 보이고,
  기술적 필요성 근거가 없다. Semaphore(N)로 교체해 실제 동시 사용자 대응력을
  높인다.

### 지시 내용(파일: `inhouse/services/report_gen/app/main.py`·`routers/_common.py`
한정, `AnalysisSummaryService` 등 이미 검증된 계산 로직은 건드리지 않음)
1. **N을 실측으로 결정**(추측 금지): 공유 컨테이너를 손대지 말고, 워크트리에서
   격리된 스크립트로 로컬 vLLM(`host.docker.internal:52302`, gemma-4-26b-a4b)에
   동시 1/2/4/8건 부하를 걸어 요청당 지연(p50/p95)을 측정. 20초 요청 예산 안에
   안정적으로 끝나는 최대 N을 고른다(단순히 LLM_CONCURRENCY=8을 그대로 쓰지
   말고 실측으로 검증).
2. **교체**: `Lock()` → `Semaphore(N)`. Python `threading.Semaphore`는 `Lock`과
   동일한 `acquire(timeout=)`/`release()` 시그니처라 `_common.py`의 로직(예산
   공유·포기 처리)은 거의 그대로 유지 가능 — 최소 변경으로.
3. **검증**: (a) 동시 N+1건 요청을 보내 N건은 병렬로 빨리 끝나고 나머지는
   대기/타임아웃 처리가 기존과 같이 정상 동작하는지, (b) 기존 skeptic 감사가
   막아둔 zombie 연쇄(느린 요청 1건이 전체를 막는 것)가 세마포어로도 여전히
   안 생기는지 재현, (c) 기존 회귀 스위트(komis_dump_smoke_test 등) 통과.
4. 근거 기반 원칙 유지: 부하테스트 실측표 + 동시요청 전/후 처리시간 대조를
   남길 것.

## 작업 B — price "주요 요인" 계산 로직 신설

### 근거(main-agent 사전 조사)
- `geo_event` 테이블(`schema_core.sql`)에 이미 `commodity_code`·`obs_date`·
  `country`·`event_type`·`severity`·`evidence_quote`·`source`가 있어, 가격
  관측기간과 겹치는 고severity 이벤트를 뽑아 "동시발생 흐름" 서술이 가능하다.
- report_gen은 prompt 외 DB를 안 읽는 원칙(2026-08-26 사용자 결정, `report_gen_
  prompt_content_260826` 메모리)이라 geo_event도 **요청 바디 새 필드**로 받아야
  한다(기존 `observations`/`compare_observations` 패턴과 동일, 하위호환 유지 —
  필드 없으면 지금처럼 이 절이 비게 됨).

### 지시 내용(파일: `inhouse/services/report_gen/app/analysis/{komir_summary,
models,prompts}.py` 등 price 계열 한정)
1. **먼저 데이터 품질 확인**(설계 전 필수): 5대 핵심광물 중 1~2개로 실제
   `geo_event` 표본(postgres, mineral_risk 스키마)을 가격 관측기간과 겹치게
   조회해 `evidence_quote`·`severity` 분포가 실제로 자연스러운 문장을 만들 수
   있는 품질인지 확인 — 안 되면 설계를 바로 진행하지 말고 보고.
2. **계산 함수 신설**: 가격 관측기간과 겹치는 해당 광종 geo_event 중 severity
   상위 1~2건을 골라 EvidenceClaim 생성. **인과 단정 금지, "동시발생 흐름"
   톤 유지**(이미 프로젝트 전체가 쓰는 원칙 — 챗봇 주의문구·`evidence.py`
   "주요 변동 요인" 라벨과 같은 결) — 예: "조회기간 중 [국가]에서 [이슈] 관련
   사안이 있었다[근거]".
3. **요청 스키마에 선택 필드 추가**: `geo_events`(또는 유사 이름) — 없으면
   기존과 동일 동작(하위호환). `models.py`뿐 아니라 `routers/analysis.py`의
   price 관련 요청 스키마에도 반영(과거 비교광종 작업 때처럼 두 곳 다 안
   고치면 필드가 안 먹힘, `report_gen_prompt_content_260826` 메모리 재발
   방지 포인트 참고).
4. **output_contract/프롬프트 반영**: price 계열 페이지의 "주요 요인" 절을
   이 새 근거가 있을 때만 채우도록.
5. **검증**: 실제 geo_event 표본으로 curl 재현 — "주요 요인" 절이 자연스러운
   문장으로 채워지는지, geo_events 필드 없을 때 기존과 동일하게 빈 채로
   남는지(회귀 없음) 둘 다 확인.

**이번엔 안 함(범위 밖) → 2026-08-28 취소 확정**: `report_demo.py`(스트림릿
데모)가 geo_events를 실제로 채워 보내는 연동은 **사용자가 최종 취소** —
"제공된 데이터 이내로만 작성하는 걸로 끝내세요"(report_gen은 DB를 안 읽고
호출자가 준 데이터로만 작성한다는 기존 원칙 그대로 유지, geo_events 조회
연동을 새로 만들지 않음). 재제안 금지.

## 공통 원칙
- 근거 기반: 추측 금지, 실측표로 남길 것.
- docker rebuild/restart는 main-agent 전담(두 작업 모두 코드 완료 후 커밋만).
- 세션 사용량 애매하면 무리하지 말고 대기.
- 파일 소유권: 이번엔 streamlit-agent·chatbot-agent 작업이 없으니 report_gen
  전체가 report-summary-agent 단독 담당.

## 진행 상태
- [x] 작업A: 부하테스트 실측(N=1~32) → **N=8 채택**(p50/p95 2.5~3.5초 평탄 구간,
  `_EXECUTOR` max_workers=8과 일치해 이중 큐잉 없음) → `Lock()`→`Semaphore(8)`
  교체(커밋 `19b6c9fb4`) → main 머지(FF) → report-gen-test 재빌드
  (`komir-report-gen:260828-semaphore`)+재기동 → **main-agent 직접 검증**:
  단일요청 2.69초 vs 동시4건 병렬 3.15초(순차였다면 ~10.76초) — 실제 병렬 처리
  확인. **완료.**
  - 캐베어(조치 불필요, 인지만): (1) N=8은 report_gen 단독 부하 기준, rag_chat과
    vLLM 공유 시 체감 지연 증가 가능하나 헤드룸 8.5초 있음. (2) comprehensive
    엔드포인트가 같은 세마포어 permit 공유 + permit당 LLM 최대 2회 호출이라
    "동시 8 permit" ≠ "동시 8 LLM 호출"(최대 16 가능) — 새 회귀 아니고 기존
    Lock() 때도 있던 특성.

- [~] 작업B: 1번(데이터 품질 확인) 단계에서 설계 반증 발견 → **main-agent 설계
  결정**(아래) 전달, 계산 함수 구현은 진행 중.

### 작업B 설계 결정(2026-08-28, report-summary-agent 실측 기반 main-agent 확정)

**실측 발견**(report-summary-agent): severity=3.0(최고) 687건 중 84.3%(GDELT,
source 공백)는 `evidence_quote`가 문장이 아니라 URL 슬러그
(`"trump-says-50-per-cent-tariff-on-copper-imports..."`). 한국어 완결문은
source=KOMIS 3.3%뿐, 나머지 8.9%(Argus 등)는 영문 완결문. **severity만으로
상위 1~2건을 뽑아 evidence_quote를 그대로 인용하는 원 설계는 84% 확률로
깨진 텍스트를 노출한다 — 채택 불가.**

**확정 설계**(report-summary-agent 권고안 기반, 선택 로직만 단순화):
1. **선택은 severity만으로**(원래 스펙 그대로, 복합정렬 안 씀) — "가장 심각한
   이벤트"라는 의미를 그대로 유지. 상위 1~2건.
2. **텍스트는 2단 구성**: ① 항상 생성되는 결정론적 한글 템플릿 —
   `direction`(7값 클린 enum)+country+obs_date로 "조회기간 중 [국가]에서
   [방향] 흐름과 맞물린 사안이 있었다(YYYY-MM-DD 기준)." 같은 안전한 문장.
   `event_type`(268종+ 자유서술)은 이번엔 미사용. ② `evidence_quote`는 품질
   휴리스틱(한글 비율+슬러그 패턴 감지)을 통과한 경우에만 템플릿 뒤에
   보강 문구로 추가.
3. 선택된 이벤트의 quote가 품질 휴리스틱을 통과 못 하면 **그냥 템플릿만
   사용**(빈 채로 두지 않음) — severity 의미는 안 깨지고 텍스트 안전성도
   보장됨. compound sort(품질,severity)는 채택 안 함(가장 심각한 이벤트를
   문장 품질 때문에 다른 이벤트로 바꿔치기하면 "주요 요인" 의미가 왜곡될
   수 있어서).

report-summary-agent에게 이 결정 전달, 이어서 진행 요청.

### 작업B 구현·검증 완료(2026-08-28)

**구현**(`9017f80f4`): `GeoEventObservation` 모델 신설(direction 7값만, event_type
268종+ 자유서술은 제외) + 요청 스키마 2곳(`AnalysisSummaryRequest.geo_events`·
`MineralDateRangeSummaryRequest.geo_events`) + page_id 제한(price 4종 외 거부) +
`calculate_price_summary(geo_events=)`가 severity≥2.0 상위 최대 2건에 대해
direction 기반 결정론적 템플릿을 항상 생성, `evidence_quote`는 품질 휴리스틱
(한글 비율≥0.3 + 슬러그 정규식 불일치) 통과 시만 보강 + 프롬프트에 "맞물린"
동시발생 톤·인과단정 금지 지시 반영.

**품질 휴리스틱 검증**(report-summary-agent, severity≥2.0 전체 7,917건 실측):
좋은 출처(KOMIS+PPS) 177건 기준 precision/recall 1.0/1.0, 출처명 하드코딩
없이 텍스트 자체 판별만으로 완벽 재현.

**실측 중 발견·수정한 부수 버그**: `SummaryNarrative.major_changes` 5문장
하드캡을 기존 코드(day_over_day+week/month/year평균+price_streak)가 이미
정확히 채울 수 있는 경계가 있어, geo_events claim을 무조건 추가하면
규칙기반 폴백에서 `ValidationError`로 죽는 걸 재현·확인 → 남은 자리
(5-기존claim수)만큼만 추가하도록 방어(기존 근거 우선, geo_events가 밀려날
수 있음 — main-agent 승인, 뒤집을 필요 없다고 판단).

**main-agent 머지·배포·독립 검증**: main 머지(FF, `9017f80f4`) → report-gen-test
재빌드(`komir-report-gen:260828-geofactors`)+재기동 → 3가지 시나리오 직접
curl 재현:
1. 고품질 인용(한국어 문장) → 템플릿+보강 문구 둘 다 정상 노출
2. 저품질(슬러그) 인용 → 보강 문구 없이 템플릿만 노출(필터링 정상)
3. `geo_events` 필드 없음 → 기존과 완전 동일 동작(회귀 없음)

**결론: 작업A·B 둘 다 완료·검증 종결.** `report_demo.py`(스트림릿) geo_events
연동은 범위 밖으로 남겨둠 — 필요 시 별도 작업.

## 작업C — LLM 정제 실사용률 실측 + price_group 검증기 오적용 수정 (2026-08-28)

### 실측(main-agent, 사용자 질문 계기)
사용자가 "규칙기반이 절반쯤 되는 것 같다"고 지적 → 재배포된 컨테이너에
report_gen_출력품질감사_260828_samples/의 실제 26건을 재전송 + 라운드1이
추가한 `llm_refined` 로그를 집계. **24건 성공 중 True 15(62.5%)·False
9(37.5%)**. page_id별: indicator_market·supply·map_korea·map_mineral은
4/4 전부 True, **price_group과 indicator_composite는 2/2 전부 False**.

### 원인 확정 — price_group (main-agent 코드 확인)
`summary.py::_validate_llm_summary`의 `elif len(claims) >= 4 and not any(len
(sentence.evidence_ids) >= 2 ...)`(근거 결합 문장 요구, SC-018의 그 규칙)가
**모든 page_id에 무차별 적용**된다(`map_mineral`만 별도 분기로 예외). 그런데
`PRICE_GROUP_SUMMARY_INSTRUCTIONS`(prompts.py)는 "group_movers·extreme_movers를
근거에 있는 그대로 옮겨 쓴다"(각 근거를 독립 문장으로) 지시하고, price_group의
`major_changes` 절은 `SECTION_SENTENCE_RANGES`상 최대 2문장뿐 — 근거 4개 이상을
"각자 따로 쓰기" 지시대로 좁은 문장 수 안에 담으면 구조적으로 결합 문장이
나올 수 없다. **매 요청 100% 폴백은 우연이 아니라 예정된 실패였다.**

### 지시 내용(파일: `inhouse/services/report_gen/app/analysis/summary.py`
`_validate_llm_summary` 한정)
1. **price_group — 확정 수정**: "근거 결합 문장 요구" 규칙에서 price_group을
   예외 처리(예: `_COMBINED_SENTENCE_EXEMPT_PAGES = {"price_group"}` 같은
   집합 상수 + `map_mineral`과 별개 조건). "모든 evidence_id를 정확히 한 번씩
   사용" 체크는 그대로 유지(이건 여전히 유효한 안전장치). 공개 `{status,report}`
   계약은 안 건드림 — 순수 내부 검증 로직 수정이라 SC-018(계약변경 보류)과는
   무관하게 바로 진행.
2. **indicator_composite — 원인 조사 먼저**: `calculate_composite_summary`는
   설계상 이미 결합 문장(메이저·희소지수 비교)을 만들도록 돼 있어 price_group과
   같은 구조적 충돌은 아닐 가능성이 높음 — docker exec로
   `indicator_composite_base.json`/`_variant.json`의 실제 request를 다시
   `AnalysisSummaryService`에 태워 `_validate_llm_summary`가 실제로 어떤
   사유 문자열을 반환하는지(claims<4라 애초에 이 규칙이 적용 안 됐는지,
   다른 규칙에 걸렸는지) 확인 후 보고 — 원인 확인 전엔 수정하지 않는다.

### 진행 상태
- [x] price_group 검증기 예외 수정(`0ab793f1c`, `_COMBINED_SENTENCE_EXEMPT_PAGES`)
  → main 머지(FF) → report-gen-test 재빌드(`komir-report-gen:260828-workc`)+재기동
  → **26건 재측정**: True 17/24(70.8%, 이전 62.5%) · False 7/24(29.2%, 이전
  37.5%) — price_group 2/2 False→2/2 True로 정확히 전환, 다른 page_id는 변화
  없음(회귀 없음 확인).
- [x] indicator_composite 폴백 원인 확정(report-summary-agent) — price_group과
  **다른 종류의 문제**: `_analyze_composite`의 게이트
  `if self._llm is None or len(calculated.claims) < 5 or quality_status ==
  "insufficient": return response`에서 **`_refine_with_llm` 진입 자체를 안 함**
  (검증 실패가 아니라 시도 자체를 안 하는 것 — price_group의 "시도했다가
  탈락"과 성격이 다름). base.json(관측치 2건)은 claims=3<5, variant.json
  (관측치 3건)은 claims=8로 충분하지만 quality_status가 observations≥4 조건
  미달로 insufficient. 관측치 4건으로 늘리면 정상 통과 확인(게이트 자체는
  의도대로 동작). **버그 아니라 의도된 최소 데이터 요건**(claims≥5 AND
  observations≥4)이 실제 KOMIS 표본 분포(관측치 2~3건 조회가 드물지 않음)와
  안 맞아 결과적으로 폴백률을 높이는 구조 — 코드는 지시대로 미수정, 문턱을
  낮출지는 사용자 판단 필요 항목으로 보고.
- [x] main-agent: 전체 재측정 완료(위 참고)

**작업C 종결(price_group 수정분).** indicator_composite 문턱(claims≥5 AND
observations≥4)은 **현행 유지로 결정**(2026-08-28, 사용자: "우선은 제공하고
피드백 받아서 고치죠 — 최종결정권자가 내가 아니라서") — 발주처 등 실제
피드백이 오기 전까지 코드 변경 안 함. 재론 시 이 문서의 원인 분석(위 §)부터
확인할 것.
