# 테이블 초안 — `public.ai_rpt_mnrl` ([광종] 수급위기 진단결과 보고서·광종별, 텍스트 섹션)

작성 2026-09-15(초안, 미적용). 원본 양식: `통합보고서_템플릿_광종별_260915.md`.

- 1행 = (광종, 보고 주차) 1부. PK `(mnrknd_unq_cd, base_ymd)`, FK `ai_mnrl_mst`.
- 표(B-1~B-4)·차트(B-1~B-5)는 제외. 본문 문장에 박히는 핵심 수치만 둔다.
- 생성 방식 표기(RULE/LLM/MANUAL, MANUAL→RULE)와 표기 관례는 `ai_rpt_overall` 초안과 같다.
- 기존 `ai_mnrl_sect(mnrknd_unq_cd, base_ymd, sect_cd, title, body)`는 세로형 범용 절 저장소다. 이 초안은 양식 1:1 가로형이며 둘 중 하나로 확정해야 한다(§대안).

## 1. 식별·표제 (B0)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| mnrknd_unq_cd | varchar(12) | PK1, FK, NOT NULL | RULE | 광종 고유코드(`ai_mnrl_mst`) |
| base_ymd | varchar(8) | PK2, NOT NULL | RULE | 보고 주차 키(월요일 YYYYMMDD). `ai_mnrl_diag.base_ymd`와 같은 체계 |
| rpt_year | smallint | NOT NULL | RULE | 보고 연도(’26년도) |
| rpt_week_no | smallint | NOT NULL | RULE | ISO 주차(24주차) |
| title | varchar(200) | NOT NULL | RULE | "[광종] 수급위기 진단결과 보고서"(광종명 `ai_mnrl_mst.mnrl_nm_ko`) |

## 2. 종합 서술문 (B2) · 진단 결과 (B3)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| grade_cd | varchar(12) | NULL | RULE | 현재 등급 코드(WATCH\|CAUTION\|WARNING\|CRITICAL). 원천 `ai_mnrl_diag.grade`(현재 더미, 산출 로직 확정 후 실값) |
| grade_nm | varchar(20) | NULL | RULE | 등급 표시명(관심\|주의\|경계\|심각, 고시 별표6 4단계 매핑) |
| score | numeric(8,2) | NULL | RULE | 주차 수급 위험지수. 원천 `ai_mnrl_diag.score` |
| score_wow | numeric(8,2) | NULL | RULE | 전주 대비(p). `ai_mnrl_diag` 주간 차분 |
| score_mom | numeric(8,2) | NULL | RULE | 전월 대비(p). 월평균 차분(대체 원천 `ko_spdm_stbt_indx` 월 지수) |
| grade_streak_wk | smallint | NULL | RULE | "[N]주 연속" — 같은 등급 연속 주수(report_gen grade_streak 규칙) |
| price_wow_pct | numeric(8,2) | NULL | RULE | 주간 평균가격 전주 대비 %. 원천 `ko_wkly_mnrl_prc.wow_pct`(비철 6종) 또는 `ko_mnrl_prc` 주간평균 차분 |
| smry_quant_txt | text | NULL | RULE | 정량 문장: "최근 [광종]의 공급망 리스크는 [등급] 수준에 있으며, [M]월 [N]주차 수급 위험지수는 [값]로 전주 대비 [N]p [상승\|하락]하였습니다." + "이에 따라 [M]월 [N]주차 [광종]의 주간 평균가격도 전주 대비 [X]%의 [상승\|하락]세를 나타내었습니다." |
| smry_cause_txt | text | NULL | LLM | "공급측면에서 [원인]가 주요 원인으로 분석됩니다." — `ai_news`·`ai_mnrl_event` 근거로 작성, 담당자 검수 |
| diag_result_txt | varchar(500) | NULL | RULE | "(수급 [등급]) [지수] (전월 대비 [N]p [상승\|하락]), [N]주 연속 "[등급]"" |
| diag_key_txt | varchar(500) | NULL | LLM | "(주요 내용) …" 원인 한 줄 |

