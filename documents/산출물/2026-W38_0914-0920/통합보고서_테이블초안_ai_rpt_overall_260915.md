# 테이블 초안 — `public.ai_rpt_overall` (핵심광물 수급위기 진단결과 보고서·전체, 텍스트 섹션)

작성 2026-09-15(초안, 미적용). 원본 양식: `통합보고서_템플릿_전체_260915.md`.

- 1행 = 보고 주차(월요일 `base_ymd`) 1부. 광종 구분 없음.
- 표·차트는 제외. 텍스트 섹션과 본문 문장에 박히는 핵심 수치만 둔다.
- **생성 방식**: RULE = 규칙 엔진이 DB 값으로 결정론적으로 생성 / LLM = 규칙이 만든 수치 근거로 LLM이 서술(원인·해석·정책) / MANUAL = 담당자 입력(외부 지표·수기 정보). "MANUAL→RULE"은 원천 실값이 적재되면 규칙으로 전환.
- 표기 관례는 기존 `public.ai_*`를 따른다(snake_case, `base_ymd varchar(8)`, `mnrknd_unq_cd varchar(12)`, `*_cd`, `frst_reg_dt`/`last_mdfcn_dt`).
- A8 품목별 관리카드는 품목 단위 반복 블록이라 이 테이블에 넣지 않고 기존 `ai_item_card`를 쓴다(§참고).

## 1. 식별·표제 (A0)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| base_ymd | varchar(8) | PK, NOT NULL | RULE | 보고 주차 키(월요일 YYYYMMDD). `ai_dash_diag.base_ymd`와 같은 체계 |
| period_from_ymd | varchar(8) | NOT NULL | RULE | 보고 기간 시작일(A0 "6월 11일~") |
| period_to_ymd | varchar(8) | NOT NULL | RULE | 보고 기간 종료일(A0 "~6월 17일") |
| rpt_year | smallint | NOT NULL | RULE | 보고 연도(’26년도) |
| rpt_week_no | smallint | NOT NULL | RULE | ISO 주차(24주차) |
| title | varchar(200) | NOT NULL | RULE | "핵심광물 수급위기 진단결과 보고서"(고정 문구) |

## 2. 종합 서술문 (A2)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| overall_score | numeric(8,2) | NULL | RULE | 전체 평균 수급 위기지수. 원천 `ai_dash_diag.overall_score`(현재 더미, 산출 로직 확정 후 실값) |
| overall_wow | numeric(8,2) | NULL | RULE | 전주 대비 변화(p). 원천 `ai_dash_diag.overall_wow` |
| overall_level_txt | varchar(20) | NULL | RULE | "전반적으로 [높은\|낮은] 위기 수준" 판정어. overall_score 임계(`ai_threshold`)로 결정 |
| focus_mnrl_cds | varchar(200) | NULL | RULE | "특히 [광종A], [광종B]의 수급 리스크가 심화" 대상 광종코드 목록(쉼표). `ai_mnrl_diag`에서 등급 상향·지수 상승 광종 선별 |
| smry_quant_txt | text | NULL | RULE | 정량 문장: "핵심광물 시장의 전체 평균 수급 위기지수는 [값]로 전주 대비 [N]p [상승\|하락]하였으며, 특히 [광종A], [광종B]의 수급 리스크가 심화되고 있습니다." + "이에 따라 [M]월 [N]주차 [광종A]과 [광종B]의 주간 평균가격도 각각 전주 대비 [X]%, [Y]%의 [상승\|하락]세를 나타내었습니다."(가격: `ko_wkly_mnrl_prc.wow_pct`) |
| smry_cause_txt | text | NULL | LLM | "[원인]가 주요 원인으로 분석됩니다." — smry_quant_txt·`ai_news`·`ai_mnrl_event`를 근거로 작성, 담당자 검수 |
| smry_demand_bg_txt | varchar(500) | NULL | LLM | 첫 문장의 수요 배경("AI 데이터 센터, 반도체 등 전략산업의 수요가 확대되는") |
| smry_supply_bg_txt | varchar(500) | NULL | LLM | 첫 문장의 공급 배경("중동 전쟁, 주요 생산국들의 자원무기화 정책") |

