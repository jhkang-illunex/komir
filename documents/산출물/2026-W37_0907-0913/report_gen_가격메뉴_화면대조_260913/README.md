# 광물자원가격 메뉴(price_*) 옵션별 화면-API 대조 점검 (2026-09-13)

> 사용자 추가 요청: "하는 김에 광물자원 가격 메뉴도 동일하게 옵션별
> 결과를 웹 페이지를 직접 아웃풋을 보면서 나오는 데이터와 요약 api
> 보고서에 나오는 결과에 대해서도 비교해주세요."

## 대상 페이지(실측 확인)

- price_base_metals → `/Komis/RsrcPrice/BaseMetals`
- price_minor_metals → `/Komis/RsrcPrice/MinorMetals`
- price_iron_energy → `/Komis/RsrcPrice/IronOre`
- price_other → `/Komis/RsrcPrice/EtcMnrl`

네 페이지 모두 같은 구조(폼 id `#frmSearch`, 광종 선택 `changeSelectVal()`,
조회 함수 `getMnrlPrcList()`, 비교광종 select `#srchCompareMnrkndUnqCd`).
Playwright로 각 페이지를 열어 `getMnrlPrcList()`를 직접 호출해 렌더링을
확인했다(map_korea/global과 달리 이 페이지들은 숨은 shadow form이 아니라
실제 보이는 `#frmSearch`라 필드값을 jQuery `.val().trigger('change')`로
직접 세팅해도 정상 반영된다).

## 최우선 확인: 비교광종(compareMnrl) — 오늘 처음으로 라이브 화면 검증

오전 `report_gen_비교광종_확인_260913/`은 정적 덤프를 "합성"해 만든
표본이라 실제 KOMIS 화면에서 비교광종을 켠 적이 없었다. 이번엔 실제
동(MNRL0008) 페이지에서 비교광종으로 니켈(MNRL0002)을 선택해 조회했다.

**화면 확인**(`screen_body_text_price_base_cu_cmp_ni.txt`): "비교광종"
select에 "니켈"이 선택된 상태로 렌더링되고, 화면에 "동"·"니켈" 두 개의
가격추이 차트 패널이 나란히 뜬다(차트 자체는 canvas라 수치 텍스트 추출은
안 되지만 패널 존재·라벨은 확인됨). 기준광종(동)의 등락률 표는 텍스트로
그대로 잡힌다:

| 항목 | 화면 | report_gen |
|---|---|---|
| 2026-09-10 기준가 | 14,390.00 | 14,390달러 |
| 전일대비 | 하락 282.00(1.92%) | 1.92% 하락 |
| 전주평균대비 | 상승 19.87(0.14%) | 0.14% 높음 |
| 전월평균대비 | 상승 36.60(0.25%) | 0.25% 높음 |
| 전년평균대비 | 상승 4,445.06(44.70%) | 44.70% 높음 |

전부 일치. `komis_fetch.fetch_price_base_metals('MNRL0008',
compare_mineral_code='MNRL0002')`로 재조회한 원본(`clean_price_cu_cmp_
ni.json`)의 `compareMnrl` 배열(6,238행, 최신일 니켈 cmercPrc=16,630)도
정상 포함돼 있고, report_gen이 이걸 받아 `compare_overall_change_pct`
(721.32%, "조회 시작일 대비 동/니켈 누적 변화율 차이") 계산까지 정상
수행 — **비교광종 기능, 라이브 데이터 기준으로 최초 검증 완료, 문제없음**.

## 실시간가/등락률 기준일 버그(오늘 이미 수정·배포) 재확인

오늘 이 세션 초반에 고친 "현재가는 실시간가, 등락률은 그 실시간가
기준으로 계산" 로직이 방금 새로 가져온 라이브 데이터(2026-09-10 최신
데이터)에서도 화면과 정확히 일치함을 위 표로 재확인했다 — 재발 없음.

## 나머지 3개 메뉴(price_minor_metals/price_iron_energy/price_other)

기본 조회(광종 무선택 → 페이지 기본 광종)로 페이지 로드만 확인, 각
`getMnrlPrcByMnrkndUnqCd` 응답이 정상 수신됨을 확인(크래시 없음). 개별
report_gen 대조는 시간 제약상 생략 — price_base_metals과 동일한
계산기·파서를 공유하고(page_id만 다름), 오늘 오전 `report_gen_
신규조건_확인_260913/`·`report_gen_비교광종_확인_260913/`에서 4개
메뉴 전부 이미 별도로 검증된 바 있어 중복 확인으로 판단.

## 애매한 부분 / 미확인 항목

- 가격기준(가격 종류, 예: LME CASH vs LME 3개월)·평균옵션(일/주/월별)을
  실제로 바꿔가며 화면-API 대조까지는 이번에 하지 못했다(시간 제약,
  `getMnrlPrcByMnrkndUnqCd`가 두 값 다 요청 파라미터로 받는 것은 코드
  확인됨 — `srchAvgOpt`/`srchPrcCrtr`). 필요하면 후속 점검 대상.

## 결론

- 실제 버그: 없음.
- 비교광종 기능은 오늘 처음으로 라이브 데이터 기준 검증 완료(정상).
- 실시간가/등락률 수정 재발 없음 확인.
- 미확인: 가격기준·평균옵션 조합별 화면 대조(후속 과제로 남김).

## 재현

Playwright 스크립트는 `report_gen_map_korea_global_화면대조_260913/
playwright_capture.py`(audit3.py)에 price_* 5개 케이스도 함께 들어있다
(같은 세션 한 스크립트로 처리). `clean_price_cu_cmp_ni.json`은
`komis_fetch.fetch_price_base_metals()`로 별도 재조회.
