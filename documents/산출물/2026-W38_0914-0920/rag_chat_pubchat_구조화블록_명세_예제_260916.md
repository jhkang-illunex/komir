# rag_chat `/pubchat` 구조화 블록(table·chart) 이벤트 명세 + 라이브 예제 — 프론트 팀용

작성 2026-09-16. **적용 범위: `POST /pubchat`(public 프로필).** 2026-09-13 `/prichat`
전용으로 도입한 블록 이벤트를 2026-09-16부터 `/pubchat`에도 그대로 적용했다 —
두 엔드포인트의 계약은 동일하며, 이 문서는 `/pubchat` 라이브 응답에서 그대로 캡처한
예제(데이터 JSON + 차트 스펙 JSON + 추천 차트)를 싣는다. 규칙 전체 정본은
`rag_chat_구조화블록_공통명세_차트추천_260916.md`(같은 폴더).

## 배경·원칙

- 표·차트를 그리는 주체는 챗봇이 아니라 프론트다. 챗봇은 "데이터 + 표현 힌트"만
  준다. 예전 `/pubchat`의 PNG `image` 이벤트는 **제거**됐다(2026-09-16).
- 데이터 블록은 LLM이 아니라 서버가 결정론적으로 만든다(인용된 근거의 마크다운 표
  파싱 → 타입 판정 → 블록). 추천 차트(`chart_hint`·`chart.spec.kind`)도 표 모양만으로
  서버가 판정한다.
- `/pubchat`은 라이선스 제한 문서와 private 전용 KOMIS 페이지(`indicator_market`·
  `indicator_supply`·`indicator_composite`)를 쓰지 않는다. 따라서 public에서 실제로
  나오는 표는 가격(price_*)·매장량/생산량(map_mineral)·국내교역(map_korea)·세계교역
  (map_global)과 문서 청크 안의 표다.

## 이벤트 순서

`session` → `status`(1..4, 여러 번) → `delta`* → **`table`* / `chart`*** → `done`.
표마다 `table` 1건, 추천 차트가 있으면 그 직후 `chart` 1건. 인용된 근거에서만 만든다.

## `table` 이벤트

| 필드 | 뜻 |
| --- | --- |
| `schema_version` | 블록 스키마 버전(현재 1) |
| `block_id` | `t{근거번호}-{표순번}`, 같은 턴 안에서 유일 |
| `columns` / `rows` | 원문 문자열 그대로(구 클라이언트 호환) |
| `columns_meta[]` | `key`(헤더에서 괄호 설명을 뗀 컬럼 키) · `label`(헤더 원문) · `display`(괄호 안 한글 설명, 축 제목·범례용) · `type`(`date`/`number`/`string`) · `unit`(`%` 또는 null) |
| `rows_typed` | `number` 열은 float, DB NULL(원문 `"None"`)은 타입 무관 `null`, 나머지는 문자열 |
| `markdown` | 근거 표 원문 마크다운. ⚠ 본문(delta)의 표는 LLM이 헤더를 한글로 바꿔 다시 쓴 것이라 이 문자열과 **일치하지 않을 수 있다** — 문자열 치환보다 본문 아래에 블록을 별도 렌더하는 쪽을 권한다 |
| `chart_hint` | **추천 차트** — `recommended`(`line`/`bar`/`pie`/`null`) · `alternatives`(대안 목록) · `reason`(사람용 판정 사유, 파싱 금지) |
| `meta` | `source_index`·`source`(출처 문구, 캡션에 그대로 사용)·`row_count` |

`type: "date"`인 열의 값은 `YYYYMMDD`·`YYYYMM`·`YYYY` 문자열이다(차트 스펙 `x_format`).

## `chart` 이벤트

| 필드 | 뜻 |
| --- | --- |
| `data_ref` | 데이터가 있는 `table` 블록의 `block_id`(`table`이 항상 먼저 온다) |
| `spec.kind` | 추천 차트: `line` / `bar` / `pie` |
| `spec.alternatives` | 토글로 제공해도 되는 대안(예: `["pie"]`) |
| `spec.x` / `x_type` / `x_format` | X축 컬럼 키 · `date`/`category` · 날짜 값 형식 |
| `spec.series` | Y 계열 컬럼 키(식별자·전부 빈 값·중복 열은 이미 제외됨) |
| `spec.group` | 있으면 같은 X에 여러 행(연도×국가)인 표 — 첫 계열을 `group` 값별 선/막대로 펼친다 |
| `spec.sort_x_ascending` | `true`면 과거→최근으로 정렬해 그린다(KOMIS 원본은 최신순) |
| `spec.title` | 계열 `display`를 이은 제목 |

