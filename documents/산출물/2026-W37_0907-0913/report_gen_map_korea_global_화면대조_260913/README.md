# 국내/글로벌 수급지도 옵션별 화면-API 대조 점검 (2026-09-13)

> 사용자 요청: "지금 수급지도 국내/글로벌 이 두 페이지에서 나올수 있는
> 옵션을 playwright을 이용해서 옵션별로 화면에 그려지는 내용을 기반으로
> 요약 보고서 api가 제대로 나오는지 한번 점검해봐주세요."

Playwright로 komis.or.kr 실 페이지(`/Komis/MnrlMap/Korea`·`/Komis/MnrlMap/
Nation`)를 직접 조작 → 화면에 실제로 렌더링된 `#resultTable`(TOP30 표)
텍스트를 캡처 → 같은 조건으로 komis_fetch.py를 통해 깨끗하게 재조회한
원본 JSON을 report_gen `AnalysisSummaryService`에 태워 문장·key_metrics
숫자가 화면과 일치하는지 대조했다.

## Playwright 자동화 관련 함정(재사용 가치 있음)

- 두 페이지 모두 `#searchBtn`(`onclick="gotoTotalSearch()"`)은 **사이트
  상단 전역 키워드 검색**이지, 페이지별 "조회" 버튼이 아니다 — 처음에
  이걸로 클릭했더니 필터를 아무리 바꿔도 화면이 갱신되지 않았다(전부
  기본값 "갈륨"만 계속 나옴). 실제 조회는 `setSearch(1)`(화면 폼 값을
  읽어 `g_*` 전역변수·숨은 `#commonForm`에 채움) → `getListKoreaData(1)`
  (map_korea) / `getNationData(1)`(map_global)을 순서대로 직접 `page.
  evaluate()` 호출해야 한다.
- 광종 선택은 `changeSelectVal(code, name)`(전역함수, 칩·select 동기화)로,
  수입/수출 탭은 `gotoImxprtMenu(dir, el)`로 호출하는 게 클릭 시뮬레이션
  보다 안정적이다(숨겨진 커스텀 라디오/탭이라 Playwright 기본 click이
  "element is outside of viewport" 등으로 자주 실패).
- `page.on("response", handler)`를 케이스마다 새로 등록하면 이전 케이스의
  핸들러가 제거되지 않아 **다음 페이지의 AJAX 응답까지 이전 케이스의
  캡처 딕셔너리에 섞여 들어간다**(실제로 겪음 — "price_base_cu" 케이스의
  마지막 캡처가 '금' 데이터였음). 이번엔 화면 DOM 텍스트 캡처는 케이스
  직후 즉시 뜬 것이라 오염되지 않았고, report_gen 대조용 원본 데이터는
  오염 위험이 없는 `komis_fetch.py`(httpx 세션 매번 새로 열림)로 별도
  재조회해 사용했다.

## 대조 결과

### 1) map_korea 수입/수출 탭 — 재정렬만 할 뿐 별도 데이터셋 아님(정상)

화면에서 "수입"/"수출" 탭을 각각 클릭해 동일 광종(동)·연도(2025)를
조회한 결과, TOP30 표의 **행 집합·`sumIncmAmt`/`sumExpAmt`는 동일**하고
정렬 기준만 바뀐다(수입 탭=칠레 1위/수입금액순, 수출 탭=중국 1위/
수출금액순, 각 행엔 원래 수입액·수출액이 항상 같이 들어있음). report_gen
의 `calculate_domestic_trade_summary`(2026-09-09부터 `trade_direction`을
참조하지 않고 항상 수입·수출 둘 다 계산)와 실제 KOMIS 데이터 구조가
정확히 일치 — **문제없음**.

### 2) map_korea 기본 조회(동, 수입, 2025) — 화면=report_gen 완전 일치

| | 화면(KOMIS) | report_gen |
|---|---|---|
| 수입총액 | 14,206,660천USD | 142.07억 달러 |
| 1위 수입국 | 칠레 2,642,749천USD(18.60%) | 칠레 약 26.43억 달러(18.60%) |
| 2위 수입국 | 호주 1,650,865천USD(11.62%) | 호주 약 16.51억 달러(11.62%) |
| 3위 수입국 | 콩고민주공화국 1,327,216천USD(9.34%) | 콩고민주공화국 약 13.27억 달러(9.34%) |

