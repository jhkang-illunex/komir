# rag_chat 구조화 블록(table·chart) 공통 명세 + 추천 차트 종류 — 프론트 팀용

작성 2026-09-16. **적용 범위: `POST /pubchat`·`POST /prichat` 공통.** 2026-09-13
private 전용으로 도입한 블록 이벤트(`rag_chat_prichat_구조화블록_명세_260913.md`,
이제 역사 기록)를 public에도 그대로 적용하고, 표 블록에 **추천 차트 종류**를
같이 싣는다. 구 `image`(PNG base64) 이벤트는 두 엔드포인트 모두에서 **제거**됐다.

## 0. 2026-09-13 명세 대비 변경점

| 항목 | 2026-09-13 | 2026-09-16(현행) |
| --- | --- | --- |
| 적용 엔드포인트 | `/prichat`만 | `/pubchat`·`/prichat` 공통 |
| `image` 이벤트 | public에서만 발송 | 제거(양쪽 모두 안 옴) |
| `table.chart_hint` | 없음 | 신설 — `{recommended, alternatives, reason}` |
| `table.columns_meta[].display` | 없음 | 신설 — 헤더 괄호 안 한글 설명 |
| `table.rows_typed` 빈 값 | `"None"` 문자열 그대로 | `null` (DB NULL은 타입 무관 null) |
| 숫자열 판정 | 셀 하나라도 `None`이면 문자열 취급 | 빈 값은 건너뛰고 숫자가 하나라도 있으면 number |
| `chart.spec` | kind·x·x_type·series·sort_x_ascending·title | + `alternatives`·`x_format`·`group` |
| 차트 종류 | line·bar | line·bar·pie(대안) — §4 추천 규칙 |
| 계열 중복 | 톤환산 중복 열도 계열 | 값이 완전히 같은 열은 첫 열만 |
| 취소선 | 없음 | SSE 직전 제거·이스케이프(§6) |

## 1. 이벤트 순서(변경 없음)

`session` → `status`(1..4, 여러 번) → `delta`* → **`table`* / `chart`*** → `done`.
`table`·`chart`는 답변 텍스트가 끝난 뒤, `done` 전에 온다. 인용된 근거에서만
만든다(인용 안 된 조회 결과의 표는 내지 않는다). 표마다 `table` 1건, 추천 차트가
있으면 그 직후 `chart` 1건. 데이터 블록은 LLM이 아니라 서버가 결정론적으로
만든다(근거 텍스트의 마크다운 표 파싱 → 타입 판정 → 블록).

## 2. `table` 이벤트

```json
{
  "schema_version": 1,
  "block_id": "t1-1",
  "columns": ["crtr_ymd(기준일자)", "lowst_prc(최저가격)", "hghst_prc(최고가격)"],
  "rows": [["20260908", "16410.62", "17080.44"], ["20260907", "None", "16733.26"]],
  "columns_meta": [
    {"key": "crtr_ymd",  "label": "crtr_ymd(기준일자)",  "display": "기준일자", "type": "date",   "unit": null},
    {"key": "lowst_prc", "label": "lowst_prc(최저가격)", "display": "최저가격", "type": "number", "unit": null},
    {"key": "hghst_prc", "label": "hghst_prc(최고가격)", "display": "최고가격", "type": "number", "unit": null}
  ],
  "rows_typed": [["20260908", 16410.62, 17080.44], ["20260907", null, 16733.26]],
  "markdown": "| crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) |\n| --- | --- | --- |\n| 20260908 | 16410.62 | 17080.44 |\n| 20260907 | None | 16733.26 |",
  "chart_hint": {"recommended": "line", "alternatives": [], "reason": "시점당 1행인 시계열, 시점 7개"},
  "meta": {"source_index": 1, "source": "public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-08-31~2026-09-08, 최신순 8건만 제공됨(요청한 전체 기간이 아닐 수 있음))", "row_count": 7},
  "source_index": 1,
  "source": "public.KO_MNRL_PRC · KOMIS 원천 · KO_MNRL_PRC(니켈) (기준시점 2026-08-31~2026-09-08, …)"
}
```

- `block_id`: `t{근거번호}-{표순번}`, 같은 턴 안에서 유일. 구 클라이언트 호환 키
  `columns`·`rows`(문자열 그대로)·`source_index`·`source`는 그대로 유지.
