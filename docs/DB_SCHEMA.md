# minerals.duckdb 스키마 정의서

> 정본 원칙: 이 문서는 `warehouse/minerals.duckdb`(로컬 전용, git 미추적 — `.gitignore`의
> `warehouse/` 규칙)를 **직접 introspection**(`PRAGMA table_info` + `count(*)`)해서 작성했다.
> 행수·컬럼·타입은 **2026-07-22 기준 실측값**이며, DB가 갱신되면 이 문서도 갱신이 필요하다
> (재현: 아래 "갱신 방법" 참고). `mineral_supply_risk/db/schema_core.sql`·
> `mineral_supply_risk/data/raw/{00_schema,geo_schema}.sql`은 **구현 이전 설계 초안**(DDL
> 드래프트)이라 실제 라이브 스키마와 컬럼명·존재 테이블이 다른 경우가 있음 — 실제 상태는
> 이 문서를 신뢰할 것.

## 갱신 방법

```bash
cd komir
python3 -c "
import duckdb
con = duckdb.connect('warehouse/minerals.duckdb', read_only=True)
for t in con.execute(\"select table_name from information_schema.tables where table_schema='main' order by 1\").df()['table_name']:
    print(t, con.execute(f'select count(*) from \"{t}\"').fetchone()[0])
    print(con.execute(f'PRAGMA table_info(\"{t}\")').df()[['name','type','pk']].to_string(index=False))
"
```

## 테이블 목록 개요 (32개, 2026-07-22 실측)

| 계층 | 테이블 | 행수 | 비고 |
|---|---|---|---|
| raw | `raw_customs_annual` | 232,001 | 관세청 연간(HS10×국가) |
| raw | `raw_customs_annual_bycountry` | 39,962 | 관세청 연간, 국가 차원 보존판(2026-07-15 결함 교정 후) |
| raw | `raw_customs_monthly` | 232,001 | 관세청 월간(HS10×국가) |
| raw | `raw_ecos` | 257 | 한국은행 ECOS 거시지표 |
| fact | `fact_trade_annual` | 1,946 | 관세청 연간 → 광종 매핑본 |
| fact | `fact_trade_monthly` | 21,955 | 관세청 월간 → 광종 매핑본 |
| fact | `fact_price` | 6,839 | LME 등 가격(주간/월간) |
| fact | `fact_price_synth_backup` | 4,830 | 가격 결측 구간 합성 보간본(백업, 운영 미사용 추정) |
| fact | `fact_indicator` | 385 | 기타 지표(관세청 외) |
| fact | `fact_indicator_synth_backup` | 370 | 위 합성 보간 백업 |
| fact | `fact_inventory` | 0 | **미사용**(스키마만 존재, 재고 데이터 미수집) |
| fact | `fact_production_reserve` | 207 | USGS 생산·매장량 |
| fact | `fact_series` | 0 | **미사용**(범용 시계열 슬롯, 미적재) |
| fact | `fact_diagnosis_answer` | 2,497 | 진단모델 정답 라벨(KOMIS 등급 기반) |
| agg/feat | `agg_production_hhi` | 10 | 광종×연도 생산 HHI |
| agg/feat | `agg_trade_annual` | 65 | 광종×연도 수입 HHI·YoY·CAGR3 |
| agg/feat | `feat_import_growth` | 15 | 수입 증감률 피처 |
| agg/feat | `feat_import_hhi` | 15 | 수입 HHI 피처 |
| dim | `dim_hs_commodity` | 0 | **미사용**(HS10→광종 매핑은 코드 상수로 대체 운영 추정) |
| dim | `doc_chunk` | 0 | **미사용**(문서 청크 슬롯, 미적재) |
| geo | `geo_event` | 295,157 | 지정학 이벤트(LLM/규칙 추출, GKG 관련성 정제 후) |
| geo | `geo_index` | 3,526 | 지정학 위기지수(주/월/연) |
| geo | `geo_prob` | 2,745 | 위기지수 확률화(NB2, 다음주 발생·급증 확률) |
| mart | `mart_weekly_diagnosis` | 4,601 | 진단모델 입력 마트(주간) |
| mart | `mart_diagnosis_nowcast` | 390 | 진단 nowcast 산출(단계·확률·기여도) |
| mart | `mart_monthly_forecast_input` | 360 | 예측모델 입력 마트(월간) |
| mart | `mart_proxy_label` | 1,139 | 수요예측용 프록시 라벨(변동성 스파이크 등) |
| mart | `mart_forecast_method_log` | 1 | 예측 방법(재귀/Direct) 자동선택 로그 |
| out | `out_diagnosis_alert` | 1,632 | **발행: 4단계 경보**(risk_score·alert_level) |
| out | `out_import_forecast` | 120 | **발행: 수입 예측**(물량/단가, horizon별) |
| out | `out_import_forecast_unit` | 60 | **발행: 수입 예측**(단가 분리·환산 상세) |
| out | `out_report` | 0 | **미사용**(리포트 생성 슬롯, 미적재) |

