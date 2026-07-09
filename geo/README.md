# geo — 비정형 문서 기반 지정학 위기 지수 파이프라인

3계층(입력·정리 / 추출 / 지수), LLM provider 무관, Docker 독립 실행.
설계 상세: `claude_output/지정학지수_시스템_설계_260702.md`.

## 로컬 실행
```bash
pip install -r requirements.txt
export GEO_DATA=./geo_data           # 상태 저장 루트(볼륨)
mkdir -p $GEO_DATA/inbox             # 여기에 pdf/hwp/xlsx 투척

python -m geo refdata --from 2016 --to 2026   # (선택) USGS 공급집중 HHI 자동수집(오픈망 필요)

# (선택) [0] 자동 수집 → inbox 투척 (komis 이식, API키 불필요)
python -m geo collect-news  --days 90         # Google News RSS
python -m geo collect-gdelt --days 90         # GDELT DOC API(주 단위, rate-limit 15초/req)

python -m geo ingest                 # [1] inbox→archive + manifest
python -m geo extract --provider rule   # [2] 이벤트 추출(키 없이 rule/mock)
python -m geo index                  # [3] 지수 + wiki 생성 (freq=W/M 둘 다 산출)
```
- 실제 LLM: `export LLM_PROVIDER=openai_compat LLM_BASE_URL=... LLM_MODEL=... LLM_API_KEY=...` 후 `python -m geo extract`
- 키 없이 파이프라인 점검: `python -m geo extract --provider mock`

### GKG 벌크(2016~) — 역사적 지수 구축 전용 경로
`collect-gdelt`(DOC API)는 실측상 2016년 근처 결과가 희박해(과거 지원이 약함) 역사적 백필용으로는
GDELT GKG 2.0 벌크 원본(2015-02~, 15분 단위)을 쓴다. `[1]ingest`를 거치지 않고 별도 3단계로 처리:
```bash
# (사전) 벌크 다운로드 — 별도 경로(대용량, NAS 등 권장). 5워커 연도단위 배정, 재개가능.
python -m geo.collectors.gkg_bulk_download --worker 0 --workers 5 --dest /path/to/bulk/gdelt &
...(worker 1~4 반복)

python -m geo gkg-parse  --bulk-root /path/to/bulk/gdelt --year-from 2016   # 규칙기반 후보 추출
python -m geo gkg-verify --bulk-root /path/to/bulk/gdelt --limit 500        # 실제 LLM 재검증(선택)
python -m geo index                                                        # 위와 동일하게 지수 반영
```
- `gkg-parse`: `WB_2934_COPPER`/`WB_2935_NICKEL` 전용 테마코드(오프셋 근접성 검증) + 코발트·리튬·
  희토류(Nd 우선)는 키워드+2차 신호어 동반출현 게이트. `extractor="rule", provider="gkg"`로 저장.
- `gkg-verify`: GKG는 본문이 없어 규칙만으로는 정밀도 한계가 있음(실측: REE 표본 오탐률 100%) —
  후보를 URL·국가·1차판정으로 구성한 passage로 실제 LLM에 재확인시켜, 확정되면 `extractor="llm"`로
  교체하고 기각되면 store에서 제거한다. `LLM_PROVIDER=openai_compat`(Ollama 등) 또는 `anthropic` 필요
  (rule/mock 지정 시 재검증 의미 없어 실행 거부).

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
- `store/manifest.parquet` · `store/geo_events.parquet` · `store/geo_index.parquet` · `store/extract_log.parquet`(추출 시도 이력)
- `archive/<발행처>/<카테고리>/<YYYY>/<MM>/` (원본 + `.txt`)
- `wiki/<광종>/<YYYY>/<MM>.md` (이슈파일, provenance)
- publish 시 공유 DB로: **`geo_index`**(지수) + **`geo_event`**(이벤트 상세 — 경보모델 오버라이드·사유 인용용)

## 지수 공식 (tanh 절대 스케일)
`index = 50 + 50·tanh(raw_score / scale_k)` — raw = Σ severity(0~3)×발행처신뢰도×공급집중×방향부호.
- **50=중립**(이벤트 없음), ~88=심각(raw≈scale_k, 기본 10). 0~50은 호재(공급확대 등).
- **절대 스케일**: 새 기간이 추가돼도 과거 발행값이 재척도되지 않음(광종 간 비교 가능).
- 이벤트 0건인 공백 기간은 발행하지 않음. 파라미터는 `config/index.yaml`.

## 강건성 (운영 방어)
- ingest: **파일당 manifest 즉시 기록**(크래시 시 이동-미기록 유실 방지), 빈 텍스트(스캔 PDF)는 `empty`로 분리, parquet 원자 쓰기.
- extract: 시도 이력(`extract_log`)으로 0건 문서 재추출 방지, LLM 실패는 다음 실행 재시도, severity/confidence 자동 clamp.
- LLM 클라이언트: 429/5xx/타임아웃 지수 백오프 재시도, `response_format` 미지원 서버(400) 자동 폴백.
- JSON 복구: 코드펜스·트레일링콤마·max_tokens 절단 방어.

## OKF(Open Knowledge Format) 익스포트 — 비파괴 파일럿
```bash
python -m geo all              # ingest→extract→index→OKF 자동 연동(파일 업로드 처리 전 과정)
python -m geo okf-export       # (단독) 정본(parquet) → geo_data/okf/ 번들만 재생성
```
> **파일 업로드 자동 연동**: `geo_data/inbox`에 pdf/hwp/xlsx를 넣고 `make geo`(=`geo all`)를 돌리면
> ingest→extract→index→**OKF 번들 생성**까지 한 번에 이어진다. `make geo-publish`로 warehouse `geo_index`까지.
> 업로드를 감시해 자동 실행: **`make geo-watch`**(inbox 폴링→감지 시 파이프라인+publish 자동 실행).
- 정본(parquet/DuckDB)은 **그대로 두고**, 지식 계층만 Google Cloud OKF v0.1(마크다운+프론트매터, 개념ID=파일경로)로 방출.
- 매핑: `metrics/geo-index`(지수 공식) · `sources/<발행처>/`(원문) · `events/<광종>/`(이벤트) · `issues/<광종>/`(월별 이슈) · `index/<광종>/`(지수 시계열).
- `GeoEvent`(schema.py) 필드가 그대로 프론트매터, 근거인용→본문 `# Citations`. GitHub 렌더·git diff·에이전트 컨텍스트로 사용.
- ⚠️ v0.1(신규 스펙)이라 **부가 export 레이어**로 운용(정본 대체 아님).

## 계약(확정 대상)
- `geo/schema.py` : `GeoEvent`([2]↔[3]), `ManifestRecord`([1]→[2])
- `config/index.yaml` : 지수 공식 파라미터
- `config/sources.yaml` : 발행처 신뢰도·공급집중 가중
