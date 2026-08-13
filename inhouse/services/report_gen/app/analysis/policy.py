# -*- coding: utf-8 -*-
"""페이지별 등급판정·분석문 정책 로딩 — 외부 저장소
`komis_report_generator/analysis/policy.py` 이식본(2026-08-13).

**원본에서 바뀐 것은 리소스 로딩 경로 하나뿐**이다: 원본은
`importlib.resources.files("komis_report_generator.analysis.resources.policies")`로
설치된 패키지 리소스를 읽는다. komir의 `services/report_gen/app`은 설치형 패키지가
아니라 컨테이너에 그대로 COPY되는 소스트리라(`data_sources/_shared.py`의
SNAPSHOT_PATH와 같은 사정) `Path(__file__).parent` 기준 상대경로로 읽는다.

**정책 YAML은 2종뿐이다**(원본도 동일): `indicator_market`·`indicator_supply`만
등급 밴드(grade_rules)를 가진 YAML 정책을 쓴다. 나머지 3종(광물종합지수·광물지도·
가격예측)은 등급 개념이 없어 YAML이 아니라 `additional_summary.py`의
`ADDITIONAL_PAGE_CONTEXTS`(SummaryPageContext dataclass)로 정의된다 — 이식 지시서에
"5종 YAML을 다 가져오라"고 적혀 있었으나 외부repo에 그런 파일은 없다(2026-08-13 실측).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from .models import GradeResult, PageId, StrictModel

#: 등급 밴드 YAML이 사는 곳(설치형 패키지 리소스가 아니라 소스트리 상대경로).
_POLICY_DIR = Path(__file__).resolve().parent / "resources" / "policies"


class PolicyError(RuntimeError):
    """정책 파일이 없거나 내부적으로 모순될 때."""


class GradeRule(StrictModel):
    """등급 1개의 점수구간과 (선택) 위기발생 조건."""

    label: str
    min_score: float
    max_score: float
    include_min: bool = True
    include_max: bool = True
    requires_crisis: bool | None = None

    def matches(self, score: float, crisis_flag: bool | None) -> bool:
        """점수·위기상태가 이 규칙을 만족하는지."""

        if self.requires_crisis is not None and crisis_flag is not self.requires_crisis:
            return False
        lower = score >= self.min_score if self.include_min else score > self.min_score
        upper = score <= self.max_score if self.include_max else score < self.max_score
        return lower and upper


class PagePolicy(StrictModel):
    """검증된 등급 규칙과 페이지별 분석문 제약."""

    schema_version: Literal[1]
    policy_version: str
    page_id: PageId
    name: str
    definition: str
    score_min: float = 0
    score_max: float = 100
    grade_rules: list[GradeRule] = Field(min_length=1)
    analysis_constraints: list[str] = Field(default_factory=list)
    source_note: str

    def classify(self, score: float, crisis_flag: bool | None = None) -> GradeResult:
        """가장 먼저 일치하는 등급 규칙으로 점수를 분류한다."""

        if not self.score_min <= score <= self.score_max:
            raise PolicyError(
                f"{self.page_id} score {score} is outside "
                f"{self.score_min}..{self.score_max}"
            )
        for rule in self.grade_rules:
            if not rule.matches(score, crisis_flag):
                continue
            upper_boundary = rule.max_score if rule.max_score < self.score_max else None
            distance = (
                max(upper_boundary - score, 0.0) if upper_boundary is not None else None
            )
            return GradeResult(
                label=rule.label,
                score=score,
                crisis_flag=crisis_flag,
                upper_boundary=upper_boundary,
                distance_to_upper_boundary=distance,
            )
        raise PolicyError(
            f"{self.page_id} policy does not classify score={score}, "
            f"crisis_flag={crisis_flag}"
        )


@lru_cache(maxsize=2)
def load_page_policy(page_id: PageId) -> PagePolicy:
    """해당 페이지의 등급 정책 YAML을 읽어 검증한다."""

    resource = _POLICY_DIR / f"{page_id}.yaml"
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"cannot load analysis policy for {page_id}: {exc}") from exc
    policy = PagePolicy.model_validate(payload)
    if policy.page_id != page_id:
        raise PolicyError(
            f"analysis policy page_id mismatch: expected {page_id}, got {policy.page_id}"
        )
    return policy
