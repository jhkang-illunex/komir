"""mnrl_report — 통합보고서(핵심광물 수급위기 진단결과 보고서) 주간 생성 모듈.

2026-09-15 신설. `public.ai_rpt_overall`(전체)·`public.ai_rpt_mnrl`(광종별)의
텍스트 섹션을 규칙 엔진으로 채우고, 선택적으로 LLM 문체 단계를 거쳐, 사람이
검수·확정하는 3단계 파이프라인이다. 실행 단위는 보고 주차(base_ymd, 월요일).

패키지 구성(의존 방향: run → stages → rules/sources → db/config; common만 참조):
- config.py    설정·주차 계산·임계값
- db.py        PG 엔진(public 스키마 읽기/쓰기 — 이 모듈은 public 쓰기가 허용된 유일한 배치)
- policy.py    컬럼별 생성 정책(RULE/LLM/MANUAL/META)과 덮어쓰기 규칙
- sources.py   원장 조회 → facts(dict). 더미 행(ai_dev_dummy_load) 차단
- rules/       facts → 문장(결정론). fmt.py 서식, mnrl.py 광종별, overall.py 전체
- engines/     규칙 엔진(RuleEngine)·생성형 엔진(GenEngine)·버전 등록부(registry) — 각 엔진은
               YYMMDD-sha8 버전을 갖고 행마다 rule_ver/llm_model_ver로 찍힌다
- writer.py    정책을 지키는 upsert(DRAFT만 덮어씀, MANUAL은 비어 있을 때만 시드)
- run.py       CLI / scheduler.py 주간 스케줄
"""
