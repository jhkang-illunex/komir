# -*- coding: utf-8 -*-
"""v10.pptx -> v13.pptx 전체 재생성(2026-09-13 검수 정정판).

v13에서 바뀐 것(검수에서 찾은 슬라이드 스크립트 버그 3건):
1. 표 행 잔존값 — 매핑에 없는(=API가 그 지표를 안 낸) 행을 손대지 않아
   v10 값이 그대로 남았다(우라늄 "연속 추세 2"). 이제 그런 행은 "-"로 비운다.
2. 표 행 부재 — 템플릿 표에 없는 행(동 "연속 추세")은 추가를 못 해 API
   출력이 누락됐다. 필요한 행은 앞 행을 복제해 끼워 넣는다.
3. 절 제목 접미어 — 수출 탭/국가필터 슬라이드에서 "글로벌 교역 현황(수출
   탭)"처럼 API 절 제목에 접미어를 붙였다. 접미어 없이 API 제목 그대로.
소스는 refetch_v13_sources.py가 라이브 원본(live_*.json)에서 다시 만든
v13_sources.json 하나만 쓴다.

(이하 v11/v12 이력 원문)
v10.pptx -> v11.pptx 전체 재생성.

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


def ensure_table_row(table, label, after_label):
    """템플릿 표에 label 행이 없으면 after_label 행 바로 뒤에 그 행을
    복제해 끼워 넣는다(v13 — API가 내는 지표를 표에 못 싣던 문제)."""
    labels = [row.cells[0].text.strip() for row in table.rows]
    if label in labels or after_label not in labels:
        return
    src_tr = table.rows[labels.index(after_label)]._tr
    new_tr = copy.deepcopy(src_tr)
    src_tr.addnext(new_tr)
    new_row = table.rows[labels.index(after_label) + 1]
    new_row.cells[0].text_frame.paragraphs[0].runs[0].text = label
    for extra in new_row.cells[0].text_frame.paragraphs[0].runs[1:]:
        extra.text = ""


def set_table_by_label(table, mapping, extra_label_rewrite=None, blank_labels=()):
    """mapping: {row_label: metric_dict-or-str}. extra_label_rewrite:
    optional (predicate(label)->bool, new_label_fn(label)->str) for rows
    like "{비교광종} 대비 조회기간 변화율차"."""
    for row in table.rows:
        label = row.cells[0].text.strip()
        text = None
        if label in mapping:
            v = mapping[label]
            text = v if isinstance(v, str) else metric_row_value(v)
        elif extra_label_rewrite is not None and extra_label_rewrite[0](label):
            predicate, new_label_fn, value = extra_label_rewrite
            row.cells[0].text_frame.paragraphs[0].runs[0].text = new_label_fn(label)
            text = metric_row_value(value)
        elif label in blank_labels:
            text = "-"  # v13 — API가 이 지표를 안 냈으면 템플릿 잔존값을 지운다
        if text is not None:
            for para in row.cells[1].text_frame.paragraphs:
                if para.runs:
                    set_paragraph_text(para, text)
                    break


def km_by_id(data):
    return {m["id"]: m for m in data["key_metrics"]}


def claims_by_id(data):
    """summary의 core_diagnosis/major_changes/current_position 문장을
    evidence_ids(claim id) 기준으로 찾아 쓸 수 있게 인덱싱한다. 2026-09-13
    사용자 지적("슬라이드는 복붙만 해야지... 수정 전부 다 리포트 요약
    api에서 작성돼야 해") — 이전엔 특정 문장을 문자열 패턴("대한민국이
    포함된 교역 루트" 부분일치, "최근 N개년...추이는" 등)으로 찾아
    절을 나눴는데, report_gen 응답이 이미 문장마다 evidence_ids(claim
    id)를 붙여주고 있어 그걸 그대로 쓰면 문자열 내용을 다시 추측할
    필요가 없다 — report_gen이 진짜 정본으로 구조를 제공하는 부분은
    그 구조를 그대로 따르고, 슬라이드 쪽에서 텍스트를 다시 해석하지
    않는다."""
    out = {}
    for section in ("core_diagnosis", "major_changes", "current_position"):
        for s in data["summary"].get(section, []):
            for cid in s.get("evidence_ids") or []:
                out[cid] = s["text"]
    return out


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


def delete_slide(prs, index):
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    rId = slides[index].rId
    prs.part.drop_rel(rId)
    xml_slides.remove(slides[index])


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
    blank = {k for k, v in mapping.items() if v is None}
    mapping = {k: v for k, v in mapping.items() if v is not None}
    extra = None
    if compare_mineral_name and "compare_overall_change_pct" in km:
        extra = (
            lambda label: label.endswith("대비 조회기간 변화율차"),
            lambda label: f"{compare_mineral_name} 대비 조회기간 변화율차",
            km["compare_overall_change_pct"],
        )
    table = shape_by_name(slide, "표 10").table
    if "연속 추세" in mapping:
        ensure_table_row(table, "연속 추세", "전년 대비")  # 렌더러 순서(_PRICE_KEY_METRIC_ORDER)와 동일 위치
    set_table_by_label(table, mapping, extra, blank_labels=blank)

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
    # 2026-09-13 사용자 지적("슬라이드는 복붙만... 수정은 리포트 요약
    # api에서") — 문장을 문자열 패턴으로 다시 추측하지 않고, report_gen
    # 응답이 문장마다 붙여주는 evidence_ids(claim id)로 절을 나눈다.
    # claim id는 calculate_domestic_trade_summary(komir_summary.py)·
    # trade_scale_trend_fact(map_presentation.py)가 붙이는 그대로다.
    claims = claims_by_id(data)
    core = claims.get("current_state", "")
    concentration = claims.get("import_concentration", "")
    trend = claims.get("trade_scale_trend")
    export_summary = claims.get("export_summary", "")

    box = shape_by_name(slide, "TextBox 4")
    entries = [("수입 현황", True), (core, False), ("수입 집중도", True), (concentration, False)]
    if trend:
        # report_render.py::_MAJOR_CHANGES_SPLIT_SECTIONS["map_korea"]의
        # 실제 절 제목("수입·수출 규모 추이") 그대로 — 처음엔 "수입/수출
        # 추이"로 손으로 다르게 적었다(2026-09-13 자체 감사로 발견·정정).
        entries += [("수입·수출 규모 추이", True), (trend, False)]
    entries += [("수출 현황", True), (export_summary, False)]
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
    # 2026-09-13 사용자 지적("슬라이드는 복붙만... 수정은 리포트 요약
    # api에서") — "대한민국이 포함된 교역 루트" 부분일치, "대비, ...
    # 루트는" 패턴 등 문자열을 다시 추측하던 걸 걷어내고, report_gen이
    # 문장마다 붙여주는 evidence_ids(claim id)로 절을 나눈다. claim id는
    # calculate_global_trade_summary·route_yearly_trend_fact가 실제로
    # 붙이는 이름 그대로(top1_country/top3_concentration/top5_
    # concentration/korea_route_rank/route_yearly_trend/country_yearly_
    # trend).
    #
    # 2026-09-13 자체 감사로 재정정 — report_render.py(진짜 렌더러)를
    # 직접 실행해 대조한 결과, route_yearly_trend은 "주요 교역 루트"
    # 절 안에 그대로 남고 별도 "## " 절로 안 빠진다는 걸 확인했다(이전
    # 버전은 "연도별 변화"라는, report_gen에 없는 절을 만들어 냈었다 —
    # 복붙이 아니라 창작이었다). 대신 route_yearly_trend이 없고
    # country_yearly_trend(바차트 국가별 변동)만 있을 때는 report_gen이
    # 그 문장을 "## 참고: 연도별 교역액 변화"라는 별도 절로 진짜 뺀다
    # (report_render.py::_HIDDEN_SECTIONS의 map_global 예외 처리) — 이건
    # 진짜로 존재하는 절이라 그대로 따라 만든다.
    claims = claims_by_id(data)
    core = claims.get("current_state", "")
    rest = " ".join(
        claims[cid]
        for cid in ("top1_country", "top3_concentration", "top5_concentration", "route_yearly_trend")
        if cid in claims
    )
    korea = claims.get("korea_route_rank", "")
    country_trend = claims.get("country_yearly_trend")

    box = shape_by_name(slide, "TextBox 4")
    body_head = "글로벌 교역 현황"  # v13 — 접미어 없이 API 절 제목 그대로(extra_body_title은 호환용, 무시)
    entries = [
        (body_head, True), (core, False),
        ("주요 교역 루트", True), (rest, False),
        ("한국 관련 루트", True), (korea, False),
    ]
    if country_trend:
        entries += [("연도별 교역액 변화", True), (country_trend, False)]  # 2026-09-13 "참고:" 접두어 제거(report_render.py와 동기화)
    fill_body(box, entries)

    km = km_by_id(data)
    table = shape_by_name(slide, "표 6").table
    mapping = {
        "세계 교역 총액": compact_currency_fmt(km["total_amount"]["value"]),
        "1위 루트 비중": metric_row_value(km["top1_share_pct"]) if "top1_share_pct" in km else "-",
        "상위3루트 비중": metric_row_value(km["top3_share_pct"]) if "top3_share_pct" in km else "-",
        "상위5루트 비중": metric_row_value(km["top5_share_pct"]) if "top5_share_pct" in km else "-",
    }
    # v13 — 바차트 기반 "{국가} 연도별 교역액 변화" 행(API key_metrics·렌더 표에
    # 있음)을 템플릿에 없어 v12까지 빠뜨렸던 것을 행 복제로 추가한다.
    wanted = {mt["label"] for mt in (data.get("key_metrics") or []) if mt["label"].endswith("연도별 교역액 변화")}
    for row in list(table.rows):  # 복제 원본 슬라이드에서 딸려온 국가 행 중 이 응답에 없는 건 제거
        lab = row.cells[0].text.strip()
        if lab.endswith("연도별 교역액 변화") and lab not in wanted:
            row._tr.getparent().remove(row._tr)
    prev = "상위5루트 비중"
    for metric in data.get("key_metrics") or []:
        if metric["label"].endswith("연도별 교역액 변화"):
            ensure_table_row(table, metric["label"], prev)
            mapping[metric["label"]] = compact_currency_fmt(metric["value"])
            prev = metric["label"]
    set_table_by_label(table, mapping)
    cap = shape_by_name(slide, "TextBox 10")
    set_caption(cap, caption)


def rebuild_map_mineral_slide(slide, data, caption, total_row_label="현재 세계 매장량", table_scale="eok"):
    # 2026-09-13 사용자 지시 — "교차 비교는 슬라이드에 필요 없어요... 아규먼트
    # 들어오는건 다 들어오는게 기본" — komis_snapshot_response(교차비교
    # 스냅샷)는 komis_fetch.fetch_map_mineral이 chart/snapshot/share 3종을
    # 항상 같이 가져오는 기본 데이터라(map_korea의 history, 수급동향지표의
    # 패널차트와 같은 결) 별도 "교차비교" 슬라이드로 대조하지 않고 baseline
    # 호출자가 항상 포함시킨다 — 그 결과 major_changes에 교차비교 문장이
    # 자연스럽게 섞여 들어오면(있으면) 그대로 보여주고, 헤더를 따로 구분
    #하지 않는다(더 이상 "옵션"이 아니라 그냥 기본 내용이므로).
    claims = claims_by_id(data)
    core = " ".join(s["text"] for s in data["summary"]["core_diagnosis"])
    ranking = " ".join(
        claims[cid] for cid in ("current_leaders", "third_country", "cross_measure_comparison") if cid in claims
    )
    extreme = claims.get("extreme_change_countries", "")

    box = shape_by_name(slide, "TextBox 4")
    label = "세계 생산량 현황" if data["applied_filters"]["measure"] == "production" else "세계 매장량 현황"
    entries = [
        (label, True), (core, False),
        ("국가별 순위 및 변화", True), (ranking, False),
        ("주요 변화", True), (extreme, False),
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
    if "max_increase_country" in km:  # v13 — 템플릿에 없어 v12까지 빠졌던 행
        ensure_table_row(table, "최대 증가 국가", "1·2위 비중 차이")
        mapping["최대 증가 국가"] = metric_row_value(km["max_increase_country"])
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

path_v10 = glob.glob(f"{EVID37}/요약분석_정리결과물/*v10*.pptx")[0]
path_v12 = path_v10.replace("v10", "v13")
import shutil  # noqa: E402
shutil.copy(path_v10, path_v12)
path = path_v12

p = Presentation(path)
assert len(p.slides) == 22, len(p.slides)

# ── 슬라이드 구조 정리(사용자 지시): "교차 비교는 슬라이드에 필요 없어요
# 기존 슬라이드에 내용 정리해서 v12로 만들어주세요. 아규먼트 들어오는건
# 다 들어오는게 기본이라고 생각하고 정리하면 됩니다." — komis_snapshot_
# response(map_mineral 교차비교)·komis_route_share_response/komis_bar_
# chart_response(map_global 수출입국가옵션)는 KOMIS 화면에 실제 토글이
# 없는 "항상 같이 오는 기본 데이터"라(map_korea history·수급동향지표
# 패널차트와 같은 결) 별도 "옵션 추가" 슬라이드로 대조하지 않고 baseline
# 호출에 기본 포함시킨다 — 그래서 그 두 슬라이드(교차비교·수출입국가옵션)
# 는 삭제하고 baseline 슬라이드 호출만 풍부하게 만든다.
delete_slide(p, 20)  # 광물지도 (매장량·생산량 교차비교)
delete_slide(p, 18)  # 글로벌수급지도 (수출입국가 옵션)
assert len(p.slides) == 20

R = load("documents/산출물/2026-W37_0907-0913/report_gen_v13_슬라이드_260913_evidence/v13_sources.json")

# 슬라이드 2(목차, v10 템플릿 손글씨)의 오타 — API 본문이 아닌 템플릿 텍스트라 여기서 고친다.
for shape in p.slides[1].shapes:
    if shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            for r_ in para.runs:
                if "희소금석" in r_.text:
                    r_.text = r_.text.replace("희소금석", "희소금속")

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

# 12 수급동향지표(패널차트 포함 — 기본 데이터, "옵션" 아님)
rebuild_indicator_supply_slide(p.slides[12], R["indicator_supply_aux"], "검색 옵션 : 동", with_aux=True)

# 13 국내수급지도 baseline(5개년 추이 포함)
rebuild_map_korea_slide(p.slides[13], R["map_korea_baseline"], "검색 옵션 :광종 : 동, 수입, 2026")

# 14 국내수급지도 국가필터(5개년 추이 포함, sumIncmAmt 버그 수정)
rebuild_map_korea_slide(
    p.slides[14], R["map_korea_country_filter"],
    f"검색 옵션 :광종 : 동, 수입, 2026, 국가필터: {R['_country_filter_name']}",
)

# 15 국내수급지도 생산품유형필터(5개년 추이 포함)
rebuild_map_korea_slide(
    p.slides[15], R["map_korea_scope"],
    "검색 옵션 :광종 : 동, 수입, 2026, 생산품유형: 기초금속",
)

# 16 글로벌수급지도 baseline(수입) — 수출입국가옵션(route_share)·bar_chart·
# 전년비교(history)를 전부 기본 포함
rebuild_map_global_baseline_slide(
    p.slides[16], R["map_global_import_full"],
    "검색 옵션 :광종 : 리튬, 수입, 2026, 수출입국가: 전체",
)

# 17 글로벌수급지도 수출옵션 — 같은 원칙으로 route_share·bar_chart 기본 포함
rebuild_map_global_baseline_slide(
    p.slides[17], R["map_global_export_full"], "검색 옵션 :광종 : 리튬, 수출, 2026, 수출입국가: 전체",
    extra_body_title="(수출 탭)",
)

# 18(신규) 글로벌수급지도 수출입국가 필터(대한민국→인도네시아) — 이건
# KOMIS 화면에 실제 입력란(수출국가/수입국가)이 있는 진짜 옵션이라 계속
# 별도 슬라이드로 유지.
kr_id_data = R["map_global_kr_id_filter"]
new_country_slide = duplicate_slide(p, 16)
move_slide(p, len(list(p.slides._sldIdLst)) - 1, 18)
set_title(p.slides[18], "글로벌수급지도 - 핵심광물지도 (수출입국가 필터: 대한민국→인도네시아)")
rebuild_map_global_baseline_slide(
    p.slides[18], kr_id_data,
    "검색 옵션 :광종 : 리튬, 수입, 2026, 수출국가: 대한민국, 수입국가: 인도네시아",
    extra_body_title="(국가필터)",
)

# 19 광물지도 baseline(매장량) — 교차비교(komis_snapshot_response)를 기본 포함
rebuild_map_mineral_slide(
    p.slides[19], R["map_mineral_baseline_full"], "검색 옵션 :광종 : 동, 매장량, 2021~2025",
)

# 20 광물지도 생산량검색 — measure=production은 KOMIS 화면의 실제 탭
# 선택이라 계속 별도 슬라이드로 유지.
rebuild_map_mineral_slide(
    p.slides[20], R["map_mineral_production"], "검색 옵션 :광종 : 동, 생산량, 2021~2025",
    total_row_label="현재 세계 생산량", table_scale="man",
)

assert len(p.slides) == 21, len(p.slides)
p.save(path)
print("v13.pptx 저장 완료:", path, "| 슬라이드", len(p.slides))
