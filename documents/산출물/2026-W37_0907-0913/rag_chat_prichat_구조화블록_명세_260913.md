# rag_chat `/prichat` 구조화 블록(table·chart) 이벤트 명세 — 프론트 팀용

작성 2026-09-13. **적용 범위: `POST /prichat`(private 프로필)만.** `/pubchat`은
기존 계약(마크다운 표 + PNG `image` 이벤트) 그대로다. 프론트가 이 방식으로
그려 보고 쓰기 좋으면 `/pubchat`에도 같은 형태로 넓힌다.

## 배경·원칙

- 표·차트를 그리는 주체는 챗봇이 아니라 프론트다. 챗봇은 "데이터 + 표현
  힌트"만 준다.
- 데이터 블록은 LLM이 아니라 서버가 결정론적으로 만든다(근거 텍스트 안의
  마크다운 표를 파싱 → 타입 판정 → 블록). 답변 본문(delta)의 숫자와 블록의
  숫자는 같은 원천이다.
- `<json></json>` 같은 HTML 태그를 마크다운에 끼우는 방식은 쓰지 않았다
  (렌더러 sanitize로 사라지거나 원문 노출, SSE 청크 경계에서 태그 분절).
  대신 SSE 이벤트 타입으로 분리한다.

## 이벤트 순서(변경 없음)

`session` → `status`(1..4, 여러 번) → `delta`* → **`table`* / `chart`*** →
`done`. `table`·`chart`는 답변 텍스트가 끝난 뒤, `done` 전에 온다. 인용된
근거에서만 만든다(인용 안 된 조회 결과의 표는 내지 않는다).

## `table` 이벤트 (private에서 확장)

기존 키 `columns`(문자열 배열)·`rows`(문자열 2차원 배열)·`source_index`·
`source`는 그대로 유지되고, 아래가 추가된다.

```json
{
  "schema_version": 1,
  "block_id": "t2-1",
  "columns": ["crtr_ymd(기준일자)", "최저가", "최고가"],
  "rows": [["20260910", "14,390", "14,850"], ["20260911", "14,200", "14,600"]],
  "columns_meta": [
    {"key": "crtr_ymd", "label": "crtr_ymd(기준일자)", "type": "date",   "unit": null},
    {"key": "최저가",   "label": "최저가",             "type": "number", "unit": null},
    {"key": "최고가",   "label": "최고가",             "type": "number", "unit": null}
  ],
  "rows_typed": [["20260910", 14390.0, 14850.0], ["20260911", 14200.0, 14600.0]],
  "markdown": "| crtr_ymd(기준일자) | 최저가 | 최고가 |\n| --- | --- | --- |\n| 20260910 | 14,390 | 14,850 |\n| 20260911 | 14,200 | 14,600 |",
  "meta": {"source_index": 2, "source": "KOMIS 국내수급지도 · 가격 (기준시점 2026-09-10)", "row_count": 2},
  "source_index": 2,
  "source": "KOMIS 국내수급지도 · 가격 (기준시점 2026-09-10)"
}
```

- `block_id`: `t{근거번호}-{표순번}`. 같은 턴 안에서 유일.
- `columns_meta[].key`: 헤더에서 `(설명)`을 뗀 컬럼 키. `type`은
  `date`(KOMIS 기준일 컬럼 `crtr_ymd`/`crtr_yr`, 값은 `YYYYMMDD`/`YYYY`
  문자열) · `number`(전 행이 숫자, 콤마·% 허용) · `string`. `unit`은 전 행이
  `%`로 끝나면 `"%"`, 그 외 `null`.
- `rows_typed`: `number` 열은 float(콤마·% 제거), 나머지는 원문 문자열.
- `markdown`: 답변 텍스트(delta 누적본) 안에 같은 표가 마크다운으로 남아
  있다. 프론트가 자기 표 컴포넌트로 바꾸려면 이 문자열을 본문에서 찾아
  치환하면 된다(구 클라이언트는 그대로 두면 마크다운 표로 보인다).
- `meta.source`는 답변 말미 "출처:" 목록과 같은 문구라 캡션에 그대로 쓸 수
  있다.

## `chart` 이벤트 (private 신설, PNG `image` 이벤트를 대체)

```json
{
  "schema_version": 1,
  "block_id": "c2-1",
  "data_ref": "t2-1",
  "spec": {
    "kind": "line",
    "x": "crtr_ymd",
    "x_type": "date",
    "series": ["최저가", "최고가"],
    "sort_x_ascending": true,
    "title": "최저가 · 최고가"
  },
  "meta": {"source_index": 2, "source": "KOMIS 국내수급지도 · 가격 (기준시점 2026-09-10)"},
  "source_index": 2,
  "source": "KOMIS 국내수급지도 · 가격 (기준시점 2026-09-10)"
}
```

- 데이터는 싣지 않는다. `data_ref`가 가리키는 `table` 블록의
  `rows_typed`/`columns_meta`를 쓴다(`table`이 항상 먼저 온다).
- `kind`: 행 4개 이상이면 `line`(추이), 그보다 적으면 `bar`(계열별 묶음).
- `x`: 날짜열이 있으면 그 열, 없으면 첫 열(국가·광종 같은 범주). `x_type`이
  `date`면 `sort_x_ascending=true` — 과거→최근으로 정렬해서 그린다(KOMIS
  원본은 최신순이라 그대로 그리면 거꾸로 읽힌다). 범주형이면 원본 순서 유지.
- `series`: 숫자열 중 값이 전부 같은 열(식별자 등)은 제외. 계열이 하나도
  없으면 `chart` 이벤트 자체가 오지 않는다(억지 차트를 그리지 않는 원칙).
- 스펙은 특정 차트 라이브러리에 묶이지 않도록 최소로 뒀다. 축 포맷(날짜
  `YYYYMMDD`→표시형), 단위 표기, 색은 프론트 몫이다.

## 호환·버전

- `schema_version`은 블록마다 들어간다. 필드 추가는 버전 유지, 의미 변경은
  버전 증가.
- private에서는 `image` 이벤트가 더 이상 오지 않는다. `/pubchat`은 종전대로
  `image`(PNG base64)가 온다.
- 참고 구현: `inhouse/streamlit_demo/chatbot.py::_render_chart`가 이 스펙을
  받아 `st.line_chart`/`st.bar_chart`로 그린다(프론트 예시).

## 서버 구현 위치

- `inhouse/rag_core/ragkit/chatbot_events.py`: `table_block()`, `chart_spec()`,
  `extract_markdown_tables()`의 `markdown` 키.
- `inhouse/rag_core/ragkit/chatbot.py::_multimodal_events(profile=)`: private면
  블록, public이면 기존 경로.
- 단위 테스트: `inhouse/rag_chat/tests/test_private_blocks.py`.
