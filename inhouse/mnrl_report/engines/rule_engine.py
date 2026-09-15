"""규칙 엔진 — facts를 양식 문장(RULE 정책 컬럼)으로 바꾸는 결정론 컴포넌트.

규칙 본체는 `rules/mnrl.py`(광종별)·`rules/overall.py`(전체)·`rules/fmt.py`(서식)에
있고, 정책은 `policy.py`, 임계·등급명은 `config.py`에 있다. 이 다섯 파일이 엔진
버전 해시의 입력이다 — 문장 문구·임계값·서식 규칙이 하나라도 바뀌면 버전이 바뀐다.
"""
from __future__ import annotations

from pathlib import Path

from ..config import ReportConfig
from ..policy import POLICIES, RULE
from ..rules import mnrl as rule_mnrl
from ..rules import overall as rule_overall
from .base import Engine, EngineResult, EngineVersion, compute_version

_PKG = Path(__file__).resolve().parents[1]
RULE_FILES = [
    _PKG / "rules" / "fmt.py", _PKG / "rules" / "mnrl.py", _PKG / "rules" / "overall.py",
    _PKG / "policy.py", _PKG / "config.py",
]


class RuleEngine(Engine):
    engine_cd = "rule"
    engine_type = "RULE"

    def __init__(self, cfg: ReportConfig):
        self.cfg = cfg
        self._version = compute_version(self.engine_cd, RULE_FILES)

    @property
    def version(self) -> EngineVersion:
        return self._version

    def generate(self, table: str, ctx: dict) -> EngineResult:
        base, facts = ctx["base"], ctx["facts"]
        if table == "ai_rpt_mnrl":
            row = rule_mnrl.build(ctx["code"], facts, base, self.cfg)
        elif table == "ai_rpt_overall":
            row = rule_overall.build(facts, base, self.cfg)
            if facts.get("gscpi"):
                row["gscpi_val"] = facts["gscpi"]["val"]  # 실값이 있을 때만(현재 더미라 대개 없음)
        else:
            raise ValueError(table)
        allowed = {c for c, k in POLICIES[table].items() if k == RULE}
        # gscpi_val은 MANUAL 정책이지만 실값 원천이 생기면 RULE로 전환 예정 — 지금은 정책 밖이라 제외
        columns = {c: v for c, v in row.items() if c in allowed}
        evidence = {k: facts[k] for k in ("price", "diag", "customs", "production", "reserve", "overall", "gscpi")
                    if k in facts and facts[k] is not None}
        return EngineResult(table=table, columns=columns, evidence=evidence)
