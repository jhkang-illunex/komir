# -*- coding: utf-8 -*-
"""v10.pptx -> v11.pptx 전체 재생성.

사용자 지시: "v11번으로 기존에 추가 안된 메뉴까지 다시 추가해서 재작성"
+ "광물전망지표(광물종합지수/시장지수/수급지수)" — 수급동향지표를
기본(옵션 없음)/옵션추가(패널차트) 2개 슬라이드로 분리 신설. 겸사겸사
같은 스크립트로 모든 슬라이드를 report_gen 최신 출력(2026-09-13 소수점
트림 규칙 반영)으로 다시 채워, 남아있던 트레일링 제로(45.70 등)를 전부
없앤다 — 이 스크립트 하나가 v11.pptx의 유일한 생성 경로다(복붙만,
이후 슬라이드를 스크립트 밖에서 손으로 고치지 않는다)."""
import copy
import glob
import json
import sys

sys.path.insert(0, "inhouse/report_gen")
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402

sys.path.insert(0, "inhouse/streamlit_demo")
import komis_fetch  # noqa: E402

from pptx import Presentation

EVID37 = "documents/산출물/2026-W37_0907-0913"
SVC = AnalysisSummaryService(None, llm=None)


def load(path):
    return json.load(open(path, encoding="utf-8"))


def run(page_id, **kwargs):
    req = AnalysisSummaryRequest(request_id="v11-build", page_id=page_id, **kwargs)
    return json.loads(SVC.analyze(req).model_dump_json())


# ────────────────────────────────────────────────────────────────
# 서식 헬퍼 — report_gen 중앙 포매터(_number/_quantity/_format_metric_row,
# 2026-09-13 트림 규칙 신설)와 동일 규칙을 슬라이드 표 셀에도 적용한다.
# ────────────────────────────────────────────────────────────────


def smart_fmt(v):
    if float(v) == int(v):
        return f"{int(v):,}"
    text = f"{v:,.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def pct_fmt(v):
    text = f"{v:.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def eok_fmt(v):
    return "약 " + smart_fmt(v / 1e8) + "억"


def man_fmt(v):
    return "약 " + smart_fmt(v / 1e4) + "만"


def compact_currency_fmt(v):
    """report_gen의 compact_fact() 자동 축약 규칙과 같은 임계값(1억)으로
    억/만 스케일을 자동 선택한다 — 국가필터처럼 총액이 작아지는 경우
    억 단위로 고정하면(예: 0.04억) 서술문(380.21만)과 표기가 어긋난다."""
    if abs(v) >= 1e8:
        return eok_fmt(v)
    return man_fmt(v)


def metric_row_value(metric):
    value = metric["value"]
    unit = metric.get("unit")
    if value is None:
        return "-"
    if unit == "ratio" and isinstance(value, (int, float)):
        return pct_fmt(value * 100)
    if isinstance(value, float):
        return smart_fmt(value)
    return str(value)


def set_paragraph_text(para, text):
    if not para.runs:
        return
    para.runs[0].text = text
    for extra in para.runs[1:]:
        extra.text = ""


def fill_body(shape, entries):
    """entries: [(text, is_header_bold_or_None), ...] — 기존 문단 재사용,
    모자라면 add_paragraph, 남으면 비운다. 서식(글꼴 크기 등)은 기존
    문단의 것을 그대로 쓴다(요청 없으면 bold만 조정)."""
    tf = shape.text_frame
    existing = list(tf.paragraphs)
    size = None
    for para in existing:
        if para.runs:
            size = para.runs[0].font.size
            break
    for i, (text, is_bold) in enumerate(entries):
        if i < len(existing):
            para = existing[i]
            if not para.runs:
                para.add_run()
            set_paragraph_text(para, text)
            if is_bold is not None:
                para.runs[0].font.bold = is_bold
            if size is not None and para.runs[0].font.size is None:
                para.runs[0].font.size = size
        else:
            para = tf.add_paragraph()
            run = para.add_run()
            run.text = text
            if size is not None:
                run.font.size = size
            run.font.bold = is_bold
    for j in range(len(entries), len(existing)):
        set_paragraph_text(existing[j], "")


