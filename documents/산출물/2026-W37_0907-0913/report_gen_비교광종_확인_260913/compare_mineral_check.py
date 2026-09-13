# -*- coding: utf-8 -*-
"""2026-09-13 후속 — 광물자원가격 4메뉴에 '비교광종'(KOMIS 원본 응답의
compareMnrl/cmpMap)까지 같이 부여해 배포된 실 컨테이너로 검증한다.

정적 덤프 8종엔 compareMnrl이 실제로 채워진 캡처가 하나도 없어(확인됨),
서로 다른 두 광종의 단일-계열 응답을 조합해 KOMIS가 실제로 주는 것과
같은 모양(data.defaultMnrl=주계열, data.compareMnrl=비교계열,
dataAvg.cmpMap.INFO=비교광종 이름/가격기준)으로 합성한다 — 필드 이름·
위치는 input_data.py::_parse_komis_price_response 문서화된 파싱 규칙
그대로(재사용 아님, 그 규칙에 맞는 입력을 만드는 것뿐)."""
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
        f"{BASE}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def pct(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / prev


def build_combined(primary_resp, compare_resp):
    combined = json.loads(json.dumps(primary_resp))  # deep copy
    combined["data"]["compareMnrl"] = compare_resp["data"]["defaultMnrl"]
    combined["dataAvg"]["cmpMap"] = {"INFO": (compare_resp.get("dataAvg") or {}).get("INFO") or {}}
    return combined


def expected_overall(resp):
    rows = (resp.get("data") or {}).get("defaultMnrl") or []
    rows_asc = sorted(rows, key=lambda r: r["crtrYmd"])
    priced = [(r["crtrYmd"], num(r.get("cmercPrc"))) for r in rows_asc if num(r.get("cmercPrc")) is not None]
    if len(priced) < 2:
        return None
    return pct(priced[-1][1], priced[0][1])


results = []


def run(page_id, path, primary_key, compare_key, dump, mineral_name, compare_mineral_name):
    p_match = [r for r in dump["results"] if r["key"] == primary_key]
    c_match = [r for r in dump["results"] if r["key"] == compare_key]
    if not p_match or not c_match:
        results.append({"page_id": page_id, "primary": primary_key, "compare": compare_key, "status": "SKIP(키 없음)"})
        return
    p_resp, c_resp = p_match[0]["response"], c_match[0]["response"]
    combined = build_combined(p_resp, c_resp)
    payload = {
        "komis_response": combined,
        "mineral_name": mineral_name, "mineral": mineral_name,
        "compare_mineral_name": compare_mineral_name, "compare_mineral": compare_mineral_name,
    }
    out = post(path, payload)
    expected_primary = expected_overall(p_resp)
    expected_compare = expected_overall(c_resp)
    expected_diff_pp = None
    if expected_primary is not None and expected_compare is not None:
        expected_diff_pp = (expected_primary - expected_compare) * 100
    entry = {
        "page_id": page_id, "primary": primary_key, "compare": compare_key,
        "status": out.get("status"),
        "expected_primary_overall_pct": round(expected_primary * 100, 2) if expected_primary is not None else None,
        "expected_compare_overall_pct": round(expected_compare * 100, 2) if expected_compare is not None else None,
        "expected_diff_pp": round(expected_diff_pp, 2) if expected_diff_pp is not None else None,
        "report": out.get("report"),
    }
    results.append(entry)


dump01 = load("komis_01_base_metals.json")
BASE_METAL_PAIRS = [
    ("아연", "아연|LME CASH|DAY", "알루미늄", "알루미늄|LME CASH|DAY"),
    ("연", "연|LME CASH|DAY", "주석", "주석|LME CASH|DAY"),
    ("니켈", "니켈|LME 3개월|DAY", "동", "동|LME CASH|DAY"),
    ("주석", "주석|LME 3개월|DAY", "아연", "아연|LME CASH|DAY"),
]
for mineral, pkey, cmineral, ckey in BASE_METAL_PAIRS:
    run("price_base_metals", "prices/base-metals", pkey, ckey, dump01, mineral, cmineral)

dump02 = load("komis_02_minor_metals.json")
MINOR_METAL_PAIRS = [
    ("텅스텐", "텅스텐|Tungsten APT|88.5|DAY", "몰리브덴", "몰리브덴|Ferro-molybdenum|60|DAY"),
    ("네오디뮴", "네오디뮴|Neodymium Oxide|99.5|DAY", "프라세오디뮴", "프라세오디뮴|Praseodymium Oxide|99.5|DAY"),
    ("갈륨", "갈륨|Gallium Metal|99.99999|DAY", "인듐", "인듐|Indium Ingot|99.995|DAY"),
    ("리튬", "리튬|Lithium Carbonate|99.5|DAY", "코발트", "코발트|Cobalt Metal|99.8|DAY"),
]
for mineral, pkey, cmineral, ckey in MINOR_METAL_PAIRS:
    run("price_minor_metals", "prices/minor-metals", pkey, ckey, dump02, mineral, cmineral)


def build_iron_other_resp(item):
    return item["response"]


phase2 = json.load(open(PHASE2, encoding="utf-8"))
pseudo_dump = {"results": [{"key": f"{x['mineral_name']}|{((x['response'].get('dataAvg') or {}).get('INFO') or {}).get('prcCrtr')}", "response": x["response"]} for x in phase2]}
IRON_ENERGY_PAIRS = [
    ("우라늄", [k for k in pseudo_dump["results"] if k["key"].startswith("우라늄|")][0]["key"],
     "유연탄", [k for k in pseudo_dump["results"] if k["key"].startswith("유연탄|")][0]["key"]),
]
for mineral, pkey, cmineral, ckey in IRON_ENERGY_PAIRS:
    run("price_iron_energy", "prices/iron-energy", pkey, ckey, pseudo_dump, mineral, cmineral)

OTHER_PAIRS = [
    ("흑연", "금"), ("철", "은"), ("백금", "팔라듐"), ("루테늄", "흑연"),
]
for mineral, cmineral in OTHER_PAIRS:
    pkey = [k for k in pseudo_dump["results"] if k["key"].startswith(mineral + "|")][0]["key"]
    ckey = [k for k in pseudo_dump["results"] if k["key"].startswith(cmineral + "|")][0]["key"]
    run("price_other", "prices/other", pkey, ckey, pseudo_dump, mineral, cmineral)


OUT_PATH = "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/compare_mineral_result.json"
json.dump(results, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)

for r in results:
    print("=====", r["page_id"], "|", r["primary"], "vs", r["compare"], "| status=", r["status"])
    print("  expected: primary", r.get("expected_primary_overall_pct"), "% | compare", r.get("expected_compare_overall_pct"), "% | diff", r.get("expected_diff_pp"), "pp")
    if r.get("report"):
        for line in r["report"].split("\n"):
            if "같은 조회기간" in line or "상대가치" in line or "변화율차" in line:
                print("  actual:", line)
    if r["status"] not in ("ok",):
        print("  !!! FULL:", json.dumps(r, ensure_ascii=False)[:400])
print()
print("저장:", OUT_PATH)
print(len(results), "건 중 ok:", sum(1 for r in results if r["status"] == "ok"))
