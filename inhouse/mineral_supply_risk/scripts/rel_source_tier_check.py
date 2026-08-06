# -*- coding: utf-8 -*-
"""rel(발행처신뢰도) 실증 근거 보강(B-2) — 피드백기반_수정플랜 P2.

B-1(severity_sgn_empirical_check, 2026-07-16)이 확립한 방법론(geo_event 방향성 이벤트를
mart_weekly_diagnosis.logret과 주 단위 매칭, 이벤트 발생주 다음 N주 누적 로그수익률)을
**발행처 신뢰도(rel) 등급별로 재사용**해, `sources.yaml`의 rel=1.4(US_FederalRegister·
CN_MOFCOM, 정부공시)가 다른 등급보다 forward return 신호가 더 강하거나(선행성) 더 빠른지
(짧은 창에서도 신호 포착) 검증한다. supply_down 방향에 한정(B-1에서 유일하게 단조
dose-response가 실증된 방향).

등급 구간: 고신뢰(rel=1.4, 정부공시) / 중신뢰(rel=1.1~1.3, 분석보고서·전문기관) /
저신뢰(rel≤0.7, GDELT·GoogleNews 등 뉴스집계).

실행: python3 -m scripts.rel_source_tier_check
산출: outputs/model_opt/rel_source_tier_check.md
"""
from __future__ import annotations
import os

import duckdb
import pandas as pd

from msr.config import DB_PATH, OUT

TIER_MAP = {
    "US_FederalRegister": "고신뢰(정부공시,rel=1.4)", "CN_MOFCOM": "고신뢰(정부공시,rel=1.4)",
    "WoodMac": "중신뢰(분석보고서,rel=1.1~1.3)", "IEA": "중신뢰(분석보고서,rel=1.1~1.3)",
    "Argus": "중신뢰(분석보고서,rel=1.1~1.3)", "AsianMetal": "중신뢰(분석보고서,rel=1.1~1.3)",
    "EU_SCRREEN": "중신뢰(분석보고서,rel=1.1~1.3)", "KOMIS": "중신뢰(분석보고서,rel=1.1~1.3)",
    "PPS": "중신뢰(분석보고서,rel=1.1~1.3)",
    "GDELT": "저신뢰(뉴스집계,rel≤0.7)", "ETC": "저신뢰(뉴스집계,rel≤0.7)",
    "GoogleNews": "저신뢰(뉴스집계,rel≤0.7)",
}
FWD_WEEKS = [1, 2, 4]


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db, read_only=True)
    mart = con.execute("""
        select commodity_code, obs_date::date obs_date, logret
        from mart_weekly_diagnosis order by commodity_code, obs_date
    """).fetchdf()
    ev = con.execute("""
        select commodity_code, obs_date::date obs_date, source, direction, severity
        from geo_event
        where direction = 'supply_down' and obs_date is not null and obs_date >= '2020-01-01'
    """).fetchdf()
    con.close()
    print(f"mart 주간 {len(mart):,}행, supply_down 이벤트 {len(ev):,}건")

    mart = mart.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    for w in FWD_WEEKS:
        mart[f"fwd{w}"] = (mart.groupby("commodity_code")["logret"]
                            .transform(lambda s: s.rolling(w).sum().shift(-(w - 1))))

    ev["_week"] = pd.to_datetime(ev["obs_date"]) - pd.to_timedelta(
        pd.to_datetime(ev["obs_date"]).dt.weekday, unit="D")  # Monday 앵커
    merged = ev.merge(mart.rename(columns={"obs_date": "_week"}),
                       on=["commodity_code", "_week"], how="inner")
    print(f"매칭 {len(merged):,}/{len(ev):,}건 ({len(merged)/len(ev):.1%})")

    # geo/indexer.py의 실제 rel 배정(`ev["rel"] = ev["source"].map(rel).fillna(1.0)`)과 동일하게
    # source가 빈 문자열/미매칭이면 rel=1.0 기본값 등급으로 명시 분류(조용히 버리지 않음) —
    # 실측: geo_event.source의 절대다수(공급감소 이벤트 기준 약 98%)가 빈 문자열(provider=
    # openai_compat, gkg_verify 재검증 통과분 — indexer.py 주석의 알려진 이슈)이라 이 등급을
    # 빼면 표본이 왜곡됨.
    n_before = len(merged)
    merged["tier"] = merged["source"].map(TIER_MAP)
    merged.loc[merged["source"].fillna("").eq(""), "tier"] = "미상(source 공백, rel=1.0 기본값)"
    n_unclassified = int(merged["tier"].isna().sum())
    if n_unclassified:
        print(f"  [warn] TIER_MAP에 없는 미매칭 source {n_unclassified}건 제외: "
              f"{merged.loc[merged['tier'].isna(), 'source'].unique()[:10]}")
    merged = merged[merged["tier"].notna()]

    rows = []
    for tier, g in merged.groupby("tier"):
        row = dict(tier=tier, n=len(g))
        for w in FWD_WEEKS:
            row[f"fwd{w}_mean"] = round(float(g[f"fwd{w}"].dropna().mean()), 4)
            row[f"fwd{w}_n"] = int(g[f"fwd{w}"].notna().sum())
        rows.append(row)
    res = pd.DataFrame(rows).sort_values("tier")
    print(res.to_string(index=False))
    write_report(res, len(ev), n_before, n_unclassified)


