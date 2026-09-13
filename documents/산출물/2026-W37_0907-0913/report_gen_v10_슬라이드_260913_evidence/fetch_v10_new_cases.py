# -*- coding: utf-8 -*-
"""v10용 — 8개 신규 슬라이드(가격4종 비교광종 + 지도3종 옵션변형 4개)의
구조화 데이터(sentences+key_metrics)를 실제 report_gen 서비스 호출로
받아 저장한다. fetch_all_v9.py와 같은 shape으로 저장(build 스크립트가
동일 헬퍼로 읽게)."""
import json
import sys

sys.path.insert(0, "inhouse/report_gen")
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402

D = "income_data/komis/"
SVC = AnalysisSummaryService(None, llm=None)


def load(name):
    return json.load(open(D + name, encoding="utf-8"))


def run(slide_key, page_id, req_dict, extra=None):
    req_dict = dict(req_dict)
    req_dict["page_id"] = page_id
    req = AnalysisSummaryRequest(**req_dict)
    resp = SVC.analyze(req)
    sentences = {sec: [s["text"] for s in vals] for sec, vals in resp.summary.model_dump().items()}
    metrics = [{"id": m.id, "label": m.label, "value": m.value, "unit": m.unit} for m in resp.key_metrics]
    detailed = [{"id": m.id, "label": m.label, "value": m.value, "unit": m.unit} for m in resp.detailed_metrics]
    result = {
        "page_id": page_id,
        "applied_filters": resp.applied_filters,
        "sentences": sentences,
        "key_metrics": metrics,
        "detailed_metrics": detailed,
        "mineral_name": resp.mineral.name if resp.mineral else None,
    }
    if extra:
        result.update(extra)
    return slide_key, result


out = {}

# ── price_* 4종: 비교광종 추가 ──
dump01 = load("komis_01_base_metals.json")
p = [r["response"] for r in dump01["results"] if r["key"] == "아연|LME CASH|DAY"][0]
c = [r["response"] for r in dump01["results"] if r["key"] == "알루미늄|LME CASH|DAY"][0]
combined = json.loads(json.dumps(p))
combined["data"]["compareMnrl"] = c["data"]["defaultMnrl"]
combined["dataAvg"]["cmpMap"] = {"INFO": c["dataAvg"]["INFO"]}
k, v = run("cmp_price_base_metals", "price_base_metals", {
    "komis_response": combined, "mineral_name": "아연", "mineral": "아연",
    "compare_mineral_name": "알루미늄", "compare_mineral": "알루미늄",
})
out[k] = v

dump02 = load("komis_02_minor_metals.json")
p = [r["response"] for r in dump02["results"] if r["key"] == "텅스텐|Tungsten APT|88.5|DAY"][0]
c = [r["response"] for r in dump02["results"] if r["key"] == "몰리브덴|Ferro-molybdenum|60|DAY"][0]
combined = json.loads(json.dumps(p))
combined["data"]["compareMnrl"] = c["data"]["defaultMnrl"]
combined["dataAvg"]["cmpMap"] = {"INFO": c["dataAvg"]["INFO"]}
k, v = run("cmp_price_minor_metals", "price_minor_metals", {
    "komis_response": combined, "mineral_name": "텅스텐", "mineral": "텅스텐",
    "compare_mineral_name": "몰리브덴", "compare_mineral": "몰리브덴",
})
out[k] = v

PHASE2 = (
    "documents/산출물/2026-W35_0824-0830/report_gen_KOMIS라이브재검증_Phase2_260829_evidence/"
    "collected_iron_other_day_raw_260829.json"
)
phase2 = json.load(open(PHASE2, encoding="utf-8"))
p = [x["response"] for x in phase2 if x["mineral_name"] == "우라늄"][0]
c = [x["response"] for x in phase2 if x["mineral_name"] == "유연탄" and ((x["response"]["dataAvg"]["INFO"]).get("prcCrtr") or "").strip().startswith("Q:5500")][0]
combined = json.loads(json.dumps(p))
combined["data"]["compareMnrl"] = c["data"]["defaultMnrl"]
combined["dataAvg"]["cmpMap"] = {"INFO": c["dataAvg"]["INFO"]}
k, v = run("cmp_price_iron_energy", "price_iron_energy", {
    "komis_response": combined, "mineral_name": "우라늄", "mineral": "우라늄",
    "compare_mineral_name": "유연탄", "compare_mineral": "유연탄",
})
out[k] = v