## 3. 가격 서술 (B5)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| price_bg_long_txt | text | NULL | MANUAL | 장기 가격 배경(예: "2022년 전기차 캐즘, 중국의 성장 둔화세 및 글로벌 금리인상에 따른 경기둔화로 …"). 광종별 고정 문안, 변경 시만 갱신(LLM 초안 가능) |
| price_bg_recent_txt | text | NULL | LLM | 최근 전환 배경(사건 기반 서술, 예: "2025년 12월 중국 장시성 … 조광권 취소, 2026년 2월 짐바브웨 정광 금수조치 …") |
| price_foot_txt | varchar(300) | NULL | RULE | 각주 "`[YY]년 [M]월 [N]주차 [광종] 가격 전주 대비 [X]% [상승\|하락], 위기진단지표 전주 대비 [Y]% [상승\|하락]" |

## 4. 가격이격률·가격신호 (B6, 표 제외 — 각주만)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| price_signal_cd | varchar(12) | NULL | RULE | 가격 신호(관심\|주의 이상 …). 가격이격률 산식·임계(평균±1σ·2σ) 확정 후 `ko_wkly_mnrl_prc`로 계산. 확정 전 NULL |
| price_signal_streak_wk | smallint | NULL | RULE | 신호 연속 주수 |
| price_signal_foot_txt | varchar(300) | NULL | RULE | 각주 "`[YY]년 [M]월 [N]주차 가격 변동성 위험신호는 [N]주 연속 [신호]" |

## 5. 국내 수입동향 (B7)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| import_month_ymd | varchar(6) | NULL | RULE | 기준 월 YYYYMM(관세청 최신 적재 월, `ko_cstm_cmmrc.crtr_ymd`) |
| import_month_txt | text | NULL | RULE | ○1 "[광종]의 `[YY]년 [M]월 수입량은 [N]천톤, 수입액은 [N]억달러(전년 대비 [X]% [증가\|감소])이며, 1~[M]월 누적 수입량은 [N]천톤, 수입액은 [N]억달러(전년 대비 [Y]% …)입니다."(`ko_cstm_cmmrc` 월 합산·누적·전년 동기 대비). 실데이터는 텅스텐만 |
| import_cagr_txt | varchar(300) | NULL | RULE | "`[YY-1]년 [광종]의 수입액은 [N]천달러로 연평균 증가율(CAGR)은 [Z]%를 기록하였습니다."(5개년 연 합산 기준) |
| import_ntn_txt | varchar(500) | NULL | RULE | ○2 "주로 [국가1]([%]), [국가2]([%]), [국가3]([%]) 등에서 수입하며, 독점도를 평가하는 HHI(허시만-허핀달 지수)는 [값]을 기록하였습니다."(국가별 incm_amt 비중) |
| import_hhi | numeric(10,2) | NULL | RULE | 수입국 HHI(Σ비중%², 0~10,000) |

## 6. 매장량·생산량 (B8)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| reserve_txt | varchar(500) | NULL | RULE | "(매장량) 세계 매장량은 약 [합계](금속기준), 상위 3개국 점유율은 [CR3]%입니다. * [국가1]([값], [%]), [국가2](…), [국가3](…)"(`ko_rsrc_burudg_quty`, SU=세계합계) |
| production_txt | varchar(500) | NULL | RULE | "(생산량) 세계 생산량은 약 [합계](금속기준), 상위 3개국 점유율 [CR3]%입니다. * …"(`ko_rsrc_prdctn_quty`) |

## 7. 리스크 분석 (B9)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| risk_quant_txt | text | NULL | RULE | 정량 문장: "`[YY]년 기준 세계 [광종] 생산량은 약 [합계](금속량 기준)이며, 주요 생산국은 [국가1]([값], [%]), [국가2](…) 및 [국가3](…)으로, 주요 3국이 `[YY]년 글로벌 생산량의 [CR3]%를 점유하고 있습니다." + "수입구조 측면에서 ’[YY]년 수입량 [N]천톤, 수입액은 [N]억달러이며, 주로 [국가1]([%]), … 등에서 수입하고 있어" |
| risk_narr_txt | text | NULL | LLM | 서술: 산업 수요 배경("[광종]은 전기차, ESS 등 배터리 산업수요가 확대되는 가운데")·지정학 사건·해석("가격변동성이 확대되고 있습니다", "국내 수급 리스크가 높아지고 있습니다") |
| domestic_prod_txt | text | NULL | MANUAL | "국내 [광종] 생산광산은 없으며, 광석 또는 탄산리튬을 수입 가공하거나 … 대부분을 해외수입에 의존하고 있습니다." — 광종별 고정 사실, 변경 시만 갱신 |
| import_struct_txt | text | NULL | RULE | 편중도 판정 문장 "편중도가 [높은\|낮은] 수준으로 수급리스크를 [확대\|완화]시키는 요인입니다." — import_hhi 임계(`ai_threshold`)로 결정 |

