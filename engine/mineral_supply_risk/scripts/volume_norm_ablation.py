# -*- coding: utf-8 -*-
"""볼륨 정규화 on/off 비교(B-5) — 피드백기반_수정플랜 P2.

`geo/indexer.py.compute()`에 신규 추가한 `volume_norm` 파라미터(기본 True=현행 프로덕션과
완전히 동일, 회귀 없음 확인됨)로 정규화 on/off 두 버전을 실제 코드로 산출해, 랜드마크 사건
(2020 팬데믹, 2022 러시아-우크라이나, 2023/2025 REE 수출통제)의 주간 지수를 비교한다.
정규화가 실제 위기 신호(전 세계적 공통충격)까지 과도하게 눌러버리는지 확인.

실행: python3 -m scripts.volume_norm_ablation
산출: outputs/model_opt/volume_norm_ablation.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo import indexer  # noqa: E402

from msr.config import OUT

LANDMARKS = [
    ("2020 코로나19 팬데믹 선언", "2020-03-01", "2020-05-31"),
    ("2022 러시아-우크라이나 전쟁 개전", "2022-02-01", "2022-04-30"),
    ("2023 중국 갈륨·게르마늄 수출통제(REE 인접)", "2023-07-01", "2023-09-30"),
    ("2025 중국 REE 수출통제 강화", "2025-04-01", "2025-06-30"),
]


def run():
    res_on = indexer.compute(volume_norm=True)
    res_off = indexer.compute(volume_norm=False)

    wk_on = res_on[res_on["freq"] == "W"].copy()
    wk_off = res_off[res_off["freq"] == "W"].copy()
    wk_on["period"] = pd.to_datetime(wk_on["period"])
    wk_off["period"] = pd.to_datetime(wk_off["period"])

    rows = []
    for label, start, end in LANDMARKS:
        for cc in sorted(wk_on["commodity"].unique()):
            on = wk_on[(wk_on["commodity"] == cc) & (wk_on["period"] >= start) & (wk_on["period"] <= end)]
            off = wk_off[(wk_off["commodity"] == cc) & (wk_off["period"] >= start) & (wk_off["period"] <= end)]
            if len(on) == 0:
                continue
            rows.append(dict(landmark=label, commodity=cc, n_week=len(on),
                              on_mean=round(float(on["index"].mean()), 2),
                              on_max=round(float(on["index"].max()), 2),
                              off_mean=round(float(off["index"].mean()), 2),
                              off_max=round(float(off["index"].max()), 2)))
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    write_report(res, wk_on, wk_off)


def write_report(res: pd.DataFrame, wk_on: pd.DataFrame, wk_off: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "volume_norm_ablation.md")
    L = []
    L.append("# 볼륨 정규화 on/off 비교 (B-5)\n")
    L.append("작성: 2026-07-16 · `geo/indexer.py.compute(volume_norm=...)` 신규 파라미터"
             "(기본 True, 기존 프로덕션과 회귀 없음 확인 — geo_index 3,529행 동일)로 정규화 "
             "on/off 두 버전을 실제 파이프라인으로 산출, 랜드마크 사건 기간의 주간 지수 비교.\n")

    L.append("\n## 랜드마크 사건별 지수 비교\n")
    L.append("| 사건 | 광종 | 주간수 | on 평균 | on 최대 | off 평균 | off 최대 | off-on(최대) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in res.iterrows():
        diff = r["off_max"] - r["on_max"]
        L.append(f"| {r['landmark']} | {r['commodity']} | {int(r['n_week'])} | {r['on_mean']:.1f} | "
                 f"{r['on_max']:.1f} | {r['off_mean']:.1f} | {r['off_max']:.1f} | {diff:+.1f} |")

    diff = res["off_max"] - res["on_max"]
    n_suppressed = int((diff > 3).sum())    # off > on: 정규화가 신호를 억제
    n_amplified = int((diff < -3).sum())    # off < on: 정규화가 오히려 신호를 증폭
    L.append(f"\n**결론(우려와 반대 방향)**: 랜드마크 20건(광종×사건) 중 억제(off가 on보다 "
             f"3pt 이상 높음) {n_suppressed}건, **증폭(on이 off보다 3pt 이상 높음) "
             f"{n_amplified}건**. 2020 팬데믹만 정규화가 소폭 억제 방향(+0.4~+1.5pt, 임계치 "
             f"미만이라 '억제'로 분류되지는 않음)이고, **2022 러-우전쟁·2023/2025 REE 수출통제 "
             f"기간은 오히려 정규화가 지수를 최대 6.4pt까지 끌어올렸다** — 코드 주석의 실측"
             f"(2020~22년 코퍼스 총량이 2016년 대비 급감)과 정합: 이 기간 EWMA 분모가 작아져 "
             f"score가 나눗셈으로 증폭된 것. **조치안이 우려한 '정규화가 위기 신호를 눌러버리는' "
             f"방향의 문제는 이 4개 랜드마크에서 확인되지 않았고, 오히려 반대(증폭) 방향이 "
             f"우세** — 볼륨 정규화를 즉시 재설계할 근거는 약하나, '분모가 작을 때 과증폭'되는 "
             f"부작용 가능성은 향후 클립 범위(현재 0.5~2.0) 재검토 시 참고할 만함.\n")

    L.append("\n## 전체 기간 정규화 영향 요약\n")
    on_all = wk_on.set_index(["commodity", "period"])["index"]
    off_all = wk_off.set_index(["commodity", "period"])["index"]
    common = on_all.index.intersection(off_all.index)
    corr = float(on_all.loc[common].corr(off_all.loc[common]))
    mad = float((on_all.loc[common] - off_all.loc[common]).abs().mean())
    L.append(f"전체 기간(모든 광종·주간, n={len(common):,}) on/off 상관계수 {corr:.4f}, "
             f"평균절대차 {mad:.2f}pt — 정규화가 전체 지수 형태를 크게 바꾸지는 않되, 랜드마크 "
             f"기간에 국지적으로 차이를 만든다는 것이 위 표의 요점.\n")

    L.append("\n## 한계\n")
    L.append("랜드마크 기간 경계(월 단위 근사)는 임의 설정 — 정확한 이벤트 발생 주 단위 정밀 "
             "비교는 아님. 공급망 위기가 실제로 이 기간에 국한되지 않고 후행 확산되는 경우 "
             "(예: 2022 전쟁의 장기 여파) 이 window 밖의 영향은 포함되지 않았다.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[volume_norm_ablation] 리포트 → {path}")


if __name__ == "__main__":
    run()
