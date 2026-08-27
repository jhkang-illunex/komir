# 데이터 산출물 레지스트리 (재활용·재현 가이드)

> 원칙(2026-07-08 확립): 파이프라인 실행 결과물은 삭제하지 않고 보존하며, 각 산출물 디렉토리에
> `META.md`(생성 과정·입력·재현 방법)를 함께 남긴다. 휘발성 위치(/tmp)의 검증 산출물은
> `data_archive/`로 이관해 영구 보존한다. 이 문서는 그 중앙 색인이다.
> 코드 기준: git base `96eb79e` + 미커밋 수정분(커밋 전까지는 WORKLOG 날짜 항목이 코드 이력의 정본).

## 운영 산출물 (파이프라인 정본)

| 위치 | 내용 | 생성 | 재현 |
|---|---|---|---|
| `warehouse/minerals.duckdb` | 공유 warehouse 정본(fact_*·mart_*·geo_index 2,087·geo_event 6,510 포함) | 2026-07-08 geo publish + weekly_mart 재빌드 | `GEO_DATA=./geo_data_2016plus_run python -m geo publish --db warehouse/minerals.duckdb` → `MSR_DB=... python -m msr.features.weekly_mart` |
| `warehouse/minerals_test.duckdb` | 위 반영 전 검증 사본(2026-07-08). 정본이 root 소유였던 동안의 조인 검증에 사용 | 〃 | 폐기 가능(정본 검증 완료) — 단 사용자 확인 후 |
| `data_archive/validation_runs/geo_data_2016plus_run_260708/`(2026-08-05 `data_archive/`로 이관 — 루트 원경로는 `geo_data_2016plus_run/`였음, artifact-provenance-policy에 따라 삭제 아닌 이관) | 2016+ 전체 코퍼스(2,812건) ingest→extract 결과. manifest·이벤트 6,510건·pdf_extract_method·OCR캐시·실행로그(run*.log) | 2026-07-07~08, §9·§10 | META.md 참고(경로만 갱신, 내용 불변) |
| `geo_data/` | **프로덕션 단일 스토어**(2026-07-12 확정): 검증 GKG 180.9만+문서 6,510 = 1,815,034건 + 지수 3,382행 + 확률 2,745행 | 2026-07-08~12 | META.md 참고 |
| NAS `광해공단/bulk/gdelt/` | GDELT GKG 원본 zip 361,407개(2016~2026) + 다운로드/파싱/검증 로그(_logs/) | 2026-07-06~08 | `python -m geo.collectors.gkg_bulk_download` (5워커, 총 ~26h) |
| NAS `광해공단/collect_out/` (예정) | 독립 수집기(`collector/` 도커, 별도 서버) 산출 — inbox 텍스트(gnews/gdelt/us_trade/cn_trade)+GKG 증분 zip. 분석기와 파일 계약으로만 연결 | 2026-07-12 구축 | `docker compose up -d` (collector/README.md) |
| `warehouse/minerals.duckdb` → `fact_diagnosis_answer` | **수급위기 진단 정답셋(ground truth)**: KOMIS 가격기준 주간 이격률 등급(정상/관심/주의경계심각 3단계, 하방이탈 미포함) + 동일그리드 가격, 5광종×552주(LI는 289주), 2,497행 | 2026-07-16, 사용자 지정 | `MSR_DB=warehouse/minerals.duckdb python -m scripts.load_price_grade_answer`(원본: `documents/2차_데이타/3. 학습 및 검증용/1. 학습용 참고자료/1. 주간가격이격률모니터링_코미스가격기준 (1).xlsx`) |
| postgres `komis_demo.mineral_risk` 스키마(38테이블, DuckDB 전체 미러) | RAG 챗봇(`rag` 브랜치) `structured.py`가 읽는 정형데이터 원천. 2026-08-10 1회성 이관 후 정기동기화 없어 stale해졌던 것 발견·즉시 재동기화(38테이블 전부 불일치 0건) + 재발방지 cron 신설 | 2026-08-19(1회성 이관은 08-10) | `inhouse/mineral_supply_risk/scripts/cron_sync_postgres_mirror.sh`(crontab `auto:komir_pg_sync_daily`, 매일 05:00) — 수동 재실행도 멱등·안전, `python -m scripts.migrate_duckdb_to_postgres` 직접 호출도 가능 |
| `mineral_supply_risk/outputs/model_opt/a5_review_sample.csv` + `a5_labeling_guide.md` + `a5_review_sample_summary.md` | **A-5(라벨 품질 검증) 검토자용 패키지**: geo_event 계층표집 248건(광종×dimension×severity, 발행처 99.6% 공백이라 대체 계층 설계) + 라벨링 가이드(severity/direction/dimension 기준 명문화) + 표본구성 요약. 사람 판정 미기입 상태(대기) — 채점 스크립트(`scripts/a5_kappa_score.py`)는 합성 데이터로 코드 검증만 완료, 실행 대기 | 2026-07-18 | `MSR_DB=warehouse/minerals.duckdb python -m scripts.a5_label_review_sample` → 검토자 기입 후 `python -m scripts.a5_kappa_score --input <채운파일>` |

## 검증·분석 아카이브 (`data_archive/`)

