# report_gen 비교광종(compare_mineral) — price_* 4종 전체로 확장 (2026-08-30)

## 배경
사용자가 정정: "compare_mineral은 광물자원가격 모든 메뉴에서 다 제공됩니다."
report_gen은 2026-08-27 price page_id 분리 당시 "비교광종은 희소금속
전용 KOMIS 기능"이라고 보고 `price_minor_metals`로만 요청 스키마를
제한해뒀다(pydantic validator). 사용자 정정 후 라이브로 재확인.

## 확인
Playwright로 KOMIS 광물자원가격 4개 서브메뉴를 전부 접속:
- `/Komis/RsrcPrice/BaseMetals`(비철금속)
- `/Komis/RsrcPrice/MinorMetals`(희소금속)
- `/Komis/RsrcPrice/IronOre`(철광석·에너지)
- `/Komis/RsrcPrice/EtcMnrl`(기타)

4개 페이지 전부 동일한 비교광종 UI 요소(`srchCompareMnrkndUnqCd`,
`srchComparePrcCrtr` select)와 "비교광종" 텍스트를 갖고 있음을 확인 —
사용자 말이 맞았고, 기존 코드의 "희소금속 전용" 가정이 틀렸다.

## 수정
`inhouse/services/report_gen/app/analysis/models.py`의
`AnalysisSummaryRequest.validate_period` — `compare_mineral`/
`compare_mineral_name`/`compare_price_criterion`/`compare_observations`
필드 허용 범위를 `page_id != "price_minor_metals"` 단일 조건에서
`page_id not in (price_base_metals, price_minor_metals, price_iron_energy,
price_other)` 4종 전체로 확장. map_korea/map_global(수급지도)엔 이 기능이
없으므로 그대로 제외 유지.

계산 로직(`komir_summary.py::calculate_price_summary`,
`summary.py::_analyze_price`의 compare_series 조립)은 애초에 page_id
무관하게 공통 경로였어서 수정 불필요 — validator 하나만 막고 있었다.
관련 주석 4곳("희소금속 전용"이라고 잘못 적혀 있던 부분: models.py,
routers/analysis.py, komir_summary.py, summary.py)도 사실대로 정정했다.

`prompts.py::SECTION_SENTENCE_RANGES`도 확인했다 — price 4종 전부
`current_position: (1,2)`인데, `period_range + inventory_level +
compare_overall_change`가 동시에 나오면 3문장이 될 수 있어(models.py
하드 제약은 max_length=3이라 허용) 이 범위를 넘을 수 있다. 이건
2026-08-26부터 `price_minor_metals`에 이미 있던 잠재 이슈이고, 이번
확장으로 base_metals 등도 같은 노출을 받을 뿐 새로 만든 문제는 아니다.
규칙기반(`_deterministic_narrative`, 이번 세션 테스트 전부 이 경로)은 이
검증을 안 타서 영향 없음 — LLM 정제 경로만 잠재 영향 있고, 실측(LLM 켠
상태) 재현 전까지 숫자는 임의로 안 바꿨다. ⚠주석에 명시해뒀다 — 후속
결정 필요하면 참고.

## 검증
- 새 검증: `compare_mineral`을 `price_base_metals`로 보내면 정상 통과,
  `map_korea`로 보내면 여전히 정상 거부(회귀 없음) 확인.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 커밋
5개 파일(models.py·komir_summary.py·summary.py·routers/analysis.py·
prompts.py) — main-agent 승인 후 재빌드·재기동 필요.
