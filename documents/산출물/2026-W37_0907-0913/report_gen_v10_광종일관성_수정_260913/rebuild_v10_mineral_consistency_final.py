# -*- coding: utf-8 -*-
"""v10.pptx 광종 일관성 수정(슬라이드3·5·15·18)을 처음부터 다시, 한 스크립트로
일관되게 재생성한다.

2026-09-13 사용자 지적으로 재작성 — 원래는 슬라이드3/5를 만드는 스크립트
(fix_v10_mineral_consistency.py)의 숫자서식 함수가 `"{:,.0f}"`(항상 정수)를
써서 코발트 현재가 53.46을 "53"으로, 동 최고가 14850.0을 "14,850.00"으로
잘못 냈다 — **report_gen API 응답(key_metrics.value)은 처음부터 53.46/
14850.0으로 정확했다, API 버그가 아니라 이 슬라이드 빌드 스크립트의 서식
함수 버그였다.** 처음 발견했을 때 그 2개 슬라이드 표 셀만 별도 커맨드로
땜빵 수정했는데, 이건 "슬라이드는 report_gen 결과물을 복붙만 해야 한다"는
원칙을 어긴 것 — 빌드 스크립트 자체(`smart_fmt`)를 고치지 않고 산출물만
손으로 고쳤었다. 이번엔 서식 함수를 스크립트에 제대로 박아 넣고, 4개
슬라이드(3·5·15·18) 전부 이 스크립트 하나로 처음부터 다시 만든다 — 이후
어떤 슬라이드 텍스트/표 값도 이 스크립트 밖에서 손으로 고치지 않는다."""
import glob
import json

from pptx import Presentation


def load(path):
    return json.load(open(path, encoding="utf-8"))


def set_paragraph_text(para, text):
    if not para.runs:
        return
    para.runs[0].text = text
    for extra in para.runs[1:]:
        extra.text = ""


def smart_fmt(v):
    """report_gen 기존 슬라이드들의 표기 관례 — 정수면 콤마만, 소수면 2자리."""
    if float(v) == int(v):
        return f"{int(v):,}"
    return f"{v:,.2f}"


def pct_fmt(v):
    return f"{v:.2f}"


def eok_fmt(v):
    return "약 " + f"{v / 1e8:,.2f}" + "억"


EVIDENCE = "documents/산출물/2026-W37_0907-0913/report_gen_v10_광종일관성_수정_260913"

# ── 슬라이드3·5 공통: price_* 비교광종 슬라이드 재구성 ──
PRICE_TABLE_MAPPING = {
    "현재가격": ("latest_price", smart_fmt),
    "전주 대비": ("week_avg_change_pct", pct_fmt),
    "전월 대비": ("month_avg_change_pct", pct_fmt),
    "전년 대비": ("year_avg_change_pct", pct_fmt),
    "연속 추세": ("price_streak_length", lambda v: str(int(v))),
    "최고가": ("period_high", smart_fmt),
    "최저가": ("period_low", smart_fmt),
    "낙폭": ("drawdown_from_period_high_pct", pct_fmt),
    "변동성": ("recent_volatility_pct", pct_fmt),
}


def rebuild_price_slide(slide, data, compare_mineral_name, caption):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = " ".join(s["text"] for s in data["summary"]["major_changes"])
    cur = [s["text"] for s in data["summary"]["current_position"]]
    km = {m["id"]: m["value"] for m in data["key_metrics"]}

    for shape in slide.shapes:
        if shape.name == "TextBox 8":
            paras = shape.text_frame.paragraphs
            set_paragraph_text(paras[1], core)
            set_paragraph_text(paras[3], major)
            for i, text in enumerate(cur):
                set_paragraph_text(paras[5 + i], text)
            for j in range(5 + len(cur), len(paras)):
                set_paragraph_text(paras[j], "")
        elif shape.has_table:
            for row in shape.table.rows:
                label = row.cells[0].text.strip()
                cell = row.cells[1]
                value_text = None
                if label in PRICE_TABLE_MAPPING:
                    metric_id, fmt_fn = PRICE_TABLE_MAPPING[label]
                    if metric_id in km:
                        value_text = fmt_fn(km[metric_id])
                elif label.endswith("대비 조회기간 변화율차"):
                    row.cells[0].text_frame.paragraphs[0].runs[0].text = (
                        f"{compare_mineral_name} 대비 조회기간 변화율차"
                    )
                    value_text = pct_fmt(km["compare_overall_change_pct"])
                if value_text is not None:
                    for para in cell.text_frame.paragraphs:
                        if para.runs:
                            set_paragraph_text(para, value_text)
                            break
        elif shape.name == "TextBox 11":
            for para in shape.text_frame.paragraphs:
                if para.runs:
                    set_paragraph_text(para, caption)