## 8. 위기대응 (B10)

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| response_txt | text | NULL | LLM | 정책 제언 문단(비축 확보, 민관 협력·컨소시엄, 국내 생산기반·기술개발·재자원화 등). 광종별 고정 문안 템플릿 + LLM 초안 + 담당자 확정(MANUAL 수정 가능) |

## 9. 생성·검수 메타

| 컬럼 | 타입(크기) | 키/NULL | 생성 | 들어갈 내용 |
|---|---|---|---|---|
| gen_stts_cd | varchar(12) | NOT NULL, 기본 'DRAFT' | — | DRAFT(자동 생성) \| REVIEWED(검수) \| DONE(확정). CHECK 제약 |
| rule_ver | varchar(30) | NULL | — | 규칙 엔진 버전 |
| llm_model_ver | varchar(30) | NULL | — | LLM 섹션 생성 모델 식별자(미사용 시 NULL) |
| llm_refined_yn | char(1) | NOT NULL, 기본 'N' | — | LLM 섹션이 실제 LLM 산출인지(Y) 규칙/수기 폴백인지(N) |
| reviewer_id | varchar(36) | NULL | — | 검수자 ID(`ai_user_mst`) |
| reviewed_dt | timestamp | NULL | — | 검수 일시 |
| frst_reg_dt | timestamp | NOT NULL, 기본 now() | — | 최초 생성 일시 |
| last_mdfcn_dt | timestamp | NOT NULL, 기본 now() | — | 최종 수정 일시 |

합계 42컬럼. 제약: PK(mnrknd_unq_cd, base_ymd), FK(mnrknd_unq_cd→ai_mnrl_mst), CHECK(gen_stts_cd), CHECK(llm_refined_yn). 인덱스: base_ymd.

## 생성 방식 집계

| 생성 | 컬럼 수 | 해당 |
|---|---|---|
| RULE | 27 | 식별·표제 5, grade_cd/nm·score/wow/mom·streak·price_wow 7, smry_quant, diag_result, price_foot, price_signal_cd/streak/foot 3, import_month_ymd/month/cagr/ntn/hhi 5, reserve, production, risk_quant, import_struct |
| LLM | 5 | smry_cause, diag_key, price_bg_recent, risk_narr, response |
| MANUAL | 2 | price_bg_long, domestic_prod |
| 메타 | 8 | gen_stts_cd 등 |

## §대안 — 세로형(기존 `ai_mnrl_sect` 재사용) 절 코드

| sect_cd | 생성 | 대응 컬럼 |
|---|---|---|
| SMRY_QUANT | RULE | smry_quant_txt |
| SMRY_CAUSE | LLM | smry_cause_txt |
| DIAG_RESULT | RULE | diag_result_txt |
| DIAG_KEY | LLM | diag_key_txt |
| PRICE_BG_LONG | MANUAL | price_bg_long_txt |
| PRICE_BG_RECENT | LLM | price_bg_recent_txt |
| PRICE_FOOT | RULE | price_foot_txt |
| PRICE_SIGNAL_FOOT | RULE | price_signal_foot_txt |
| IMPORT_MONTH | RULE | import_month_txt |
| IMPORT_CAGR | RULE | import_cagr_txt |
| IMPORT_NTN | RULE | import_ntn_txt |
| RESERVE | RULE | reserve_txt |
| PRODUCTION | RULE | production_txt |
| RISK_QUANT | RULE | risk_quant_txt |
| RISK_NARR | LLM | risk_narr_txt |
| DOMESTIC_PROD | MANUAL | domestic_prod_txt |
| IMPORT_STRUCT | RULE | import_struct_txt |
| RESPONSE | LLM | response_txt |

세로형을 택하면 수치 컬럼(grade_cd·score·score_wow·score_mom·grade_streak_wk·price_wow_pct·import_hhi 등)은 `ai_mnrl_diag`·별도 지표 테이블에 두고, 생성 방식은 코드 테이블 `ai_rpt_sect_policy(sect_cd, gen_se_cd, src_desc)`로 관리한다. 가로형은 화면 매핑·NOT NULL 검증이 쉽고, 세로형은 절 추가에 유연하다.

---

## 전체 컬럼 정리 (`public.ai_rpt_mnrl`, 42컬럼 — 위 섹션별 표를 합친 한 테이블)