## 3. 진단 결과 요약 (A3) · 위기진단 표 제목 (A4)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| diag_grade_cd | varchar(12) | NULL | RULE | "(수급 [등급])"의 등급 코드(WATCH\|CAUTION\|WARNING\|CRITICAL, `ai_mnrl_diag.grade` 체계). 고시 4단계 표시명(관심/주의/경계/심각) 매핑은 표시 계층 |
| diag_grade_mnrl_txt | varchar(500) | NULL | RULE | "[광종A], [광종B] 등 [N]종" — 해당 등급 광종명 나열(`ai_mnrl_mst.mnrl_nm_ko`) |
| diag_key_txt | varchar(500) | NULL | LLM | "(주요 내용) …" 원인 한 줄 |
| diag_tbl_title_txt | varchar(200) | NULL | RULE | A4 표 제목 "(위기진단) [광종…] 등 총 [N]개 광종 "[등급]" 단계". 표 본체는 프론트가 `ai_mnrl_diag`·`ko_wkly_mnrl_prc`·`ko_cstm_cmmrc`·`ko_rsrc_*`로 구성 |

## 4. 지표 분석·수급상황 판단 (A5)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| idx_anal_txt | text | NULL | RULE | ① 불릿: "핵심광물 [N]종 中 [M]종 수급 이상징후 확인 / 관심등급 [n]종은 가격, 수입 등 모니터링 유지 / 주의등급 [m]종은 수급상황 판단 검토"(`ai_mnrl_diag` 등급 집계) |
| judge_quant_txt | text | NULL | RULE | ② 수치 불릿: "([광종]) 위기진단지표 [값] (전주 대비 [N]p↑), 위기등급 "[등급]" ([N]주 연속)" ×광종 + "`[YY]년 [M]월 [N]주차 가격 상승률(%, 전주 대비): [광종A] [X]%↑, …". 연속 주는 report_gen grade_streak 규칙 |
| judge_basis_txt | varchar(500) | NULL | LLM | ② 판단 근거 문장("중국 이중용도 품목 수출제한 등 정세불안 증가 및 수급위기 발생 가능성") |

