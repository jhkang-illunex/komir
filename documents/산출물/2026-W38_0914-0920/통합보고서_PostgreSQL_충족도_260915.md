# 통합보고서 섹션별 PostgreSQL 충족도 — 값을 가져올 수 있는 부분 / 없는 부분

작성 2026-09-15(같은 날 재정리: **`mineral_risk` 스키마 제외** — 사용자 확인,
expired/ 파이프라인과 함께 폐기 대상이라 보고서 소스로 쓰지 않는다).
대상: `통합보고서_섹션분해_주간업무정의_260915.md`의 섹션 A0~A8(전체 양식)·
B0~B10(광종별 양식). 판정 근거는 2026-09-15 komis_demo(172.30.1.101:5433)
전 스키마 재스캔 결과 중 **`public` 스키마(공단 원장 `ko_*` 12종 + 본사업
`ai_*` 30종)만**이다.

## 0. `public` 스키마 실데이터 현황(2026-09-15 스캔)

`public.ai_dev_dummy_load`(14,729행)가 개발 더미 행을 키 단위로 추적한다.
아래 "실데이터"는 그 더미를 제외한 것이다.

| 테이블 | 실데이터 | 더미(DEV_DUMMY) | 비고 |
|---|---|---|---|
| `ko_wkly_mnrl_prc` 공단 주간 가격+LME재고 | 비철 6종(동·아연·연·주석·니켈·알루미늄) 각 1,016주, 2007-01~**2026-06-15** | 없음 | cmerc_prc·lowst/hghst·wow_prc/wow_pct·lme_invt·lme_invt_wow |
| `ko_mnrl_prc` 광물가격 일별 | 텅스텐(~2026-01-08)·니켈(~2026-09, 미래일 2027-07-03 1행 포함)·이리듐·로듐(~2026-09-14) | 9,107행(연·팔라듐·루테늄·주석·흑연·망간·백금·네오디뮴 등 185행씩) | 가격기준 SN↔광종은 `ai_prc_mnrl_map`·`ko_mnrl_prc_crtr` |
| `ko_mnrl_snths_indx` 광물종합지수 | HI001~HI003 일별 ~2026-09-05 | 없음 | indx·prvdy_cprs·uplmt/lwlmt/center(MA) |
| `ko_spdm_stbt_indx` 수급안정화지수(월) | 동·니켈·코발트·리튬·아연·텅스텐 6종 ~2026-07 | 없음 | spdm_stbt_indx·real_prc·prvmm_cprs·crisis_yn |
| `ko_mrkt_prspect_idct` 시장전망지표 | 같은 6종 ~2026-07-01 | 없음 | mrkt_prspect_idct·real_prc·prvmm_cprs |
| `ko_cstm_cmmrc` 관세청 무역 | **텅스텐만** 23,310행(HS×국가×월, ~2026-07-01) | 4,150행(다른 광종 100행씩) | hs_cd·trgt_ntn·incm_weig/amt·exp_weig/amt |
| `ko_un_cmmrc` UN Comtrade | HS 9종(253090·260500·280530·320649·741980·750110/120/220·820900), 2017~2026-01-01 | 없음 | 광종코드 미매핑(mnrknd_unq_cd null) |
| `ko_rsrc_prdctn_quty` / `ko_rsrc_burudg_quty` USGS 생산·매장 | **텅스텐만**(생산 90행 2019~2025, 매장 84행 ~2025) | 492행씩(그 외 34광종) | 국가코드·톤환산 |
| `ko_wkly_indc` / `ai_macro_indc` 거시지수 | SPGSCI·USD_INDEX 주간(KoreaPDS) ~2026-06-15 / ~2026-08-31 | `ai_macro_indc`의 GSCPI·GPR·LME_PRICE_INDEX 16행 | |
| `ai_mnrl_diag` 광종 주간 진단 | 0행 | 80행 전부(5광종×16주, ~20260831) | score·grade·score_wow_pct·crisis_type·price_vol·event_cnt·pess_prob_pct·smry_* |
| `ai_dash_diag` P1 종합 진단(주 1행) | 0행 | 16행 전부 | overall_score/grade/wow·kpi_*·grade_*_cnt·smry_* |
| `ai_dash_factor` RISK/ACTION 인사이트 | 0행 | 48행 전부 | |
| `ai_news` | 0행 | 4행 전부 | |
| `ai_item_mst` 핵심품목 마스터 | 3건(텅스텐 분말·탄화텅스텐·텅스텐 광석·정광) | 68건 | hs_cd·agency_nm·final_grade_cd·final_grade_from_ymd |
| `ai_item_card` 관리카드 / `ai_item_grade_hist` | 시연 3건(sections_json 샘플) / 2건 | | 내용 없음 |
| `ai_mnrl_event`·`ai_mnrl_sect`·`ai_mnrl_var`·`ai_report`·`ai_menu_smry`·`ai_evid` | 0행(스키마만) | | |
| `ai_threshold` | 3건(시드 임계) | | 가격 신호 임계 아님 |
| `ai_mnrl_mst`·`ai_ntn_mst`·`ai_hs_mnrl_map`·`ai_prc_mnrl_map` | 마스터·매핑 | 일부 더미 | 광종명·국가명·HS↔광종·가격SN↔광종 |

