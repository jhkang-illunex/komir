# KOMIS 라이브 재검증 Phase 2 — price_iron_energy·price_other 필수 확보 + price_minor_metals 스팟체크 (2026-08-29)

## 배경
Phase 1 완료 후 main-agent 지시: price_iron_energy·price_other는 정적 덤프
자체가 없어(`income_data/komis/MANIFEST.json`에 파일 無) 라이브 확보가
최우선(필수), price_minor_metals는 이미 34광종 정적덤프로 검증됐으니
대표 광종(리튬·코발트) 라이브 스팟체크만. 코드 수정은 이 문서 보고 후
승인받고 진행 — 이번 라운드는 확인 중심이다(예외: 아래 "확인" 항목은
Phase 1 승인 범위 안이라 회귀 스위트로 이미 검증됨).

## 1) price_iron_energy·price_other 라이브 확보
KOMIS URL: `/Komis/RsrcPrice/IronOre`(우라늄·유연탄·철), `/Komis/RsrcPrice/
EtcMnrl`(금·루테늄·백금·은·팔라듐·흑연) — `komis_menu_map.yaml`에서 확인.
Playwright로 각 광종×가격기준 조합의 DAY 응답을 라이브 캡처(iron_energy 4건,
other 6건, 전부 성공) — 원본은
`report_gen_KOMIS라이브재검증_Phase2_260829_evidence/collected_iron_other_day_raw_260829.json`.

**stdMap 구조 동일 확인**: 10건 전부 `dataAvg.stdMap.{DAY,WEEK,MONTH,YEAR}`
존재. Phase 1의 `calculate_price_summary`(page_id 무관하게 공유 로직) +
`komis_period_comparisons` 패스스루를 실제로 태워 검증한 결과, **week/
month/year 기간비교 30개(iron_energy 4콤보×3기간=12, other 6콤보×3기간=18)
전부 mismatch 0** — stdMap 패스스루 설계가 price_iron_energy·price_other에도
코드 수정 없이 그대로 적용됨을 확인. price_minor_metals 스팟체크(§2)
18개까지 합치면 이번 Phase 2에서 대조한 기간비교는 총 48개, 전부 mismatch
0이다.

**DAY 패스스루 제외 결정 재검증**: Phase 1은 동(일별 캐던스)만으로 "DAY는
자체계산이 KOMIS와 일치하니 패스스루 불필요"를 확정했었다. 이번에 처음
확보한 **주간 캐던스 계열**(우라늄, 138행 — 매일이 아니라 주 단위로만
갱신)을 포함해 16콤보 전부 자체계산(인접 관측치 `_pct`) vs
`stdMap.DAY.flctnPrcnt`를 전수 대조한 결과 **16/16 정확히 일치** — DAY
제외 결정이 신규 3페이지·비일별 캐던스에서도 그대로 유효함을 확인했다
(week_avg처럼 캐던스가 다르면 정의차가 숨어있을까 우려했는데, DAY는
"인접 관측치 직접 비교"라는 정의 자체가 캐던스 무관하게 KOMIS와 같다).

표본(철/Iron Ore Fines):
```
2026년 8월 27일 기준 철 실거래가는 100.50이다.
전일(2026년 8월 26일) 대비 +0.00% 변동했다.
전주평균(99.10) 대비 +1.41% 수준이다.
전월평균(98.59) 대비 +1.94% 수준이다.
전년평균(102.21) 대비 -1.67% 수준이다.
```
`report_gen_KOMIS라이브재검증_Phase1_260828.md`에서 이미 적용한
period_range 폴백(2f13eef23 커밋)도 정상 동작 확인("조회기간 관측치
(실거래가) 기준 최고 143.32, 최저 88.85였다" — 철 hghst/lowst도 최근
구간이 0.00이라 폴백 경로를 탄다).

## 2) price_minor_metals 스팟체크(리튬·코발트)
KOMIS `/Komis/RsrcPrice/MinorMetals`에서 리튬(3개 가격기준)·코발트(3개
가격기준) 총 6콤보 라이브 재캡처(원본:
`collected_minor_spotcheck_raw_260829.json`). stdMap 존재 확인, 18개
기간비교 대조 전부 mismatch 0 — Phase 1 정적덤프 검증(34광종)과 결이
같아 별도 우려 없음.

## 3) 신규 발견(중요) — 재고량(inventory)이 base_metals 6종 외엔 전량 "0.00"(가짜 결측)
Phase 1에서는 동·니켈(전통 LME 6대금속 중 2종)만 실측했고, 그 673+673행
전부에서 `invt`가 0인 사례가 없어 "재고 0톤도 물리적으로 가능하니 결측
취급하면 안 된다"고 판단해 `_nonzero()` 게이트를 재고량에 적용하지
않았다(Phase 1 문서 "남은 한계" 절에 이미 판별 불가로 기록해뒀던 지점).

이번 Phase 2 라이브 데이터로 그 공백이 메워졌다 — **16개 광종/가격기준
콤보(우라늄·유연탄·철·금·루테늄·백금·은·팔라듐·흑연·리튬×3·코발트×3)를
전수 확인한 결과, 전부 다 매 관측일 `invt="0.00"`**이다(예외 0건). Phase 1
때 재수집한 나머지 base_metals 4종(아연·알루미늄·연·주석)도 이번에 다시
확인했는데, 이쪽은 동·니켈처럼 **매 관측일 실측값**이고 0인 사례가 없다.

