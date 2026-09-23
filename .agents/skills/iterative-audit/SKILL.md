---
name: iterative-audit
description: Risk-adaptive, quota-aware workflow for implementing and validating multi-area changes. Prefer the cheapest sufficient model and deterministic checks; batch premium audits and iterate only for material risk.
---

# Iterative Audit — Risk-Adaptive and Quota-Aware Development

Use this skill when work needs implementation plus evidence-based validation. The workflow is not a fixed Plan → Implement → Audit loop. Its objective is sufficient quality with the least unnecessary model use, repeated context loading, and quota consumption.

## 1. Preconditions and task classification

Before acting:

- Define scope, exclusions, stopping condition, and a round cap (default five).
- Confirm the live process or container. Source changes do not prove deployment.
- Inventory relevant caches (`st.cache_*`, `lru_cache`, module globals) when runtime behavior is in scope.
- Assign each editable file to exactly one worker. Shared workspaces forbid concurrent edits to the same file.
- Preserve unrelated dirty changes.

Classify the task as `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` using scope, dependency impact, public contracts, data semantics, architecture, security, reversibility, test coverage, and silent-failure risk.

### LOW

Text, labels, formatting, mechanical refactors, isolated tests, trivial configuration, obvious local fixes, or changes strongly covered by deterministic tests.

Pipeline: worker plan and implementation → deterministic checks → done. Do not invoke a premium planner or auditor by default.

### MEDIUM

Local business logic, isolated features, limited multi-file changes, or moderate behavior changes without a public contract change.

Pipeline: worker plan and implementation → deterministic checks → collect compatible changes → one batched premium audit when justified → done.

### HIGH

Public API or contract changes, retrieval/evidence/provenance logic, cross-module invariants, important data semantics, complex state transitions, or behavior that tests cannot fully establish.

Pipeline: premium plan → worker implementation → targeted tests → premium targeted audit → done or focused fix.

### CRITICAL

Architecture, schema or migration changes, security/authorization, core data integrity, irreversible operations, or fundamental contracts.

Pipeline: premium plan → worker implementation → regression tests → premium audit → targeted fix and re-audit only for HIGH/CRITICAL findings.

## 2. Model allocation

Premium models (for example Sol) are escalation resources for difficult planning, semantic validation, HIGH/CRITICAL audits, and cross-module invariants. Worker models (for example Terra/Luna) handle implementation, local planning, tests, debugging, and repetitive changes.

LOW and MEDIUM work should normally stay with workers. Do not invoke a premium model merely because a planning or audit phase exists.

## 3. Deterministic validation first

Use this order whenever it can establish correctness:

1. Static checks and diff checks.
2. Unit tests.
3. Targeted regression tests.
4. Risk evaluation.
5. Premium audit only when residual risk justifies it.

Tests are the first-line auditor. Do not spend premium reasoning tokens rediscovering failures that deterministic checks can detect.

## 4. Conditional and batched audits

Before creating an audit, ask:

1. Can deterministic tests sufficiently validate the change?
2. Is the change LOW risk?
3. Has the exact area already been audited?
4. Can this audit be combined with pending compatible changes?
5. Does the expected risk reduction justify premium usage?

Skip or defer the audit when it adds little value. Batch logically related MEDIUM changes into one audit. The auditor reviews only the changed diff, affected contracts and invariants, relevant test results, and directly neighboring behavior. Do not re-audit the repository without evidence of repository-wide impact.

## 5. Round workflow

1. Investigate first and report reproducible evidence before editing when the risk warrants independent investigation.
2. Triage findings by severity, exclusions, and file ownership.
3. Give each owner a focused fix request with evidence, allowed files, success criteria, and regression checks.
4. Review before/after evidence. A fix claim without same-condition verification is incomplete.
5. A designated deployment owner alone may rebuild, restart, or deploy. Confirm image/process identity afterward.
6. Clear relevant caches before runtime rechecks. Do not repeat a full audit unless new evidence warrants it.
7. Record fixed items, remaining items, exclusions, deployment state, and new HIGH/CRITICAL findings in the project evidence location.

Iterate primarily when the previous audit finds HIGH or CRITICAL issues. Fix LOW findings directly or record them as backlog; fix MEDIUM findings without restarting the entire pipeline or include them in the next batch audit.

## 6. Quota-aware execution

Treat model quota as finite compute. Adjust the pipeline using task risk, complexity, context size, remaining quota, expected audit value, and deterministic coverage.

- **Above 50%:** normal risk-adaptive execution; premium models allowed for HIGH/CRITICAL work; batch MEDIUM audits.
- **20–50%:** premium planning only for HIGH/CRITICAL; use workers and reuse prior context aggressively.
- **5–20%:** preservation mode; avoid broad analysis and new expensive work; finish active work and rely on deterministic checks.
- **At or below 5%:** stop starting expensive work. Create a checkpoint, then wait for quota reset. Do not repeatedly poll the quota.

The checkpoint must record: completed work, current task, modified files, diff state, tests run/passed/failed, unresolved HIGH/CRITICAL issues, pending audit requirements, remaining tasks, and the exact next command or action.

## 7. Resume after reset

Read the checkpoint first. Do not restart analysis. Reuse the previous plan, audit conclusions, tests, invariants, and inspected files. Reload only the context needed for the next unfinished operation.

## 8. Safety and deployment boundaries

- Reproduce uncertain root causes before proposing fixes.
- Do not independently restart shared containers, alter shared databases irreversibly, merge, commit, or deploy unless explicitly authorized and assigned.
- Keep deployment claims separate from local-source claims.
- Preserve rollback evidence for material data or deployment changes.

## 9. Objective

Choose the pipeline that minimizes compute cost plus residual risk while meeting the required quality. The objective is minimum sufficient intelligence, not minimum tokens at any cost and not maximum reasoning for every task.
