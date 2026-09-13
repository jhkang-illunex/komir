# META — 요약보고서 데모 메뉴별 옵션·분석요약 생성 결과

## 무엇인가
`inhouse/streamlit_demo/views/report_demo.py`(요약보고서 작성 데모)에 실제로
뜨는 **주메뉴×서브메뉴 10개 케이스** 전부에 대해, (1) 그 메뉴에서 선택 가능한
UI 옵션과 (2) report_gen 분석요약 API를 실제로 호출해 받은 결과를 케이스(메뉴)
단위 md 10개로 정리한 것. 사용자 요청(2026-09-08): "요약 보고서 데모에 있는
모든 페이지에 대해서 주 메뉴와 서브 메뉴로 나올 수 있는 케이스에 대해 옵션과
분석 요약 생성 결과를 메뉴 단위로 md로 만들어 달라".

**2026-09-08 재작성(같은 날 후속 지시)**: "주메뉴 광물자원가격 이하 모든
메뉴에 대해서 기간을 최근 1년으로 해서 다시 md를 작성"— `01_`~`04_`(광물자원가격
4종)만 갱신, `05_`~`10_`(광물전망지표·핵심광물지도)은 최초본 그대로 유지.
이전엔 `komis_raw.py`에 박제된 정적 예시(14영업일)를 그대로 썼지만, 이번엔
`komis_fetch.fetch_price_*`로 komis.or.kr을 **실시간 재조회**(기간 구분자
month, 평균 옵션 DAY, 2025-09~2026-09, 광종당 246~258건)해 report_gen에
넣었다 — 정적 예시가 아니라 이번 실행 시점 실데이터라 값이 최초본과 다르고
(예: 동 최신가 14,490.00→14,540.00), 표본이 늘어나 변동성·이동평균·RSI·
백분위·낙폭 등 최초본에서 "관측치 부족으로 계산하지 않음"이었던 항목까지
채워졌다. 실행 일시: 2026-09-08 19:26 KST(같은 컨테이너·같은 HEAD, 아래
"실행 근거" 참고).

## 범위
`report_gen_client.PAGE_SPECS`에 등록된 10개 page_id 전부. 파일 번호(01~10)
순서는 `komis_menu_map.yaml`의 `komis_site_map`(KOMIS 실제 사이트맵) top-level
키 순서를 직접 읽어 확인한 값 — `[광물자원가격, 광물전망지표, 광종_국가정보,
핵심광물지도]`(광종_국가정보는 이 데모에 없는 메뉴) 그대로:

1. 광물자원가격 > 비철금속(`price_base_metals`)
2. 광물자원가격 > 희소금속(`price_minor_metals`)
3. 광물자원가격 > 철광석 및 에너지(`price_iron_energy`)
4. 광물자원가격 > 기타(`price_other`)
5. 광물전망지표 > 광물종합지수(`indicator_composite`)
6. 광물전망지표 > 시장동향지표(`indicator_market`)
7. 광물전망지표 > 수급동향지표(`indicator_supply`)
8. 핵심광물지도 > 국내 수급지도(수출입)(`map_korea`)
9. 핵심광물지도 > 글로벌 수급지도(원산지→도착지)(`map_global`)
10. 핵심광물지도 > 광물지도(매장량/생산량)(`map_mineral`)

⚠ 이 화면에 없는 2개 page_id는 포함하지 않았다:
- `forecast_price`(가격예측) — report_gen 서버엔 살아있지만(엔드포인트 생존)
  2026-09-01 사용자 지시로 이 데모 화면에서 메뉴 자체를 제거했다.
- `price_group`(그룹 요약, 비철금속/희소금속) — 2026-08-31 사용자 지시로
  report_gen 서버 쪽 **외부 인터페이스 자체가 삭제**돼(`POST /prices/group`이
  404) 이 데모도 같은 결정을 따라 메뉴를 제거했다(코드는 남아 있어 필요 시
  API만 복원 가능한 상태).
`feedback_forecast_price_exclusion_260903` 메모리 참고(문서 재생성마다
재등장했던 이력이 있어 명시).