def set_table_by_label(table, mapping, extra_label_rewrite=None):
    """mapping: {row_label: metric_dict-or-str}. extra_label_rewrite:
    optional (predicate(label)->bool, new_label_fn(label)->str) for rows
    like "{비교광종} 대비 조회기간 변화율차"."""
    for row in table.rows:
        label = row.cells[0].text.strip()
        text = None
        if label in mapping:
            v = mapping[label]
            text = v if isinstance(v, str) else metric_row_value(v)
        elif extra_label_rewrite is not None:
            predicate, new_label_fn, value = extra_label_rewrite
            if predicate(label):
                row.cells[0].text_frame.paragraphs[0].runs[0].text = new_label_fn(label)
                text = metric_row_value(value)
        if text is not None:
            for para in row.cells[1].text_frame.paragraphs:
                if para.runs:
                    set_paragraph_text(para, text)
                    break


def km_by_id(data):
    return {m["id"]: m for m in data["key_metrics"]}


def km_by_label(data):
    out = {}
    for m in data["key_metrics"]:
        out.setdefault(m["label"], []).append(m)
    return out


def set_caption(shape, text):
    for para in shape.text_frame.paragraphs:
        if para.runs:
            set_paragraph_text(para, text)
            return


def set_title(slide, text):
    for shape in slide.shapes:
        if shape.name == "제목 1":
            tf = shape.text_frame
            if tf.paragraphs and tf.paragraphs[0].runs:
                set_paragraph_text(tf.paragraphs[0], text)
                for extra in tf.paragraphs[1:]:
                    set_paragraph_text(extra, "")
            return


def shape_by_name(slide, name):
    for shape in slide.shapes:
        if shape.name == name:
            return shape
    raise KeyError(name)


def duplicate_slide(prs, index):
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


# ────────────────────────────────────────────────────────────────
# 슬라이드 유형별 재구성 함수
# ────────────────────────────────────────────────────────────────


def rebuild_price_slide(slide, data, caption, compare_mineral_name=None):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = " ".join(s["text"] for s in data["summary"]["major_changes"])
    cur = [s["text"] for s in data["summary"]["current_position"]]

    box = shape_by_name(slide, "TextBox 8")
    entries = [("가격 요약", True), (core, False), ("최근 변화", True), (major, False), ("변동 구간", True)]
    entries += [(t, False) for t in cur]
    fill_body(box, entries)

    km = km_by_id(data)
    mapping = {
        "현재가격": km.get("latest_price"),
        "전주 대비": km.get("week_avg_change_pct"),
        "전월 대비": km.get("month_avg_change_pct"),
        "전년 대비": km.get("year_avg_change_pct"),
        "연속 추세": km.get("price_streak_length"),
        "최고가": km.get("period_high"),
        "최저가": km.get("period_low"),
        "낙폭": km.get("drawdown_from_period_high_pct"),
        "변동성": km.get("recent_volatility_pct"),
    }
    mapping = {k: v for k, v in mapping.items() if v is not None}
    extra = None
    if compare_mineral_name and "compare_overall_change_pct" in km:
        extra = (
            lambda label: label.endswith("대비 조회기간 변화율차"),
            lambda label: f"{compare_mineral_name} 대비 조회기간 변화율차",
            km["compare_overall_change_pct"],
        )
    table = shape_by_name(slide, "표 10").table
    set_table_by_label(table, mapping, extra)

    try:
        cap = shape_by_name(slide, "TextBox 11")
        set_caption(cap, caption)
    except KeyError:
        pass


def _indicator_score_table(slide, data):
    km = km_by_id(data)
    mapping = {
        "현재 점수": km.get("current_score"),
        "현재 단계": km.get("current_grade"),
        "최근 점수 변화": km.get("latest_score_change"),
        "현재 단계 연속기간": km.get("current_grade_streak"),
        "단계 전환 횟수": km.get("grade_transition_count"),
        "최대 월간 점수 변화": km.get("largest_monthly_score_change"),
        "최근 가격 변화율": km.get("latest_price_change_rate"),
        "조회기간 평균 점수": km.get("period_average_score"),
    }
    mapping = {k: v for k, v in mapping.items() if v is not None}
    table = shape_by_name(slide, "표 10").table
    set_table_by_label(table, mapping)


def rebuild_indicator_market_slide(slide, data, caption):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = " ".join(s["text"] for s in data["summary"]["major_changes"])
    cur = " ".join(s["text"] for s in data["summary"]["current_position"])

    box = shape_by_name(slide, "TextBox 8")
    entries = [("현재 단계", True), (core, False), ("단계 변화", True), (major, False), ("주요 변동 특징", True), (cur, False)]
    fill_body(box, entries)
    _indicator_score_table(slide, data)
    set_caption(shape_by_name(slide, "TextBox 11"), caption)


