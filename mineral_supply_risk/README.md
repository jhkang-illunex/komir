# mineral_supply_risk — 핵심광물 수급위기 데이터·모델 파이프라인

수집(스크래핑/API) → 전처리 → 피처 조합 → 학습을 **모듈화**한 Python 프로젝트.
과업 산출물(수급위기 진단모델·수입 예측모델·지정학 분석·경보)의 데이터/모델 백엔드.

## 1. 설치
```bash
pip install -r requirements.txt
cp .env.example .env    # 이미 키가 채워진 .env 포함(커밋 금지)
```
`.env`에 발급키가 들어 있습니다: 관세청(공공데이터포털)·한국은행 ECOS.

## 1-B. 윈도우(Windows) 빠른 시작
> Python 3.10~3.13 설치되어 있으면 됩니다(모든 패키지 Windows 휠 제공). 한컴/GPU 불필요.
```bat
:: 1) 프로젝트 폴더에서
run_windows.bat            :: 가상환경 생성 + 패키지 설치 (최초 1회)

:: 또는 수동으로
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 2) 실행 (인증키는 .env에 이미 설정됨)
python -m scripts.run collect-ecos                    :: 한국 GDP·산업생산 (동작 검증됨)
python -m scripts.run collect-customs 201301 202512   :: 관세청 월간 수입(5광종 167 HS)
python -m scripts.run features                         :: 피처 → data\processed\minerals.duckdb
```
> 윈도우 호환: 모든 경로는 pathlib/os 기반(상대경로), 외부 프로그램(한컴·soffice·tesseract) 의존 없음.

## 2. 구조
```
mineral_supply_risk/
├─ .env / .env.example / .gitignore      # 인증키(커밋금지)
├─ requirements.txt
├─ msr/
│  ├─ config.py                 # 경로·상수(5광종)·키·ECOS코드
│  ├─ collectors/               # ── 수집 ──
│  │  ├─ customs_api.py         #   관세청 품목별국가별 수출입(월간, XML)
│  │  ├─ ecos_api.py            #   한국은행 ECOS(GDP·산업생산, JSON) ✅검증
│  │  ├─ komis_files.py         #   제공 xlsx/csv 로더(가격·교역·USGS·지표)
│  │  └─ geo_pipeline.py        #   지정학 보고서 수집·이벤트 추출(RAG/규칙+LLM)
│  ├─ preprocess/
│  │  └─ hs_mapping.py          #   HS→광종 매핑(검증본 167코드)
│  ├─ features/
│  │  ├─ builders.py            #   HHI·CAGR·YoY·변동성·Cash-3M 스프레드
│  │  └─ marts.py               #   주간 진단 / 연·월 예측 feature mart
│  ├─ models/
│  │  ├─ diagnosis.py           #   진단 GBM+위기분류
│  │  ├─ forecast.py            #   수입 예측(walk-forward)
│  │  ├─ alert.py               #   경보 4단계(자원안보특별법)
│  │  └─ alert_reason.py        #   경보 사유 생성
│  ├─ storage/db.py             #   DuckDB 적재·Parquet 내보내기(운영DB 이관)
│  ├─ utils/hwp_extract.py      #   HWP 텍스트 추출(한컴 불필요)
│  └─ pipeline.py               #   오케스트레이션(collect→features→train)
├─ scripts/
│  ├─ run.py                    #   CLI 진입점
│  └─ schedule.py               #   주간/월간 배치(cron/Airflow 연결점)
└─ data/{raw,interim,processed}/, outputs/
```

## 3. 사용
```bash
# ECOS 통계코드 탐색(정확 코드 확인)
python -m scripts.run ecos-search 생산

# 수집
python -m scripts.run collect-customs 201301 202512   # 관세청 월간 수입(5광종 167 HS)
python -m scripts.run collect-ecos                     # 한국 GDP·산업생산

# 피처 산출 → DuckDB(data/processed/minerals.duckdb)
python -m scripts.run features

# 전체
python -m scripts.run all

# 모델 학습/추론 (out_* 적재)
python -m scripts.train forecast   # 월간 수입 예측(실구현): raw_customs_monthly → out_import_forecast
python -m scripts.train all        # forecast + diagnosis(스캐폴드)

# 스케줄(운영: crontab)
#   0 6 * * 1  python -m scripts.schedule weekly     # 주간 진단
#   0 7 1 * *  python -m scripts.schedule monthly    # 월간 예측
```
> **모델 구현 현황**
> - ✅ **수입 예측**(`msr/models/forecast.py`): 월간 패널→지연/계절 피처→홀드아웃 백테스트(MAE/R²)+12개월 재귀예측. `mart_monthly_forecast_input`·`out_import_forecast` 적재. 타깃 volume(kg)·value($). *실측 검증: 2023~2025 기준 백테스트 R² volume 0.90 / value 0.87.*
> - 🔧 **진단·경보**(`diagnosis.py`/`alert.py`): 로직은 있으나 입력 마트(`mart_weekly_diagnosis`)가 **가격 변동성·지정학 지수·교사신호**를 요구 → 해당 수집·정규화(raw→fact) 확보 후 배선.

