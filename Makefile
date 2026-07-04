.PHONY: init build schema collect monthly normalize synth features train geo refdata geo-publish all clean

init:            ## 폴더 생성 + .env 준비
	mkdir -p geo_data/inbox warehouse
	[ -f .env ] || cp .env.example .env
	@echo "→ dev/.env 에 키 입력 후 'make build'"

build:           ## 이미지 빌드 (msr:dev, geo:dev)
	docker compose build

schema:          ## DDL 적용
	docker compose run --rm schema

collect:         ## 관세청(연간)+ECOS+피처
	docker compose run --rm collect

monthly:         ## 월간 수입 수집(예측용)
	docker compose run --rm collect-customs-monthly

normalize:       ## raw→fact 정규화(fact_trade_* + agg_trade_annual)
	docker compose run --rm normalize

synth:           ## (데모) 합성 가격·지표 → fact_price/indicator (진단모델 검증용)
	docker compose run --rm synth

features:        ## 피처 마트
	docker compose run --rm features

geo:             ## 지정학: ingest→extract→index
	docker compose run --rm geo

refdata:         ## USGS HHI 2016~최근
	docker compose run --rm geo-refdata

geo-publish:     ## 지정학 지수 → 공유 DuckDB
	docker compose run --rm geo-publish

train:           ## 모델 학습(3 템플릿 훅)
	docker compose run --rm train

all: init build schema collect geo geo-publish train  ## 전체 파이프라인

clean:           ## 산출물 정리(원본 보존)
	rm -f warehouse/*.duckdb warehouse/*.duckdb.wal
