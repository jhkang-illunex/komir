"""Deterministic deployment bootstrap, discovery and smoke validation.

This module is deliberately outside the agent execution path.  It inspects the
environment and existing data contracts, and only applies the application-owned
HistoryStore migration when explicitly requested with ``--migrate``.

Example::

    PYTHONPATH=inhouse/rag_chat:inhouse \
      python -m app.deployment_bootstrap --check \
      --manifest /tmp/deployment_capability_manifest.json

    PYTHONPATH=inhouse/rag_chat:inhouse \
      python -m app.deployment_bootstrap --migrate --smoke-url http://127.0.0.1:8002
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol


HISTORY_COMPONENT = "multihop_history"
HISTORY_VERSION = 1
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_env(name: str, default: Any) -> Any:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must contain JSON: {exc}") from exc


def _safe_identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label} identifier: {value!r}")
    return value


def _split_table(value: str) -> tuple[str, str]:
    parts = value.split(".")
    if len(parts) != 2:
        raise ValueError(f"table must be schema.table: {value!r}")
    return _safe_identifier(parts[0], "schema"), _safe_identifier(parts[1], "table")


class DatabaseInspector(Protocol):
    def close(self) -> None: ...

    def schema_exists(self, schema: str) -> bool: ...

    def table_info(self, schema: str, table: str) -> dict[str, Any] | None: ...

    def migration_version(self, schema: str, component: str) -> int | None: ...

    def entity_values(self, schema: str, table: str) -> set[str]: ...


class PostgresInspector:
    """Read-only deployment inspector; it never creates or alters business tables."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("PG_DSN is required")
        import psycopg2

        self._connection = psycopg2.connect(dsn.replace("postgresql+psycopg2://", "postgresql://", 1))

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())

    def close(self) -> None:
        self._connection.close()

    def schema_exists(self, schema: str) -> bool:
        return self._fetchone(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema,)
        ) is not None

    def table_info(self, schema: str, table: str) -> dict[str, Any] | None:
        columns = self._fetchall(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
            (schema, table),
        )
        if not columns:
            return None
        qualified = f'"{schema}"."{table}"'
        count = self._fetchone(f"SELECT COUNT(*) FROM {qualified}")[0]
        return {"schema": schema, "table": table, "columns": [row[0] for row in columns], "row_count": int(count)}

    def migration_version(self, schema: str, component: str) -> int | None:
        if not self.table_info(schema, "schema_migration"):
            return None
        row = self._fetchone(
            f'SELECT version FROM "{schema}"."schema_migration" WHERE component=%s', (component,)
        )
        return int(row[0]) if row else None

    def entity_values(self, schema: str, table: str) -> set[str]:
        info = self.table_info(schema, table)
        if not info:
            return set()
        columns = set(info["columns"])
        candidates = [name for name in ("mnrknd_unq_cd", "mnrl_nm_ko", "mnrl_nm_en", "commodity_code") if name in columns]
        if not candidates:
            return set()
        qualified = f'"{schema}"."{table}"'
        expressions = ", ".join(f'"{name}"::text' for name in candidates)
        values: set[str] = set()
        for row in self._fetchall(f"SELECT {expressions} FROM {qualified} LIMIT 5000"):
            values.update(str(value).strip() for value in row if value not in (None, ""))
        return values


def _probe_url(url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    if not url:
        return {"available": False, "status": "NOT_CONFIGURED"}
    candidates = [url.rstrip("/") + suffix for suffix in ("/health", "/healthz", "/v1/models", "")]
    errors: list[str] = []
    for candidate in candidates:
        try:
            with urllib.request.urlopen(candidate, timeout=timeout) as response:
                return {"available": 200 <= response.status < 500, "status_code": response.status, "url": candidate}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{candidate}: {type(exc).__name__}")
    return {"available": False, "url": url, "errors": errors}


def _readable_path(path_value: str, patterns: tuple[str, ...]) -> dict[str, Any]:
    path = Path(path_value).expanduser() if path_value else Path()
    result: dict[str, Any] = {"path": str(path), "readable": False, "count": 0, "representative": None}
    if not path_value or not path.is_dir():
        result["status"] = "MISSING"
        return result
    files = sorted(file for pattern in patterns for file in path.rglob(pattern) if file.is_file())
    result["readable"] = os.access(path, os.R_OK)
    result["count"] = len(files)
    if files:
        representative = files[0]
        result["representative"] = str(representative)
        try:
            representative.read_bytes()[:256]
            result["representative_readable"] = True
        except OSError as exc:
            result["representative_readable"] = False
            result["error"] = str(exc)
    result["status"] = (
        "READY" if result["readable"] and result["representative_readable"] else "UNREADABLE"
    ) if files else "EMPTY"
    return result


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.casefold())


