# -*- coding: utf-8 -*-
"""v9 -> v10: 가격 4종 서브메뉴 각각에 '비교광종 추가' 슬라이드 1개씩,
핵심광물지도 3종에 '날짜 외 옵션'(국가필터·생산품유형필터·수출입국가·
매장량/생산량 교차비교) 슬라이드 4개를 새로 추가한다. 기존 12개 슬라이드
내용은 건드리지 않는다(순수 추가)."""
import copy
import json
import os
import shutil
import sys

sys.path.insert(0, "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad")
from pptx_helpers import find_pptx, get_shape_by_name, set_paragraph, clear_runs, D
from pptx import Presentation
from pptx.oxml.ns import qn

DATA = json.load(open(
    "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/859eef05-8b64-4e86-96f6-020f2796a86f/scratchpad/v10_new_cases.json",
    encoding="utf-8",
))


def fmt(value, digits=2):
    if value is None:
        return ""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"


def pct(value, digits=2):
    return fmt(round(value, digits), digits)


def year(date_str):
    return date_str[:4]


def base_style(shape):
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            return run.font.size
    return None


def fill(shape, entries):
    size = base_style(shape)
    tf = shape.text_frame
    existing = list(tf.paragraphs)
    for i, (text, is_header) in enumerate(entries):
        p = existing[i] if i < len(existing) else tf.add_paragraph()
        set_paragraph(p, [(text, False)], size=size, bold=(True if is_header else None))
    for j in range(len(entries), len(existing)):
        clear_runs(existing[j])


def set_caption(shape, text):
    for para in shape.text_frame.paragraphs:
        if para.runs:
            para.runs[0].text = text
            for extra in para.runs[1:]:
                extra.text = ""
            return
    if shape.text_frame.paragraphs:
        set_paragraph(shape.text_frame.paragraphs[0], [(text, False)])


def set_title(slide, text):
    for shape in slide.shapes:
        if shape.name == "제목 1":
            tf = shape.text_frame
            if tf.paragraphs and tf.paragraphs[0].runs:
                tf.paragraphs[0].runs[0].text = text
                for extra in tf.paragraphs[0].runs[1:]:
                    extra.text = ""
                for p in tf.paragraphs[1:]:
                    clear_runs(p)
                return
    raise KeyError("title shape not found")


def mid(metrics, metric_id):
    for m in metrics:
        if m["id"] == metric_id:
            return m
    raise KeyError(metric_id)


def mlabel(metrics, label):
    for m in metrics:
        if m["label"] == label:
            return m
    raise KeyError(label)


def set_table_value(table, row_label, value_text):
    for row in table.rows:
        if row.cells[0].text.strip() == row_label:
            cell = row.cells[1]
            for para in cell.text_frame.paragraphs:
                if para.runs:
                    para.runs[0].text = value_text
                    for extra in para.runs[1:]:
                        extra.text = ""
                    return True
    return False


def clear_table_value(table, row_label):
    set_table_value(table, row_label, "")


def duplicate_slide(prs, index):
    """index 슬라이드를 복제해 프레젠테이션 맨 뒤에 추가하고 그 Slide 객체를
    반환한다(위치는 나중에 move_slide로 옮긴다) — python-pptx엔 내장 복제
    기능이 없어 표준 레시피(레이아웃으로 새 슬라이드를 만들고 원본 shape을
    deepcopy로 옮김)를 쓴다."""
    source = prs.slides[index]
    dest = prs.slides.add_slide(source.slide_layout)
    for shape in list(dest.shapes):
        shape._element.getparent().remove(shape._element)
    for shape in source.shapes:
        dest.shapes._spTree.append(copy.deepcopy(shape._element))
    return dest


def move_slide(prs, old_index, new_index):
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    xml_slides.remove(slides[old_index])
    xml_slides.insert(new_index, slides[old_index])


GROUP_LABEL = {
    "price_base_metals": "비철금속", "price_minor_metals": "희소금속",
    "price_iron_energy": "철에너지", "price_other": "기타",
}


