# 작업 이력 (WORKLOG)

> 커밋 해시는 `git log --oneline` 기준. 최신이 위.

## 2026-07-16 — 감사 잔여 4건 일괄(에이전트 병렬): 부분풀링·오버라이드·HS계층·event study

전부 DB read_only 병렬 평가(신규 스크립트 4본), 오버라이드만 결과를 운영에 반영.
- **① 부분 풀링(B-2③, partial_pooling_eval.py): 기각 — 완전풀링 유지.** 계층 Ridge의
  최적 풀링 강도 s=0.0(=완전풀링)으로 수렴(s>0 전 구간 과적합), MixedLM(+0.012)은 유의
  기준 미달. 감사 전제(LI≠CU 계수)를 심각 표본(13건, LI 1건)이 지지하지 않음. 각주:
  MixedLM이 심각 Miss 0.385→0.222(2케이스 차) — 미탐 치명 시 재검토 여지.
- **② 오버라이드 백테스트(B-2④, override_backtest.py): 재설계 반영.** 전체 On이 QWK
  0.937→0.416·FAR 0.044→0.592로 파괴적. 판정·적용: 변동성 유지(결과선행 lift ×3.7),
  편중 목표단계 경계→관심 강등(단독 FAR 0.20), **지정학 격상 폐지**(674주 상시격상·실현율
  기저 이하·지수와 이중계상; ALERT_OVERRIDE_GEO=on 복원 스위치, 사유 인용은 유지).
  alert.py 수정·재적재 — 분포 정상화(정상 68~196주/광종), 최신 경보 불변.
- **③ HS 계층 정합(B-3⑤, hs_hierarchy_eval.py): 요구 시 bottom-up.** coherence 문제
  실재(base 합산 불일치 8~16%), MinT/OLS는 규모차 300배 무시로 소계열 왜곡(HS4 MASE
  6~27배 악화) → 부적합 판정(원인 규명 포함). BU가 품목·총량 동시 제공의 승자(총량
  WAPE 22.9 — 현행 동급). 총량만 쓰는 현 운영엔 도입 불필요.
- **④ Event study(B-3⑥, event_study_lp.py): REE에서 정책 인용급 발견.** 풀링은 유의
  반응 없음(정직 — 이벤트 2024~25 편중, 검정력 낮음). REE 단독: 수출통제 공시 후
  **h=5~8개월 수입물량 +5~7%**(h=5 p<0.001, placebo 통과) — 실물 부족 이전의
  front-loading·대체조달 신호로 해석(인과 아닌 상관으로 신중 서술).
- 워드 상세판 §2-4(오버라이드 재설계)·§8(8·10 갱신, 11·12 신규) 반영.

## 2026-07-15 — 감사 잔여 6종 일괄: 지수 정밀화 3종·v2 재앵커 + 민감도·lead time·CU 조사(에이전트 병렬)

**지수 v2**(메인 세션, indexer 직렬 수정): ① 볼륨 드리프트 정규화 — 실측상 코퍼스가
2016 29.2만/년→2020~22 12.5만/년 감소 후 회복(증가 일변도 통념과 반대), EWMA 52주 기저·
평균1·클립 0.5~2로 시간축 눈금 통일(연대별 교정 -3.2/+3.9/+7.0pt) ② stock/flow 감쇠 —
수출통제·제재·정책 hl=13주/보도·파업·재해 2주/기타 4주, 질량1 커널(총량 보존), 감쇠 잔존
주간도 발행(3,439→3,529행) ③ 근사중복 키 dedup — 정규화 80자+토큰 정렬 키로 +112,167건
제거. 분포 변화로 **scale_k v2 재앵커**(CU 297/NI 125/CO 14/LI 12/REE 34, P90=88 복원
87.8~88.6 검증, publish 기본 버전 v2). 랜드마크(REE 수출통제 주간 97~100) 유지.
- 임베딩 표본 검증(신규 validate_neardup_embedding.py): 키 dedup 후 **잔존 근사중복 12.0%**
  (30버킷·6,161건, cos≥0.9) → 2단계(BGE-M3 전량, 수집서버 GPU 배치) 도입 필요 판정.
**에이전트 병렬 3건**: ④ 가중치 민감도(sensitivity_geo_weights.py) — 순수 곱 구조라 전역 스칼라 섭동은 퇴화(순위 불변, 부록 A 실증) → '성분평균 편차 ±30% 신축'(상대섭동)으로 검정:
rel·conc·imp_mult 강건(P90 집합 Jaccard 0.92~0.96), **severity·sgn 취약(0.67~0.70) →
정밀화 우선순위**. 복제검증 저상관은 v2 동시 개정 타이밍 탓(리포트에 원인 주석).
⑤ lead time(lead_time_eval.py) — **h=0~3개월 전 지평에서 Naive 대비 QWK 우위, 격차
+0.009→+0.229 확대**(0.919/0.891/0.859/0.821 vs 0.910/0.799/0.692/0.592), FAR≤1.8%.
h=0 Miss만 Naive 근소 우위(정직 명기). 비용민감 컷 스캔 부록(비용비 발주처 합의 필요).
⑥ CU 역방향(investigate_cu_proxy.py) — **가설 채택**: vol_spike 3건 전부 거시발(COVID·
Fed 긴축), 2024-05 COMEX 스퀴즈는 vol90 정의가 포착 못함, fx_vol 통제 후에도 음(-),
거시 AUC 0.59>교사 0.46. 대안: 백워데이션 진입 AUC 0.551(유일 >0.5). 권고: CU는 변동성
아닌 기간구조·수입집중 병행 해석(발주 문서 주석 채택).
**v2 전 체인 재적합**: prob isotonic Brier 0.121→0.106·ECE 0.086→0.028, 진단 **QWK
0.925·전환월 0.745**(Ridge 풀링 우승 불변), ablation 지정학 전환월 기여 +3.4→**+6.9%p**
(0.690→0.759 — 정밀화가 신호 순도 개선). 최신 경보 CU 심각/CO·REE 주의/LI 관심/NI 정상.
워드 2종 §2-3/2-4/5/5-1/8·요약본 5-1/5-2 갱신.

## 2026-07-15 — import_hhi 국가 기준 재배선 + 진단 재적합 (HHI 결함 교정 완결)

- normalize의 agg_trade_annual HHI 원천을 raw_customs_annual_bycountry(국가별 정본)로
  교체(총액·YoY·CAGR은 합계 기반이라 종전 경로 유지, bycountry 없는 환경 폴백+경고).
  교정 실측: LI 6,509·REE 6,941(만점 1만, 고집중) vs 종전 품목 HHI 2,434~2,687(무의미).
- 전 체인 재적합(마트→8후보 재검증→nowcast→alert→ablation): **QWK 0.905→0.910,
  전환월 적중 0.631→0.742(+11%p)** — 교정 HHI+이중 노출 지수 동시 반영 효과.
  Ridge(풀링) 우승 불변, 최신 경보 불변(CU 심각/CO·REE 주의/LI·NI 정상 — 안정성 확인).
- ablation 갱신: +수입구조(국가 HHI) 0.938/0.690 → +지정학 0.919/0.724 — 지정학은
  QWK 소폭 희생하되 전환 감지 +3.4%p(보조 신호 역할 일관). 워드 2종 수치 갱신.

## 2026-07-15 — 국가×광종 이중 노출 가중 (감사 후속 4번 완료) + 관세청 국가차원 결함 교정

**부수 발견(치명 등급)**: 관세청 수집기가 country←statKor(품목명) 오매핑 — 국가 차원 소실.
실API 검증으로 확인(국가는 statCdCntnKor1/statCd). 합계는 groupby-sum이라 정상(예측 무영향)
이나 **기존 import_hhi는 '품목 구성 HHI'였음(결함)**. 수집기 교정(country_cd·item_kor 보존).
- 국가별 연간 재수집: 161 HS × 2013~2025 = 2,093콜 → raw_customs_annual_bycountry
  39,962행·223개국(기존 테이블 보존). REE 중국 $3.0B 최상위 정합.
- build_kr_import_share.py: 국가별 수입비중(한글→영문 별칭 확장, 수입액 가중 커버리지
  93.5%) → geo refdata. **교정판 수입국 HHI: LI 0.59~0.67·REE 0.69~0.71 고집중 vs
  CU 0.08·NI 0.09 분산** — 종전 품목 HHI 대비 정책적으로 유의미.
- indexer._apply_kr_exposure(): imp_mult=(1+s_imp)를 광종별 이벤트 모집단 mean-one 정규화
  (P90 앵커 보존; 순수 곱 s_prod×s_imp는 비수입 생산국 이벤트를 0으로 지워 기각·주석화).
  실측: 이벤트 34.4% 매칭, 최대 배수 LI/REE 1.59·CO 1.48·CU 1.24·NI 1.19.
