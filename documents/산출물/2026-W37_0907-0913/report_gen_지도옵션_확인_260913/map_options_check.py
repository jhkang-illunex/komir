# -*- coding: utf-8 -*-
"""2026-09-13 후속 — 핵심광물지도 3메뉴에서 날짜가 아니라 '국가·생산품유형'류
옵션을 바꿔가며 배포된 실 컨테이너로 검증한다.

- map_korea: KOMIS 조회필터 3종(국가/생산품유형/HS코드) — 정적 덤프엔
  필터 걸린 캡처가 없어(전수 확인됨) 문서화된 규칙(models.py의
  `_map_korea_query_filters` 설명 — 국가필터시 sumIncmAmt가 그 국가 자체
  금액과 일치, scope필터시 부분소계)대로 전체기간 응답에서 합성한다.
- map_global: `komis_route_share_response`(getListMapNationData) — 실제
  캡처된 원본("...|map" 키)을 그대로 쓴다(합성 아님).
- map_mineral: `komis_snapshot_response`(getListMapMnrlData, "...|map")
  + `komis_share_response`(getListMnrlTablePrdctnBurgudg, "...|table") —
  둘 다 실제 캡처된 원본을 그대로 쓴다(합성 아님)."""
import json
import urllib.request

D = "/home/nuri/dev/git/ws/mine_ws/komir/income_data/komis/"
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


results = []


def record(menu, label, out, note=None):
    entry = {"menu": menu, "condition": label, "status": out.get("status"), "note": note, "report": out.get("report")}
    if out.get("status") != "ok":
        entry["raw"] = json.dumps(out, ensure_ascii=False)[:400]
    results.append(entry)


# ─────────────────────── map_korea: 국가/생산품유형/HS 필터 ───────────────────────
dump06 = load("komis_06_supply_map_korea.json")

MAP_KOREA_COUNTRY_FILTERS = [
    ("동", "수입"), ("니켈", "수입"), ("희토류", "수출"),
]
for mineral, direction in MAP_KOREA_COUNTRY_FILTERS:
    key = f"{mineral}|{direction}|전체기간|list"
    match = [r for r in dump06["results"] if r["key"] == key]
    if not match:
        record("map_korea(국가필터)", key, {"status": "SKIP(키 없음)"})
        continue
    resp = json.loads(json.dumps(match[0]["response"]))
    rows = resp.get("list") or []
    if not rows:
        record("map_korea(국가필터)", key, {"status": "SKIP(행 없음)"})
        continue
    amt_field = "incmAmt" if direction == "수입" else "expAmt"
    sum_field = "sumIncmAmt" if direction == "수입" else "sumExpAmt"
    # 1위국으로 필터: KOMIS 실측 규칙 — 국가필터시 list=그 국가 1행뿐,
    # sum*Amt=그 국가 자신의 amt와 정확히 일치.
    top_row = max(rows, key=lambda r: num(r.get(amt_field)) or 0)
    resp["list"] = [top_row]
    resp[sum_field] = top_row[amt_field]
    resp["srchNtnCd"] = top_row["ntnCd"]
    out = post("maps/domestic-trade", {"komis_response": resp, "mineral_name": mineral})
    record("map_korea(국가필터)", f"{key} -> 국가={top_row['ntnKornNm']}", out,
           note=f"expected {sum_field}={top_row[amt_field]}")