## 추천 차트 종류(서버 판정 규칙 요약)

| kind | 추천 조건 |
| --- | --- |
| `line` | 날짜열이 X축, 시점당 1행, 시점 4개 이상 |
| `bar` | 범주형 X(국가·품목), 또는 날짜열이지만 시점 3개 이하. `group`이 있으면 구분값별 묶음막대 |
| `pie` | 대안으로만 — 범주형 X, 계열 1개, 범주 2~8개, 값 전부 양수 |
| (없음) | 값이 갈리는 숫자 계열이 없거나 행 2개 미만 → `chart_hint.recommended=null`, `chart` 이벤트 없음 |

## 라이브 예제(2026-09-16, `komir-rag-chat:260916-blocks2`, `/pubchat`)

⚠ 발주 5광종의 KOMIS `ko_*` 데이터는 개발용 더미(DEV_DUMMY)라 **값은 예시**다(답변
본문에 서버가 그 경고를 강제로 붙인다). 모양·필드는 실제 계약 그대로다.

### 예제 1 — 시계열 → `line` (니켈 가격, KO_MNRL_PRC)

질문: `니켈 최근 일주일 LME 가격을 표와 함께 보여줘`
이벤트 수: `{"session": 1, "status": 5, "delta": 345, "table": 1, "chart": 1, "done": 1}`

답변 본문(delta 누적, 취소선 필터 통과 후 — `~`가 `\~`로 이스케이프된 것에 주목):

```markdown
제공된 근거의 실제 조회기간은 2026-09-02부터 2026-09-08까지입니다. [1]

| 기준일자 | 최저가격 | 최고가격 | 통상가격 | 재고 |
| --- | --- | --- | --- | --- |
| 2026-09-08 | 16410.62 | 17080.44 | 16745.53 | 272380.0 |
| 2026-09-07 | 16077.06 | 16733.26 | 16405.16 | 271900.0 |
| 2026-09-04 | 16110.08 | 16767.64 | 16438.86 | 270257.0 |
| 2026-09-03 | 16004.4 | 16657.64 | 16331.02 | 271620.0 |
| 2026-09-02 | 15812.85 | 16458.27 | 16135.56 | 271469.0 |

[1]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-02\~2026-09-08, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))
```

`table` 이벤트(원문 그대로):