| 그룹 | 콤보 수 | invt=0.00 행 비율 |
|---|---|---|
| price_base_metals(6대 전통 LME금속: 니켈·동·아연·알루미늄·연·주석) | 13(6광종×가격기준, 주석은 3기준) | **0%**(모든 행 실측값) |
| price_iron_energy(우라늄·유연탄·철) | 4 | **100%** |
| price_other(금·루테늄·백금·은·팔라듐·흑연) | 6 | **100%** |
| price_minor_metals(리튬·코발트, 코발트는 LME 기준도 포함) | 6 | **100%** |

즉 "LME 재고량"은 KOMIS가 전통 LME 6대 비철금속(정확히 price_base_metals
6광종)에만 실제로 제공하고, 그 외(철광석·에너지·귀금속·흑연·희소금속 —
코발트가 LME 기준가라도 마찬가지)는 `invt` 필드 자체를 "0.00"으로 채워
보낸다 — 이건 `_nonzero()` 함수 docstring이 이미 문서화한 KOMIS 전역
관행("값이 없을 때 '0.00'을 채워 보낸다")과 정확히 같은 패턴이다.

**문제**: Phase 1에서 구현한 `inventory_level` 근거는 이 게이트를 적용하지
않아서, price_iron_energy/price_other/price_minor_metals(코발트 등) 요청에
`inventory` 값이 전달되면 **"재고량은 0.00이다"라는 사실상 거짓 문장**을
만든다(실제로는 "재고량 정보 없음"인데 "0톤"으로 단정). 이미 Phase 1이
main에 머지·재배포된 상태라 **현재 배포된 테스트 이미지에 이 문제가
그대로 있다** — 실제로 Phase 1 회귀 스위트가 이미 이 문장을 만들어
레포에 커밋해뒀다(`report_gen_KOMIS라이브재검증_Phase1_260828_evidence/
harness_sample_entries_260828.json`, 가돌리늄 표본):
```
## 현재 위치

조회기간 중 최고 37.78, 최저 22.10였다. 2026년 8월 25일 기준 재고량은 0.00이다.
```
가설이 아니라 이미 산출된 실물이다 — 승인 후 하네스 재실행하면 이
문장이 사라지는 게 깔끔한 before/after가 된다.

**제안하는 처방**: `latest.inventory`·직전 관측치의 inventory 값 둘 다에
`_nonzero()`를 적용해, 0.00이면 결측으로 취급(claim 생성 건너뜀) — 이미
`lowest_price`/`highest_price`에 적용 중인 것과 완전히 동일한 패턴이라
새 개념을 들여오는 게 아니다. 페이지별로 하드코딩(`page_id ==
"price_base_metals"`)하는 대신 값 기반으로 게이트하는 쪽을 추천한다 —
근거: (1) 이번 조사가 "전통 LME 6대금속만 실데이터"를 확인했지만 이건
현재 시점 관측이지 코드 계약이 아니고, (2) 값 기반 게이트는 향후 KOMIS가
다른 광종에도 재고량을 채워 넣기 시작하면 코드 수정 없이 자동으로
반영된다.

**코드는 아직 안 건드렸다** — 승인 후 진행하겠습니다.

## 4) 처방 적용 완료(main-agent 승인, 2026-08-29)
`latest.inventory`·`prior_inventory_obs` 탐색 둘 다에 `not in (None, 0, 0.0)`
게이트를 적용했다(값 기반, page_id 하드코딩 없음 — 승인받은 설계 그대로).

**before/after(가돌리늄, minor_metals:가돌리늄|Gadolinium Oxide|99.5|DAY)**:
```diff
 ## 현재 위치

-조회기간 중 최고 37.78, 최저 22.10였다. 2026년 8월 25일 기준 재고량은 0.00이다.
+조회기간 관측치(실거래가) 기준 최고 107.93, 최저 9.51였다.
```
(최고·최저 수치 자체도 바뀐 건 이 커밋과 무관 — 같은 날 먼저 적용한
period_range 폴백 수정(2f13eef23)이 이번 재실행에 함께 반영된 것뿐, hghst/
lowst 커버리지가 불완전해 commerce_price 기준으로 재계산된 결과다.)
`inventory_level`/`inventory_change_pct` key_metrics도 더 이상 안 나온다
(수정 전: `inventory_level=0.0`, 수정 후: 아예 없음).

**회귀 확인**: 실측 재고량이 있는 base_metals(동·니켈 등, 13콤보)는 영향
없음 — 예: 동|LME 3개월 표본은 수정 후에도 `inventory_level=235575.0`·
`inventory_change_pct=-0.80`(스크린샷과 일치하던 그 값) 그대로 유지.
`komis_dump_smoke_test.py` 전체 재실행 결과 8페이지 395콤보 internal_error
0·mismatches 0(변화 없음 — 이 체크는 week/month/year만 대조해 inventory
회귀는 직접 잡지 않지만, 크래시·다른 지표 영향 없음은 확인된다).

## Phase 3 진행 가능 여부
위 inventory 처방 결정과 무관하게 Phase 3(map_korea/global/mineral)는
독립적으로 진행 가능합니다 — 병행 지시하셔도 되고, 순서대로 하셔도
됩니다.