def fill_price_slide(slide, d, page_id, title_suffix, compare_name):
    set_title(slide, f"{GROUP_LABEL[page_id]} - 광물가격지표 ({title_suffix})")
    box = get_shape_by_name(slide, "TextBox 8")
    core = " ".join(d["sentences"]["core_diagnosis"])
    major = " ".join(d["sentences"]["major_changes"])
    position = d["sentences"]["current_position"]
    entries = [("가격 요약", True), (core, False), ("최근 변화", True), (major, False), ("변동 구간", True)]
    entries += [(s, False) for s in position]
    fill(box, entries)

    cap = get_shape_by_name(slide, "TextBox 11")
    mineral = d["applied_filters"]["mineral"]
    y0, y1 = year(d["applied_filters"]["start_date"]), year(d["applied_filters"]["end_date"])
    set_caption(
        cap,
        f"검색 옵션 : {GROUP_LABEL[page_id]}, {mineral}, {y0}~{y1}, 일 평균 조회, 비교광종: {compare_name}",
    )

    table = get_shape_by_name(slide, "표 10").table
    km = d["key_metrics"]
    set_table_value(table, "현재가격", fmt(mid(km, "latest_price")["value"]))
    try:
        set_table_value(table, "전주 대비", pct(mid(km, "week_avg_change_pct")["value"]))
    except KeyError:
        clear_table_value(table, "전주 대비")
    try:
        set_table_value(table, "전월 대비", pct(mid(km, "month_avg_change_pct")["value"]))
    except KeyError:
        clear_table_value(table, "전월 대비")
    try:
        set_table_value(table, "전년 대비", pct(mid(km, "year_avg_change_pct")["value"]))
    except KeyError:
        clear_table_value(table, "전년 대비")
    set_table_value(table, "최고가", fmt(mid(km, "period_high")["value"]))
    set_table_value(table, "최저가", fmt(mid(km, "period_low")["value"]))
    try:
        set_table_value(table, "낙폭", pct(mid(km, "drawdown_from_period_high_pct")["value"]))
    except KeyError:
        clear_table_value(table, "낙폭")
    try:
        set_table_value(table, "변동성", pct(mid(km, "recent_volatility_pct")["value"]))
    except KeyError:
        clear_table_value(table, "변동성")
    try:
        streak = mid(km, "price_streak_length")
        set_table_value(table, "연속 추세", fmt(streak["value"]))
    except KeyError:
        pass
    # 비교광종 변화율차 — 기존 표에 없던 행이라 마지막 행을 복제해 추가한다.
    NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    tbl = table._tbl
    rows = tbl.findall(f".//{NS}tr")
    new_row = copy.deepcopy(rows[-1])
    rows[-1].addnext(new_row)
    cells = new_row.findall(f"{NS}tc")
    cmp_metric = mid(km, "compare_overall_change_pct")
    values = [f"{compare_name} 대비 조회기간 변화율차", pct(cmp_metric["value"]), "%p"]
    for cell_el, value in zip(cells, values):
        texts = cell_el.findall(f".//{NS}t")
        for i, t in enumerate(texts):
            t.text = value if i == 0 else ""