```json
{
  "schema_version": 1,
  "block_id": "t1-1",
  "columns": [
    "mnrl_prc_crtr_sn(광물가격기준순번)",
    "crtr_ymd(기준일자)",
    "lowst_prc(최저가격)",
    "hghst_prc(최고가격)",
    "cmerc_prc(통상가격)",
    "invt(재고)"
  ],
  "rows": [
    [
      "502.0",
      "20260908",
      "16410.62",
      "17080.44",
      "16745.53",
      "272380.0"
    ],
    [
      "502.0",
      "20260907",
      "16077.06",
      "16733.26",
      "16405.16",
      "271900.0"
    ],
    [
      "502.0",
      "20260904",
      "16110.08",
      "16767.64",
      "16438.86",
      "270257.0"
    ],
    [
      "502.0",
      "20260903",
      "16004.4",
      "16657.64",
      "16331.02",
      "271620.0"
    ],
    [
      "502.0",
      "20260902",
      "15812.85",
      "16458.27",
      "16135.56",
      "271469.0"
    ]
  ],
  "columns_meta": [
    {
      "key": "mnrl_prc_crtr_sn",
      "label": "mnrl_prc_crtr_sn(광물가격기준순번)",
      "display": "광물가격기준순번",
      "type": "number",
      "unit": null
    },
    {
      "key": "crtr_ymd",
      "label": "crtr_ymd(기준일자)",
      "display": "기준일자",
      "type": "date",
      "unit": null
    },
    {
      "key": "lowst_prc",
      "label": "lowst_prc(최저가격)",
      "display": "최저가격",
      "type": "number",
      "unit": null
    },
    {
      "key": "hghst_prc",
      "label": "hghst_prc(최고가격)",
      "display": "최고가격",
      "type": "number",
      "unit": null
    },
    {
      "key": "cmerc_prc",
      "label": "cmerc_prc(통상가격)",
      "display": "통상가격",
      "type": "number",
      "unit": null
    },
    {
      "key": "invt",
      "label": "invt(재고)",
      "display": "재고",
      "type": "number",
      "unit": null
    }
  ],
  "rows_typed": [
    [
      502.0,
      "20260908",
      16410.62,
      17080.44,
      16745.53,
      272380.0
    ],
    [
      502.0,
      "20260907",
      16077.06,
      16733.26,
      16405.16,
      271900.0
    ],
    [
      502.0,
      "20260904",
      16110.08,
      16767.64,
      16438.86,
      270257.0
    ],
    [
      502.0,
      "20260903",
      16004.4,
      16657.64,
      16331.02,
      271620.0
    ],
    [
      502.0,
      "20260902",
      15812.85,
      16458.27,
      16135.56,
      271469.0
    ]
  ],
  "markdown": "| mnrl_prc_crtr_sn(광물가격기준순번) | crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) |\n| --- | --- | --- | --- | --- | --- |\n| 502.0 | 20260908 | 16410.62 | 17080.44 | 16745.53 | 272380.0 |\n| 502.0 | 20260907 | 16077.06 | 16733.26 | 16405.16 | 271900.0 |\n| 502.0 | 20260904 | 16110.08 | 16767.64 | 16438.86 | 270257.0 |\n| 502.0 | 20260903 | 16004.4 | 16657.64 | 16331.02 | 271620.0 |\n| 502.0 | 20260902 | 15812.85 | 16458.27 | 16135.56 | 271469.0 |",
  "chart_hint": {
    "recommended": "line",
    "alternatives": [],
    "reason": "시점당 1행인 시계열, 시점 5개"
  },
  "meta": {
    "source_index": 1,
    "source": "public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-02~2026-09-08, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))",
    "row_count": 5
  },
  "source_index": 1,
  "source": "public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-02~2026-09-08, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
}
```

`chart` 이벤트(원문 그대로):

```json
{
  "schema_version": 1,
  "block_id": "c1-1",
  "data_ref": "t1-1",
  "spec": {
    "kind": "line",
    "alternatives": [],
    "x": "crtr_ymd",
    "x_type": "date",
    "x_format": "YYYYMMDD",
    "series": [
      "lowst_prc",
      "hghst_prc",
      "cmerc_prc",
      "invt"
    ],
    "group": null,
    "sort_x_ascending": true,
    "title": "최저가격 · 최고가격 · 통상가격 · 재고"
  },
  "meta": {
    "source_index": 1,
    "source": "public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-02~2026-09-08, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
  },
  "source_index": 1,
  "source": "public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-09-02~2026-09-08, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
}
```

`done` 이벤트:

```json
{
  "done": true,
  "citations": [
    {
      "index": 1,
      "kind": "structured",
      "source": "public.KO_MNRL_PRC",
      "section": "KOMIS 원천 · KO_MNRL_PRC(니켈)",
      "as_of": "2026-09-02~2026-09-08, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음)",
      "unit": null
    }
  ],
  "bogus_citations": [],
  "abstained": false
}
```

그리는 방법: X=`crtr_ymd`(오름차순, `YYYYMMDD`→표시형), 선 4개(`lowst_prc`·`hghst_prc`·`cmerc_prc`·`invt`, 범례는 `display`). `mnrl_prc_crtr_sn`은 전 행 같은 값이라 계열에서 빠져 있다. 재고(27만대)와 가격(1.6만대) 스케일 차이는 이중 축 또는 계열 토글로.


### 예제 2 — 단일 시점 범주 → `bar` + `pie` 대안 (희토류 국가별 생산량, KO_RSRC_PRDCTN_QUTY)

질문: `희토류 국가별 생산량 알려줘`
이벤트 수: `{"session": 1, "status": 5, "delta": 216, "table": 1, "chart": 1, "done": 1}`

답변 본문(delta 누적, 취소선 필터 통과 후 — `~`가 `\~`로 이스케이프된 것에 주목):

```markdown
2026년 기준 희토류 국가별 생산량은 다음과 같습니다. 해당 데이터의 실제 조회기간은 2026\~2026입니다. [2]

| 국가 영문코드 | 생산량 | 생산량(톤환산) |
| :--- | :--- | :--- |
| US | 3984.0 | 3984.0 |
| ID | 9296.0 | 9296.0 |
| CN | 21248.0 | 21248.0 |
| CL | 6640.0 | 6640.0 |
| CD | 5312.0 | 5312.0 |

2026년 기준 희토류 생산량은 CN이 21,248.0톤으로 가장 많으며, ID, CL, CD, US 순으로 나타납니다. [2]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [2] public.KO_RSRC_PRDCTN_QUTY · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(희토류) (기준시점 2026\~2026, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))
```