## 4. 데이터 소스·검증 상태
| 소스 | 모듈 | 상태 |
|---|---|---|
| 한국은행 ECOS(GDP·산업생산) | ecos_api | ✅ **키·스키마·실수집 검증**(전산업생산지수 901Y033 월간) |
| 관세청 품목별국가별 수출입 | customs_api | ✅ **연간 실수집 검증**(`raw_customs_annual` 232,001행). 월간은 일일 호출 한도 제약 — 아래 참조 |
| USGS / 제공 xlsx·csv | komis_files | 기존 검증 로더 통합 |
| 지정학 보고서 | geo_pipeline | 기존 파이프라인 통합(규칙+LLM) |

> ⚠️ 참고: 본 개발 환경에서는 외부 아웃바운드가 제한되어 **ECOS만 원격 검증**되었고, **관세청은 사내/로컬 네트워크에서 실행**하면 동작합니다(코드·키 준비 완료). 실수집 증빙 샘플: `outputs/_ecos_sample_전산업생산지수_2025.csv`.

### 4-B. ⚠️ 관세청(data.go.kr) 일일 호출 한도 — 월간 수집 제약
관세청 `getNitemtradeList`는 **1콜당 최대 1개 기간창**만 허용하므로, 광종 HS 목록 전체를 조회하면 콜 수가 급증한다.

| 모드 | 콜 수 산식 | 예(HS 161개) | 일 한도(≈10,000) |
|---|---|---|---|
| 연간(`freq=A`) | HS × 연도 | 161 × 13년 = **2,093** | ✅ 하루 완주 |
| 월간(`freq=M`) | HS × 개월 | 161 × 132월(2015~2025) = **21,252** | ❌ **초과 → 완주 불가** |

- **한도 초과 시 증상**: HTTP `429 Too Many Requests`. `fetch_one`이 3회(2·4·6초 백오프) 재시도하지만, 한도 소진 후에는 재시도도 모두 실패 → 해당 `(HS×월)` 레코드 **누락**. 한도는 **자정(KST) 기준 리셋**.
- **부분 수집분은 저장되지 않음**: `customs_api.collect()`는 전체 콜을 메모리에 모은 뒤 **끝까지 성공해야 1회 적재**한다(중간 flush 없음). 도중에 중단하면 그때까지 수집분도 사라진다.
- **권장 운용**:
  1. **기간 축소로 한도 이내 유지** — 예: 최근 3년 `202301~202512` = 161 × 36 = **5,796콜**(하루 완주). 최근 5년 `202101~202512` = 9,660콜(한도 근접).
  2. **운영계정 트래픽 상향** — data.go.kr 활용사례 등록으로 일 한도 상향/무제한(승인 대기 수일). 전 기간 1회 수집의 근본책.
  3. **일 단위 분할 수집** — 하루 10k씩 나눠 수집. 단 현재 `pipeline.collect_customs()`의 `db.upsert_df(..., del_where="1=1")`가 매 실행마다 테이블을 전량 삭제·교체하므로, 분할하려면 **append 또는 기간조건 del_where로 코드 수정 필요**(그렇지 않으면 앞 청크가 사라짐).
- **실측(2026-07-03)**: 월간 `201501~202512` 실행 중 약 10,000콜 지점부터 429가 지속 발생 → 일 한도 소진 확인. 이후 최근 3년(5,796콜) 범위로 재수집하기로 결정.

## 5. 운영 DB 이관
`msr/storage/db.py`의 `export_parquet()`로 전 테이블을 Parquet로 내보내 Postgres/Oracle 등 납품 DB로 이관(스키마는 설계단계 ERD 확정 후).

## 6. 보안
- `.env`는 `.gitignore`로 제외. 키를 리포지토리·로그에 남기지 말 것.
- 상용 LLM API 사용 시 데이터 외부반출 정책(공단 보안) 확인 필요.