| 위치 | 내용 | 근거 문서 |
|---|---|---|
| `data_archive/validation_runs/geo_ingest_check_260707/` | 10개 대표샘플 재실행 결과(manifest·이벤트 14건·추출텍스트 tgz) — classify/rule 버그 수정 검증에 사용 | 데이터수집현황 §7 |
| `data_archive/validation_runs/geo_pipeline_v2_check/` | opendataloader+OCR+LLM 파이프라인 v2 검증(10샘플, 이벤트 29건) | 〃 §9 도입부 |
| `data_archive/analysis/rule_vs_llm_260707/` | 룰기반 vs LLM(gemma) 추출 비교 원자료 pkl 2종 | 〃 §8 |
| `data_archive/analysis/chaksu_ocr_260708/` | 착수보고 39p OCR 전문(원본 PDF는 폰트 매핑 파손으로 텍스트 추출 불가) | mineral_risk_model_v1.md |
| `data_archive/backups/pre_gkg_relevance_cleanup*`, `pre_llm_relevance_apply_20260720/` | GKG 소급정제 각 라운드 전 geo_events.parquet+minerals.duckdb 백업 | WORKLOG 2026-07-20 |
| `mineral_supply_risk/outputs/model_opt/_gkg_relevance_llm_state/` | GKG 관련성 LLM 1차 재검증 실행 로그(checked/rejected/corrected, META.md 참고) | WORKLOG 2026-07-20, "LLM 관련성 재검증 전량 실행 완료" |
| `mineral_supply_risk/outputs/model_opt/_gkg_relevance_verify2_state/` | GKG 관련성 LLM 2차(적대적) 재검증 실행 로그(checked/problem/corrected, META.md 참고) — 최종 유효성 99.5% | WORKLOG 2026-07-21, "2차 적대적 재검증(합의투표 방식)" |
| `mineral_supply_risk/outputs/model_opt/{conc_impmult_corr_v2,kr_exposure_ablation,conf_weight_ablation,severity_sgn_significance_check,neardup_impact_sim_v2,rel_source_tier_check_v2}.md` + `data_archive/analysis/neardup_embed_260722/report.md` | 지수화 비판 #1~7,9 잔여 8개 일괄 처리(#4 이중노출 resid 채택·#7 conf_weight 활성화·#6 재확인 등) — 07-16 B-1~B-6의 조건부("refdata 백필 후 재실행" 등) 후속작업. #3(rel_source_tier_check_v2)만 07-22 당시 재검증 없이 보류됐던 걸 07-24 완결(결론 불변 재확인) | WORKLOG 2026-07-22(최신②)·2026-07-24(후속) 상세 |
| `mineral_supply_risk/outputs/model_opt/diagnosis_ylag_deep_review.md` (+ `scripts/diagnosis_ylag_deep_review.py`) | 진단모델 y_lag1 의존 심층검토 — 미착수 대안 6계열(비대칭게이트·Δ타깃·서수·전환가중·동역학피처·잔차회귀)+E7 방향별 이벤트 피처 일괄 백테스트, **전부 기각(7번째 동일 결론)**. E4 형식통과→강건성 기각, E7 개선분=가격뉴스 오염 판명. 이 방향 재시도 전 반드시 이 리포트 확인 | WORKLOG 2026-07-24(최신⑧), 스코어카드 v1.4 |
| `documents/산출물/2026-W30_0720-0726/피처_데이터_인벤토리_260724.md` | (구버전 — 260725판으로 대체) 3모델 피처 인벤토리 초판 | 사용자 요청(2026-07-24), 스코어카드 v1.6 시점 |
| `documents/산출물/2026-W31_0727-0802/방향긍정보류_결합검정_260731.md` | **방향긍정 보류 14건 결합검정 결과 문서** — 배경·대상·방법·결과·해석·결론 정리(스코어보드 §8 요약의 상세판). NI 결합 시 신호 희석(중복 후보 혼입) 메커니즘 설명 포함 | 사용자 요청(2026-07-31), WORKLOG 최신㊼ |
| `mineral_supply_risk/scripts/r10_joint_pending_test.py` (+ `outputs/model_opt/r10_joint_pending_test_260731.log`) | **방향긍정 보류 14건 결합(joint) 검정** — 순차검정이 놓친 결합효과 가설 직접 검정. NI 9건 결합 P=0.910·CU 3건 결합 P=0.856, 둘 다 채택 문턱 미달(NI는 개별 최강 후보보다 오히려 신호 희석 확인). "처음부터 다시 빌드해도 같은 결과인가" 질의의 직접 답 | 사용자 요청(2026-07-31), WORKLOG 최신㊼ |
| `documents/산출물/2026-W31_0727-0802/피처_검정_전체이력_260730.md` | **피처 검정 전체이력 종합표** — 프로젝트 시작(2026-07-09 지수 확률화)부터 어제(Census·BPS API)·오늘(칠레·DRC) 신규분까지 진단/예측/지수 전 모듈의 피처 후보와 채택·기각·보류 판정+구체 사유(QWK/P값) 총망라. 국가·기관 데이터 후보 58건 중 채택 2건(아르헨 LI·OECD 한국 CLI)뿐임을 정량 재확인 | 사용자 요청(2026-07-30), WORKLOG 최신㊻ |
| `mineral_supply_risk/outputs/model_opt/r10_retune_report.md` | **R10 전면 재검정 최신판(260730)** — tier2 검정 공백(칠레 COCHILCO 구리·DRC 코발트 미러) 발견 후 3계열 등록·재검정. cl_cu_ref 방향긍정 보류 추가, 채택 0건, 챔피언 불변. tier2 전 조합 검정 이력 확보(유의 채택은 아르헨 LI 1건뿐). 직전판(260729, ARCA/Census/BPS 반영분)은 `r10_retune_report_260729.md` 보존 | 사용자 요청(2026-07-30), WORKLOG 최신㊺ |
| `documents/산출물/2026-W31_0727-0802/해외기관_수집리스트_점검_260729.md` | **수집 리스트 항목별 점검(260728판 상세·후속판)** — 원 요청 국가×기관 순서로 상태·확보 시계열·불가 사유·필요 조치 재정리 + §5 "구조적 행 정합 불가" 5유형(그레인 과소·누계발표·조인키 연도가변·미보고·스캔PDF) 신규 분리 서술. FedReg 2020컷 임의값 확인·MOFCOM 페이지네이션 재확인(불가 유지) | 사용자 요청(2026-07-29), WORKLOG 최신㊸ |
| `documents/산출물/2026-W31_0727-0802/해외관세정책_데이터확장_260728.md` | **발주처 수집대상 확장(9개국×기관) 조사·반영 결과** — 당일 수집기 반영 7소스(BCRP·ABS·PSA·GACC월보·MOFCOM·연방관보·HTS, 신규 15계열 2,436행+공고 1,381건+관세율 775행)·키 필요 5건·불가 대안 4건·후속 6건·R10 검정 결과. 수집기 `collect_intl_agency_feeds.py`+cron 편입 | 사용자 요청(2026-07-28), WORKLOG 최신㊷ |
| `documents/산출물/2026-W31_0727-0802/시스템_기술서_데이터_전처리_모델링_260727.md` | **기술 정본** — 수집 데이터 전수(07-27 실측)+수집 규약·전처리(비정형 4단계/정형 as-of·결측·파생/지수화)·모델링 4모듈 상세(피처·모델 코드 재확인)+검증 원칙+발행 산출물 | 사용자 요청(2026-07-27), WORKLOG 최신㊶ |
| `documents/산출물/2026-W31_0727-0802/챔피언_스코어보드_260727.md` | **스코어보드 통합 확정판(260725판 대체 정본)** — 모듈 총괄·15셀 매트릭스(v4 단일 수치)·07-27 운영 상태·재시도 금지 요약·교체 조건 | WORKLOG 2026-07-27(최신㊶) |
| `documents/산출물/2026-W31_0727-0802/확정모델_광종별구성표_260727.md` | **발주처 전달용 확정 모델 구성표** — 5광종×3모듈 15셀 확정본(공통 구성+광종 특화+성능 상세 3표+한계 명기+유지·교체 원칙). 수치는 챔피언_스코어보드_260725.md 실측분 그대로, 내부용어 발주처어로 번역 | 사용자 요청(2026-07-27), WORKLOG 최신㊵ |
| `mineral_supply_risk/outputs/model_opt/a5_review_llmjudge_claude_260727.csv` + `a5_kappa_report_llmjudge_260727.md` (+ `scripts/a5_fill_llm_judge.py`) | **⚠A-5 LLM 교차판정(Claude, 사람 검증 아님 — 사용자 명시 선택)** — vLLM vs Claude 250건: severity wk 0.49·direction 0.51·ET 적절성 Y 52%. 계통 발견: severity 상향 편향(vLLM=3의 93% 비동의)·중립에 방향 남발·'뉴스' 무정보 라벨 76건. 발주처 기재는 "교차 모델 일관성 점검"만 허용 | WORKLOG 2026-07-27(최신㊴) |
| `mineral_supply_risk/outputs/model_opt/a5_review_{sample,A,B}_260727.csv` + `a5_labeling_guide_v2_260727.md` + `a5_review_sample_summary_260727.md` | **A-5 v2 검수 패키지(B안 2인 교차)** — 정제 후 모집단 재표집 250건(광종×severity 층화), 검토자 A/B 배포용(LLM 값 제거)·마스터(채점용)·가이드 v2. 구판(07-18) 파일은 보존. 채점: `a5_kappa_score.py --input A --input2 B --master ...` | WORKLOG 2026-07-27(최신㊳) |
| `documents/산출물/2026-W31_0727-0802/A5_사람판정_진행방안_260727.md` | **A-5 사람판정 진행 방안** — 실측 3건(기존 표본 생존 49%→재표집 필수·dimension 전량 소실→판정축 재정의·관련성 검증 별도 종결) 기반 단계별 방안: 패키지 최신화(Claude)→검토자 옵션 A/B(권장)/C→파일럿→본판정→채점. 성공 기준 사전 합의·8월 중순 종결 일정 | 사용자 요청(2026-07-27), WORKLOG 최신㊲ |
| `documents/산출물/2026-W30_0720-0726/피처_데이터_인벤토리_260725.md` | **3모델 피처 인벤토리 정본(07-25 주말 사이클 반영 전면 갱신)** — ①운영 사용 13행(R10 채택 2건·재고·CLI 포함) ②R10 재검정 결과별 세분(보류 6·기각·예측 exog 29종 전패·축적 대기) ③미DB화 잔여(WoodMac 승격 제외) ④07-24 셔틀리스트 8건 결산+발주처 요청 21항목 연결. 수량 전부 07-27 DB 재실측(각주 쿼리). ⚠SHFE CU 재고 소실 재발 발견→**07-27 원인 규명·복구 완료**(exchange_inventory의 광종 무한정 DELETE — WORKLOG 최신㉟, 교차 삭제 결함 3곳 수정) | 사용자 요청(2026-07-27 작성), 스코어카드 v1.21 시점 |
| `documents/산출물/2026-W30_0720-0726/자체수집_추가후보_상세_260724.md` | 자체 수집 추가 후보 상세(접근성 실측 포함) — Tier1: Comtrade 공급국 흐름 4종(인니NI·호주LI·칠레CU·미얀마→중국REE, 전부 실측✓)·CFTC 코발트/리튬 COT(2022-11~, 신규 발견)·생산국 통화·중국 선물 OI. Tier2: Cochilco·중국통계국·USGS MIS·SIA·ECOS 업종. 불가 확정: CME 재고(403 실측) 등 | 사용자 요청(2026-07-24) |
| `mineral_supply_risk/outputs/model_opt/diagnosis_tier1_eval.md` (+ `scripts/collect_tier1_feeds.py`, `scripts/diagnosis_tier1_eval.py`) | Tier1 자체수집(공급국 흐름 4종·CFTC CO/LI COT·인니 루피아·중국 OI 3종, 전부 사전 접근성 실측)+검정(발주처 시점 컷 2026-06-08 명시) — **CU +SHFE OI 유의 채택(P=0.996, 오경보 -47%, CU 최초 유의 피처)**, 풀링 확장 기각·CO COT2 교란 재검 대기 | WORKLOG 2026-07-24(최신⑮), 스코어카드 v1.11 |
| `documents/산출물/2026-W30_0720-0726/발주처보고_데이터확충_모델개선_260726.md` | **발주처 전달용 통합 보고서** — 데이터 확충(16배)·모델 개선(예측 -11%/-10%·조기경보 0.83→0.89·REE 왜곡 해소) 결과 + 협조 요청 우선순위 5건(LME CO 주간>조달청 비축>중국 세관>EV>기보유 구독분). 미수집 21항목은 별첨 참조 | WORKLOG 2026-07-26 |
| `mineral_supply_risk/outputs/model_opt/r10_retune_report.md` (+ `scripts/r10_retune_harness.py`, 수집기 collect_tier3/4) | **R10 완결 — 최종 수집 스윕(신규 31시리즈+파생 4종)+전면 재검정**: 진단 채택 2건(풀링 +한국 CLI P=1.000 / LI +아르헨 z24 조건부), 예측 exog 29종 전패, 가짜 유의 2건 철회(기준선 함정)·시드 강건성 축. SERIES_SPEC 등록형 하네스 = 신규 데이터 원커맨드 재검정 | WORKLOG 2026-07-26(최신㉘), 스코어카드 v1.20 |
| `documents/산출물/2026-W30_0720-0726/미수집데이터_발주처요청목록_260725.md` | **미수집 데이터 전수 목록(발주처 협조 요청용)** — 유료 8·비공개 3·미보고 5·반자동 5, 전 항목 실측 사유 기재. 우선순위: LME CO 주간(KOMIS 채널)>조달청 비축>중국 세관 최신(GTA/TDM)>EV 장기>기보유 구독분 확인 | WORKLOG 2026-07-25 |
| `documents/산출물/2026-W30_0720-0726/자체수집_Tier3후보_260725.md` | Tier3 수집 후보(전 항목 접근성 실측) — 즉시 가능 6종(칠레·아르헨 LI, 필리핀 NI, 말레이 REE, 일본 NI수입, USGS 구리 MIS)·간접 3종(EIA·Eurostat·akshare 에너지)·보류/불가 정직 기록(조달청 비축=발주처 안건 3호 후보) | WORKLOG 2026-07-25(최신㉗) |
| `documents/산출물/2026-W30_0720-0726/챔피언_스코어보드_260725.md` | (최종 수치는 260727 통합판으로 대체 — 탐색 이력·기각 상세는 이 문서가 정본) 기존 vs 신생 챔피언 대비·재발행 강건성 판정·15셀 실측 추기 1~3 | WORKLOG 2026-07-25(최신㉒)~07-26, v1.16~v1.22 |
| `mineral_supply_risk/outputs/model_opt/broad_method_sweep.md` (+ `challenger_alternatives.md`) | 광범위 방법론 스윕 R4~R6 — **재발행 강건성 발견**(지수·확률 재발행이 기준선 ±0.01~0.03 이동, v1.15 신챔피언 2건 강등)·**예측 ExtraTrees 신기록**(ton 0.2710·unit 0.1799, P=1.000)·**진단 배깅/보팅 랩핑 유의**(P=0.993~1.000)·부스팅 랩핑 비추·지수 NB2+z13 방어. 대등 구성 포트폴리오(모듈별 5+)는 challenger_alternatives.md | WORKLOG 2026-07-25(최신㉒), 스코어카드 v1.16 |
| `mineral_supply_risk/outputs/model_opt/challenger_validation.md` (+ `scripts/{challenger_validation,diag_refine1}.py`, `diag_refine1.md`) | **챔피언 초과 탐색 종결 — 3모듈 전부 유의 개선**(통합 재현 스크립트): 진단 Δ p_burst→gsev_z13 대체(QWK 0.839→0.861 P=0.997)·예측 ton +MIDAS지수(P=0.992)·unit +U-MIDAS 가격환율(P=0.987)·지수확률화 CO +x_z13(Brier 0.205→0.174 P=0.992, 상수기준 열세 해소). 공통 통찰: 원시 주간 신호의 시간 구조 > 압축·평균. 운영 반영 결정 대기 | WORKLOG 2026-07-25(최신㉑), 스코어카드 v1.15 |
| `mineral_supply_risk/outputs/model_opt/midas_eval.md` (+ `scripts/midas_eval.py`, `diagnosis_combo_sweep.md` 재실행 추기) | MIDAS 혼합주기 검정+CU 복구 스윕 재검증 — **ton 예측 +MIDAS지수 채택 권고(예측모듈 최초 유의 개선**: WAPE 0.287→0.273, CI [+0.003,+0.025] P=0.992, 6오리진 전부 비악화, NI·REE 견인**)**, unit +U-MIDAS 보류(P=0.955)·진단 U-MIDAS PMI 기각. 스윕 재검증은 채택 동작점 유지·TRD 중립 재분류 | WORKLOG 2026-07-25(최신⑳), 스코어카드 v1.14 |
| `mineral_supply_risk/outputs/model_opt/alt_refit_summary.md` (상세 `{diagnosis_alt_refit,forecast_alt_refit,geo_prob_alt_refit}.md` + `scripts/{diagnosis_alt_refit,forecast_alt_refit,geo_prob_alt_refit}.py`) | 3모듈 대안 재피팅(전피처 기존+T1+T2 × HGB/RF/ElasticNet/GBM분류기) — **전부 현행 챔피언 유지(아홉 번째 동일 결론)**: 진단 Ridge+현행 0.9687 최상·Δ 트리 계열은 조기경보 기능 상실·예측 지배 대안 없음·지수 NB2 Brier 0.1243 최상(GBM은 REE 체제전환 붕괴). 관찰: CU ton 트리+FULL 개선(재검 후보)·ElasticNet CO 강건 | WORKLOG 2026-07-25(최신⑰), 스코어카드 v1.13 |
| `mineral_supply_risk/outputs/model_opt/{diagnosis_tier2_eval,forecast_tier2_exog_eval,geo_tier2_linkage}.md` (+ `scripts/{collect_tier2_feeds,diagnosis_tier2_eval,forecast_tier2_exog_eval,geo_tier2_linkage}.py`) | Tier2 자체수집+3축 검정 — 수집: Cochilco 칠레 구리생산 137개월(경로 재발견)·USGS MIS 경유 CO LME재고 85개월(안건 A "무료 경로 부재" 정정)·WSTS 반도체 빌링 485개월·ECOS 세부업종 5계열 각 245개월, 중국 국가통계국 불가 확정(403). 검정: **진단 채택 0건**(방향긍정 3건 — CU/풀링 +KINV P≈0.96, LI +KIP P=0.942)·예측 외생 전부 노이즈(lag 지배 재확인)·지수 연계는 CU 동시탐지 타당성 실증(이벤트 스터디 p=0.044, Escondida 앵커)+선행성 없음. 월간 cron 편입 | WORKLOG 2026-07-25(최신⑯), 스코어카드 v1.12 |
| `mineral_supply_risk/scripts/backfill_macro_history.py` (결과는 diagnosis_combo_sweep.md 재심 절) | 거시 6계열 과거분 백필(2006-01~2021-06, 각 806주 — ECB 환율 3종·미 재무부 금리 2종·동방재부 달러인덱스, KOMIS 중복구간 교차검증 오차 0.002~0.32% 통과분만, src=BACKFILL_PUBLIC). **CLN 재심: 전환적중 0.577→0.192 붕괴 — 커버리지 교란 실증·기각 확정, 동작점 유지**. FEDFUNDS·STLFSI·BDI·PRICEIDX는 불가/기각 사유 기재 | WORKLOG 2026-07-24(최신⑭), 스코어카드 v1.10 |
| `mineral_supply_risk/outputs/model_opt/{diagnosis_combo_sweep,forecast_exog_eval}.md` (+ `scripts/{collect_demand_feeds,collect_forecast_exog,diagnosis_combo_sweep,forecast_exog_eval}.py`, `scripts/cron_collect_feeds.sh`) | ①전수 조합 스윕(7그룹 128+64×2조합, LI 백필 완료 후 전면 재실행) — **풀링 동작점 v1.9로 교체(INV+CNINV+PMICN, TRD 제외 — 완전 데이터에서 v1.7 구성 지배)**, 백필 전 결과는 git 4e9f99f ②예측모델 최초 외생 검정(COT·WoodMac·PMI·한국산업생산) — 전부 WAPE ±0.01 노이즈, 채택 없음 ③수요측 3종 추가 적재(ISM·유로PMI·부동산, 피드 꼬리 정지 플래그) ④수집 cron 상시화(주간/월간) | WORKLOG 2026-07-24(최신⑫), 스코어카드 v1.8 |
| `documents/산출물/2026-W30_0720-0726/발주처협의안건_추가2건_260724.md` | 발주처 안건 추가 2건 — A. CO LME 재고 제공 요청(무료 경로 8종 전수 실패 근거), B. EV/배터리 장기 데이터 예산(무료분 2년치뿐 실측) | WORKLOG 2026-07-24(최신⑫) |
| `mineral_supply_risk/outputs/model_opt/diagnosis_priority_feeds_eval.md` (+ `scripts/collect_priority_feeds.py`, `scripts/diagnosis_priority_feeds_eval.py`) | 인벤토리 1~4순위 수집·검정 — SHFE 구리재고 1,165행·Comtrade REE/CO 월간 각 108개월·중국 PMI 2종 적재(fact_inventory_exch/fact_indicator/fact_series). **풀링 전부결합 유의 개선(QWK CI [+0.12,+0.18]·P=1.000, 오경보 -49%) — 3번째 실증, 고정밀 동작점 채택 권고**. CU 2축 기각(NI 패턴 미재현)·REE 방향긍정 보류·COMEX 무료경로 부재 | WORKLOG 2026-07-24(최신⑪), 스코어카드 v1.7 |
| `mineral_supply_risk/outputs/model_opt/co_inventory_recon.md` + `diagnosis_exch_inventory_eval.md` (+ `scripts/collect_exchange_inventory.py`, `scripts/diagnosis_exch_inventory_eval.py`) | CO 재고 수집 정찰(8경로 전수 실측 — **무료 자동수집 불가 확정**, 발주처 경유 안건) + 대체 수집: NI SHFE 재고 643행(2015~)·LI GFEX 창단 61주(공백 있음, 재수집 예정)를 `fact_inventory_exch`(신설, PK에 src)에 적재. 검증: **NI LME+SHFE 결합 유의 개선**(QWK CI [+0.20,+0.42], 오경보 -71%) — 재고→전환탐지 두 번째 실증 | WORKLOG 2026-07-24(최신⑩), 스코어카드 v1.6 |
| `mineral_supply_risk/outputs/model_opt/diagnosis_aux_features_eval.md` (+ `scripts/load_market_aux.py`, `scripts/diagnosis_aux_features_eval.py`) | 외부 직교 데이터 확보→검정 — 발주처 원본의 미활용 주간 LME재고(CU·NI 2007~)·거시 12종을 `fact_inventory`(2,030행)·`fact_series`(3,373행)에 최초 적재 후 전환탐지 재검정. **재고 피처가 CU·NI Δ분류에서 전환 적중 1/18→7/18·QWK 동반상승(부트스트랩 P=1.000) — 보조 조기경보 고정밀 동작점 신규 확보**. 거시=보류(커버리지 교란), 게이트=8번째 기각. CO/LI/REE 수집 경로 조사 포함 | WORKLOG 2026-07-24(최신⑨), 스코어카드 v1.5 |
| `mineral_supply_risk/outputs/model_opt/ylag_publication_delay_sensitivity.md` (+ `ylag_publication_delay_sensitivity_folds.csv`, `scripts/ylag_publication_delay_sensitivity.py`) | **진단모델 미래시(look-ahead) 오염 점검 — 사용자 지시**. 발견: `mart_weekly_diagnosis`의 교사(수급동향지표) 조인이 다른 모든 외부데이터(관세청·PMI·CLI 등)와 달리 `avail_date` 없이 자기 참조월로만 조인돼 발행지연이 전혀 반영 안 됨(weekly_mart.py:61-62) — `y_lag1`(전월 교사값)은 챔피언 QWK 기여도가 dQWK 0.765로 압도적(report.md). 민감도 실험: y_lag1→y_lag2→y_lag3 교체 시 챔피언 QWK 0.921→0.825→0.759, 단 동일지연 Naive 대비 우위는 0.035→0.083→0.144로 오히려 확대(모델 자체 가치는 어떤 지연가정에서도 유지, 헤드라인 절대QWK만 지연=1개월 가정에 낙관적으로 의존). 별도 발견: `geo_prob`(p_burst) 발행값이 전체이력 재적합이라 구조적 lookahead 있으나 dQWK=0 실측이라 현재 영향 미미. **KOMIS 실제 발행지연 일수는 로컬 문서로 "갱신주기=월간"까지만 확인, 정확한 지연은 미해결 — 발주처 확인 필요** | 사용자 요청(2026-08-10~13) |
| `mineral_supply_risk/outputs/model_opt/lookahead_bias_audit_260813.md` | **미래시 오염 5개 서브모듈 감사 + 적대적 검증(각 결론을 독립 에이전트가 반박 시도)**. 위 y_lag1 건은 CONFIRMED(실측 완결). **신규 발견**: `geo_index`의 `indexer.py:39-78` `_apply_kr_exposure(mode="resid")`가 잔차화 계수를 2016~2026 전체 이력으로 추정해 2016년 값에도 소급 적용 — `geo_prob`(p_burst) 전체이력재적합과 동일한 안티패턴이 지수 자체에도 존재(CU가 이 모드 운영중), "과거 지수값 불변"(07-05/07-22 결론)과 배치. `geo_prob`의 "dQWK=0=무해" 판정은 stale 스냅샷(07-13~16, 이후 NB2버그수정·CO x_z13 반영 안 됨)·마지막 폴드만 측정이라 근거 부족으로 REVISED → **2026-08-14 재검증 후 CONFIRMED**(아래 행 참고, 구조문제는 별개로 유지). `geo_event.published_at` 컬럼이 publish() 1회당 단일값 일괄대입이라 완전 무의미함을 발견(distinct=1, 296,679행). 이벤트 발생일-보도일 지연은 전체의 2.3%(비GKG 경로)만 해당, 영향 경미. BASE_FEATS 4/5·최근 파생피처군(INV/CNINV/PMI/CLI/GSEV) 6종은 코드로직 정상 재확인(단 avail_date 오프셋 값 자체는 미실증 가정) | 사용자 요청(2026-08-13), 병렬 조사5+적대적검증5 에이전트 |
| `mineral_supply_risk/outputs/model_opt/geo_prob_perfold_sensitivity.md` (+ `.csv`, `scripts/geo_prob_perfold_sensitivity.py`) | **geo_prob(p_burst) 피처민감도 최신코드 재실행 — 사용자 지시**. `geo_prob` DB는 이미 08-08에 07-24/07-25 수정 반영된 상태였음(실측 확인, max period 2026-08-03) — `report.md`만 07-16 스냅샷으로 낡아있어 재생성(전체 dQWK -0.003, 기존 결론과 동일). 적대적 검증이 지적한 "마지막 폴드만 측정" 약점 해소 위해 3폴드 전부 개별 계산: 2023 dQWK=0.0000·2024 dQWK=0.0000·2025 dQWK=-0.0035 — **"초기 폴드일수록 오염 클 것"이라는 우려 실측으로 기각, 전 폴드 일관되게 무기여 확정**. `lookahead_bias_audit_260813.md` §2 갱신 완료(REVISED→CONFIRMED, 구조문제는 별개 유지) | 사용자 요청(2026-08-14) |

