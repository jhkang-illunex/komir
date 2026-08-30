# report_gen — compare_mineral_name도 komis_response 자동채움 (2026-08-30)

## 배경
사용자: "api v1 analysis prices base-metals에서 compare_mineral,
compare_mineral_name 이건 komis_respose안애 data 사전 내에 값이
있지 않나?"

직전 라운드(Swagger 2차 재감사)에서 `compare_mineral_name`을
"데모는 안 보내지만 실제 KOMIS 연동 캐스터를 위한 표시명 오버라이드로
유효"라고만 판단하고, komis_response로 자동채움이 가능한지는 확인하지
않았다 — 이번 지적으로 재조사.

## 조사 — Playwright 라이브 재현
`샌드박스 curl은 막혀도 Playwright는 됨`(기존 메모리) 패턴대로,
KOMIS 희소금속 화면(`MinorMetals`)에서 실제로 기본광종=네오디뮴,
비교광종=갈륨을 선택하고 검색을 눌러 `getMnrlPrcByMnrkndUnqCd` 응답을
캡처했다:

```
dataAvg.cmpMap.INFO.mnrkndKornNm = "갈륨"   ← 비교광종 한글명
dataAvg.stdMap.INFO.mnrkndKornNm = "네오디뮴" ← 기본광종 한글명(기존에 이미 자동채움 중)
```

`cmpMap`은 `stdMap`(기본 광종 몫)과 완전히 같은 모양으로 비교 광종
몫이 별도로 온다 — 사용자 말대로 정말 있었다. `mineral_name`은 이미
이 자리(`stdMap.INFO`)에서 자동채움하고 있었는데, 대칭인
`cmpMap.INFO`는 그동안 읽지 않고 있었다(직전 라운드에서도 놓친
부분).

단, `compare_mineral`(코드)은 이번에도 응답 어디에도 없다는 게
재확인됐다(`cmpMap.INFO`도 이름만 있고 코드 없음) — 코드는 여전히
호출자가 명시해야 한다(기존 결론 불변, 이름만 신규 자동채움).

## 변경
`app/analysis/summary.py::_parse_komis_price_response()` 반환값을
5개→6개로 확장, `compare_mineral_name`(`dataAvg.cmpMap.INFO.
mnrkndKornNm`) 추가. `_analyze_price()`에서
`request.compare_mineral_name or komis_compare_mineral_name or
request.compare_mineral` 폴백 체인으로 사용(`mineral_name`과 동일
패턴). `routers/analysis.py::PriceSummaryRequest` docstring도 갱신
(필드 타입/필수여부는 변경 없음 — 원래도 optional이었다).

## 검증
- 실제 캡처한 라이브 응답(네오디뮴 vs 갈륨)으로 `prices/minor-metals`
  호출 — `compare_mineral_name`을 아예 안 보냈는데도 보고서에
  "**비교광종**: 갈륨"·"갈륨은 +13.37% 변동" 정상 출력.
- `komis_dump_smoke_test.py` 회귀 395콤보(8페이지) 전부 mismatch 0
  유지.

## 커밋
`app/analysis/summary.py`·`app/routers/analysis.py` — main-agent
승인 후 재빌드·재기동 필요.
