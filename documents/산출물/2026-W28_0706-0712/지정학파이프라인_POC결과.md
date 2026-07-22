# 지정학 리스크 파이프라인 — 구축 및 실데이터 POC 결과

> 보고서 → `doc_raw`(원본) → `geo_event`(분석) 2단 분리 + 수집→분석 파이프라인 구축.
> Asian Metal 리튬 주간 PDF 18건으로 실제 적재·추출까지 완료.

## 1. 산출물 (claude_output/db/)
| 파일 | 내용 |
|---|---|
| `geo_schema.sql` | doc_raw + geo_event 테이블 + `fact_geopolitical_weekly` 뷰 |
| `geo_pipeline.py` | ingest(수집)→parse(섹션태깅)→analyze(이벤트추출) 3단 파이프라인 |
| `minerals.duckdb` | 위 테이블 포함, POC 데이터 적재 완료 |

## 2. 설계 핵심 (논의 반영)
- **원본/분석 2단 분리**: `doc_raw`(발행일·원문·섹션 JSON) ↔ `geo_event`(국가·광종·위험도·근거)
- **BLOB 대신 JSON**: 섹션은 `sections JSON`(쿼리가능), 원본 바이트는 선택적 `raw_blob`만
- **수집/분석 비동기**: status(received→parsed→analyzed→failed)로 단계 관리·재개
- **중복방지·재현성**: `file_hash` UNIQUE 중복차단, `model_version` 태깅으로 재분석 가능
- **추적성**: 모든 이벤트에 `evidence_quote`(근거 인용문) + doc_id 보존
- **시간앵커**: 발행일(pub_date) 기준 → 미래정보 누수 방지

## 3. POC 실행 결과 (Asian Metal 리튬 2026, 18건)
- 수집/파싱/분석: **18문서 전부 analyzed**, 발행일 2026-01-09 ~ 06-12
- 추출 이벤트: **108건**
- 유형: regulation 48, policy_subsidy 36, trade_data 9, **export_restriction 6**, supply_disruption 6, tariff 2, conflict 1
- 국가: China 10, Zimbabwe 2, Argentina/Australia/Indonesia 등

### 실제로 잡아낸 지정학 이벤트 (근거 인용)
- 🔴 `China adds 20 Japanese entities to export control` (2026-02-28, severity 0.85)
- 🔴 `China tightens export controls on dual-use items` (2026-01-09, 0.85)
- 🔴 `export quota for lithium concentrate from Zimbabwe` (2026-04-17, 0.85)
- 🟡 `China publishes implementation regulations for ...` (2026-05-22, 0.5)

### 진단 mart 변수⑥ 연결 (루프 완성)
`fact_geopolitical_weekly`를 `mart_weekly_diagnosis`에 주간 결합 → **LI 17개 주간행의 `geopolitical_risk` 채움**.
이제 한 행에 변동성①·교사신호(수급동향지표)·지정학⑥이 함께 존재.

## 4. 추출기 2종
- **baseline(규칙기반)** — 현재 POC에 사용. API 불필요, 즉시 실행. 국가×이벤트키워드×문장 → 이벤트.
  - 장점: 무비용·재현성. 단점: regulation/subsidy 과탐(노이즈) → 사전 정제 필요.
- **LLM(운영 권장)** — `geo_pipeline.py`의 `llm_extract(sections, hint, call_llm)`에 LLM 호출자 주입.
  - 단락→(국가·광종·severity·direction·confidence·근거) 구조화 JSON. 정밀도↑, 과업의 "비계량 이벤트 계량화"에 부합.

## 5. 다음 단계
1. **LLM 추출기 연결**(API 키 주입) → baseline 노이즈 제거, severity 정밀화
2. **소스 확장**: Argus(일간 동·니켈), IEA(연), 우드맥킨지(분기), KOMIS HWP(한컴 변환)
3. **광종 커버리지**: 코발트·희토류는 다광종 보고서 단락분류로 확보
4. **폴더 watch + 스케줄 배치**로 자동 수집(신규 보고서 입력 시 자동 적재·분석)

> 결론: 제안하신 아키텍처(2테이블 분리 + 수집/분석 파이프라인)가 **실데이터로 검증 완료**. 규칙기반으로도 China 수출통제·Zimbabwe 쿼터 등 실질 지정학 이벤트를 포착했고, LLM 연결 시 정밀도가 더 올라간다.
