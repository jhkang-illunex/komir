# report_gen — 대한민국 수급지도(map_korea) 조회필터 4종 반영 (2026-08-31)

## 배경
사용자 지시(streamlit-agent 경유): "핵심광물지도 > 수급지도 > 대한민국"
페이지에 KOMIS 조회필터 4종(기간구분·국가·생산품유형·HS코드)을 추가하고
"report-summary-agent에 전달해서 보고서 작성에도 사용하게" — streamlit_demo
쪽 KOMIS 실호출은 이미 구현·라이브검증됐고, report_gen이 이 필터들을 어떻게
받아 반영할지는 이 세션에 판단이 위임됐다.

## 실측으로 확정한 설계 근거 2가지
1. **`getListKoreaData`는 요청 파라미터 전부를 응답 최상위에 그대로
   echo한다**(streamlit-agent 라이브 캡처 확인: srchCrtrYmd/srchNtnCd/
   srchMttrFlowCd/srchHsCd 등). 가격페이지 `dataAvg.stdMap`처럼 "조회와
   무관하게 항상 같은 값"이 아니라 진짜 요청 반영 echo다 — 그래서
   price의 `srch_avg_opt`류(새 요청 필드 필수)와 달리 **새 요청 필드가
   필요 없다**, `komis_response` 안에서 다 읽는다. 유일한 예외가
   `mttr_flow_name`(생산품유형 한글 라벨 — 응답 어디에도 없음, 아래 참고).
2. **`sumIncmAmt`/`sumExpAmt`는 "광종 전체 총액"이 아니라 현재 조회
   필터가 적용된 소계다**(streamlit-agent가 필터없음/생산품유형/HS/
   국가 4개 조합을 동일 조건에서 비교해 확정 — 국가필터를 걸면 그
   국가 자체 금액과 정확히 일치, 생산품유형/HS필터를 걸면 그 범위만의
   소계로 줄어듦). 이 사실이 서사 설계를 갈랐다:
   - **국가 단일 필터**: total이 그 국가 자신의 값이라 "1위 수입국
     비중 100%" 같은 공허한 랭킹 문장이 나온다 → 랭킹 claim(top1_country/
     top3/top5_concentration)을 만들지 않고 "{국가} 대상 수입총액은
     X다" 단문으로 대체.
   - **생산품유형/HS 필터**: 국가는 여러 개 그대로 남아 랭킹이 여전히
     의미 있지만, 분모가 광종 전체가 아니라 좁혀진 범위이므로 "전체의"
     → "이 범위 내"로 라벨을 바꿔 오해를 막는다.

## 구현
### 신규 필드 (models.py / routers/analysis.py)
- `mttr_flow_name: str | None`(page_id=map_korea 전용) — `mineral_name`
  선례와 동일한 선택적 라벨 passthrough. 응답에 코드만 있고 한글 라벨이
  없는 유일한 필터라(국가명·HS품목명은 행 데이터에 이미 있음) 호출자가
  KOMIS `getListMttrFlow`로 이미 갖고 있는 라벨을 실어 보낸다(안 보내면
  코드로 폴백).

### 파서/추출 (summary.py)
- `_map_korea_query_filters(komis_response, observations, mttr_flow_name)`
  신설 — echo에서 `(period_unit_label, country_filter_name, scope_label)`
  3종을 뽑는다. 국가필터가 있으면 scope_label은 만들지 않는다(상호배타 —
  국가필터가 랭킹 자체를 억제하므로 범위라벨은 의미 없음). HS코드가
  있으면 생산품유형보다 우선(더 세부 단위라 라벨도 더 구체적).
- `_analyze_domestic_trade`가 이걸 `calculate_domestic_trade_summary`에
  전달, `_respond_trade_map`이 같은 걸 `applied_filters`(period_unit/
  country_filter/scope_filter)에도 노출(보고서 상단 메타데이터 표시용,
  서사 반영과 별개).

### 서사 반영 (komir_summary.py::calculate_domestic_trade_summary)
- `country_filter_name`/`scope_label` 2개 신규 파라미터.
- `current_state`(core_diagnosis) 문장에 필터 접두어 삽입("{국가} 대상"
  또는 "{범위}").
- 국가필터 시: `top1_country` claim id를 재사용해 "조회가 {국가} 한
  국가로 한정돼 있어 ... 전체 금액이다" 단문으로 대체, top3/top5는
  아예 만들지 않는다(claim id 재사용 + major_changes 절이 비지 않게
  유지 — `MAP_KOREA_SUMMARY_INSTRUCTIONS`가 이미 이 id를 "있는 경우"로
  다루고 있어 prompt 문구 변경 없이도 안전).
- 범위필터(생산품유형/HS) 시: 기존 top1/top3/top5 claim 구조는 그대로
  유지하되 "전체의" → "이 범위 내"로 문구만 바꾼다.
- **claim id를 새로 만들지 않고 기존 3개(current_state/top1_country/
  top3_concentration/top5_concentration)를 조건부로 재사용·생략만 해서,
  `MAP_KOREA_SUMMARY_INSTRUCTIONS`·`SECTION_SENTENCE_RANGES` 무변경 —
  이번 배포는 seed_prompts 재실행 불필요.**

## 검증
- pydantic 검증 — `mttr_flow_name`을 map_korea 이외 page_id로 보내면
  거부 확인.
- 실측 기반 합성 테스트(`income_data/komis/komis_06_supply_map_korea.json`
  실제 응답을 변형) 5종 — `AnalysisSummaryService(llm=None).analyze()`
  직접 호출:
  - 필터없음: 기존과 동일한 랭킹 문장 3개 그대로(회귀 없음).
  - 국가필터(대만): "대만 대상 수입총액은 2,429,691이다" + "조회가
    대만 한 국가로 한정돼 있어 ... 전체 금액이다" 1문장만 생성,
    top3/top5 없음 — 의도대로 동작.
  - 생산품유형필터(라벨 없음): "생산품유형코드 001 수입총액은..." +
    랭킹 문장에 "이 범위 내" 라벨 확인.
  - 생산품유형필터(라벨 있음, "기초원료" 전달): "기초원료 수입총액은..."
    확인.
  - HS필터+월별 조합: "HS 2603000000(구리광과 그 정광) 수입총액은...",
    `applied_filters.period_unit`="월별" 확인, itemNm이 행 데이터에서
    정확히 뽑힘.
- 회귀 395콤보(`scripts/komis_dump_smoke_test.py`) mismatch 0 유지
  (기존 덤프는 4개 필터 전부 빈 문자열이라 새 로직이 자연스럽게
  no-op — 회귀 안전).

## 미반영/후속
- `trade_direction` 필드 docstring이 "응답 자체엔 이 선택이 안 드러나
  자동 채움 불가"라고 돼 있는데, 이번 실측으로 `srchIncmExp`도 echo에
  있음이 확인됐다 — 이 필드도 mineral 패턴처럼 자동채움할지는 별도
  판단 필요(이번 사이클 범위 밖, 다음에 이 파일 만질 때 정정 대상으로
  남겨둠).
- map_global(getListDataNation)에는 이번 4개 필터를 확장하지 않았다 —
  사용자 지시가 "대한민국" 페이지 한정이었고 map_global의 echo 여부는
  미검증.

## 커밋
`app/analysis/models.py`·`app/analysis/summary.py`·
`app/analysis/komir_summary.py`·`app/routers/analysis.py` — main-agent
승인 후 재빌드·재기동(seed_prompts 불필요).
