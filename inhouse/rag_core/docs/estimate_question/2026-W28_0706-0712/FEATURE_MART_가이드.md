---
source: documents/산출물/2026-W28_0706-0712/db/FEATURE_MART_가이드.md
week: 2026-W28
title: Feature Mart 가이드 (모델별 학습 패널)
---

# 예상 질문

## 테이블 구성 / 규모
- `build_feature_marts.py`가 생성하는 테이블 4개는 무엇이며 각각의 행수는?
- `mart_weekly_diagnosis`와 `mart_annual_forecast`는 각각 어느 모델(진단/예측)을 위한 패널인가?
- `agg_trade_annual`과 `agg_production_annual`은 각각 무엇을 집계하는가?
- feature mart 생성 명령어는 무엇인가?

## 과업 6변수 ↔ 컬럼 매핑
- 과업 변수 ①시장변동성~⑥지정학에 대응하는 컬럼명은 각각 무엇인가?
- `volatility_12w`는 어떻게 계산되며 비결측률은 얼마인가?
- `spread_pct`의 계산식은 무엇이고 왜 CU·NI만 존재하는가(비결측률 58.8%)?
- `import_hhi`의 값 범위(스케일)는 어떻게 되는가?
- `production_hhi`의 비결측률이 7.9%에 불과한 이유는?
- `supply_shortage`와 `geopolitical_risk`의 비결측률이 0%인 이유는 각각 무엇인가?

## 교사신호 / 학습 구간
- `teacher_supply_demand`는 어떤 지표이며 어떤 주기 변환(월간→주간)을 거치는가?
- 교사신호 비결측률이 전체로는 34.7%인데 2020년 이후는 100%인 이유는?
- 학습 권장 구간을 2020년 이후로 잡는 근거는 무엇인가?

## 누수 방지 설계
- 연간 변수(②③⑤)를 "익년부터 가용"으로 가정해 ASOF 결합하는 이유는?
- 2026년 주간행은 어떤 값으로 채워지는가?

## 알려진 한계
- REE(희토류)가 주간 mart에서 제외된 이유는 무엇이며 대안은?
- 예측모델이 과업 요구인 "월간·12개월" 타깃을 만족하지 못하는 이유는?
- 현재 `mart_annual_forecast`의 타깃 컬럼명은 무엇인가?
- 월간 수입통계를 확보하면 어떤 확장이 가능한가?

## 사용법
- 진단모델 학습셋을 뽑는 예시 SQL의 필터 조건 두 가지는 무엇인가?