`table` 이벤트(원문 그대로):

```json
{
  "schema_version": 1,
  "block_id": "t2-1",
  "columns": [
    "mnrknd_unq_cd(광종고유코드 KO_HS_HIGH_GROUP.MNRKND_UNQ_CD)",
    "crtr_yr(기준년도)",
    "ntn_eng_cd(국가 영문코드)",
    "mass_unit_cd(질량단위코드 ST_CODE_MST.CD_GRP = 'WT000')",
    "prdctn_quty(생산량)",
    "se_cd([샘플확장] 구분코드)",
    "prdctn_quty_ton([샘플확장] 생산량(톤환산))"
  ],
  "rows": [
    [
      "MNRL0006",
      "2026",
      "US",
      "TON",
      "3984.0",
      "DEV",
      "3984.0"
    ],
    [
      "MNRL0006",
      "2026",
      "ID",
      "TON",
      "9296.0",
      "DEV",
      "9296.0"
    ],
    [
      "MNRL0006",
      "2026",
      "CN",
      "TON",
      "21248.0",
      "DEV",
      "21248.0"
    ],
    [
      "MNRL0006",
      "2026",
      "CL",
      "TON",
      "6640.0",
      "DEV",
      "6640.0"
    ],
    [
      "MNRL0006",
      "2026",
      "CD",
      "TON",
      "5312.0",
      "DEV",
      "5312.0"
    ]
  ],
  "columns_meta": [
    {
      "key": "mnrknd_unq_cd",
      "label": "mnrknd_unq_cd(광종고유코드 KO_HS_HIGH_GROUP.MNRKND_UNQ_CD)",
      "display": "광종고유코드 KO_HS_HIGH_GROUP.MNRKND_UNQ_CD",
      "type": "string",
      "unit": null
    },
    {
      "key": "crtr_yr",
      "label": "crtr_yr(기준년도)",
      "display": "기준년도",
      "type": "date",
      "unit": null
    },
    {
      "key": "ntn_eng_cd",
      "label": "ntn_eng_cd(국가 영문코드)",
      "display": "국가 영문코드",
      "type": "string",
      "unit": null
    },
    {
      "key": "mass_unit_cd",
      "label": "mass_unit_cd(질량단위코드 ST_CODE_MST.CD_GRP = 'WT000')",
      "display": "질량단위코드 ST_CODE_MST.CD_GRP = 'WT000'",
      "type": "string",
      "unit": null
    },
    {
      "key": "prdctn_quty",
      "label": "prdctn_quty(생산량)",
      "display": "생산량",
      "type": "number",
      "unit": null
    },
    {
      "key": "se_cd",
      "label": "se_cd([샘플확장] 구분코드)",
      "display": "[샘플확장] 구분코드",
      "type": "string",
      "unit": null
    },
    {
      "key": "prdctn_quty_ton",
      "label": "prdctn_quty_ton([샘플확장] 생산량(톤환산))",
      "display": "[샘플확장] 생산량(톤환산)",
      "type": "number",
      "unit": null
    }
  ],
  "rows_typed": [
    [
      "MNRL0006",
      "2026",
      "US",
      "TON",
      3984.0,
      "DEV",
      3984.0
    ],
    [
      "MNRL0006",
      "2026",
      "ID",
      "TON",
      9296.0,
      "DEV",
      9296.0
    ],
    [
      "MNRL0006",
      "2026",
      "CN",
      "TON",
      21248.0,
      "DEV",
      21248.0
    ],
    [
      "MNRL0006",
      "2026",
      "CL",
      "TON",
      6640.0,
      "DEV",
      6640.0
    ],
    [
      "MNRL0006",
      "2026",
      "CD",
      "TON",
      5312.0,
      "DEV",
      5312.0
    ]
  ],
  "markdown": "| mnrknd_unq_cd(광종고유코드 KO_HS_HIGH_GROUP.MNRKND_UNQ_CD) | crtr_yr(기준년도) | ntn_eng_cd(국가 영문코드) | mass_unit_cd(질량단위코드 ST_CODE_MST.CD_GRP = 'WT000') | prdctn_quty(생산량) | se_cd([샘플확장] 구분코드) | prdctn_quty_ton([샘플확장] 생산량(톤환산)) |\n| --- | --- | --- | --- | --- | --- | --- |\n| MNRL0006 | 2026 | US | TON | 3984.0 | DEV | 3984.0 |\n| MNRL0006 | 2026 | ID | TON | 9296.0 | DEV | 9296.0 |\n| MNRL0006 | 2026 | CN | TON | 21248.0 | DEV | 21248.0 |\n| MNRL0006 | 2026 | CL | TON | 6640.0 | DEV | 6640.0 |\n| MNRL0006 | 2026 | CD | TON | 5312.0 | DEV | 5312.0 |",
  "chart_hint": {
    "recommended": "bar",
    "alternatives": [
      "pie"
    ],
    "reason": "단일 시점(2026) 스냅샷 — ntn_eng_cd별 비교"
  },
  "meta": {
    "source_index": 2,
    "source": "public.KO_RSRC_PRDCTN_QUTY · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(희토류) (기준시점 2026~2026, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))",
    "row_count": 5
  },
  "source_index": 2,
  "source": "public.KO_RSRC_PRDCTN_QUTY · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(희토류) (기준시점 2026~2026, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
}
```

