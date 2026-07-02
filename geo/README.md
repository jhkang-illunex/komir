# geo — 비정형 문서 기반 지정학 위기 지수 파이프라인

3계층(입력·정리 / 추출 / 지수), LLM provider 무관, Docker 독립 실행.
설계 상세: `claude_output/지정학지수_시스템_설계_260702.md`.

## 로컬 실행
```bash
pip install -r requirements.txt
export GEO_DATA=./geo_data           # 상태 저장 루트(볼륨)
mkdir -p $GEO_DATA/inbox             # 여기에 pdf/hwp/xlsx 투척

python -m geo refdata --from 2016 --to 2026   # (선택) USGS 공급집중 HHI 자동수집(오픈망 필요)
python -m geo ingest                 # [1] inbox→archive + manifest
python -m geo extract --provider rule   # [2] 이벤트 추출(키 없이 rule/mock)
python -m geo index                  # [3] 지수 + wiki 생성
```
- 실제 LLM: `export LLM_PROVIDER=openai_compat LLM_BASE_URL=... LLM_MODEL=... LLM_API_KEY=...` 후 `python -m geo extract`
- 키 없이 파이프라인 점검: `python -m geo extract --provider mock`

## Docker
```bash
docker build -t geo:0.1.0 .
docker run --rm -v /host/geo_data:/data --env-file .env \
  --add-host=host.docker.internal:host-gateway geo:0.1.0 ingest
docker run --rm -v /host/geo_data:/data --env-file .env geo:0.1.0 extract
docker run --rm -v /host/geo_data:/data --env-file .env geo:0.1.0 index
# 또는: docker compose run --rm ingest / extract / index
```
- 로컬 LLM(Ollama/vLLM)은 `LLM_BASE_URL=http://host.docker.internal:PORT/v1`
- 비밀키는 `.env`/secret으로만, 이미지에 굽지 말 것.

## 산출물 (GEO_DATA 아래)
- `store/manifest.parquet` · `store/geo_events.parquet` · `store/geo_index.parquet`
- `archive/<발행처>/<카테고리>/<YYYY>/<MM>/` (원본 + `.txt`)
- `wiki/<광종>/<YYYY>/<MM>.md` (이슈파일, provenance)

## 계약(확정 대상)
- `geo/schema.py` : `GeoEvent`([2]↔[3]), `ManifestRecord`([1]→[2])
- `config/index.yaml` : 지수 공식 파라미터
- `config/sources.yaml` : 발행처 신뢰도·공급집중 가중