- `columns_meta[]`: `key`는 헤더에서 `(설명)`을 뗀 컬럼 키, `display`는 괄호 안
  설명(없으면 key) — 축 제목·범례에 쓴다. `type`은 `date`(KOMIS 기준일 컬럼
  `crtr_ymd`/`crtr_yr`, 값은 `YYYYMMDD`·`YYYYMM`·`YYYY` 문자열) · `number`(빈 값을
  제외한 모든 셀이 숫자, 콤마·% 허용) · `string`. `unit`은 전 행이 `%`로 끝나면
  `"%"`, 그 외 `null`.
- `rows_typed`: `number` 열은 float, DB NULL(원문 `"None"`·빈칸)은 열 타입과
  무관하게 `null`, 나머지는 원문 문자열.
- `markdown`: 답변 텍스트(delta 누적본) 안에 같은 표가 마크다운으로 남아 있다.
  프론트가 자기 표 컴포넌트로 바꾸려면 이 문자열을 본문에서 찾아 치환한다.
  본문과 같은 취소선 필터(§6)를 거친 문자열이라 본문과 일치한다.
- `chart_hint`: 이 표에 추천하는 차트. `recommended`가 `null`이면 차트 없음(표만).
  `alternatives`는 프론트가 토글로 제공해도 되는 대안, `reason`은 판정 사유
  (사람용 문구, 파싱하지 말 것). 같은 판정으로 만든 `chart` 이벤트가 뒤따르므로
  둘 중 편한 쪽을 쓰면 된다.

