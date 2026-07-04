# 작업 이력 (WORKLOG)

> 커밋 해시는 `git log --oneline` 기준. 최신이 위.

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

## 남은 과제 (다음 스프린트)
1. **실 데이터 투입** — 진단·경보 실운영 전환의 유일한 블로커:
   - KOMIS xlsx(가격·수급동향지표) 입수 시 `collect-komis` 어댑터 작성(파서는 `komis_files.py`에 있음 — warehouse 계약으로 브릿지 필요) + `SYNTH` 행 삭제 후 재학습.
   - 실 지정학 문서는 `geo_data/inbox`에 넣으면 즉시 자동(파일명에 날짜 필수).
   - USGS(→`production_hhi`)·관세청 전기간(운영계정 트래픽 상향 신청) 병행.
2. 보류 리뷰 2건(DR7·ingest 락)은 canonical 데이터/동시 실행 요구 발생 시 처리.
3. (선택) OKF-정본 승격 실험, geo-watch 상시화(systemd).