`chart` 이벤트(원문 그대로):

```json
{
  "schema_version": 1,
  "block_id": "c2-1",
  "data_ref": "t2-1",
  "spec": {
    "kind": "bar",
    "alternatives": [
      "pie"
    ],
    "x": "ntn_eng_cd",
    "x_type": "category",
    "x_format": null,
    "series": [
      "prdctn_quty"
    ],
    "group": null,
    "sort_x_ascending": false,
    "title": "생산량"
  },
  "meta": {
    "source_index": 2,
    "source": "public.KO_RSRC_PRDCTN_QUTY · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(희토류) (기준시점 2026~2026, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
  },
  "source_index": 2,
  "source": "public.KO_RSRC_PRDCTN_QUTY · KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(희토류) (기준시점 2026~2026, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
}
```

`done` 이벤트:

```json
{
  "done": true,
  "citations": [
    {
      "index": 2,
      "kind": "structured",
      "source": "public.KO_RSRC_PRDCTN_QUTY",
      "section": "KOMIS 원천 · KO_RSRC_PRDCTN_QUTY(희토류)",
      "as_of": "2026~2026, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음)",
      "unit": null
    }
  ],
  "bogus_citations": [],
  "abstained": false
}
```

그리는 방법: X=`ntn_eng_cd`(원본 순서), 막대 1계열(`prdctn_quty`). `prdctn_quty_ton`은 값이 완전히 같아 계열에서 제외됐다. 계열 1개·범주 5개·전부 양수라 `alternatives: ["pie"]` — 구성비 토글을 제공하면 된다.


### 예제 3 — 단일 시점 범주, 계열 2개 → `bar` (동 국가별 수입, KO_CSTM_CMMRC)

질문: `동 국내 수입 현황 국가별로 보여줘`
이벤트 수: `{"session": 1, "status": 5, "delta": 226, "table": 1, "chart": 1, "done": 1}`

답변 본문(delta 누적, 취소선 필터 통과 후 — `~`가 `\~`로 이스케이프된 것에 주목):

```markdown
2026년 9월 9일 기준 동의 국가별 수입 현황은 다음과 같습니다. 해당 데이터의 실제 조회기간은 2026-09-09\~2026-09-09입니다. [1]

| 대상국가 | 수입중량 | 수입금액 |
| :--- | :--- | :--- |
| 남아프리카공화국 | 1,853.68 | 21,808,000.0 |
| 캐나다 | 383.52 | 4,512,000.0 |
| 브라질 | 255.68 | 3,008,000.0 |
| 중국 | 191.76 | 2,256,000.0 |
| 호주 | 159.8 | 1,880,000.0 |

[1]

⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다 — 실제 값이 아닙니다.

출처:
- [1] public.KO_CSTM_CMMRC · KOMIS 원천 · KO_CSTM_CMMRC(동) (기준시점 2026-09-09\~2026-09-09, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))
```

`table` 이벤트(원문 그대로):

