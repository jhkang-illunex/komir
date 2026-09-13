# -*- coding: utf-8 -*-
"""v12.pptx의 모든 report_gen 응답을 원본 KOMIS raw 입력에서 처음부터
다시 만든다 — D-10(조회기간 표기) 반영 후 재조회. 이전엔 여러 세션에
걸쳐 조각조각 fetch한 결과를 캐시(v11_remaining_sources.json)에 계속
누적/재사용했는데, 코드가 바뀌면(오늘의 트림 규칙·D-10 등) 캐시가
stale해지는 문제가 반복됐다 — 이 스크립트 하나로 항상 처음부터 다시
만들어 stale 캐시 문제를 구조적으로 없앤다."""
import json
import sys

sys.path.insert(0, "inhouse/report_gen")
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402

sys.path.insert(0, "inhouse/streamlit_demo")
import komis_fetch  # noqa: E402

D = "income_data/komis/"
svc = AnalysisSummaryService(None, llm=None)
out: dict = {}


def load(name):
    return json.load(open(D + name, encoding="utf-8"))


def run(key, page_id, **kwargs):
    req = AnalysisSummaryRequest(request_id=f"v12-{key}", page_id=page_id, **kwargs)
    resp = svc.analyze(req)
    out[key] = json.loads(resp.model_dump_json())
    print(key, "ok")


# ── price_base_metals: 동 baseline + 동 vs 니켈 ──
d01 = load("komis_01_base_metals.json")


def r01(key):
    return next(r["response"] for r in d01["results"] if r["key"] == key)


cu = r01("동|LME CASH|DAY")
ni = r01("니켈|LME CASH|DAY")
run("price_base_baseline", "price_base_metals", komis_response=cu, mineral_name="동", mineral="동")
combined = json.loads(json.dumps(cu))
combined["data"]["compareMnrl"] = ni["data"]["defaultMnrl"]
combined["dataAvg"]["cmpMap"] = {"INFO": ni["dataAvg"]["INFO"]}
run(
    "price_base_cmp", "price_base_metals", komis_response=combined, mineral_name="동", mineral="동",
    compare_mineral_name="니켈", compare_mineral="니켈",
)

# ── price_minor_metals: 코발트 baseline + 코발트 vs 몰리브덴 ──
d02 = load("komis_02_minor_metals.json")


def r02(key):
    return next(r["response"] for r in d02["results"] if r["key"] == key)


co = r02("코발트|Cobalt Metal|99.8|DAY")
mo = r02("몰리브덴|Ferro-molybdenum|60|DAY")
run("price_minor_baseline", "price_minor_metals", komis_response=co, mineral_name="코발트", mineral="코발트")
combined2 = json.loads(json.dumps(co))
combined2["data"]["compareMnrl"] = mo["data"]["defaultMnrl"]
combined2["dataAvg"]["cmpMap"] = {"INFO": mo["dataAvg"]["INFO"]}
run(
    "price_minor_cmp", "price_minor_metals", komis_response=combined2, mineral_name="코발트", mineral="코발트",
    compare_mineral_name="몰리브덴", compare_mineral="몰리브덴",
)

# ── price_iron_energy: 우라늄 baseline + 우라늄 vs 유연탄 ──
phase2 = json.load(open(
    "documents/산출물/2026-W35_0824-0830/report_gen_KOMIS라이브재검증_Phase2_260829_evidence/"
    "collected_iron_other_day_raw_260829.json",
    encoding="utf-8",
))
uranium = next(x["response"] for x in phase2 if x["mineral_name"] == "우라늄")
coal = next(
    x["response"] for x in phase2
    if x["mineral_name"] == "유연탄" and ((x["response"]["dataAvg"]["INFO"]).get("prcCrtr") or "").strip().startswith("Q:5500")
)
run("price_iron_baseline", "price_iron_energy", komis_response=uranium, mineral_name="우라늄", mineral="우라늄")
combined3 = json.loads(json.dumps(uranium))
combined3["data"]["compareMnrl"] = coal["data"]["defaultMnrl"]
combined3["dataAvg"]["cmpMap"] = {"INFO": coal["dataAvg"]["INFO"]}
run(
    "price_iron_cmp", "price_iron_energy", komis_response=combined3, mineral_name="우라늄", mineral="우라늄",
    compare_mineral_name="유연탄", compare_mineral="유연탄",
)

# ── price_other: 흑연 baseline + 흑연 vs 금 ──
graphite = next(x["response"] for x in phase2 if x["mineral_name"] == "흑연")
gold = next(x["response"] for x in phase2 if x["mineral_name"] == "금")
run("price_other_baseline", "price_other", komis_response=graphite, mineral_name="흑연", mineral="흑연")
combined4 = json.loads(json.dumps(graphite))
combined4["data"]["compareMnrl"] = gold["data"]["defaultMnrl"]
combined4["dataAvg"]["cmpMap"] = {"INFO": gold["dataAvg"]["INFO"]}
run(
    "price_other_cmp", "price_other", komis_response=combined4, mineral_name="흑연", mineral="흑연",
    compare_mineral_name="금", compare_mineral="금",
)