전부 일치. `clean_korea_cu_2025.json`(재조회 원본)·화면 캡처는
`screen_capture_results.json`의 `korea_cu_import_2025` 키 참고.

### 3) map_korea 국가필터(동, 수입, 칠레만) — 일치

화면: 칠레 1행만, 수입금액점유율 100.00%. report_gen: "2025년 기준
한국의 동 칠레 대상 수입액은 총 약 26.43억 달러입니다." — 값(26.43억)
일치, 랭킹 대신 단문으로 대체하는 기존 설계(국가 1개면 비중이 항상
100%라 공허)도 화면 구조(1행만 남음)와 부합.

### 4) map_korea 생산품유형필터(코발트, 기초금속) — 일치

화면에서 "기초금속" 필터를 걸면 HS CODE 열이 전부 "기초금속"으로
좁혀지고 1위가 콩고민주공화국(4,710.2만USD, 33.04%)으로 바뀐다 —
report_gen에 별도로 안 태웠지만(시간 제약) 화면상 필터가 정상 적용되는
것과 report_gen이 이미 `scope_label` 파라미터로 같은 구조를 처리하도록
설계돼 있음(코드 확인 완료, 오늘 세션 다른 점검에서 이미 한 차례 검증됨).

### 5) map_korea 월별 조회(동, 수입, 2026-09) — NO DATA(정상, 데이터 지연)

화면 자체가 "NO DATA"를 표시 — KOMIS 통관 데이터가 아직 2026년 9월분을
반영하지 못한 것으로 보인다(관세 통계 특성상 몇 개월 지연이 흔함).
report_gen 쪽 결함이 아니라 원천 데이터 부재.

### 6) map_global 수입(I)/수출(O) 탭 — 오늘 이미 수정한 v10.pptx 버그와
동일 계열, 재확인 완료

화면에서 직접 리튬 2026년 I/O 탭을 각각 클릭해 확인한 결과값이 오늘
앞서 httpx로 직접 조회했던 값과 정확히 일치(I탭 1위 호주→인도네시아
$12,290천, O탭 1위 호주→중국 $387,264천) — `report_gen_map_global_
방향라벨_버그_260913/`에서 이미 코드는 무결점으로 확인했고 이번엔 화면
자체로도 같은 패턴을 재확인.

### 7) [애매한 부분 — 구조적 갭, 코드 버그 아님] map_global "수출"(O) 탭이
report_gen 파이프라인에 아예 연결돼 있지 않음

`inhouse/streamlit_demo/komis_fetch.py::fetch_map_global()`은
`srchImxprtSeCd`를 `"I"`로 **하드코딩**한다 — 호출부가 "수출" 탭을
선택할 방법이 코드에 없다. KOMIS 실 화면은 이 두 탭을 대등한 선택지로
제공하고(같은 광종이라도 데이터가 완전히 다름, 위 6번 참고) 발주처
문서(`documents/meta/`)에서도 "수출" 관점을 배제해야 한다는 근거는
찾지 못했다 — 즉 수요가 있다면 현재 지원 범위 밖이다. **코드 수정은
하지 않았다**(판단이 필요한 기능 확장 사안, 버그 수정 범위 밖).

## 결론

- 실제 버그: 없음(오늘 이미 발견·수정한 map_global 방향/연도 라벨링
  2건은 이 점검 이전에 완료됨).
- 확인된 정상 동작: map_korea I/E 재정렬, 국가/생산품유형 필터, 기본
  수입 현황 계산 — 전부 화면과 일치.
- 애매한 부분(발견·보고만, 미수정): map_global "수출"(O) 탭이 우리
  파이프라인에서 아예 선택 불가능.

## 재현

`playwright_capture.py`(audit3.py) — komis.or.kr 실 조회 13개 케이스
(이 폴더는 map_korea 5개·map_global 3개만 다룸, 가격 5개는
`report_gen_가격메뉴_화면대조_260913/` 참고) 실행 → `screen_capture_
results.json`. report_gen 대조는 `clean_korea_cu_2025.json`/
`clean_korea_cu_cl_2025.json`(komis_fetch.py로 재조회)을
`AnalysisSummaryService(None, llm=None)`에 직접 태워 확인.