def rebuild_indicator_supply_slide(slide, data, caption, with_aux):
    """슬라이드12(0-idx) 원본 템플릿 — 헤더0이 "현재 단계: {등급} ({점수}점)"
    동적 문자열, "구성요소 변화" 절은 문장마다 빈 문단 1개로 구분돼 있다.
    기본(with_aux=False)은 그 절에 가격리스크 문장 1개만, 옵션추가
    (with_aux=True)는 komis_snapshot_response로 늘어난 문장 전부를 채운다."""
    km = km_by_id(data)
    score = km["current_score"]["value"]
    grade = km["current_grade"]["value"]
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = " ".join(s["text"] for s in data["summary"]["major_changes"])
    cur = [s["text"] for s in data["summary"]["current_position"]]

    box = shape_by_name(slide, "TextBox 8")
    entries = [
        (f"현재 단계: {grade} ({pct_fmt(score)}점)", True), ("", False),
        ("현재 수급 단계", True), (core, False), ("", False),
        ("단계 변화", True), (major, False), ("", False), ("", False),
        ("구성요소 변화", True),
    ]
    for i, t in enumerate(cur):
        entries.append((t, False))
        if i < len(cur) - 1:
            entries.append(("", False))
    fill_body(box, entries)
    _indicator_score_table(slide, data)
    set_caption(shape_by_name(slide, "TextBox 11"), caption)


def rebuild_map_korea_slide(slide, data, caption, scope=None):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = [s["text"] for s in data["summary"]["major_changes"]]
    cur = " ".join(s["text"] for s in data["summary"]["current_position"])

    box = shape_by_name(slide, "TextBox 4")
    # 2026-09-13 사용자 지적 — "수입/수출 옵션에서 데이터 변화량이
    # 수입/수출 현황에 표시돼야 하는데 없다". KOMIS map_korea 화면은
    # "수입규모 추이" 차트를 항상 같이 보여주는 기본 요소라(옵션 아님,
    # §직전 수급동향지표 교훈과 같은 결) `komis_history_responses`로
    # 과거 연도 데이터를 실어야 report_gen의 `trade_scale_trend_fact`가
    # "최근 5개년 수입/수출액 추이" 문장을 major_changes에 추가한다 —
    # 그 문장이 있으면 "수입/수출 추이" 절을 새로 만들어 담고, 없으면
    # (히스토리 데이터를 못 구한 경우) 기존 3절 구조로 폴백한다.
    trend_idx = next((i for i, m in enumerate(major) if m.startswith("최근") and "개년" in m and "추이는" in m), None)
    if trend_idx is not None:
        concentration = [m for i, m in enumerate(major) if i != trend_idx]
        entries = [
            ("수입 현황", True), (core, False),
            ("수입 집중도", True), (" ".join(concentration), False),
            ("수입/수출 추이", True), (major[trend_idx], False),
            ("수출 현황", True), (cur, False),
        ]
    else:
        entries = [("수입 현황", True), (core, False), ("수입 집중도", True), (" ".join(major), False), ("수출 현황", True), (cur, False)]
    fill_body(box, entries)

    labels = km_by_label(data)
    table = shape_by_name(slide, "표 6").table
    consumed = {}

    def next_metric(label):
        idx = consumed.get(label, 0)
        vals = labels.get(label) or []
        if idx >= len(vals):
            return None
        consumed[label] = idx + 1
        return vals[idx]

    for row in table.rows:
        label = row.cells[0].text.strip()
        if label == "지표":
            continue
        m = next_metric(label)
        if m is None:
            text = "-"
        else:
            text = compact_currency_fmt(m["value"]) if label in ("수입총액", "수출총액") else metric_row_value(m)
        for para in row.cells[1].text_frame.paragraphs:
            if para.runs:
                set_paragraph_text(para, text)
                break

    cap = shape_by_name(slide, "TextBox 10")
    set_caption(cap, caption)


