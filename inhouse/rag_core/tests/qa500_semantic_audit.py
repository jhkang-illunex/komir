"""Offline, conservative QA500 contract audit (stdlib only; no production imports).

Run::
    python3 inhouse/rag_core/tests/qa500_semantic_audit.py \
      --input /tmp/qa500-gemma-before.jsonl --output /tmp/qa500-semantic-audit.json
    python3 inhouse/rag_core/tests/qa500_semantic_audit.py --self-test

The 125 authored TSV contracts are Gold, shared by all four parameter variants.
Regex below reads TEST GOLD, never repairs/interprets the model's question text.
Model evidence comes exclusively from typed fields and explicit DAG references.
Output names, presentation prose, raw_content and schema success are NOT evidence
of executable semantics. MATCHED means a narrow structural check, never full PASS.
Every case retains its exact result invariant as an unresolved review obligation.
No backend execution, live SemanticProgram or multi-turn snapshot is inferred.
"""

import argparse
import calendar
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import Mock


HERE = Path(__file__).resolve().parent
DIMENSIONS = ("entities", "metric", "period", "operation",
              "ordering_dependency", "requested_output", "ties")
V2_PRIMITIVES = {"Retrieve", "Calculate", "Filter", "Sort", "TopK", "Select",
                 "Aggregate", "Compare", "Join", "Project", "Composite"}
MINERALS = {
    "니켈": {"니켈", "NI", "nickel"}, "구리": {"구리", "CU", "copper"},
    "리튬": {"리튬", "LI", "lithium"}, "코발트": {"코발트", "CO", "cobalt"},
    "희토류": {"희토류", "REE", "rare_earth"}, "아연": {"아연", "ZN", "zinc"},
    "알루미늄": {"알루미늄", "AL", "aluminum", "aluminium"},
    "망간": {"망간", "MN", "manganese"}, "흑연": {"흑연", "graphite"},
    "텅스텐": {"텅스텐", "W", "tungsten"}, "몰리브덴": {"몰리브덴", "MO", "molybdenum"},
    "언옵테이늄": {"언옵테이늄", "unobtainium"},
}
ALIASES = {
    "mean": {"mean", "avg", "average", "arithmetic_mean"},
    "population_stddev": {"population_stddev", "stddev_pop", "stddev_population"},
    "sample_stddev": {"sample_stddev", "stddev_samp", "stddev_sample"},
    "country": {"country", "partner_country"},
    "partner_country": {"country", "partner_country"},
    "hs": {"hs", "hs_code", "hs코드"},
    "material_flow": {"material_flow", "stage", "product_stage"},
    "share": {"share", "country_share"},
    "country_share": {"share", "country_share"},
    "change": {"change", "price_change", "import_change", "percent_change"},
    "yoy": {"yoy", "year_over_year", "yoy_change"},
    "pp": {"pp", "percentage_point", "percentage_point_change"},
    "value/weight": {"value/weight", "unit_value", "unit_price"},
    "unit_value": {"value/weight", "unit_value", "unit_price"},
    "balance": {"balance", "trade_balance"},
    "reserve/production": {"reserve/production", "reserve_life", "reserves_life"},
    "correlation": {"correlation", "pearson", "pearson_correlation"},
    "first": {"first", "first_observation", "first_of_period"},
    "latest": {"latest", "last", "last_observation"},
    "date": {"date", "observation_date"},
    "count": {"count", "observation_count", "valid_count", "count_valid"},
}
COUNTRIES = {
    "한국": {"한국", "대한민국", "South Korea", "Korea", "KR", "KOR", "410"},
    "중국": {"중국", "China", "CN", "CHN", "156"},
    "칠레": {"칠레", "Chile", "CL", "CHL", "152"},
    "호주": {"호주", "Australia", "AU", "AUS", "036"},
    "인도네시아": {"인도네시아", "Indonesia", "ID", "IDN", "360"},
}
# Human-inspected BEFORE examples. A digest prevents these observations from
# being silently reused for an AFTER plan or a replaced/duplicate input record.
MANUAL_BASELINE = {
    "EXT500-001": ("cb44e923099be10e71940ad5fd74cbd3c825128176f1c9076615106df262b929",
                   "SEMANTIC_MISMATCH", "ArgMax(value)만 있고 Gold의 일별 high_price 선택과 모든 동률 반환 정책이 누락됨.",
                   "turn[1].semantic_plan.requirements[0].selection"),
    "EXT500-005": ("66c9b4550708010a945411cb5bc320073b23f2f53396006dfc7739ee7502d646",
                   "SEMANTIC_MISMATCH", "NULL을 0으로 세지 말라는 Gold를 exclude_zero=true로 바꿔 실제 0도 제외하는 의미로 변조함. NULL/0 구별 위반 확정.",
                   "turn[1].semantic_plan.requirements[0].constraints"),
    "EXT500-009": ("3a9c04f6260a411bac8998bd4c8c276036793f032f051b52f0c5f5cbeb1afff3",
                   "SEMANTIC_MISMATCH", "월평균이 Retrieve.aggregation에만 남음. Aggregate와 유효 관측 수 계산이 없고 날짜 목록은 count를 대체하지 않음.",
                   "turn[1].logical_program.nodes"),
    "EXT500-041": ("20fb5797d00a39f8f645a523dc1988d2f90f006ebd2a70c1feff6b4492cd5d93",
                   "SEMANTIC_MISMATCH", "국가별 sum과 share가 조회 속성에만 있음. TopK(k=3)에는 동률 정책이 없고 전체국가 분모도 실행 미검증.",
                   "turn[1].logical_program.nodes"),
    "EXT500-269": ("18e28132d46afec59cc2fe30153723ab4022b6c8a4d18df16aa54b3dceac24e4",
                   "SEMANTIC_MISMATCH", "문서→광종 추출→가격 입력 binding이 없고 가격 latest에 연말 cutoff가 없음. V2 ForEach 공백과 live 지원을 혼동하면 안 됨.",
                   "turn[1].logical_program.nodes[req_other_minerals_price]"),
    "EXT500-325": ("33779517bf5d390c12362461d4f7c9c56645cd19221b992d527e794dc9a90fb4",
                   "SEMANTIC_MISMATCH", "3턴의 requested=true req_5_select(argmin change)가 최종 root에 연결되지 않아 요청된 선택 결과 소실 확정. snapshot 없는 멀티턴 E2E 미검증은 별도.",
                   "turn[3].logical_program.roots"),
}


def equivalent(value, expected):
    """Closed aliases, not substring matching or unrestricted semantic guessing."""
    return isinstance(value, str) and value.lower() in ALIASES.get(expected.lower(), {expected.lower()})


def entity_tokens(value):
    """Inspect a typed entity value only; a comma string still needs set review."""
    if isinstance(value, str):
        return {v.strip() for v in value.split(",")}
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    return set()