# ── 슬라이드15: map_korea 생산품유형 필터 ──
def rebuild_map_korea_scope_slide(slide, data, caption):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = " ".join(s["text"] for s in data["summary"]["major_changes"])
    cur = " ".join(s["text"] for s in data["summary"]["current_position"])

    km_by_label: dict[str, list[float]] = {}
    for m in data["key_metrics"]:
        km_by_label.setdefault(m["label"], []).append(m["value"])
    consumed: dict[str, int] = {}

    for shape in slide.shapes:
        if shape.name == "TextBox 4":
            paras = shape.text_frame.paragraphs
            set_paragraph_text(paras[1], core)
            set_paragraph_text(paras[3], major)
            set_paragraph_text(paras[5], cur)
        elif shape.has_table:
            for row in shape.table.rows:
                label = row.cells[0].text.strip()
                if label not in km_by_label:
                    continue
                idx = consumed.get(label, 0)
                if idx >= len(km_by_label[label]):
                    continue
                value = km_by_label[label][idx]
                consumed[label] = idx + 1
                text = eok_fmt(value) if label in ("수입총액", "수출총액") else pct_fmt(value)
                for para in row.cells[1].text_frame.paragraphs:
                    if para.runs:
                        set_paragraph_text(para, text)
                        break
        elif shape.name == "TextBox 10":
            for para in shape.text_frame.paragraphs:
                if para.runs:
                    set_paragraph_text(para, caption)


# ── 슬라이드18: map_global 수출입국가옵션 ──
def route_fmt(v):
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def rebuild_map_global_route_slide(slide, data, caption):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = [s["text"] for s in data["summary"]["major_changes"]]
    route_text = (
        "komis_route_share_response(수출입국가 상세)를 더 넣으면 구조화 데이터"
        "(detailed_metrics)에 루트별 자국 집계총액 대비 비중이 추가된다 — 예: "
        + "; ".join(
            f"{m['label']} {route_fmt(m['value'])}%"
            for m in data["detailed_metrics"]
            if m["id"].startswith("route_share_")
        )[:220]
        + " 등. 본문 서술문에는 반영되지 않는다(설계상 표/데이터 전용)."
    )
    km = {m["id"]: m["value"] for m in data["key_metrics"]}

    for shape in slide.shapes:
        if shape.name == "TextBox 4":
            paras = shape.text_frame.paragraphs
            set_paragraph_text(paras[1], core)
            set_paragraph_text(paras[3], " ".join(major[:3]))
            set_paragraph_text(paras[5], major[3] if len(major) > 3 else "")
            set_paragraph_text(paras[7], route_text)
        elif shape.has_table:
            mapping = {
                "세계 교역 총액": ("total_amount", eok_fmt),
                "1위 루트 비중": ("top1_share_pct", pct_fmt),
                "상위3루트 비중": ("top3_share_pct", pct_fmt),
                "상위5루트 비중": ("top5_share_pct", pct_fmt),
            }
            for row in shape.table.rows:
                label = row.cells[0].text.strip()
                if label in mapping:
                    metric_id, fmt_fn = mapping[label]
                    text = fmt_fn(km[metric_id])
                    for para in row.cells[1].text_frame.paragraphs:
                        if para.runs:
                            set_paragraph_text(para, text)
                            break
        elif shape.name == "TextBox 10":
            for para in shape.text_frame.paragraphs:
                if para.runs:
                    set_paragraph_text(para, caption)


path = glob.glob("documents/산출물/2026-W37_0907-0913/요약분석_정리결과물/*v10*")[0]
p = Presentation(path)

rebuild_price_slide(
    p.slides[3], load(f"{EVIDENCE}/price_base_cu_ni.json"), "니켈",
    "검색 옵션 : 비철금속, 동, 2024~2026, 일 평균 조회, 비교광종: 니켈",
)
rebuild_price_slide(
    p.slides[5], load(f"{EVIDENCE}/price_minor_co_mo.json"), "몰리브덴",
    "검색 옵션 : 희소금속, 코발트, 2010~2026, 일 평균 조회, 비교광종: 몰리브덴",
)
rebuild_map_korea_scope_slide(
    p.slides[15], load(f"{EVIDENCE}/cu_map_korea_scope_verified.json"),
    "검색 옵션 :광종 : 동, 수입, 2026, 생산품유형: 기초금속",
)
rebuild_map_global_route_slide(
    p.slides[18], load(f"{EVIDENCE}/li_2026_map_global_route_share_verified.json"),
    "검색 옵션 :광종 : 리튬, 수입, 2026, 수출입국가: 상세(komis_route_share_response)",
)

p.save(path)
print("슬라이드 3·5·15·18 스크립트 단일 실행으로 재생성 완료:", path)
