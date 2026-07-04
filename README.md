# dev — 통합 오케스트레이션 (docker compose)

흩어진 파이프라인을 **한 곳에서** 빌드·실행. 코드는 각 패키지(`../mineral_supply_risk`, `../geo`)에 그대로 두고, `dev/`는 서비스·볼륨만 묶는다.

## 구조
```
dev/
├─ docker-compose.yml     # 서비스 정의 (정형 + geo + train)
├─ Makefile               # make 명령
├─ .env(.example)         # 키·provider·DB경로
├─ warehouse/             # ★ 공유 DuckDB (모든 결과 집결) — 바인드 마운트
└─ geo_data/inbox/        # 비정형 문서 투척 — 바인드 마운트
```
두 이미지: `msr:dev`(정형·모델, context=../mineral_supply_risk), `geo:dev`(지정학, context=../geo).
공유 저장: `warehouse/minerals.duckdb` (컨테이너 `/warehouse`).

## 빠른 시작
```bash
cd dev
make init                 # geo_data/·warehouse/ 생성 + .env 준비
#  → dev/.env 에 관세청·ECOS·LLM 키 입력
make build                # msr:dev, geo:dev 빌드
make schema               # DDL 적용(공유 DuckDB)

# 정형
make collect              # 관세청(연간)+ECOS → normalize(raw→fact) → 피처
make monthly              # (예측용) 월간 수입 수집
make normalize            # raw_customs_* → fact_trade_* + agg_trade_annual (정본 팩트)
make refdata              # USGS HHI 2016~최근

# 비정형 지정학  (geo_data/inbox 에 pdf·hwp·xlsx 투척 후)
make geo                  # ingest→extract(LLM)→index→OKF 번들 (한 번에)
make geo-publish          # 지정학 지수(geo_index) + 이벤트 상세(geo_event) → 공유 DuckDB
make geo-watch            # inbox 감시 → 업로드 시 위 과정 자동 실행
make geo-okf              # (단독) OKF 마크다운 번들만 재생성 (geo_data/okf/)

# 모델 (train all = 진단 → 경보 → 예측)
make synth                # (데모) 실 가격·지표 없을 때 합성 fact_price/indicator 생성
make train                # 진단(HistGBM)·경보4단계(법정문안 사유)·수입예측(12개월) → out_*

make all                  # init→build→schema→collect→geo→geo-publish→train
```

## 산출 확인
```bash
python -c "import duckdb;c=duckdb.connect('warehouse/minerals.duckdb',read_only=True);\
print([t[0] for t in c.execute('select table_name from information_schema.tables').fetchall()])"
```
정형 팩트·마트 + `geo_index`/`geo_event` + 모델 결과(`out_*`)가 한 DB에 모인다.

## 구현 상태 (2026-07 기준)
| 산출물 | 테이블 | 상태 |
|---|---|---|
| 관세청 수집(연간+월간 2023~25)·ECOS | `raw_customs_*`, `raw_ecos` | ✅ 실데이터 (일 한도 ≈10k콜 유의) |
| raw→fact 정규화·교역 집계 | `fact_trade_*`, `agg_trade_annual` | ✅ (`make normalize`) |
| 수입 예측(백테스트+12개월) | `out_import_forecast` | ✅ 실데이터 (R² ~0.9) |
| 지정학 지수·이벤트 (gemma vLLM 추출) | `geo_index`, `geo_event` | ✅ tanh 절대스케일(50=중립, 발행값 불변) |
| OKF 지식번들 (마크다운+프론트매터) | `geo_data/okf/` | ✅ 파이프라인 자동 생성 |
| 진단 모델 (HistGBM) | outputs/model | 🟡 배선 완료 — **합성 데모**(실 가격·수급동향지표 필요) |
| 경보 4단계 (+법정문안 사유·지정학 격상) | `out_diagnosis_alert` | 🟡 배선 완료 — 위기지수는 합성, 지정학 오버라이드는 실추출 이벤트 |

실운영 전환에 남은 것: **실 데이터 소스 투입**(KOMIS/LME 가격·수급동향지표·USGS·실 지정학 문서). 스키마·배선은 완료 — 동일 fact 테이블(`fact_price`·`fact_indicator`)에 넣으면 코드 수정 없이 흐른다.

## 서버DB로 전환 (운영)
`.env`의 경로를 SQLAlchemy URL로 바꾸면 동일 코드가 Oracle/MariaDB/MSSQL로 나간다.
```
MSR_DB=mariadb+pymysql://user:pw@host:3306/mineral
GEO_PUBLISH_DB=oracle+oracledb://user:pw@host:1521/?service_name=ORCL
```
(서버DB는 이미지에 sqlalchemy+드라이버 포함/추가 필요.)

## 주의
- 서비스는 일회성(`run --rm`). 자동화는 호스트 cron으로 `make collect`/`make geo` 등 호출.
- **관세청 API 일일 호출 한도(≈10,000콜)**: `make monthly`(월간 전체 21,252콜)는 하루에 완주 불가 → 429. 기간 축소(예 최근 3년 ≈5,796콜)·운영계정 상향·일 분할 중 택. 상세: `mineral_supply_risk/README.md` §4-B.
- DuckDB는 단일 파일 → 동시 쓰기 금지(순차 실행). 서버DB면 동시성 해결.
- 로컬 LLM(Ollama/vLLM): `LLM_BASE_URL=http://host.docker.internal:PORT/v1`.
- 비밀키는 `.env`(커밋 금지). 원본 데이터·`data/`는 이미지에서 제외(.dockerignore).