- 지수 diff: **REE 평균 +3.4pt·최대 +14.6pt(중국 수출통제 주간들), LI +1.0(2021 급등기),
  CU/NI 중립(+0.1~0.4)** — '한국의' 지수로 전환 의도대로. DB 재발행 완료.
- 잔여(후속): weekly_mart의 import_hhi를 국가 기준(연간 ASOF)으로 교체 재배선 +
  진단 재적합, 월간 국가별 재수집(19,320콜)은 월단위 국가 피처 필요 시.

## 2026-07-15 — 결과변수 proxy 라벨 구축·교차검증 (감사 후속 1(b), 1차 완료)

scripts/build_proxy_label.py: "향후 3개월 내 (①vol90>기준기간 P95) OR (②수입량 동월기준
-20% 이탈)"의 관측 가능 라벨 → mart_proxy_label(1,139 광종-월) + 교차검증 리포트.
- **합성 proxy는 AUC 0.44로 무정보처럼 보였으나 분해가 진실**:
  · ①가격 급변: 교사 0.60/모델 0.64 — 광종별 **LI 0.90·NI 0.91·REE 0.99**(강한 선행성
    실증), CO 0.52 무정보, **CU 0.18 역방향**(LME 거시·투기 변동성이 수급 지표와 다른
    동학 — 후속 조사 항목). 경보(경계↑)→가격급변 precision 0.43/recall 0.38.
  · ②수입 이탈: AUC 0.33~0.46, 기저율 40% — 월간 선적 덩어리짐 노이즈 지배로 **결과변수
    부적합 판정**(강화 정의 -20%×2연속·-30%도 동일). 분기 집계 재정의 후 재도입(로드맵).
- 결론: 경보 체계의 실물 선행성은 가격 경로에서 3개 광종에 대해 실증됨. 수입 경로
  라벨과 CU는 재정의·조사 필요, 최종 라벨 합의는 발주처 협의(A-1(a), 회의 안건).
- 워드 상세판 §8 로드맵 1번 "부분 잔여"로 갱신.

## 2026-07-14 — 예측구간 conformal 보수화(CQR) — 감사 후속 3번 종결

분위 HistGBM 구간의 과소커버(0.60/0.72) 해소. CQR: 보정 원점들의 OOS conformity score
E=max(q10−y, y−q90)(log공간)의 유한표본 (1−α) 분위를 가산폭으로 [q10·e^−Q, q90·e^+Q].
- 백테스트(누수 차단): 보정 원점 2022-06/12(실측 ~2023-12, 평가창과 무겹침) →
  **커버리지 0.60→0.73 / 0.72→0.85 (평균 0.79, 목표 0.80 달성권)**.
- 발행: 최신 가용 원점 3개(last_m−24/18/12개월)로 보정(ton 0.318/unit 0.164) —
  구간 sanity 확인(CU h=1 톤 17만~43만/점 21만). basis에 가산폭·보정원점 명세.
- 워드 2종 갱신(§2-5·§8 로드맵 3번 완료 처리, 요약본 5-3). 감사 로드맵 2·3번 종결 —
  다음 후보: 1번 proxy 라벨, 4번 이중 노출 가중.

## 2026-07-14 — 관세청 월간 백필 완료 → 156개월 재학습·재판정 (감사 후속 2·3 종결)

- 백필 완료: 161/161 HS, raw_customs_monthly 232,001행(2013~2025) → normalize:
  fact_trade_monthly 5,408→21,955행. **crontab 00:40 백필 항목 제거**(완료 정리).
- forecast_unit 재학습(표본 36→156개월, 광종별 156개월 완전 패널):
  · **대 계절나이브 재판정: 혼조→우위** — 금액 WAPE 28.1/19.4 vs 나이브 36.0/20.9
    (두 원점 모두 상회), MASE 0.93/0.94. 백필이 정확히 처방이었음이 실증.
  · **재귀 vs Direct 재판정: 재귀 유지**(MASE 0.94 vs 1.02) — 36개월 때(1.71) 대비
    Direct가 크게 좁혔으나 역전엔 못 미침. 자동 판정 로직이 상시 감시.
  · 단가 vs 랜덤워크: 우위 유지(MASE_unit 0.81/0.77 vs RW 1.02/0.81).
  · 80% 구간 커버리지 0.60/0.72 — 표본 확대로 구간이 좁아지며 과소커버(36개월 땐
    0.82/0.70). conformal 보수화가 후속(감사 로드맵 3번 잔여분).
  · 금액 직접예측이 156개월에선 경쟁력 회복(WAPE 18.6/28.4) — 분해 유지 근거는
    원점 간 안정성(28.1/19.4)+과업의 물량·단가 개별 산출 요구.
- 발주 워드 2종 성적 갱신(§2-5·§5·§6-2·§8, 요약본 5-3).

## 2026-07-13 — 수입예측 v2: Direct 다중기간+분위 구간(MC 합성) 구현, 재판정은 백필 후

감사 로드맵 2·3번 선구현(사용자 지시: 백필 재학습과 함께 진행).
- Direct h별 독립 HistGBM(계절항은 t+h 기준) + 분위 모델(q10/q90, log공간 → 단조변환 보존).
- 금액 80% 구간 = 물량×단가 마진 lognormal 근사 후 **몬테카를로 합성**(분위 직접 곱 금지).
- 점추정 방식은 백테스트 금액 MASE로 자동 판정(MSR_FORECAST_METHOD env 강제 가능).
- 36개월 실측: Direct 열세(금액 MASE 1.71 vs 재귀 0.94 — h별 학습행이 h개월씩 깎여
  소표본에서 구조적 불리, 원점1 ton MASE 16 붕괴) → **재귀 유지 + 구간만 Direct 분위 사용**.
  80% 구간 커버리지 0.82/0.70(목표 0.80 근접). 156개월 재학습 시 재판정 예정.
- 발행 스키마 확장: ton_lo/hi, unit_lo/hi, pred_value_lo/hi + basis에 method·interval 명세.

## 2026-07-13 — 외부 방법론 감사 대응: 즉시항목 5건 수정·실증, 나머지 로드맵化

감사 지적 16건 중 즉시 가능 5건 당일 처리(치명 1~4순위 + 5 일부), 잔여는 문서 §8 로드맵.
- **A-1(c) 단계 컷 앵커**: 교사신호는 KOMIS 외생 지표(순환 아님)임을 확인. 단, 컷이 전체
  분포 분위로 재계산돼 "항상 ~5%가 심각"이던 것을 기준기간(2020-01~2023-12) 동결 컷으로
  절대화(diagnosis_opt.ANCHOR_SPAN·anchored_cuts → nowcast·alert 배선). 효과 실측: 최신
  경보 LI·NI 관심→정상(상대분위 인플레 제거), CU 심각·CO/REE 주의 유지.
- **A-2 NB2 캘리브레이션**: P90 임계 look-ahead 감사 → **무혐의**(burst_k는 train만,
  기준선도 train 기저율). 과소예측 편향은 사실 → isotonic 사후보정 구현(OOS 쌍 시간순
  60/40 분할): 평가구간 Brier 0.1166→0.1120, ECE 0.059→0.044. 발행에 p_burst_cal 병기.
- **A-3 Ablation**(scripts/ablation_diagnosis.py): 진단에서 Δ지정학 QWK +0.001, 전환월
  적중 +0.035(0.655→0.690) — **작음(정직 기록)**. 주동력은 가격(전환 0.138→0.586).
  반전: **수입예측에서 geo exog 제거 시 금액 WAPE 37.9→103.8 / 18.2→24.0 붕괴** —
  파이프라인 존재 증명은 수입예측(단가 경로)에서 성립. 포지셔닝 전환: 진단 보조 +
  수입예측 exog + 독립 산출물(오버라이드·사유 인용).
- **B-3② 단가 정직성**: 랜덤워크(원점 단가 유지) 기준선 상시 병기 — MASE 1.20/0.73 vs
  RW 1.53/0.81 **두 원점 모두 모델 우위**(geo exog 동력). 우위 상실 시 시나리오 전환 설계.
- 문서: 워드 보고서에 §5-1(ablation 표)·§8(로드맵 10항) 신설, §2-4/2-5/4/5 갱신(발주 톤).
- 잔여(로드맵): proxy 라벨 교차검증, Direct 다중기간, 구간추정(conformal+MC), 이중 노출
  가중, lead time 표, 볼륨 드리프트, stock/flow decay, 임베딩 dedup, 부분 풀링, event study.

