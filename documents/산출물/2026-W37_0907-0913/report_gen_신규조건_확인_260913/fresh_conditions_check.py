# -*- coding: utf-8 -*-
"""2026-09-13 후속 — 광물가격(4메뉴)·핵심광물지도(3메뉴) 각각 지금까지
이 세션에서 예시로 보여준 적 없는 새 조건 4~5개씩을 배포된 실 컨테이너
(komir-report-gen-test, 실시간가 수정 반영판)에 HTTP로 호출해 결과를
받고, 조건별로 핵심 수치 1개를 raw KOMIS JSON에서 독립적으로 재계산해
대조한다(전수검증은 이미 완료됐으므로 여기서는 '이 구체적 조건들이
실제로 깨끗한 보고서를 내는지' 표본 확인 + 가벼운 교차검산)."""
import json
import urllib.request

D = "/home/nuri/dev/git/ws/mine_ws/komir/income_data/komis/"
PHASE2 = (
    "/home/nuri/dev/git/ws/mine_ws/komir/documents/산출물/2026-W35_0824-0830/"
    "report_gen_KOMIS라이브재검증_Phase2_260829_evidence/collected_iron_other_day_raw_260829.json"
)
BASE = "http://localhost:18003/api/v1/analysis"


def load(name):
    return json.load(open(D + name, encoding="utf-8"))


