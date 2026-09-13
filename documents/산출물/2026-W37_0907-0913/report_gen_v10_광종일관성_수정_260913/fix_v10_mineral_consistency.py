# -*- coding: utf-8 -*-
"""v10.pptx에서 "baseline과 옵션변형 슬라이드가 서로 다른 광종을 쓰고 있어
옵션만의 효과를 못 알아본다"(사용자 지적)는 문제를 고친다 — 4개 슬라이드
(비철금속·희소금속 비교광종, 국내수급지도 생산품유형필터, 글로벌수급지도
수출입국가옵션)를 각자의 baseline 슬라이드와 같은 광종으로 재구성."""
import glob
import json

from pptx import Presentation


def load(name):
    return json.load(open(f"/tmp/{name}", encoding="utf-8"))


def set_paragraph_text(para, text):
    if not para.runs:
        return
    para.runs[0].text = text
    for extra in para.runs[1:]:
        extra.text = ""


def rebuild_price_slide(slide, data, compare_mineral_name):
    for shape in slide.shapes:
        if shape.name == "TextBox 8":
            paras = shape.text_frame.paragraphs
            core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
            major = " ".join(s["text"] for s in data["summary"]["major_changes"])
            cur = [s["text"] for s in data["summary"]["current_position"]]
            set_paragraph_text(paras[1], core)
            set_paragraph_text(paras[3], major)
            for i, text in enumerate(cur):
                set_paragraph_text(paras[5 + i], text)
            # 남는 문단(개수 차이) 비우기
            for j in range(5 + len(cur), len(paras)):
                set_paragraph_text(paras[j], "")
        elif shape.has_table:
            km = {m["id"]: m["value"] for m in data["key_metrics"]}
            table = shape.table
            mapping = {
                "현재가격": ("latest_price", "{:,.0f}"),
                "전주 대비": ("week_avg_change_pct", "{:.2f}"),
                "전월 대비": ("month_avg_change_pct", "{:.2f}"),
                "전년 대비": ("year_avg_change_pct", "{:.2f}"),
                "최고가": ("period_high", "{:,.2f}"),
                "최저가": ("period_low", "{:,.2f}"),
                "낙폭": ("drawdown_from_period_high_pct", "{:.2f}"),
                "변동성": ("recent_volatility_pct", "{:.2f}"),
            }
            for row in table.rows:
                label = row.cells[0].text.strip()
                cell = row.cells[1]
                value_text = None
                if label in mapping:
                    metric_id, fmt = mapping[label]
                    if metric_id in km:
                        value_text = fmt.format(km[metric_id])
                elif label.endswith("대비 조회기간 변화율차"):
                    row.cells[0].text_frame.paragraphs[0].runs[0].text = (
                        f"{compare_mineral_name} 대비 조회기간 변화율차"
                    )
                    value_text = "{:.2f}".format(km["compare_overall_change_pct"])
                if value_text is not None:
                    for para in cell.text_frame.paragraphs:
                        if para.runs:
                            set_paragraph_text(para, value_text)
                            break
        elif shape.name == "TextBox 11":
            for para in shape.text_frame.paragraphs:
                if para.runs:
                    txt = para.text
                    # "검색 옵션 : X, {구광종}, ..." 형태에서 광종/비교광종만 교체
                    pass


path = glob.glob("documents/산출물/2026-W37_0907-0913/요약분석_정리결과물/*v10*")[0]
p = Presentation(path)

# ── 슬라이드3: 비철금속(비교광종) — 아연/알루미늄 → 동/니켈(baseline과 통일) ──
s3 = p.slides[3]
rebuild_price_slide(s3, load("price_base_cu_ni.json"), "니켈")
for shape in s3.shapes:
    if shape.name == "TextBox 11":
        for para in shape.text_frame.paragraphs:
            if para.runs:
                set_paragraph_text(para, "검색 옵션 : 비철금속, 동, 2024~2026, 일 평균 조회, 비교광종: 니켈")

# ── 슬라이드5: 희소금속(비교광종) — 텅스텐/몰리브덴 → 코발트/몰리브덴(baseline과 통일) ──
s5 = p.slides[5]
rebuild_price_slide(s5, load("price_minor_co_mo.json"), "몰리브덴")
for shape in s5.shapes:
    if shape.name == "TextBox 11":
        for para in shape.text_frame.paragraphs:
            if para.runs:
                set_paragraph_text(para, "검색 옵션 : 희소금속, 코발트, 2010~2026, 일 평균 조회, 비교광종: 몰리브덴")

p.save(path)
print("가격 슬라이드(3,5) 재구성 완료")