## 3. `chart` 이벤트

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
    "series": ["lowst_prc", "hghst_prc", "cmerc_prc", "invt"],
    "group": null,
    "sort_x_ascending": true,
    "title": "최저가격 · 최고가격 · 통상가격 · 재고"
  },
  "meta": {"source_index": 1, "source": "…"},
  "source_index": 1,
  "source": "…"
}
```

- 데이터는 싣지 않는다. `data_ref`가 가리키는 `table` 블록의 `rows_typed`/
  `columns_meta`를 쓴다(`table`이 항상 먼저 온다).
- `kind`: `line` | `bar` | `pie` 중 추천값(§4). `alternatives`: 대안 목록.
- `x`: X축 컬럼 키. `x_type`이 `date`면 `x_format`(`YYYYMMDD`|`YYYYMM`|`YYYY`)이
  값 형식이고 `sort_x_ascending=true` — 과거→최근으로 정렬해 그린다(KOMIS 원본은
  최신순이라 그대로 그리면 거꾸로 읽힌다). `category`면 원본 순서 유지.
- `series`: Y 계열 컬럼 키 목록. 값이 전부 같은 열(식별자)·전부 빈 열·앞선 계열과
  값이 완전히 같은 열(`*_quty` ↔ `*_quty_ton`)은 빠져 있다. `display`로 범례를
  붙이면 된다.
- `group`: 값이 있으면(예: `ntn_eng_cd`) 같은 X(연도)에 여러 행(국가)이 있는
  표다 — **계열 하나를 `group` 값별로 펼쳐**(국가별 선/막대) 그린다. `series`가
  여럿이면 첫 계열을 기본으로 두고 나머지는 선택 항목으로 처리하면 된다.
- 축 포맷·단위 표기·색·`pie` 렌더링은 프론트 몫. 스펙은 특정 라이브러리에 묶이지
  않도록 최소로 뒀다.

## 4. 차트 종류와 추천 규칙(서버 `recommend_chart()`, LLM 관여 없음)

| kind | 뜻 | 추천 조건 |
| --- | --- | --- |
| `line` | 시계열 추이 | 날짜열이 X축이고 시점이 **4개 이상** |
| `bar` | 범주 비교 또는 짧은 시계열 | 범주형 X(국가·품목), 또는 날짜열이지만 시점 3개 이하. 계열이 여럿이면 묶음막대, `group`이 있으면 구분값별 막대 |
| `pie` | 단일 계열 구성비 | **대안으로만** — 범주형 X, 계열 1개, 범주 2~8개, 값 전부 양수 |
| (없음) | 표만 | 행 2개 미만, 값이 갈리는 숫자 계열 없음, 시점이 중복되는데 구분 열이 없음 |

판정 순서:
1. 계열(Y) = 숫자열 중 값이 갈리는 열(식별자·고정 코드·전부 빈 열·중복 열 제외).
   없으면 차트 없음.
2. 날짜열(`crtr_ymd`/`crtr_yr`)이 있고 **시점당 1행**이면 시계열 → 시점 4개 이상
   `line`, 미만 `bar`. X=날짜, 오름차순.
3. 날짜열이 있는데 **시점이 1개**(단일 연도 국가별 매장량 등)면 범주형 → X=구분
   열, `bar`(+`pie` 대안). 구분 열은 문자열 열 중 값이 갈리는 것, `_cd`로 끝나지
   않는 사람이 읽는 열(예: `trgt_ntn` 국가명) 우선.
4. 날짜열이 있고 시점도 여럿·구분 열도 있으면(연도×국가, 일자×지수종류) →
   X=날짜, `group`=구분 열, 시점 4개 이상 `line` 아니면 `bar`.
5. 날짜열이 없으면 X=구분 열(없으면 첫 열), `bar`(+`pie` 대안).

KOMIS 원천 page_id별로 실제 나오는 모양(2026-09-16 실측, `KOMIS_RAW_MAX_TIMESTAMPS`
기본 60건 기준):

| page_id(원천 테이블) | 표 모양 | 추천 |
| --- | --- | --- |
| price_* (KO_MNRL_PRC) | 일자당 1행 | `line` (x=crtr_ymd, series=최저·최고·통상가격·재고) |
| indicator_supply (KO_SPDM_STBT_INDX) | 월당 1행 | `line` (x_format `YYYYMM`) |
| indicator_market (KO_MRKT_PRSPECT_IDCT) | 월당 1행, 3건이면 | `bar` (시점 3개) |
| indicator_composite (KO_MNRL_SNTHS_INDX) | 일자×지수종류(HI001~003) | `group`=indx_se_cd, 시점 4개 이상이면 `line` |
| map_mineral (KO_RSRC_BURUDG_QUTY·PRDCTN_QUTY) | 단일 연도×국가 | `bar` + `pie` 대안 (x=ntn_eng_cd, series=매장량/생산량 1개) |
| map_mineral 복수 연도 | 연도×국가 | `group`=ntn_eng_cd, `bar`(연도 2~3개) / `line`(4개 이상) |
| map_korea (KO_CSTM_CMMRC) | 단일 일자×국가 | `bar` (x=trgt_ntn 국가명, series=수입중량·수입금액) |

## 5. 데모 데이터(실제 KOMIS 원천 근거 표 → 블록)

아래는 컨테이너에서 `KomisRawDataRepository.fetch()`로 뽑은 실제 근거 표를 새
`table_block()`/`chart_spec()`에 통과시킨 결과다(2026-09-16). ⚠ 발주 5광종의
KOMIS `ko_*` 데이터는 대부분 개발용 더미(DEV_DUMMY)라 **값은 개발용**이고 모양만
참고할 것. 긴 필드(`markdown`·`source`)는 생략했다.

### 5-A. 시계열 → `line` — 니켈 가격(KO_MNRL_PRC, 가격기준순번 502)

근거 표(일부):

```
| mnrl_prc_crtr_sn(광물가격기준순번) | crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | cmerc_prc(통상가격) | invt(재고) |
| --- | --- | --- | --- | --- | --- |
| 502.0 | 20260908 | 16410.62 | 17080.44 | 16745.53 | 272380.0 |
| 502.0 | 20260907 | 16077.06 | 16733.26 | 16405.16 | 271900.0 |
| 502.0 | 20260904 | 16110.08 | 16767.64 | 16438.86 | 270257.0 |
| … 7행 |
```

`table`(요약): `columns_meta` 타입 = number·**date**·number·number·number·number,
`rows_typed[0]` = `[502.0, "20260908", 16410.62, 17080.44, 16745.53, 272380.0]`,
`chart_hint` = `{"recommended": "line", "alternatives": [], "reason": "시점당 1행인 시계열, 시점 7개"}`.

`chart.spec`:

```json
{"kind": "line", "alternatives": [], "x": "crtr_ymd", "x_type": "date", "x_format": "YYYYMMDD",
 "series": ["lowst_prc", "hghst_prc", "cmerc_prc", "invt"], "group": null,
 "sort_x_ascending": true, "title": "최저가격 · 최고가격 · 통상가격 · 재고"}