## 2026-07-13 — 수입예측 평가지표 교체: SMAPE → WAPE·MASE 주지표 (결론 일부 뒤집힘)

사용자 지적(SMAPE의 0 근처 분모 붕괴·저값 왜곡·광종 스케일 300배 차) 수용 — M4/M5 이후
표준대로 **WAPE**(Σ|F−A|/Σ|A|, 총합비율·0값 강건)와 **MASE**(계절 m=12 나이브 스케일,
광종별 정규화 후 매크로 평균, <1=우수)를 주지표로 병기(forecast_unit.py). SMAPE는 이력
비교용 유지. 동일 데이터(36개월, 재정규화 전) 재실행 결과:
- **분해>직접 결론은 강화**: 금액 WAPE 분해 18.2~37.9 vs 직접 38.6~59.7 — 직접예측이
  2차 원점에서 붕괴(SMAPE 43.6이 가려주던 실패가 WAPE 59.7로 노출).
- **대 계절나이브 결론은 뒤집힘(혼조)**: MASE 분해 1.13/0.76 vs 나이브 0.73/0.84 —
  원점 2024-06에선 나이브가 우세. SMAPE(25~31 vs 28~32)가 근소 우위처럼 보이게 했던 것.
  원인은 학습 36개월(계절 실질 2주기) — **백필 완료(156개월) 후 재학습이 선결**.
- basis(근거 JSON)에 지표 설명 포함, 발주 보고 워드 문서 §2-5·§5도 새 수치로 갱신.

## 2026-07-12 — 아키텍처 정합: "전처리기→DB→추정기" 배선 + 주/월 실행 체인 완결

5모듈 분리(수집기/전처리기/지정학 추정기/수급위기 진단기/수입 추정기) 점검 결과 갭 2건 해소.
- **갭① 추정기의 DB 읽기 전환**: 기존엔 extract(→parquet)→index(parquet 읽기)→publish(사후
  발행) 순서라 "전처리기가 DB에 넣고 추정기가 DB에서 읽는" 계약과 반대였음.
  · `geo publish --what events|index|all` 단계 분리(publish.py) — events는 extract 직후,
    index는 추정 직후 발행. geo_event에 **provider·extractor 컬럼 추가**(빠지면 DB 모드에서
    GKG '뉴스' 티어 제외가 무력화되는 조용한 회귀 — 발견 즉시 방지). 신규 컬럼 출현 시
    DELETE+INSERT가 죽으므로 컬럼 셋 비교 후 테이블 재생성 폴백.
  · `store.load_events(source=)` + env `GEO_EVENT_SOURCE=db`(+`GEO_PUBLISH_DB`) — 추정기
    (indexer·prob) 전용 모드. publish 계약(commodity_code, source '')→내부 계약 복원.
  · indexer: source 컬럼 기존재 시 manifest 병합 스킵(충돌 방지).
  · **동치성 실증**: DB 모드 compute() 3,439행 = 파일 모드 geo_index와 전 행 매칭,
    지수 최대 차이 0.0. prob 주간 패널도 DB 모드 2,745행 정상.
- **갭② 주/월 실행 체인 완결**(`scripts/schedule.py` 전면 재작성):
  · weekly = ingest-bundles→extract→publish(events)→index(DB)→prob(DB)→publish(index)
    →weekly_mart→nowcast→alert→publish_results. geo는 서브프로세스(단계 격리, cwd=komir).
  · monthly = 관세청 최근 24개월 **증분**(신규 `pipeline.collect_customs_incremental` —
    HS×연도구간만 삭제 후 삽입; 기존 collect_customs는 전삭제형이라 2013~22 백필 유실 위험)
    →ECOS→normalize→features→forecast_unit→publish_results.
  · cron 2줄(월 06:00 weekly / 매월 1일 07:00 monthly)로 운영 투입 가능 — 남은 과제 ⑥의
    분석서버 반입·기동만 잔여.

## 2026-07-12 — 미/중 공시 10년 백필 테스트 (/goal) — 지수 반영 실증

"최근 10년치 공시 수집→백데이터 채움→지정학지수 반영 가능?" 검증.
- 미국: 기존 백필(886건)이 이미 2016~2026 연도별 고른 분포(150/93/63/59/78/55/55/78/124/91/40)
  — 절단 없음, 10년 커버 확인.
- 중국: 목록 JS렌더링 한계 우회 — **Wayback CDX로 공고 URL 인벤토리**(aqygzj 130 + 구 상무부
  zcfb 69) 확보 후, 라이브 우선·죽은 구 경로는 아카이브 스냅샷에서 본문 수집
  (`collector/cn_trade_backfill.py` 신설, 1회성). 신규 122건(2020:6/2024:39/2025:67/2026:10 —
  Wayback 아카이브 밀도 한계로 2016~23 희박, 2024~25 수출통제 격화기는 두껍게 확보).
- 추출: CN_MOFCOM 이벤트 5→**55건** — 2025-04 中중희토류 수출통제 결정, 2025-10 희토류
  생산설비·원부자재 수출통제(통제품목 코드 2B902/1C914 원문) 등 역사적 공고가 1차 사료
  sev 3.0으로 적재.
- 지수 반영 실측(diff): REE 2025-01-19 주 +24.3pt(43.6→67.9), 2026-03-01 주 +21.3pt(→94.2),
  2025-09-21 주 +11.6pt 등 — 영향은 REE(평균 +2.85)에 집중, CU/NI는 GKG 볼륨에 희석(±0.1).
  결론: **백필 공시가 지수에 정상 반영되며, 특히 REE 수출통제 국면의 백데이터가 1차 사료로
  강화됨**. 잔여 한계: 중국 2016~23 공고는 Wayback 미보존分 다수 — GKG(보도 기반)가 해당
  구간을 보완(이미 반영돼 있음).

## 2026-07-12 — 미/중 고시 LLM 연동 검증 (/goal) — 정상 확인

점검 4단계: ① vLLM(gemma-4-26b-a4b) 엔드포인트·models.yaml(provider=openai_compat) 정상
② 저장 이벤트 44건 전부 extractor=llm/gemma — 중국어 고시 해석 품질 육안검증(실체명단→
Export Control supply_down, 对日 심사강화→Geopolitical Tension 등 정확) ③ 라이브 재해석
테스트 — 중국 공고 conf 0.9 정상, 미국 1건은 직접호출(폴백 미경유) 0건이나 프로덕션 경로
(json_mode=False 폴백)로는 정상 추출(반덤핑 일몰재심→CU/무역정책) ④ 간헐 빈응답 누락 정량화:
0건 관련문서 81건 전량 재시도 → 추가 1건뿐(44→45) — 나머지 80건은 광물 무관 절차성 공시를
LLM이 올바르게 기각한 진성 0건. 결론: 연동 정상, 누락률 극소(1/82).

## 2026-07-12 — 관세청 월간 2013~2022 백필 시작 (진행 중)

월간이 2023~25만 있던 이유 = API 일 한도(≈1만 콜)로 당시 최근 3년만 수집. 일 한도는 자정
리셋이므로 자체 백필 가능 — `scripts/backfill_customs_monthly.py`로 시작(19,320콜 = 161 HS ×
120개월, 기존 보존형 멱등·상태 재개). **호스트 crontab 00:40 자동 재개 등록** — 2026-07-14경
완료 예상. 완료 후: fact_trade_monthly 재정규화 → forecast_unit 재학습(표본 36→156개월) →
crontab 정리. (메모리 customs-monthly-backfill에도 기록됨.)

## 2026-07-12 — 수입 예측 v2: 단가 분해 모듈 (`msr/models/forecast_unit.py`) — /goal 수행

월 단위 h=1~12 수입 예측을 사용자 지정 구조로 재설계: **금액 = 광물당 톤당 단가(USD/ton) ×
톤(실지출액)** — 물량과 단가를 각각 지도학습(관세청 월간, HS 확정 161코드 바스켓→5광종 필터)
후 곱으로 재조립(항등식 정확 성립).
- 구조: 단일스텝 HistGBM ×2(log톤·log단가, 광종 풀링+더미) 재귀 h=12. 피처 = 자기시차
  (1·2·3·6·12)+롤링3+월 계절성+외생(LME 월평균가·원달러 환율 CSV·지정학 지수 — 예측구간
  최종값 고정, 시나리오 입력 대체 가능 설계).
- 백테스트(워크포워드 2오리진×12개월, SMAPE%): **분해 금액 25.3~31.2 < 직접 금액예측
  36.1~40.0 < 계절나이브 27.9~31.8** — 분해 구조의 우위 실증(단가가 LME에 계류돼 22~27%로
  잘 맞고, 물량은 나이브 대비 소폭 우위). 톤 29.8~35.6.
