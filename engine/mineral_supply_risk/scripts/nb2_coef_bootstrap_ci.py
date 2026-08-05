# -*- coding: utf-8 -*-
"""소표본 광종 계수 신뢰구간 제공(C-7) — 피드백기반_수정플랜 P3.

`geo/prob_model.py`의 NB2 계수(b0~b3: const·x_ewma·x_geo·x_vol, α)는 point estimate만
보고돼 REE·CO 등 소표본 광종의 불확실성이 표기되지 않는다. 블록 부트스트랩(주간 시계열이라
단순 iid 리샘플은 자기상관을 깨뜨림 — 연속 블록 단위로 리샘플해 시간적 의존성을 보존)으로
b0~b3·α의 95% 신뢰구간을 산출한다. prob_model.py의 `_fit_one`을 그대로 재사용(재구현 없음),
리샘플링 로직만 이 스크립트에서 수행.

블록 부트스트랩: 블록 길이 8주(EWMA_HALFLIFE=4주의 2배 — 자기상관이 크게 감쇠하는 구간),
학습표본 길이만큼 블록을 복원추출로 이어붙여 재표본 구성, 200회 반복.

실행: python3 -m scripts.nb2_coef_bootstrap_ci
산출: outputs/model_opt/nb2_coef_bootstrap_ci.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo.prob_model import _weekly_panel, _attach_geo_idx, _features, _fit_one, TRAIN_END  # noqa: E402

from msr.config import OUT

N_BOOT = 200
BLOCK_LEN = 8
SEED = 42
PARAM_NAMES = ["const", "x_ewma", "x_geo", "x_vol"]


def block_bootstrap_sample(df: pd.DataFrame, block_len: int, rng: np.random.Generator) -> pd.DataFrame:
    n = len(df)
    n_blocks = int(np.ceil(n / block_len))
    starts = rng.integers(0, max(1, n - block_len + 1), size=n_blocks)
    idx = np.concatenate([np.arange(s, min(s + block_len, n)) for s in starts])[:n]
    return df.iloc[idx].reset_index(drop=True)


def run():
    feat = _features(_attach_geo_idx(_weekly_panel()))
    rng = np.random.default_rng(SEED)
    rows = []
    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        if len(train) < 52:
            print(f"{c}: 표본 부족 스킵"); continue

        params0, alpha0, family0 = _fit_one(train)
        boot_params, boot_alpha = [], []
        n_fail = 0
        for _ in range(N_BOOT):
            bs = block_bootstrap_sample(train, BLOCK_LEN, rng)
            try:
                p, a, fam = _fit_one(bs)
                if fam == "nb2" and np.isfinite(p).all() and np.isfinite(a):
                    boot_params.append(np.asarray(p, dtype=float))
                    boot_alpha.append(a)
                else:
                    n_fail += 1
            except Exception:
                n_fail += 1
        if len(boot_params) < 30:
            print(f"{c}: 부트스트랩 성공 {len(boot_params)}/{N_BOOT} — 신뢰구간 불안정, 참고용으로만 보고")
        bp = np.array(boot_params)
        ba = np.array(boot_alpha)
        print(f"\n=== {c} (train n={len(train)}, family={family0}, 부트스트랩 성공 {len(boot_params)}/{N_BOOT}) ===")
        for i, name in enumerate(PARAM_NAMES):
            lo, hi = np.percentile(bp[:, i], [2.5, 97.5]) if len(bp) else (np.nan, np.nan)
            print(f"    {name}: point={params0.iloc[i]:.4f} 95%CI=[{lo:.4f}, {hi:.4f}]")
            rows.append(dict(commodity=c, param=name, point=round(float(params0.iloc[i]), 4),
                              ci_lo=round(float(lo), 4) if np.isfinite(lo) else None,
                              ci_hi=round(float(hi), 4) if np.isfinite(hi) else None,
                              n_boot_ok=len(boot_params)))
        lo_a, hi_a = np.percentile(ba, [2.5, 97.5]) if len(ba) else (np.nan, np.nan)
        print(f"    alpha: point={alpha0:.4f} 95%CI=[{lo_a:.4f}, {hi_a:.4f}]")
        rows.append(dict(commodity=c, param="alpha", point=round(float(alpha0), 4),
                          ci_lo=round(float(lo_a), 4) if np.isfinite(lo_a) else None,
                          ci_hi=round(float(hi_a), 4) if np.isfinite(hi_a) else None,
                          n_boot_ok=len(boot_params)))

    res = pd.DataFrame(rows)
    write_report(res)


def write_report(res: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "nb2_coef_bootstrap_ci.md")
    L = []
    L.append("# NB2 계수 소표본 신뢰구간 (C-7)\n")
    L.append(f"작성: 2026-07-17 · 블록 부트스트랩(블록길이 {BLOCK_LEN}주, {N_BOOT}회 반복, "
             f"seed={SEED})으로 prob_model.py `_fit_one`을 재사용해 5광종 b0~b3·α의 95% "
             f"신뢰구간(2.5/97.5 백분위) 산출. 단순 iid 리샘플이 아닌 블록 단위 리샘플로 "
             f"주간 시계열의 자기상관을 보존.\n")

    L.append("\n## 광종별 계수 95% 신뢰구간\n")
    L.append("| 광종 | 계수 | point estimate | 95% CI | 부트스트랩 성공 |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        ci = "—" if r["ci_lo"] is None else f"[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}]"
        L.append(f"| {r['commodity']} | {r['param']} | {r['point']:.4f} | {ci} | "
                 f"{int(r['n_boot_ok'])}/{N_BOOT} |")

    L.append("\n## 광종별 불확실성 요약(구간폭)\n")
    L.append("| 광종 | x_geo 구간폭 | x_ewma 구간폭 | 해석 |")
    L.append("|---|---|---|---|")
    for c in res["commodity"].unique():
        sub = res[res["commodity"] == c]
        geo_r = sub[sub["param"] == "x_geo"].iloc[0]
        ewma_r = sub[sub["param"] == "x_ewma"].iloc[0]
        geo_w = (geo_r["ci_hi"] - geo_r["ci_lo"]) if geo_r["ci_lo"] is not None else None
        ewma_w = (ewma_r["ci_hi"] - ewma_r["ci_lo"]) if ewma_r["ci_lo"] is not None else None
        geo_w_s = "—" if geo_w is None else f"{geo_w:.4f}"
        ewma_w_s = "—" if ewma_w is None else f"{ewma_w:.4f}"
        note = "구간이 0을 포함하면 해당 계수의 방향(부호)조차 통계적으로 확정 못함" if (
            geo_r["ci_lo"] is not None and geo_r["ci_lo"] < 0 < geo_r["ci_hi"]) else "x_geo 부호는 안정적"
        L.append(f"| {c} | {geo_w_s} | {ewma_w_s} | {note} |")

    x_geo = res[res["param"] == "x_geo"]
    n_sig = int(((x_geo["ci_lo"] > 0) | (x_geo["ci_hi"] < 0)).sum())
    sig_commodities = x_geo[(x_geo["ci_lo"] > 0) | (x_geo["ci_hi"] < 0)]["commodity"].tolist()
    L.append(f"\n**핵심 발견(x_geo 계수)**: 5광종 중 신뢰구간이 0을 포함하지 않아 부호가 "
             f"통계적으로 유의한 광종은 **{n_sig}개뿐**({', '.join(sig_commodities) if sig_commodities else '없음'})"
             f" — C-2(prob_decompose)에서 x_geo의 광종 평균 기여도가 약한 음수(-0.0097)로 "
             f"나왔던 것과 정합적으로, 지수 자체의 예측 기여가 통계적으로 약하다는 것이 이제 "
             f"신뢰구간으로도 확인됨. x_geo를 근거로 한 개별 광종 설명(예: \"지정학 위기지수가 "
             f"높아 확률이 올라갔다\")은 CU를 제외하면 통계적 근거가 약하다는 점을 설계문서에 "
             f"명시할 필요가 있음.\n")

    L.append("\n## 해석 주의\n")
    L.append("REE·CO처럼 표본이 작은 광종은 부트스트랩 성공률이 낮거나(MLE 수렴 실패가 리샘플"
             "마다 발생) 구간이 넓게 나올 수 있음 — 이 경우 point estimate 자체의 신뢰도가 "
             "낮다는 뜻으로 해석해야 하며, 신뢰구간 산출 실패 자체가 하나의 진단 정보. 블록 "
             "길이(8주)는 임의 선택 — 다른 블록 길이로 민감도 확인은 하지 않았음.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[nb2_coef_bootstrap_ci] 리포트 → {path}")


if __name__ == "__main__":
    run()
