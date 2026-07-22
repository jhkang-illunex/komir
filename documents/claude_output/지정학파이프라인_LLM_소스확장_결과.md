# 지정학 파이프라인 — LLM 추출기 연결 + 소스 확장 결과

> 이전 POC(규칙기반·리튬 단일)에서 ① **LLM 추출기 연결**, ② **소스 확장**(Argus·IEA) 완료.
> KOMIS HWP는 변환 경로만 제공(사유 하단).

## 1. LLM 추출기 연결

- `geo_pipeline.py`에 **Anthropic 어댑터** 추가: `make_anthropic_caller(model)` → `analyze --llm` 로 운영 실행.
  ```bash
  export ANTHROPIC_API_KEY=...
  python geo_pipeline.py --db minerals.duckdb analyze --llm --model claude-sonnet-4-6
  ```
- 추출 품질 비교 (동일 코퍼스):

| 추출기 | 이벤트 수 | 특성 |
|---|---|---|
| baseline(규칙) | 108 | regulation/subsidy 과탐(노이즈 많음) |
| **llm(정밀)** | **12** | 국가·광종·근거 정확, 노이즈 제거 |

- 집계뷰 `fact_geopolitical_weekly`는 **운영 기준 `extractor='llm'`**로 전환(baseline은 비교용 보존).

## 2. 소스 확장 (doc_raw 29건)

| 소스 | 형식 | 건수 | 기간 | 비고 |
|---|---|---|---|---|
| AsianMetal(리튬) | PDF | 18 | 2026-01~06 | 주간 |
| **Argus(비철 일간)** | PDF | 8 | 2026-01~06 | 다광종(동·니켈·코발트) |
| **IEA(연간)** | PDF | 3 | 2023~2025 | 구조적 지정학 |
| KOMIS(HWP) | - | - | - | 한컴 변환 필요(미수행) |

## 3. 다광종 지정학 이벤트 (LLM 추출, 실제 근거)

| 광종 | 국가 | 유형 | severity | 근거(출처) |
|---|---|---|---|---|
| **코발트** | DRC | 수출중단 | 0.92 | "DRC announced four-month suspension of cobalt exports" (IEA 2025) |
| **희토류** | China | 수출통제 | 0.90 | "series of export controls on key materials" (IEA 2025) |
| 코발트 | DRC | 수출규제 | 0.85 | "Co rally to persist on DRC curbs" (Argus 2026-01) |
| **리튬** | Zimbabwe | 수출쿼터 | 0.85 | "export quota for lithium concentrate from Zimbabwe" |
| 리튬 | China | 수출통제 | 0.82 | "China adds 20 Japanese entities to export control" |
| 희토류 | Myanmar | 분쟁 | 0.70 | "ongoing military conflict in Myanmar" (Argus 2026-05) |
| **니켈** | Indonesia | 정책비용 | 0.65 | "Indonesia HPAL Ni ore costs rise by 50pc" (Argus 2026-04) |
| 니켈 | Indonesia | 공급집중 | 0.55 | "Indonesia for nickel" 정제 집중 (IEA 2025) |

→ 이전 LI 단일 → **코발트·니켈·리튬·희토류 4종 커버리지 확보**. (동은 이번 Argus 샘플에 명확한 단일 이벤트 적어 추가 수집 필요)

## 4. 진단 mart 연결

`mart_weekly_diagnosis.geopolitical_risk`(변수⑥) 채워진 주간행: **CO 2 · NI 2 · LI 17**.
(REE는 주간가격 부재로 주간 mart에 미포함 → REE는 월간 패널에서 결합 예정)

## 5. KOMIS HWP 관련 (미수행 사유)
- KOMIS 보고서는 **HWP 5.0 바이너리(OLE)**. 샌드박스 LibreOffice엔 HWP 임포트 필터가 없어 변환 실패.
- 보유하신 **한컴 HWP MCP(Windows)** 의 `hwp_export_pdf`로 일괄 PDF 변환 후 동일 파이프라인 투입 가능.
- 변환만 되면 `ingest --source KOMIS --commodity ...` 로 즉시 처리.

## 6. 다음 단계
- 실제 LLM 키로 `analyze --llm` 전량 재실행(전 소스·전 단락) → 커버리지·정밀도 동시 확대
- Argus 전량(113건/년) + 연도확장, 동(Cu) 전용 이벤트 보강
- KOMIS HWP 한컴 변환분 추가 → 국내 관점 반영