요약하면 **실데이터로 실제 값을 낼 수 있는 광종**은 ①가격: 비철 6종(주간)
+ 텅스텐·니켈·이리듐·로듐(일별) ②지표: 6종(동·니켈·코발트·리튬·아연·
텅스텐) ③관세청·USGS: 텅스텐 1종 ④지수·거시: 광종 무관. 나머지는 더미다.

판정 기호: **가능** = 실데이터 컬럼에서 바로 조회, **부분** = 일부 광종·
일부 항목만(또는 계산 필요), **불가** = `public`에 없음(외부·수기·정성·더미만).

---

## 1. 양식 A — 전체 보고서

| 섹션 | 항목 | 판정 | `public` 출처 · 신선도 · 비고 |
|---|---|---|---|
| A0 | 보고 기간·주차 | 가능 | 계산값. 주차 키는 `ai_dash_diag.base_ymd`(월요일) 형식 |
| A1 | 위험등급 분포(38종 종수) | 불가 | 자리 `ai_dash_diag.grade_critical/warning/caution/watch_cnt` — 더미뿐. 광종별 등급 원천 없음 |
| A1 | 전체 평균 위험지수·전주 대비 | 불가 | 자리 `ai_dash_diag.overall_score/overall_wow` — 더미뿐 |
| A1 | 진단지표 추이 | 부분 | 진단 지수 자체는 없음. 대체 가능한 실데이터 시계열: `ko_spdm_stbt_indx`(수급안정화지수, 6종, 월)·`ko_mrkt_prspect_idct`(시장전망지표, 6종)·`ko_mnrl_snths_indx`(종합지수, 일별) |
| A1 | 육각 레이더(요인) | 불가 | 자리 `ai_mnrl_var`(0행). 요인 값 원천 없음 |
| A2 | 종합 서술 — 정량(평균지수·전주비) | 불가 | 진단 지수 없음 |
| A2 | 종합 서술 — 가격 전주비 | 부분 | `ko_wkly_mnrl_prc.wow_pct`(비철 6종, ~2026-06-15) / `ko_mnrl_prc` 일별→주간평균(텅스텐·니켈·이리듐·로듐) |
| A2 | 종합 서술 — 원인(관세·전쟁·수출통제) | 불가 | 정성. `ai_news`·`ai_mnrl_event`는 더미/0행 |
| A3 | 등급별 광종 목록 | 불가 | 자리 `ai_mnrl_diag.grade` — 더미뿐 |
| A3 | 주요 내용 | 불가 | 정성 |
| A4 | 진단지표 | 불가 | 자리 `ai_mnrl_diag.score` — 더미. 대체: `ko_spdm_stbt_indx.spdm_stbt_indx`(6종, 월) |
| A4 | 가격·변동률(전주비) | 부분 | `ko_wkly_mnrl_prc.cmerc_prc/wow_pct`(비철 6종) |
| A4 | 수입량(톤)·수입액(천$) | 부분 | `ko_cstm_cmmrc.incm_weig/incm_amt`(HS 합산, 월) — **텅스텐만** 실데이터 |
| A4 | 수입 1위국(비중) | 부분 | `ko_cstm_cmmrc.trgt_ntn` 국가별 집계 — 텅스텐만 |
| A4 | 생산·매장 1위국(비중) | 부분 | `ko_rsrc_prdctn_quty`/`ko_rsrc_burudg_quty` 국가별 — 텅스텐만 실데이터 |
| A5 | 이상징후 종수·등급 연속 주·지표 전주비 | 불가 | 진단 등급·지수 시계열 없음(더미) |
| A5 | 가격 상승률 | 부분 | A4 가격과 동일 |
| A5 | 판단 문장 | 불가 | 정성 |
| A6 | 지정학 리스크지수·전주비 | 불가 | 자리 `ai_macro_indc(indc_cd='GPR')` — 더미 16행 |
| A6 | 국가별 리스크 등급 지도 | 불가 | 없음 |
| A6-① | 중국 수출통제 서술·무역정책 리스크지수 | 불가 | 없음 |
| A6-② | USGS 생산 국가별 비중 | 부분 | `ko_rsrc_prdctn_quty` — 텅스텐만(양식 예시의 텅스텐은 가능, 인듐은 없음) |
| A6-② | 가격 전주/전월/전년비 | 부분 | 텅스텐: `ko_mnrl_prc`(~2026-01-08, 최신 아님). 인듐: 없음 |
| A6-③ | GSCPI | 불가 | `ai_macro_indc.GSCPI` 더미. 실데이터는 SPGSCI·USD_INDEX만 |
| A6-③ | 중동 전쟁 서술 | 불가 | 정성 |
| A6-④ | 국가별 수입액·비중·전년비 | 부분 | `ko_cstm_cmmrc` — 텅스텐만 |
| A7 | 위기대응 제언 | 불가 | 정성. 자리 `ai_dash_factor(ACTION)` 더미 |
| A8 | 소관부서·품목명·HSK코드 | 부분 | `ai_item_mst(item_nm, hs_cd, agency_nm)` 실 3건(텅스텐 계열) |
| A8 | 위기진단 지수·등급 지속기간 | 불가 | `ai_item_mst.final_grade_cd/final_grade_from_ymd`는 정량 산식 미확정(더미) |
| A8 | 밸류체인 설명 | 불가 | `ai_item_card.sections_json` 시연 샘플뿐 |
| A8 | 국내 수입 5개년(량·액) | 부분 | `ko_cstm_cmmrc` 연 합산 — 텅스텐(2014~2026) |
| A8 | 수입국 비중 상위5 + 수입 HHI | 부분 | `ko_cstm_cmmrc` 국가별 집계로 계산 — 텅스텐만. HHI 컬럼은 없어 계산 필요 |
| A8 | 세계 생산 구성비 상위5 + 생산 HHI | 부분 | `ko_rsrc_prdctn_quty`로 계산 — 텅스텐만 |
| A8 | 세계 매장 구성비 + 매장 HHI | 부분 | `ko_rsrc_burudg_quty`로 계산 — 텅스텐만 |
| A8 | 수입기업 | 불가 | 없음 |
| A8 | 가격 동향(차트·전주/전월/전년평균 대비) | 부분 | 비철 6종 `ko_wkly_mnrl_prc`, 텅스텐·니켈·이리듐·로듐 `ko_mnrl_prc`; 평균 대비는 계산 |
| A8 | 비축 동향 | 불가 | 없음(`ai_item_mst.item_type_cd='STOCKPILE'` 분류만) |
| A8 | 지정학적 리스크(사건) | 불가 | 자리 `ai_mnrl_event` 0행 |