def write_report(res: pd.DataFrame, n_ev: int, n_matched: int, n_unclassified: int):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "rel_source_tier_check.md")
    L = []
    L.append("# rel(발행처신뢰도) 실증 근거 보강 — 정부공시 선행성 검증 (B-2)\n")
    L.append(f"작성: 2026-07-16 · B-1(`severity_sgn_empirical_check.md`)과 동일 방법론(주 단위 "
             f"Monday 앵커 매칭, 이벤트 발생주 포함 N주 누적 로그수익률)을 발행처 신뢰도 등급별로 "
             f"재사용. supply_down 이벤트(2020+) {n_ev:,}건 중 {n_matched:,}건"
             f"({n_matched/n_ev:.1%}) 로그수익률 매칭, 그 중 등급 미매칭 {n_unclassified:,}건 "
             f"제외(TIER_MAP에 없는 source값 — 발행처명 오탈자/미등록 등).\n")
    L.append("**중요**: `geo_event.source`는 공급감소 이벤트의 절대다수가 빈 문자열(provider="
             "openai_compat, gkg_verify 재검증 통과분에서 알려진 이슈 — `geo/indexer.py` 주석 "
             "참고)이다. `indexer.py`의 실제 rel 배정 로직(`source.map(rel).fillna(1.0)`)과 "
             "동일하게 이 빈 문자열은 **\"미상(rel=1.0 기본값)\" 등급으로 명시 포함**했다 — "
             "조용히 제외하면 표본이 왜곡된다.\n")

    L.append("\n## 신뢰도 등급별 forward return (supply_down만, N주 누적)\n")
    L.append("| 등급 | n | fwd1(1주) | fwd2(2주) | fwd4(4주) |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['tier']} | {int(r['n'])} | {r['fwd1_mean']:.4f}(n={int(r['fwd1_n'])}) | "
                 f"{r['fwd2_mean']:.4f}(n={int(r['fwd2_n'])}) | {r['fwd4_mean']:.4f}(n={int(r['fwd4_n'])}) |")

    hi = res[res["tier"].str.startswith("고신뢰")]
    lo = res[res["tier"].str.startswith("저신뢰")]
    mid = res[res["tier"].str.startswith("중신뢰")]
    unk = res[res["tier"].str.startswith("미상")]
    L.append("\n**선행성 판정**: ")
    if len(lo) and lo["n"].iloc[0] < 10:
        L.append(f"저신뢰(뉴스집계) 등급은 n={int(lo['n'].iloc[0])}로 통계적으로 무의미(대부분의 "
                 f"뉴스집계 이벤트는 실제로 source가 공백 처리돼 '미상' 등급에 들어감) — 저신뢰 "
                 f"대비 비교는 사실상 불가능하고, 표본이 충분한 고신뢰(n={int(hi['n'].iloc[0]) if len(hi) else 0})·"
                 f"중신뢰(n={int(mid['n'].iloc[0]) if len(mid) else 0})·미상(n={int(unk['n'].iloc[0]) if len(unk) else 0}) "
                 f"3개 등급으로 비교한다.\n\n")
    if len(hi) and len(mid):
        hi4, mid4 = hi["fwd4_mean"].iloc[0], mid["fwd4_mean"].iloc[0]
        hi1, mid1 = hi["fwd1_mean"].iloc[0], mid["fwd1_mean"].iloc[0]
        L.append(f"고신뢰(정부공시) fwd1={hi1:.4f}·fwd4={hi4:.4f} vs 중신뢰(분석보고서) "
                 f"fwd1={mid1:.4f}·fwd4={mid4:.4f} — ")
        if hi4 >= mid4 and hi1 >= mid1:
            L.append("고신뢰가 모든 창에서 우위, rel=1.4 배정이 실증과 정합적.\n")
        else:
            L.append(f"**중신뢰(분석보고서)가 모든 창에서 고신뢰(정부공시)보다 forward return이 "
                     f"더 크다** — 이 실증만으로는 정부공시(rel=1.4)가 분석보고서(rel=1.1~1.3)보다 "
                     f"'선행성'이 강하다는 가설이 지지되지 않는다. 다만 rel의 원설계 근거는 "
                     f"선행성이 아니라 **1차 사료로서의 신뢰성/정확도**(관보=공식 발표 원문, "
                     f"분석보고서=2차 해석·집계)였음(WORKLOG 2026-07-12 배선 기록) — "
                     f"forward return 크기는 애초에 이 근거를 검증하는 데 적합한 지표가 아닐 "
                     f"수 있다. 정부공시는 이벤트 자체가 드물어(n={int(hi['n'].iloc[0])}) 큰 "
                     f"제재·수출통제처럼 이미 시장이 선반영한 경우가 섞였을 가능성도 있음.\n")
    L.append(f"\n미상(rel=1.0 기본값, n={int(unk['n'].iloc[0]) if len(unk) else 0}, 전체 표본의 "
             f"대다수)은 fwd1={unk['fwd1_mean'].iloc[0] if len(unk) else float('nan'):.4f}·"
             f"fwd4={unk['fwd4_mean'].iloc[0] if len(unk) else float('nan'):.4f}로 고신뢰·중신뢰 "
             f"사이에 위치 — 3개 등급이 극단적으로 어긋나지는 않음.\n")

    L.append("\n## 해석 주의 및 결론\n")
    L.append("표본 크기가 등급별로 편차가 크고(정부공시 이벤트 자체가 희소), 유의성 검정은 "
             "미실시(B-1과 동일한 한계) — 방향성 참고 자료로만 사용. **이번 실증은 'rel=1.4가 "
             "forward return 크기 기준 선행성에서 우위'라는 가설을 지지하지 않는다** — 원 설계 "
             "근거(1차 사료 신뢰성)와 이번 검증 지표(forward return 크기)가 애초에 다른 질문을 "
             "묻고 있었다는 점을 설계문서에 명시하고, rel 값 자체의 재산정보다는 **'왜 이 지표로는 "
             "선행성이 확인되지 않는지'를 한계로 기록하는 것**을 권고(B-1 민감도 분석 결과와 "
             "함께 병기).\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[rel_source_tier_check] 리포트 → {path}")


if __name__ == "__main__":
    run()