- 발행: out_import_forecast_unit 60행(base 2025-12 → 2026-01~12) — pred_ton·
  pred_unit_usd_per_ton·pred_value_usd/천달러 + basis(백테스트 근거·지도학습 정의 json).
  publish_results 대상 등록(외부 DB 연동 포함).
- 참고: NI 단가(500~880 USD/ton)가 낮아 보이는 것은 바스켓 혼합 단가 특성(중량 대부분이
  저단가 광석·페로니켈) — 정의상 정상. 학습표본 36개월(관세청 월간 한도 제약) — 2013~22
  월간 백필(발주처 경유)이 정확도 개선의 최대 지렛대.

## 2026-07-12 — 예측 결과 DB화 + 외부 DB 연동(env 주입)

"DB 접속 URL·스키마를 외부 환경에서 주입, 예측 결과와 근거를 DB화" 요구 구현.
- `db/dbio.py::write_df`에 schema 파라미터 추가 — SQLAlchemy to_sql(schema=)로 Oracle 스키마/
  MariaDB DB 지정, DuckDB면 CREATE SCHEMA 후 사용.
- `scripts/publish_results.py` 신설 — env 계약: MSR_PUBLISH_DB(:// 포함=서버DB URL, 아니면
  DuckDB 경로)·MSR_PUBLISH_SCHEMA(선택)·MSR_DB(원천). 발행 테이블(근거 동봉): out_diagnosis_alert
  (4단계+법정 사유·모델 원천·확률·기여·이벤트 인용), mart_diagnosis_nowcast(예측 지수+XAI json),
  out_import_forecast, geo_index, geo_prob.
- E2E 검증(SQLAlchemy 경로 — sqlite 대역, Oracle/MariaDB와 코드 경로 동일): 5테이블 8,326행
  발행, 외부 DB에서 사유·stage_probs·contrib 필드 원문 조회 확인.

## 2026-07-12 — 수급위기 진단 대시보드 프로토타입 (`dashboards/`)

주간 4단계 진단을 UI화(산출물 ③ 모니터링 대시보드의 선행 프로토타입) — 자체완결 단일 HTML
(외부 의존 0, 폐쇄망 게시 가능). 구성: 5광종 요약 카드(단계 chip·신뢰도)/주간 위기지수 차트
(2020~, 하단 단계 리본+지정학 지수 오버레이+클릭으로 주 선택)/선택 주 법정 사유(모델 원천·
확률·기여 병기 문안 그대로)/최신월 XAI 패널(단계 확률 스택바+기여도 다이버징 바, 피처 한글화)/
최근 16주 이력 테이블. 경보색은 붙임2 법정 명칭·색(관심 Blue/주의 Yellow/경계 Orange/심각 Red)
그대로, 다크/라이트 테마 지원. 데이터=warehouse 스냅샷 임베드(재생성 절차는 dashboards/META).

## 2026-07-12 — 최적모델 alert 배선 + XAI(설명가능성) 산출

diagnosis_opt 1위 구성(Ridge 풀링+AR+분위매핑)을 운영 배선하고 착수보고의 XAI 약속 이행.
- `msr/models/nowcast.py` 신설: 전 기간 재적합 → mart_diagnosis_nowcast(월×광종 390행 —
  ci_pred·4단계·단계확률·기여도 json) + final_model.joblib + xai_latest.md.
  · 기여도: Ridge 선형 정확 분해(계수×표준화값, SHAP 선형 특수해와 동일) — 위기지수 방향 부호.
  · Confidence: 광종별 학습잔차 σ 정규근사로 단계별 확률(착수보고 "경계 55%, 심각 30%" 사양).
- `alert.py` 배선: 위기지수 원천 = 모델 nowcast 우선(1,632/1,632주 결합), 교사 폴백,
  ALERT_CRISIS_SOURCE=teacher로 구동작 강제 가능(감사용). 사유 문안에 원천표기(model)+
  단계확률+기여도 상위3 병기 — 예: "[CU·심각(Red)] …(수급위기지수 99/100(model), 지정학1.00)
  확률: 심각 55%, 주의 19%. 기여: y_lag1 +33.1, price_z52 +3.2, …. 관련 이벤트: 'First
  Quantum…'(Panama, sev 3.0/3)".
- 분포 영향 미미(모델이 교사와 고일치 — QWK 0.905), 최신 경보: CU 심각·CO/REE 주의·LI/NI 관심.

## 2026-07-12 — 진단모델 최적화 (`msr/models/diagnosis_opt.py`) — /goal 수행

백데이터(실교사 2020~2026·지정학 2016~) 기반 체계 비교로 4단계 진단모델 최적화.
- 방법: 워크포워드 3폴드(test 2023/2024/2025~), 후보 8종(Naive 지속/Ridge·HistGBM 풀링·광종별
  ×회귀→분위매핑/과업지시서 명시 Logistic·DT·RF 직접분류), 지표 QWK·macroF1·RPS·전환월 적중률.
- 1차 실행의 발견 2건: ① 지속성 Naive(QWK 0.884)가 전 모델 압도 — 진단(nowcast)에서 전월
  교사값은 가용 정보인데 피처에 없었음 → y_lag1(자기회귀항) 추가. ② VIF 폭발 — geo level·
  lag·chg 완전공선 → level+chg만 유지(붙임1 상관성·중복성 분석이 실제로 작동한 사례).
- 최종(3폴드 평균): **Ridge(풀링)+분위매핑 QWK 0.905 > Naive 0.884**, RPS 0.032<0.038,
  **전환월 적중률 0.631 vs Naive 0.000**(단계가 바뀌는 달에서 모델의 실가치 입증, n_chg 기준).
  광종별(최종 폴드): CU 0.961·REE 0.941·LI 0.88·CO 0.768·NI nan(2025~ 전 기간 '정상'이라
  카파 정의불가 — 데이터 특성).
- 피처 민감도(제거 시 QWK 하락): y_lag1 0.823 ≫ price_z52 0.022 > **geo_chg 0.016** >
  **p_burst 0.007** > import_cagr3 0.005 — 지정학 파생피처(변화량·burst확률)가 측정 가능한
  한계기여 확보(레벨 단독은 지속성에 흡수됨).
- 산출: outputs/model_opt/{comparison(_folds).csv, per_commodity.csv, corr_vif.txt, report.md}.
- 다음: 최적 구성(Ridge+AR+분위매핑)을 alert 레이어의 점수단계 산출기로 배선(현재 alert는
  교사 직접 사용 — 운영에선 교사 발표 지연을 모델 nowcast로 메꾸는 구조로 전환).

## 2026-07-12 — 4단계 수급위기 진단 첫 실데이터 산출 + 오버라이드 소스 제한

진단의 계약상 최종 산출(주간 4단계: 관심/주의/경계/심각)을 실데이터로 첫 가동 —
mart(실가격·실교사) + geo_event → out_diagnosis_alert 1,632주(5광종×2020-01~2026-05).
- 버그성 과다경보 발견·수정: geo_event가 GKG 182만건을 포함하게 되면서 지정학 오버라이드
  (severity 3 → 격상)가 거의 매주 발동 → '심각'이 주의 25~30%. 오버라이드 트리거를 고신뢰
  소스(관보 US_FederalRegister/CN_MOFCOM + 큐레이션 보고서)·supply_down으로 제한 — 붙임2
  계열1("수출제한 실시")은 뉴스 보도가 아니라 확정력 있는 근거로만 발동해야 하고, GDELT
  뉴스 신호는 이미 변수⑥(지수)으로 점수단계에 반영되므로 이중계상 방지 겸.
- 수정 후 분포(주 단위): 정상 20~38% / 관심·주의 / 심각 6~19%(COVID·우크라이나·DRC 수출중단·
  중국 수출통제 국면 포함 기간임을 감안하면 타당 범위). 최신 주: CU 심각, CO·LI·REE 주의, NI 관심.
- 남은 것(v1 §7-4 완전체): 단계 = max(점수단계, 계열1, 계열2) 구조로 개편 + dimension 백필
  기반 계열2(시설·수송) 트리거 — 현재는 기존 alert_rule_v1(분위수+오버라이드+히스테리시스) 유지.

## 2026-07-12 — 실가격·교사신호 로딩 → 진단모델 첫 실데이터 가동

`scripts/load_komis_xlsx.py` 신설 — KOMIS 제공 xlsx를 warehouse에 적재, SYNTH 완전 교체.
- 가격(fact_price 6,839행): 「KOMIS 핵심광물 공급망 통계」 '주간 평균' 시트 단일 소스로 5광종
  전부 확보 — CU/NI: LME CASH+3M(2001~), CO: LME CASH(2010~), LI: 탄산리튬 CIF China(2018~),
  REE: 산화네오디뮴 FOB China(2010~). 전부 2026-06까지.
