"""엔진 계층 — 파이프라인(run.py)이 호출하는 두 종류의 생성 엔진.

- RuleEngine(engines/rule_engine.py): 결정론. facts → RULE 정책 컬럼.
- GenEngine (engines/gen_engine.py): 생성형(LLM). RULE 결과·근거 → LLM 정책 컬럼.

두 엔진 모두 `Engine` 인터페이스(engines/base.py)를 따르고, 버전은
`YYMMDD-sha8`(엔진을 구성하는 소스·프롬프트 파일의 내용 해시)로 자동 계산된다.
버전과 실행 이력은 `public.ai_rpt_engine_ver`·`public.ai_rpt_gen_run`에 기록한다
(engines/registry.py).
"""
from .base import Engine, EngineResult, EngineVersion
from .gen_engine import GenEngine
from .rule_engine import RuleEngine

__all__ = ["Engine", "EngineResult", "EngineVersion", "GenEngine", "RuleEngine"]