def rebuild_map_global_baseline_slide(slide, data, caption, extra_body_title=None):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = [s["text"] for s in data["summary"]["major_changes"]]

    box = shape_by_name(slide, "TextBox 4")
    body_head = "글로벌 교역 현황" if extra_body_title is None else f"글로벌 교역 현황{extra_body_title}"
    # major_changes 마지막 문장이 항상 "한국 관련 루트"(대한민국이 포함된
    # 교역 루트...) — 나머지는 전부 "주요 교역 루트" 절로 묶는다. 국가
    # 필터로 루트가 1개뿐이면 major가 2개(1위 문장+한국관련 문장)뿐이라
    # 고정 인덱스([:3]/[3])가 아니라 "마지막 1개 vs 나머지"로 일반화한다.
    entries = [
        (body_head, True), (core, False),
        ("주요 교역 루트", True), (" ".join(major[:-1]) if len(major) > 1 else (major[0] if major else ""), False),
        ("한국 관련 루트", True), (major[-1] if major else "", False),
    ]
    fill_body(box, entries)

    km = km_by_id(data)
    table = shape_by_name(slide, "표 6").table
    mapping = {
        "세계 교역 총액": compact_currency_fmt(km["total_amount"]["value"]),
        "1위 루트 비중": metric_row_value(km["top1_share_pct"]) if "top1_share_pct" in km else "-",
        "상위3루트 비중": metric_row_value(km["top3_share_pct"]) if "top3_share_pct" in km else "-",
        "상위5루트 비중": metric_row_value(km["top5_share_pct"]) if "top5_share_pct" in km else "-",
    }
    set_table_by_label(table, mapping)
    cap = shape_by_name(slide, "TextBox 10")
    set_caption(cap, caption)


def route_pct_fmt(v):
    return smart_fmt(v)


def rebuild_map_global_route_slide(slide, data, caption):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = [s["text"] for s in data["summary"]["major_changes"]]
    route_text = (
        "komis_route_share_response(수출입국가 상세)를 더 넣으면 구조화 데이터"
        "(detailed_metrics)에 루트별 자국 집계총액 대비 비중이 추가된다 — 예: "
        + "; ".join(
            f"{m['label']} {route_pct_fmt(m['value'])}%"
            for m in data["detailed_metrics"]
            if m["id"].startswith("route_share_")
        )[:220]
        + " 등. 본문 서술문에는 반영되지 않는다(설계상 표/데이터 전용)."
    )

    box = shape_by_name(slide, "TextBox 4")
    entries = [
        ("글로벌 교역 현황", True), (core, False),
        ("주요 교역 루트", True), (" ".join(major[:3]), False),
        ("한국 관련 루트", True), (major[3] if len(major) > 3 else "", False),
        ("수출입국가 옵션 추가 정보", True), (route_text, False),
    ]
    fill_body(box, entries)

    km = km_by_id(data)
    table = shape_by_name(slide, "표 6").table
    mapping = {
        "세계 교역 총액": eok_fmt(km["total_amount"]["value"]),
        "1위 루트 비중": metric_row_value(km["top1_share_pct"]),
        "상위3루트 비중": metric_row_value(km["top3_share_pct"]),
        "상위5루트 비중": metric_row_value(km["top5_share_pct"]),
    }
    set_table_by_label(table, mapping)
    cap = shape_by_name(slide, "TextBox 10")
    set_caption(cap, caption)


def rebuild_map_mineral_slide(slide, data, caption, cross=False, total_row_label="현재 세계 매장량", table_scale="eok"):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = [s["text"] for s in data["summary"]["major_changes"]]

    box = shape_by_name(slide, "TextBox 4")
    label = "세계 생산량 현황" if data["applied_filters"]["measure"] == "production" else "세계 매장량 현황"
    header2 = "국가별 순위 및 변화(교차비교 포함)" if cross else "국가별 순위 및 변화"
    entries = [
        (label, True), (core, False),
        (header2, True), (" ".join(major[:-1]), False),
        ("주요 변화", True), (major[-1] if major else "", False),
    ]
    fill_body(box, entries)

    km = km_by_id(data)
    scale_fn = eok_fmt if table_scale == "eok" else man_fmt
    total_value = km["current_world_total"]["value"]
    for row in shape_by_name(slide, "표 6").table.rows:
        if row.cells[0].text.strip() in ("현재 세계 매장량", "현재 세계 생산량"):
            row.cells[0].text_frame.paragraphs[0].runs[0].text = total_row_label
            break
    mapping = {
        total_row_label: scale_fn(total_value),
        "조회기간 세계합계 변화율": metric_row_value(km["period_world_total_change"]),
        "1위 국가": metric_row_value(km["top_country"]),
        "1위 국가 비중": metric_row_value(km["top_country_share"]),
        "상위 3개국 비중": metric_row_value(km["cr3"]),
        "상위 5개국 비중": metric_row_value(km["cr5"]),
        "1·2위 비중 차이": metric_row_value(km["top_two_share_gap"]),
        "최대 감소 국가": metric_row_value(km["max_decrease_country"]),
        "전년 대비 변화율": metric_row_value(km["latest_year_total_change"]),
    }
    table = shape_by_name(slide, "표 6").table
    set_table_by_label(table, mapping)
    cap = shape_by_name(slide, "TextBox 10")
    set_caption(cap, caption)