| # | 컬럼 | 타입(크기) | 키/NULL | 생성 | 내용 |
|---|---|---|---|---|---|
| 1 | mnrknd_unq_cd | varchar(12) | PK1, FK, NOT NULL | RULE | 광종 고유코드(ai_mnrl_mst) |
| 2 | base_ymd | varchar(8) | PK2, NOT NULL | RULE | 보고 주차 키(월요일 YYYYMMDD) |
| 3 | rpt_year | smallint | NOT NULL | RULE | 보고 연도 |
| 4 | rpt_week_no | smallint | NOT NULL | RULE | ISO 주차 |
| 5 | title | varchar(200) | NOT NULL | RULE | 표제([광종] 수급위기 진단결과 보고서) |
| 6 | grade_cd | varchar(12) | NULL | RULE | B2/B3 등급 코드(ai_mnrl_diag.grade) |
| 7 | grade_nm | varchar(20) | NULL | RULE | 등급 표시명(관심/주의/경계/심각) |
| 8 | score | numeric(8,2) | NULL | RULE | B2 주차 수급 위험지수 |
| 9 | score_wow | numeric(8,2) | NULL | RULE | B2 전주 대비(p) |
| 10 | score_mom | numeric(8,2) | NULL | RULE | B3 전월 대비(p) |
| 11 | grade_streak_wk | smallint | NULL | RULE | B3 같은 등급 연속 주수 |
| 12 | price_wow_pct | numeric(8,2) | NULL | RULE | B2/B5 주간 평균가격 전주 대비 % |
| 13 | smry_quant_txt | text | NULL | RULE | B2 정량 문장 |
| 14 | smry_cause_txt | text | NULL | LLM | B2 공급측 원인 서술 |
| 15 | diag_result_txt | varchar(500) | NULL | RULE | B3 진단 결과 한 줄 |
| 16 | diag_key_txt | varchar(500) | NULL | LLM | B3 주요 내용 한 줄 |
| 17 | price_bg_long_txt | text | NULL | MANUAL | B5 장기 가격 배경(광종별 고정 문안) |
| 18 | price_bg_recent_txt | text | NULL | LLM | B5 최근 전환 배경 |
| 19 | price_foot_txt | varchar(300) | NULL | RULE | B5 각주(가격·지표 전주비) |
| 20 | price_signal_cd | varchar(12) | NULL | RULE | B6 가격 신호(산식 확정 후) |
| 21 | price_signal_streak_wk | smallint | NULL | RULE | B6 신호 연속 주수 |
| 22 | price_signal_foot_txt | varchar(300) | NULL | RULE | B6 각주 |
| 23 | import_month_ymd | varchar(6) | NULL | RULE | B7 기준 월 YYYYMM |
| 24 | import_month_txt | text | NULL | RULE | B7 당월·누적 수입량/액·전년비 문장 |
| 25 | import_cagr_txt | varchar(300) | NULL | RULE | B7 전년 수입액·CAGR 문장 |
| 26 | import_ntn_txt | varchar(500) | NULL | RULE | B7 수입국 비중·HHI 문장 |
| 27 | import_hhi | numeric(10,2) | NULL | RULE | B7 수입국 HHI |
| 28 | reserve_txt | varchar(500) | NULL | RULE | B8 매장량 문장(세계합계·CR3·상위3국) |
| 29 | production_txt | varchar(500) | NULL | RULE | B8 생산량 문장 |
| 30 | risk_quant_txt | text | NULL | RULE | B9 생산·수입 정량 문장 |
| 31 | risk_narr_txt | text | NULL | LLM | B9 수요 배경·사건·해석 서술 |
| 32 | domestic_prod_txt | text | NULL | MANUAL | B9 국내 생산·가공 구조(고정 사실) |
| 33 | import_struct_txt | text | NULL | RULE | B9 편중도 판정 문장(HHI 임계) |
| 34 | response_txt | text | NULL | LLM | B10 위기대응 정책 제언 |
| 35 | gen_stts_cd | varchar(12) | NOT NULL, 기본 'DRAFT' | 메타 | DRAFT/REVIEWED/DONE |
| 36 | rule_ver | varchar(30) | NULL | 메타 | 규칙 엔진 버전 |
| 37 | llm_model_ver | varchar(30) | NULL | 메타 | LLM 모델 식별자 |
| 38 | llm_refined_yn | char(1) | NOT NULL, 기본 'N' | 메타 | LLM 실제 산출 여부 |
| 39 | reviewer_id | varchar(36) | NULL | 메타 | 검수자 ID |
| 40 | reviewed_dt | timestamp | NULL | 메타 | 검수 일시 |
| 41 | frst_reg_dt | timestamp | NOT NULL, 기본 now() | 메타 | 최초 생성 일시 |
| 42 | last_mdfcn_dt | timestamp | NOT NULL, 기본 now() | 메타 | 최종 수정 일시 |