```json
{
  "schema_version": 1,
  "block_id": "t1-1",
  "columns": [
    "hs_cd(HS Code)",
    "crtr_ymd(기준일자)",
    "trgt_ntn_cd(대상국가코드)",
    "incm_weig(수입중량)",
    "incm_amt(수입금액)",
    "exp_weig(수출중량)",
    "exp_amt(수출금액)",
    "trgt_ntn(대상국가)",
    "item_nm(품목명)"
  ],
  "rows": [
    [
      "9900000801",
      "20260909",
      "ZA",
      "1853.68",
      "21808000.0",
      "0.0",
      "0.0",
      "남아프리카공화국",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      "9900000801",
      "20260909",
      "CA",
      "383.52",
      "4512000.0",
      "0.0",
      "0.0",
      "캐나다",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      "9900000801",
      "20260909",
      "BR",
      "255.68",
      "3008000.0",
      "0.0",
      "0.0",
      "브라질",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      "9900000801",
      "20260909",
      "CN",
      "191.76",
      "2256000.0",
      "0.0",
      "0.0",
      "중국",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      "9900000801",
      "20260909",
      "AU",
      "159.8",
      "1880000.0",
      "0.0",
      "0.0",
      "호주",
      "[DEV_DUMMY] 동 품목A"
    ]
  ],
  "columns_meta": [
    {
      "key": "hs_cd",
      "label": "hs_cd(HS Code)",
      "display": "HS Code",
      "type": "number",
      "unit": null
    },
    {
      "key": "crtr_ymd",
      "label": "crtr_ymd(기준일자)",
      "display": "기준일자",
      "type": "date",
      "unit": null
    },
    {
      "key": "trgt_ntn_cd",
      "label": "trgt_ntn_cd(대상국가코드)",
      "display": "대상국가코드",
      "type": "string",
      "unit": null
    },
    {
      "key": "incm_weig",
      "label": "incm_weig(수입중량)",
      "display": "수입중량",
      "type": "number",
      "unit": null
    },
    {
      "key": "incm_amt",
      "label": "incm_amt(수입금액)",
      "display": "수입금액",
      "type": "number",
      "unit": null
    },
    {
      "key": "exp_weig",
      "label": "exp_weig(수출중량)",
      "display": "수출중량",
      "type": "number",
      "unit": null
    },
    {
      "key": "exp_amt",
      "label": "exp_amt(수출금액)",
      "display": "수출금액",
      "type": "number",
      "unit": null
    },
    {
      "key": "trgt_ntn",
      "label": "trgt_ntn(대상국가)",
      "display": "대상국가",
      "type": "string",
      "unit": null
    },
    {
      "key": "item_nm",
      "label": "item_nm(품목명)",
      "display": "품목명",
      "type": "string",
      "unit": null
    }
  ],
  "rows_typed": [
    [
      9900000801.0,
      "20260909",
      "ZA",
      1853.68,
      21808000.0,
      0.0,
      0.0,
      "남아프리카공화국",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      9900000801.0,
      "20260909",
      "CA",
      383.52,
      4512000.0,
      0.0,
      0.0,
      "캐나다",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      9900000801.0,
      "20260909",
      "BR",
      255.68,
      3008000.0,
      0.0,
      0.0,
      "브라질",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      9900000801.0,
      "20260909",
      "CN",
      191.76,
      2256000.0,
      0.0,
      0.0,
      "중국",
      "[DEV_DUMMY] 동 품목A"
    ],
    [
      9900000801.0,
      "20260909",
      "AU",
      159.8,
      1880000.0,
      0.0,
      0.0,
      "호주",
      "[DEV_DUMMY] 동 품목A"
    ]
  ],
  "markdown": "| hs_cd(HS Code) | crtr_ymd(기준일자) | trgt_ntn_cd(대상국가코드) | incm_weig(수입중량) | incm_amt(수입금액) | exp_weig(수출중량) | exp_amt(수출금액) | trgt_ntn(대상국가) | item_nm(품목명) |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| 9900000801 | 20260909 | ZA | 1853.68 | 21808000.0 | 0.0 | 0.0 | 남아프리카공화국 | [DEV_DUMMY] 동 품목A |\n| 9900000801 | 20260909 | CA | 383.52 | 4512000.0 | 0.0 | 0.0 | 캐나다 | [DEV_DUMMY] 동 품목A |\n| 9900000801 | 20260909 | BR | 255.68 | 3008000.0 | 0.0 | 0.0 | 브라질 | [DEV_DUMMY] 동 품목A |\n| 9900000801 | 20260909 | CN | 191.76 | 2256000.0 | 0.0 | 0.0 | 중국 | [DEV_DUMMY] 동 품목A |\n| 9900000801 | 20260909 | AU | 159.8 | 1880000.0 | 0.0 | 0.0 | 호주 | [DEV_DUMMY] 동 품목A |",
  "chart_hint": {
    "recommended": "bar",
    "alternatives": [],
    "reason": "단일 시점(20260909) 스냅샷 — trgt_ntn별 비교"
  },
  "meta": {
    "source_index": 1,
    "source": "public.KO_CSTM_CMMRC · KOMIS 원천 · KO_CSTM_CMMRC(동) (기준시점 2026-09-09~2026-09-09, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))",
    "row_count": 5
  },
  "source_index": 1,
  "source": "public.KO_CSTM_CMMRC · KOMIS 원천 · KO_CSTM_CMMRC(동) (기준시점 2026-09-09~2026-09-09, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
}
```

