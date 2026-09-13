# -*- coding: utf-8 -*-
"""2026-09-13 '풀 검증' — report_gen 10개 page_id의 핵심 수치를 raw KOMIS
JSON에서 독립적으로(report_gen 파서 재사용 없이) 재계산하고, 실제 프로덕션
진입점(komis_response 패스스루)으로 얻은 응답과 비교한다.

원칙(advisor 검토 반영):
  - expected 쪽은 이 파일 안에서 새로 짠 코드로만 raw JSON을 읽는다
    (input_data.py의 _parse_komis_* 함수, komis_dump_smoke_test.py의
    adapt_* 함수를 일절 import하지 않는다 — 두 쪽이 같은 전처리를
    공유하면 그 전처리 버그가 통과됨, 실제로 map_korea에서 있었던 일).
  - actual 쪽은 AnalysisSummaryRequest(komis_response=...) 패스스루로만
    호출한다 — 손 조립 observations/komis_trade_totals 경로는 실 API
    라우터가 절대 받지 않는 모양이라 검증 가치가 낮다.
  - 표본 1건이 아니라 덤프에 있는 해당 그룹의 모든 광종/아이템을 돈다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "inhouse" / "report_gen"))
sys.path.insert(0, "/home/nuri/dev/git/ws/mine_ws/komir/inhouse/report_gen")

from app.analysis.models import AnalysisSummaryRequest  # noqa: E402
from app.analysis.summary import AnalysisSummaryService  # noqa: E402

D = "/home/nuri/dev/git/ws/mine_ws/komir/income_data/komis/"
PHASE2 = (
    "/home/nuri/dev/git/ws/mine_ws/komir/documents/산출물/2026-W35_0824-0830/"
    "report_gen_KOMIS라이브재검증_Phase2_260829_evidence/collected_iron_other_day_raw_260829.json"
)

SVC = AnalysisSummaryService(None, llm=None)

results = []  # (page_id, item_label, list[(metric_id, expected, actual, ok, note)])


def load(name):
    return json.load(open(D + name, encoding="utf-8"))


def num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def close(a, b, tol_rel=0.001, tol_abs=0.01):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= max(tol_abs, abs(a) * tol_rel)


def call(page_id, komis_response, mineral_name=None, extra=None, mineral_code=None):
    payload = {"page_id": page_id, "komis_response": komis_response}
    if mineral_name:
        payload["mineral_name"] = mineral_name
    if mineral_code or mineral_name:
        payload["mineral"] = mineral_code or mineral_name
    if extra:
        payload.update(extra)
    req = AnalysisSummaryRequest(**payload)
    return SVC.analyze(req)


def metric_map(resp):
    out = {}
    for m in resp.key_metrics:
        out.setdefault(m.id, []).append(m.value)
    return out


def record(page_id, item, checks):
    results.append((page_id, item, checks))


# ---------------------------------------------------------------- price ----
def verify_price_group(dump_name, page_id, mineral_filter=None):
    dump = load(dump_name)
    for r in dump["results"]:
        resp = r["response"]
        info = ((resp.get("dataAvg") or {}).get("INFO")) or {}
        mineral = info.get("mnrkndKornNm")
        if mineral is None:
            continue
        if mineral_filter and mineral not in mineral_filter:
            continue
        rows = (resp.get("data") or {}).get("defaultMnrl") or []
        if not rows:
            continue
        rows_asc = sorted(rows, key=lambda x: x["crtrYmd"])
        prices = [(row["crtrYmd"], num(row.get("cmercPrc"))) for row in rows_asc if num(row.get("cmercPrc")) not in (None, 0)]
        if not prices:
            continue
        std_map = ((resp.get("dataAvg") or {}).get("stdMap")) or {}
        latest_expected = num((std_map.get("CRTRYMD") or {}).get("cmercPrc"))
        if latest_expected is None:
            latest_expected = num((std_map.get("DAY") or {}).get("cmercPrc"))
        if latest_expected is None:
            latest_expected = prices[-1][1]

        # period high/low over ALL rows with a price (independent scan)
        high_expected = max(p for _, p in prices)
        low_expected = min(p for _, p in prices)

        # inventory
        inv_rows = [(row["crtrYmd"], num(row.get("invt"))) for row in rows_asc if num(row.get("invt")) not in (None, 0)]
        inv_expected = inv_rows[-1][1] if inv_rows else None
        inv_change_expected = None
        if len(inv_rows) >= 2:
            prev_inv = inv_rows[-2][1]
            if prev_inv:
                inv_change_expected = (inv_rows[-1][1] - prev_inv) / prev_inv * 100

        # streak: direction scan over the full ascending price series (all rows, not just >0 filtered)
        full_prices = [(row["crtrYmd"], num(row.get("cmercPrc"))) for row in rows_asc]
        full_prices = [x for x in full_prices if x[1] is not None]
        directions = []
        for (_, a), (_, b) in zip(full_prices, full_prices[1:]):
            directions.append("up" if b > a else "down" if b < a else "flat")
        streak_expected = None
        if directions:
            last_dir = directions[-1]
            streak = 1
            for d in reversed(directions[:-1]):
                if d != last_dir:
                    break
                streak += 1
            if streak >= 2:
                streak_expected = streak

        # week/month/year change_pct via KOMIS stdMap passthrough (exact)
        period_expected = {}
        for key, field in (("week_avg", "WEEK"), ("month_avg", "MONTH"), ("year_avg", "YEAR")):
            entry = std_map.get(field)
            if entry:
                pct = num(entry.get("flctnPrcnt"))
                if pct is not None:
                    period_expected[f"{key}_change_pct"] = pct

        komis_response = {"data": {"defaultMnrl": rows}, "dataAvg": resp.get("dataAvg")}
        try:
            resp_actual = call(page_id, komis_response, mineral_name=mineral)
        except Exception as exc:  # noqa: BLE001
            record(page_id, mineral, [("CALL_ERROR", None, str(exc), False, "예외 발생")])
            continue
        mm = metric_map(resp_actual)

        checks = []
        checks.append(("latest_price", latest_expected, (mm.get("latest_price") or [None])[0], close(latest_expected, (mm.get("latest_price") or [None])[0]), ""))
        if "period_high" in mm:
            checks.append(("period_high", high_expected, mm["period_high"][0], close(high_expected, mm["period_high"][0]), ""))
        if "period_low" in mm:
            checks.append(("period_low", low_expected, mm["period_low"][0], close(low_expected, mm["period_low"][0]), ""))
        if inv_expected is not None and "inventory_level" in mm:
            checks.append(("inventory_level", inv_expected, mm["inventory_level"][0], close(inv_expected, mm["inventory_level"][0]), ""))
        if inv_change_expected is not None and "inventory_change_pct" in mm:
            checks.append(("inventory_change_pct", inv_change_expected, mm["inventory_change_pct"][0], close(inv_change_expected, mm["inventory_change_pct"][0], tol_abs=0.05), ""))
        if streak_expected is not None and "price_streak_length" in mm:
            checks.append(("price_streak_length", streak_expected, mm["price_streak_length"][0], streak_expected == mm["price_streak_length"][0], ""))
        for key, exp in period_expected.items():
            if key in mm:
                checks.append((key, exp, mm[key][0], close(exp, mm[key][0], tol_abs=0.05), "KOMIS stdMap 패스스루 exact"))
        record(page_id, mineral, checks)


verify_price_group("komis_01_base_metals.json", "price_base_metals")
verify_price_group("komis_02_minor_metals.json", "price_minor_metals")

# price_iron_energy / price_other via Phase2 dump (10 items, day-avg observations)
iron_other = json.load(open(PHASE2, encoding="utf-8"))
IRON_ENERGY_MINERALS = {"우라늄", "유연탄"}
for item in iron_other:
    mineral = item["mineral_name"]
    resp = item["response"]
    info = (resp.get("dataAvg") or {}).get("INFO") or {}
    rows = (resp.get("data") or {}).get("defaultMnrl") or []
    if not rows:
        continue
    rows_asc = sorted(rows, key=lambda x: x["crtrYmd"])
    prices = [(row["crtrYmd"], num(row.get("cmercPrc"))) for row in rows_asc if num(row.get("cmercPrc"))]
    if not prices:
        continue
    std_map = ((resp.get("dataAvg") or {}).get("stdMap")) or {}
    latest_expected = num((std_map.get("CRTRYMD") or {}).get("cmercPrc")) or num((std_map.get("DAY") or {}).get("cmercPrc")) or prices[-1][1]
    high_expected = max(p for _, p in prices)
    low_expected = min(p for _, p in prices)
    page_id = "price_iron_energy" if mineral in IRON_ENERGY_MINERALS else "price_other"
    komis_response = {"data": {"defaultMnrl": rows}, "dataAvg": resp.get("dataAvg")}
    try:
        resp_actual = call(page_id, komis_response, mineral_name=mineral)
    except Exception as exc:  # noqa: BLE001
        record(page_id, mineral, [("CALL_ERROR", None, str(exc), False, "예외 발생")])
        continue
    mm = metric_map(resp_actual)
    checks = [("latest_price", latest_expected, (mm.get("latest_price") or [None])[0], close(latest_expected, (mm.get("latest_price") or [None])[0]), "")]
    if "period_high" in mm:
        checks.append(("period_high", high_expected, mm["period_high"][0], close(high_expected, mm["period_high"][0]), ""))
    if "period_low" in mm:
        checks.append(("period_low", low_expected, mm["period_low"][0], close(low_expected, mm["period_low"][0]), ""))
    record(page_id, mineral, checks)


# ------------------------------------------------------------ indicator ---
INDICATOR_GRADE_BANDS = [
    ("긴장", 0, 20, True, True),
    ("주의", 20, 40, False, True),
    ("관심", 40, 60, False, True),
    ("안정", 60, 80, False, True),
    ("원활", 80, 100, False, True),
]


def classify_grade(score):
    for label, lo, hi, inc_min, inc_max in INDICATOR_GRADE_BANDS:
        lower_ok = score >= lo if inc_min else score > lo
        upper_ok = score <= hi if inc_max else score < hi
        if lower_ok and upper_ok:
            return label
    return None


def verify_indicator_group(dump_name, page_id, score_field, snapshot_key=None):
    dump = load(dump_name)
    for r in dump["results"]:
        key = r["key"]
        if snapshot_key and snapshot_key in key:
            continue
        mineral = key
        resp = r["response"]
        rows = resp.get("data") if isinstance(resp, dict) else resp
        if not isinstance(rows, list) or not rows:
            continue
        seen_months = set()
        obs = []
        for row in rows:  # KOMIS gives descending; keep first occurrence per month
            ymd = str(row.get("crtrYmd") or "")
            month = ymd[:6]
            score = num(row.get(score_field))
            if len(month) != 6 or score is None or month in seen_months:
                continue
            seen_months.add(month)
            obs.append((month, score))
        if not obs:
            continue
        obs.sort(key=lambda x: x[0])
        current_score_expected = obs[-1][1]
        observation_count_expected = len(obs)

        rising = falling = flat = 0
        for (_, a), (_, b) in zip(obs, obs[1:]):
            if b > a:
                rising += 1
            elif b < a:
                falling += 1
            else:
                flat += 1

        # grade streak (contiguous months only, per code docstring)
        def month_before(m):
            y, mo = int(m[:4]), int(m[4:6])
            return f"{y-1}12" if mo == 1 else f"{y}{mo-1:02d}"

        grades = [classify_grade(s) for _, s in obs]
        current_grade_expected = grades[-1]
        streak = 1
        for i in range(len(obs) - 1, 0, -1):
            if grades[i] != grades[i - 1]:
                break
            if month_before(obs[i][0]) != obs[i - 1][0]:
                break
            streak += 1

        komis_response = {"data": rows}
        try:
            resp_actual = call(page_id, komis_response, mineral_name=mineral)
        except Exception as exc:  # noqa: BLE001
            record(page_id, mineral, [("CALL_ERROR", None, str(exc), False, "예외 발생")])
            continue
        mm = metric_map(resp_actual)
        checks = []
        if "current_score" in mm:
            checks.append(("current_score", current_score_expected, mm["current_score"][0], close(current_score_expected, mm["current_score"][0]), ""))
        if "observation_count" in mm:
            checks.append(("observation_count", observation_count_expected, mm["observation_count"][0], observation_count_expected == mm["observation_count"][0], "월별 dedup 재현"))
        if "score_rising_months" in mm:
            checks.append(("score_rising_months", rising, mm["score_rising_months"][0], rising == mm["score_rising_months"][0], ""))
        if "score_falling_months" in mm:
            checks.append(("score_falling_months", falling, mm["score_falling_months"][0], falling == mm["score_falling_months"][0], ""))
        if "score_flat_months" in mm:
            checks.append(("score_flat_months", flat, mm["score_flat_months"][0], flat == mm["score_flat_months"][0], ""))
        if streak >= 2 and "current_grade_streak" in mm:
            checks.append(("current_grade_streak", streak, mm["current_grade_streak"][0], streak == mm["current_grade_streak"][0], f"등급={current_grade_expected}"))
        record(page_id, mineral, checks)


verify_indicator_group("komis_04_market_trend.json", "indicator_market", "mrktPrspectIdct")
verify_indicator_group("komis_05_supply_trend.json", "indicator_supply", "spdmStbtIndx", snapshot_key="패널차트")


# ------------------------------------------------------------- map_korea --
def verify_map_korea():
    dump = load("komis_06_supply_map_korea.json")
    minerals = sorted({r["key"].split("|")[0] for r in dump["results"] if r["key"].endswith("전체기간|list")})
    for mineral in minerals:
        for direction, metric_prefix in (("수입", "import"), ("수출", "export")):
            key = f"{mineral}|{direction}|전체기간|list"
            match = [r for r in dump["results"] if r["key"] == key]
            if not match:
                continue
            resp = match[0]["response"]
            rows = resp.get("list") or []
            if not rows:
                continue
            sum_field = "sumIncmAmt" if direction == "수입" else "sumExpAmt"
            amt_field = "incmAmt" if direction == "수입" else "expAmt"
            total_expected = num(rows[0].get(sum_field))
            if total_expected is None:
                continue
            # top3/top5 share: rows themselves ARE already sorted top-N by KOMIS (orderSort desc assumed);
            # verify via independent sort by amt_field, share against the true KOMIS total.
            sorted_rows = sorted(rows, key=lambda x: num(x.get(amt_field)) or 0, reverse=True)
            top3_sum = sum(num(x.get(amt_field)) or 0 for x in sorted_rows[:3])
            top5_sum = sum(num(x.get(amt_field)) or 0 for x in sorted_rows[:5])
            top3_share_expected = top3_sum / total_expected * 100 if total_expected else None
            top5_share_expected = top5_sum / total_expected * 100 if total_expected else None
            top1_expected = num(sorted_rows[0].get(amt_field))

            komis_response = resp
            try:
                resp_actual = call("map_korea", komis_response, mineral_name=mineral)
            except Exception as exc:  # noqa: BLE001
                record("map_korea", f"{mineral}|{direction}", [("CALL_ERROR", None, str(exc), False, "예외 발생")])
                continue
            mm = metric_map(resp_actual)
            checks = []
            total_id = "import_total_amount" if direction == "수입" else "export_total_amount"
            if total_id in mm:
                checks.append((total_id, total_expected, mm[total_id][0], close(total_expected, mm[total_id][0], tol_rel=0.0001), "KOMIS sum*Amt 패스스루 exact"))
            if direction == "수입":
                if "top3_import_share_pct" in mm and len(mm["top3_import_share_pct"]) >= 1:
                    # id reused (3위국 비중 vs 상위3국 수입비중) -> check ANY value matches CR3
                    matched = any(close(top3_share_expected, v, tol_abs=0.5) for v in mm["top3_import_share_pct"])
                    checks.append(("top3_import_share_pct(any)", top3_share_expected, mm["top3_import_share_pct"], matched, "list 30행 캡=KOMIS도 캡, 상위 5국 안쪽이라 안전"))
                if "top5_import_share_pct" in mm:
                    matched = any(close(top5_share_expected, v, tol_abs=0.5) for v in mm["top5_import_share_pct"])
                    checks.append(("top5_import_share_pct", top5_share_expected, mm["top5_import_share_pct"], matched, ""))
            else:
                if "top1_export_share_pct" in mm:
                    top1_share_expected = top1_expected / total_expected * 100 if total_expected else None
                    checks.append(("top1_export_share_pct", top1_share_expected, mm["top1_export_share_pct"][0], close(top1_share_expected, mm["top1_export_share_pct"][0], tol_abs=0.5), ""))
                if "export_import_ratio_pct" in mm:
                    # need import total too
                    imp_match = [r for r in dump["results"] if r["key"] == f"{mineral}|수입|전체기간|list"]
                    if imp_match:
                        imp_total = num((imp_match[0]["response"].get("list") or [{}])[0].get("sumIncmAmt"))
                        if imp_total:
                            ratio_expected = total_expected / imp_total * 100
                            checks.append(("export_import_ratio_pct", ratio_expected, mm["export_import_ratio_pct"][0], close(ratio_expected, mm["export_import_ratio_pct"][0], tol_abs=0.5), ""))
            record("map_korea", f"{mineral}|{direction}", checks)


verify_map_korea()


# ------------------------------------------------------------ map_global --
def verify_map_global():
    dump = load("komis_07_supply_map_global.json")
    minerals = sorted({r["key"].split("|")[0] for r in dump["results"] if r["key"].endswith("전체기간|list")})
    for mineral in minerals:
        key = f"{mineral}|수입|전체기간|list"
        match = [r for r in dump["results"] if r["key"] == key]
        if not match:
            continue
        resp = match[0]["response"]
        rows = resp.get("list") or []
        if not rows:
            continue
        total_expected = num(rows[0].get("sumAmt"))
        if total_expected is None:
            continue
        sorted_rows = sorted(rows, key=lambda x: num(x.get("amt")) or 0, reverse=True)
        top1_expected = num(sorted_rows[0].get("amt"))
        top3_share_expected = sum(num(x.get("amt")) or 0 for x in sorted_rows[:3]) / total_expected * 100
        top5_share_expected = sum(num(x.get("amt")) or 0 for x in sorted_rows[:5]) / total_expected * 100
        top1_share_expected = top1_expected / total_expected * 100

        try:
            resp_actual = call("map_global", resp, mineral_name=mineral)
        except Exception as exc:  # noqa: BLE001
            record("map_global", mineral, [("CALL_ERROR", None, str(exc), False, "예외 발생")])
            continue
        mm = metric_map(resp_actual)
        checks = []
        if "total_amount" in mm:
            checks.append(("total_amount", total_expected, mm["total_amount"][0], close(total_expected, mm["total_amount"][0], tol_rel=0.0001), "KOMIS sumAmt 패스스루 exact"))
        if "top1_share_pct" in mm:
            checks.append(("top1_share_pct", top1_share_expected, mm["top1_share_pct"][0], close(top1_share_expected, mm["top1_share_pct"][0], tol_abs=0.5), ""))
        if "top3_share_pct" in mm:
            checks.append(("top3_share_pct", top3_share_expected, mm["top3_share_pct"][0], close(top3_share_expected, mm["top3_share_pct"][0], tol_abs=0.5), ""))
        if "top5_share_pct" in mm:
            checks.append(("top5_share_pct", top5_share_expected, mm["top5_share_pct"][0], close(top5_share_expected, mm["top5_share_pct"][0], tol_abs=0.5), ""))
        record("map_global", mineral, checks)


verify_map_global()


# ----------------------------------------------------------- map_mineral --
def verify_map_mineral():
    dump = load("komis_08_mineral_map.json")
    combos = sorted({(r["key"].split("|")[0], r["key"].split("|")[1]) for r in dump["results"] if r["key"].endswith("|chart")})
    field_map = {"매장량": "burudgQuty", "생산량": "prdctnQuty"}
    measure_map = {"매장량": "reserves", "생산량": "production"}
    for mineral, measure in combos:
        key = f"{mineral}|{measure}|chart"
        match = [r for r in dump["results"] if r["key"] == key]
        if not match:
            continue
        resp = match[0]["response"]
        rows = resp.get("data") or []
        if not rows:
            continue
        field = field_map.get(measure)
        if field is None:
            continue
        years = sorted({row.get("crtrYr") for row in rows if row.get("crtrYr")})
        if not years:
            continue
        current_year = years[-1]
        current_rows = [row for row in rows if row.get("crtrYr") == current_year]
        vals = [(row.get("ntnKornNm"), num(row.get(field))) for row in current_rows if num(row.get(field))]
        if not vals:
            continue
        total_expected = sum(v for _, v in vals)
        vals_sorted = sorted(vals, key=lambda x: x[1], reverse=True)
        top_country_expected = vals_sorted[0][0]
        top1_share_expected = vals_sorted[0][1] / total_expected
        cr3_expected = sum(v for _, v in vals_sorted[:3]) / total_expected
        cr5_expected = sum(v for _, v in vals_sorted[:5]) / total_expected

        try:
            resp_actual = call("map_mineral", resp, mineral_name=mineral, extra={"measure": measure_map[measure], "unit": (rows[0].get("cdVal") or "")})
        except Exception as exc:  # noqa: BLE001
            record("map_mineral", f"{mineral}|{measure}", [("CALL_ERROR", None, str(exc), False, "예외 발생")])
            continue
        mm = metric_map(resp_actual)
        checks = []
        if "current_world_total" in mm:
            checks.append(("current_world_total", total_expected, mm["current_world_total"][0], close(total_expected, mm["current_world_total"][0], tol_rel=0.001), "totalBurudgQuty 필드 안 믿고 행 합산(기존 정책)"))
        if "top_country" in mm:
            checks.append(("top_country", top_country_expected, mm["top_country"][0], top_country_expected == mm["top_country"][0], ""))
        if "top_country_share" in mm:
            checks.append(("top_country_share", top1_share_expected, mm["top_country_share"][0], close(top1_share_expected, mm["top_country_share"][0], tol_abs=0.005), ""))
        if "cr3" in mm:
            checks.append(("cr3", cr3_expected, mm["cr3"][0], close(cr3_expected, mm["cr3"][0], tol_abs=0.005), ""))
        if "cr5" in mm:
            checks.append(("cr5", cr5_expected, mm["cr5"][0], close(cr5_expected, mm["cr5"][0], tol_abs=0.005), ""))
        record("map_mineral", f"{mineral}|{measure}", checks)


verify_map_mineral()


# --------------------------------------------------------------- report ---
total_checks = 0
total_fail = 0
by_page = {}
fails = []
for page_id, item, checks in results:
    for metric_id, exp, act, ok, note in checks:
        total_checks += 1
        by_page.setdefault(page_id, [0, 0])
        by_page[page_id][1] += 1
        if ok:
            by_page[page_id][0] += 1
        else:
            total_fail += 1
            fails.append((page_id, item, metric_id, exp, act, note))

print(f"=== 총 {len(results)}개 (page_id,item) 조합, {total_checks}개 독립 재계산 체크 ===")
for page_id, (ok, tot) in sorted(by_page.items()):
    print(f"  {page_id}: {ok}/{tot} 일치")
print()
if fails:
    print(f"!!! 불일치 {total_fail}건 !!!")
    for page_id, item, metric_id, exp, act, note in fails:
        print(f"  [{page_id}] {item} :: {metric_id} expected={exp} actual={act} ({note})")
else:
    print("불일치 없음 (0건)")

OUT = "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/full_verify_result.json"
json.dump(
    {
        "summary": {k: {"ok": v[0], "total": v[1]} for k, v in by_page.items()},
        "combos": len(results),
        "total_checks": total_checks,
        "total_fail": total_fail,
        "fails": [
            {"page_id": p, "item": i, "metric_id": m, "expected": e, "actual": a, "note": n}
            for p, i, m, e, a, n in fails
        ],
        "all": [
            {"page_id": p, "item": i, "checks": [
                {"metric_id": m, "expected": e, "actual": a, "ok": ok, "note": n} for m, e, a, ok, n in c
            ]}
            for p, i, c in results
        ],
    },
    open(OUT, "w"),
    ensure_ascii=False,
    indent=2,
)
print("저장:", OUT)
