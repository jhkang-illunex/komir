# KOMIS 원본 JSON 붙여넣기 방식 전환 + 검증근거 (2026-08-30)

## 배경

사용자가 UI를 다시 단순화하라고 지시 — streamlit이 komis.or.kr을 직접 호출하는
"실시간 가져오기"(A안)는 이 세션에서 komis.or.kr 자체가 네트워크 레벨로 막혀
있어 이미 취소됐고(라운드6 이전 대화 참고), 대신 **사람이 외부에서 KOMIS를
조회해 얻은 원본 JSON을 사용자가 입력란에 붙여넣는** 방식으로 확정됐다.
report_gen 원칙("prompt 제외 DB/외부호출 없음, 외부에서 입력된 값을 정리·요약")과
정확히 일치한다.

## 변경 사항

1. **geo_events UI 완전 제거** — 라운드6 이전에 별도 expander로 분리했던 것을
   다시 사용자가 "통째로 빼라"고 지시 — `AdvancedJsonField`에서 geo_events
   인스턴스 4개, `geo_event_fields()`/`komis_advanced_fields()` 헬퍼 전부
   삭제. `ADVANCED_JSON_FIELDS`는 이제 price_minor_metals/iron_energy/other의
   `komis_period_comparisons`(실측 부재로 빈 값)만 남았다.
2. **`observations` 수동 JSON 입력란 제거** — price_base_metals·map_korea·
   map_global·map_mineral·indicator_composite·forecast_price 6개 페이지에서
   "우리 자체 스키마" observations textarea를 없앴다.
3. **선택 필드는 그대로 유지** — 광종·기간·measure·trade_direction 등 기존
   위젯은 손대지 않았다.
4. **신규 `inhouse/streamlit_demo/komis_raw.py`** — KOMIS AJAX 원본 응답
   JSON을 report_gen 스키마로 변환하는 페이지별 함수 6개
   (`convert_price_snapshot`·`convert_map_korea`·`convert_map_global`·
   `convert_map_mineral`·`convert_indicator_composite`·`convert_forecast_price`).
   전부 `documents/산출물/2026-W35_0824-0830/report_gen_KOMIS라이브재검증_
   Phase{1,2,3,4}_260829_evidence/`의 실측 원본 구조를 근거로 작성(값을
   지어내지 않는다는 원칙 — 함수 docstring에 출처 명시).
5. **새 text_area 1개**: "KOMIS 데이터 조회 결과(외부에서 조회한 원본 JSON을
   붙여넣으세요)" — 6개 페이지 전부 실측 원본 JSON으로 기본값 prefill(버튼만
   눌러도 동작).
6. price_minor_metals/iron_energy/other·price_group·indicator_market/supply는
   원본 캡처가 없거나(후자 2개는 로그인 필요) 엔드포인트가 확정 안 돼 **기존
   observations 수동 입력 방식 그대로 유지**.

## 변환 로직 세부 — 값을 지어내지 않는다는 원칙과 실측 한계

| 페이지 | 매핑 근거 | 알아둘 한계 |
|---|---|---|
| price_base_metals | `dataAvg.stdMap.CRTRYMD/DAY`→관측치, `.WEEK/MONTH/YEAR`→komis_period_comparisons, `data.defaultMnrl[0].invt`→재고량 | ⚠ `average_price`는 KOMIS의 진짜 "직전완결 기간평균"이 아니라 `commerce_price - flctnPrc`의 역산(수학적으로 flctnPrcnt와 일관됨은 실측 확인) — `report_gen_price_base_metals_부실요약_원인조사_260828.md`에서 밝혀진 대로 KOMIS flctnPrc는 점대점 비교지 기간평균이 아니라서 근사치임을 명시(코드 주석에 반영) |
| map_korea | `list[].incmAmt/incmWeig`(또는 export면 expAmt/expWeig)→관측치, `sumIncmAmt/sumIncmWeig`→komis_trade_totals | 응답에 날짜가 없어 쿼리 파라미터 `srchDateS`를 관측일로 사용 |
| map_global | `list[].amt/weig/incmNtnCd/expNtnCd`→관측치, `sumAmt/sumWeig`→komis_trade_totals | 위와 동일 |
| map_mineral | `data[].burudgQuty`(reserves) 또는 `prdctnQuty`(production), ÷1000으로 "천톤" 환산 | 응답 1건=연도 1개 스냅샷이라 서버 "연도≥2" 요건을 위해 **같은 스냅샷을 두 연도에 복제**(round5와 동일한 정직한 한계) |
| indicator_composite | `data.xaxis`+`data.series`(MNRL/MAJOR/RARE) 시계열 전체 | ⚠ **최신 스냅샷 1건(`dataIndx`)만으로는 NO_DATA** — 실측으로 확인(4건 미만·1주 미만 시차면 실패, 4건 이상이면 성공). 시계열 전체를 쓰도록 설계·prefill도 수정 |
| forecast_price | `data[].crtrPrd`("26년 2Q")→period, `realYn`→is_actual | 원본이 미래→과거 역순이라 시간순으로 뒤집음 |

## 검증 — 12개 page_id "버튼만 클릭" 기준 재검사(임시 8502 인스턴스)

- **1차 시도에서 `indicator_composite`가 NO_DATA로 회귀**(직접 재현 — 최신
  스냅샷 1건만 변환했더니 서버가 거부, curl로 관측치 2건까지도 실패·4건부터
  성공함을 실측 확인) → `xaxis`+`series` 시계열 전체를 쓰도록 변환 함수와
  prefill 예시를 재작성해 해결.
- 재검사 결과: **12개 page_id 전부 status:ok**.
- geo_events 관련 문구가 화면 어디에도 없음을 재확인(`"geo_events" in body`,
  `"지정학 위기지수" in body` 둘 다 False).
- 6개 신규 페이지 전부에서 "observations(JSON 배열)" 옛 캡션이 사라지고
  "KOMIS 데이터 조회 결과" 새 캡션만 노출됨을 확인.
- 에러 처리 확인: JSON 자체가 깨진 경우(`render_json_error` 재사용, "KOMIS
  데이터 조회 결과 JSON 형식이 올바르지 않습니다") / 구조는 유효하지만 필요한
  키가 없는 경우(`KomisRawConversionError`, "KOMIS 원본 JSON 변환 실패: ...")
  둘 다 명확한 한국어 메시지로 구분 확인.
- prompt_admin.py의 "기능 테스트" 섹션도 report_demo.py와 동일한 방식으로
  전환·검증(price_base_metals로 parity 확인).

## 정리한 죽은 코드

- `report_gen_client.py`: `MAP_KOREA_OBSERVATIONS_BY_DIRECTION`(더 이상 참조
  없음 — map_korea가 새 방식으로 전환돼 동적 전환 로직 자체가 불필요해짐),
  geo_events 관련 상수·헬퍼 전부 삭제.
