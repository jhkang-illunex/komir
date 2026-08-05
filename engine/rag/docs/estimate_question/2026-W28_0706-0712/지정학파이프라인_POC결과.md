---
source: documents/산출물/2026-W28_0706-0712/지정학파이프라인_POC결과.md
week: 2026-W28
title: 지정학 리스크 파이프라인 — 구축 및 실데이터 POC 결과
---

# 예상 질문

## 아키텍처 / 산출물
- 보고서에서 지수까지 이어지는 2단 테이블 분리 구조는 무엇인가(`doc_raw` ↔ `geo_event`)?
- `geo_schema.sql`이 정의하는 테이블·뷰는 무엇인가?
- `geo_pipeline.py`의 3단 파이프라인 단계는 각각 무엇을 하는가?

## 설계 원칙
- 섹션 저장에 BLOB 대신 JSON을 택한 이유는?
- status 값 4단계(received→parsed→analyzed→failed)는 무엇을 위한 것인가?
- 중복방지와 재현성은 각각 어떤 컬럼으로 보장되는가?
- 추적성을 위해 모든 이벤트에 무엇을 남기는가?
- 미래정보 누수를 막기 위한 시간앵커는 무엇인가?

## POC 실행 결과
- POC에 사용한 코퍼스는 무엇이며 문서 건수와 발행일 범위는?
- 추출된 이벤트 총 건수는 몇 건인가?
- 이벤트 유형별 분포(regulation·policy_subsidy·trade_data·export_restriction·supply_disruption·tariff·conflict)는?
- 국가별 분포에서 가장 많은 국가와 건수는?
- severity 0.85로 잡힌 이벤트 3건은 각각 무엇인가?

## 모델 연결
- `fact_geopolitical_weekly`를 `mart_weekly_diagnosis`에 결합한 결과 몇 개 주간행의 변수⑥이 채워졌는가?
- 이 결합으로 한 행에 함께 존재하게 된 변수 3가지는 무엇인가?

## 추출기 비교
- baseline(규칙기반) 추출기의 장점과 단점은 각각 무엇인가?
- LLM 추출기는 어떤 인터페이스로 주입되며 어떤 구조화 결과를 내놓는가?
- LLM 추출이 과업지시서의 어떤 요구와 부합하는가?

## 다음 단계
- LLM 추출기 연결로 기대하는 개선 2가지는?
- 소스 확장 대상 4종(Argus·IEA·우드맥킨지·KOMIS)의 주기는 각각 무엇인가?
- 코발트·희토류 커버리지는 어떤 방식으로 확보하려 하는가?
- 자동 수집을 위해 제안한 방식은 무엇인가?