MAP_KOREA_SCOPE_FILTERS = [
    ("코발트", "수입", "생산품유형"), ("리튬", "수입", "HS코드"),
]
for mineral, direction, kind in MAP_KOREA_SCOPE_FILTERS:
    key = f"{mineral}|{direction}|전체기간|list"
    match = [r for r in dump06["results"] if r["key"] == key]
    if not match:
        record("map_korea(범위필터)", key, {"status": "SKIP(키 없음)"})
        continue
    resp = json.loads(json.dumps(match[0]["response"]))
    rows = resp.get("list") or []
    amt_field = "incmAmt" if direction == "수입" else "expAmt"
    sum_field = "sumIncmAmt" if direction == "수입" else "sumExpAmt"
    half = rows[: max(3, len(rows) // 2)]
    scope_total = sum(num(r.get(amt_field)) or 0 for r in half)
    resp["list"] = half
    resp[sum_field] = scope_total
    payload = {"komis_response": resp, "mineral_name": mineral}
    if kind == "생산품유형":
        resp["srchMttrFlowCd"] = "PRD01"
        payload["mttr_flow_name"] = "정련품"
    else:
        resp["srchHsCd"] = "2825.30"
    out = post("maps/domestic-trade", payload)
    record("map_korea(범위필터)", f"{key} -> {kind}", out, note=f"expected {sum_field}~{scope_total}")


# ─────────────────────── map_global: komis_route_share_response ───────────────────────
dump07 = load("komis_07_supply_map_global.json")
MAP_GLOBAL_ROUTE_SHARE_PICKS = ["동", "니켈", "코발트", "희토류"]
for mineral in MAP_GLOBAL_ROUTE_SHARE_PICKS:
    list_key = f"{mineral}|수입|전체기간|list"
    map_key = f"{mineral}|수입|전체기간|map"
    list_match = [r for r in dump07["results"] if r["key"] == list_key]
    map_match = [r for r in dump07["results"] if r["key"] == map_key]
    if not list_match or not map_match:
        record("map_global(route_share)", mineral, {"status": "SKIP(키 없음)"})
        continue
    payload = {
        "komis_response": list_match[0]["response"],
        "mineral_name": mineral,
        "komis_route_share_response": map_match[0]["response"],
    }
    out = post("maps/global-trade", payload)
    record("map_global(route_share)", mineral, out)


# ─────────────────────── map_mineral: snapshot(교차비교) + share(공식비중표) ───────────────────────
dump08 = load("komis_08_mineral_map.json")
MAP_MINERAL_CROSS_PICKS = [("동", "reserves"), ("니켈", "production")]
for mineral, measure in MAP_MINERAL_CROSS_PICKS:
    measure_kr = "매장량" if measure == "reserves" else "생산량"
    chart_key = f"{mineral}|{measure_kr}|chart"
    map_key = f"{mineral}|{measure_kr}|map"
    table_key = f"{mineral}|{measure_kr}|table"
    chart_match = [r for r in dump08["results"] if r["key"] == chart_key]
    map_match = [r for r in dump08["results"] if r["key"] == map_key]
    table_match = [r for r in dump08["results"] if r["key"] == table_key]
    if not chart_match:
        record("map_mineral(교차비교+비중표)", chart_key, {"status": "SKIP(키 없음)"})
        continue
    resp = chart_match[0]["response"]
    rows = resp.get("data") or []
    unit = (rows[0].get("cdVal") or "") if rows else ""
    payload = {
        "komis_response": resp, "mineral_name": mineral, "mineral": mineral,
        "measure": measure, "unit": unit,
    }
    if map_match:
        payload["komis_snapshot_response"] = map_match[0]["response"]
    if table_match:
        payload["komis_share_response"] = table_match[0]["response"]
    out = post("maps/mineral", payload)
    record("map_mineral(교차비교+비중표)", f"{mineral}|{measure}", out,
           note=f"snapshot={'Y' if map_match else 'N'} share={'Y' if table_match else 'N'}")


OUT_PATH = "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/map_options_result.json"
json.dump(results, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)

for r in results:
    print("=====", r["menu"], "|", r["condition"], "| status=", r["status"], "|", r.get("note") or "")
    if r["status"] != "ok":
        print("  !!!", r.get("raw"))
    elif r.get("report"):
        print(r["report"][:900])
    print()
print("저장:", OUT_PATH)
print(len(results), "건 중 ok:", sum(1 for r in results if r["status"] == "ok"))