## 5. 리스크 분석 (A6)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| geo_risk_idx | numeric(8,2) | NULL | MANUAL→RULE | 지정학 리스크지수 카드 값(pt). 원천 미정(`ai_macro_indc.GPR`은 더미). 실값 적재 전엔 담당자 입력 |
| geo_risk_wow_pct | numeric(8,2) | NULL | MANUAL→RULE | 지정학 리스크지수 전주 대비 % |
| risk1_title | varchar(200) | NULL | LLM | ① 제목(예: 중국의 핵심광물 수출통제 강화) |
| risk1_txt | text | NULL | LLM | ① 서술 문단. "중국의 무역정책 리스크 지수는 [M]월 기준 [값]…" 문장은 원천 없음(MANUAL) |
| risk2_title | varchar(200) | NULL | LLM | ② 제목(예: 중국의 공급 지배력 강화에 따른 가격 변동성 심화) |
| risk2_quant_txt | text | NULL | RULE | ② 정량 문장: "USGS에 따르면, [광종]의 세계 생산량은 `[YY]년 기준 [합계]톤으로 국가별 비중은 [국가1] [%], …로 나타나고 있습니다."(`ko_rsrc_prdctn_quty`, SU=세계합계) + "[M]월[N]주차 [광종]의 가격은 [단위][값]으로 전주 대비 [X]%, 전월 대비 [Y]%, 전년 대비 [Z]%…"(`ko_wkly_mnrl_prc`/`ko_mnrl_prc`) |
| risk2_narr_txt | text | NULL | LLM | ② 해석 문장("중국의 생산비중이 가장 높은 상황에서 수출통제가 지속될 경우 가격변동성은 더욱 심화될 수 있습니다") |
| risk3_title | varchar(200) | NULL | LLM | ③ 제목(예: 중동 전쟁 지속에 따른 공급망 차질 우려 확산) |
| gscpi_val | numeric(8,2) | NULL | MANUAL→RULE | GSCPI 값. 원천 `ai_macro_indc.GSCPI`(현재 더미) |
| gscpi_mom | numeric(8,2) | NULL | MANUAL→RULE | GSCPI 전월 대비(p) |
| gscpi_yoy | numeric(8,2) | NULL | MANUAL→RULE | GSCPI 전년 동월 대비(p) |
| risk3_txt | text | NULL | LLM | ③ 서술. "미 연준에 따르면, 글로벌 공급망 긴장지수(GSCPI)는 `[YY]년 [M]월 기준 [값]로 전월 대비 [N]p 상승, 전년 동월 대비 [N]p 상승" 정량 문장은 규칙이 조립해 앞에 붙임 |
| risk4_title | varchar(200) | NULL | LLM | ④ 제목(예: 특정국 수입편중도 심화) |
| risk4_quant_txt | text | NULL | RULE | ④ 정량 문장: "한국의 [광종] 수입금액은 `[YY]년 기준 U$[값]천으로 전년 대비 [N]% [감소\|증가]하였으며, 국가별 비중은 [국가1] [%], …로 [국가1]이 대부분을 차지"(`ko_cstm_cmmrc` 연 합산·국가 비중) |
| risk4_narr_txt | text | NULL | LLM | ④ 해석 문장("중국의 핵심광물 수출정책의 불확실성 지속으로 … 수급리스크가 높아질 우려") |

## 6. 위기대응 (A7)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| response_txt | text | NULL | LLM | 정책 제언 문단(비축 확대·해외자원개발·모니터링 강화·위기대응체계·대체재·재자원화). 고정 문안 템플릿 + LLM 초안 + 담당자 확정(MANUAL 수정 가능) |

## 7. 생성·검수 메타

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| gen_stts_cd | varchar(12) | NOT NULL, 기본 'DRAFT' | — | DRAFT(자동 생성) \| REVIEWED(검수) \| DONE(확정). CHECK 제약 |
| rule_ver | varchar(30) | NULL | — | 규칙 엔진 버전(report_gen 계열 버전 문자열) |
| llm_model_ver | varchar(30) | NULL | — | LLM 섹션 생성에 쓴 모델 식별자(LLM 미사용 시 NULL) |
| llm_refined_yn | char(1) | NOT NULL, 기본 'N' | — | LLM 섹션이 실제 LLM 산출인지(Y) 규칙/수기 폴백인지(N) |
| reviewer_id | varchar(36) | NULL | — | 검수자 ID(`ai_user_mst`) |
| reviewed_dt | timestamp | NULL | — | 검수 일시 |
| frst_reg_dt | timestamp | NOT NULL, 기본 now() | — | 최초 생성 일시 |
| last_mdfcn_dt | timestamp | NOT NULL, 기본 now() | — | 최종 수정 일시 |

합계 45컬럼. 제약: PK(base_ymd), CHECK(gen_stts_cd), CHECK(llm_refined_yn).

## 생성 방식 집계

| 생성 | 컬럼 수 | 해당 |
|---|---|---|
| RULE | 18 | 식별·표제 6, overall_score/wow/level/focus 4, smry_quant, diag_grade_cd/mnrl, diag_tbl_title, idx_anal, judge_quant, risk2_quant, risk4_quant |
| LLM | 14 | smry_cause/demand_bg/supply_bg, diag_key, judge_basis, risk1~4 title 4, risk1_txt, risk2_narr, risk3_txt, risk4_narr, response |
| MANUAL→RULE | 5 | geo_risk_idx/wow, gscpi_val/mom/yoy |
| 메타 | 8 | gen_stts_cd 등 |