- 교사(fact_indicator 385행): 수급동향지표.xlsx 월별 2020-01~2026-05, 5광종(REE=네오디뮴 컬럼).
- SYNTH는 fact_*_synth_backup 테이블로 백업 후 제거(보존 정책). 재실행 멱등(키 삭제 후 삽입).
- 마트 재빌드: 1,610(합성)→4,601행(실데이터), 교사 1,632·지정학 2,844·생산HHI 351·변동성 4,591.
- 진단 첫 실데이터 결과(월간 패널 390행, train 300/test 90=2025~):
  Ridge R² 0.701(MAE 10.87) vs Naive 0.263 — 실질 예측력. 위기 이진분류 AUC 0.988(위기율 23%).
  피처 중요도: import_hhi 0.39 > ref_price 0.30 > spread 0.17 > … > geopolitical_risk 0.01.
- 관찰: ⑥ 중요도가 아직 낮음 — (a) 교사가 시장결과형 지표라 가격·교역 구조에 1차 반응
  (b) 지정학은 평시 평균이 아니라 꼬리/전환점에 기여(경보 계열1 오버라이드가 그 몫)
  (c) 풀링 GBM 기준 — v1 §7의 광종별 가중(REE·CO 지정학 강조)·ordered logit에서 재평가 예정.
  production_hhi는 가용 시점(2025-02+) 제약으로 이번 패널에선 자동 제외 — refdata 백필 후 복귀.

## 2026-07-12 — 일일 운영 모드 확정: `collector daily` + zip 번들

수집기를 "매일 1회: GDELT 하루치 캐치업 + 뉴스/미·중 공시 수집 → collect_YYYYMMDD.zip" 모드로
확정(사용자 지정 — 압축 포맷 zip).
- bundler: tar.gz → zip(ZIP_DEFLATED) 전환, CRC 무결성(testzip)+멤버수 재검증 유지.
- `collector daily` 서브커맨드(수집→즉시 번들, cron용) + daemon `--bundle-each`(compose 기본
  CMD를 1440분+bundle-each로 — 컨테이너 단독으로 일일 운영). 뉴스 기본 소급 2일(경계 유실 방지,
  seen 중복방지가 이중수집 차단).
- geo ingest-bundles: zip/tar.gz 양쪽 수용(하위호환).
- E2E: daily 1회 실행(gkg 4 + gnews 57 + us 886 + cn 16 → zip 9.2MB) → 분석기 발견·라우팅
  (txt 959→inbox, gkg 4→gkg_bulk→파싱 3이벤트) → 멱등 재실행 0건.

## 2026-07-12 — 연간 발행물의 연 단위 적용: 지수 Y 시리즈 + 변수⑤ USGS 배선

사용자 방침("연간 발행 보고서는 연 단위 적용") 구현.
- indexer: 연간(YS) 시리즈 추가 — USGS·IEA·광업요람 등 연간 발행물 이벤트가 연 단위 배경
  신호로 자연 집계(붙임1 다중주기 요구의 '연' 대응). 주기 배수(scale_k×{W:1, M:52/12, Y:52})
  도입 — 주간 P90=88 앵커 의미를 월/연에서도 보존(도입 전 연간은 raw가 52배라 즉시 포화).
  산출 분포 검증: Y 중앙값 62~74·max 81~96(포화 없음). geo_index 3,439행(W 2,743+M 639+Y 57).
- 변수⑤ 배선: scripts/load_usgs.py 신설 — USGS 엑셀정리본(MCS2026 피벗데이터) →
  fact_production_reserve(207행) + agg_production_hhi(광종×연도 생산/매장 HHI, avail_date=
  발행 익년 2/1로 미래참조 차단). weekly_mart에 ASOF 배선 — production_hhi 280행 채움
  (2025-02 이후 행. 2016~23 백필은 수집서버 geo refdata 실행 후 번들 반입 경로).
  HHI 실측치 타당성: CO 0.56(DRC)·REE 0.51(중국)·NI 0.46(인니)·LI 0.20·CU 0.12.
- 남은 배선: 변수④(세계 공급부족 — WoodMac 수급밸런스 CU·NI parquet 확보됨) + 실가격/교사
  xlsx 로딩(SYNTH 교체) → 이후 B v0 스코어카드 가동 가능.

## 2026-07-12 — 번들에 GKG 포함 + 분석서버 오프라인 대응

분석 서버가 외부 인터넷 불가로 확정 — 일자별 번들이 유일한 데이터 반입 경로가 되도록 확장.
- bundler: GKG zip을 번들에 포함(tar 내부 inbox/ + gkg/ 2계층). gkg 증분 상태는 타임스탬프
  기반이라 원본 이동에 영향 없음.
- ingest-bundles: 멤버 라우팅(txt→inbox→ingest / gkg zip→$GEO_DATA/gkg_bulk→gkg-parse 자동
  연쇄, --no-gkg-parse 분리 옵션). 구버전 번들(inbox/ 접두 없음) 하위호환.
- E2E: 기사 2건+실제 GKG zip 2개 → 번들 → 라우팅 전개 → ingest 2 archived(소스 정상 인식)
  + gkg-parse 7이벤트 → 재실행 멱등 0건.
- 오프라인 제약 문서화: LLM은 내부망 vLLM으로 충족, USGS refdata는 수집서버 실행 후 번들 반입,
  도커 이미지는 외부 빌드 반입(collector/README).

## 2026-07-12 — 일자별 번들 인도 프로토콜 (수집기→분석기)

수집기가 매일 inbox를 collect_YYYYMMDD.tar.gz 하나로 묶고(데몬 날짜전환 자동 or `collector
bundle` cron), 분석기가 볼륨에서 번들을 발견해 처리(`geo ingest-bundles` — 전개 후 ingest 자동
연쇄). 기존 파일 계약 위의 전송 형식 변경이라 수정 범위 작음(양단 모듈 1개씩).
- 원자성: .part→rename + 멤버수 재검증. 원본은 _bundled/로 이동(삭제 안 함 — 번들이 일자별
  원시 아카이브 겸임, 보존 정책 정합).
- 멱등: bundles_done.txt 상태 + ingest 파일해시 dedup 2중 방어(재실행 무해 실증).
- 안전: tar 경로탈출 방어, .txt 멤버만 전개.
- E2E 검증: 수집(3건)→번들→발견→전개→ingest(3 archived)→재실행 0건.

## 2026-07-12 — 미국/중국 수출입 공시 → 지정학 위기지수 배선 완성

수집기(us_trade/cn_trade) 산출을 geo 파이프라인에 실배선 + 2016~ 백필 실투입(미국 886건·중국 16건).
- 배선: sources.yaml에 US_FederalRegister/CN_MOFCOM 신뢰도 1.4(관보=1차 사료, 분석보고서 1.3보다
  높게), classify.source_of 경로 인식, GEO_KEYWORDS·COMMODITY_KEYWORDS에 중국어 추가(없으면
  중국 공시가 프리필터에서 전량 탈락).
- 버그 3중 연쇄 발견·수정: ① LLM이 광종 불특정 공시에 commodity='mixed' 반환 → 스키마 검증
  조용한 탈락 — 본문 광종 탐지 확장(광종별 이벤트化, 미탐지 시 스킵). ② as_event_list가 "{}"
  응답을 빈 이벤트 1건으로 반환(truthy라 재시도도 우회) — 빈 dict 필터. ③ vLLM json_object
  강제모드가 "JSON 배열만" 프롬프트와 충돌, 중국어 입력에서 "{}" 도피 지속 — 빈 응답 시
  json_mode=False 폴백 추출기로 재시도(실측 0/5→3/5 문서 성공).
- 결과: 공시 이벤트 44건(US 39: 러시아 산업제재·232/301조·수출통제 개정 / CN 5: REE 4 —
  전략광물 수출통제·실체명단). 지수 diff 실측: REE 2023-10-22 주간 51.6→74.4(+22.8pt, 중국
  수출통제 국면), REE 최신주 +18.2pt, LI 최대 +14.0, CO +11.8. CU/NI는 GKG 볼륨에 희석돼
  평균 ~0(개별 주간 최대 ±1.8) — 영향은 REE·CO·LI 공시 주간에 집중(과업지시서 Step2의
  "희토류=지정학 무기화" 설계 논리와 정합). warehouse 재발행·마트 재빌드 완료.

## 2026-07-12 — GKG 재검증 완료 → 프로덕션 지수 체계 완성 (v1 §11 순번 1~2 종결)

