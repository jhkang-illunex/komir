# -*- coding: utf-8 -*-
"""R10 재현성 검토 — ph_psa·fgap_ni 채택후보(유의) 전환(2026-08-04)의 재현성 확인.

배경: KOMIS 가격 5주 갱신(fact_price 종점 2026-06-08→2026-07-06) 후 R10 전면
재검정에서 ph_psa(QWK CI 하한 +0.0153)·fgap_ni(+0.0045)가 방향긍정 보류→
채택후보(유의)로 전환. 갱신으로 늘어난 검정행은 광종당 주간 4행뿐이라
전환이 우연(부트스트랩 잡음·소표본)인지 실효인지 확인이 필요.

검토 4종:
 1) 결정론 재현(replay): 08-04 하네스와 동일하게 스크리닝→유망 목록→공유
    rng(0) 순차 부트스트랩을 재실행, 리포트 수치와 대조.
 2) 시드 강건성: ph_psa·fgap_ni만 독립 시드 1..10(+n_iter 20000 정밀 1회)로
    부트스트랩 반복 — 채택 판정(QWK CI 하한>0)이 시드에 안정적인지.
 3) 갱신 전 대조: NI 패널을 2026-06-08(갱신 전 종점)로 절단 후 같은 검정
    (시드 0..9) — 07-30 보류 판정으로 되돌아가는지.
 4) 신규 행 정오표: 갱신으로 추가된 NI 4행에서 기준(pA)/후보(pB) 예측 비교.

실행: cd mineral_supply_risk && MSR_DB=<warehouse> \
      python -m scripts.r10_repro_check_phpsa_fgapni
산출: outputs/model_opt/r10_repro_check_260804.md
"""
from __future__ import annotations
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                                # noqa: E402
from scripts.override_backtest import qwk                                 # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG, FOLDS  # noqa: E402
from scripts.diagnosis_ylag_deep_review import (                          # noqa: E402
    add_dynamics, e2_delta_classifier, pooled_design,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F          # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                      # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                       # noqa: E402
    build_pmi, PMI_F, bootstrap_diff,
)
from scripts.diag_refine1 import build_refined                            # noqa: E402
from scripts.r10_retune_harness import (                                  # noqa: E402
    build_new_features, build_derived_features,
)

CUT = pd.Timestamp("2026-06-08")   # 가격 갱신 전 패널 종점(07-30 리포트 기준)
TARGETS = ["ph_psa", "fgap_ni"]
# 08-04 리포트(r10_retune_report.md, 워크트리) 기재값 — replay 대조용
REPORTED = {
    "li_ar":   (+0.0206, +0.1016, 1.000),
    "cli_kr":  (+0.0068, +0.0472, 0.997),
    "ph_psa":  (+0.0153, +0.1306, 0.995),
    "fgap_ni": (+0.0045, +0.0489, 0.984),
}


def build_stack(db: str):
    """08-04 하네스 main()과 동일한 패널·피처 스택."""
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_pmi(db, df)
    df = build_refined(db, df)
    from scripts.diagnosis_tier1_eval import build_tier1
    df = build_tier1(db, df)
    df, meta = build_new_features(db, df)
    df, meta2 = build_derived_features(db, df)
    meta.update(meta2)
    return df, meta


def preds_with_dates(dfx: pd.DataFrame, feats: list[str]):
    """bootstrap_diff 내부 preds()와 동일 로직 + obs_date 반환(정오표용)."""
    ys, lags, ps, dts = [], [], [], []
    for t0, t1 in FOLDS:
        tr = dfx[dfx["obs_date"] < t0].copy()
        te = dfx[(dfx["obs_date"] >= t0) & (dfx["obs_date"] < t1)].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        dtr = np.clip(tr["grade_ord"].values - tr["grade_lag1"].round().values,
                      -1, 1).astype(int)
        Xtr, Xte = pooled_design(tr, te, feats)
        m = LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0)
        m.fit(Xtr, dtr)
        dh = m.predict(Xte).astype(int)
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        ys.append(te["grade_ord"].astype(int).values)
        lags.append(lag)
        ps.append(np.clip(lag + dh, 0, 2))
        dts.append(te["obs_date"].values)
    return (np.concatenate(ys), np.concatenate(lags),
            np.concatenate(ps), np.concatenate(dts))


