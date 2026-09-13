# -*- coding: utf-8 -*-
"""map_mineral 세계총계 수정(2026-09-13) 회귀검증 — 정적 KOMIS 덤프
(income_data/komis/komis_08_mineral_map.json)의 chart/table 쌍 전부에
대해 실제 AnalysisSummaryService.analyze()를 호출하고, 응답의
current_world_total이 이 스크립트가 원본 JSON에서 **독립적으로**
재계산한 `_TOTAL_`(SU, before1)과 일치하는지 확인한다.

report_gen 자신의 파서(_parse_komis_map_mineral_share_totals)를
재사용하지 않는다 — 정답 계산과 실제 응답 계산이 같은 전처리를 공유하면
안 된다는 이번 세션의 원칙(price 실시간가 검증에서도 적용)."""

import json
import sys
from pathlib import Path

REPORT_GEN_ROOT = Path("/home/nuri/dev/git/ws/mine_ws/komir/inhouse/report_gen")
DUMP_PATH = Path("/home/nuri/dev/git/ws/mine_ws/komir/income_data/komis/komis_08_mineral_map.json")

sys.path.insert(0, str(REPORT_GEN_ROOT))
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    data = json.loads(DUMP_PATH.read_text(encoding="utf-8"))
    results = data["results"]

    charts, shares, snapshot_params = {}, {}, {}
    for r in results:
        ep = r["endpoint"].split("/")[-1]
        parts = r["key"].split("|")
        mineral, measure = parts[0], parts[1]
        rows = (r.get("response") or {}).get("data") or []
        if ep == "getListMapMnrlChartData":
            charts[(mineral, measure)] = (rows, r["params"])
        elif ep == "getListMnrlTablePrdctnBurgudg":
            shares[(mineral, measure)] = rows

    svc = AnalysisSummaryService(None, llm=None)
    checked = 0
    ok = 0
    mismatches = []
    skipped_no_su = 0

    for key, (chart_rows, params) in charts.items():
        mineral, measure = key
        if not chart_rows:
            continue
        share_rows = shares.get(key) or []
        total_row = next((row for row in share_rows if row.get("ntnEngCd") == "SU"), None)
        expected = num(total_row.get("before1")) if total_row else None
        if expected is None or expected <= 0:
            skipped_no_su += 1
            continue

        measure_en = "reserves" if measure == "매장량" else "production"
        req = AnalysisSummaryRequest(
            request_id=f"verify-{mineral}-{measure}",
            page_id="map_mineral",
            mineral=mineral,
            mineral_name=mineral,
            measure=measure_en,
            start_year=int(params["srchDateS"]),
            end_year=int(params["srchDateE"]),
            komis_response={"data": chart_rows},
            komis_share_response={"data": share_rows},
        )
        checked += 1
        try:
            resp = svc.analyze(req)
        except Exception as exc:  # noqa: BLE001
            mismatches.append(f"{mineral}|{measure}: EXCEPTION {exc!r}")
            continue
        actual = next((m.value for m in resp.key_metrics if m.id == "current_world_total"), None)
        tol = max(1.0, expected * 0.005)
        if actual is None or abs(actual - expected) > tol:
            mismatches.append(f"{mineral}|{measure}: expected={expected:,.0f} actual={actual}")
        else:
            ok += 1

    print(f"checked={checked} ok={ok} mismatches={len(mismatches)} skipped(no _TOTAL_)={skipped_no_su}")
    for m in mismatches:
        print(" MISMATCH:", m)
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