- **재검증 최종**: 2,008,521건 검증 — 확정 1,799,238(89.6%)·기각 209,283(10.4%). 샤드 691개
  병합+기각 실삭제 → geo_data 스토어 1,808,524건(전량 extractor=llm). 문서 이벤트 6,510건+
  manifest 2,801건을 geo_data로 병합해 **프로덕션 단일 스토어**(1,815,034건) 구성.
- **광종별 scale_k 확정 캘리브레이션**: GKG는 CU/NI만 전용 테마코드가 있어 주간 |raw_score|
  규모가 광종 간 최대 70배(P50: CU 220 vs LI 3) — 단일 k로는 CU 포화·LI/CO/REE 무반응.
  `scale_k_by_commodity` 도입(schema/indexer/index.yaml), 앵커=각 광종 P90→지수 88, 동결
  (CU 447/NI 165/CO 14/LI 12/REE 20). 재산출 후 5광종 전부 실동적범위 확보(이전 LI/CO/REE
  50 고정 → IQR 50~80). 반복보도 dedup이 GKG에서 471,101건 걸러냄(설계 검증).
- **확률모델 v2 — burst 타깃**: GKG 병합 후 "심각 이벤트 ≥1건" 기저율이 0.83~1.0으로 포화
  (CU/NI 상시 1.0 = 무정보) — 조기경보 신호를 **P(주간 심각수 ≥ 광종별 P90 임계)**(burst)로
  승격, NB2 생존함수로 산출(p_severe_next는 하위호환 유지). REE에서 NB MLE α가 0으로 붕괴해
  포아송 폴백→꼬리 과신 문제 발견 → Cameron-Trivedi 모멘트 α 폴백 추가(α=6.81로 교정).
  검증(burst, test 2024+): CU·NI·REE 기준선 대비 개선 / CO 동률 / LI 열세 — LI·CO burst는
  외생 서프라이즈 성격이 강해 현 피처(자기이력+지수+보도량)로는 한계, 가격·재고 공변량 추가가
  다음 단계(v1 §3 보조 변수 배선 시).
- **발행**: warehouse에 geo_index 3,382행·geo_event 1,815,034행·**geo_prob 2,745행(신규 테이블)**.
  mart_weekly_diagnosis 재빌드 — geopolitical_risk 분산 확보(sd 6~18, 이전 50 고정)로 진단모델
  변수 ⑥이 실질 피처로 가동.

## 2026-07-12 — 독립 수집기 도커(`collector/`) 신설 + 미국/중국 수출입 공시 수집

분석기(geo)와 **다른 서버**에서 단독 실행되는 수집 전용 패키지·도커. geo 코드 의존 없음 —
접점은 $COLLECT_OUT 파일 계약뿐(inbox 텍스트=geo ingest 호환 / gkg zip=gkg-parse 호환).
- 구성: gkg_incremental(15분 타임스탬프 직접 생성 — 마스터리스트 불필요, 상태 재개형),
  gnews·gdelt_doc(기존 이식), **us_trade 신설**(Federal Register 공식 API — BIS 수출통제·
  Entity List/USTR 301조/ITA, since 상태 기반 증분+2016 백필), **cn_trade 신설**(상무부
  안전관제국 aqygzj.mofcom.gov.cn — 전략광물 이중용도 수출통제 공고·실체명단·대변인 문답).
- 실측 이슈 2건: ① mofcom 하위 목록은 JS 렌더링(jpaas) — 메인 페이지만 서버 렌더링이라
  주기 수집은 메인만 긁음(과거 백필 불가, GKG 보완). ② slim 컨테이너에서 apparent_encoding이
  중국어를 오판해 키워드 필터 전멸 — UTF-8 명시로 해결.
- 검증: 호스트+도커 양쪽 스모크(us_trade 1건/cn_trade 16건/gkg 증분 3파일/gnews 10건).
- 운영: docker compose(60분 데몬), NAS 볼륨 공유 → 분석 서버가 rsync 또는 직접 마운트.

## 2026-07-09 — 지수 확률화: NB2 강도모델 (`geo/prob_model.py`, v1 문서 §6-3)

geo_idx(점수)를 "다음주 심각(sev≥2) 이벤트 발생확률"로 번역하는 확률 레이어. 실측 과산포
(주간 이벤트 분산/평균 3.7~6.6, 포아송 전제 기각)에 따라 순수 포아송이 아닌 음이항(NB2,
포아송-감마 혼합 = Cox process 정상형) 회귀 채택. λ = exp(β₀+β₁·EWMA심각수+β₂·geo_idx+β₃·log
주간전체이벤트수), 발행값 P(≥1)=1−(1+αλ)^(−1/α). `geo prob` CLI, 산출 store/geo_prob.parquet.
- 검증(시계열 분할 train~2023/test 2024+): 5광종 전부 학습기저율 상수 기준선 대비 Brier 개선
  (CO 0.138 vs 0.658 / CU 0.089 vs 0.106 / LI 0.268 vs 0.404 / NI 0.175 vs 0.216 / REE 0.295
  vs 0.498). α 전부 유의(0.7~3.5) — 과산포 실재 확인.
- 부수 발견·수정: LLM이 전망 문장("2028년부터 확대")의 미래 시점을 obs_date로 뽑는 문제(7건) —
  extract.py에서 발행일 초과 obs_date는 horizon_months로 이관+발행일로 교정(근본), indexer/
  prob_model에 미래날짜 방어선, 기존 7건 패치. geo_index 2,087→2,076행 재산출.
- 검증 기준선 버그 즉시 수정: 테스트 실현율을 기준선으로 쓰면 오라클(미래 참조) — 학습기간
  기저율로 교체.
- 잔존 한계: 2024+ 체계적 과소예측 경향 — 코퍼스 커버리지 성장(Argus 일일보고서 2023-09+)으로
  "기록되는" 이벤트 기저율 자체가 비정상. GKG(2016~2026 균일 15분 주기) 병합 후 재적합하면
  해소 예상 — β₃(보도량 통제)로는 부분 흡수만 됨.

## 2026-07-08 — 변수⑥ 배선 완성: geo_index → mart_weekly_diagnosis 조인 (v1 문서 §11-3)

감사 이래 "생성은 되나 연결이 없어 항상 NULL"이던 지정학 지수를 진단 마트에 실제 배선.
- `msr/features/weekly_mart.py`: geo_index(freq='W') ASOF 조인 추가 — 마트 관측일 이전 최근
  주간지수(주말 라벨이라 직전 완결 주 = 미래참조 없음, 검증 완료). geo_index 미발행 환경에서는
  기존처럼 NULL 폴백(하위호환). 치환 문자열 내 SQL 인라인 주석이 쉼표를 삼키는 파서 오류 1건 수정.
- `geo/publish.py`: LLM 불량 obs_date("202X-09-01" placeholder, "2023-02-29" 달력불가) 방어 —
  형식+달력 검증 후 불량은 NULL. `geo/extract.py`에도 근본 수정(LLM date를 `_valid`로 검증 후
  폴백사슬). 기존 저장분 1건 수리.
- `geo/indexer.py`: gkg_verify 통과 이벤트(provider=openai_compat)가 GDELT 신뢰도 0.7 매핑을
  빠져나가 1.0으로 계산되던 버그 수정 — manifest 미매칭 잔여 source는 전부 GDELT 귀속.
- 검증(warehouse 사본): publish 2,087행+6,510행 → mart 1,610행 전부 geopolitical_risk 채움(100%),
  diagnosis.py가 자동으로 피처 포함(기존 "전부 NULL이면 제외" 로직 통과). 현재 중요도 ~0은 예상대로
  (교사신호=SYNTH, scale_k 잠정, GKG 미병합) — GKG 재검증 완료 후 재캘리브레이션하면 분산 확보.
- ⚠️ 정본 `warehouse/minerals.duckdb`가 root 소유(docker 잔재) — chown 후 정본 재발행 필요.

## 2026-07-08 — 모델 설계 정본 v1 작성 (`documents/claude_output/mineral_risk_model_v1.md`)

v0 뼈대 + 과업지시서(붙임1·2 원문, 붙임2 경보기준표는 OCR 판독) + 착수보고(39p 전량 OCR — 임베딩
폰트 유니코드 매핑 파손으로 pypdf/fitz 모두 한글 추출 불가, easyocr로 해결)를 대조해 작업 기준
문서 v1.0 확정. 핵심 결정: 산출물 구조를 과업지시서에 정렬(지정학지수=필수변수⑥의 공급기, 계약
산출물은 진단 B·예측 C), 필수 6변수+신규 3(GSCPI 확보/원자재지수[P]/WGI) 변수사전, 광종별 차등
가중치 매트릭스 초기값(과업지시서 Step2 앵커 준수 — 기존 감사 최대 누락 시정), 붙임2 경보 3계열
병렬 max 결합(가격 주축 역전 시정), severity 0~3·GeoEvent 현행 스키마 유지+dimension/article_count
추가, HS 확정 161코드로 v0 초안 폐기, 9월 납기 역산 구현순서 10단계, 발주처 블로킹 이슈 8건 정리.