**미사용 테이블(5개, 0행)**: `fact_inventory`·`fact_series`·`dim_hs_commodity`·`doc_chunk`·
`out_report` — 전부 `mineral_supply_risk/db/schema_core.sql` 등 초기 설계 DDL에서 만들어진
슬롯으로, 실제 파이프라인이 아직 채우지 않고 있다. 삭제하지 않고 남겨둔 이유는 확인 필요
(향후 확장 예약일 수도, 단순 미정리일 수도 있음).

## 테이블 상세

### raw_customs_annual (관세청 연간, HS10×국가)
PK: 없음(명시 PK 미설정)
| 컬럼 | 타입 |
|---|---|
| year | BIGINT |
| month | VARCHAR |
| hscode | VARCHAR |
| country | VARCHAR |
| exp_usd | BIGINT |
| exp_wgt | BIGINT |
| imp_usd | BIGINT |
| imp_wgt | BIGINT |
| balance | VARCHAR |
| hs_query | VARCHAR |
| q_year | VARCHAR |
| q_month | VARCHAR |
| commodity_code | VARCHAR |

### raw_customs_annual_bycountry (관세청 연간, 국가 차원 보존판)
2026-07-15 발견된 "country←statKor 오매핑" 결함 교정 후 국가 차원을 제대로 보존한 버전
(build_kr_import_share.py 등이 참조). PK: 없음.
| 컬럼 | 타입 |
|---|---|
| year | BIGINT |
| hscode | VARCHAR |
| country | VARCHAR |
| hs_query | VARCHAR |
| q_year | VARCHAR |
| country_cd | VARCHAR |
| item_kor | VARCHAR |
| exp_usd | BIGINT |
| exp_wgt | BIGINT |
| imp_usd | BIGINT |
| imp_wgt | BIGINT |
| commodity_code | VARCHAR |

### raw_customs_monthly (관세청 월간, HS10×국가)
PK: 없음.
| 컬럼 | 타입 |
|---|---|
| year | BIGINT |
| month | BIGINT |
| hscode | VARCHAR |
| country | VARCHAR |
| exp_usd | BIGINT |
| exp_wgt | BIGINT |
| imp_usd | BIGINT |
| imp_wgt | BIGINT |
| balance | VARCHAR |
| hs_query | VARCHAR |
| q_year | VARCHAR |
| q_month | VARCHAR |
| commodity_code | VARCHAR |

### raw_ecos (한국은행 ECOS)
PK: (series_name, period)
| 컬럼 | 타입 |
|---|---|
| series_name | VARCHAR NOT NULL, PK |
| period | VARCHAR NOT NULL, PK |
| val | DECIMAL(20,4) |

### fact_trade_annual / fact_trade_monthly (관세청 → 광종 매핑본)
PK: (yr[,mon], hs10, country)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| yr | INTEGER NOT NULL, PK | |
| mon | INTEGER NOT NULL, PK | monthly만 |
| hs10 | VARCHAR NOT NULL, PK | |
| commodity_code | VARCHAR | |
| country | VARCHAR NOT NULL, PK | |
| imp_usd/imp_wgt/exp_usd/exp_wgt | DECIMAL(20,3) | |
| src | VARCHAR | |
| loaded_at | TIMESTAMP | |

### fact_price / fact_price_synth_backup (가격)
PK(fact_price): (commodity_code, price_type, obs_date)
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR NOT NULL, PK |
| price_type | VARCHAR NOT NULL, PK |
| freq | VARCHAR NOT NULL |
| obs_date | DATE NOT NULL, PK |
| val | DECIMAL(20,4) |
| unit | VARCHAR |
| src | VARCHAR |

### fact_indicator / fact_indicator_synth_backup
PK(fact_indicator): (commodity_code, indicator, obs_date)
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR NOT NULL, PK |
| indicator | VARCHAR NOT NULL, PK |
| freq | VARCHAR |
| obs_date | DATE NOT NULL, PK |
| val | DECIMAL(20,4) |
| src | VARCHAR |

### fact_inventory (미사용, 0행)
PK: (commodity_code, obs_date) — 컬럼: val DECIMAL(20,3), unit, src.