```

프론트: X=기준일자(오름차순, `YYYYMMDD`→표시형), 선 4개(범례는 `display`).
`mnrl_prc_crtr_sn`(전 행 502)은 계열에서 빠진다. 재고(27만대)와 가격(1.6만대)의
스케일 차이가 크므로 이중 축 또는 계열 토글은 프론트 판단.

### 5-B. 단일 시점 범주 → `bar` (+`pie`) — 희토류 국가별 생산량(KO_RSRC_PRDCTN_QUTY)

```
| mnrknd_unq_cd(광종고유코드 …) | crtr_yr(기준년도) | ntn_eng_cd(국가 영문코드) | mass_unit_cd(…) | prdctn_quty(생산량) | se_cd([샘플확장] 구분코드) | prdctn_quty_ton([샘플확장] 생산량(톤환산)) |
| --- | --- | --- | --- | --- | --- | --- |
| MNRL1001 | 2026 | US | TON | 3040.0 | DEV | 3040.0 |
| MNRL1001 | 2026 | ID | TON | 6080.0 | DEV | 6080.0 |
| MNRL1001 | 2026 | CN | TON | 44080.0 | DEV | 44080.0 |
| MNRL1001 | 2026 | CL | TON | 4560.0 | DEV | 4560.0 |
| MNRL1001 | 2026 | CD | TON | 3800.0 | DEV | 3800.0 |
```

`table.chart_hint` = `{"recommended": "bar", "alternatives": ["pie"], "reason": "단일 시점(2026) 스냅샷 — ntn_eng_cd별 비교"}`

`chart.spec`:

```json
{"kind": "bar", "alternatives": ["pie"], "x": "ntn_eng_cd", "x_type": "category", "x_format": null,
 "series": ["prdctn_quty"], "group": null, "sort_x_ascending": false, "title": "생산량"}
```

프론트: X=국가코드(원본 순서), 막대 1계열. `prdctn_quty_ton`은 값이 `prdctn_quty`와
완전히 같아 계열에서 제외됐다. 계열이 하나고 5개 범주·전부 양수라 `pie`를
대안으로 제공한다(구성비 토글).

### 5-C. 시점×구분 → `group` — 광물종합지수(KO_MNRL_SNTHS_INDX, HI001~003)

```
| indx_se_cd(광물종합지수순번) | crtr_ymd(기준일자) | indx(지수) | prvdy_cprs(전일대비) | uplmt(상한) | lwlmt(하한) | center(중심(MA)) |
| --- | --- | --- | --- | --- | --- | --- |
| HI003 | 20260905 | 2925.65 | 14.47 | None | None | None |
| HI002 | 20260905 | 3011.24 | 9.57 | None | None | None |
| HI001 | 20260905 | 3651.45 | 23.31 | None | None | None |
| HI003 | 20260904 | 2911.18 | 0.0 | None | None | None |
| HI001 | 20260904 | 3628.15 | 8.42 | None | None | None |
| HI002 | 20260904 | 3001.67 | 15.94 | None | None | None |
```

`table`(요약): `uplmt`·`lwlmt`·`center`는 전부 NULL이라 `type: "string"`,
`rows_typed`에서 `null`. `chart_hint` = `{"recommended": "bar", "alternatives": [], "reason": "시점 2개 × indx_se_cd 구분 — 구분값별 계열"}`
(실제 챗봇 조회는 최신 60건 = 20일치라 시점 4개 이상 → `line`).

`chart.spec`:

```json
{"kind": "bar", "alternatives": [], "x": "crtr_ymd", "x_type": "date", "x_format": "YYYYMMDD",
 "series": ["indx", "prvdy_cprs"], "group": "indx_se_cd", "sort_x_ascending": true, "title": "지수 · 전일대비"}
