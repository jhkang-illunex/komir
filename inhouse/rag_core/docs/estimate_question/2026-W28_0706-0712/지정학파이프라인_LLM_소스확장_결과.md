---
source: documents/산출물/2026-W28_0706-0712/지정학파이프라인_LLM_소스확장_결과.md
week: 2026-W28
title: 지정학 파이프라인 — LLM 추출기 연결 + 소스 확장 결과
---

# 예상 질문

## LLM 추출기 연결
- `geo_pipeline.py`에 추가된 LLM 어댑터 함수명과 실행 명령어는?
- 동일 코퍼스에서 baseline과 llm 추출기의 이벤트 건수는 각각 몇 건인가?
- 이벤트 수가 108건에서 12건으로 줄어든 것을 왜 품질 개선으로 해석하는가?
- 집계뷰 `fact_geopolitical_weekly`는 어떤 extractor를 운영 기준으로 삼게 되었는가?
- baseline 결과는 삭제되었는가, 보존되었는가?

## 소스 확장
- doc_raw 29건은 어떤 소스로 구성되는가(AsianMetal·Argus·IEA·KOMIS)?
- Argus 자료의 주기·건수·기간과 포함 광종은?
- IEA 자료는 몇 건이며 어떤 성격의 지정학 정보를 담는가?
- KOMIS(HWP)가 이번에 포함되지 못한 이유는?

## 추출된 다광종 이벤트
- severity가 가장 높은 이벤트는 무엇이며 값과 출처는?
- DRC 코발트 관련 이벤트 2건의 severity와 근거 인용문은?
- 중국 희토류 수출통제 이벤트의 severity는?
- Zimbabwe 리튬 수출쿼터의 severity는?
- Myanmar 분쟁 이벤트의 광종·severity·출처는?
- 인도네시아 니켈 관련 이벤트 2건(정책비용·공급집중)의 severity와 근거는?
- 커버리지가 LI 단일에서 몇 개 광종으로 늘었으며, 아직 부족한 광종은 무엇인가?

## 진단 mart 연결
- `geopolitical_risk`가 채워진 주간행 수는 광종별로 각각 몇 건인가?
- REE가 주간 mart에 포함되지 못하는 이유와 대안은?

## KOMIS HWP 미수행 사유
- KOMIS 보고서의 파일 포맷은 무엇이며 왜 샌드박스에서 변환에 실패했는가?
- 변환 후에는 어떤 명령으로 파이프라인에 투입할 수 있는가?

## 다음 단계
- 다음 단계 3가지(LLM 전량 재실행·Argus 전량 확장·KOMIS 추가)는 각각 무엇을 노리는가?
- Argus는 연간 몇 건 규모로 확장할 계획인가?