### fact_production_reserve (USGS 생산·매장량)
PK: 없음.
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR |
| country | VARCHAR |
| year | BIGINT |
| metric | VARCHAR |
| val | DOUBLE |
| src | VARCHAR |

### fact_series (미사용, 0행)
PK: (series_code, obs_date) — 컬럼: val DECIMAL(24,6), unit, src.

### fact_diagnosis_answer (진단모델 정답 라벨)
PK: (commodity_code, indicator, obs_date)
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR NOT NULL, PK |
| indicator | VARCHAR NOT NULL, PK |
| freq | VARCHAR |
| obs_date | DATE NOT NULL, PK |
| grade | VARCHAR |
| grade_ord | INTEGER |
| price | DECIMAL(20,4) |
| series_label | VARCHAR |
| src | VARCHAR |
| deviation_rate | DECIMAL(20,6) |

### agg_production_hhi / agg_trade_annual / feat_import_growth / feat_import_hhi
집계·피처 레이어(광종×연도). PK 없음. 공통 컬럼: `commodity_code`(VARCHAR), `year`(BIGINT).
- `agg_production_hhi`: production_hhi, reserve_hhi(DOUBLE), avail_date(DATE)
- `agg_trade_annual`: import_value_usd/import_weight_kg(DECIMAL(38,3)), import_hhi/
  import_yoy/import_cagr3(DOUBLE), avail_date(DATE)
- `feat_import_growth`: imp_usd(BIGINT), import_yoy/import_cagr3(DOUBLE)
- `feat_import_hhi`: import_hhi(DOUBLE)

### dim_hs_commodity (미사용, 0행)
PK: hs10(VARCHAR) — 컬럼: commodity_code, commodity_ko, is_core5(BOOLEAN).

### doc_chunk (미사용, 0행)
PK: chunk_id(VARCHAR) — 컬럼: doc_id, commodity_code, src, pub_date(DATE), seq(INTEGER), txt.

### geo_event (지정학 이벤트, 지수화 파이프라인의 원자료)
PK: 없음(event_id가 사실상 유니크지만 미선언). GKG 관련성 정제 후 295,157건(2026-07-20~21,
관련성 99.5%). `geo/schema.py::GeoEvent`가 파이썬 측 정본 스키마.
| 컬럼 | 타입 | 비고 |
|---|---|---|
| event_id | VARCHAR | |
| doc_id | VARCHAR | |
| commodity_code | VARCHAR | CU/NI/CO/LI/REE |
| obs_date | VARCHAR | 문자열 저장(날짜 아님 — 발행 계약) |
| country | VARCHAR | |
| event_type | VARCHAR | 정책/뉴스/재해 등 |
| direction | VARCHAR | supply_up/down·price_up/down·demand_up/down·neutral(7종) |
| target | VARCHAR | |
| severity | DOUBLE | 0~3 |
| confidence | DOUBLE | LLM 자체보고 확신도, 0~1(실측 0.1~1.0, 평균0.70, 상수 아님) |
| evidence_quote | VARCHAR | |
| source | VARCHAR | 발행처(신뢰도 가중 키) |
| provider | VARCHAR | 수집 경로(gkg/openai_compat 등) |
| extractor | VARCHAR | rule/llm |
| published_at | VARCHAR | |
| dimension | VARCHAR | |

### geo_index (지정학 위기지수)
PK: (commodity_code, freq, period)
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR NOT NULL, PK |
| freq | VARCHAR NOT NULL, PK — 'W'/'M'/'Y' |
| period | DATE NOT NULL, PK |
| raw_score | DECIMAL(20,6) |
| n_events | INTEGER |
| idx_value | DECIMAL(9,3) — tanh0_100(0~100, 50=중립) |
| index_config_version | VARCHAR |
| generated_at | TIMESTAMP |

### geo_prob (지정학 위기지수 확률화, NB2)
PK: 없음(commodity_code, period가 사실상 유니크).
| 컬럼 | 타입 | 비고 |
|---|---|---|
| commodity_code | VARCHAR | |
| period | VARCHAR | |
| lambda_next | DOUBLE | 다음 주 예상 심각이벤트 강도 |
| p_severe_next | DOUBLE | 다음 주 심각이벤트 발생확률 |
| burst_threshold | BIGINT | 급증 판정 임계(주간 건수, P90) |
| p_burst_next | DOUBLE | 다음 주 급증확률 |
| family | VARCHAR | 확률모형군(nb2 등) |
| alpha_disp | DOUBLE | NB2 산포모수 α |
| p_burst_cal | DOUBLE | isotonic 보정 후 급증확률 |
| generated_at | VARCHAR | |

