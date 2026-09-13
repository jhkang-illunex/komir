# streamlit_demo map_mineral "천톤" 기본값 버그 — 발견·수정 (2026-09-13)

> 배경: 사용자 제보 — "핵심 광물지도에서 생산량으로 검색시 나오는 수치가
> 생산량이 아니라 매장량으로 표시를 하고 있어요." report_gen API 자체가
> 아니라 **streamlit_demo(기획팀 보고용 UI)의 실시간 조회(komis.or.kr
> 라이브 fetch) 경로에서 실제 버그를 발견·재현·수정했다.**

## 재현(komis.or.kr 라이브 조회로 실측)

`komis_fetch.fetch_map_mineral('MNRL0008', measure='production', ...)`로
동(MNRL0008)의 실 생산량 데이터를 라이브로 가져온 뒤(이 evidence 폴더의
`live_komis_fetch_cu_production_260913.json`), 데모와 동일한 변환
(`komis_raw.passthrough_map_mineral`)을 거쳐 report_gen에 넘겨봤다.

- **버그 있는 상태**(`unit="천톤"` 포함, 데모 실제 기본값): "2025년 세계
  동 생산량은 **약 200.13억톤**입니다... 칠레는 **약 53억톤**" — 세계
  구리 생산량이 연간 2천만 톤 안팎(실측)인데 200억 톤이 나옴, 1,000배
  과장.
- **수정 후**(`unit` 미지정, komis_response에서 자동유도): "2025년 세계
  동 생산량은 **약 2,001.30만톤**입니다... 칠레는 **약 530만톤**" — 칠레
  실제 연간 구리 생산량(약 530만 톤대)과 정확히 일치하는 현실적인 수치.

## 원인

`report_gen_client.py::EXTRA_FIELD_DEFAULTS["unit"] = "천톤"` — map_mineral
페이지의 "단위(unit)" 입력란을 항상 "천톤"으로 미리 채워뒀다(2026-08-29
도입, 당시엔 unit 필드가 비면 서버가 NO_DATA를 던지는 걸 막기 위한
임시조치였음). 그런데 report_gen의 `_analyze_mineral_map`은
`unit = request.unit or komis_unit`(호출자가 명시한 값이 있으면 그게
우선) 규칙이라, 사용자가 이 기본값을 지우지 않으면 원래
`komis_response`에서 정확히 자동유도되는 단위("톤" — KOMIS 원시 코드
"k ton"의 실측 확정 매핑)를 "천톤"이 덮어쓴다. `compact_fact()`의 단위
환산표에서 "천톤"은 "원값×1000=실제 톤"으로 정의돼 있어(반면 원값은
이미 톤 단위), 모든 map_mineral 실시간조회 결과(매장량·생산량 둘 다)가
1,000배 부풀려져 나왔다.

2026-08-29 당시 이 기본값을 넣은 이유(정적 템플릿 미리보기에서 komis_
response 없이 unit이 비면 NO_DATA)는, map_mineral이 그 이후 KOMIS_RAW_
PAGES로 편입되면서 정적 예시(`komis_raw.py`의 `example_raw_json`)도
`passthrough_map_mineral` 변환을 거쳐 komis_response 기반 자동유도가
항상 가능해져 이미 해소돼 있었다 — 기본값을 비워도 NO_DATA가 재발하지
않는다(재확인 완료).

## 조치

`EXTRA_FIELD_DEFAULTS`에서 `"unit": "천톤"` 항목 삭제(빈 dict로) —
`inhouse/streamlit_demo/report_gen_client.py`. pyflakes 통과. streamlit
프로세스 재기동(mtime 17:06:34 < 새 프로세스 시작 17:07:20으로 코드 반영
확인, HTTP 200 확인).

**report_gen API 코드는 무결점** — 버그는 전적으로 데모 UI(streamlit_demo)
쪽 기본값이었다.