## 2. 양식 B — 광종별 보고서

| 섹션 | 항목 | 판정 | `public` 출처 · 신선도 · 비고 |
|---|---|---|---|
| B0 | 광종명·주차 | 가능 | `ai_mnrl_mst.mnrl_nm_ko` |
| B1 | 등급 계기판 | 불가 | 등급 원천 없음(`ai_mnrl_diag.grade` 더미). 유일한 실 신호는 `ko_spdm_stbt_indx.crisis_yn`(6종, 월, Y/N) |
| B1 | 6요인 레이더 | 불가 | 요인 값 없음 |
| B1 | 진단지표 추이 | 부분 | 대체: `ko_spdm_stbt_indx`(6종 월)·`ko_mrkt_prspect_idct`(6종) |
| B2 | 정량(등급·지수·전주비) | 불가 | 진단 지수 없음 |
| B2 | 가격 전주비 | 부분 | `ko_wkly_mnrl_prc.wow_pct`(동·니켈 등 비철 6종) |
| B2 | 원인 서술 | 불가 | 정성 |
| B3 | 지수·전월비·n주 연속 | 불가 | 진단 지수 없음. 월 단위 대체: `ko_spdm_stbt_indx.prvmm_cprs`(전월대비) |
| B4 | 지표 월평균·주간평균·전월비·전주비 | 불가 | 주간 진단 지수 없음(월 지표만 6종) |
| B4 | 가격 월평균·주간평균·전월비·전주비 | 부분 | `ko_wkly_mnrl_prc`(비철 6종, 주간)·`ko_mnrl_prc`(텅스텐·니켈·이리듐·로듐, 일별) 집계 |
| B5 | 장기 추세 서술 | 불가 | 정성 |
| B6 | 가격이격률·전주비 | 불가 | 이격률 컬럼 없음. `ko_mnrl_snths_indx.center/uplmt/lwlmt`(종합지수 MA·상하한)만 유사, 광종 가격엔 없음 → 산식 확정 후 `ko_wkly_mnrl_prc`에서 계산 가능 |
| B6 | 가격 신호(관심/주의 이상) | 불가 | 신호 판정 없음 |
| B7 | 당월 수입량·액·전년비·누적 | 부분 | `ko_cstm_cmmrc` 월 합산 — 텅스텐만(~2026-07-01). 리튬 예시는 더미 |
| B7 | 전년 수입액·CAGR | 부분 | `ko_cstm_cmmrc` 연 합산으로 계산 — 텅스텐만 |
| B7 | 수입국 비중·HHI | 부분 | `ko_cstm_cmmrc` 국가별로 계산 — 텅스텐만 |
| B7 | 5개년+당해누적 표·수출입 비중 | 부분 | `ko_cstm_cmmrc`(incm/exp) — 텅스텐만 |
| B8 | 세계 매장·생산 합계·상위 3·5국 | 부분 | `ko_rsrc_burudg_quty`/`ko_rsrc_prdctn_quty` — 텅스텐만 |
| B9 | 리스크 분석 정량(생산·수입 비중) | 부분 | B7·B8과 동일(텅스텐만) |
| B9 | 사건·산업 배경 서술 | 불가 | 정성 |
| B10 | 위기대응 | 불가 | 정성 |

