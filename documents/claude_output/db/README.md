# 핵심광물 데이터 → DuckDB 적재 (1차: 스키마 + 로더)

보유 원천 데이터를 **canonical(정규화) 스키마**로 DuckDB에 적재하는 첫 단계 산출물.
두 모델(진단=주간, 예측=월간)이 공유하는 단일 원천 계층이다.

## 구성
- `00_schema.sql` — canonical 스키마 DDL (차원 3 + 사실 6)
- `load_to_duckdb.py` — 보유 파일 → DuckDB 적재 스크립트
- `README.md` — 본 문서

## 설치 & 실행
```bash
pip install duckdb pandas openpyxl

python load_to_duckdb.py \
  --data-root "C:/Users/jhkan/Documents/cowork/광해광업" \
  --db "minerals.duckdb"
```
- `--data-root` : 원천 데이터 최상위 폴더 (하위 재귀 탐색)
- `--db`        : 생성할 DuckDB 파일 경로
- `--schema`    : (선택) 00_schema.sql 경로, 기본은 스크립트와 같은 폴더

## 스키마 (long/tidy)
| 테이블 | 내용 | 주기 |
|---|---|---|
| `dim_commodity` | 5대 핵심광물 사전 (CU/NI/LI/CO/REE) | - |
| `dim_commodity_map` | 원천 표기명 → 표준코드 매핑 | - |
| `dim_series` | 거시·지수·환율 시계열 메타 | - |
| `fact_price` | LME Cash/3M·기준가·연월평균 (통합 long) | W/M/Y |
| `fact_inventory` | LME 재고량 | W |
| `fact_trade` | 관세청 수출입 (연·국가·HS) | Y |
| `fact_production_reserve` | USGS 생산·매장량 (국가별 long) | Y |
| `fact_indicator` | KOMIS 수급동향/시장동향 지표 + 가격 | M |
| `fact_series` | BDI·원자재지수·환율·美금융·中수요 | W/M/Q |

## 적재 완료 결과 (minerals.duckdb 실제 생성 완료 ✅)
| 테이블 | 행수 | 비고 |
|---|---|---|
| fact_price | 62,308 | 공급망 Cash/3M 56,212 + 주간 기준가 6,096 |
| fact_inventory | 6,090 | 주간 LME 재고 |
| fact_production_reserve | 2,256 | USGS 생산 1,504 / 매장 752 |
| fact_indicator | 11,088 | 수급동향 2,772 / 시장동향 2,772 / 가격 5,544 |
| fact_series | 6,569 | 15개 시리즈 (BDI·환율·中 월/분기 포함) |
| fact_trade | 105,194 | 관세청 2013~2025 전 행 (HS기준 광종코드 부여) |
| dim_hs_commodity | 542 | HS→광종 권위 매핑 (core5 167) |

> **`minerals.duckdb` (약 7MB) 생성 완료.** 5대 핵심광물 교역행: CU 19,317 / NI 6,066 / CO 2,007 / REE 1,369 / LI 1,080.
> 검증: 동 Cash<3M(정상 콘탱고), 리튬 수급동향(2026-05=41.1), USGS 매장량 톤값, 중국 월/분기 정상.

### 바로 쓰기 (Python)
```python
import duckdb
con = duckdb.connect("minerals.duckdb", read_only=True)
con.execute("SELECT * FROM fact_indicator WHERE commodity_code='LI'").df()
```

## 타 DB 이관 (DuckDB → 상용 DB)
```sql
-- (A) PostgreSQL 직접 적재
INSTALL postgres; LOAD postgres;
ATTACH 'host=... dbname=... user=... password=...' AS pg (TYPE postgres);
CREATE TABLE pg.fact_price AS SELECT * FROM fact_price;   -- 테이블별 반복

-- (B) 범용: CSV/Parquet로 내보내 어디서나 적재 (Oracle 등)
EXPORT DATABASE 'export_dir' (FORMAT PARQUET);   -- 전체 덤프
COPY fact_price TO 'fact_price.csv' (FORMAT CSV, HEADER);
--  Oracle: External Table 또는 SQL*Loader로 CSV 적재
--  MySQL : LOAD DATA INFILE
```
운영 DB 이관 시 DDL은 타깃 방언으로 치환 (00_schema.sql 주석의 타입 매핑표 참조).

## 알려진 한계 / 다음 단계
- `광물종합지수.xlsx`(COMPOSITE)는 헤더 구조가 달라 미적재 — 필요 시 별도 파서 추가.
- 광종 매핑은 표기명 기반(5종)이며, **관세청 HS코드→광종 정밀 매핑은 별도 검증 과업**(`HS코드분류_최종.xlsx` 활용). 현재 `commodity_code`가 NULL인 교역행은 매핑 확장 대상.
- 다음 단계: ① HS매핑 검증·확장 → ② 주간/월간 feature mart 뷰 생성 → ③ 모델별 피처 가공.