def fmt(b: dict) -> str:
    return (f"QWK CI [{b['qwk_ci'][0]:+.4f},{b['qwk_ci'][1]:+.4f}] "
            f"P={b['qwk_p']:.3f} | chg CI [{b['chg_ci'][0]:+.3f},"
            f"{b['chg_ci'][1]:+.3f}] P={b['chg_p']:.3f}")


def adopt(b: dict) -> bool:
    """하네스와 동일한 채택후보 판정 규칙."""
    return (b["qwk_ci"][0] > 0) or (b["chg_ci"][0] > 0 and b["qwk_ci"][0] > -0.005)


def main():
    db = os.environ["MSR_DB"]
    df, meta = build_stack(db)
    print(f"패널 종점: {df['obs_date'].max().date()}")
    L = ["# R10 재현성 검토 — ph_psa·fgap_ni (2026-08-04 채택후보 전환)\n",
         f"패널 종점 {df['obs_date'].max().date()} · 절단 대조 기준 {CUT.date()} · "
         f"판정 규칙=하네스 동일(QWK CI 하한>0)\n"]

    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    CHAMP = nolag + INV_F + exch.CNINV_F + PMI_F
    from scripts.diagnosis_tier1_eval import CNOI_F
    PER_CC_CHAMP = {"CU": nolag + CNOI_F,
                    "NI": nolag + INV_F + exch.CNINV_F,
                    "LI": nolag, "CO": nolag, "REE": nolag}
    champ = e2_delta_classifier(df, CHAMP, "Logistic")
    print(f"챔피언(스크리닝): QWK {champ['QWK']:.4f} chg {champ['chg_acc']:.4f} "
          f"FAR {champ['FAR']:.4f}")

    # ── 1) 결정론 재현: 하네스와 동일 스크리닝→공유 rng(0) 순차 부트스트랩 ──
    L.append("## 1) 결정론 재현(replay) — 08-04 리포트 대조\n")
    promising = []
    for name, m in meta.items():
        cov = df[m["feats"][0]].notna().mean()
        if cov < 0.05:
            continue
        if m["ccs"] == ["*"]:
            r = e2_delta_classifier(df, CHAMP + m["feats"], "Logistic")
            base, axis = champ, "풀링"
        else:
            cc = m["ccs"][0]
            d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
            base_feats = PER_CC_CHAMP.get(cc, nolag)
            base = e2_delta_classifier(d1, base_feats, "Logistic")
            r = e2_delta_classifier(d1, base_feats + m["feats"], "Logistic")
            axis = cc
        better = (r["QWK"] >= base["QWK"] - 0.003 and
                  (r["chg_acc"] > base["chg_acc"] or r["FAR"] < base["FAR"] - 0.01)) \
            or r["QWK"] > base["QWK"] + 0.005
        if better:
            promising.append((name, m, axis))
    L.append(f"- 유망 목록 재현: {len(promising)}건 — "
             f"{', '.join(n for n, _, _ in promising)}")
    print(f"유망 {len(promising)}건: {[n for n, _, _ in promising]}")

    rng = np.random.default_rng(0)
    replay = {}
    for name, m, axis in promising:
        dfx = df if axis == "풀링" else \
            df[df["commodity_code"] == axis].reset_index(drop=True)
        bf = CHAMP if axis == "풀링" else PER_CC_CHAMP.get(axis, nolag)
        b = bootstrap_diff(dfx, bf, bf + m["feats"], nolag, rng)
        replay[name] = b
        print(f"replay {name} [{axis}]: {fmt(b)}")
    for name, (lo, hi, p) in REPORTED.items():
        b = replay.get(name)
        if b is None:
            L.append(f"- {name}: **유망 목록에서 탈락 — 재현 실패(원인 확인 필요)**")
            continue
        ok = (round(b["qwk_ci"][0], 4) == lo and round(b["qwk_ci"][1], 4) == hi
              and round(b["qwk_p"], 3) == p)
        L.append(f"- {name}: {fmt(b)} — 리포트 [{lo:+.4f},{hi:+.4f}] P={p:.3f} → "
                 + ("**일치**" if ok else "**불일치(⚠ 원인 확인 필요)**"))

    # ── 2) 시드 강건성 + 3) 갱신 전 절단 대조 ─────────────────────────
    d_ni = df[df["commodity_code"] == "NI"].reset_index(drop=True)
    d_pre = d_ni[d_ni["obs_date"] <= CUT].reset_index(drop=True)
    bf_ni = PER_CC_CHAMP["NI"]
    L.append(f"\n갱신 후 NI 패널 {len(d_ni)}행 / 절단(≤{CUT.date()}) {len(d_pre)}행 — "
             f"차이 {len(d_ni) - len(d_pre)}행\n")

    for name in TARGETS:
        feats = meta[name]["feats"]
        L.append(f"## 2·3) {name} — 시드 강건성·절단 대조\n")
        for tag, dfx in (("갱신 후(전체)", d_ni), (f"절단(≤{CUT.date()})", d_pre)):
            rows, n_adopt = [], 0
            for s in range(1, 11):
                b = bootstrap_diff(dfx, bf_ni, bf_ni + feats, nolag,
                                   np.random.default_rng(s))
                rows.append(b)
                n_adopt += int(adopt(b))
            lo_min = min(b["qwk_ci"][0] for b in rows)
            lo_max = max(b["qwk_ci"][0] for b in rows)
            p_min = min(b["qwk_p"] for b in rows)
            p_max = max(b["qwk_p"] for b in rows)
            bp = bootstrap_diff(dfx, bf_ni, bf_ni + feats, nolag,
                                np.random.default_rng(42), n_iter=20000)
            L.append(f"- **{tag}**: 시드 10종 채택 {n_adopt}/10 · CI 하한 "
                     f"[{lo_min:+.4f},{lo_max:+.4f}] · P [{p_min:.3f},{p_max:.3f}]")
            L.append(f"  - 정밀(n_iter=20000, seed42): {fmt(bp)} → "
                     + ("채택후보(유의)" if adopt(bp) else "방향긍정 보류"))
            print(f"{name} {tag}: 채택 {n_adopt}/10, CI하한 [{lo_min:+.4f},"
                  f"{lo_max:+.4f}], 정밀 {fmt(bp)}")

        # ── 4) 신규 4행 정오표 ────────────────────────────────────
        y, lag, pA, dts = preds_with_dates(d_ni, bf_ni)
        _, _, pB, _ = preds_with_dates(d_ni, bf_ni + feats)
        new = pd.to_datetime(pd.Series(dts)) > CUT
        L.append(f"  - 신규 행({int(new.sum())}건) 정오표(실제/기준pA/후보pB):")
        for i in np.where(new.values)[0]:
            d = pd.Timestamp(dts[i]).date()
            mark = ("B만 정답" if (pB[i] == y[i] and pA[i] != y[i]) else
                    "A만 정답" if (pA[i] == y[i] and pB[i] != y[i]) else
                    "둘 다 정답" if pA[i] == y[i] else "둘 다 오답")
            L.append(f"    - {d}: y={y[i]} lag={lag[i]} pA={pA[i]} pB={pB[i]} → {mark}")
        old = ~new.values
        gain_new = int(((pB == y) & (pA != y) & new.values).sum())
        loss_new = int(((pA == y) & (pB != y) & new.values).sum())
        gain_old = int(((pB == y) & (pA != y) & old).sum())
        loss_old = int(((pA == y) & (pB != y) & old).sum())
        L.append(f"  - 우세 분해: 기존 구간 net {gain_old - loss_old:+d}"
                 f"(득 {gain_old}/실 {loss_old}) · 신규 구간 net "
                 f"{gain_new - loss_new:+d}(득 {gain_new}/실 {loss_new})\n")
        print(f"{name} 우세 분해: 기존 net {gain_old - loss_old:+d}, "
              f"신규 net {gain_new - loss_new:+d}")

    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "r10_repro_check_260804.md")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[repro] 리포트 → {path}")


if __name__ == "__main__":
    main()