### mart_weekly_diagnosis (진단모델 입력 마트, 주간)
PK: 없음(commodity_code, obs_date가 사실상 유니크).
| 컬럼 | 타입 | 비고 |
|---|---|---|
| commodity_code | VARCHAR | |
| obs_date | DATE | Monday 앵커 |
| yr | BIGINT | |
| ref_price | DECIMAL(20,4) | |
| logret | DOUBLE | |
| volatility_12w | DOUBLE | |
| spread_pct | DOUBLE | CO/LI/REE 100% 결측(2026-07-16 확인된 데이터공백) |
| import_hhi | DOUBLE | 국가 기준(2026-07-15 교정 후) |
| import_yoy | DOUBLE | |
| import_cagr3 | DOUBLE | |
| production_hhi | DOUBLE | |
| geopolitical_risk | DOUBLE | geo_index 유래 |
| geo_macro | DOUBLE | |
| teacher_supply_demand | DECIMAL(20,4) | |

### mart_diagnosis_nowcast (진단 nowcast 산출)
PK: 없음.
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR |
| month | DATE |
| ci_pred | DOUBLE |
| ci_teacher | DOUBLE |
| stage_pred | BIGINT |
| stage_name | VARCHAR |
| stage_probs | VARCHAR (JSON 문자열) |
| contrib | VARCHAR (JSON 문자열) |
| base_level | DOUBLE |
| generated_at | VARCHAR |

### mart_monthly_forecast_input (예측모델 입력 마트, 월간)
PK: (commodity_code, target, obs_date)
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR NOT NULL, PK |
| target | VARCHAR NOT NULL, PK |
| obs_date | DATE NOT NULL, PK |
| y_val | DECIMAL(20,4) |
| feat_json | VARCHAR (JSON 문자열) |

### mart_proxy_label (수요예측용 프록시 라벨)
PK: 없음.
| 컬럼 | 타입 |
|---|---|
| month | TIMESTAMP |
| commodity_code | VARCHAR |
| ton | DOUBLE |
| imp_dev | DOUBLE |
| import_drop | BIGINT |
| vol90 | DOUBLE |
| vol_thr | DOUBLE |
| vol_spike | BIGINT |
| bad_event | BIGINT |
| proxy_bad_next3m | DOUBLE |

### mart_forecast_method_log (예측 방법 자동선택 로그)
PK: 없음. 1행(최신 실행만 보관 추정).
| 컬럼 | 타입 |
|---|---|
| base_month | DATE |
| mase_recursive | DOUBLE |
| mase_direct | DOUBLE |
| gap | DOUBLE |
| method_selected | VARCHAR |
| method_naive | VARCHAR |
| margin_threshold | DOUBLE |
| generated_at | TIMESTAMP WITH TIME ZONE |

### out_diagnosis_alert (발행: 4단계 경보) ★대시보드/보고서 직접 참조
PK: (commodity_code, obs_date)
| 컬럼 | 타입 |
|---|---|
| commodity_code | VARCHAR NOT NULL, PK |
| obs_date | DATE NOT NULL, PK |
| risk_score | DECIMAL(9,4) |
| risk_proba | DECIMAL(9,6) |
| alert_level | VARCHAR — 정상/관심/주의/심각 |
| reason | VARCHAR |
| model_version | VARCHAR |
| generated_at | TIMESTAMP |
| evidence_json | VARCHAR (JSON 문자열) |

### out_import_forecast / out_import_forecast_unit (발행: 수입 예측) ★대시보드/보고서 직접 참조
PK(out_import_forecast): (commodity_code, target, base_date, horizon)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| commodity_code | VARCHAR NOT NULL, PK | |
| target | VARCHAR NOT NULL, PK | 물량/금액 |
| base_date | DATE NOT NULL, PK | |
| horizon | INTEGER NOT NULL, PK | 개월 |
| yhat/yhat_lo/yhat_hi | DECIMAL(20,4) | |
| model_version | VARCHAR | |
| generated_at | TIMESTAMP | |

`out_import_forecast_unit`(PK 없음): target_month·h·ton_lo/hi·unit_lo/hi·pred_ton·
pred_unit_usd_per_ton·pred_value_usd·pred_value_lo/hi·pred_value_kusd·base_month·
model_version·basis·generated_at — 물량/단가 분리 예측의 상세 분해판.

### out_report (미사용, 0행)
PK: report_id(VARCHAR) — 컬럼: commodity_code, period, kind, title, body, generated_at.
