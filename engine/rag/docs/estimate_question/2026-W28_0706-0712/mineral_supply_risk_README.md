---
source: documents/산출물/2026-W28_0706-0712/mineral_supply_risk/README.md
week: 2026-W28
title: mineral_supply_risk — 핵심광물 수급위기 데이터·모델 파이프라인
---

# 예상 질문

## 프로젝트 개요
- 이 프로젝트가 모듈화한 4단계 흐름은 무엇인가?
- 이 파이프라인이 백엔드로 지원하는 과업 산출물은 무엇인가?
- `.env`에는 어떤 기관의 발급키가 들어 있는가?

## 디렉터리 구조
- `msr/collectors/` 아래 4개 모듈은 각각 어떤 소스를 수집하는가?
- `msr/features/builders.py`가 만드는 피처들은 무엇인가?
- `msr/models/` 아래 4개 모듈(diagnosis·forecast·alert·alert_reason)의 역할은 각각 무엇인가?
- `msr/preprocess/hs_mapping.py`는 몇 개 HS 코드의 검증본을 사용하는가?
- `msr/utils/hwp_extract.py`가 한컴 오피스 없이 하는 일은 무엇인가?
- `msr/storage/db.py`는 어떤 두 가지 기능을 담당하는가?
- 오케스트레이션(collect→features→train)을 담당하는 파일은?

## 실행 / 사용법
- ECOS 통계코드를 탐색하는 명령어는 무엇인가?
- 관세청 월간 수입을 2013-01~2025-12로 수집하는 명령어는?
- 피처 산출 결과 DuckDB 파일은 어느 경로에 생성되는가?
- 운영 crontab에 등록하도록 제시된 주간·월간 배치 스케줄은 각각 언제이며 무엇을 실행하는가?

## 데이터 소스 검증 상태
- 원격 검증까지 완료된 소스는 무엇이며 어떤 통계코드를 확인했는가?
- 관세청 수집기가 본 개발 환경에서 실행되지 못한 이유는?
- 실수집 증빙으로 남긴 샘플 파일 경로는?
- USGS·제공 xlsx·csv, 지정학 보고서는 각각 어떤 모듈로 처리되는가?

## 운영 이관 / 보안
- 운영 DB 이관은 어떤 함수로 어떤 포맷을 내보내는가?
- 보안상 `.env`와 관련해 지켜야 할 원칙은?
- 상용 LLM API 사용 시 확인이 필요한 정책은 무엇인가?