def leaves(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from leaves(value, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from leaves(value, f"{path}[{i}]")
    elif obj is not None:
        yield path, obj


def load_gold():
    corpus_path = HERE / "qa_build_order2_4_500.json"
    patterns_path = HERE / "qa_order2_4_patterns.tsv"
    corpus_bytes, pattern_bytes = corpus_path.read_bytes(), patterns_path.read_bytes()
    cases = json.loads(corpus_bytes)["cases"]
    patterns = {}
    for line in pattern_bytes.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        order, family, source, metrics, graph, invariant, template = line.split("|", 6)
        pid = f"PAT-{len(patterns) + 1:03d}"
        patterns[pid] = dict(order=order, family=family, source=source,
                             metrics=metrics.split(","), graph=graph.split(">"),
                             invariant=invariant, template=template)
    if len(cases) != 500 or len(patterns) != 125 or len({c["id"] for c in cases}) != 500:
        raise ValueError("Gold must contain 500 unique IDs and 125 patterns")
    if Counter(c["pattern_id"] for c in cases) != Counter({p: 4 for p in patterns}):
        raise ValueError("Each Gold pattern must have exactly four variants")
    for case in cases:
        p = patterns[case["pattern_id"]]
        bindings = case["semantic_requirement"]["parameter_bindings"]
        if (case["operation_graph"] != p["graph"] or
                case["semantic_requirement"]["metrics"] != p["metrics"] or
                case["result_invariant"] != p["invariant"] or
                len(case["turns"]) != len(p["template"].split("|||"))):
            raise ValueError(f"Corpus/TSV Gold drift: {case['id']}")
    return cases, patterns, {"corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
                              "patterns_sha256": hashlib.sha256(pattern_bytes).hexdigest()}


def read_snapshot(path):
    """Read one bounded byte snapshot; unfinished last line is retried next run.

    Latest complete duplicate wins, including failures. Never cherry-pick a PASS.
    Malformed complete lines/unknown IDs remain visible in input diagnostics.
    """
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(0)
            data = stream.read(size)
    except FileNotFoundError:
        return {}, {"bytes": 0, "missing_input": True, "errors": [], "duplicates": []}
    rows, errors, duplicates = {}, [], []
    lines = data.splitlines(keepends=True)
    pending_tail = 0
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("expected object with string id")
        except (ValueError, UnicodeError) as exc:
            if lineno == len(lines) and not line.endswith(b"\n"):
                pending_tail = len(line)
            else:
                errors.append({"line": lineno, "error": str(exc)})
            continue
        if row["id"] in rows:
            duplicates.append({"id": row["id"], "previous_line": rows[row["id"]][0],
                               "selected_line": lineno})
        rows[row["id"]] = (lineno, row)
    return rows, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                  "errors": errors, "duplicates": duplicates, "pending_tail_bytes": pending_tail}


def interval(time_range):
    if not isinstance(time_range, dict):
        return None
    start, end = time_range.get("start"), time_range.get("end")
    year = time_range.get("value")
    if time_range.get("kind") in {"year", "calendar_year"} and isinstance(year, int):
        return f"{year}-01-01", f"{year}-12-31"
    try:
        if start and end:
            date.fromisoformat(start)
            date.fromisoformat(end)
            return (start, end) if start <= end else None
    except (ValueError, TypeError):
        pass
    return None


def same_period_union(periods, expected):
    """Accept a partition of a fixed interval, without accepting gaps/overshoot."""
    valid = sorted(set(p for p in periods if p is not None))
    if not valid or valid[0][0] != expected[0]:
        return False
    end = valid[0][1]
    for start, stop in valid[1:]:
        if date.fromisoformat(start).toordinal() > date.fromisoformat(end).toordinal() + 1:
            return False
        end = max(end, stop)
    return end == expected[1]


def gold_periods(question, bindings, pid):
    """Gold-only period extraction. Complex/dynamic windows get explicit review."""
    y, m = bindings["y"], bindings["month"]
    if pid == "PAT-041":
        return [(f"{y}-01-01", f"{y}-06-30"), (f"{y}-07-01", f"{y}-12-31")]
    if pid == "PAT-049":
        return [(f"{year}-01-01", f"{year}-{m:02d}-{calendar.monthrange(year, m)[1]}")
                for year in (y, bindings["prev_year"])]
    span = re.search(r"(20\d{2})년부터 (20\d{2})년까지", question)
    if span:
        return [(f"{span[1]}-01-01", f"{span[2]}-12-31")]
    months = re.findall(r"(20\d{2})년 (\d{1,2})월", question)
    if months and "말" not in question and "발표 전후" not in question:
        return [(f"{int(year)}-{int(month):02d}-01",
                 f"{int(year)}-{int(month):02d}-{calendar.monthrange(int(year), int(month))[1]}")
                for year, month in months]
    years = {int(x) for x in re.findall(r"(20\d{2})년", question)}
    if "전년" in question:
        years.add(y - 1)
    return [(f"{year}-01-01", f"{year}-12-31") for year in sorted(years)]


def metric_evidence(req, metric):
    actual = req.get("metric")
    op = req.get("operation")
    if metric == "price":
        return actual in {"price", "price_change"}
    if metric == "import_value":
        return actual in {"import_value", "import_change"} and req.get("flow") != "export" and op != "weight"
    if metric == "reserve":
        return actual in {"reserve", "reserves"}
    if metric in {"document", "news"}:
        return actual == "document_evidence"  # news subtype remains a review obligation
    if metric in {"hhi", "cr3", "tsi", "unit_value", "trade_balance", "country_dependency"}:
        expected = {"country_dependency": "share"}.get(metric, metric)
        return any(equivalent(req.get(k), expected) for k in ("operation", "aggregation", "indicator"))
    if metric == "import_weight":
        return actual == "import_weight" or (actual == "import_value" and
            (op == "weight" or any(v in {"weight", "import_weight"} for _, v in leaves(req.get("constraints")) if isinstance(v, str))))
    if metric == "export_value":
        return actual == "export_value" or (actual == "import_value" and req.get("flow") == "export")
    if metric in {"mineral_index", "supply_stability_index", "market_outlook_index"}:
        return actual == "indicator" and (req.get("indicator") == metric or
            (metric == "mineral_index" and req.get("indicator") in {"HI001", "HI002", "HI003", "HI004"}))
    if metric in {"forecast", "price_basis", "exchange_rate"}:
        return actual == metric or op == metric
    if metric in {"mineral_mentions", "summary", "event_facts", "event_date", "issues"}:
        return None  # extraction contract cannot be inferred from document_evidence alone
    return actual == metric


def step_nodes(step, nodes):
    """Return (matched nodes, check kind). Unknown compositions need human review.

    Retrieve.operation/aggregation, output names and presentation never count as
    Calculate/Aggregate implementations. Fused time Filter is narrowly recognized.
    """
    head = step.split("(", 1)[0]
    arg = step[len(head) + 1:-1] if "(" in step else ""
    found = []
    supported = head in {"Retrieve", "RetrieveDocument", "ArgMax", "ArgMin", "Aggregate",
                         "Calculate", "GroupBy", "Join", "Compare", "Sort", "Rank",
                         "TopK", "Select", "First", "Count", "Filter", "Project"}
    if not supported:
        return [], "REVIEW_NEEDED"
    for node in nodes:
        op, a = node.get("op"), node.get("arguments", {})
        match = False
        if head in {"Retrieve", "RetrieveDocument"}:
            match = op == "Retrieve" and (head == "Retrieve" or a.get("metric") in {"document_evidence", "usage"})
        elif head in {"ArgMax", "ArgMin", "First"}:
            match = op == "Select" and equivalent(a.get("mode"), {"ArgMax": "argmax", "ArgMin": "argmin", "First": "first"}[head])
        elif head in {"Aggregate", "Calculate", "Count"}:
            expected = "count" if head == "Count" else arg
            keys = ("aggregation", "function") if head in {"Aggregate", "Count"} else ("calculation", "operation", "metric", "function")
            match = op == ("Aggregate" if head == "Count" else head) and (not expected or
                all(any(equivalent(a.get(k), e) for k in keys) for e in expected.split(",")))
            if head == "Calculate" and arg.lower() in {"hhi", "cr3", "population_stddev", "sample_stddev", "correlation"}:
                match = match or (op == "Aggregate" and equivalent(a.get("aggregation"), arg))
            if head == "Count":
                match = match or (op == "Calculate" and equivalent(a.get("calculation"), "count"))
        elif head == "GroupBy":
            groups = a.get("group_by", [])
            if isinstance(groups, str):
                groups = [groups]
            match = op == "Aggregate" and all(any(equivalent(g, x) for g in groups) for x in arg.split(","))
        elif head == "Select":
            match = op == "Select" and (not arg or equivalent(a.get("mode"), arg))
        elif head == "Filter" and arg in {"period", "year", "as_of"}:
            match = (op == "Retrieve" and bool(a.get("time_range"))) or op == "Filter"
        elif head == "Project":
            match = op == "Project"
        elif head == "Rank":
            match = op == "Sort"  # rank ordinal/tie policy still reviewed
        else:
            match = op == head
        if match:
            found.append(node)
    # A Project may be folded into a renderer; Rank may be Sort+TopK. Do not
    # claim a proven semantic failure solely because conceptual node is absent.
    kind = "STRUCTURAL" if head not in {"Project", "Rank", "Select", "Filter"} else "REVIEW_NEEDED"
    return found, kind


def audit_case(case, pattern, record=None, line=None):
    findings, checks = [], []

    def add(dimension, code, expected, observed, paths=(), status="MISMATCH", turn=None,
            failure_class=None):
        if status == "MISMATCH":
            status = ("PIPELINE_FAILURE" if dimension == "parser" else
                      "INPUT_ERROR" if dimension == "input" else "SEMANTIC_MISMATCH")
        if failure_class is None and status == "SEMANTIC_MISMATCH":
            failure_class = ("LOGICAL_PLAN_INCOMPLETE" if dimension == "ordering_dependency" or
                             code in {"OPERATION_NOT_ESTABLISHED", "REQUESTED_NODE_NOT_REACHABLE"}
                             else "SEMANTIC_OMISSION")
        findings.append(dict(dimension=dimension, code=code, status=status, turn=turn,
                             failure_class=failure_class,
                             expected=expected, observed=observed, evidence_paths=list(paths)))

    def matched(dimension, expected, paths):
        checks.append(dict(dimension=dimension, expected=expected, evidence_paths=list(paths),
                           status="MATCHED_STRUCTURAL_ONLY"))

    base = dict(id=case["id"], pattern_id=case["pattern_id"], variant_id=case["variant_id"],
                input_line=line, gold=dict(metrics=pattern["metrics"], operation_graph=pattern["graph"],
                invariant=pattern["invariant"], bindings=case["semantic_requirement"]["parameter_bindings"]),
                full_pass=False, multiturn_e2e_pass=False, live_semantic_program_assessed=False)
    turns = (record or {}).get("turns", [])
    if not isinstance(turns, list):
        turns = []
    turn_map = {t.get("turn"): t for t in turns if isinstance(t, dict)}
    requirements, nodes, plans = [], [], []
    parsed = logical_turns = source_checked = source_conflicts = 0
    if record and record.get("pattern_id") != case["pattern_id"]:
        add("input", "PATTERN_ID_MISMATCH", case["pattern_id"], record.get("pattern_id"))
    for gold_turn in case["turns"]:
        num = gold_turn["turn"]
        prefix = f"turn[{num}]"
        t = turn_map.get(num)
        if t is None:
            add("input", "MISSING_LOG_TURN", "complete logged turn", None,
                status="REVIEW_NEEDED", turn=num)
            continue
        if t.get("question") != gold_turn["question"]:
            add("input", "QUESTION_IDENTITY_MISMATCH", gold_turn["question"], t.get("question"), turn=num)
        plan = t.get("semantic_plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("requirements"), list):
            add("parser", "PARSER_OR_SCHEMA_FAIL", "typed semantic_plan", t.get("error", t.get("status")), turn=num)
            continue
        parsed += 1
        artifacts = [a.get("parsed_output") for a in (t.get("record") or {}).get("attempts", [])
                     if isinstance(a, dict) and isinstance(a.get("parsed_output"), dict)]
        if artifacts:
            source_checked += 1
            if artifacts[-1] != plan:
                source_conflicts += 1
                add("input", "SCHEMA_ARTIFACT_TRACE_CONFLICT", artifacts[-1], plan,
                    [prefix + ".record.attempts[-1].parsed_output", prefix + ".semantic_plan"], turn=num)
        plans.append((prefix, plan))
        reqs = [r for r in plan["requirements"] if isinstance(r, dict)]
        requirements.extend((f"{prefix}.semantic_plan.requirements[{i}]", r) for i, r in enumerate(reqs))
        if plan.get("request_class") != "DATA_QUERY":
            add("metric", "NORMAL_DATA_REQUIREMENTS_REJECTED", pattern["metrics"], plan.get("request_class"), turn=num)
        # Per-turn explicit Gold entities: future turns never excuse an earlier omission.
        mineral_aliases = dict(MINERALS)
        for key in ("m", "m2"):
            value = base["gold"]["bindings"][key]
            mineral_aliases.setdefault(value, {value})
        for mineral, aliases in mineral_aliases.items():
            if mineral not in gold_turn["question"]:
                continue
            evidence = [f"{prefix}.semantic_plan.requirements[{i}].entity" for i, r in enumerate(reqs)
                        if (r.get("entity") or {}).get("value") in aliases]
            # Typed document filters may identify the anchor without entity.value.
            doc_evidence = [f"{prefix}.semantic_plan.requirements[{i}].document_requirement.{p}"
                            for i, r in enumerate(reqs) for p, value in leaves(r.get("document_requirement"))
                            if isinstance(value, str) and value in aliases]
            if evidence or doc_evidence:
                matched("entities", mineral, evidence + doc_evidence)
            else:
                possible = [f"{prefix}.semantic_plan.requirements[{i}].{p}"
                            for i, r in enumerate(reqs) for p, v in leaves({k: r.get(k) for k in (
                                "entity", "constraints", "scope", "document_requirement")})
                            if entity_tokens(v) & aliases]
                add("entities", "ENTITY_SET_BINDING_REQUIRES_REVIEW" if possible else "MISSING_ENTITY_BINDING", mineral,
                    [r.get("entity") for r in reqs], possible or [prefix + ".semantic_plan.requirements"],
                    status="REVIEW_NEEDED" if possible else "MISMATCH", turn=num)
        expected_periods = gold_periods(gold_turn["question"], base["gold"]["bindings"], case["pattern_id"])
        actual_periods = [(i, interval(r.get("time_range"))) for i, r in enumerate(reqs)]
        for expected in expected_periods:
            evidence = [f"{prefix}.semantic_plan.requirements[{i}].time_range" for i, p in actual_periods if p == expected]
            if evidence:
                matched("period", expected, evidence)
            else:
                # Date partitions, as-of bounds and dynamic windows may be equivalent.
                # No time at all is definite absence; other representations need review.
                status = "MISMATCH" if not any(r.get("time_range") for r in reqs) and len(case["turns"]) == 1 else "REVIEW_NEEDED"
                simple_fixed = case["pattern_id"] in {
                    "PAT-001", "PAT-002", "PAT-003", "PAT-004", "PAT-008", "PAT-009", "PAT-010",
                    "PAT-011", "PAT-012", "PAT-013", "PAT-014", "PAT-015", "PAT-016", "PAT-017",
                    "PAT-018", "PAT-019", "PAT-020", "PAT-021", "PAT-022", "PAT-024", "PAT-025", "PAT-027"}
                if simple_fixed and actual_periods and all(p for _, p in actual_periods) and not any(r.get("constraints") for r in reqs) and not same_period_union([p for _, p in actual_periods], expected):
                    # All intervals are explicit but the sole fixed Gold interval
                    # is absent, with no alternate temporal predicate to inspect.
                    status = "MISMATCH"
                add("period", "PERIOD_NOT_ESTABLISHED", expected, [r.get("time_range") for r in reqs],
                    [prefix + ".semantic_plan.requirements"], status, num)
        if case["pattern_id"] == "PAT-005":
            b = base["gold"]["bindings"]
            cutoff = f"{b['y']}-{b['month']:02d}-{calendar.monthrange(b['y'], b['month'])[1]}"
            for i, req in enumerate(reqs):
                if req.get("metric") != "price":
                    continue
                actual_end = (req.get("time_range") or {}).get("end")
                if actual_end != cutoff:
                    add("period", "AS_OF_CUTOFF_NOT_PRESERVED", cutoff, req.get("time_range"),
                        [f"{prefix}.semantic_plan.requirements[{i}].time_range"],
                        "REVIEW_NEEDED" if req.get("constraints") else "MISMATCH", num)
        for i, req in enumerate(reqs):
            rp = f"{prefix}.semantic_plan.requirements[{i}]"
            tr = req.get("time_range") or {}
            if expected_periods and tr.get("kind") == "latest" and not tr.get("end"):
                bounds = [(p, v) for p, v in leaves(req.get("constraints"))
                          if p.rsplit(".", 1)[-1] in {"year", "end", "as_of", "cutoff", "before", "date"}]
                add("period", "HISTORICAL_LATEST_WITHOUT_BOUND", "Gold historical cutoff per requirement",
                    {"time_range": tr, "alternative_bounds": bounds}, [rp + ".time_range"],
                    "REVIEW_NEEDED" if bounds or req.get("operation") in {"year_end", "latest_at_year_end"} else "MISMATCH", num)
            if req.get("constraints"):
                # Preservation checks below compare typed payloads; free text
                # constraints are never interpreted as executable semantics.
                if any(c.get("exclude_zero") is True for c in req["constraints"] if isinstance(c, dict)) and "값이 없는 날은 0" in gold_turn["question"]:
                    add("metric", "NULL_ZERO_POLICY_CONFLATION", "exclude missing values; do not silently exclude observed zero",
                        req["constraints"], [rp + ".constraints"], "MISMATCH", num, "SEMANTIC_CONTRADICTION")
        expected_limits = {int(v) for v in re.findall(r"(?:상위\s*|최신\s*|기사\s*)(\d+)\s*(?:개|국)", gold_turn["question"])}
        if expected_limits:
            actual_limits = [r.get("limit") for r in reqs if r.get("limit") is not None]
            for k in sorted(expected_limits):
                if k not in actual_limits:
                    add("operation", "TOPK_CARDINALITY_NOT_ESTABLISHED", k, actual_limits,
                        [prefix + ".semantic_plan.requirements[*].limit"], "REVIEW_NEEDED", num)
        country_aliases = dict(COUNTRIES)
        country = base["gold"]["bindings"]["country"]
        country_aliases.setdefault(country, {country})
        for country, aliases in country_aliases.items():
            if country not in gold_turn["question"]:
                continue
            evidence = [f"{prefix}.semantic_plan.requirements[{i}].{path}"
                        for i, req in enumerate(reqs) for path, value in leaves({
                            k: req.get(k) for k in ("entity", "scope", "constraints", "document_requirement")})
                        if isinstance(value, str) and value in aliases]
            if evidence:
                matched("entities", {"country": country, "role": "presence_only"}, evidence)
            else:
                add("entities", "COUNTRY_BINDING_NOT_ESTABLISHED", country,
                    [{k: r.get(k) for k in ("scope", "entity", "constraints", "document_requirement")} for r in reqs],
                    [prefix + ".semantic_plan.requirements"], "REVIEW_NEEDED", num)
        logical = t.get("logical_program")
        if not isinstance(logical, dict):
            add("operation", "LOGICAL_PROGRAM_UNAVAILABLE", "logged logical-primitive-v2", t.get("error"),
                [prefix], "PIPELINE_FAILURE" if t.get("status") == "LOWERING_FAILURE" else "REVIEW_NEEDED", num)
            continue
        if logical.get("schema_version") != "logical-primitive-v2":
            add("operation", "NOT_V2_PROGRAM", "logical-primitive-v2; live program assessed separately",
                logical.get("schema_version"), [prefix + ".logical_program"], "REVIEW_NEEDED", num)
            continue
        logical_turns += 1
        local = [n for n in logical.get("nodes", []) if isinstance(n, dict)]
        for i, req in enumerate(reqs):
            req_id = req.get("requirement_id")
            # A semantic aggregation/calculation copied only onto Retrieve is
            # an explicit semantic->logical loss, distinct from Gemma omission.
            refs_for_req = {n.get("node_id"): [x.get("node_id") for x in n.get("inputs", []) if isinstance(x, dict)] for n in local}
            derived = {n.get("node_id") for n in local if n.get("op") == "Retrieve" and (
                n.get("node_id") == req_id or n.get("node_id") == f"{req_id}_retrieve")}
            for _ in range(len(local)):
                enlarged = derived | {nid for nid, src in refs_for_req.items() if any(s in derived for s in src)}
                if enlarged == derived:
                    break
                derived = enlarged
            for field, op in (("aggregation", "Aggregate"), ("operation", "Calculate")):
                value = req.get(field)
                known = (field == "aggregation" and any(equivalent(value, x) for x in (
                    "mean", "sum", "count", "hhi", "population_stddev", "sample_stddev"))) or (
                    field == "operation" and any(equivalent(value, x) for x in (
                        "share", "hhi", "cr3", "tsi", "unit_value", "balance", "change", "difference", "pp")))
                possible_ops = {"Aggregate", "Calculate"} if field == "aggregation" else {"Aggregate", "Calculate", "Compare"}
                candidates = [n for n in local if n.get("node_id") in derived and n.get("op") in possible_ops]
                if known and not candidates:
                    add("operation", "SEMANTIC_OPERATION_LOST_IN_DAG", {field: value, "requirement_id": req_id},
                        {"reachable_computations": [], "retrieval_descendants": sorted(derived)},
                        [f"{prefix}.semantic_plan.requirements[{i}].{field}", prefix + ".logical_program.nodes"],
                        "MISMATCH", num, "LOWERING_PLANNING_LOSS")
        for i, req in enumerate(reqs):
            for ci, constraint in enumerate(req.get("constraints", [])):
                if not isinstance(constraint, dict):
                    continue
                # A lost typed constraint is a lowering coverage finding, not
                # proof that an adapter's undocumented default violates it.
                gold_leaves = list(leaves(constraint))
                actual_leaves = [item for n in local for item in leaves(n.get("arguments", {}))]
                missing = [(p, v) for p, v in gold_leaves if not any(
                    ap.rsplit(".", 1)[-1] == p.rsplit(".", 1)[-1] and av == v for ap, av in actual_leaves)]
                if missing:
                    executable_keys = {"tie_breaker", "include_ties", "ties", "tie_policy", "year", "as_of", "end",
                                       "exclude_zero", "exclude_null", "exclude_country", "reporter_country", "partner_country"}
                    explicit_lost = any(p.rsplit(".", 1)[-1] in executable_keys for p, _ in missing)
                    add("ordering_dependency", "SEMANTIC_CONSTRAINT_NOT_LOWERED", constraint, missing,
                        [f"{prefix}.semantic_plan.requirements[{i}].constraints[{ci}]", prefix + ".logical_program.nodes"],
                        "MISMATCH" if explicit_lost else "REVIEW_NEEDED", num,
                        "LOWERING_PLANNING_LOSS" if explicit_lost else None)
        ids = {n.get("node_id") for n in local}
        refs = {n.get("node_id"): [x.get("node_id") for x in n.get("inputs", []) if isinstance(x, dict)] for n in local}
        roots = logical.get("roots", [])
        if len(ids) != len(local):
            add("ordering_dependency", "DUPLICATE_NODE_ID", "unique node IDs", [n.get("node_id") for n in local], turn=num)
        reachable, active = set(), set()

        def visit(node_id):
            if node_id in active:
                add("ordering_dependency", "CYCLIC_DEPENDENCY", "DAG", node_id, turn=num)
                return
            if node_id in reachable:
                return
            if node_id not in ids:
                add("ordering_dependency", "DANGLING_REFERENCE", "existing node", node_id, turn=num)
                return
            active.add(node_id)
            for source in refs[node_id]:
                visit(source)
            active.remove(node_id)
            reachable.add(node_id)

        for root in roots:
            visit(root)
        for node in local:
            nid = node.get("node_id")
            path = f"{prefix}.logical_program.nodes[{nid}]"
            if nid not in reachable:
                add("ordering_dependency", "DEAD_NODE", "check whether unconsumed node is required by Gold", nid,
                    [path], "REVIEW_NEEDED", num)
                if node.get("requested") is True:
                    add("requested_output", "REQUESTED_NODE_NOT_REACHABLE", "requested node reaches final root", nid, [path], turn=num)
            if node.get("op") not in V2_PRIMITIVES:
                add("operation", "UNKNOWN_V2_PRIMITIVE", sorted(V2_PRIMITIVES), node.get("op"), [path], turn=num)
            for source in refs[nid]:
                if source not in ids:
                    add("ordering_dependency", "DANGLING_REFERENCE", "existing node", source, [path], turn=num)
            a = node.get("arguments", {})
            if node.get("op") == "TopK" and len(expected_limits) == 1 and a.get("k") not in expected_limits:
                add("operation", "TOPK_CARDINALITY_CONFLICT", sorted(expected_limits), a.get("k"),
                    [path + ".arguments.k"], "REVIEW_NEEDED", num)
            if node.get("op") == "Sort" and any(x in gold_turn["question"] for x in ("큰 순서", "높은 순서", "최신순")):
                if a.get("order", a.get("direction")) not in {"desc", "descending"}:
                    add("ordering_dependency", "DESCENDING_ORDER_NOT_ESTABLISHED", "desc for Gold requested sort field",
                        a, [path + ".arguments"], "REVIEW_NEEDED", num)
            if node.get("op") == "Retrieve" and (a.get("aggregation") or a.get("operation")):
                add("operation", "RETRIEVE_ANNOTATION_IS_NOT_EXECUTION",
                    "explicit Aggregate/Calculate or independently verified adapter contract",
                    {k: a[k] for k in ("aggregation", "operation") if a.get(k)}, [path + ".arguments"], "REVIEW_NEEDED", num)
            if node.get("op") in {"Join", "Compare"} and (len(refs[nid]) < 2 or not a.get("join_key")):
                add("ordering_dependency", "RELATION_KEYS_OR_OPERANDS_UNESTABLISHED",
                    "typed paired operands and alignment keys", a, [path], "REVIEW_NEEDED", num)
            # An entity.source_node must be a real dependency, not just a label.
            source = (a.get("entity") or {}).get("source_node")
            if source and source not in refs[nid]:
                add("ordering_dependency", "ENTITY_SOURCE_NOT_BOUND_AS_INPUT", source, refs[nid], [path], "REVIEW_NEEDED", num)
            if nid in reachable:
                nodes.append((path, node, num, refs))

        if "mineral_mentions" in pattern["metrics"] and any(s.startswith("ForEach") for s in pattern["graph"]):
            downstream = [n for n in local if n.get("op") == "Retrieve" and
                          n.get("arguments", {}).get("metric") not in {"document_evidence", "usage"}]
            for n in downstream:
                entity = n.get("arguments", {}).get("entity") or {}
                if not refs.get(n.get("node_id")) and not entity.get("source_node") and not entity.get("value"):
                    add("ordering_dependency", "DOCUMENT_ENTITY_SET_NOT_BOUND_TO_RETRIEVE",
                        "document extraction result supplies downstream entity set",
                        {"entity": entity, "inputs": n.get("inputs")},
                        [f"{prefix}.logical_program.nodes[{n.get('node_id')}]"],
                        "MISMATCH", num, "LOGICAL_PLAN_INCOMPLETE")

    complete = parsed == len(case["turns"])
    observed = len(turn_map) > 0
    if parsed:
        for metric in pattern["metrics"]:
            evidence = [p for p, r in requirements if metric_evidence(r, metric) is True]
            uncertain = (any(metric_evidence(r, metric) is None for _, r in requirements) or
                         metric not in {"price", "inventory", "production", "reserve", "import_value"})
            if evidence:
                matched("metric", metric, evidence)
            else:
                add("metric", "METRIC_NOT_ESTABLISHED", metric,
                    [{k: r.get(k) for k in ("metric", "operation", "flow", "indicator")} for _, r in requirements],
                    [p for p, _ in requirements], "REVIEW_NEEDED" if uncertain or not complete else "MISMATCH")
        # Case-level graph screen only. Multi-turn stages cannot be allocated to
        # turns safely from a flat Gold graph; every cross-turn dependency is review.
        previous = None
        for step in pattern["graph"]:
            matches, kind = step_nodes(step, [n for _, n, _, _ in nodes])
            evidence = [p for p, n, _, _ in nodes if any(n is x for x in matches)]
            if evidence:
                matched("operation", step, evidence)
            elif step.startswith("ForEach"):
                add("operation", "V2_FOREACH_GAP", step,
                    "V2 Primitive has no ForEach; live SemanticProgram supports for_each, not evaluated here",
                    status="REVIEW_NEEDED")
            else:
                # Missing a closed alias does not prove semantic failure when
                # a plausible alternative computation exists. Keep it in review.
                head = step.split("(", 1)[0]
                alternatives = {
                    "Aggregate": {"Aggregate", "Calculate"},
                    "Calculate": {"Calculate", "Aggregate", "Compare"},
                    "GroupBy": {"Aggregate"},
                    "ArgMax": {"Select", "Sort", "TopK", "Aggregate"},
                    "ArgMin": {"Select", "Sort", "TopK", "Aggregate"},
                    "Compare": {"Compare", "Calculate"}, "TopK": {"TopK", "Select"},
                    "Join": {"Join", "Compare"},
                }
                ambiguous_alternative = any(n.get("op") in alternatives.get(head, set()) for _, n, _, _ in nodes)
                if head == "Filter" and step in {"Filter", "Filter(positive)", "Filter(index_up)", "Filter(above_mean)", "Filter(upward)"}:
                    conditions = [r.get("constraints") or r.get("selection") for _, r in requirements]
                    conditions += [rel.get("predicate") for _, plan in plans for rel in plan.get("relationships", []) if isinstance(rel, dict)]
                    if not any(conditions) and complete:
                        add("operation", "REQUIRED_FILTER_PREDICATE_ABSENT", step,
                            "no requirement constraints/selection, relationship predicate or logical Filter",
                            status="MISMATCH", failure_class="SEMANTIC_OMISSION")
                add("operation", "OPERATION_NOT_ESTABLISHED", step,
                    [{"op": n.get("op"), "arguments": n.get("arguments")} for _, n, _, _ in nodes],
                    status="MISMATCH" if kind == "STRUCTURAL" and not ambiguous_alternative and
                    complete and logical_turns == parsed and len(case["turns"]) == 1 else "REVIEW_NEEDED")
            if previous and matches:
                prev_step, prev_matches = previous
                connected = False
                for _, n, turn_number, refs in nodes:
                    if not any(n is x for x in matches):
                        continue
                    todo, seen = [n.get("node_id")], set()
                    while todo:
                        cur = todo.pop()
                        if cur in seen:
                            continue
                        seen.add(cur)
                        todo.extend(refs.get(cur, []))
                    same_turn_prev = [pn for _, pn, pt, _ in nodes if pt == turn_number and any(pn is x for x in prev_matches)]
                    if any(x.get("node_id") in seen for x in same_turn_prev):
                        connected = True
                if not connected:
                    add("ordering_dependency", "GOLD_STAGE_DEPENDENCY_NOT_ESTABLISHED",
                        f"{prev_step} -> {step}", evidence, status="REVIEW_NEEDED")
            previous = (step, matches) if matches else None
        # Required output is a projection with lineage, not a descriptive name.
        declared = [(p + f".semantic_plan.requested_outputs[{i}]", out)
                    for p, plan in plans for i, out in enumerate(plan.get("requested_outputs", []))]
        for p, out in declared:
            if not isinstance(out, dict) or not out.get("fields") or not out.get("source_node"):
                add("requested_output", "OUTPUT_LINEAGE_UNESTABLISHED", "typed fields plus producing source_node",
                    out, [p], "REVIEW_NEEDED")
            elif out.get("source_node"):
                source = out["source_node"]
                turn_prefix = p.split(".", 1)[0]
                if not any(np.startswith(turn_prefix + ".") and n.get("node_id") == source for np, n, _, _ in nodes):
                    add("requested_output", "OUTPUT_SOURCE_NOT_REACHABLE", source, "no reachable producer in this turn",
                        [p], "MISMATCH")
        if not declared:
            add("requested_output", "REQUESTED_OUTPUT_MISSING", pattern["invariant"], [],
                status="REVIEW_NEEDED" if any(r.get("requested_outputs") for _, r in requirements) else "MISMATCH")
        # Test Gold supplemental contracts: conceptual graphs omit these outputs.
        required_fields = {"PAT-001": ["date", "value"], "PAT-002": ["date"],
                           "PAT-003": ["month", "count"], "PAT-009": ["count"],
                           "PAT-011": ["country", "share"], "PAT-027": ["date", "value"]}.get(case["pattern_id"], [])
        fields = [v for _, out in declared if isinstance(out, dict) for v in out.get("fields", [])]
        for field in required_fields:
            if not any(equivalent(v, field) for v in fields):
                add("requested_output", "REQUIRED_TYPED_OUTPUT_FIELD_MISSING", field, fields,
                    [p for p, _ in declared], "REVIEW_NEEDED")
        if case["pattern_id"] in {"PAT-001", "PAT-002"}:
            expected_field = "high" if case["pattern_id"] == "PAT-001" else "low"
            values = [(p, v) for rp, r in requirements for p, v in leaves({k: r.get(k) for k in ("selection", "constraints", "scope")}, rp)
                      if p.rsplit(".", 1)[-1] in {"field", "price_field", "price_type", "price_basis"}]
            allowed = {"high", "high_price", "daily_high", "highest_price"} if expected_field == "high" else {"low", "low_price", "daily_low", "lowest_price"}
            if not any(isinstance(v, str) and v in allowed for _, v in values):
                unknown_fields = [v for _, v in values if isinstance(v, str) and v not in {
                    "value", "price", "date", "observation_date", "high", "low", "high_price", "low_price"}]
                add("metric", "PRICE_FIELD_UNSPECIFIED", expected_field, values,
                    [p for p, _ in values], "REVIEW_NEEDED" if unknown_fields else "MISMATCH")
        if case["pattern_id"] == "PAT-003" and not any(
                (n.get("op") == "Aggregate" and equivalent(n.get("arguments", {}).get("aggregation"), "count")) or
                (n.get("op") == "Calculate" and equivalent(n.get("arguments", {}).get("calculation"), "count"))
                for _, n, _, _ in nodes):
            add("operation", "VALID_OBSERVATION_COUNT_NOT_COMPUTED", "monthly count(non-null price)",
                [n.get("op") for _, n, _, _ in nodes], status="MISMATCH" if complete else "REVIEW_NEEDED")

    # Review all authored invariants, even when primitive presence checks match.
    # This preserves population, NULL/zero, units, denominator, provenance, domain
    # predicates, output subsets and conditional abstention obligations for all 125.
    add("contract", "AUTHORED_PATTERN_INVARIANT_REQUIRES_REVIEW", pattern["invariant"],
        "structural screen cannot establish numerical/runtime or full domain semantics",
        status="REVIEW_NEEDED")
    for i, invariant in enumerate(case["expected_ast"]["common_invariants"]):
        add("contract", f"COMMON_INVARIANT_{i + 1}_UNVERIFIED", invariant,
            "no backend execution or deterministic result in supplied log", status="REVIEW_NEEDED")
    question = " ".join(t["question"] for t in case["turns"])
    if "동률" in question or "공동1위" in pattern["invariant"] or "동률" in pattern["invariant"]:
        policy = "country_code_asc_exact_k" if "국가코드" in question else (
            "ask_selection" if "선택을 요청" in question else "include_all_ties")
        execution_ties = [(p, n.get("arguments")) for p, n, _, _ in nodes
                          if n.get("op") in {"Select", "Sort", "TopK"}]
        keys = {"ties", "tie_policy", "tie_breaker", "tie_break", "include_ties", "handle_ties", "keep_ties", "keep", "return_all_ties"}
        semantic_ties = [(p + "." + key, value) for p, plan in plans
                         for key, value in leaves({k: plan.get(k) for k in ("requirements", "presentation")})
                         if key.rsplit(".", 1)[-1] in keys or "tie" in key.rsplit(".", 1)[-1].lower()]
        logical_ties = [(p + "." + key, value) for p, n, _, _ in nodes
                        for key, value in leaves(n.get("arguments", {})) if key.rsplit(".", 1)[-1] in keys or "tie" in key.rsplit(".", 1)[-1].lower()]
        contradictory = [(p, v) for p, v in logical_ties if policy == "include_all_ties" and (
            v is False or isinstance(v, str) and v in {"first", "drop", "exclude", "single"})]
        if contradictory:
            add("ties", "TIE_POLICY_CONFLICT", policy, contradictory, [p for p, _ in contradictory],
                "MISMATCH", failure_class="SEMANTIC_CONTRADICTION")
        elif not logical_ties and complete:
            add("ties", "TIE_POLICY_LOST_IN_DAG" if semantic_ties else "EXPLICIT_TIE_POLICY_ABSENT", policy,
                {"semantic_policy": semantic_ties, "logical_selection": execution_ties},
                [p for p, _ in execution_ties], "MISMATCH",
                failure_class="LOWERING_PLANNING_LOSS" if semantic_ties else "SEMANTIC_OMISSION")
        else:
            add("ties", "TIE_POLICY_NOT_EXECUTION_VERIFIED", policy,
                {"semantic_policy": semantic_ties, "logical_policy": logical_ties}, status="REVIEW_NEEDED")
    if len(case["turns"]) > 1:
        add("ordering_dependency", "MULTITURN_PREVIOUS_REQUIREMENTS_ONLY", "executed immutable result snapshots and bindings",
            "collector passes previous_requirements with result_snapshots=[]; no multi-turn E2E PASS",
            status="REVIEW_NEEDED")
    add("period", "PER_REQUIREMENT_TEMPORAL_SCOPE_REVIEW", "each entity/metric keeps its own Gold period; dynamic windows, as-of and frequency",
        "a matching interval anywhere does not establish every requirement's period", status="REVIEW_NEEDED")
    add("entities", "ENTITY_ROLE_AND_BINDING_REVIEW", "reporter/partner, document-derived entity set and exclusions",
        "entity presence alone does not prove role, population or downstream binding", status="REVIEW_NEEDED")
    add("requested_output", "OUTPUT_PRODUCTION_REVIEW", pattern["invariant"],
        "typed declarations alone do not prove final root production or renderer coverage", status="REVIEW_NEEDED")
    dimensions = {}
    for dimension in DIMENSIONS:
        items = [f for f in findings if f["dimension"] == dimension]
        dimensions[dimension] = ("SEMANTIC_MISMATCH" if any(f["status"] == "SEMANTIC_MISMATCH" for f in items)
                                 else "REVIEW_NEEDED" if items or not complete
                                 else "MATCHED_STRUCTURAL_ONLY" if any(c["dimension"] == dimension for c in checks)
                                 else "NOT_APPLICABLE")
    definite = [f for f in findings if f["status"] == "SEMANTIC_MISMATCH"]
    reviews = [f for f in findings if f["status"] == "REVIEW_NEEDED"]
    status = "SEMANTIC_MISMATCH" if definite else "REVIEW_NEEDED"
    return {**base, "status": status, "evaluation_eligibility": (
        "COMPLETE_TYPED_LOG" if complete and logical_turns == parsed else "PARTIAL_TYPED_LOG" if parsed else
        "PARSER_FAILURE_ONLY" if observed else "MISSING_LOG"),
        "expected_turns": len(case["turns"]), "parsed_turns": parsed, "logical_turns": logical_turns,
        "source_artifact_checked_turns": source_checked, "source_artifact_conflict_turns": source_conflicts,
        "definite_semantic_mismatch_count": len(definite), "review_needed_count": len(reviews),
        "unverified_invariants": [f["expected"] for f in reviews if f["dimension"] == "contract"],
        "dimensions": dimensions, "checks": checks, "findings": findings}


def build_report(input_path):
    cases, patterns, provenance = load_gold()
    rows, snapshot = read_snapshot(input_path)
    snapshot["unknown_ids"] = sorted(set(rows) - {c["id"] for c in cases})
    results = [audit_case(c, patterns[c["pattern_id"]], rows.get(c["id"], (None, None))[1],
                          rows.get(c["id"], (None, None))[0]) for c in cases]
    counts = Counter(r["status"] for r in results)
    eligibility = Counter(r["evaluation_eligibility"] for r in results)
    manual = []
    for cid, (baseline_sha, status, note, path) in MANUAL_BASELINE.items():
        row = rows.get(cid, (None, {}))[1]
        payload = [{k: t.get(k) for k in ("turn", "semantic_plan", "logical_program")}
                   for t in row.get("turns", [])]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        manual.append({"id": cid, "baseline_sha256": baseline_sha, "observed_sha256": digest,
                       "status": status if digest == baseline_sha else "REVIEW_NEEDED",
                       "failure_class": ({"EXT500-001": "SEMANTIC_OMISSION", "EXT500-005": "SEMANTIC_CONTRADICTION",
                                          "EXT500-009": "LOWERING_PLANNING_LOSS", "EXT500-041": "LOWERING_PLANNING_LOSS",
                                          "EXT500-269": "LOGICAL_PLAN_INCOMPLETE", "EXT500-325": "LOGICAL_PLAN_INCOMPLETE"}[cid]
                                         if digest == baseline_sha else None),
                       "applies_to_current_input": digest == baseline_sha,
                       "baseline_observation": note, "evidence_path": path,
                       "reason": "manually inspected identical typed plan" if digest == baseline_sha else
                       "current input absent or changed; do not reuse BEFORE observation as AFTER finding"})
    return {"audit_version": 2, "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input": str(input_path), "input_snapshot": snapshot, "gold_provenance": provenance,
            "scope": {"offline_only": True, "new_gemma_calls": 0,
                      "production_imports": False, "audited_schema": "logical-primitive-v2",
                      "v2_foreach_primitive": False, "live_semantic_program_foreach": True,
                      "live_program_assessed": False, "backend_execution_assessed": False},
            "manual_audit": manual,
            "summary": {"total_ids": len(results), "gold_patterns": len(patterns), "full_pass": 0,
                        "pending_audit_ids": len(cases) - len(results), "missing_log_ids": eligibility["MISSING_LOG"],
                        "source_artifact_checked_turns": sum(r["source_artifact_checked_turns"] for r in results),
                        "source_artifact_conflict_turns": sum(r["source_artifact_conflict_turns"] for r in results),
                        "logical_trace_turns": sum(r["logical_turns"] for r in results),
                        "definite_semantic_mismatch": counts["SEMANTIC_MISMATCH"],
                        "review_needed_only": counts["REVIEW_NEEDED"],
                        "cases_with_unverified_invariants": sum(bool(r["unverified_invariants"]) for r in results),
                        "cases_with_pipeline_failure": sum(any(f["status"] == "PIPELINE_FAILURE" for f in r["findings"]) for r in results),
                        "eligibility": dict(eligibility), "all_ids_have_evaluation_record": len(results) == 500,
                        "multiturn_e2e_pass": 0,
                        "finding_counts": dict(Counter(f["code"] for r in results for f in r["findings"])),
                        "definite_finding_counts": dict(Counter(f["code"] for r in results for f in r["findings"] if f["status"] == "SEMANTIC_MISMATCH")),
                        "definite_case_ids_by_failure_class": {category: [r["id"] for r in results if any(
                            f["status"] == "SEMANTIC_MISMATCH" and f["failure_class"] == category for f in r["findings"])]
                            for category in ("SEMANTIC_OMISSION", "SEMANTIC_CONTRADICTION", "LOWERING_PLANNING_LOSS", "LOGICAL_PLAN_INCOMPLETE")},
                        "triage_review_only_observed_ids": [r["id"] for r in results if r["status"] == "REVIEW_NEEDED" and r["parsed_turns"]],
                        "triage_review_only_complete_ids": [r["id"] for r in results if r["status"] == "REVIEW_NEEDED" and r["evaluation_eligibility"] == "COMPLETE_TYPED_LOG"],
                        "triage_pipeline_failure_ids": [r["id"] for r in results if any(f["status"] == "PIPELINE_FAILURE" for f in r["findings"])],
                        "review_finding_counts": dict(Counter(f["code"] for r in results for f in r["findings"] if f["status"] == "REVIEW_NEEDED")),
                        "review_case_ids_by_code": {code: [r["id"] for r in results if any(
                            f["code"] == code and f["status"] == "REVIEW_NEEDED" for f in r["findings"])]
                            for code in sorted({f["code"] for r in results for f in r["findings"] if f["status"] == "REVIEW_NEEDED"})},
                        "pattern_counts": {p: dict(Counter(r["status"] for r in results if r["pattern_id"] == p)) for p in patterns}},
            "cases": results}


class AuditSelfTests(unittest.TestCase):
    """Anti-false-pass tests of the auditor, not a production/runtime QA claim."""

    def test_all_125_gold_contracts_apply_to_four_variants(self):
        cases, patterns, _ = load_gold()
        for case in cases:
            with self.subTest(id=case["id"]):
                result = audit_case(case, patterns[case["pattern_id"]])
                self.assertEqual(result["status"], "REVIEW_NEEDED")
                self.assertEqual(result["evaluation_eligibility"], "MISSING_LOG")
                self.assertEqual(set(result["dimensions"]), set(DIMENSIONS))
                self.assertFalse(result["full_pass"])

    def test_output_names_cannot_supply_operations(self):
        forged = {"node_id": "x", "op": "Retrieve", "arguments": {
            "metric": "price", "aggregation": "mean", "operation": "hhi",
            "requested_outputs": ["HHI mean ForEach include_all_ties"]}}
        for step in ("Aggregate(mean)", "Calculate(HHI)", "ForEach(Retrieve)"):
            self.assertFalse(step_nodes(step, [forged])[0])

    def test_closed_aliases_and_typed_periods(self):
        self.assertTrue(equivalent("average", "mean"))
        self.assertFalse(equivalent("monthly_average_price_name", "mean"))
        self.assertFalse(equivalent("stddev", "population_stddev"))
        self.assertEqual(interval({"kind": "year", "value": 2025}), ("2025-01-01", "2025-12-31"))
        self.assertIsNone(interval({"start": "2025-12-31", "end": "2025-01-01"}))
        self.assertEqual(entity_tokens("니켈, 구리"), {"니켈", "구리"})
        self.assertTrue(same_period_union([("2025-01-01", "2025-06-30"),
                                          ("2025-07-01", "2025-12-31")], ("2025-01-01", "2025-12-31")))
        self.assertFalse(same_period_union([("2025-01-01", "2025-06-30"),
                                           ("2025-07-02", "2025-12-31")], ("2025-01-01", "2025-12-31")))

    def test_metric_distinctions(self):
        self.assertFalse(metric_evidence({"metric": "import_value"}, "import_weight"))
        self.assertFalse(metric_evidence({"metric": "price", "requested_outputs": ["inventory"]}, "inventory"))
        self.assertFalse(metric_evidence({"metric": "import_value", "flow": "export"}, "import_value"))
        self.assertTrue(metric_evidence({"metric": "import_value", "flow": "export"}, "export_value"))

    def test_incremental_log_and_duplicate_failure_not_cherry_picked(self):
        path = Mock()
        path.open.return_value = io.BytesIO(b'{"id":"x","status":"ok"}\n{"id":"x","status":"fail"}\n{bad}\n{"id":')
        rows, diagnostics = read_snapshot(path)
        self.assertEqual(rows["x"][1]["status"], "fail")
        self.assertEqual(len(diagnostics["duplicates"]), 1)
        self.assertEqual(len(diagnostics["errors"]), 1)
        self.assertGreater(diagnostics["pending_tail_bytes"], 0)
        path.open.return_value = io.BytesIO(b'{"id":"x"}\n{"id":"y"}\n')
        self.assertEqual(set(read_snapshot(path)[0]), {"x", "y"})

    def test_equivalent_aggregate_composition(self):
        node = {"op": "Aggregate", "arguments": {"aggregation": "hhi"}}
        self.assertEqual(step_nodes("Calculate(HHI)", [node])[0], [node])

    def test_explicit_price_field_and_ties_are_definite_omissions_all_variants(self):
        cases, patterns, _ = load_gold()
        for c in cases[:4]:
            with self.subTest(id=c["id"]):
                b = c["semantic_requirement"]["parameter_bindings"]
                selection = {"mode": "argmax", "field": "value"}
                req = {"requirement_id": "r", "metric": "price", "entity": {"value": b["m"]},
                       "time_range": {"kind": "year", "value": b["y"]}, "selection": selection}
                plan = {"request_class": "DATA_QUERY", "requirements": [req],
                        "requested_outputs": [{"name": "all_ties_high_price", "source_node": "s", "fields": ["date", "value"]}]}
                logical = {"schema_version": "logical-primitive-v2", "roots": ["s"], "nodes": [
                    {"node_id": "r", "op": "Retrieve", "arguments": {"metric": "price", "time_range": req["time_range"]}},
                    {"node_id": "s", "op": "Select", "arguments": selection, "inputs": [{"node_id": "r"}]}]}
                row = {"pattern_id": c["pattern_id"], "turns": [{"turn": 1, "question": c["turns"][0]["question"],
                       "semantic_plan": plan, "logical_program": logical}]}
                result = audit_case(c, patterns[c["pattern_id"]], row)
                codes = {f["code"] for f in result["findings"] if f["status"] == "SEMANTIC_MISMATCH"}
                self.assertIn("PRICE_FIELD_UNSPECIFIED", codes)
                self.assertIn("EXPLICIT_TIE_POLICY_ABSENT", codes)
                selection.update(field="high_price", include_ties=True)
                result = audit_case(c, patterns[c["pattern_id"]], row)
                self.assertEqual(result["status"], "REVIEW_NEEDED")
                self.assertFalse(result["full_pass"])
                # An unknown typed synonym must not be declared a definite omission.
                selection.update(field="intraday_upper_quote")
                result = audit_case(c, patterns[c["pattern_id"]], row)
                field_findings = [f for f in result["findings"] if f["code"] == "PRICE_FIELD_UNSPECIFIED"]
                self.assertEqual(field_findings[0]["status"], "REVIEW_NEEDED")

    def test_semantic_ties_lost_in_dag_is_separate_from_omission(self):
        cases, patterns, _ = load_gold()
        c = cases[0]
        row = {"pattern_id": c["pattern_id"], "turns": [{"turn": 1, "question": c["turns"][0]["question"],
               "semantic_plan": {"request_class": "DATA_QUERY", "requirements": [], "presentation": {"handle_ties": "include_all"}},
               "logical_program": {"schema_version": "logical-primitive-v2", "nodes": [], "roots": []}}]}
        result = audit_case(c, patterns[c["pattern_id"]], row)
        finding = next(f for f in result["findings"] if f["code"] == "TIE_POLICY_LOST_IN_DAG")
        self.assertEqual(finding["failure_class"], "LOWERING_PLANNING_LOSS")

    def test_null_is_not_zero_and_requested_dead_root_is_definite(self):
        cases, patterns, _ = load_gold()
        c = cases[4]
        row = {"pattern_id": c["pattern_id"], "turns": [{"turn": 1, "question": c["turns"][0]["question"],
               "semantic_plan": {"request_class": "DATA_QUERY", "requirements": [{
                   "requirement_id": "r", "metric": "price", "constraints": [{"exclude_zero": True}]}]},
               "logical_program": {"schema_version": "logical-primitive-v2", "roots": ["r"], "nodes": [
                   {"node_id": "r", "op": "Retrieve", "arguments": {"metric": "price"}},
                   {"node_id": "s", "op": "Select", "requested": True,
                    "arguments": {"mode": "argmin"}, "inputs": [{"node_id": "r"}]}]}}]}
        result = audit_case(c, patterns[c["pattern_id"]], row)
        for code, category in (("NULL_ZERO_POLICY_CONFLATION", "SEMANTIC_CONTRADICTION"),
                               ("REQUESTED_NODE_NOT_REACHABLE", "LOGICAL_PLAN_INCOMPLETE")):
            finding = next(f for f in result["findings"] if f["code"] == code)
            self.assertEqual(finding["status"], "SEMANTIC_MISMATCH")
            self.assertEqual(finding["failure_class"], category)

    def test_name_only_and_dead_computation_are_flagged(self):
        cases, patterns, _ = load_gold()
        c = cases[8]  # PAT-003 V1: mean plus observation count
        row = {"id": c["id"], "pattern_id": c["pattern_id"], "turns": [{
            "turn": 1, "question": c["turns"][0]["question"],
            "semantic_plan": {"request_class": "DATA_QUERY", "requirements": [{
                "metric": "price", "entity": {"value": "니켈"}, "aggregation": "mean",
                "time_range": {"kind": "year", "value": 2025}}],
                "requested_outputs": [{"name": "monthly_mean_and_valid_count"}]},
            "logical_program": {"schema_version": "logical-primitive-v2", "roots": ["r"], "nodes": [
                {"node_id": "r", "op": "Retrieve", "arguments": {"metric": "price"}},
                {"node_id": "dead", "op": "Aggregate", "arguments": {"aggregation": "count"}, "inputs": [{"node_id": "r"}]}]}}]}
        result = audit_case(c, patterns[c["pattern_id"]], row)
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("DEAD_NODE", codes)
        self.assertIn("VALID_OBSERVATION_COUNT_NOT_COMPUTED", codes)
        self.assertIn("OUTPUT_LINEAGE_UNESTABLISHED", codes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AuditSelfTests))
        return 0 if result.wasSuccessful() else 1
    if not args.input or not args.output:
        parser.error("--input and --output are required unless --self-test")
    protected = {args.input.resolve(), Path(__file__).resolve(),
                 (HERE / "qa_build_order2_4_500.json").resolve(), (HERE / "qa_order2_4_patterns.tsv").resolve()}
    if args.output.resolve() in protected:
        parser.error("output must not overwrite input, Gold or auditor")
    report = build_report(args.input)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report["summary"].items() if k not in {
        "finding_counts", "pattern_counts", "definite_finding_counts", "review_finding_counts", "review_case_ids_by_code",
        "definite_case_ids_by_failure_class", "triage_review_only_observed_ids", "triage_review_only_complete_ids",
        "triage_pipeline_failure_ids"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