## SQL 스키마 (PostgreSQL DDL)

```sql
CREATE TABLE public.ai_rpt_mnrl (
    mnrknd_unq_cd           varchar(12) NOT NULL,
    base_ymd                varchar(8) NOT NULL,
    rpt_year                smallint NOT NULL,
    rpt_week_no             smallint NOT NULL,
    title                   varchar(200) NOT NULL,
    grade_cd                varchar(12),
    grade_nm                varchar(20),
    score                   numeric(8,2),
    score_wow               numeric(8,2),
    score_mom               numeric(8,2),
    grade_streak_wk         smallint,
    price_wow_pct           numeric(8,2),
    smry_quant_txt          text,
    smry_cause_txt          text,
    diag_result_txt         varchar(500),
    diag_key_txt            varchar(500),
    price_bg_long_txt       text,
    price_bg_recent_txt     text,
    price_foot_txt          varchar(300),
    price_signal_cd         varchar(12),
    price_signal_streak_wk  smallint,
    price_signal_foot_txt   varchar(300),
    import_month_ymd        varchar(6),
    import_month_txt        text,
    import_cagr_txt         varchar(300),
    import_ntn_txt          varchar(500),
    import_hhi              numeric(10,2),
    reserve_txt             varchar(500),
    production_txt          varchar(500),
    risk_quant_txt          text,
    risk_narr_txt           text,
    domestic_prod_txt       text,
    import_struct_txt       text,
    response_txt            text,
    gen_stts_cd             varchar(12) NOT NULL DEFAULT 'DRAFT',
    rule_ver                varchar(30),
    llm_model_ver           varchar(30),
    llm_refined_yn          char(1) NOT NULL DEFAULT 'N',
    reviewer_id             varchar(36),
    reviewed_dt             timestamp,
    frst_reg_dt             timestamp NOT NULL DEFAULT now(),
    last_mdfcn_dt           timestamp NOT NULL DEFAULT now(),
    CONSTRAINT pk_ai_rpt_mnrl PRIMARY KEY (mnrknd_unq_cd, base_ymd),
    CONSTRAINT fk_ai_rpt_mnrl_mnrl FOREIGN KEY (mnrknd_unq_cd) REFERENCES public.ai_mnrl_mst (mnrknd_unq_cd),
    CONSTRAINT ck_ai_rpt_mnrl_stts CHECK (gen_stts_cd IN ('DRAFT','REVIEWED','DONE')),
    CONSTRAINT ck_ai_rpt_mnrl_llm CHECK (llm_refined_yn IN ('Y','N'))
);

CREATE INDEX ix_ai_rpt_mnrl_base_ymd ON public.ai_rpt_mnrl (base_ymd);

COMMENT ON TABLE  public.ai_rpt_mnrl IS '[광종] 수급위기 진단결과 보고서(광종별) 텍스트 섹션. (광종, 보고 주차)당 1행. 표·차트 제외. 컬럼 COMMENT 앞 [RULE]/[LLM]/[MANUAL]=생성 방식';
COMMENT ON COLUMN public.ai_rpt_mnrl.mnrknd_unq_cd IS '[RULE] 광종 고유코드(ai_mnrl_mst)';
COMMENT ON COLUMN public.ai_rpt_mnrl.base_ymd IS '[RULE] 보고 주차 키(월요일 YYYYMMDD)';
COMMENT ON COLUMN public.ai_rpt_mnrl.rpt_year IS '[RULE] 보고 연도';
COMMENT ON COLUMN public.ai_rpt_mnrl.rpt_week_no IS '[RULE] ISO 주차';
COMMENT ON COLUMN public.ai_rpt_mnrl.title IS '[RULE] 표제([광종] 수급위기 진단결과 보고서)';
COMMENT ON COLUMN public.ai_rpt_mnrl.grade_cd IS '[RULE] B2/B3 등급 코드(ai_mnrl_diag.grade)';
COMMENT ON COLUMN public.ai_rpt_mnrl.grade_nm IS '[RULE] 등급 표시명(관심/주의/경계/심각)';
COMMENT ON COLUMN public.ai_rpt_mnrl.score IS '[RULE] B2 주차 수급 위험지수';
COMMENT ON COLUMN public.ai_rpt_mnrl.score_wow IS '[RULE] B2 전주 대비(p)';
COMMENT ON COLUMN public.ai_rpt_mnrl.score_mom IS '[RULE] B3 전월 대비(p)';
COMMENT ON COLUMN public.ai_rpt_mnrl.grade_streak_wk IS '[RULE] B3 같은 등급 연속 주수';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_wow_pct IS '[RULE] B2/B5 주간 평균가격 전주 대비 %';
COMMENT ON COLUMN public.ai_rpt_mnrl.smry_quant_txt IS '[RULE] B2 정량 문장';
COMMENT ON COLUMN public.ai_rpt_mnrl.smry_cause_txt IS '[LLM] B2 공급측 원인 서술';
COMMENT ON COLUMN public.ai_rpt_mnrl.diag_result_txt IS '[RULE] B3 진단 결과 한 줄';
COMMENT ON COLUMN public.ai_rpt_mnrl.diag_key_txt IS '[LLM] B3 주요 내용 한 줄';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_bg_long_txt IS '[MANUAL] B5 장기 가격 배경(광종별 고정 문안)';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_bg_recent_txt IS '[LLM] B5 최근 전환 배경';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_foot_txt IS '[RULE] B5 각주(가격·지표 전주비)';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_signal_cd IS '[RULE] B6 가격 신호(산식 확정 후)';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_signal_streak_wk IS '[RULE] B6 신호 연속 주수';
COMMENT ON COLUMN public.ai_rpt_mnrl.price_signal_foot_txt IS '[RULE] B6 각주';
COMMENT ON COLUMN public.ai_rpt_mnrl.import_month_ymd IS '[RULE] B7 기준 월 YYYYMM';
COMMENT ON COLUMN public.ai_rpt_mnrl.import_month_txt IS '[RULE] B7 당월·누적 수입량/액·전년비 문장';
COMMENT ON COLUMN public.ai_rpt_mnrl.import_cagr_txt IS '[RULE] B7 전년 수입액·CAGR 문장';
COMMENT ON COLUMN public.ai_rpt_mnrl.import_ntn_txt IS '[RULE] B7 수입국 비중·HHI 문장';
COMMENT ON COLUMN public.ai_rpt_mnrl.import_hhi IS '[RULE] B7 수입국 HHI';
COMMENT ON COLUMN public.ai_rpt_mnrl.reserve_txt IS '[RULE] B8 매장량 문장(세계합계·CR3·상위3국)';
COMMENT ON COLUMN public.ai_rpt_mnrl.production_txt IS '[RULE] B8 생산량 문장';
COMMENT ON COLUMN public.ai_rpt_mnrl.risk_quant_txt IS '[RULE] B9 생산·수입 정량 문장';
COMMENT ON COLUMN public.ai_rpt_mnrl.risk_narr_txt IS '[LLM] B9 수요 배경·사건·해석 서술';
COMMENT ON COLUMN public.ai_rpt_mnrl.domestic_prod_txt IS '[MANUAL] B9 국내 생산·가공 구조(고정 사실)';
COMMENT ON COLUMN public.ai_rpt_mnrl.import_struct_txt IS '[RULE] B9 편중도 판정 문장(HHI 임계)';
COMMENT ON COLUMN public.ai_rpt_mnrl.response_txt IS '[LLM] B10 위기대응 정책 제언';
COMMENT ON COLUMN public.ai_rpt_mnrl.gen_stts_cd IS 'DRAFT/REVIEWED/DONE';
COMMENT ON COLUMN public.ai_rpt_mnrl.rule_ver IS '규칙 엔진 버전';
COMMENT ON COLUMN public.ai_rpt_mnrl.llm_model_ver IS 'LLM 모델 식별자';
COMMENT ON COLUMN public.ai_rpt_mnrl.llm_refined_yn IS 'LLM 실제 산출 여부';
COMMENT ON COLUMN public.ai_rpt_mnrl.reviewer_id IS '검수자 ID';
COMMENT ON COLUMN public.ai_rpt_mnrl.reviewed_dt IS '검수 일시';
COMMENT ON COLUMN public.ai_rpt_mnrl.frst_reg_dt IS '최초 생성 일시';
COMMENT ON COLUMN public.ai_rpt_mnrl.last_mdfcn_dt IS '최종 수정 일시';
```
