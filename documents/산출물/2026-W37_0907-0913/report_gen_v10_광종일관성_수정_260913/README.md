# v10.pptx 광종 일관성 수정 (2026-09-13)

> 사용자 지적: "테스트 사이트 정리한 슬라이드에 광종은 고정하고 옵션을
> 바꿔야 제대로 적용된건지 알죠, 광종이랑 옵션 다 바꾸면 제대로 파악이
> 안됨"

옵션(비교광종·필터·수출입방향 등)의 효과를 보여주려면 baseline 슬라이드와
옵션-변형 슬라이드가 **같은 광종**이어야 한다(광종까지 같이 바뀌면 결과
차이가 옵션 때문인지 광종 때문인지 구분이 안 됨). v10.pptx 전체를 점검한
결과 22개 슬라이드 중 4개가 이 원칙을 어기고 있었다 — 전부 같은 baseline
광종으로 재구성했다(전부 실제 report_gen 호출 결과, 손입력 없음).

## 발견된 불일치 4건

| 슬라이드 | baseline 광종 | 기존(불일치) | 수정 후 |
|---|---|---|---|
| 비철금속(비교광종 추가) | 동(슬라이드2) | 아연 vs 알루미늄 | **동 vs 니켈** |
| 희소금속(비교광종 추가) | 코발트(슬라이드4) | 텅스텐 vs 몰리브덴 | **코발트 vs 몰리브덴** |
| 국내수급지도(생산품유형 필터) | 동(슬라이드13) | 코발트 | **동(기초금속)** |
| 글로벌수급지도(수출입국가 옵션) | 리튬(슬라이드16) | 동 | **리튬** |

(철에너지·기타 가격 비교슬라이드, 국내수급지도 국가필터, 광물지도
교차비교/생산량슬라이드는 이미 baseline과 광종이 일치해 손대지 않았다.)

## 데이터 출처

- **동 vs 니켈**(비철금속): 정적 덤프 `income_data/komis/
  komis_01_base_metals.json`의 `동|LME CASH|DAY`+`니켈|LME CASH|DAY`를
  KOMIS 실제 비교광종 응답 모양으로 합성(기존 비교광종 검증 세션과 동일
  규칙, `report_gen_비교광종_확인_260913/README.md` 참고) → report_gen
  실호출(`price_base_cu_ni.json`).
- **코발트 vs 몰리브덴**(희소금속): 같은 방식,
  `income_data/komis/komis_02_minor_metals.json`의 `코발트|Cobalt
  Metal|99.8|DAY`+`몰리브덴|Ferro-molybdenum|60|DAY` (`price_minor_co_mo.json`).
  코발트 실거래가(53.46달러)가 2010-07-02 시작가(42.85달러)와 정확히
  일치해 올바른 가격기준(baseline과 동일)임을 재확인.
- **동(기초금속)**(국내수급지도): 정적 덤프에 동+생산품유형 조합 캡처가
  없어 komis.or.kr을 직접 라이브 조회(`komis_fetch.fetch_map_korea(
  'MNRL0008', product_type_code='002', ...)`, `cu_map_korea_scope.json`)
  → report_gen 실호출(`cu_map_korea_scope_verified.json`).
- **리튬**(글로벌수급지도 수출입국가옵션): 오늘 슬라이드16 재조회 때 이미
  받아둔 라이브 데이터(`komis_route_share_response`용 `nation_map`)를
  재사용 — 별도 재조회 없이 report_gen에
  `komis_route_share_response`만 추가해 실호출(`li_2026_map_global_
  route_share_verified.json`). 슬라이드16(수입)·17(수출)·18(수입+옵션
  상세) 세 슬라이드가 이제 전부 리튬·2026으로 일관됨.

## 검증

- 표·본문 수치는 report_gen 응답 JSON에서 그대로 옮김(재타이핑 없음).
- zip 무결성(`testzip()` None)·재오픈·red-run 0건 확인.

## ⚠ 정정(2026-09-13, 사용자 지적으로 발견) — 숫자서식 버그는 API가 아니라 이 슬라이드 빌드 스크립트 문제였다

처음 이 4개 슬라이드를 만들 때 표 셀 숫자서식 함수가 `"{:,.0f}"`(항상
정수)를 써서 코발트 현재가 53.46이 "53"으로, 동 최고가 14850.0이
"14,850.00"으로 잘못 나왔다. **report_gen API 응답(`key_metrics.value`)
은 처음부터 53.46/14850.0으로 정확했다 — API 버그가 아니라 이 슬라이드를
만드는 파이썬 스크립트의 서식 함수 버그였다.**

발견 당시 이 2개 슬라이드 표 셀만 별도 커맨드로 직접 고쳤는데, 이건
"슬라이드는 report_gen 결과물을 복붙만 해야 한다"는 원칙을 어긴 것이었다
(사용자 지적: "슬라이드는 결과물을 복붙만 해야지 고치면 안되요") —
산출물을 손으로 땜빵하고 빌드 스크립트 자체는 안 고친 상태였다.

**재조치**: `fix_v10_mineral_consistency.py`(슬라이드3·5만 다루던 구
스크립트, 참고용으로 남김)를 폐기하고, 서식 함수(`smart_fmt`)를 제대로
박아 넣은 `rebuild_v10_mineral_consistency_final.py` 하나로 4개 슬라이드
(3·5·15·18) 전부를 **이 evidence 폴더의 report_gen 응답 JSON에서 처음부터
다시 생성**했다 — 이후 이 스크립트 밖에서 슬라이드 텍스트/표 값을 손으로
고치지 않는다.

## 재현

`rebuild_v10_mineral_consistency_final.py`(4개 슬라이드 전부 이 스크립트
하나로) + 이 폴더의 report_gen 응답 JSON 4개(`price_base_cu_ni.json`·
`price_minor_co_mo.json`·`cu_map_korea_scope_verified.json`·
`li_2026_map_global_route_share_verified.json`)가 입력.