p = [x["response"] for x in phase2 if x["mineral_name"] == "흑연"][0]
c = [x["response"] for x in phase2 if x["mineral_name"] == "금"][0]
combined = json.loads(json.dumps(p))
combined["data"]["compareMnrl"] = c["data"]["defaultMnrl"]
combined["dataAvg"]["cmpMap"] = {"INFO": c["dataAvg"]["INFO"]}
k, v = run("cmp_price_other", "price_other", {
    "komis_response": combined, "mineral_name": "흑연", "mineral": "흑연",
    "compare_mineral_name": "금", "compare_mineral": "금",
})
out[k] = v

# ── map_korea: 국가필터, 생산품유형 범위필터 ──
dump06 = load("komis_06_supply_map_korea.json")
resp = json.loads(json.dumps([r["response"] for r in dump06["results"] if r["key"] == "동|수입|전체기간|list"][0]))
rows = resp["list"]
top = max(rows, key=lambda r: r["incmAmt"])
resp["list"] = [top]
resp["sumIncmAmt"] = top["incmAmt"]
resp["srchNtnCd"] = top["ntnCd"]
k, v = run("map_korea_country_filter", "map_korea", {"komis_response": resp, "mineral_name": "동"})
out[k] = v
out[k]["filter_country"] = top["ntnKornNm"]

resp2 = json.loads(json.dumps([r["response"] for r in dump06["results"] if r["key"] == "코발트|수입|전체기간|list"][0]))
rows2 = resp2["list"]
half = rows2[: max(3, len(rows2) // 2)]
resp2["list"] = half
resp2["sumIncmAmt"] = sum(r["incmAmt"] for r in half)
resp2["srchMttrFlowCd"] = "PRD01"
k, v = run("map_korea_scope_filter", "map_korea", {
    "komis_response": resp2, "mineral_name": "코발트", "mttr_flow_name": "정련품",
})
out[k] = v

# ── map_global: 국가(수출입국가) 옵션 — komis_route_share_response ──
dump07 = load("komis_07_supply_map_global.json")
list_resp = [r["response"] for r in dump07["results"] if r["key"] == "동|수입|전체기간|list"][0]
map_resp = [r["response"] for r in dump07["results"] if r["key"] == "동|수입|전체기간|map"][0]
k, v = run("map_global_route_share", "map_global", {
    "komis_response": list_resp, "mineral_name": "동", "komis_route_share_response": map_resp,
})
out[k] = v

# ── map_mineral: 교차비교(매장량 vs 생산량, komis_snapshot_response) ──
dump08 = load("komis_08_mineral_map.json")
chart = [r["response"] for r in dump08["results"] if r["key"] == "동|매장량|chart"][0]
snap = [r["response"] for r in dump08["results"] if r["key"] == "동|매장량|map"][0]
share = [r["response"] for r in dump08["results"] if r["key"] == "동|매장량|table"][0]
rows = chart["data"]
unit = rows[0].get("cdVal") or ""
k, v = run("map_mineral_cross", "map_mineral", {
    "komis_response": chart, "mineral_name": "동", "mineral": "동",
    "measure": "reserves", "unit": unit,
    "komis_snapshot_response": snap, "komis_share_response": share,
})
out[k] = v

OUT_PATH = "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/v10_new_cases.json"
json.dump(out, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)
print("저장:", OUT_PATH)
for k in out:
    print(k, "->", out[k]["applied_filters"])
