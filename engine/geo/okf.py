# -*- coding: utf-8 -*-
"""OKF(Open Knowledge Format, Google Cloud v0.1) 익스포트 — 비파괴 파일럿.
기존 정본(parquet 스토어: events/index/manifest)+config를 읽어 $GEO_DATA/okf/ 아래
'마크다운 + YAML 프론트매터' 번들로 방출한다. 정본(parquet/DuckDB)은 건드리지 않는다.

OKF 규약: 개념ID = 파일경로, 유일 필수 필드 = type, 본문 관례 섹션 = # Schema/# Examples/# Citations.
매핑: source-document(원문) · geo-event(이벤트) · geo-issue(월별 이슈) · geo-index(광종 지수) · metric-definition(지수 공식).
"""
import re
from . import config as C, store

try:
    import yaml
except ImportError:
    yaml = None

OKF_VERSION = "0.1"


def _slug(s):
    return re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", str(s)).strip("-")[:64] or "untitled"


def _doc(typ, meta, body=""):
    """OKF 문서: type만 필수. None/빈값 필드는 생략."""
    fm = {"type": typ}
    fm.update({k: v for k, v in meta.items() if v is not None and v != "" and not (isinstance(v, float) and v != v)})
    if yaml:
        front = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    else:
        # 폴백(PyYAML 부재): LLM 유래 값의 개행/따옴표/'---'가 프론트매터를 깨뜨리지 않게
        # JSON 문자열 인용으로 이스케이프(JSON은 YAML 부분집합이라 유효).
        import json as _json
        def _v(v):
            if isinstance(v, (int, float, bool)): return str(v).lower() if isinstance(v, bool) else str(v)
            if isinstance(v, list): return "[" + ", ".join(_json.dumps(str(x), ensure_ascii=False) for x in v) + "]"
            return _json.dumps(str(v), ensure_ascii=False)
        front = "\n".join(f"{k}: {_v(v)}" for k, v in fm.items())
    return f"---\n{front}\n---\n\n{body.strip()}\n"


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def export(root=None):
    """정본 → OKF 번들. 반환: 문서 종류별 개수.
    재생성 전 기존 서브트리를 비워 stale 문서(삭제/재계산된 이벤트·이슈) 잔존 방지."""
    import shutil
    root = root or (C.GEO_DATA / "okf")
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("metrics", "sources", "events", "issues", "index"):
        shutil.rmtree(root / sub, ignore_errors=True)
    ev = store.load_events()
    idx = store._read(C.INDEX)
    man = store.load_manifest()
    n = {"metric": 0, "sources": 0, "events": 0, "issues": 0, "index": 0}

    # 0) metric-definition (지수 공식 = index.yaml + sources.yaml)
    icfg, scfg = C.load_yaml("index.yaml"), C.load_yaml("sources.yaml")
    ydump = (lambda d: yaml.safe_dump(d, allow_unicode=True, sort_keys=False)) if yaml else (lambda d: str(d))
    body = ("# Schema\n\n광종별 지정학 이벤트를 감쇠·방향가중·발행처신뢰도·공급집중으로 결합해 "
            "0~100 위기지수를 산출한다.\n\n## index.yaml\n```yaml\n" + ydump(icfg) +
            "```\n\n## sources.yaml (발행처 신뢰도·가중)\n```yaml\n" + ydump(scfg) + "```\n")
    _write(root / "metrics" / "geo-index.md", _doc("metric-definition", {
        "title": "지정학 위기 지수 (geo-index)",
        "description": "광종별 지정학 이벤트 → 감쇠·가중·정규화 0~100 지수",
        "okf_version": OKF_VERSION, "tags": ["geopolitics", "index", "critical-minerals"]}, body))
    n["metric"] = 1

    # 1) source-document (manifest)
    for _, r in man.iterrows():
        did = str(r.get("doc_id"))
        _write(root / "sources" / _slug(r.get("source", "ETC")) / f"{did}.md",
               _doc("source-document", {
                   "title": r.get("orig_name"), "description": f"{r.get('source')} · {r.get('category')}",
                   "resource": r.get("archive_path"), "timestamp": r.get("pub_date"),
                   "doc_id": did, "fmt": r.get("fmt"), "commodity_hint": r.get("commodity_hint"),
                   "n_chars": int(r.get("n_chars") or 0), "status": r.get("status"),
                   "tags": ["source-document", r.get("source")]},
                   f"# Examples\n\n- 원문 아카이브: `{r.get('archive_path')}`\n- 발행처: {r.get('source')}\n"))
        n["sources"] += 1

    # 2) geo-event (이벤트 1건 = OKF 문서 1개)
    manmap = man.set_index("doc_id")[["source", "orig_name"]].to_dict("index") if len(man) else {}
    for _, e in ev.iterrows():
        src = manmap.get(e["doc_id"], {})
        quote = str(e.get("evidence_quote", "") or "")
        body = (f"{quote}\n\n# Citations\n\n"
                f"- doc: `{e['doc_id']}` — {src.get('source', '?')} · {src.get('orig_name', '?')}\n"
                f"- extractor: {e.get('extractor')} / {e.get('provider', '')} {e.get('model', '')}\n")
        _write(root / "events" / str(e["commodity"]) / f"{_slug(e['event_id'])}.md",
               _doc("geo-event", {
                   "title": f"{e['commodity']} · {e.get('event_type')}",
                   "description": (quote or str(e.get("event_type")))[:120],
                   "timestamp": e.get("obs_date"),
                   "commodity": e["commodity"], "country": e.get("country"),
                   "event_type": e.get("event_type"), "direction": e.get("direction"),
                   "target": e.get("target"),
                   "severity": float(e.get("severity") or 0), "confidence": float(e.get("confidence") or 0),
                   "doc_id": e["doc_id"], "event_id": e["event_id"],
                   "tags": ["geo-event", str(e["commodity"]), str(e.get("event_type"))]}, body))
        n["events"] += 1

    # 이벤트에 발행처/원문명 결합(이슈 표에 사용)
    evm = ev.merge(man[["doc_id", "source", "orig_name"]], on="doc_id", how="left") if len(ev) else ev
    if len(evm):
        evm["ym"] = evm["obs_date"].astype(str).str.slice(0, 7)

    # 3) geo-issue (월별) — 기존 wiki를 OKF로 승격
    idx_m = idx[idx["freq"] == "M"] if len(idx) else idx
    for _, r in idx_m.iterrows():
        c = r["commodity"]; ym = str(r["period"])[:7]
        rows = evm[(evm["commodity"] == c) & (evm["ym"] == ym)] if len(evm) else evm
        lines = [f"# {c} 지정학 이슈 — {ym}", "",
                 f"- 월간 지수: **{r['index']:.1f}** (raw {r['raw_score']:.2f}, 이벤트 {int(r['n_events'])}건)", "",
                 "# Examples", ""]
        if len(rows):
            lines += ["| event_type | dir | sev | country | 출처 | 근거 |", "|---|---|---|---|---|---|"]
            for _, e in rows.iterrows():
                q = str(e.get("evidence_quote", ""))[:80].replace("|", "／").replace("\n", " ")
                lines.append(f"| {e['event_type']} | {e['direction']} | {e['severity']:.0f} | "
                             f"{e.get('country') or '-'} | {e.get('source') or '-'}:{str(e.get('orig_name') or '')[:24]} | {q} |")
        else:
            lines.append("_이벤트 없음_")
        _write(root / "issues" / str(c) / f"{ym}.md", _doc("geo-issue", {
            "title": f"{c} 지정학 이슈 {ym}", "description": f"{c} {ym} 월간 지정학 위기지수 {r['index']:.1f}",
            "timestamp": f"{ym}-01", "commodity": c, "period": ym,
            "index_value": float(r["index"]), "n_events": int(r["n_events"]),
            "tags": ["geo-issue", str(c)]}, "\n".join(lines)))
        n["issues"] += 1

    # 4) geo-index (광종별 지수 시계열)
    if len(idx):
        for c, g in idx.sort_values(["commodity", "freq", "period"]).groupby("commodity"):
            lines = [f"# {c} 지정학 위기지수", "", "# Schema", "",
                     "| freq | period | index(0~100) | raw | n_events |", "|---|---|---|---|---|"]
            for _, r in g.iterrows():
                lines.append(f"| {r['freq']} | {str(r['period'])[:10]} | {r['index']:.1f} | {r['raw_score']:.2f} | {int(r['n_events'])} |")
            latest = g.sort_values("period").iloc[-1]
            _write(root / "index" / f"{c}.md", _doc("geo-index", {
                "title": f"{c} 지정학 위기지수", "description": f"{c} 지정학 지수 시계열(최신 {latest['index']:.1f})",
                "commodity": c, "metric": "metrics/geo-index", "latest_index": float(latest["index"]),
                "tags": ["geo-index", str(c)]}, "\n".join(lines)))
            n["index"] += 1

    # 번들 개요(사람용, OKF 문서는 아님)
    total = sum(n.values())
    _write(root / "README.md",
           f"# geo OKF 번들 (v{OKF_VERSION})\n\n정본(parquet/DuckDB)에서 방출한 지정학 지식 번들. "
           f"개념ID=파일경로, 필수 프론트매터=type.\n\n문서 {total}개: "
           + ", ".join(f"{k} {v}" for k, v in n.items()) + "\n\n- `metrics/` 지수 공식 정의\n- `sources/` 원문 문서\n"
           "- `events/<광종>/` 이벤트\n- `issues/<광종>/` 월별 이슈\n- `index/<광종>/` 지수 시계열\n")
    print(f"[okf] {root} → {total}개 문서 ({', '.join(f'{k}={v}' for k, v in n.items())})")
    return n


if __name__ == "__main__":
    export()
