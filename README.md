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
make geo                  # ingest→extract→index
make geo-publish          # 지정학 지수 → 공유 DuckDB

# 모델
make train                # 3 템플릿 학습(현재 훅)

make all                  # init→build→schema→collect→geo→geo-publish→train
```

## 산출 확인
```bash
python -c "import duckdb;c=duckdb.connect('warehouse/minerals.duckdb',read_only=True);\
print([t[0] for t in c.execute('select table_name from information_schema.tables').fetchall()])"
```
정형 팩트·마트 + `geo_index` + 모델 결과(`out_*`)가 한 DB에 모인다.

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
