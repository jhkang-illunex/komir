# -*- coding: utf-8 -*-
"""v13.pptx의 모든 report_gen 응답을 원본 KOMIS 입력에서 처음부터 다시
만든다(2026-09-13 검수 정정판). v12용 스크립트는 가격 4종·광물종합지수·
시장/수급동향지표를 정적 덤프(8/17~8/27)에서 만들었는데, 같은 날 라이브
재조회로 캐시만 교체하고 이 스크립트엔 그 경로를 안 넣어 "재현 실행 시
9개 항목이 stale 값으로 되돌아가는" 재현 불일치가 있었다(검수에서 발견).
이제 evidence 폴더의 live_*.json(komis.or.kr 라이브 원본 그대로)을
직접 읽어 같은 절차로 만든다 — 캐시를 손으로 덧대는 단계가 없다."""
import copy
import json
import sys

sys.path.insert(0, "inhouse/report_gen")
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402

D = "income_data/komis/"
LIVE = "documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/"
svc = AnalysisSummaryService(None, llm=None)
out: dict = {}


def load(name):
    return json.load(open(D + name, encoding="utf-8"))


def live(name):
    return json.load(open(LIVE + name + ".json", encoding="utf-8"))


def run(key, page_id, **kwargs):
    req = AnalysisSummaryRequest(request_id=f"v13-{key}", page_id=page_id, **kwargs)
    resp = svc.analyze(req)
    out[key] = json.loads(resp.model_dump_json())
    print(key, "ok")


def price_pair(live_name, page_id, key_prefix, mineral, compare):
    """live_price_*.json은 비교광종을 붙여 한 번에 받은 원본이라 baseline은
    compareMnrl/cmpMap을 떼고, 비교 슬라이드는 그대로 넣는다."""
    full = live(live_name)
    base = copy.deepcopy(full)
    base["data"].pop("compareMnrl", None)
    base["dataAvg"].pop("cmpMap", None)
    run(f"{key_prefix}_baseline", page_id, komis_response=base, mineral_name=mineral, mineral=mineral)
    run(
        f"{key_prefix}_cmp", page_id, komis_response=full, mineral_name=mineral, mineral=mineral,
        compare_mineral_name=compare, compare_mineral=compare,
    )


# ── 가격 4종(라이브 2026-09-10 조회, 우라늄은 KOMIS 최신일 8-31) ──
price_pair("live_price_base", "price_base_metals", "price_base", "동", "니켈")
price_pair("live_price_minor", "price_minor_metals", "price_minor", "코발트", "몰리브덴")
price_pair("live_price_iron", "price_iron_energy", "price_iron", "우라늄", "유연탄")
price_pair("live_price_other", "price_other", "price_other", "흑연", "금")

# ── 광물전망지표 3종(라이브) ──
run("indicator_composite", "indicator_composite", komis_response=live("live_composite"))
run("indicator_market", "indicator_market", komis_response=live("live_market"), mineral_name="동", mineral="동")
run("indicator_supply_baseline", "indicator_supply", komis_response=live("live_supply"), mineral_name="동", mineral="동")
run(
    "indicator_supply_aux", "indicator_supply", komis_response=live("live_supply"),
    komis_snapshot_response=live("live_supply_panel"), mineral_name="동", mineral="동",
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

scope_primary = json.load(open("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/cu_map_korea_scope.json", encoding="utf-8"))
scope_history = [json.load(open(f"documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/cu_map_korea_scope_{y}.json", encoding="utf-8")) for y in years[1:]]
run(
    "map_korea_scope", "map_korea", komis_response=scope_primary, komis_history_responses=scope_history,
    mineral_name="동", mttr_flow_name="기초금속",
)

# ── map_global: baseline(수입, full)/수출옵션(full)/수출입국가필터 ──
d26 = json.load(open("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/li_2026_map_global.json", encoding="utf-8"))
d25 = json.load(open("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/li_2025_map_global.json", encoding="utf-8"))
run(
    "map_global_import_full", "map_global", mineral="MNRL0001", mineral_name="리튬",
    komis_response=d26["list_data"], komis_bar_chart_response=d26["bar_chart"],
    komis_route_share_response=d26["nation_map"], komis_history_responses=[d25["list_data"]],
)

export_raw = json.load(open("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/li_2026_map_global_export_full.json", encoding="utf-8"))
run(
    "map_global_export_full", "map_global", mineral="MNRL0001", mineral_name="리튬",
    komis_response=export_raw["list_data"], komis_bar_chart_response=export_raw["bar_chart"],
    komis_route_share_response=export_raw["nation_map"],
)

kr_id_raw = json.load(open("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/raw/li_korea_indonesia_filter.json", encoding="utf-8"))
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

json.dump(out, open("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/v13_sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("saved", len(out), "entries")
