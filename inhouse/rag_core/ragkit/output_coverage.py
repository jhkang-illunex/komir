"""Exact output-set diagnostics, not plan acceptance or automatic repair.

Callers retain their vocabulary, aliases and args-dependent production rules.
Provider hints use declared semantic output types only; allowed row fields,
runtime ValueTypes and semantic tokens are not interchangeable namespaces.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping


@dataclass(frozen=True)
class OutputCoverageDiagnostic:
    required: frozenset[str]
    produced: frozenset[str]
    missing: tuple[str, ...]
    known_providers: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def covered(self) -> frozenset[str]:
        return self.required & self.produced

    @property
    def status(self) -> Literal["COMPLETE", "PARTIAL", "MISSING"]:
        if not self.missing:
            return "COMPLETE"
        return "PARTIAL" if self.covered else "MISSING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": sorted(self.required), "produced": sorted(self.produced),
            "covered": sorted(self.covered), "missing": list(self.missing),
            "known_providers": {output: list(providers) for output, providers in self.known_providers},
            "status": self.status,
        }


def diagnose_output_coverage(
    required: Iterable[str], produced: Iterable[str], *,
    provider_specs: Mapping[str, Mapping[str, Any]] | None = None,
) -> OutputCoverageDiagnostic:
    """Compare one vocabulary; provider availability never fills a missing output.

    ``provider_specs`` is an optional read-only catalog view. Candidates are
    exact declared ``output_type`` matches, not verified argument, dependency,
    cardinality, provenance, field or executable-composition compatibility.
    Existing acceptance callers need no provider lookup; richer observations
    must not be fed into model/repair payloads as part of this extraction.
    """
    required_set, produced_set = frozenset(required), frozenset(produced)
    missing = tuple(sorted(required_set - produced_set))
    providers = () if provider_specs is None else tuple(
        (output, tuple(sorted(
            action_id for action_id, spec in provider_specs.items()
            if spec.get("output_type") == output
        )))
        for output in missing
    )
    return OutputCoverageDiagnostic(required_set, produced_set, missing, providers)
