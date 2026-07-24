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
| `geo_data_2016plus_run/` | 2016+ 전체 코퍼스(2,812건) ingest→extract 결과. manifest·이벤트 6,510건·pdf_extract_method·OCR캐시·실행로그(run*.log) | 2026-07-07~08, §9·§10 | META.md 참고 |
| `geo_data/` | **프로덕션 단일 스토어**(2026-07-12 확정): 검증 GKG 180.9만+문서 6,510 = 1,815,034건 + 지수 3,382행 + 확률 2,745행 | 2026-07-08~12 | META.md 참고 |
| NAS `광해공단/bulk/gdelt/` | GDELT GKG 원본 zip 361,407개(2016~2026) + 다운로드/파싱/검증 로그(_logs/) | 2026-07-06~08 | `python -m geo.collectors.gkg_bulk_download` (5워커, 총 ~26h) |
| NAS `광해공단/collect_out/` (예정) | 독립 수집기(`collector/` 도커, 별도 서버) 산출 — inbox 텍스트(gnews/gdelt/us_trade/cn_trade)+GKG 증분 zip. 분석기와 파일 계약으로만 연결 | 2026-07-12 구축 | `docker compose up -d` (collector/README.md) |
| `warehouse/minerals.duckdb` → `fact_diagnosis_answer` | **수급위기 진단 정답셋(ground truth)**: KOMIS 가격기준 주간 이격률 등급(정상/관심/주의경계심각 3단계, 하방이탈 미포함) + 동일그리드 가격, 5광종×552주(LI는 289주), 2,497행 | 2026-07-16, 사용자 지정 | `MSR_DB=warehouse/minerals.duckdb python -m scripts.load_price_grade_answer`(원본: `documents/2차_데이타/3. 학습 및 검증용/1. 학습용 참고자료/1. 주간가격이격률모니터링_코미스가격기준 (1).xlsx`) |
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
| `documents/산출물/2026-W30_0720-0726/피처_데이터_인벤토리_260724.md` | 3모델(지수·진단·예측) 피처 인벤토리 — ①DB화+사용중 ②DB화+미반영 ③사내 미DB화 ④미수집 후보 셔틀리스트(우선순위·비용·기대효과). 수집 전 오염·커버리지 검정 원칙 명시 | 사용자 요청(2026-07-24), 스코어카드 v1.6 시점 |
| `mineral_supply_risk/scripts/backfill_macro_history.py` (결과는 diagnosis_combo_sweep.md 재심 절) | 거시 6계열 과거분 백필(2006-01~2021-06, 각 806주 — ECB 환율 3종·미 재무부 금리 2종·동방재부 달러인덱스, KOMIS 중복구간 교차검증 오차 0.002~0.32% 통과분만, src=BACKFILL_PUBLIC). **CLN 재심: 전환적중 0.577→0.192 붕괴 — 커버리지 교란 실증·기각 확정, 동작점 유지**. FEDFUNDS·STLFSI·BDI·PRICEIDX는 불가/기각 사유 기재 | WORKLOG 2026-07-24(최신⑭), 스코어카드 v1.10 |
| `mineral_supply_risk/outputs/model_opt/{diagnosis_combo_sweep,forecast_exog_eval}.md` (+ `scripts/{collect_demand_feeds,collect_forecast_exog,diagnosis_combo_sweep,forecast_exog_eval}.py`, `scripts/cron_collect_feeds.sh`) | ①전수 조합 스윕(7그룹 128+64×2조합, LI 백필 완료 후 전면 재실행) — **풀링 동작점 v1.9로 교체(INV+CNINV+PMICN, TRD 제외 — 완전 데이터에서 v1.7 구성 지배)**, 백필 전 결과는 git 4e9f99f ②예측모델 최초 외생 검정(COT·WoodMac·PMI·한국산업생산) — 전부 WAPE ±0.01 노이즈, 채택 없음 ③수요측 3종 추가 적재(ISM·유로PMI·부동산, 피드 꼬리 정지 플래그) ④수집 cron 상시화(주간/월간) | WORKLOG 2026-07-24(최신⑫), 스코어카드 v1.8 |
| `documents/산출물/2026-W30_0720-0726/발주처협의안건_추가2건_260724.md` | 발주처 안건 추가 2건 — A. CO LME 재고 제공 요청(무료 경로 8종 전수 실패 근거), B. EV/배터리 장기 데이터 예산(무료분 2년치뿐 실측) | WORKLOG 2026-07-24(최신⑫) |
| `mineral_supply_risk/outputs/model_opt/diagnosis_priority_feeds_eval.md` (+ `scripts/collect_priority_feeds.py`, `scripts/diagnosis_priority_feeds_eval.py`) | 인벤토리 1~4순위 수집·검정 — SHFE 구리재고 1,165행·Comtrade REE/CO 월간 각 108개월·중국 PMI 2종 적재(fact_inventory_exch/fact_indicator/fact_series). **풀링 전부결합 유의 개선(QWK CI [+0.12,+0.18]·P=1.000, 오경보 -49%) — 3번째 실증, 고정밀 동작점 채택 권고**. CU 2축 기각(NI 패턴 미재현)·REE 방향긍정 보류·COMEX 무료경로 부재 | WORKLOG 2026-07-24(최신⑪), 스코어카드 v1.7 |
| `mineral_supply_risk/outputs/model_opt/co_inventory_recon.md` + `diagnosis_exch_inventory_eval.md` (+ `scripts/collect_exchange_inventory.py`, `scripts/diagnosis_exch_inventory_eval.py`) | CO 재고 수집 정찰(8경로 전수 실측 — **무료 자동수집 불가 확정**, 발주처 경유 안건) + 대체 수집: NI SHFE 재고 643행(2015~)·LI GFEX 창단 61주(공백 있음, 재수집 예정)를 `fact_inventory_exch`(신설, PK에 src)에 적재. 검증: **NI LME+SHFE 결합 유의 개선**(QWK CI [+0.20,+0.42], 오경보 -71%) — 재고→전환탐지 두 번째 실증 | WORKLOG 2026-07-24(최신⑩), 스코어카드 v1.6 |
| `mineral_supply_risk/outputs/model_opt/diagnosis_aux_features_eval.md` (+ `scripts/load_market_aux.py`, `scripts/diagnosis_aux_features_eval.py`) | 외부 직교 데이터 확보→검정 — 발주처 원본의 미활용 주간 LME재고(CU·NI 2007~)·거시 12종을 `fact_inventory`(2,030행)·`fact_series`(3,373행)에 최초 적재 후 전환탐지 재검정. **재고 피처가 CU·NI Δ분류에서 전환 적중 1/18→7/18·QWK 동반상승(부트스트랩 P=1.000) — 보조 조기경보 고정밀 동작점 신규 확보**. 거시=보류(커버리지 교란), 게이트=8번째 기각. CO/LI/REE 수집 경로 조사 포함 | WORKLOG 2026-07-24(최신⑨), 스코어카드 v1.5 |

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