```

프론트: X=기준일자, `indx`를 `indx_se_cd`(HI001/HI002/HI003)별 계열로 펼쳐 그린다.
`prvdy_cprs`는 선택 항목.

### 5-D. 차트 없음 — 문자열만 있는 표

```
| a | b |
| --- | --- |
| x | y |
| z | w |
```

`table.chart_hint` = `{"recommended": null, "alternatives": [], "reason": "값이 갈리는 숫자 계열 없음"}`,
`chart` 이벤트 없음(억지 차트 금지).

## 6. 취소선 정책(SSE 직전, 2026-09-16)

실측 경위: `/prichat` "코발트 광물종합지표의 최근 12개월 변화" 답변의 출처 푸터에
`(기준시점 2026-08-11~2026-09-05, …)`·`Argus Metal_비철금속_2023~2026_일일 …
(2023-09-21~2024-12/…)`처럼 기간 표기가 여러 개 들어가면서, GFM 렌더러(remark-gfm
`singleTilde` 기본값 등)가 `~…~`를 취소선으로 해석해 물결표 사이 텍스트가 취소선으로
그려졌다. 서버가 SSE로 내보내기 직전에 다음을 적용한다(`rag_chat/app/streaming.py::
StrikethroughFilter`, delta·페이지추천 답변·`table.markdown` 대상):

- 명시적 취소선 스팬 `~~…~~`, `<s>…</s>`·`<del>`·`<strike>`는 **내용째 제거**한다
  (취소된 데이터는 넘기지 않는다).
- 짝 없는 단일 `~`(기간·범위 표기)는 `\~`로 이스케이프한다 — CommonMark 백슬래시
  이스케이프라 어느 마크다운 렌더러든 `~` 글자로 표시되고 취소선이 되지 않는다.
  프론트가 delta를 **마크다운으로 렌더**하면 추가 처리 없이 그대로 보인다. plain
  text로 보여주는 곳이 있다면 `\~`→`~` 치환 한 번이 필요하다.
- 마커가 청크 경계에 걸리는 경우(`~` + `~14,300~` + `~`)도 서버가 청크를 넘겨
  판정한다. `done.citations[].as_of`·`table.rows` 같은 JSON 데이터 필드는 마크다운이
  아니므로 손대지 않는다(원문 `2026-08-11~2026-09-05` 그대로).
- 프론트 캡처(`documents/기획문서/image (1).png`, 2026-09-15 17:14 /prichat "코발트
  광물종합지표의 최근 12개월 변화")에서 함께 드러난 것 두 가지도 정정했다:
  (1) 출처 항목 `[1]~[6]`이 한 문단으로 뭉침 — 마크다운 소프트 줄바꿈이라 붙어
  렌더됐다. 이제 `출처:` 아래 각 항목을 `- [n] …` 목록으로 보낸다.
  (2) 광물종합지수 차트가 톱니 모양 — 같은 일자에 HI001/HI002/HI003 세 행이
  있는데 한 선으로 이어 그렸다. 새 스펙의 `group: "indx_se_cd"`로 지수종류별
  선 3개로 나눠 그릴 것(§3 `group`). `prvdy_cprs`(전일대비, 0 부근)는 `indx`와
  스케일이 달라 기본은 첫 계열만 그리고 나머지는 토글로 두기를 권한다.

## 7. 호환·버전

- `schema_version`은 블록마다 들어간다(현재 1). 이번 변경은 필드 추가·빈 값 표현
  변경(`"None"`→`null`)이라 버전 유지. 의미 변경 시 증가.
- `image` 이벤트는 `/pubchat`·`/prichat` 어디서도 더 이상 오지 않는다. 구
  클라이언트는 `columns`/`rows`로 표만 보게 된다(차트 없음).
- 참고 구현: `inhouse/streamlit_demo/chatbot.py::_render_chart`(line/bar, `group`
  피벗, pie는 bar로 대신 그리고 캡션에만 표시), `_render_table`(캡션에 추천 차트).

## 8. 서버 구현 위치·검증

- `inhouse/rag_core/ragkit/chatbot_events.py`: `recommend_chart()`(추천 규칙 단일
  소스), `table_block()`(`chart_hint`), `chart_spec()`, PNG 렌더 제거.
- `inhouse/rag_core/ragkit/chatbot.py::_multimodal_events()`: profile 분기 제거,
  public/private 공통.
- `inhouse/rag_chat/app/streaming.py`: `StrikethroughFilter`·`strip_strikethrough`,
  `routers/chat.py`가 document·page 두 경로에 적용.
- `inhouse/common/komis_raw.py`: KO_MNRL_PRC에 `LAST_DEL_DT IS NULL` 추가 — 소프트
  삭제 행 11건(전부 기준일자 20270703·최저/최고가 NULL)이 최신순 조회 맨 앞에 와
  "니켈 최신 가격 2027-07-03"처럼 답변·차트를 오염시키던 것을 제거(report_gen도
  같은 조회를 쓰므로 함께 정정됨).
- `inhouse/rag_chat/requirements.txt`: matplotlib·koreanize-matplotlib 제거.
- 단위 테스트: `inhouse/rag_chat/tests/test_structured_blocks.py`(블록 5건 + 취소선
  필터 3건). 라이브 검증 결과는 WORKLOG 2026-09-16.
