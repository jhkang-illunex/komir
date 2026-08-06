# -*- coding: utf-8 -*-
"""severity·direction_sign 하드코딩값 유의성 재검증 (#1·#5, 2026-07-22).

2026-07-16 B-1(`outputs/model_opt/severity_sgn_empirical_check.md`, 원본 스크립트는
저장되지 않음 — 이 스크립트가 방법론을 재구현)이 "유의성 검정·confound 통제 없는 부분
완료"로 남긴 것을 마무리한다. 방법론(B-1 각주 재현): mart_weekly_diagnosis.logret
(Monday 앵커)과 geo_event(고신뢰소스, 2020년 이후)를 주 단위 매칭, rolling(4).sum()
.shift(-3)으로 이벤트 발생주 포함 향후 4주 누적수익률 산출, direction×severity 그룹
평균 비교. 여기 추가하는 것: ① 그룹별 평균이 0과 다른지 t검정 ② supply_down(양의
dose-response 유지 여부)·supply_up(부호 반전 가설) 각각 bootstrap 95% CI.

실행: python3 -m scripts.severity_sgn_significance_check
산출: outputs/model_opt/severity_sgn_significance_check.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
from msr.config import OUT  # noqa: E402

DB = KOMIR / "warehouse" / "minerals.duckdb"
HIGH_REL_SOURCES = None  # sources.yaml rel>=1.1인 소스만(고신뢰) — 아래서 로드
N_BOOT = 2000
RNG_SEED = 0


def load():
    con = duckdb.connect(str(DB), read_only=True)
    ev = con.execute("""
        select commodity_code as commodity, obs_date, direction, severity, source
        from geo_event where obs_date >= '2020-01-01'
    """).df()
    mart = con.execute("""
        select commodity_code as commodity, obs_date, logret from mart_weekly_diagnosis
    """).df()
    con.close()
    return ev, mart


def main():
    from geo import config as C
    rel_map = {k: float(v) for k, v in (C.load_yaml("sources.yaml") or {}).get("reliability", {}).items()}
    high_rel = {k for k, v in rel_map.items() if v >= 1.1}

    ev, mart = load()
    ev["obs_date"] = pd.to_datetime(ev["obs_date"])
    mart["obs_date"] = pd.to_datetime(mart["obs_date"])
    ev = ev[ev["source"].isin(high_rel)]
    print(f"고신뢰 소스 이벤트(2020+): {len(ev):,}건")

    mart = mart.sort_values(["commodity", "obs_date"]).copy()
    mart["fwd4"] = (mart.groupby("commodity")["logret"]
                     .transform(lambda s: s.rolling(4).sum().shift(-3)))

    m = ev.merge(mart[["commodity", "obs_date", "fwd4"]], on=["commodity", "obs_date"], how="left")
    m = m.dropna(subset=["fwd4"])
    print(f"forward return 매칭: {len(m):,}건")

    rows = []
    rng = np.random.default_rng(RNG_SEED)
    for (d, s), g in m.groupby(["direction", "severity"]):
        x = g["fwd4"].values
        if len(x) < 5:
            rows.append(dict(direction=d, severity=s, n=len(x), mean=np.mean(x) if len(x) else np.nan,
                              t=None, p=None, ci_lo=None, ci_hi=None, note="표본<5, 검정 생략"))
            continue
        t, p = stats.ttest_1samp(x, 0.0)
        boot = np.array([rng.choice(x, size=len(x), replace=True).mean() for _ in range(N_BOOT)])
        ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
        rows.append(dict(direction=d, severity=s, n=len(x), mean=round(float(np.mean(x)), 5),
                          t=round(float(t), 3), p=round(float(p), 4),
                          ci_lo=round(float(ci_lo), 5), ci_hi=round(float(ci_hi), 5), note=""))
    res = pd.DataFrame(rows).sort_values(["direction", "severity"])
    print(res.to_string(index=False))
    write_report(res, m)


def write_report(res: pd.DataFrame, m: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "severity_sgn_significance_check.md")
    L = []
    L.append("# severity·direction_sign 유의성 재검증 (#1·#5, 2026-07-22)\n")
    L.append("작성: 2026-07-22 · 2026-07-16 B-1(`severity_sgn_empirical_check.md`)이 "
              "'부분 완료'로 남긴 유의성 검정(t검정)·bootstrap 95% CI를 추가해 마무리.\n")
    L.append("\n## direction×severity별 향후 4주 누적수익률(고신뢰소스, 2020+)\n")
    L.append("| direction | severity | n | mean | t | p | 95% CI |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in res.iterrows():
        ci = "—" if r["ci_lo"] is None else f"[{r['ci_lo']}, {r['ci_hi']}]"
        tp = "—" if r["t"] is None else f"t={r['t']}, p={r['p']}"
        L.append(f"| {r['direction']} | {int(r['severity'])} | {int(r['n'])} | {r['mean']} | {tp} | | {ci} |")

    su = res[res["direction"] == "supply_up"]
    sd = res[res["direction"] == "supply_down"]
    L.append("\n## #1 severity 선형성 재확인(supply_down dose-response)\n")
    if len(sd) >= 2:
        mono = all(sd.sort_values("severity")["mean"].diff().dropna() >= -1e-9)
        L.append(f"severity 오름차순 평균이 단조증가: {'예(재확인)' if mono else '아니오(재검토 필요)'} — "
                  f"{sd[['severity','mean']].to_dict('records')}\n")
    L.append("\n## #5 supply_up 부호 재검증\n")
    if len(su):
        any_sig_pos = ((su["p"].astype(float) < 0.05) & (su["mean"].astype(float) > 0)).any() if su["p"].notna().any() else False
        L.append(f"supply_up(config상 sgn=-0.5, 즉 '개선' 방향)의 실측 4주 forward return — "
                  f"{su[['severity','mean','p']].to_dict('records')}. "
                  f"유의(p<0.05)하게 양(+)인 severity 존재: {'예 — 부호 반전 근거 강화' if any_sig_pos else '아니오(유의성 미달, 기존처럼 즉시 반전 근거 부족)'}\n")
    L.append(f"\n표본: 고신뢰소스 이벤트 매칭 {len(m):,}건. 유의성 미달 항목은 방향성 참고로만 사용.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[write] {path}")


if __name__ == "__main__":
    main()
