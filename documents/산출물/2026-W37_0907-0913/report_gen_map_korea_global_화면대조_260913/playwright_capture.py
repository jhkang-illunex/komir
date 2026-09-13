# -*- coding: utf-8 -*-
import json
from playwright.sync_api import sync_playwright

RESULTS = {}

def capture_ajax(page, endpoints):
    captured = {}
    def handler(response):
        for ep in endpoints:
            if ep in response.url and response.status == 200:
                try:
                    captured.setdefault(ep, []).append(response.json())
                except Exception:
                    pass
    page.on("response", handler)
    return captured

def table_text(page, sel="#resultTable"):
    try:
        return page.locator(sel).inner_text(timeout=5000)
    except Exception:
        return None

def set_select_jq(page, sel_id, value):
    page.evaluate(f"$('#{sel_id}').val('{value}').trigger('change')")

def run_korea_case(page, case_name, *, mineral_code, mineral_name, direction="I", year="2025",
                    country=None, product=None, month=None):
    captured = capture_ajax(page, ["getListKoreaData"])
    page.goto("https://www.komis.or.kr/Komis/MnrlMap/Korea", timeout=30000)
    page.wait_for_load_state("networkidle")
    page.evaluate(f"changeSelectVal('{mineral_code}', '{mineral_name}')")
    page.wait_for_timeout(400)
    page.evaluate(f"document.querySelector('#{'srchIncmExp1' if direction=='I' else 'srchIncmExp2'}').checked = true")
    if month:
        page.evaluate("document.querySelector('#srchCrtrYmd2').checked = true")
        set_select_jq(page, "srchMonthE", month)
    set_select_jq(page, "srchYearE", year)
    if country:
        set_select_jq(page, "srchNtnCd", country)
    if product:
        set_select_jq(page, "srchMttrFlowCd", product)
    page.evaluate("setSearch(1); getListKoreaData(1);")
    page.wait_for_timeout(2500)
    text = table_text(page)
    title_el = page.locator("#top5ChartTitle")
    top5_title = title_el.inner_text() if title_el.count() else None
    RESULTS[case_name] = {
        "page": "korea", "mineral": mineral_name, "direction": direction, "year": year,
        "country": country, "product": product, "month": month,
        "table_text_head": (text or "")[:1600],
        "top5_title": top5_title,
        "ajax": captured,
    }
    print("done:", case_name)

def run_global_case(page, case_name, *, mineral_code, mineral_name, direction="I", year="2025",
                     exp_country=None, incm_country=None):
    captured = capture_ajax(page, ["getListDataNation", "getBarChartDataNation", "getListMapNationData"])
    page.goto("https://www.komis.or.kr/Komis/MnrlMap/Nation", timeout=30000)
    page.wait_for_load_state("networkidle")
    page.evaluate(f"changeSelectVal('{mineral_code}', '{mineral_name}')")
    page.wait_for_timeout(400)
    page.evaluate(f"document.querySelector('a[data-im={direction}]').classList.contains('active') || gotoImxprtMenu('{direction}', document.querySelector('a[data-im={direction}]'))")
    set_select_jq(page, "srchYearE", year)
    if exp_country:
        set_select_jq(page, "srchExpNtnCd", exp_country)
    if incm_country:
        set_select_jq(page, "srchIncmNtnCd", incm_country)
    page.evaluate("setSearch(1); getNationData(1);")
    page.wait_for_timeout(2500)
    text = table_text(page)
    RESULTS[case_name] = {
        "page": "global", "mineral": mineral_name, "direction": direction, "year": year,
        "exp_country": exp_country, "incm_country": incm_country,
        "table_text_head": (text or "")[:1600],
        "ajax": captured,
    }
    print("done:", case_name)

def run_price_case(page, case_name, *, url, mineral_code=None, mineral_name=None, compare_code=None,
                    avg_opt=None, start_year=None, end_year=None):
    captured = capture_ajax(page, ["getMnrlPrcByMnrkndUnqCd"])
    page.goto(url, timeout=30000)
    page.wait_for_load_state("networkidle")
    if mineral_code:
        page.evaluate(f"changeSelectVal('{mineral_code}', '{mineral_name}')")
        page.wait_for_timeout(400)
    if compare_code:
        set_select_jq(page, "srchCompareMnrkndUnqCd", compare_code)
    if avg_opt:
        set_select_jq(page, "srchAvgOpt", avg_opt)
    if start_year:
        set_select_jq(page, "srchStartDate", start_year)
    if end_year:
        set_select_jq(page, "srchEndDate", end_year)
    page.evaluate("getMnrlPrcList()")
    page.wait_for_timeout(2500)
    body_text = None
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        pass
    RESULTS[case_name] = {
        "page": "price", "url": url, "mineral": mineral_name, "compare": compare_code,
        "avg_opt": avg_opt, "start_year": start_year, "end_year": end_year,
        "ajax": captured,
    }
    if body_text:
        with open(f"/tmp/komis_pw_audit/{case_name}_body.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
    print("done:", case_name)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    # ── map_korea ──
    run_korea_case(page, "korea_cu_import_2025", mineral_code="MNRL0008", mineral_name="동", direction="I", year="2025")
    run_korea_case(page, "korea_cu_export_2025", mineral_code="MNRL0008", mineral_name="동", direction="E", year="2025")
    run_korea_case(page, "korea_cu_import_country_CL_2025", mineral_code="MNRL0008", mineral_name="동", direction="I", year="2025", country="CL")
    run_korea_case(page, "korea_co_import_product_2025", mineral_code="MNRL0003", mineral_name="코발트", direction="I", year="2025", product="002")
    run_korea_case(page, "korea_cu_import_month_2026_09", mineral_code="MNRL0008", mineral_name="동", direction="I", year="2026", month="09")

    # ── map_global ──
    run_global_case(page, "global_li_import_2026", mineral_code="MNRL0001", mineral_name="리튬", direction="I", year="2026")
    run_global_case(page, "global_li_export_2026", mineral_code="MNRL0001", mineral_name="리튬", direction="O", year="2026")
    run_global_case(page, "global_cu_import_2025", mineral_code="MNRL0008", mineral_name="동", direction="I", year="2025")

    # ── price_* ──
    run_price_case(page, "price_base_cu", url="https://www.komis.or.kr/Komis/RsrcPrice/BaseMetals",
                    mineral_code="MNRL0008", mineral_name="동")
    run_price_case(page, "price_base_cu_cmp_ni", url="https://www.komis.or.kr/Komis/RsrcPrice/BaseMetals",
                    mineral_code="MNRL0008", mineral_name="동", compare_code="MNRL0002")
    run_price_case(page, "price_minor_default", url="https://www.komis.or.kr/Komis/RsrcPrice/MinorMetals")
    run_price_case(page, "price_iron_default", url="https://www.komis.or.kr/Komis/RsrcPrice/IronOre")
    run_price_case(page, "price_other_default", url="https://www.komis.or.kr/Komis/RsrcPrice/EtcMnrl")

    browser.close()

with open("/tmp/komis_pw_audit/results3.json", "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)
print("ALL DONE")