def rebuild_composite_slide(slide, data, caption):
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    major = " ".join(s["text"] for s in data["summary"]["major_changes"])
    cur = " ".join(s["text"] for s in data["summary"]["current_position"])

    box = shape_by_name(slide, "TextBox 8")
    entries = [("지수 요약", True), (core, False), ("지수별 변화", True), (major, False), ("지수 위치", True), (cur, False)]
    fill_body(box, entries)

    km = km_by_id(data)
    table = shape_by_name(slide, "표 10").table
    mapping = {
        "현재 광물종합지수": km.get("current_composite_index"),
        "현재 메이저금속지수": km.get("current_major_metals_index"),
        "현재 희소금속지수": km.get("current_minor_metals_index"),
        "전주 대비": km.get("weekly_composite_change"),
    }
    mapping = {k: v for k, v in mapping.items() if v is not None}
    set_table_by_label(table, mapping)



# ────────────────────────────────────────────────────────────────
# 메인 — v10.pptx를 복사한 v11.pptx를 열어 슬라이드12를 복제(기본/옵션
# 추가 분리)한 뒤 전체 23슬라이드를 재구성한다.
# ────────────────────────────────────────────────────────────────

path = glob.glob(f"{EVID37}/요약분석_정리결과물/*v11*")[0]
p = Presentation(path)
assert len(p.slides) == 22, len(p.slides)

R = load("/tmp/v11_remaining_sources.json")

# 2·3 비철금속
rebuild_price_slide(p.slides[2], R["price_base_baseline"], "검색 옵션 : 비철금속, 동, 2024~2026, 일 평균 조회")
rebuild_price_slide(
    p.slides[3], R["price_base_cmp"], "검색 옵션 : 비철금속, 동, 2024~2026, 일 평균 조회, 비교광종: 니켈",
    compare_mineral_name="니켈",
)

# 4·5 희소금속
rebuild_price_slide(p.slides[4], R["price_minor_baseline"], "검색 옵션 : 희소금속, 코발트, 2010~2026, 일 평균 조회")
rebuild_price_slide(
    p.slides[5], R["price_minor_cmp"], "검색 옵션 : 희소금속, 코발트, 2010~2026, 일 평균 조회, 비교광종: 몰리브덴",
    compare_mineral_name="몰리브덴",
)

# 6·7 철에너지
rebuild_price_slide(p.slides[6], R["price_iron_baseline"], "검색 옵션 : 철에너지, 우라늄, 2024~2026, 일 평균 조회")
rebuild_price_slide(
    p.slides[7], R["price_iron_cmp"], "검색 옵션 : 철에너지, 우라늄, 2024~2026, 일 평균 조회, 비교광종: 유연탄",
    compare_mineral_name="유연탄",
)

# 8·9 기타
rebuild_price_slide(p.slides[8], R["price_other_baseline"], "검색 옵션 : 기타, 흑연, 2024~2026, 일 평균 조회")
rebuild_price_slide(
    p.slides[9], R["price_other_cmp"], "검색 옵션 : 기타, 흑연, 2024~2026, 일 평균 조회, 비교광종: 금",
    compare_mineral_name="금",
)

# 10 광물종합지수
rebuild_composite_slide(p.slides[10], R["indicator_composite"], "")

# 11 시장동향지표
rebuild_indicator_market_slide(p.slides[11], R["indicator_market"], "검색 옵션 : 동")

