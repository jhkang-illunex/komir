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

# 스케줄(운영: crontab)
#   0 6 * * 1  python -m scripts.schedule weekly     # 주간 진단
#   0 7 1 * *  python -m scripts.schedule monthly    # 월간 예측
```

## 4. 데이터 소스·검증 상태
| 소스 | 모듈 | 상태 |
|---|---|---|
| 한국은행 ECOS(GDP·산업생산) | ecos_api | ✅ **키·스키마·실수집 검증**(전산업생산지수 901Y033 월간) |
| 관세청 품목별국가별 수출입 | customs_api | 코드·파라미터 정합(엔드포인트/HS/월간). *개발샌드박스 아웃바운드 차단으로 로컬 실행 필요* |
| USGS / 제공 xlsx·csv | komis_files | 기존 검증 로더 통합 |
| 지정학 보고서 | geo_pipeline | 기존 파이프라인 통합(규칙+LLM) |

> ⚠️ 참고: 본 개발 환경에서는 외부 아웃바운드가 제한되어 **ECOS만 원격 검증**되었고, **관세청은 사내/로컬 네트워크에서 실행**하면 동작합니다(코드·키 준비 완료). 실수집 증빙 샘플: `outputs/_ecos_sample_전산업생산지수_2025.csv`.

## 5. 운영 DB 이관
`msr/storage/db.py`의 `export_parquet()`로 전 테이블을 Parquet로 내보내 Postgres/Oracle 등 납품 DB로 이관(스키마는 설계단계 ERD 확정 후).

## 6. 보안
- `.env`는 `.gitignore`로 제외. 키를 리포지토리·로그에 남기지 말 것.
- 상용 LLM API 사용 시 데이터 외부반출 정책(공단 보안) 확인 필요.