| `geo/prob_model.py`·`geo/indexer.py` (코드 변경, 산출물 아님) + `data_archive/backups/pre_geo_expanding_window_refactor_20260818/minerals.duckdb` | **geo_prob·geo_index를 expanding-window로 리팩터 — 사용자 지시(§2·§4 구조적 문제 실수정)**. `prob_model.py::run()`의 발행 섹션을 연도별 1/1 컷오프 expanding 재적합으로, `indexer.py::_apply_kr_exposure()`의 정규화·잔차화 계수를 광종×연도 소표 기반 벡터화 expanding 계산으로 교체(둘 다 `_asof_grid`류 벡터화 패턴, row-wise apply 없음). 반영 전 DB 백업 후 `geo publish --what index`+`msr.features.weekly_mart` 재빌드로 프로덕션 반영 완료. 결과: geo_prob 2,770→2,510행(2016년 웜업미달분 정직한 결측, 진단모델은 2020+만 써서 무영향), geo_index 행수불변(초기연도 평균 0.8~2.0점 변화 후 2017+ 0.2~0.3점으로 수렴). 진단모델 재검증: 챔피언 QWK 0.921→**0.934**(악화 아닌 소폭 개선), p_burst·geopolitical_risk dQWK 전부 여전히 ~0(y_lag1 0.808 대비 미미) — 구조적 lookahead 제거가 성능을 해치지 않음을 확인. `lookahead_bias_audit_260813.md` 최종 갱신 완료 | 사용자 요청(2026-08-18) |
| `data_lake/semi_structure/okf_documents/{Argus_비철금속_일일,조달청보고서}/` + `pageindex_trees/{동일}/` + `komis_demo.mineral_risk.doc_chunk`(pgvector) | **Argus 690건·조달청보고서 887건 문서-OKF·PageIndex·임베딩 — 이미 완료(08-12~13), WORKLOG 공백만 08-19에 소급 기록**. `build_okf_documents.py --what argus`(source_policy.py의 유료출처 차단을 `allow_paid_sources=True`로 이 경로에서만 우회, 2026-08-12 사용자가 라이선스상 내부 파생DB 허용 확인 후 지시)와 `build_pageindex_trees.py`로 Argus 690/690건·조달청 868/887건 OKF+트리 생성 완료(08-12), pgvector 임베딩까지 완료(08-13, Argus 청크 77,648개·조달청 55,530개, 전체 doc_chunk 140,031건 중 95%). 완료 시점엔 WORKLOG 기록이 없어 08-11/08-12 "보류" 기록만 보고 "미착수"로 오판할 뻔했다가 실측(직접 쿼리)으로 정정 | WORKLOG 2026-08-19 |
| `documents/산출물/한양대/0818발표자료_komir구현_비교분석_260819.pptx` | **"0818 발표자료 vs komir 구현" 비교 PPT(16슬라이드, 사용자 요청, 08-19 초안13매→08-19 3매 추가)** — `0818_일루넥스_발표자료(최종).pptx`(과업1·2 주간보고, Chronos-2+Gemma4 기반)를 komir 실제 구현과 광해공단 과업지시서(`documents/260625 ..._일루넥스.pdf`) 요구사항 대비로 비교. 핵심: 0818은 니켈 1개 광종·~6개월만 검증(정답라벨無·정량지표 미제시) vs komir는 5광종·워크포워드 3폴드·수년치 백테스트, 0818 "5단계" 표기 vs 과업지시서·화면기획 4단계(정렬확인 필요), Chronos-2 미래가격예측을 진단입력으로 쓰는 구조가 과업지시서 "미래예측 아님" 조항과 정합성 확인 필요, 필수변수⑥ 중 ④세계공급부족·신규지표3종(공급망압력·원자재·ESG지수)은 양쪽 다 공백, 0818의 LLM서술형 종합판단·3분류 시나리오는 화면기획 #13·#20·#21 공백에 대응하는 참고가치(r10 채택기준 조건부). **추가 3슬라이드**(모델링 상세비교/요구사항 9항목 부합도 판정표(7:1:1로 komir 우위)/GPU·인프라 자원 비교 — komir는 AI모델_사용안_260722.docx §5에 GPU서버1대·gemma-4-26b-a4b MoE fp8이 문서화돼 있으나 VRAM은 "인프라팀 확인필요"로 미확정, 0818은 gemma4:31b dense(슬라이드41)만 명시돼 있고 GPU스펙 자체가 PPT 범위 밖이라 통상 어림 VRAM을 추정치로만 병기, 양쪽 다 GPU 사양은 발주처 결정 대기(시스템_결정필요사항.md 1-2)). 모든 정량수치는 프레임(광종/지평/지표) 라벨 병기로 액면비교 왜곡 방지. gotenberg 도커로 PDF변환 후 렌더링 육안검증 완료(겹침·잘림 없음) | WORKLOG 2026-08-19(최신④) |
| `documents/산출물/한양대/한양대_질의사항_260823.md` | **비교 PPT(위 항목) 기반 한양대 질의사항 22개 정리(사용자 요청, 260823 보안감사 안내 2건 추가)** — 과업1(진단) 9건(4/5단계 표기·미래정보 사용·검증범위 확장·정량지표 도입계획·필수변수⑥매핑·신규지표3종 현황·후보모델 비교검증 여부·5요인 루브릭 재현성·라벨오염 방지설계), 과업2(예측) 5건(검증범위 확장·best-of-3 오라클 운영적용·확률자동산출 설계·VAR/Chronos-2 앙상블 세부·정성정보 9종 산정기준), 공통·방법론 3건(LLM 서빙환경·GPU사양·소표본 강건성검증·서술형근거 신뢰성확보), 산출물·일정 2건, **[신규] 발주처 LLM/임베딩 모델 보안감사 요구사항 안내 2건**(모델별 보안취약점 보고서 준비현황, 제외모델 지정시 대체계획 — Chronos-2·Gemma4 대상, komir측 gemma-4-26b-a4b·intfloat/multilingual-e5-small도 동일 대응 필요함을 병기), 협업제안 1건(서술형 종합판단 프로토타입, r10 채택기준 조건부). 우열판단 아닌 정렬확인 목적 명시 | 사용자 요청(2026-08-23) |
| `documents/산출물/한양대/한양대_질의및보완요구사항_260824.md` | **한양대에 실제 발송할 문서로 질의사항(260823)+보완요구사항을 하나로 통합(사용자 요청, 대상=한양대 0818 구현 미충족사항으로 범위 명확화)** — II절 보완요구사항 11건(R1~R11, 과업지시서·화면기획 대비 0818 미충족: 5광종중1개만검증·정량지표미제시·미래정보사용조항위배소지·5단계표기·필수변수6종매핑불명·신규지표3종언급없음·후보모델비교검증없음·과업2 12개월/ton/확률자동산출 미완성 + [신규]LLM보안감사 요구 2건) III절 질의사항 8건(설계세부확인, 요구성격 아닌 정보요청만 추림) IV절 산출물·일정조율 2건 V절 협업제안 1건. 이전 `한양대_질의사항_260823.md`(질의중심 초안)는 이력으로 보존, 이 문서가 발송용 정본 | 사용자 요청(2026-08-24) |
| `documents/산출물/2026-W34_0817-0823/발주처요구사항_미충족항목_보완요구_260823.md` | **발주처 요구사항(과업지시서·화면기획안 v1.3·신규 보안감사) 대비 komir 미충족 항목 전수 목록화 + 항목별 보완요구(사용자 요청)** — A.과업1 4건(필수변수④·신규지표3종·y_lag1발행지연의존·published_at컬럼) B.과업2 0건(문자그대로 충족 확인) C.화면기획 AI기능 12건(#13·18·20·21·29~37·정형조회배선 — 08-13 실측 08-23 재확인 변경없음) D.공통인프라 6건(DB/VDB근거계약·RAG품질기준·챗봇조정서비스·report_gen분석요약3종·대화상태정책·조달청범위) E.[신규]LLM보안감사 3건(gemma-4-26b-a4b·multilingual-e5-small 보안취약점보고서 미작성, 제외모델 대체계획 부재) F.발주처확인대기 4건(발행지연·5광종데이터·GPU·조달청범위). 우선순위 권고(저비용즉시/발주처확인선행/신규설계중기/보안보고서즉시착수) 포함. 코드변경 없음(순수점검) | 사용자 요청(2026-08-23) |

- **지정학 위기지수·수급위기 진단·수요예측 모델링 통합 정리(워드)**: `documents/산출물/2026-W35_0824-0830/지정학위기지수_수급위기진단_수요예측_모델링정리_260826.docx`
  — 3개 모듈(과업 산출물 ①②③)에 한정한 데이터 처리·모델링 작업 히스토리·모델링
  비교표 통합본. 착수(07-02)~08-23 기준 미충족항목까지의 기존 산출물(확정모델_
  광종별구성표_260727·챔피언_스코어보드_260727·시스템_기술서_260727·lookahead_
  bias_audit_260813 등)을 재종합한 것으로 신규 조사·수치 산출은 없음(전부 원본
  문서 인용, 출처 각주 병기). QWK 등 시점별 수치가 다른 항목(0.9687→0.921→0.934)은
  단일 추세로 오독되지 않도록 측정 시점·프레임을 표로 분리 표기.

## 관련 문서
- 작업 이력: `docs/WORKLOG.md` (날짜별 변경·버그·결정)
- 데이터 수집 현황·실측: `documents/산출물/2026-W28_0706-0712/지정학위기지수_데이터수집현황_260707.md`
- 모델 설계 정본: `documents/산출물/2026-W28_0706-0712/mineral_risk_model_v1.md`
- **중간 진행 상황 보고(워드)**: `documents/산출물/2026-W30_0720-0726/중간진행상황보고_260722.docx`
  (**정본**. 260716 원본 보존 — 260722는 GKG 이벤트 건수만 갱신(181만→29.5만, 관련성
  99.5%), 보고일·타임라인 서술은 260716 스냅샷 그대로 유지)
  — 착수(07-02)~현재 6단계 타임라인·수집/가공 현황·5광종별 지수/진단/1년후 수입예측 표·
  성능 스냅샷·주요 발견·산출물·잔여 작업(WORKLOG 35항+DB 실측 기반).
- **발주처 협의 안건서(워드)**: `documents/산출물/2026-W30_0720-0726/발주처협의안건_4건_260722.docx`
  (**정본**. 260716 원본 보존. 260722 = 안건1·2에 인용된 AUC·허위경보율 수치를 GKG
  재정제 후 데이터로 재검증(`scripts/build_proxy_label.py`·`scripts/lead_time_eval.py`
  재실행)해 갱신 — AUC(LI/NI/REE)는 재정제 전후 동일 수준(0.90/0.91/0.99) 확인, 허위경보율은
  단일수치 "1.8% 이하" 표현이 지평별 실제론 0.6~3.6% 범위임을 확인해 더 정확한 표현으로
  수정. 안건3·4·본문 서술은 변경 없음)
  — 에피소드 라벨 협조·미탐:오탐 비용비 합의·CU 해석 방침 승인·품목 예측 수요 확인.
  v1 §12 기존 8건과 별개 추가 안건임을 명시.
- **광종별 HS코드 연계표(워드)**: `documents/산출물/2026-W29_0713-0719/광종별_HS코드_연계표_260713.docx`
  — core 161코드(CU 88/NI 36/CO 15/LI 13/REE 9)를 HS 호(4단위) 품명 그룹으로 정리.
  정본은 `mineral_supply_risk/data/raw/hs_commodity_map.csv`(542행), 문서는 그 뷰.
- **발주 보고용 요약본(워드, 구성도 포함)**: `documents/산출물/2026-W30_0720-0726/핵심광물_시스템구성_요약본_260722.docx`
  (**정본**. 260716 = 협의 안건 예정 추가·성능 최신화. 260713 파일은 갱신 과정에서 동일
  내용으로 덮어써진 동일본 — 사용자 결정(2026-07-16)으로 히스토리 표기용 보존. 260722 =
  GKG 관련성 재정제 결과 반영(건수 약181만→29.5만, 관련성 71.4%→99.5%) — 260716은
  히스토리 보존)
  — 5모듈·구성도(수집서버 외부망/분석서버 폐쇄망)·수집기 배치·반입 절차·운영 요약. 구성도 원본
  `documents/산출물/2026-W29_0713-0719/시스템구성도_260713.png`(matplotlib 생성, 스크립트는 세션 스크래치)
- **발주 보고용 확정본(워드)**: `documents/산출물/2026-W30_0720-0726/핵심광물_시스템_확정아키텍처_모델링정리_v1_260722.docx`
  (**정본**. 260713 = 최초 확정본, 히스토리 보존. 260722 = GKG 관련성 재정제 결과 반영,
  "작성일" 줄에 갱신일 병기)
  — 5모듈 아키텍처·데이터 흐름·지표/모델링·전통 ML 채택 근거. 생성 스크립트는 세션 스크래치
  (숫자 출처: outputs/model_opt/report.md, outputs/forecast_unit/forecast_latest.csv,
  WORKLOG 2026-07-12~13, 2026-07-20~21 GKG 재정제)
- **프로세스 정리(외부 AI 검토용, 워드)**: `documents/산출물/2026-W30_0720-0726/프로세스정리_외부AI검토용_260724.docx`
  (**정본**. 260716 원본 보존, 260722 보존(둘 다 히스토리로만 유지). 260722 = geo_event
  원장 건수만 GKG 재정제 후 수치로 갱신(181만/134만→29.5만/21.3만) — 당시 "구조화문서 LLM
  추출 성공률(90.4%)·GKG raw_score 스케일 상수·NB2 Brier score 등 설계검증 근거 수치는
  GKG와 무관한 별도 검증이라 원본 그대로 유지"로 사용자 확인(2026-07-22)했으나, 그 판단
  **이후** 시점정합성 수정(#8)·USGS refdata 실가동·이중노출 잔차화(#4)·LLM 확신도 가중(#7)
  으로 NB2·지수식 자체가 수차례 재계산돼 그 전제가 깨짐 — **260724 = §4-1(지수 공식에
  conf_mult 6번째 성분 반영)·§4-3(민감도분석이 구5성분·GKG정제전 데이터 기준임을 명시,
  6성분 재검증 미실시 상태로 정직하게 플래그)·§4-4(NB2 Brier 표를 07-24 재계산치로 전면
  교체 — CU 0.046/NI 0.048/REE 0.209/CO 0.208/LI 0.113, 광종별 우열판정 CU·NI·REE
  개선/CO·LI 열세로 판정 자체가 바뀜, 옛 P(y≥1) 타깃 수치는 "검증 이력"으로 성격 명시해
  보존)·§4-5(#4 conc×imp_mult 상관 실측+resid 채택 경위 추가) 갱신.** 사용자 지시
  ("매일 일지 형식으로 과거 기록을 유지")에 따라 260716·260722는 삭제하지 않고 그대로
  보존 — 세 버전을 시간순으로 비교하면 설계검증치가 어떻게 바뀌어왔는지 감사 추적이
  가능하다.
  — 6단계 파이프라인 상세, 외부 AI 방법론 검토용.
- **AI 모델 사용안(워드)**: `documents/산출물/2026-W30_0720-0726/AI모델_사용안_260722.docx`
  — 수급위기 진단모델(Ridge alpha=1.0, 풀링+광종더미)·수입수요 예측모델(HistGradientBoosting
  Regressor, 물량·단가 분리+재귀/Direct 자동선택)·지정학 LLM(gemma-4-26b-a4b, 사내 vLLM)
  각각의 특징·선정사유·장단점·제약사항 + 필요 인프라 자원 표. 모델 종류·피처·하이퍼파라미터는
  `mineral_supply_risk/scripts/diagnosis_retrain_answer.py`·`msr/models/forecast_unit.py`·
  `geo/config.py`·`.env`를 서브에이전트로 직접 확인해 작성(문서 재인용 아님). GPU VRAM 등
  일부 인프라 수치는 미확정이라 문서에 명시적으로 "확인 필요"로 표시.
  **(후속 보강, 같은 날)** 사용자 지적으로 "지정학 위기지수 = LLM 추출뿐 아니라 이벤트를
  기존 데이터(USGS 공급집중·관세청 수입의존도·발행처 신뢰도)와 결합해 지수화하는 과정"이
  빠져있던 걸 발견 — 4-2(이벤트→지수화, `geo/indexer.py` 결정론적 가중합산·중복제거·볼륨
  드리프트 정규화·사건지속성 감쇠·tanh0_100 정규화)·4-3(NB2 확률화 레이어, `geo/prob_model.py`)
  섹션 신규 추가. 두 섹션 모두 서브에이전트가 `indexer.py`·`prob_model.py`·`refdata.py`·
  `build_kr_import_share.py`를 직접 정독해 확인한 내용.
  **(2차 후속 보강, 2026-07-22)** 시점정합성(#8) 코드 수정 후 §4-3의 NB2 Brier 검증 수치를
  재계산값으로 교체(문단 44·73·74) — CU 0.046/NI 0.048/REE 0.209/CO 0.206/LI 0.113,
  isotonic 0.1184→0.1162·ECE 0.079→0.073. 상세는 `docs/WORKLOG.md` 2026-07-22(최신) 항목
  참고. 광종별 우열 판정(CU·NI·REE 개선/CO·LI 열세)은 수정 전과 동일 — 수치만 소폭 이동.
- **GKG 필터링 프로세스(md, 신규)**: `documents/산출물/2026-W30_0720-0726/GKG_필터링_프로세스_260724.md`
  — 원본 GDELT(1,815,184건, 관련성 28.6%)에서 4단계(규칙기반 4라운드→LLM 관련성 재검증→
  LLM 적대적 재검증)를 거쳐 최종 295,157건(관련성 99.5%)까지 좁혀지는 전 과정 정리 +
  "LLM 재검증이 있는데도 규칙기반 필터를 다듬는 이유" + 2026-07-24 CO/LI/REE 동음이의어
  노이즈 보강 후속작업(발견·수정·회귀 발견 및 재수정 전 과정, `geo/gkg_relevance.py`)
  기록. 전부 `docs/WORKLOG.md` 2026-07-20·07-21·07-24 항목의 실측치 재인용(신규 조사 아님,
  본문에 명시).
- **시스템 스코어카드(md, 신규, 살아있는 문서)**: `documents/산출물/2026-W30_0720-0726/시스템_스코어카드_260724.md`
  — 사용자 요청("작업한 것들을 정리해서 점수화")으로 신설. 시스템을 ①수집기 ②분석
  시스템(2-1 전처리·2-2 지수생성기·2-3 진단기·2-4 예측기)의 2단 구조로 확정(사용자 지시,
  2026-07-24)하고 각 모듈의 핵심 지표를 라이브 DB 직접 조회로 채움. **v1에서 발견한
  핵심 갭**: 2-2(지수)가 07-22에 크게 바뀌었는데 2-3·2-4는 각각 07-17·07-04 재학습 기준이라
  아직 반영 전 — 다음 버전 재적합 필요 항목으로 문서 내 명시. **버전 정책**: 새 버전은
  이 문서를 덮어쓰지 않고 "버전 이력" 절에 이어붙이는 방식으로 계속 갱신 예정(WORKLOG와
  동일한 일지 방식, 매 버전마다 파일을 새로 만들지는 않음 — GKG 필터링 프로세스 문서와
  달리 이 문서 자체가 누적형). 향후 수집기·전처리 모듈에 보안 지표가 추가될 가능성을
  염두에 둔 자리도 마련해둠. **v1.1(같은 날 후속)**: 사용자 요청으로 4-2·4-3·4-4에
  설명가능성 항목 추가(지수·진단은 이미 가동 중 확인) → 곧이어 4-4(예측기) 설명가능성을
  실제로 구현(`msr/models/forecast_unit.py`, SHAP TreeExplainer+permutation_importance,
  `out_import_forecast_unit`에 `reason`·`explain_json` 컬럼 신규) — 재적합 부수효과로
  2-4의 버전정합성 갭도 동시 해소(WAPE 갱신). 3모듈 설명가능성 전부 가동 중으로 전환,
  진단기(2-3) 재적합만 잔여 갭으로 남음. **v1.2(같은 날 후속)**: 사용자 요청으로
  2-2·2-3·2-4 **적대적 감사**(5장 신설, 서브에이전트 3개 병렬+핵심 발견 직접
  재검증) — 코드 수정 4건 즉시 반영: `geo/indexer.py` 국가명 정규화(CO 이벤트
  44.6%가 USGS DRC 표기 불일치로 conc 중립 폴백되던 버그), `geo/config/index.yaml`
  scale_k v2→v3 재앵커(P90 목표 88 복원), `geo/prob_model.py` NB2 MLE 수렴 체크,
  `msr/models/forecast_unit.py` 환율 피처 100% 결측 버그(발주처 문서가 "환율 반영"을
  주장했으나 실제로는 한 번도 반영된 적 없었음). 전부 재실행·재발행 검증 완료, 최종
  결론(우열 판정)은 안정적으로 유지. 진단모델 타깃-피처 순환성 등 구조적 한계는
  코드 대신 문서 문안 교정으로 대응 — 상세는 `docs/WORKLOG.md` 2026-07-24(최신⑥).
  **v1.3(같은 날 후속)**: 사용자 지시("수정된 것을 기반으로 다시 점수화")로 마지막
  잔여 갭(2-3 진단기 재적합)을 해소 — mart 재빌드→nowcast→alert 전체 체인 재실행.
  QWK 0.9687 완전 무변화(y_lag1 지배 확인의 방증), GEO_ONLY_NO_LAG 지표를 신규
  병기해 지수 변경의 실제 반영처를 명확히 함. 5개 모듈 전체가 2026-07-24 기준
  동일 시점으로 정합 완료 — 상세는 `docs/WORKLOG.md` 2026-07-24(최신⑦).
- ⚠ **의도적으로 갱신하지 않은 문서**: `documents/산출물/2026-W29_0713-0719/피드백기반_수정플랜_260716.docx`
  14~15번째 문단의 "1,815,194건"은 **2026-07-16 시점 실측 정정 기록**(WORKLOG의 "650만건"
  오기재를 직접 쿼리로 정정한 감사 로그)이라 현재 수치로 바꾸면 오히려 그 날짜의 실측
  사실을 왜곡함 — 향후 세션에서 "이것도 stale 아닌가" 재검토할 필요 없음(2026-07-22
  사용자 확인 완료).