`chart` 이벤트(원문 그대로):

```json
{
  "schema_version": 1,
  "block_id": "c1-1",
  "data_ref": "t1-1",
  "spec": {
    "kind": "bar",
    "alternatives": [],
    "x": "trgt_ntn",
    "x_type": "category",
    "x_format": null,
    "series": [
      "incm_weig",
      "incm_amt"
    ],
    "group": null,
    "sort_x_ascending": false,
    "title": "수입중량 · 수입금액"
  },
  "meta": {
    "source_index": 1,
    "source": "public.KO_CSTM_CMMRC · KOMIS 원천 · KO_CSTM_CMMRC(동) (기준시점 2026-09-09~2026-09-09, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
  },
  "source_index": 1,
  "source": "public.KO_CSTM_CMMRC · KOMIS 원천 · KO_CSTM_CMMRC(동) (기준시점 2026-09-09~2026-09-09, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음))"
}
```

`done` 이벤트:

```json
{
  "done": true,
  "citations": [
    {
      "index": 1,
      "kind": "structured",
      "source": "public.KO_CSTM_CMMRC",
      "section": "KOMIS 원천 · KO_CSTM_CMMRC(동)",
      "as_of": "2026-09-09~2026-09-09, 최신순 5건만 제공됨(요청한 전체 기간이 아닐 수 있음)",
      "unit": null
    }
  ],
  "bogus_citations": [],
  "abstained": false
}
```

그리는 방법: X=`trgt_ntn`(국가명 — `trgt_ntn_cd` 코드 열보다 사람이 읽는 열을 우선 선택), 묶음막대 2계열(`incm_weig`·`incm_amt`). `exp_weig`·`exp_amt`는 전 행 0이라 제외, `hs_cd`는 고정값이라 제외. 계열이 2개라 pie 대안은 없다.


## 취소선(SSE 직전 처리)

출처 푸터·본문의 기간 표기(`2026-09-02~2026-09-08`, `2026~2026`)에 든 단일 `~`가 GFM
렌더러에서 취소선으로 해석되던 문제(2026-09-15 프론트 캡처)를 서버가 SSE 직전에 막는다:
단일 `~`는 `\~`로 이스케이프(위 예제 본문 참고), 명시적 `~~…~~`/`<del>` 스팬은 내용째
제거. 마크다운으로 렌더하면 `~`로 보인다. `done.citations[].as_of`·`table.rows` 같은
JSON 데이터 필드는 원문 그대로다.

## 호환·버전

- `/prichat`과 계약이 같다. 차이는 private에서 `indicator_*` 3개 page_id(시장전망·
  수급안정·광물종합지수)가 추가로 나온다는 것뿐이며, 그 표는 `group`(예:
  `indx_se_cd`)이 붙는 경우가 많다.
- `schema_version` 1 유지. 필드 추가는 버전 유지, 의미 변경은 증가.
- 참고 구현: `inhouse/streamlit_demo/chatbot.py::_render_chart`(line/bar, `group` 피벗).

## 서버 구현 위치

- `inhouse/rag_core/ragkit/chatbot_events.py`: `recommend_chart()`·`table_block()`·`chart_spec()`
- `inhouse/rag_core/ragkit/chatbot.py::_multimodal_events()`: public/private 공통
- `inhouse/rag_chat/app/streaming.py`: `StrikethroughFilter`
- 단위 테스트: `inhouse/rag_chat/tests/test_structured_blocks.py`
