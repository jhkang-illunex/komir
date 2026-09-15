"""광종별 보고서(ai_rpt_mnrl) RULE 컬럼 — 양식 B의 문장 템플릿 그대로.

입력 facts 키(sources.py): name, base(date), price, diag, customs, reserve,
production. 없는 원천은 None → 해당 문장 컬럼은 None(빈 채로 남긴다, 지어내지
않는다). 문장 문구는 `통합보고서_템플릿_광종별_260915.md`와 일치해야 한다.
"""
from __future__ import annotations

from datetime import date

from ..config import GRADE_NAMES, ReportConfig, month_week_label, week_meta
from . import fmt


def build(code: str, facts: dict, base: date, cfg: ReportConfig) -> dict:
    name = facts["name"]
    out: dict = {"mnrknd_unq_cd": code, "base_ymd": base.strftime("%Y%m%d"),
                 "title": f"{name} 수급위기 진단결과 보고서"}
    wm = week_meta(base)
    out["rpt_year"], out["rpt_week_no"] = wm["rpt_year"], wm["rpt_week_no"]
    mw = month_week_label(base)

    # ── B2/B3 진단·가격 ──
    diag, price = facts.get("diag"), facts.get("price")
    if diag:
        out["grade_cd"] = diag["grade"]
        out["grade_nm"] = GRADE_NAMES.get(diag["grade"], diag["grade"])
        out["score"], out["score_wow"], out["score_mom"] = diag["score"], diag["score_wow"], diag["score_mom"]
        out["grade_streak_wk"] = diag["streak_wk"]
    if price:
        out["price_wow_pct"] = price["wow_pct"]

    parts = []
    if diag and diag["score"] is not None and diag["score_wow"] is not None:
        parts.append(f"최근 {name}의 공급망 리스크는 {out['grade_nm']} 수준에 있으며, {mw} 수급 위험지수는 "
                     f"{fmt.num(diag['score'], 2)}로 전주 대비 {fmt.points(diag['score_wow'])} "
                     f"{fmt.signed_dir(diag['score_wow'])}하였습니다.")
    if price and price["wow_pct"] is not None:
        lead = "이에 따라 " if parts else ""
        also = "도" if parts else "은"
        parts.append(f"{lead}{mw} {name}의 주간 평균가격{also} 전주 대비 {fmt.pct(abs(price['wow_pct']), 2)}의 "
                     f"{fmt.signed_dir(price['wow_pct'])}세를 나타내었습니다.")
    out["smry_quant_txt"] = " ".join(parts) or None

    if diag and diag["score"] is not None:
        mom = (f" (전월 대비 {fmt.points(diag['score_mom'])} {fmt.signed_dir(diag['score_mom'])})"
               if diag["score_mom"] is not None else "")
        out["diag_result_txt"] = (f"(수급 {out['grade_nm']}) {fmt.num(diag['score'], 2)}{mom}, "
                                  f"{diag['streak_wk']}주 연속 \"{out['grade_nm']}\"")

    # ── B5 각주 ──
    foot = []
    if price and price["wow_pct"] is not None:
        foot.append(f"{name} 가격 전주 대비 {fmt.pct(abs(price['wow_pct']), 2)} {fmt.signed_dir(price['wow_pct'])}")
    if diag and diag["score_wow"] is not None and diag["score"] is not None:
        prev = diag["score"] - diag["score_wow"]
        idx_pct = (diag["score_wow"] / prev * 100) if prev else None
        if idx_pct is not None:
            foot.append(f"위기진단지표 전주 대비 {fmt.pct(abs(idx_pct))} {fmt.signed_dir(idx_pct)}")
    if foot:
        out["price_foot_txt"] = f"{fmt.yy(base.year)} {mw} " + ", ".join(foot)

    # ── B6 가격이격률·신호: 산식 미확정 → 계산하지 않는다(NULL) ──

    # ── B7 국내 수입동향 ──
    cu = facts.get("customs")
    if cu:
        y, m = int(cu["latest_ym"][:4]), int(cu["latest_ym"][4:])
        out["import_month_ymd"] = cu["latest_ym"]
        yoy_m = fmt.ratio_change(cu["month"]["usd"], cu["month_prev_year"]["usd"])
        yoy_ytd = fmt.ratio_change(cu["ytd"]["usd"], cu["ytd_prev_year"]["usd"])
        out["import_month_txt"] = (
            f"{name}의 {fmt.yy(y)} {m}월 수입량은 {fmt.kton(cu['month']['ton'])}, 수입액은 "
            f"{fmt.eok_usd(cu['month']['usd'])}"
            + (f"(전년 대비 {fmt.pct(abs(yoy_m))} {fmt.signed_dir(yoy_m, '증가', '감소', '보합')})" if yoy_m is not None else "")
            + f"이며, 1~{m}월 누적 수입량은 {fmt.kton(cu['ytd']['ton'])}, 수입액은 {fmt.eok_usd(cu['ytd']['usd'])}"
            + (f"(전년 대비 {fmt.pct(abs(yoy_ytd))} {fmt.signed_dir(yoy_ytd, '증가', '감소', '보합')})" if yoy_ytd is not None else "")
            + "입니다."
        )
        prev_tot = cu["year_tot"].get(cu["prev_year"])
        if prev_tot and cu["cagr_pct"] is not None:
            out["import_cagr_txt"] = (f"{fmt.yy(cu['prev_year'])} {name}의 수입액은 {fmt.k_usd(prev_tot['usd'])}로 "
                                      f"연평균 증가율(CAGR)은 {fmt.pct(cu['cagr_pct'])}를 기록하였습니다.")
        top3 = ", ".join(f"{n}({fmt.pct(s)})" for n, s in cu["shares"][:3])
        out["import_ntn_txt"] = (f"주로 {top3} 등에서 수입하며, 독점도를 평가하는 HHI(허시만-허핀달 지수)는 "
                                 f"{fmt.hhi(cu['hhi'])}을 기록하였습니다.")
        out["import_hhi"] = round(cu["hhi"], 2)
        high = cu["hhi"] >= cfg.hhi_high
        out["import_struct_txt"] = (f"편중도가 {'높은' if high else '낮은'} 수준으로 수급리스크를 "
                                    f"{'확대' if high else '완화'}시키는 요인입니다.")

    # ── B8 매장량·생산량 ──
    def _rp(label: str, u: dict) -> str:
        top3 = ", ".join(f"{n}({fmt.kton(v)}, {fmt.pct(s)})" for n, v, s in u["top"][:3])
        return (f"({label}) 세계 {label}은 약 {fmt.kton(u['world_ton'])}(금속기준), 상위 3개국 점유율은 "
                f"{fmt.pct(u['cr3_pct'])}입니다. * {top3}")
    rs, pr = facts.get("reserve"), facts.get("production")
    if rs:
        out["reserve_txt"] = _rp("매장량", rs)
    if pr:
        out["production_txt"] = _rp("생산량", pr)

    # ── B9 정량 ──
    q = []
    if pr:
        top3 = ", ".join(f"{n}({fmt.kton(v)}, {fmt.pct(s)})" for n, v, s in pr["top"][:3])
        q.append(f"{fmt.yy(pr['year'])} 기준 세계 {name} 생산량은 약 {fmt.kton(pr['world_ton'])}(금속량 기준)이며, "
                 f"주요 생산국은 {top3}으로, 주요 3국이 {fmt.yy(pr['year'])} 글로벌 생산량의 "
                 f"{fmt.pct(pr['cr3_pct'])}를 점유하고 있습니다.")
    if cu:
        yt = cu["year_tot"].get(cu["prev_year"])
        if yt:
            top3 = ", ".join(f"{n}({fmt.pct(s)})" for n, s in cu["shares"][:3])
            q.append(f"수입구조 측면에서 {fmt.yy(cu['prev_year'])} 수입량 {fmt.kton(yt['ton'])}, 수입액은 "
                     f"{fmt.eok_usd(yt['usd'])}이며, 주로 {top3} 등에서 수입하고 있습니다.")
    out["risk_quant_txt"] = " ".join(q) or None
    return out