# 12 수급동향지표 — 2026-09-13 사용자 지적으로 "기본(옵션없음)/옵션추가"
# 2슬라이드 분리를 되돌린다: "수급 동향 지표는 komis_response가 들어간게
# 기본인데, 값이 없거나 할때만 표시 안되야 함" — 패널차트(komis_snapshot_
# response)는 compare_mineral·국가필터처럼 KOMIS 화면에서 사용자가 켜고
# 끄는 진짜 "옵션"이 아니라, 정상적으로 조회하면 늘 함께 오는 기본
# 데이터다. 구성요소가 안 보이는 경우는 "옵션을 안 넣어서"가 아니라
# 해당 요인의 원천 데이터가 그 광종에 한해 실제로 비어 있을 때뿐(예:
# 세계수급비율 subChart05가 일부 광종에서 빈 배열)이어야 한다 — 그래서
# "옵션추가" 버전(전체 구성요소 반영)을 유일한 정본으로 삼는다.
rebuild_indicator_supply_slide(p.slides[12], R["indicator_supply_aux"], "검색 옵션 : 동", with_aux=True)

# 13 국내수급지도 baseline
rebuild_map_korea_slide(p.slides[13], R["map_korea_baseline"], "검색 옵션 :광종 : 동, 수입, 2026")

# 14 국내수급지도 국가필터(버그 수정: sumIncmAmt 행단위 반영 누락)
rebuild_map_korea_slide(
    p.slides[14], R["map_korea_country_filter"],
    f"검색 옵션 :광종 : 동, 수입, 2026, 국가필터: {R['_country_filter_name']}",
)

# 15 국내수급지도 생산품유형필터
rebuild_map_korea_slide(
    p.slides[15], R["map_korea_scope"],
    "검색 옵션 :광종 : 동, 수입, 2026, 생산품유형: 기초금속",
)

# 16 글로벌수급지도 baseline(수입)
rebuild_map_global_baseline_slide(
    p.slides[16], R["map_global_import"],
    "검색 옵션 :광종 : 리튬, 수입, 2026, 수출입국가: 전체",
)

# 17 글로벌수급지도 수출옵션
rebuild_map_global_baseline_slide(
    p.slides[17], R["map_global_export"], "검색 옵션 :광종 : 리튬, 수출, 2026, 수출입국가: 전체",
    extra_body_title="(수출 탭)",
)

# 18 글로벌수급지도 수출입국가옵션(komis_route_share_response)
rebuild_map_global_route_slide(
    p.slides[18], R["map_global_route"],
    "검색 옵션 :광종 : 리튬, 수입, 2026, 수출입국가: 상세(komis_route_share_response)",
)

# 19(신규) 글로벌수급지도 수출입국가 필터(대한민국→인도네시아) — 사용자
# 지시: "20 페이지에 수출입 국가에 인도네시아/한국으로 수출/수입시
# 페이지를 추가해서 표시해주세요". "인도네시아(수출)→한국(수입)"은
# 2026년 리튬 데이터에 없어(라이브 조회 0건) 반대 방향으로 조회했다
# (baseline 5위 루트와 동일 건).
kr_id_raw = komis_fetch.fetch_map_global(
    "MNRL0001", period_field="year", start_period="2026", end_period="2026",
    trade_direction="import", export_country_name="대한민국", import_country_name="인도네시아",
)
kr_id_data = run("map_global", mineral="MNRL0001", mineral_name="리튬", komis_response=kr_id_raw["list_data"])
new_country_slide = duplicate_slide(p, 16)
move_slide(p, len(list(p.slides._sldIdLst)) - 1, 19)
set_title(p.slides[19], "글로벌수급지도 - 핵심광물지도 (수출입국가 필터: 대한민국→인도네시아)")
rebuild_map_global_baseline_slide(
    p.slides[19], kr_id_data,
    "검색 옵션 :광종 : 리튬, 수입, 2026, 수출국가: 대한민국, 수입국가: 인도네시아",
    extra_body_title="(국가필터)",
)

# 20 광물지도 baseline
rebuild_map_mineral_slide(
    p.slides[20], R["map_mineral_baseline"], "검색 옵션 :광종 : 동, 매장량, 2021~2025",
)

# 21 광물지도 교차비교
rebuild_map_mineral_slide(
    p.slides[21], R["map_mineral_cross"], "검색 옵션 :광종 : 동, 매장량, 2021~2025, 교차비교: 생산량(komis_snapshot_response)",
    cross=True,
)

# 22 광물지도 생산량검색
rebuild_map_mineral_slide(
    p.slides[22], R["map_mineral_production"], "검색 옵션 :광종 : 동, 생산량, 2021~2025",
    total_row_label="현재 세계 생산량", table_scale="man",
)

assert len(p.slides) == 23, len(p.slides)
p.save(path)
print("v11.pptx 저장 완료:", path, "| 슬라이드", len(p.slides))