def build(path):
    p = Presentation(path)

    # ── 가격 4종: 비교광종 추가 슬라이드(각 기존 슬라이드 바로 뒤에 삽입) ──
    price_specs = [
        (2, "cmp_price_base_metals", "price_base_metals", "비교광종 추가", "알루미늄"),
        (3, "cmp_price_minor_metals", "price_minor_metals", "비교광종 추가", "몰리브덴"),
        (4, "cmp_price_iron_energy", "price_iron_energy", "비교광종 추가", "유연탄"),
        (5, "cmp_price_other", "price_other", "비교광종 추가", "금"),
    ]
    # 삽입할 때마다 뒤 슬라이드 인덱스가 밀리므로, 삽입 위치를 큰 인덱스부터
    # 역순으로 처리해 앞쪽 인덱스가 안 틀어지게 한다.
    inserted_map_positions = []
    offset = 0
    for base_idx, data_key, page_id, suffix, cmp_name in price_specs:
        new_slide = duplicate_slide(p, base_idx + offset)
        fill_price_slide(new_slide, DATA[data_key], page_id, suffix, cmp_name)
        new_pos = base_idx + offset + 1
        move_slide(p, len(list(p.slides._sldIdLst)) - 1, new_pos)
        offset += 1

    # ── 핵심광물지도 3종: 옵션 슬라이드 4개(각 메뉴 기존 슬라이드 바로 뒤) ──
    # 가격 슬라이드 4개가 삽입된 만큼 map_korea/global/mineral의 원래 인덱스
    # (9,10,11)도 +4 만큼 밀렸다.
    map_korea_idx = 9 + offset
    map_global_idx = 10 + offset
    map_mineral_idx = 11 + offset

    # map_korea 국가필터
    d = DATA["map_korea_country_filter"]
    new_slide = duplicate_slide(p, map_korea_idx)
    set_title(new_slide, "국내수급지도 - 핵심광물지도 (국가필터)")
    box = get_shape_by_name(new_slide, "TextBox 4")
    entries = [
        ("수입 현황", True), (" ".join(d["sentences"]["core_diagnosis"]), False),
        ("수입 집중도", True), (" ".join(d["sentences"]["major_changes"]), False),
        ("수출 현황", True), (" ".join(d["sentences"]["current_position"]), False),
    ]
    fill(box, entries)
    cap = get_shape_by_name(new_slide, "TextBox 10")
    set_caption(cap, f"검색 옵션 :광종 : {d['applied_filters']['mineral']}, 수입, {year(d['applied_filters']['start_date'])}, 국가필터: {d['filter_country']}")
    table = get_shape_by_name(new_slide, "표 6").table
    km = d["key_metrics"]
    set_table_value(table, "수입총액", "약 " + fmt(mid(km, "import_total_amount")["value"] / 1e8) + "억")
    for row_label in ("1위 수입국 비중", "2위 수입국 비중", "3위 수입국 비중", "상위3국 수입비중", "상위5국 수입비중"):
        clear_table_value(table, row_label)
    set_table_value(table, "수출총액", "약 " + fmt(mid(km, "export_total_amount")["value"] / 1e8) + "억")
    set_table_value(table, "수입 대비 수출 비율", pct(mid(km, "export_import_ratio_pct")["value"]))
    clear_table_value(table, "1위 수출국 비중")
    move_slide(p, len(list(p.slides._sldIdLst)) - 1, map_korea_idx + 1)

    # map_korea 생산품유형 필터(범위필터) — 위 슬라이드 삽입으로 +1 밀림
    d = DATA["map_korea_scope_filter"]
    base = map_korea_idx + 1
    new_slide = duplicate_slide(p, base)
    set_title(new_slide, "국내수급지도 - 핵심광물지도 (생산품유형 필터)")
    box = get_shape_by_name(new_slide, "TextBox 4")
    entries = [
        ("수입 현황", True), (" ".join(d["sentences"]["core_diagnosis"]), False),
        ("수입 집중도", True), (" ".join(d["sentences"]["major_changes"]), False),
        ("수출 현황", True), (" ".join(d["sentences"]["current_position"]), False),
    ]
    fill(box, entries)
    cap = get_shape_by_name(new_slide, "TextBox 10")
    set_caption(cap, f"검색 옵션 :광종 : {d['applied_filters']['mineral']}, 수입, {year(d['applied_filters']['start_date'])}, 생산품유형: {d['applied_filters']['scope_filter']}")
    table = get_shape_by_name(new_slide, "표 6").table
    km = d["key_metrics"]
    set_table_value(table, "수입총액", "약 " + fmt(mid(km, "import_total_amount")["value"] / 1e8) + "억")
    set_table_value(table, "1위 수입국 비중", pct(mid(km, "top1_import_share_pct")["value"]))
    set_table_value(table, "2위 수입국 비중", pct(mid(km, "top2_import_share_pct")["value"]))
    top3_entries = [m for m in km if m["id"] == "top3_import_share_pct"]
    set_table_value(table, "3위 수입국 비중", pct(top3_entries[0]["value"]))
    set_table_value(table, "상위3국 수입비중", pct(top3_entries[1]["value"]))
    set_table_value(table, "상위5국 수입비중", pct(mid(km, "top5_import_share_pct")["value"]))
    set_table_value(table, "수출총액", "약 " + fmt(mid(km, "export_total_amount")["value"] / 1e8) + "억")
    set_table_value(table, "수입 대비 수출 비율", pct(mid(km, "export_import_ratio_pct")["value"]))
    set_table_value(table, "1위 수출국 비중", pct(mid(km, "top1_export_share_pct")["value"]))
    move_slide(p, len(list(p.slides._sldIdLst)) - 1, base + 1)

    # map_global 수출입국가(komis_route_share_response) 옵션
    map_global_idx2 = map_global_idx + 2
    d = DATA["map_global_route_share"]
    new_slide = duplicate_slide(p, map_global_idx2)
    set_title(new_slide, "글로벌수급지도 - 핵심광물지도 (수출입국가 옵션)")
    box = get_shape_by_name(new_slide, "TextBox 4")
    entries = [
        ("글로벌 교역 현황", True), (" ".join(d["sentences"]["core_diagnosis"]), False),
        ("주요 교역 루트", True), (" ".join(d["sentences"]["major_changes"][:-1]), False),
        ("한국 관련 루트", True), (d["sentences"]["major_changes"][-1], False),
        ("수출입국가 옵션 추가 정보", True),
        (
            "komis_route_share_response(수출입국가 상세)를 더 넣으면 구조화 데이터"
            "(detailed_metrics)에 루트별 자국 집계총액 대비 비중이 추가된다 — 예: "
            + "; ".join(
                f"{m['label']} {fmt(m['value'])}%"
                for m in d["detailed_metrics"]
                if m["id"].startswith("route_share_")
            )[:220]
            + " 등. 본문 서술문에는 반영되지 않는다(설계상 표/데이터 전용).",
            False,
        ),
    ]
    fill(box, entries)
    cap = get_shape_by_name(new_slide, "TextBox 10")
    set_caption(cap, f"검색 옵션 :광종 : {d['applied_filters']['mineral']}, 수입, {year(d['applied_filters']['start_date'])}, 수출입국가: 상세(komis_route_share_response)")
    table = get_shape_by_name(new_slide, "표 6").table
    km = d["key_metrics"]
    set_table_value(table, "세계 교역 총액", "약 " + fmt(mid(km, "total_amount")["value"] / 1e8) + "억")
    set_table_value(table, "1위 루트 비중", pct(mid(km, "top1_share_pct")["value"]))
    set_table_value(table, "상위3루트 비중", pct(mid(km, "top3_share_pct")["value"]))
    set_table_value(table, "상위5루트 비중", pct(mid(km, "top5_share_pct")["value"]))
    move_slide(p, len(list(p.slides._sldIdLst)) - 1, map_global_idx2 + 1)

    # map_mineral 매장량/생산량 교차비교
    map_mineral_idx2 = map_mineral_idx + 3
    d = DATA["map_mineral_cross"]
    new_slide = duplicate_slide(p, map_mineral_idx2)
    set_title(new_slide, "광물지도 - 핵심광물지도 (매장량·생산량 교차비교)")
    box = get_shape_by_name(new_slide, "TextBox 4")
    major = d["sentences"]["major_changes"]
    entries = [
        ("세계 매장량 현황", True), (" ".join(d["sentences"]["core_diagnosis"]), False),
        ("국가별 순위 및 변화(교차비교 포함)", True), (" ".join(major[:-1]), False),
        ("주요 변화", True), (major[-1], False),
    ]
    fill(box, entries)
    cap = get_shape_by_name(new_slide, "TextBox 10")
    set_caption(cap, f"검색 옵션 :광종 : {d['applied_filters']['mineral']}, 매장량, {d['applied_filters']['start_year']}~{d['applied_filters']['end_year']}, 교차비교: 생산량(komis_snapshot_response)")
    table = get_shape_by_name(new_slide, "표 6").table
    km = d["key_metrics"]
    set_table_value(table, "현재 세계 매장량", "약 " + fmt(mid(km, "current_world_total")["value"] / 1e8) + "억")
    set_table_value(table, "조회기간 세계합계 변화율", pct(mid(km, "period_world_total_change")["value"] * 100))
    set_table_value(table, "1위 국가", mid(km, "top_country")["value"])
    set_table_value(table, "1위 국가 비중", pct(mid(km, "top_country_share")["value"] * 100))
    set_table_value(table, "상위 3개국 비중", pct(mid(km, "cr3")["value"] * 100))
    set_table_value(table, "상위 5개국 비중", pct(mid(km, "cr5")["value"] * 100))
    set_table_value(table, "1·2위 비중 차이", pct(mid(km, "top_two_share_gap")["value"] * 100))
    set_table_value(table, "최대 감소 국가", mid(km, "max_decrease_country")["value"])
    set_table_value(table, "전년 대비 변화율", pct(mid(km, "latest_year_total_change")["value"] * 100))
    move_slide(p, len(list(p.slides._sldIdLst)) - 1, map_mineral_idx2 + 1)

    p.save(path)
    print("저장 완료:", path, "| 총 슬라이드", len(p.slides))


if __name__ == "__main__":
    v9 = find_pptx("v9")
    v10 = os.path.join(D, os.path.basename(v9).replace("v9", "v10"))
    shutil.copy(v9, v10)
    build(v10)