## §참고 — A8 품목별 관리카드(기존 `ai_item_card` 재사용안)

| sections_json 코드 | 생성 | 들어갈 내용 |
|---|---|---|
| VALUE_CHAIN | MANUAL | 밸류체인 설명 |
| STOCKPILE_TREND | MANUAL | 비축 동향 |
| GEO_RISK | MANUAL→RULE | 지정학적 리스크(`ai_mnrl_event` 적재 시 규칙 전환) |
| PRICE_TREND_TXT | RULE | "(기준일) [값] 단위 / 전주평균 대비 X% / 전월평균 대비 Y% / 전년평균 대비 Z%"(`ko_wkly_mnrl_prc`·`ko_mnrl_prc`) |

수치 블록(수입 5개년·수입국 비중·HHI·생산/매장 구성비·수입기업)은 표라 제외.

---

## 전체 컬럼 정리 (`public.ai_rpt_overall`, 45컬럼 — 위 섹션별 표를 합친 한 테이블)

| # | 컬럼 | 타입(크기) | 키/NULL | 생성 | 내용 |
|---|---|---|---|---|---|
| 1 | base_ymd | varchar(8) | PK, NOT NULL | RULE | 보고 주차 키(월요일 YYYYMMDD) |
| 2 | period_from_ymd | varchar(8) | NOT NULL | RULE | 보고 기간 시작일 |
| 3 | period_to_ymd | varchar(8) | NOT NULL | RULE | 보고 기간 종료일 |
| 4 | rpt_year | smallint | NOT NULL | RULE | 보고 연도 |
| 5 | rpt_week_no | smallint | NOT NULL | RULE | ISO 주차 |
| 6 | title | varchar(200) | NOT NULL | RULE | 표제(고정 문구) |
| 7 | overall_score | numeric(8,2) | NULL | RULE | A2 전체 평균 수급 위기지수(ai_dash_diag.overall_score) |
| 8 | overall_wow | numeric(8,2) | NULL | RULE | A2 전주 대비(p) |
| 9 | overall_level_txt | varchar(20) | NULL | RULE | A2 위기 수준 판정어(높은/낮은) |
| 10 | focus_mnrl_cds | varchar(200) | NULL | RULE | A2 리스크 심화 광종코드 목록 |
| 11 | smry_quant_txt | text | NULL | RULE | A2 정량 문장(지수·전주비·광종별 가격 전주비) |
| 12 | smry_cause_txt | text | NULL | LLM | A2 주요 원인 서술 |
| 13 | smry_demand_bg_txt | varchar(500) | NULL | LLM | A2 수요 배경 구절 |
| 14 | smry_supply_bg_txt | varchar(500) | NULL | LLM | A2 공급 배경 구절 |
| 15 | diag_grade_cd | varchar(12) | NULL | RULE | A3 등급 코드(WATCH/CAUTION/WARNING/CRITICAL) |
| 16 | diag_grade_mnrl_txt | varchar(500) | NULL | RULE | A3 해당 등급 광종 나열 |
| 17 | diag_key_txt | varchar(500) | NULL | LLM | A3 주요 내용 한 줄 |
| 18 | diag_tbl_title_txt | varchar(200) | NULL | RULE | A4 위기진단 표 제목 |
| 19 | idx_anal_txt | text | NULL | RULE | A5 ① 지표 분석 불릿 |
| 20 | judge_quant_txt | text | NULL | RULE | A5 ② 광종별 지표·등급·연속 주·가격 상승률 불릿 |
| 21 | judge_basis_txt | varchar(500) | NULL | LLM | A5 ② 판단 근거 문장 |
| 22 | geo_risk_idx | numeric(8,2) | NULL | MANUAL→RULE | A6 지정학 리스크지수(pt) |
| 23 | geo_risk_wow_pct | numeric(8,2) | NULL | MANUAL→RULE | A6 지정학 리스크지수 전주 대비 % |
| 24 | risk1_title | varchar(200) | NULL | LLM | A6 ① 제목 |
| 25 | risk1_txt | text | NULL | LLM | A6 ① 서술(중국 수출통제 등) |
| 26 | risk2_title | varchar(200) | NULL | LLM | A6 ② 제목 |
| 27 | risk2_quant_txt | text | NULL | RULE | A6 ② USGS 생산 비중·가격 전주/전월/전년비 문장 |
| 28 | risk2_narr_txt | text | NULL | LLM | A6 ② 해석 문장 |
| 29 | risk3_title | varchar(200) | NULL | LLM | A6 ③ 제목 |
| 30 | gscpi_val | numeric(8,2) | NULL | MANUAL→RULE | A6 ③ GSCPI 값 |
| 31 | gscpi_mom | numeric(8,2) | NULL | MANUAL→RULE | A6 ③ GSCPI 전월 대비(p) |
| 32 | gscpi_yoy | numeric(8,2) | NULL | MANUAL→RULE | A6 ③ GSCPI 전년 동월 대비(p) |
| 33 | risk3_txt | text | NULL | LLM | A6 ③ 서술(GSCPI 정량 문장은 규칙이 앞에 조립) |
| 34 | risk4_title | varchar(200) | NULL | LLM | A6 ④ 제목 |
| 35 | risk4_quant_txt | text | NULL | RULE | A6 ④ 수입금액·전년비·국가별 비중 문장 |
| 36 | risk4_narr_txt | text | NULL | LLM | A6 ④ 해석 문장 |
| 37 | response_txt | text | NULL | LLM | A7 위기대응 정책 제언 |
| 38 | gen_stts_cd | varchar(12) | NOT NULL, 기본 'DRAFT' | 메타 | DRAFT/REVIEWED/DONE |
| 39 | rule_ver | varchar(30) | NULL | 메타 | 규칙 엔진 버전 |
| 40 | llm_model_ver | varchar(30) | NULL | 메타 | LLM 모델 식별자 |
| 41 | llm_refined_yn | char(1) | NOT NULL, 기본 'N' | 메타 | LLM 실제 산출 여부 |
| 42 | reviewer_id | varchar(36) | NULL | 메타 | 검수자 ID |
| 43 | reviewed_dt | timestamp | NULL | 메타 | 검수 일시 |
| 44 | frst_reg_dt | timestamp | NOT NULL, 기본 now() | 메타 | 최초 생성 일시 |
| 45 | last_mdfcn_dt | timestamp | NOT NULL, 기본 now() | 메타 | 최종 수정 일시 |

