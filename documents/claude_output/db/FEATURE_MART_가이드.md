# Feature Mart 가이드 (모델별 학습 패널)

`build_feature_marts.py`가 canonical DuckDB 위에 생성하는 모델 입력 테이블.
실행: `python build_feature_marts.py --db minerals.duckdb`

## 생성 테이블
| 테이블 | 용도 | 행수 |
|---|---|---|
| `agg_trade_annual` | 광종·연도 교역집계(수입 HHI/YoY/CAGR3) | 65 |
| `agg_production_annual` | 광종·연도 생산 HHI(USGS) | 10 |
| `mart_weekly_diagnosis` | **[진단모델] 주간 패널** | 3,805 |
| `mart_annual_forecast` | **[예측모델] 연간 수입 패널** | 65 |

## mart_weekly_diagnosis 컬럼 ↔ 과업 6변수
| 컬럼 | 과업변수 | 비결측률 | 비고 |
|---|---|---|---|
| `volatility_12w` | ① 시장변동성 | 99.8% | 주간 로그수익률 12주 표준편차 |
| `spread_pct` | 신규(Cash-3M) | 58.8% | (Cash−3M)/3M×100, CU·NI만 |
| `import_hhi` | ② 수입편중도 | 62.0% | 국가별 수입액 HHI(0~10000) |
| `import_yoy`,`import_cagr3` | ③ 수입증가도 | 58.0% | 연간 YoY / 3년 CAGR |
| `production_hhi` | ⑤ 생산독점도 | 7.9% | USGS 2024~25만 보유 |
| `supply_shortage` | ④ 공급부족 | 0% | **소비량 데이터 미보유(확보 필요)** |
| `geopolitical_risk` | ⑥ 지정학 | 0% | **발주처 제공 예정** |
| `teacher_supply_demand` | 교사신호 | 34.7%(2020년~ **100%**) | KOMIS 수급동향지표(월간→주간 ASOF) |

> 연간 변수(②③⑤)는 **익년부터 가용** 가정으로 ASOF 결합 → 미래정보 누수 방지 + 2026년 주간행도 직전연도값으로 채움.
> KOMIS 지표가 2020-01~ 존재하므로 **학습 권장 구간은 2020년 이후**(교사신호 100%).

## 알려진 한계
1. **희토류(REE)는 주간가격 미보유**로 주간 mart에서 제외됨 → REE 진단은 월간(교사신호·교역·생산) 기반 별도 패널 필요.
2. ④공급부족(소비/공급), ⑥지정학은 데이터 확보 후 동일 구조로 컬럼만 채우면 됨.
3. **예측모델: 관세청 데이터가 연간뿐**이라 과업의 "월간·12개월" 타깃 불가 → 현재는 `mart_annual_forecast`(1년후 수입 `import_value_usd_next`). 월간 수입통계 확보 시 월간 패널로 확장.

## 사용 예
```python
import duckdb
con=duckdb.connect("minerals.duckdb", read_only=True)
# 진단모델 학습셋 (2020년 이후, 교사신호 존재)
df = con.execute("""
  SELECT * FROM mart_weekly_diagnosis
  WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL
""").df()
```