# ── indicator_composite ──
d03 = load("komis_03_mineral_index.json")
comp = next(r["response"] for r in d03["results"] if r["key"] == "광물종합지수|1개월")
run("indicator_composite", "indicator_composite", komis_response=comp)

# ── indicator_market: 동 ──
d04 = load("komis_04_market_trend.json")
market_cu = next(r["response"] for r in d04["results"] if r["key"] == "동")
run("indicator_market", "indicator_market", komis_response=market_cu, mineral_name="동", mineral="동")

# ── indicator_supply: 동 baseline + aux(패널차트) ──
d05 = load("komis_05_supply_trend.json")


def r05(key):
    return next(r["response"] for r in d05["results"] if r["key"] == key)


supply_primary = r05("동|월별지표")
supply_snapshot = r05("동|패널차트|202607")
run("indicator_supply_baseline", "indicator_supply", komis_response=supply_primary, mineral_name="동", mineral="동")
run(
    "indicator_supply_aux", "indicator_supply", komis_response=supply_primary,
    komis_snapshot_response=supply_snapshot, mineral_name="동", mineral="동",
)

# ── map_korea: baseline/국가필터/생산품유형필터, 전부 5개년 히스토리 포함 ──
d06 = load("komis_06_supply_map_korea.json")


def r06(key):
    return json.loads(json.dumps(next(x["response"] for x in d06["results"] if x["key"] == key)))


years = ["2026", "2025", "2024", "2023", "2022"]
mk_by_year = {y: r06(f"동|수입|{y}|list") for y in years}
run(
    "map_korea_baseline", "map_korea", komis_response=mk_by_year["2026"],
    komis_history_responses=[mk_by_year[y] for y in years[1:]], mineral_name="동",
)

filtered = {}
for y, raw in mk_by_year.items():
    cl = dict(next(r for r in raw["list"] if r["ntnCd"] == "CL"))
    cl["sumIncmAmt"] = cl["incmAmt"]
    cl["sumExpAmt"] = cl["expAmt"]
    f = dict(raw)
    f["list"] = [cl]
    f["sumIncmAmt"] = cl["incmAmt"]
    f["srchNtnCd"] = "CL"
    filtered[y] = f
run(
    "map_korea_country_filter", "map_korea", komis_response=filtered["2026"],
    komis_history_responses=[filtered[y] for y in years[1:]], mineral_name="동",
)
out["_country_filter_name"] = "칠레"

scope_primary = json.load(open("/tmp/cu_map_korea_scope.json", encoding="utf-8"))
scope_history = [json.load(open(f"/tmp/cu_map_korea_scope_{y}.json", encoding="utf-8")) for y in years[1:]]
run(
    "map_korea_scope", "map_korea", komis_response=scope_primary, komis_history_responses=scope_history,
    mineral_name="동", mttr_flow_name="기초금속",
)

# ── map_global: baseline(수입, full)/수출옵션(full)/수출입국가필터 ──
d26 = json.load(open("/tmp/li_2026_map_global.json", encoding="utf-8"))
d25 = json.load(open("/tmp/li_2025_map_global.json", encoding="utf-8"))
run(
    "map_global_import_full", "map_global", mineral="MNRL0001", mineral_name="리튬",
    komis_response=d26["list_data"], komis_bar_chart_response=d26["bar_chart"],
    komis_route_share_response=d26["nation_map"], komis_history_responses=[d25["list_data"]],
)

export_raw = json.load(open("/tmp/li_2026_map_global_export_full.json", encoding="utf-8"))
run(
    "map_global_export_full", "map_global", mineral="MNRL0001", mineral_name="리튬",
    komis_response=export_raw["list_data"], komis_bar_chart_response=export_raw["bar_chart"],
    komis_route_share_response=export_raw["nation_map"],
)

kr_id_raw = json.load(open("/tmp/li_korea_indonesia_filter.json", encoding="utf-8"))
run("map_global_kr_id_filter", "map_global", mineral="MNRL0001", mineral_name="리튬", komis_response=kr_id_raw["list_data"])

# ── map_mineral: baseline(매장량+교차비교 기본포함)/생산량검색 ──
d08 = load("komis_08_mineral_map.json")


def r08(key):
    return next(r["response"] for r in d08["results"] if r["key"] == key)


run(
    "map_mineral_baseline_full", "map_mineral", mineral="MNRL0008", mineral_name="동", measure="reserves",
    start_year=2021, end_year=2025, komis_response=r08("동|매장량|chart"), komis_share_response=r08("동|매장량|table"),
    komis_snapshot_response=r08("동|생산량|map"),
)
run(
    "map_mineral_production", "map_mineral", mineral="MNRL0008", mineral_name="동", measure="production",
    start_year=2021, end_year=2025, komis_response=r08("동|생산량|chart"), komis_share_response=r08("동|생산량|table"),
)

json.dump(out, open("/tmp/v11_remaining_sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("saved", len(out), "entries")
