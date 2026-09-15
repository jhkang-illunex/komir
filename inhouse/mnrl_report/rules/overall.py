"""전체 보고서(ai_rpt_overall) RULE 컬럼 — 양식 A의 문장 템플릿 그대로.

입력 facts: base(date), overall(ai_dash_diag, 더미면 None), minerals: {code:
{name, diag, price, customs, production}}, gscpi(더미면 None).
진단 원천이 없으면 등급·지수 문장은 None으로 두고, 가격·USGS·관세청 정량
문장만 채운다.
"""
from __future__ import annotations

from datetime import date

from ..config import ABNORMAL_MIN_GRADE, GRADE_NAMES, GRADE_ORDER, ReportConfig, month_week_label, week_meta
from . import fmt


def _grade_ge(g: str, ref: str) -> bool:
    return g in GRADE_ORDER and GRADE_ORDER.index(g) >= GRADE_ORDER.index(ref)


def build(facts: dict, base: date, cfg: ReportConfig) -> dict:
    out: dict = {"base_ymd": base.strftime("%Y%m%d"), "title": "핵심광물 수급위기 진단결과 보고서"}
    out.update(week_meta(base))
    mw = month_week_label(base)
    mins: dict[str, dict] = facts.get("minerals", {})
    ov = facts.get("overall")

    # ── A2 정량 ──
    parts = []
    if ov and ov.get("overall_score") is not None:
        out["overall_score"] = ov["overall_score"]
        out["overall_wow"] = ov.get("overall_wow")
        out["overall_level_txt"] = "높은" if ov["overall_score"] >= cfg.overall_high else "낮은"
        s = f"핵심광물 시장의 전체 평균 수급 위기지수는 {fmt.num(ov['overall_score'], 1)}로"
        if ov.get("overall_wow") is not None:
            s += f" 전주 대비 {fmt.points(ov['overall_wow'], 1)} {fmt.signed_dir(ov['overall_wow'])}하였으며"
        parts.append(s)
    # 관심 광종: 실진단이 있으면 등급 상향/지수 상승 상위 2, 없으면 주간가격 변동 절대값 상위 2
    diag_ranked = sorted(
        ((c, m) for c, m in mins.items() if m.get("diag") and m["diag"]["score_wow"] is not None),
        key=lambda x: -x[1]["diag"]["score_wow"])
    if diag_ranked:
        focus = [c for c, _ in diag_ranked[:2]]
    else:
        focus = [c for c, _ in sorted(((c, m) for c, m in mins.items() if m.get("price") and m["price"]["wow_pct"] is not None),
                                      key=lambda x: -abs(x[1]["price"]["wow_pct"]))[:2]]
    out["focus_mnrl_cds"] = ",".join(focus) or None
    if focus and diag_ranked:
        names = ", ".join(mins[c]["name"] for c in focus)
        parts[-1:] = [parts[-1] + f", 특히 {names}의 수급 리스크가 심화되고 있습니다."] if parts else \
            [f"특히 {names}의 수급 리스크가 심화되고 있습니다."]
    elif parts:
        parts[-1] += "."
    price_bits = [(mins[c]["name"], mins[c]["price"]["wow_pct"]) for c in focus
                  if mins[c].get("price") and mins[c]["price"]["wow_pct"] is not None]
    if price_bits:
        lead = "이에 따라 " if parts else ""
        also = "도" if parts else "은"
        dirs = {fmt.signed_dir(p) for _, p in price_bits}
        if len(dirs) == 1:  # 방향이 같을 때만 "각각 a%, b%의 상승세"로 묶는다
            names = "과 ".join(n for n, _ in price_bits)
            pcts = ", ".join(fmt.pct(abs(p), 2) for _, p in price_bits)
            each = "각각 " if len(price_bits) > 1 else ""
            parts.append(f"{lead}{mw} {names}의 주간 평균가격{also} {each}전주 대비 {pcts}의 {dirs.pop()}세를 나타내었습니다.")
        else:  # 방향이 다르면 광종마다 방향어를 붙인다(2026-09-15 주석 상승이 "하락세"로 적히던 버그)
            seg = ", ".join(f"{n} {fmt.pct(abs(p), 2)} {fmt.signed_dir(p)}" for n, p in price_bits)
            parts.append(f"{lead}{mw} 주간 평균가격{also} 전주 대비 {seg}을 나타내었습니다.")
    out["smry_quant_txt"] = " ".join(parts) or None

    # ── A3/A4/A5 등급 기반(실진단 있을 때만) ──
    graded = {c: m for c, m in mins.items() if m.get("diag")}
    if graded:
        top_grade = max((m["diag"]["grade"] for m in graded.values()), key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else -1)
        in_top = [m["name"] for m in graded.values() if m["diag"]["grade"] == top_grade]
        gn = GRADE_NAMES.get(top_grade, top_grade)
        out["diag_grade_cd"] = top_grade
        out["diag_grade_mnrl_txt"] = f"{', '.join(in_top[:2])} 등 {len(in_top)}종"
        out["diag_tbl_title_txt"] = f"(위기진단) {', '.join(in_top[:2])} 등 총 {len(in_top)}개 광종 \"{gn}\" 단계"
        n_all = len(graded)
        abn = [m for m in graded.values() if _grade_ge(m["diag"]["grade"], ABNORMAL_MIN_GRADE)]
        watch = [m for m in graded.values() if m["diag"]["grade"] == "WATCH"]
        caution = [m for m in graded.values() if m["diag"]["grade"] == "CAUTION"]
        out["idx_anal_txt"] = (f"① (지표 분석) 핵심광물 {n_all}종 中 {len(abn)}종 수급 이상징후 확인\n"
                               f"  * 관심등급 {len(watch)}종은 가격, 수입 등 모니터링 유지\n"
                               f"  * 주의등급 {len(caution)}종은 수급상황 판단 검토")
        lines = [f"② (수급상황 판단) 수급이상 징후 {len(abn)}종 中 {len(in_top)}종 수급 \"{gn}\" 판단"]
        for m in abn:
            d = m["diag"]
            wow = (f" (전주 대비 {fmt.points(d['score_wow'])}{'↑' if d['score_wow'] > 0 else '↓' if d['score_wow'] < 0 else ''})"
                   if d["score_wow"] is not None else "")
            lines.append(f"  * ({m['name']}) 위기진단지표 {fmt.num(d['score'], 2)}{wow}, 위기등급 "
                         f"\"{GRADE_NAMES.get(d['grade'], d['grade'])}\" ({d['streak_wk']}주 연속)")
        pb = [f"{m['name']} {fmt.pct(abs(m['price']['wow_pct']), 2)}{'↑' if m['price']['wow_pct'] >= 0 else '↓'}"
              for m in abn if m.get("price") and m["price"]["wow_pct"] is not None]
        if pb:
            lines.append(f"  * {fmt.yy(base.year)} {mw} 가격 상승률(%, 전주 대비) : {', '.join(pb)}")
        out["judge_quant_txt"] = "\n".join(lines)

    # ── A6 ② USGS 생산 비중 + 가격 전주/전월/전년비 (정량) ──
    q2 = []
    for c in (focus or list(mins)):
        m = mins[c]
        pr = m.get("production")
        if pr:
            shares = ", ".join(f"{n} {fmt.pct(s)}" for n, _, s in pr["top"][:5])
            q2.append(f"USGS에 따르면, {m['name']}의 세계 생산량은 {fmt.yy(pr['year'])} 기준 "
                      f"{fmt.num(pr['world_ton'], 0)}톤으로 국가별 비중은 {shares}로 나타나고 있습니다.")
    for c in (focus or list(mins)):
        m = mins[c]
        p = m.get("price")
        if p and p["wow_pct"] is not None:
            items = [("전주 대비", p["wow_pct"], 2), ("전월 대비", p.get("mom_pct"), 1), ("전년 대비", p.get("yoy_pct"), 1)]
            items = [(k, v, d) for k, v, d in items if v is not None]
            dirs = {fmt.signed_dir(v, "상승률", "하락률", "보합") for _, v, _ in items}
            head = f"{mw} {m['name']}의 가격은 {fmt.num(p['price'], 2)}달러로 "
            if len(dirs) == 1:
                bits = ", ".join(f"{k} {fmt.pct(abs(v), d)}" for k, v, d in items)
                q2.append(f"{head}{bits}의 {dirs.pop()}을 기록하였습니다.")
            else:  # 기간별 방향이 다르면 항목마다 방향어(전주 하락·전년 상승 혼재 케이스)
                bits = ", ".join(f"{k} {fmt.pct(abs(v), d)} {fmt.signed_dir(v)}" for k, v, d in items)
                q2.append(f"{head}{bits}을 기록하였습니다.")
    out["risk2_quant_txt"] = " ".join(q2) or None

    # ── A6 ④ 수입금액·국가 비중 (정량) ──
    q4 = []
    for c in (focus or list(mins)):
        m = mins[c]
        cu = m.get("customs")
        if not cu:
            continue
        yt = cu["year_tot"].get(cu["prev_year"])
        yt0 = cu["year_tot"].get(str(int(cu["prev_year"]) - 1))
        if not yt:
            continue
        yoy = fmt.ratio_change(yt["usd"], yt0["usd"]) if yt0 else None
        shares = ", ".join(f"{n} {fmt.pct(s)}" for n, s in cu["shares"][:5])
        s = f"한국의 {m['name']} 수입금액은 {fmt.yy(cu['prev_year'])} 기준 {fmt.k_usd_u(yt['usd'])}으로"
        if yoy is not None:
            s += f" 전년 대비 {fmt.pct(abs(yoy))} {fmt.signed_dir(yoy, '증가', '감소', '보합')}하였으며,"
        s += f" 국가별 비중은 {shares}로 {cu['shares'][0][0]}이 대부분을 차지하고 있습니다."
        q4.append(s)
    out["risk4_quant_txt"] = " ".join(q4) or None
    return out