## 3. 집계

| 판정 | A(38항목) | B(22항목) |
|---|---|---|
| 가능 | 1 | 1 |
| 부분 | 15 | 10 |
| 불가 | 22 | 11 |

## 4. 결론

- **`public`만으로 실제 값을 채울 수 있는 것**: 가격 블록(비철 6종 주간 가격·전주비·LME 재고, 텅스텐·니켈·이리듐·로듐 일별 가격, 광물종합지수), 수급안정화지수·시장전망지표(6종, 월), 관세청·USGS 기반 블록(수입 5개년·수입국 비중·HHI·생산/매장 구성비) — **단 텅스텐 1종만**. 거시지수는 SPGSCI·달러인덱스뿐.
- **채울 수 없는 것**: 보고서의 뼈대인 **광종별 위기진단 등급·지수·전주비·연속 주·요인 레이더·38종 분포·전체 평균 지수**(자리 `ai_mnrl_diag`·`ai_dash_diag`·`ai_mnrl_var`는 전부 더미 또는 0행), 지정학 리스크지수(GPR 더미)·국가별 리스크 지도, GSCPI·중국 무역정책 지수, 가격이격률·가격 신호, 정성 서술 전부(원인·사건·정책), 관리카드의 밸류체인·수입기업·비축 동향.
- **실데이터 광종 범위가 좁다**: 관세청·USGS는 텅스텐뿐이라 양식 A의 동·네오디뮴·리튬·코발트·니켈 표와 양식 B의 리튬 예시는 현재 `public` 실데이터로는 만들 수 없다. 공단 원장 실샘플이 광종별로 더 적재돼야 한다(`ai_mnrl_mst.ko_data_src_cd`가 KOMIS_SAMPLE인 광종이 텅스텐 1종).
- 따라서 통합보고서 자동화의 선결 과제는 ①`ai_mnrl_diag`·`ai_dash_diag`·`ai_mnrl_var`·`ai_mnrl_event`·`ai_mnrl_sect`에 **실제 진단 값을 만들어 넣는 산출 로직**(expired 파이프라인을 대체할 새 계산기 또는 공단 제공 값) ②`ko_cstm_cmmrc`·`ko_rsrc_*`·`ko_mnrl_prc`의 광종별 실샘플 확보 ③GSCPI·GPR 실값 적재 ④정성 항목의 작성 주체 결정이다.