## 2026-07-07 — ingest 파이프라인 실행검증·버그 4건 수정

`documents`(구 `documens`) 내 실자산(보고서_1·2, 조달청, EU SCRREEN, WoodMac, IEA, KOMIS 광업요람)
대표 10건을 실제 `geo ingest`→`extract`에 태워 실행검증(요청: "실행해봐주세요, 정상적으로 되는지
체크"). 4개 버그 발견·수정 — 상세는 `documents/claude_output/지정학위기지수_데이터수집현황_260707.md` §7.

- `classify.py`: `date_of()` 비0패딩 날짜(`2020.5.12`) 폴백 정규식 `_D1_LOOSE` 추가.
- `classify.py`: `source_of()`에 조달청("비철금속시장동향", 공백무관) + EU SCRREEN 패턴 추가.
- `classify.py`: `commodity_of()` 파일명 우선 검사로 순서 변경(본문 앞부분 광고문구 오염 방지 —
  WoodMac 니켈 보고서가 LI로 오분류되던 문제).
- `llm/rule.py`: `RuleExtractor.extract()`가 문서당 `commodity_hint` 1개만 쓰던 것을, 사건유형
  매치 국지창(±120자)에서 광종을 직접 탐지하도록 재작성(`_COUNTRY`와 동일 패턴) — 다광종 문서
  (조달청·Argus·IEA·광업요람)의 0건 추출·오염 태깅 문제 해소.
- `config/sources.yaml`: `EU_SCRREEN: 1.1` 신뢰도 등록.
- 재검증(동일 10건): ingest archived 6→10, unclassified 4→0. extract 이벤트 7건(2문서)→11건(7문서).
  WoodMac 4건 LI→NI 정정 확인. 조달청·IEA에서 최초로 CU 이벤트 추출 확인.
- **미착수(다음 단계 후보)**: 887개 조달청 전체 등 2016+ 전체 코퍼스 재투입은 샘플 검증 이후로 보류 —
  대량 재처리 전 사용자 확인 필요.
- **추가 발견(같은 날, 재실행 육안검수 중)**: `llm/rule.py` RULES의 `war`/`quota`가 단어경계 없이
  매칭 → 시황보고서 상투어 `warehouse`(88회, 실제 war 3회)·`quotations`가 오탐되어 허위 "분쟁"/"정책"
  이벤트 생성. `\bwar\b`/`\bcoup\b`/`\bquota\b`로 수정(한글 키워드는 `\b`가 무공백 복합어를 깨뜨릴 수
  있어 미변경). 재검증: 오탐 소멸, 동일 문서의 진짜 "trade war" 매치는 정상 유지.
- **룰기반 vs LLM 실측 비교**(사내 vLLM gemma-4-26b-a4b, `localhost:52302`, 가동 확인): 동일 9개 문서
  기준 룰=14건, LLM=29건. IEA 문서에서 룰기반은 DRC 코발트 4개월 수출중단(2025-02)을 통째로 놓쳤으나
  LLM은 포착 — `sources.yaml`의 `CO:DR Congo 1.7` 가중치가 정조준하는 시나리오라 임팩트 큼. 원인:
  `RULES`가 문서당 패턴 1매치만 채택(break)+방향(direction)이 키워드에 고정매핑(관세 인하도
  `supply_down`)+8종 고정 사건유형 밖은 아예 매치 불가. **부수 발견·수정**: 로컬 vLLM json_object
  강제모드가 배열을 `{"type":"text","text":"[...]"}`로 이중 인코딩 반환 → `jsonutil.as_event_list()`가
  못 풀고 이벤트 전부 유실되던 버그 수정(문자열 값 재귀 재파싱). 상세: 데이터수집현황 문서 §8.
  **프로덕션 provider 전환은 사용자 승인 대기 — 아직 미실행.**
- **날짜미상 695건 재처리**(`geo/date_resolve.py` 신설 + `classify.py` 신규 필명패턴 4종 추가 —
  연도전용/한글년월/계간지회차/"YYYY-DD-DD-Mon"): 695건 중 692건 해결(3건만 미해결), 2016+ 427건
  신규 투입. ingest archived 427/427(실패 0), OCR 실제 발동 2건(광업요람 2021·2024편) — 마침내 OCR
  경로 실증. 2021편은 서술형 문단 OCR 정확도가 높아 CO/DR Congo 분쟁광물 이벤트를 정확히 포착,
  2024편은 표 위주라 노이즈 대부분(가독 18%)이었으나 허위 이벤트 없이 안전하게 0건 종료. 누적
  이벤트 6,510건. `ManifestRecord`에 `pub_date_method` 필드 추가(감사용). 상세: 데이터수집현황
  문서 §10.
- **잔여이슈 3건 마무리**: (1) `date_resolve.py`에 xls(OLE)/xlsx(OOXML)/hwp(OLE) 메타데이터 폴백
  추가 — 날짜미상 최종 3건 중 2건(수급망지수.xls·CM_Data_Explorer.xlsx) 해결(작성일 메타데이터로
  2016+ 확인, 신규 투입 완료), 1건(LME Seminar hwp)은 메타데이터 전무+본문상 2008년 문서 확인돼
  범위 밖으로 정리. (2) `indexer.py`에 반복보도 dedup 추가 — 같은 광종·같은 달·같은 근거문구(앞
  40자)는 최고 severity 1건만 지수에 반영(원본 이벤트는 무손실 유지). 실측: 6,510건 중 87건(1.3%,
  DRC 코발트 수출중단 위주)이 중복합산되고 있었음, 수정 후 재계산 검증(2,087행 정상 산출). (3) 광종별
  무작위 8건×5광종=40건 층화표본 육안검증 — commodity/country 태깅 40/40 정확, severity가 정보값에
  비례(저정보 항목은 severity 0으로 자동 감쇠). 상세: 데이터수집현황 문서 §11.
- **2016+ 전체 코퍼스(2,385건) 실투입**(승인 후 실행): opendataloader-pdf 배치+OCR폴백(easyocr,
  CPU) 구현, `config/models.yaml` provider를 로컬 vLLM(gemma-4-26b-a4b)으로 전환, `extract.py`에
  `ThreadPoolExecutor` 동시요청(concurrency=8) 추가. 결과: ingest archived 2,367/2,385(failed 5건은
  전부 xlrd/openpyxl 미설치, 텍스트실패 아님), PDF 1,805건 텍스트확보 100%(opendataloader 97.9%+
  pypdf_fallback 2.1%, OCR 0%), 이벤트추출 1건이상 성공 1,890/2,355(80.3%), 총 이벤트 6,039건.
  실행 중 opendataloader 부분실패를 청크 전체 실패로 오판해 불필요한 OCR 폭주(CPU 212분→재발 407분)
  버그 발견·수정(파일단위 `.md` 존재판정 + OCR보다 pypdf 우선). 결과물은 `geo_data_2016plus_run/`에
  보존. 상세: 데이터수집현황 문서 §9.

## 2026-07-06 — 지정학 지수 1차: 비정형 수집기 이식(komis→komir)

과업지시서·착수보고 재검토 감사(`documens/claude_output/진단예측모델_요구사항대조_코드감사_260706.md`)에서
①진단모델 필수변수 ⑥지정학적리스크가 `mart_weekly_diagnosis`에 항상 NULL(연결 코드 없음), ②예측모델은
지정학 피처가 아예 0건임을 확인. 별도 구현체 `komis/`의 자동 수집기(GDELT·Google News RSS)가 실데이터
319건을 이미 확보하고 있어, 이를 komir `geo/` 파이프라인에 이식해 지수 볼륨을 늘리는 1차 작업 착수.

- **`geo/collectors/` 신설**: `gnews.py`(Google News RSS, 분기 단위)·`gdelt.py`(GDELT DOC API, 주 단위) —
  komis 원본 로직 이식. **komis 자체의 event_intensity/감성 점수는 가져오지 않음** — 원문(제목+URL+날짜)만
  `geo_data/inbox/{gnews,gdelt}/`에 텍스트로 투척해 기존 `[1]ingest→[2]extract`(LLM/rule)가 severity를
  산출하도록 함(소스 간 점수체계 일원화). `collectors/_common.py`에 URL해시 기반 중복 발행 방지(같은 사건이
  GDELT·GNews 양쪽에서 잡혀도 1건만 남김) 공용화.
- **`extractors.py`**: `.txt` 포맷 지원 추가(뉴스 원문 투척에 필요, 기존엔 pdf/hwp/xlsx만 지원).
- **`classify.py`**: `source_of()`에 `gdelt`/`gnews` 경로 감지 → `GDELT`/`GoogleNews` 소스 태깅.
- **`config/sources.yaml`**: `GDELT: 0.7`, `GoogleNews: 0.6` 신뢰도 등록(큐레이션된 업계보고서 대비 낮게 —
  뉴스취합이 물량으로 지수를 왜곡하지 않도록).
- **`__main__.py`**: `collect-news`/`collect-gdelt` 서브커맨드 추가(`geo all`에는 미포함 — 외부 API 호출이라
  명시적 실행 권장).
- **검증**: 오프라인 스모크 테스트로 텍스트투척→`ingest`(분류: source/category/commodity_hint 정상)→
  `extract --provider rule`(GeoEvent 생성: commodity/severity/country 정상) end-to-end 확인.
- **komis에서 의도적으로 가져오지 않은 것**: IEA 공급집중표(supply.py, 정적데이터라 ⑤production_hhi·
  refdata 쪽에 붙여야 함) · yfinance 프록시가격 · UN Comtrade(komir가 이미 더 나은 1차 소스 보유).
- **남은 것(2차)**: `geo_index`(또는 `geo_event` 월간 집계)를 `mart_weekly_diagnosis`(①)·`forecast.py`(②)에
  실제로 join하는 코드는 아직 없음 — 지수 "생성"과 모델 "활용" 사이 연결이 이번 1차의 범위 밖.

## 2026-07-02 ~ 07-05 — 파이프라인 구축·모델 가동·품질 강화 (1차 스프린트)

### 1. 인프라·환경
- 도커 통합 오케스트레이션 검증: `msr:dev`(정형·모델) + `geo:dev`(지정학) 빌드, 공유 `warehouse/minerals.duckdb`.
- `.env` 구성: 관세청·ECOS 키, **사내 vLLM gemma**(`gemma-4-26b-a4b`, host 52302) LLM 설정.
  - ⚠️ 교훈: `.env` 값 뒤 인라인 주석이 compose에서 **값으로 새어** LLM 인증헤더 오염(latin-1 오류) — 주석은 별도 줄로.
- git 원격 SSH 전환(`jhkang-illunex/komir`), 이후 전 커밋 push 완료.

### 2. 데이터 수집 (실데이터)
- 관세청 연간(2013~25, 2,093콜) + ECOS: `raw_customs_annual` 232,001행 · `raw_ecos` 257행.
- 관세청 월간: **일 한도(≈10,000콜) 실측 확인** → 전 기간(21,252콜) 불가, 최근 3년(2023~25, 5,796콜)으로 결정.
  host cron 자동 실행(자정 리셋 후)으로 `raw_customs_monthly` **61,291행** 수집 성공. 상세: msr README §4-B.

### 3. 스키마 통합·피처 (`9741497`)
- 정본 스키마 = `db/schema_core.sql`(warehouse) 확정.
- **raw→fact 정규화** 신설(`msr/features/normalize.py`, `make normalize`): `fact_trade_monthly` 5,408 · `fact_trade_annual` 1,946 · `agg_trade_annual` 65(광종·연도 HHI/YoY/CAGR3).
- features·forecast를 fact 계층 단일 소스로 전환(결과 무손실 검증).

### 4. 모델 3종 가동
- **수입 예측**(`eed898b`): `forecast.run()` — 월간 패널→lag/계절 피처→백테스트+12개월 재귀예측(80% 구간).
  `out_import_forecast` 120행. 실데이터 백테스트 **R² volume 0.897 / value 0.866**.
- **진단**(`6c55d9c`): `weekly_mart.py`(fact_price/indicator→`mart_weekly_diagnosis`) + `diagnosis.run()`.
  ⚠️ 실 가격·수급동향지표 부재 → **합성 데모**(`gen_synth.py`, src='SYNTH')로 e2e 검증(HistGBM R²~0.9, 위기 AUC~0.97).
- **경보 4단계**(`9e0983e`, DR13 해소): `geo_event` 계약 신설(geo publish가 이벤트 상세도 warehouse 발행) +
  `alert.run()` — 분위수 기본단계 + 오버라이드(변동성·HHI·지정학 sev/3 정규화) + 히스테리시스 + **법정 문안 사유·이벤트 인용** → `out_diagnosis_alert`.
  오버라이드 실증: NI 위기지수 27/100에도 인니 수출금지(sev 3)로 '경계' 격상.

### 5. 지정학(geo)·OKF
- geo 파이프라인 gemma로 실증(`0add376` 등): 문서 업로드→ingest→extract→index→**OKF 자동**(`geo all` 통합) + `make geo-watch`(inbox 감시 자동 실행).
- **OKF**(Open Knowledge Format, Google v0.1) 익스포트(`5ae20d9`): 정본 비파괴, `geo_data/okf/`에 metric/source/event/issue/index 마크다운+프론트매터 번들.
- **지수 공식 교체**(`514e1a1`): min-max(히스토리 재척도 결함) → **`index = 50+50·tanh(raw/scale_k)`** 절대 스케일.
  50=중립, 발행값 영구 불변(1월만 vs 전체 계산 동일 실증), 광종 간 비교 가능.

### 6. 코드 리뷰 4차 — 발견 22건 전부 수정
- 1차 수집·전처리(`3e2a01a`): serviceKey 로그 마스킹, 429/한도 `QuotaExceeded` 즉시 중단, **HS 단위 증분 적재**, ECOS 에러봉투 표면화.
- 2차 스키마·레거시(`fcce3d9`): 깨진 스키마 경로, legacy 명시(komis_files·구 geo_pipeline), hs_mapping BOM 견고화.
- 3차 심층(`4955e5a`, `1798fb3`): upsert 원자화+컬럼명 INSERT, YoY/CAGR 연도 기반, HHI 총0→NaN, 연간 월행 집계,
  diagnosis import 부작용 제거·함수화, 하드코딩 경로 제거.
- 4차 멀티에이전트(HIGH `514e1a1` / MEDIUM `0f49471` / LOW `d9b2203`):
  지수 안정화, ingest 파일당 manifest(유실 방지), extract_log(0건 문서 무한 재추출 차단), LLM 재시도/rf 폴백,
  월간 그레인 축 통일(q_year/q_month), forecast 월간 그리드, JSON 절단 복구, 날짜 파싱 달력 검증,
  OKF stale 정리, publish DDL 보존(PK 복원), normalize PK 잠복 충돌, spread ASOF, ManifestRecord 계약 강제,
  빈 텍스트 문서 분리, utcnow 정리 등. **보류 2건**: DR7(marts SQL — 데이터 없어 검증 불가), 동시 ingest 락(저위험).

### 7. 문서화 (`335f339`)
- README 3종 동기화: 구현 상태 표(실데이터/합성 구분), 지수 공식, 강건성, 사용법.

## 남은 과제 (다음 스프린트, 2026-07-12 갱신)

1. **관세청 월간 백필 완료 후속**(~07-14 자동): normalize 재실행 → `forecast_unit` 재학습
   (표본 36→156개월) → crontab 정리. [메모리: customs-monthly-backfill]
2. **경보 v1 §7-4 완전체**: 단계 = max(점수단계, 계열1, 계열2) 3계열 병렬 구조 + dimension
   백필(이벤트 650만건 event_type→ops/trade/corridor/input 규칙 매핑) 기반 계열2(시설·수송)
   트리거. 현재는 alert_rule_v1(분위수+고신뢰 소스 오버라이드).
3. **변수④(세계 공급부족) 배선**: woodmac_series.parquet(CU·NI 수급밸런스)→연간 팩트→마트
   ASOF. CO/LI/REE는 IEA/USGS 보완([E]).
4. **USGS refdata 과거 백필**: 수집 서버에서 `geo refdata`(ScienceBase) 실행 → 번들 반입 →
   production_hhi 2016~23 채움 + geo 지수 conc 가중 연도별화.
5. **확률모델 LI·CO 개선**: burst 예측 열세 — 가격·재고 공변량(§3 보조변수) 추가 후 재적합.
6. **운영 배포**: 수집 서버에 collector 도커(daily) 기동, 분석 서버(폐쇄망) 이미지 반입 +
   일일 체인(ingest-bundles→…→publish_results) cron 구성.
7. **발주처 블로킹 8건**(v1 §12): B 학습라벨·C 필수변수·KOMIS 비정형 원천 등 — 회의 안건.
8. 대시보드 운영화: 현재 스냅샷 임베드 → 일일 재생성 스크립트화(+KOMIS 연계는 산출물 ③ 본계약).