def _binding_check(entity_map: Mapping[str, Any], db_values: set[str], paths: Mapping[str, str]) -> dict[str, Any]:
    if not entity_map:
        return {"status": "NOT_CONFIGURED", "mismatches": [], "checked": 0}
    source_tokens: dict[str, set[str]] = {"postgres": {_norm(item) for item in db_values}}
    for source, path_value in paths.items():
        root = Path(path_value).expanduser()
        tokens: set[str] = set()
        if root.is_dir():
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    tokens.add(_norm(item.stem))
        source_tokens[source] = tokens
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for canonical, source_requirements in entity_map.items():
        checked += 1
        for source, aliases in source_requirements.items():
            available = source_tokens.get(source, set())
            if not any(_norm(str(alias)) in available or any(_norm(str(alias)) in token for token in available) for alias in aliases):
                mismatches.append({"entity": canonical, "source": source, "aliases": list(aliases)})
    return {"status": "READY" if not mismatches else "MISMATCH", "mismatches": mismatches, "checked": checked}


def _capability_specs() -> dict[str, dict[str, Any]]:
    default = {
        "trade": {"table": "public.ko_cstm_cmmrc", "columns": ["crtr_ymd", "incm_amt", "incm_weig"], "period_column": "crtr_ymd"},
        "price": {"table": "public.ko_mnrl_prc", "columns": ["crtr_ymd", "cmerc_prc"], "period_column": "crtr_ymd"},
        "production": {"table": "public.ko_rsrc_prdctn_quty", "columns": ["crtr_yr", "prdctn_quty_ton"], "period_column": "crtr_yr"},
        "reserve": {"table": "public.ko_rsrc_prdctn_quty", "columns": ["crtr_yr", "rsrv_quty_ton"], "period_column": "crtr_yr"},
    }
    return _json_env("BOOTSTRAP_CAPABILITIES_JSON", default)


def _discover_capabilities(inspector: DatabaseInspector) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, spec in _capability_specs().items():
        schema, table = _split_table(str(spec["table"]))
        info = inspector.table_info(schema, table)
        required = [str(item) for item in spec.get("columns", [])]
        if not info:
            result[name] = {"available": False, "status": "TABLE_MISSING", "table": spec["table"], "required_columns": required}
            continue
        missing = sorted(set(required) - set(info["columns"]))
        item = {"available": not missing and info["row_count"] > 0, "table": spec["table"], "row_count": info["row_count"], "missing_columns": missing}
        item["status"] = "AVAILABLE" if item["available"] else ("COLUMN_MISSING" if missing else "EMPTY")
        period_column = spec.get("period_column")
        if not missing and period_column in info["columns"] and info["row_count"]:
            qualified = f'"{schema}"."{table}"'
            row = inspector._fetchone(f'SELECT MIN("{period_column}"), MAX("{period_column}") FROM {qualified}') if hasattr(inspector, "_fetchone") else None
            if row:
                item["period"] = {"from": str(row[0]) if row[0] is not None else None, "to": str(row[1]) if row[1] is not None else None}
        result[name] = item
    return result