## 실행 방법(재현 절차)
1. 사전 확인: `komir-report-gen-test` 컨테이너 기동 상태(`curl localhost:18003/healthz` → 200)
2. `inhouse/streamlit_demo/report_gen_client.py`·`komis_raw.py`는 streamlit
   비의존(import만으로 사용 가능) — cwd=`inhouse`에서 두 모듈을 직접 import해
   각 page_id의 `PAGE_SPECS[page_id]`+`KOMIS_RAW_PAGES[page_id].example_raw_json`
   (코드에 이미 박제된 라이브 실측 캡처, 출처는 각 파일 주석)로 UI 기본값과
   동일한 요청 바디를 구성, `ReportGenClient.summarize(page_id, payload)`를
   직접 호출(스크린샷/브라우저 조작 없이 API 레벨로 재현 — streamlit 화면이
   내부적으로 하는 것과 동일한 호출).
3. 광종은 각 page_id의 원본 JSON 예시가 실제로 담고 있는 광종과 일치시켰다
   (UI 자체가 "드롭다운 광종≠JSON 광종이면 섞여 나온다"고 경고하는 함정이라
   반드시 맞춤). 코드는 `public.ai_mnrl_mst`+
   `rag_chat/app/page_recommend/resources/metadata/komis-metadata.snapshot.json`
   직접 조회로 확인(추측 금지 — `data-quantity-verification-rule` 메모리 원칙):
   - 동 MNRL0008, 코발트 MNRL0003, 철 MNRL1011, 금 MNRL0046 — `public.ai_mnrl_mst` 조회
     (`SELECT mnrknd_unq_cd, mnrl_nm_ko FROM public.ai_mnrl_mst WHERE mnrl_nm_ko IN (...)`)
   - 갈륨 MNRL0024 — `map_korea`/`map_global`/`indicator_market`/`indicator_supply`
     예시 JSON의 `srchMnrkndUnqCd`/`chartSpdmStbt.mnrkndUnqCd` 필드에 직접 명시돼
     그대로 사용(별도 조회 불필요)
4. 그 외 옵션(기간·측정지표·비교광종 등)은 화면이 렌더링될 때의 **기본 선택값**
   그대로 사용(기간은 공란, compare_mineral은 미선택, measure=매장량,
   trade_direction=수입, unit=천톤) — 사용자 개입 없이 버튼만 눌러도 나오는
   결과를 재현하는 것이 목적이라 임의 조합 매트릭스는 만들지 않았다.
5. 10건 전부 1차 호출에서 `status: ok` — 재시도 발생 없음.

## 실행 근거(재현 가능하도록 명시)
- 실행 일시: 2026-09-08 19:03 KST
- report_gen 컨테이너: `komir-report-gen-test`(이미지 `komir-report-gen:260908-deep-audit`, 생성 2026-09-07T18:23:31Z), `localhost:18003`
- komir 저장소 HEAD: `702c6c48aabb492c70289058c86c12b1792f1505`
- 원자료 출처: `inhouse/streamlit_demo/komis_raw.py`의 `KOMIS_RAW_PAGES[*].example_raw_json`
  (각 항목이 어느 라이브 캡처 문서에서 왔는지는 그 파일 주석에 명시돼 있음 —
  대부분 `documents/산출물/2026-W35_0824-0830/report_gen_KOMIS라이브재검증_Phase{1,2,3,4}_260829_evidence/`,
  indicator_market/supply는 2026-09-01 발주처 제공 원본)
- 옵션 UI 서술 출처: `inhouse/streamlit_demo/views/report_demo.py`(2026-08-27~09-01 이력) 코드 직접 확인
- 사이트맵 순서 출처: `inhouse/streamlit_demo/komis_menu_map.yaml`(`komis_site_map` 키 순서, 직접 파싱해 확인)

## 파일 목록
`01_`~`10_` 접두 순서 = 화면 주메뉴 정렬(`komis_menu_map.yaml` 사이트맵 순서)
그대로. 각 파일 구성: ①선택 가능한 옵션 ②이번 실행에 쓴 옵션값 ③분석요약
생성 결과(status + report 원문 markdown).

## 주의
- 이 산출물은 **개발 데모(report_demo.py)의 실행 결과 스냅샷**이다 — 운영
  챗봇/report_gen 정식 서빙 경로가 아니라 report_gen API 계약을 직접 확인하는
  용도의 화면이라는 점은 `report_demo.py` 파일 상단 docstring과 동일.
- 값 자체(가격·지수·수입액 등)는 코드에 실려 있는 라이브 실측 캡처 그대로이며,
  캡처 시점(대체로 2026-08-27~09-01)의 스냅샷이다 — "현재" 시황이 아니다.