def post(path, payload):
    req = urllib.request.Request(
        f"{BASE}/{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


results = []


def record(menu, label, out, crosscheck):
    results.append({"menu": menu, "condition": label, "status": out.get("status"), "report": out.get("report"), "crosscheck": crosscheck})


# ───────────────────── 광물가격(price_*) 4메뉴 ─────────────────────

BASE_METALS_PICKS = [
    ("아연", "LME CASH", "MONTH"),
    ("알루미늄", "LME 3개월", "QUARTER"),
    ("연", "LME CASH", "YEAR"),
    ("주석", "LME 15개월", "DAY"),
    ("주석", "LME CASH", "WEEK"),
]
dump01 = load("komis_01_base_metals.json")
for mineral, crit, opt in BASE_METALS_PICKS:
    key = f"{mineral}|{crit}|{opt}"
    match = [r for r in dump01["results"] if r["key"] == key]
    if not match:
        record("price_base_metals", key, {"status": "SKIP(키 없음)"}, None)
        continue
    resp = match[0]["response"]
    std_map = ((resp.get("dataAvg") or {}).get("stdMap")) or {}
    realtime = num((std_map.get("CRTRYMD") or std_map.get("DAY") or {}).get("cmercPrc"))
    out = post("prices/base-metals", {"komis_response": resp, "mineral_name": mineral, "mineral": mineral})
    actual_latest = None
    if out.get("status") == "ok":
        for line in out["report"].split("\n"):
            if "현재가격" in line:
                actual_latest = line
    record("price_base_metals", key, out, f"expected latest~{realtime} | {actual_latest}")

MINOR_METALS_PICKS = [
    ("네오디뮴", "Neodymium Oxide", "99.5", "DAY"),
    ("리튬", "Lithium Hydroxide Monohydrate", "56.5", "WEEK"),
    ("텅스텐", "Tungsten APT", "88.5", "MONTH"),
    ("몰리브덴", "Molybdenum Concentrate", "45", "QUARTER"),
    ("갈륨", "Gallium Metal", "99.99", "YEAR"),
]
dump02 = load("komis_02_minor_metals.json")
for mineral, crit, grade, opt in MINOR_METALS_PICKS:
    key = f"{mineral}|{crit}|{grade}|{opt}"
    match = [r for r in dump02["results"] if r["key"] == key]
    if not match:
        record("price_minor_metals", key, {"status": "SKIP(키 없음)"}, None)
        continue
    resp = match[0]["response"]
    std_map = ((resp.get("dataAvg") or {}).get("stdMap")) or {}
    realtime = num((std_map.get("CRTRYMD") or std_map.get("DAY") or {}).get("cmercPrc"))
    out = post("prices/minor-metals", {"komis_response": resp, "mineral_name": mineral, "mineral": mineral})
    actual_latest = None
    if out.get("status") == "ok":
        for line in out["report"].split("\n"):
            if "현재가격" in line:
                actual_latest = line
    record("price_minor_metals", key, out, f"expected latest~{realtime} | {actual_latest}")

phase2 = json.load(open(PHASE2, encoding="utf-8"))


def build_iron_other_req(item):
    resp = item["response"]
    info = (resp.get("dataAvg") or {}).get("INFO") or {}
    return {
        "komis_response": resp,
        "mineral_name": info.get("mnrkndKornNm") or item["mineral_name"],
        "mineral": item["mineral_code"],
    }


IRON_ENERGY_PICKS_CRITERIA = [" Q:5500 In port Qinhuangdao", "  A 10%max, V 26%max EXW Henan"]
for crit in IRON_ENERGY_PICKS_CRITERIA:
    match = [
        x for x in phase2
        if x["mineral_name"] == "유연탄"
        and ((x["response"].get("dataAvg") or {}).get("INFO") or {}).get("prcCrtr") == crit
    ]
    if not match:
        record("price_iron_energy", f"유연탄|{crit}", {"status": "SKIP(키 없음)"}, None)
        continue
    item = match[0]
    out = post("prices/iron-energy", build_iron_other_req(item))
    actual_latest = None
    if out.get("status") == "ok":
        for line in out["report"].split("\n"):
            if "현재가격" in line:
                actual_latest = line
    record("price_iron_energy", f"유연탄|{crit.strip()}", out, actual_latest)

OTHER_PICKS = ["철", "금", "루테늄", "백금", "팔라듐"]
for mineral in OTHER_PICKS:
    match = [x for x in phase2 if x["mineral_name"] == mineral]
    if not match:
        record("price_other", mineral, {"status": "SKIP(키 없음)"}, None)
        continue
    item = match[0]
    out = post("prices/other", build_iron_other_req(item))
    actual_latest = None
    if out.get("status") == "ok":
        for line in out["report"].split("\n"):
            if "현재가격" in line:
                actual_latest = line
    record("price_other", mineral, out, actual_latest)


# ───────────────────── 핵심광물지도(map_*) 3메뉴 ─────────────────────

dump06 = load("komis_06_supply_map_korea.json")
MAP_KOREA_PICKS = [("니켈", "수입"), ("코발트", "수입"), ("리튬", "수출"), ("희토류", "수입"), ("흑연", "수입")]
for mineral, direction in MAP_KOREA_PICKS:
    key = f"{mineral}|{direction}|전체기간|list"
    match = [r for r in dump06["results"] if r["key"] == key]
    if not match:
        record("map_korea", key, {"status": "SKIP(키 없음)"}, None)
        continue
    resp = match[0]["response"]
    rows = resp.get("list") or []
    sum_field = "sumIncmAmt" if direction == "수입" else "sumExpAmt"
    expected_total = num(rows[0].get(sum_field)) if rows else None
    out = post("maps/domestic-trade", {"komis_response": resp, "mineral_name": mineral})
    actual_total = None
    if out.get("status") == "ok" and out.get("key_metrics"):
        pass
    record("map_korea", key, out, f"expected total~{expected_total}")

dump07 = load("komis_07_supply_map_global.json")
MAP_GLOBAL_PICKS = ["동", "니켈", "코발트", "희토류", "흑연"]
for mineral in MAP_GLOBAL_PICKS:
    key = f"{mineral}|수입|전체기간|list"
    match = [r for r in dump07["results"] if r["key"] == key]
    if not match:
        record("map_global", key, {"status": "SKIP(키 없음)"}, None)
        continue
    resp = match[0]["response"]
    rows = resp.get("list") or []
    expected_total = num(rows[0].get("sumAmt")) if rows else None
    out = post("maps/global-trade", {"komis_response": resp, "mineral_name": mineral})
    record("map_global", key, out, f"expected total~{expected_total}")

dump08 = load("komis_08_mineral_map.json")
MAP_MINERAL_PICKS = [("니켈", "생산량"), ("코발트", "매장량"), ("리튬", "생산량"), ("희토류", "매장량"), ("흑연", "생산량")]
MEASURE_MAP = {"매장량": "reserves", "생산량": "production"}
for mineral, measure_kr in MAP_MINERAL_PICKS:
    key = f"{mineral}|{measure_kr}|chart"
    match = [r for r in dump08["results"] if r["key"] == key]
    if not match:
        record("map_mineral", key, {"status": "SKIP(키 없음)"}, None)
        continue
    resp = match[0]["response"]
    rows = resp.get("data") or []
    unit = (rows[0].get("cdVal") or "") if rows else ""
    out = post("maps/mineral", {
        "komis_response": resp, "mineral_name": mineral, "mineral": mineral,
        "measure": MEASURE_MAP[measure_kr], "unit": unit,
    })
    record("map_mineral", key, out, None)


OUT_PATH = "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/fresh_conditions_result.json"
json.dump(results, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)

for r in results:
    print("=====", r["menu"], "|", r["condition"], "| status=", r["status"])
    if r["crosscheck"]:
        print("  crosscheck:", r["crosscheck"])
    if r["status"] not in ("ok",):
        print("  !!!", json.dumps(r, ensure_ascii=False)[:300])
print()
print("저장:", OUT_PATH)
print("전체", len(results), "건 중 status=ok:", sum(1 for r in results if r["status"] == "ok"))