def _vector_check(inspector: DatabaseInspector | None) -> dict[str, Any]:
    model = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    expected_dim = int(os.environ.get("EMBEDDING_DIMENSION", "384"))
    expected = {
        "model": model,
        "revision": os.environ.get("EMBEDDING_MODEL_REVISION", "unknown"),
        "dimension": expected_dim,
        "preprocessing": os.environ.get("EMBEDDING_PREPROCESSING_VERSION", "e5-prefix-v1"),
        "normalization": os.environ.get("EMBEDDING_NORMALIZATION", "l2"),
    }
    if inspector is None:
        return {"available": False, "status": "DB_UNAVAILABLE", "expected": expected, "compatible": False}
    info = inspector.table_info(os.environ.get("VECTOR_SCHEMA", "mineral_risk"), "doc_chunk")
    if not info or "embedding" not in info["columns"] or not info["row_count"]:
        return {"available": False, "status": "INDEX_MISSING_OR_EMPTY", "expected": expected, "compatible": False}
    observed_path = os.environ.get("VECTOR_INDEX_METADATA_PATH", "")
    observed: dict[str, Any] | None = None
    if observed_path:
        try:
            observed = json.loads(Path(observed_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"available": True, "status": "REINDEX_REQUIRED", "reason": f"metadata unreadable: {exc}", "expected": expected, "compatible": False}
    if not observed:
        return {"available": True, "status": "REINDEX_REQUIRED", "reason": "index metadata missing; dimension alone is insufficient", "expected": expected, "compatible": False, "row_count": info["row_count"]}
    comparable = {key: observed.get(key) for key in expected}
    compatible = comparable == expected
    return {"available": True, "status": "AVAILABLE" if compatible else "REINDEX_REQUIRED", "compatible": compatible, "expected": expected, "observed": comparable, "row_count": info["row_count"]}


def _smoke(url: str) -> dict[str, Any]:
    if not url:
        return {"status": "SKIPPED", "cases": []}
    cases = _json_env("BOOTSTRAP_SMOKE_CASES_JSON", [
        {"id": "structured", "message": "최근 1년간 니켈 가격 추이를 보여줘", "events": ["table", "chart", "done"], "done_fields": ["citations"]},
        {"id": "abstain", "message": "2030년 리튬 실제 월별 가격을 보여줘", "events": ["done"], "done_fields": ["abstained"]},
    ])
    outputs: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        payload = json.dumps({"user_id": f"bootstrap-smoke-{index}", "message": case["message"], "mode": "auto"}).encode()
        request = urllib.request.Request(url.rstrip("/") + "/pubchat", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=float(os.environ.get("BOOTSTRAP_SMOKE_TIMEOUT", "90"))) as response:
                raw = response.read().decode("utf-8", errors="replace")
            events = [line[7:] for line in raw.splitlines() if line.startswith("event: ")]
            payloads: list[dict[str, Any]] = []
            for line in raw.splitlines():
                if line.startswith("data: "):
                    try:
                        payload = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        payloads.append(payload)
            has_done = "done" in events
            expected = set(case.get("events", ["done"]))
            done_payload = next((payload for payload in reversed(payloads) if "done" in payload), {})
            fields_ok = all(field in done_payload for field in case.get("done_fields", ()))
            passed = has_done and expected.issubset(set(events)) and fields_ok
            outputs.append({"id": case["id"], "status": "PASS" if passed else "FAIL", "events": events, "has_done": has_done, "done_fields": sorted(done_payload)})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            outputs.append({"id": case["id"], "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    return {"status": "READY" if all(item["status"] == "PASS" for item in outputs) else "FAIL", "passed": sum(item["status"] == "PASS" for item in outputs), "total": len(outputs), "cases": outputs}


def _apply_history_migration() -> None:
    from rag_core.ragkit.history_context import PostgresHistoryStore

    dsn = os.environ.get("MULTIHOP_HISTORY_DSN") or os.environ.get("PG_DSN", "")
    store = PostgresHistoryStore(dsn, schema=os.environ.get("MULTIHOP_HISTORY_SCHEMA", "ai_chatbot"), ttl_days=int(os.environ.get("MULTIHOP_HISTORY_TTL_DAYS", "30")))
    import asyncio

    asyncio.run(store.ensure_schema())


def run(*, migrate: bool = False, smoke_url: str = "") -> dict[str, Any]:
    manifest: dict[str, Any] = {"environment": {"checked_at": _now(), "application_version": os.environ.get("APPLICATION_VERSION", "unknown")}}
    data_lake = os.environ.get("INGEST_DATA_LAKE_DIR", "").strip()
    pageindex_path = os.environ.get("PAGEINDEX_TREES_DIR", "") or (str(Path(data_lake) / "pageindex_trees") if data_lake else "")
    okf_path = os.environ.get("OKF_DOCUMENTS_DIR", "") or (str(Path(data_lake) / "okf_documents") if data_lake else "")
    required = [item for item in os.environ.get("BOOTSTRAP_REQUIRED_ENV", "PG_DSN,LLM_BASE_URL").split(",") if item]
    missing_env = [item for item in required if not os.environ.get(item, "").strip()]
    manifest["application"] = {"required_environment": required, "missing_environment": missing_env, "status": "READY" if not missing_env else "NOT_READY"}

    inspector: PostgresInspector | None = None
    db: dict[str, Any] = {"available": False, "status": "NOT_READY"}
    dsn = os.environ.get("PG_DSN", "")
    if dsn:
        try:
            inspector = PostgresInspector(dsn)
            schemas = [item for item in os.environ.get("BOOTSTRAP_REQUIRED_SCHEMAS", "mineral_risk,public").split(",") if item]
            schema_state = {schema: inspector.schema_exists(schema) for schema in schemas}
            history_schema = os.environ.get("MULTIHOP_HISTORY_SCHEMA", os.environ.get("CHATBOT_SCHEMA", "ai_chatbot"))
            history_table = inspector.table_info(history_schema, "multihop_semantic_turn")
            version = inspector.migration_version(history_schema, HISTORY_COMPONENT)
            if migrate:
                _apply_history_migration()
                history_table = inspector.table_info(history_schema, "multihop_semantic_turn")
                version = inspector.migration_version(history_schema, HISTORY_COMPONENT)
            db = {"available": True, "status": "READY", "schemas": schema_state, "history_store": {"schema": history_schema, "table": bool(history_table), "migration_version": version, "required_version": HISTORY_VERSION, "status": "READY" if version == HISTORY_VERSION else "MIGRATION_REQUIRED"}, "capabilities": _discover_capabilities(inspector)}
        except Exception as exc:  # noqa: BLE001 - bootstrap must report the root cause
            db = {"available": False, "status": "NOT_READY", "error": f"{type(exc).__name__}: {exc}"}
    manifest["postgresql"] = db
    manifest["pageindex"] = _readable_path(pageindex_path, ("*.tree.json",))
    manifest["okf"] = _readable_path(okf_path, ("*.md",))
    manifest["vector"] = _vector_check(inspector)
    manifest["embedding"] = {"backend": os.environ.get("EMBEDDING_BASE_URL") or "sentence_transformers", "model": os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"), "probe": _probe_url(os.environ.get("EMBEDDING_BASE_URL", "")) if os.environ.get("EMBEDDING_BASE_URL") else {"status": "LOCAL"}}
    manifest["llm"] = {"model": os.environ.get("LLM_MODEL", "unknown"), "probe": _probe_url(os.environ.get("LLM_BASE_URL", ""))}
    manifest["service"] = _probe_url(smoke_url.rstrip("/") + "/healthz") if smoke_url else {"status": "NOT_CONFIGURED"}
    db_values = inspector.entity_values("public", "ai_mnrl_mst") if inspector else set()
    manifest["entity_binding"] = _binding_check(_json_env("BOOTSTRAP_ENTITY_BINDINGS_JSON", {}), db_values, {"pageindex": pageindex_path, "okf": okf_path})
    manifest["smoke_qa"] = _smoke(smoke_url)
    if inspector:
        inspector.close()

    critical = []
    if missing_env or not manifest["postgresql"].get("available"):
        critical.append("application_or_postgresql")
    if manifest["postgresql"].get("schemas") and not all(manifest["postgresql"]["schemas"].values()):
        critical.append("required_schema")
    if manifest["postgresql"].get("history_store", {}).get("migration_version") != HISTORY_VERSION:
        critical.append("history_migration")
    for name in ("pageindex", "okf"):
        if manifest[name].get("status") in {"MISSING", "EMPTY"}:
            critical.append(name)
    if not manifest["llm"]["probe"].get("available", False):
        critical.append("llm")
    degraded = []
    if os.environ.get("EMBEDDING_BASE_URL") and not manifest["embedding"]["probe"].get("available", False):
        (critical if os.environ.get("BOOTSTRAP_REQUIRE_EMBEDDING", "0") == "1" else degraded).append("embedding")
    if smoke_url and not manifest["service"].get("available", False):
        critical.append("service")
    if smoke_url and manifest["smoke_qa"]["status"] == "FAIL" and os.environ.get("BOOTSTRAP_REQUIRE_SMOKE", "0") == "1":
        critical.append("smoke_qa")
    if manifest["vector"].get("status") == "REINDEX_REQUIRED":
        degraded.append("vector_reindex")
    if manifest["entity_binding"].get("status") in {"MISMATCH", "NOT_CONFIGURED"}:
        degraded.append("entity_binding")
    if manifest["smoke_qa"]["status"] in {"FAIL", "SKIPPED"}:
        degraded.append("smoke_qa")
    for name, value in manifest.get("postgresql", {}).get("capabilities", {}).items():
        if not value.get("available"):
            degraded.append(name)
    manifest["overall"] = {"status": "NOT_READY" if critical else ("DEGRADED" if degraded else "READY"), "critical_reasons": critical, "limitations": sorted(set(degraded))}
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deployment bootstrap/capability discovery for komir rag_chat")
    parser.add_argument("--check", action="store_true", help="검사만 수행(기본값)")
    parser.add_argument("--migrate", action="store_true", help="HistoryStore agent-owned migration 적용")
    parser.add_argument("--smoke-url", default=os.environ.get("BOOTSTRAP_SMOKE_URL", ""), help="실행 중 rag_chat base URL")
    parser.add_argument("--manifest", default="deployment_capability_manifest.json", help="manifest 출력 경로")
    args = parser.parse_args(argv)
    manifest = run(migrate=args.migrate, smoke_url=args.smoke_url)
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["overall"], ensure_ascii=False))
    print(f"Manifest: {args.manifest}")
    return 0 if manifest["overall"]["status"] != "NOT_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