## SQL 스키마 (PostgreSQL DDL)

```sql
CREATE TABLE public.ai_rpt_overall (
    base_ymd             varchar(8) NOT NULL,
    period_from_ymd      varchar(8) NOT NULL,
    period_to_ymd        varchar(8) NOT NULL,
    rpt_year             smallint NOT NULL,
    rpt_week_no          smallint NOT NULL,
    title                varchar(200) NOT NULL,
    overall_score        numeric(8,2),
    overall_wow          numeric(8,2),
    overall_level_txt    varchar(20),
    focus_mnrl_cds       varchar(200),
    smry_quant_txt       text,
    smry_cause_txt       text,
    smry_demand_bg_txt   varchar(500),
    smry_supply_bg_txt   varchar(500),
    diag_grade_cd        varchar(12),
    diag_grade_mnrl_txt  varchar(500),
    diag_key_txt         varchar(500),
    diag_tbl_title_txt   varchar(200),
    idx_anal_txt         text,
    judge_quant_txt      text,
    judge_basis_txt      varchar(500),
    geo_risk_idx         numeric(8,2),
    geo_risk_wow_pct     numeric(8,2),
    risk1_title          varchar(200),
    risk1_txt            text,
    risk2_title          varchar(200),
    risk2_quant_txt      text,
    risk2_narr_txt       text,
    risk3_title          varchar(200),
    gscpi_val            numeric(8,2),
    gscpi_mom            numeric(8,2),
    gscpi_yoy            numeric(8,2),
    risk3_txt            text,
    risk4_title          varchar(200),
    risk4_quant_txt      text,
    risk4_narr_txt       text,
    response_txt         text,
    gen_stts_cd          varchar(12) NOT NULL DEFAULT 'DRAFT',
    rule_ver             varchar(30),
    llm_model_ver        varchar(30),
    llm_refined_yn       char(1) NOT NULL DEFAULT 'N',
    reviewer_id          varchar(36),
    reviewed_dt          timestamp,
    frst_reg_dt          timestamp NOT NULL DEFAULT now(),
    last_mdfcn_dt        timestamp NOT NULL DEFAULT now(),
    CONSTRAINT pk_ai_rpt_overall PRIMARY KEY (base_ymd),
    CONSTRAINT ck_ai_rpt_overall_stts CHECK (gen_stts_cd IN ('DRAFT','REVIEWED','DONE')),
    CONSTRAINT ck_ai_rpt_overall_llm CHECK (llm_refined_yn IN ('Y','N'))
);

COMMENT ON TABLE  public.ai_rpt_overall IS '핵심광물 수급위기 진단결과 보고서(전체) 텍스트 섹션. 보고 주차당 1행. 표·차트 제외. 컬럼 COMMENT 앞 [RULE]/[LLM]/[MANUAL]=생성 방식';
COMMENT ON COLUMN public.ai_rpt_overall.base_ymd IS '[RULE] 보고 주차 키(월요일 YYYYMMDD)';
COMMENT ON COLUMN public.ai_rpt_overall.period_from_ymd IS '[RULE] 보고 기간 시작일';
COMMENT ON COLUMN public.ai_rpt_overall.period_to_ymd IS '[RULE] 보고 기간 종료일';
COMMENT ON COLUMN public.ai_rpt_overall.rpt_year IS '[RULE] 보고 연도';
COMMENT ON COLUMN public.ai_rpt_overall.rpt_week_no IS '[RULE] ISO 주차';
COMMENT ON COLUMN public.ai_rpt_overall.title IS '[RULE] 표제(고정 문구)';
COMMENT ON COLUMN public.ai_rpt_overall.overall_score IS '[RULE] A2 전체 평균 수급 위기지수(ai_dash_diag.overall_score)';
COMMENT ON COLUMN public.ai_rpt_overall.overall_wow IS '[RULE] A2 전주 대비(p)';
COMMENT ON COLUMN public.ai_rpt_overall.overall_level_txt IS '[RULE] A2 위기 수준 판정어(높은/낮은)';
COMMENT ON COLUMN public.ai_rpt_overall.focus_mnrl_cds IS '[RULE] A2 리스크 심화 광종코드 목록';
COMMENT ON COLUMN public.ai_rpt_overall.smry_quant_txt IS '[RULE] A2 정량 문장(지수·전주비·광종별 가격 전주비)';
COMMENT ON COLUMN public.ai_rpt_overall.smry_cause_txt IS '[LLM] A2 주요 원인 서술';
COMMENT ON COLUMN public.ai_rpt_overall.smry_demand_bg_txt IS '[LLM] A2 수요 배경 구절';
COMMENT ON COLUMN public.ai_rpt_overall.smry_supply_bg_txt IS '[LLM] A2 공급 배경 구절';
COMMENT ON COLUMN public.ai_rpt_overall.diag_grade_cd IS '[RULE] A3 등급 코드(WATCH/CAUTION/WARNING/CRITICAL)';
COMMENT ON COLUMN public.ai_rpt_overall.diag_grade_mnrl_txt IS '[RULE] A3 해당 등급 광종 나열';
COMMENT ON COLUMN public.ai_rpt_overall.diag_key_txt IS '[LLM] A3 주요 내용 한 줄';
COMMENT ON COLUMN public.ai_rpt_overall.diag_tbl_title_txt IS '[RULE] A4 위기진단 표 제목';
COMMENT ON COLUMN public.ai_rpt_overall.idx_anal_txt IS '[RULE] A5 ① 지표 분석 불릿';
COMMENT ON COLUMN public.ai_rpt_overall.judge_quant_txt IS '[RULE] A5 ② 광종별 지표·등급·연속 주·가격 상승률 불릿';
COMMENT ON COLUMN public.ai_rpt_overall.judge_basis_txt IS '[LLM] A5 ② 판단 근거 문장';
COMMENT ON COLUMN public.ai_rpt_overall.geo_risk_idx IS '[MANUAL→RULE] A6 지정학 리스크지수(pt)';
COMMENT ON COLUMN public.ai_rpt_overall.geo_risk_wow_pct IS '[MANUAL→RULE] A6 지정학 리스크지수 전주 대비 %';
COMMENT ON COLUMN public.ai_rpt_overall.risk1_title IS '[LLM] A6 ① 제목';
COMMENT ON COLUMN public.ai_rpt_overall.risk1_txt IS '[LLM] A6 ① 서술(중국 수출통제 등)';
COMMENT ON COLUMN public.ai_rpt_overall.risk2_title IS '[LLM] A6 ② 제목';
COMMENT ON COLUMN public.ai_rpt_overall.risk2_quant_txt IS '[RULE] A6 ② USGS 생산 비중·가격 전주/전월/전년비 문장';
COMMENT ON COLUMN public.ai_rpt_overall.risk2_narr_txt IS '[LLM] A6 ② 해석 문장';
COMMENT ON COLUMN public.ai_rpt_overall.risk3_title IS '[LLM] A6 ③ 제목';
COMMENT ON COLUMN public.ai_rpt_overall.gscpi_val IS '[MANUAL→RULE] A6 ③ GSCPI 값';
COMMENT ON COLUMN public.ai_rpt_overall.gscpi_mom IS '[MANUAL→RULE] A6 ③ GSCPI 전월 대비(p)';
COMMENT ON COLUMN public.ai_rpt_overall.gscpi_yoy IS '[MANUAL→RULE] A6 ③ GSCPI 전년 동월 대비(p)';
COMMENT ON COLUMN public.ai_rpt_overall.risk3_txt IS '[LLM] A6 ③ 서술(GSCPI 정량 문장은 규칙이 앞에 조립)';
COMMENT ON COLUMN public.ai_rpt_overall.risk4_title IS '[LLM] A6 ④ 제목';
COMMENT ON COLUMN public.ai_rpt_overall.risk4_quant_txt IS '[RULE] A6 ④ 수입금액·전년비·국가별 비중 문장';
COMMENT ON COLUMN public.ai_rpt_overall.risk4_narr_txt IS '[LLM] A6 ④ 해석 문장';
COMMENT ON COLUMN public.ai_rpt_overall.response_txt IS '[LLM] A7 위기대응 정책 제언';
COMMENT ON COLUMN public.ai_rpt_overall.gen_stts_cd IS 'DRAFT/REVIEWED/DONE';
COMMENT ON COLUMN public.ai_rpt_overall.rule_ver IS '규칙 엔진 버전';
COMMENT ON COLUMN public.ai_rpt_overall.llm_model_ver IS 'LLM 모델 식별자';
COMMENT ON COLUMN public.ai_rpt_overall.llm_refined_yn IS 'LLM 실제 산출 여부';
COMMENT ON COLUMN public.ai_rpt_overall.reviewer_id IS '검수자 ID';
COMMENT ON COLUMN public.ai_rpt_overall.reviewed_dt IS '검수 일시';
COMMENT ON COLUMN public.ai_rpt_overall.frst_reg_dt IS '최초 생성 일시';
COMMENT ON COLUMN public.ai_rpt_overall.last_mdfcn_dt IS '최종 수정 일시';
```
