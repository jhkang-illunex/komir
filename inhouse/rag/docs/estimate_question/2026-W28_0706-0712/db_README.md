---
source: documents/산출물/2026-W28_0706-0712/db/README.md
week: 2026-W28
title: 핵심광물 데이터 → DuckDB 적재 (1차: 스키마 + 로더)
---

# 예상 질문

## 목적 / 구성
- 이 1차 산출물의 구성 파일 3개는 무엇인가?
- canonical 스키마는 차원 테이블 몇 개, 사실 테이블 몇 개로 구성되는가?
- 진단모델과 예측모델은 각각 어떤 주기(주간/월간)를 쓰며 왜 단일 원천 계층을 공유하는가?

## 실행 방법
- `load_to_duckdb.py` 실행 시 `--data-root`, `--db`, `--schema` 인자는 각각 무엇을 지정하는가?
- 설치에 필요한 파이썬 패키지 3종은 무엇인가?

## 스키마
- `dim_commodity`, `dim_commodity_map`, `dim_series`는 각각 무엇을 담는 차원 테이블인가?
- `fact_price`, `fact_inventory`, `fact_trade`, `fact_production_reserve`, `fact_indicator`, `fact_series`의 내용과 주기(W/M/Y 등)는 각각 무엇인가?
- `fact_series`에는 어떤 계열들이 들어가는가?

## 적재 결과(수치)
- fact_price 62,308행은 어떤 두 종류로 구성되는가?
- fact_indicator 11,088행의 내역(수급동향/시장동향/가격)은 어떻게 나뉘는가?
- fact_production_reserve의 생산·매장 행수는 각각 얼마인가?
- fact_trade는 몇 년치 관세청 데이터이며 총 행수는?
- 5대 핵심광물별 교역행 수(CU/NI/CO/REE/LI)는 각각 얼마인가?
- 생성된 `minerals.duckdb`의 대략적인 용량은?

## 검증
- 적재 후 어떤 항목들로 값 타당성을 검증했는가(동 Cash<3M, 리튬 수급동향 등)?
- 리튬 수급동향 2026-05 값은 얼마로 확인되었는가?

## 운영 DB 이관
- DuckDB에서 PostgreSQL로 직접 적재하는 방법은 어떤 확장을 쓰는가?
- Oracle·MySQL 등 범용 이관 시 권장 경로는 무엇인가?

## 한계 / 다음 단계
- `광물종합지수.xlsx`(COMPOSITE)가 미적재된 이유는?
- 현재 `commodity_code`가 NULL인 교역행은 어떻게 처리할 계획인가?
- 다음 단계 3가지는 무엇인가?
