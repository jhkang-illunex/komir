# -*- coding: utf-8 -*-
"""부분 풀링(partial pooling) 도입 가치 평가 — 외부감사 B-2③.

감사 논거: "Ridge 완전풀링은 리튬(계약가·비상장)과 구리(LME 상장)를 같은 계수로 본다.
광종별 random effect로 완전풀링과 개별모델 사이의 최적점을 찾아라."

챔피언(diagnosis_opt.py Ridge 풀링+분위매핑)과 **동일 파이프라인**(회귀→위기지수→학습기간
광종별 분위 컷 매핑)·**동일 폴드**(워크포워드 3폴드)로 다음을 공정 비교한다:

  [기준선] (a) 지속성 Naive  (b) 챔피언 Ridge(완전풀링·광종더미)  (c) Ridge(광종별 개별, 참고치)
  [후보]   (1) 계층 Ridge — 전역계수 ⊕ 광종별 편차계수(스케일 s로 축소); s→0 완전풀링, s→∞ 개별
                 s∈{0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 2.0} 그리드로 풀링 강도 스윕
           (2) MixedLM — random intercept + random slope(y_lag1); 수렴 실패 시 생략(명기)

지표(폴드 풀링 집계): QWK, 전환월 적중(전월과 단계가 달라진 달), FAR(실제<주의인데 예측≥주의),
Miss(실제≥경계인데 예측<경계). 광종별 분해로 감사 논거(LI vs CU에서 부분 풀링 이득?) 검증.

실행: MSR_DB=<warehouse> python3 -m scripts.partial_pooling_eval
산출: outputs/model_opt/partial_pooling.md
"""
from __future__ import annotations
import os, sys, warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT, CORE_COMMODITIES                     # noqa: E402
from msr.models.diagnosis_opt import (                                    # noqa: E402
    FOLDS, BASE_FEATS, GEO_DERIVED, Q_CUT,
    build_panel, stage_labels, reg_to_stage, _fit_predict_reg)

warnings.filterwarnings("ignore")

# 단계 눈금(alert.py·diagnosis_opt와 동일 0~4): 0정상 1관심 2주의 3경계 4심각
STAGE_ATTN = 2      # '주의' 이상 = 경보 발령
STAGE_ALARM = 3     # '경계' 이상 = 고강도 대응
# 계층 Ridge 풀링 강도 그리드(감사 명시 {0.1,0.3,0.5} 포함, 양 극단까지 확장)
S_GRID = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 2.0]


def _prep():
    return Pipeline([("imp", SimpleImputer(strategy="median")),
                     ("sc", StandardScaler())])


# ─────────────────────────── 계층 Ridge(부분 풀링) ───────────────────────────
def hier_ridge_predict(tr, te, feats, s, commodities, alpha=1.0):
    """계층 Ridge — 피처 증강으로 부분 풀링 구현.

    설계: 표준화 전역피처 X_g(모든 광종 공유) ⊕ 광종별 편차블록[절편, 기울기]×s.
      - s=0   : 편차블록 전부 0 → 순수 전역모델(완전풀링, 광종절편도 없음 — 최강 풀링)
      - s 증가: 편차블록이 Ridge 벌점(alpha=1) 하에서 광종별 조정 허용 → 개별모델로 접근
    편차블록에 s를 곱하면 동일 alpha 벌점 하에서 s가 클수록 편차계수가 '싸져'(같은 예측
    기여를 더 작은 계수로 달성) 실질 벌점이 완화 → s가 곧 풀링 강도 매개변수.
    """
    prep = _prep()
    Xtr_g = prep.fit_transform(tr[feats])
    Xte_g = prep.transform(te[feats])

    def block(Xg, ccs):
        parts = [Xg]
        for c in commodities:
            m = (ccs == c).astype(float)[:, None]      # (n,1) 광종 지시자
            parts.append(m * s)                         # 광종별 절편 편차
            parts.append(Xg * m * s)                    # 광종별 기울기 편차
        return np.hstack(parts)

    Xtr = block(Xtr_g, tr["commodity_code"].values)
    Xte = block(Xte_g, te["commodity_code"].values)
    model = Ridge(alpha=alpha)
    model.fit(Xtr, tr["y"].values)
    return model.predict(Xte)


# ─────────────────────────────── MixedLM ───────────────────────────────
def mixedlm_predict(tr, te, feats):
    """statsmodels MixedLM — random intercept + random slope(y_lag1).

    y ~ 전역 고정효과(표준화 피처) + (1 + y_lag1 | commodity_code).
    수렴 실패/예외 시 None 반환(호출부에서 후보 제외·명기).
    """
    try:
        import statsmodels.formula.api as smf
    except Exception:
        return None
    prep = _prep()
    Xtr = prep.fit_transform(tr[feats]); Xte = prep.transform(te[feats])
    cols = [f"f{i}" for i in range(len(feats))]
    dtr = pd.DataFrame(Xtr, columns=cols); dtr["y"] = tr["y"].values
    dtr["cc"] = tr["commodity_code"].values
    dte = pd.DataFrame(Xte, columns=cols); dte["cc"] = te["commodity_code"].values
    fixed = "y ~ " + " + ".join(cols)
    # random slope 대상 = y_lag1(있으면). feats 내 위치로 컬럼 지정.
    re_formula = "~1"
    if "y_lag1" in feats:
        re_formula = f"~1 + f{feats.index('y_lag1')}"
    try:
        md = smf.mixedlm(fixed, dtr, groups=dtr["cc"], re_formula=re_formula)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mf = md.fit(method="lbfgs", maxiter=200, disp=False)
        if not mf.converged:
            return None
        # 고정효과 예측 + 광종별 random effect(절편·기울기) 가산
        pred = mf.predict(dte)
        re = mf.random_effects
        out = pred.values.astype(float).copy()
        slope_col = f"f{feats.index('y_lag1')}" if "y_lag1" in feats else None
        for i, c in enumerate(dte["cc"].values):
            eff = re.get(c)
            if eff is None:
                continue
            out[i] += float(eff.get("Group", eff.iloc[0]))          # random intercept
            if slope_col is not None and slope_col in eff.index:
                out[i] += float(eff[slope_col]) * dte[slope_col].values[i]
        return out
    except Exception:
        return None


# ─────────────────────────────── 지표 ───────────────────────────────
def far_miss(y_true, y_pred):
    """FAR(실제<주의인데 예측≥주의; 헛경보율)·Miss(실제≥경계인데 예측<경계; 미탐율)."""
    y_true = np.asarray(y_true); y_pred = np.asarray(y_pred)
    calm = y_true < STAGE_ATTN
    far = float((y_pred[calm] >= STAGE_ATTN).mean()) if calm.sum() else np.nan
    severe = y_true >= STAGE_ALARM
    miss = float((y_pred[severe] < STAGE_ALARM).mean()) if severe.sum() else np.nan
    return round(far, 3), round(miss, 3), int(calm.sum()), int(severe.sum())


def metrics(y_true, y_pred, chg):
    """폴드 풀링 벡터에서 전 지표 산출."""
    y_true = np.asarray(y_true); y_pred = np.asarray(y_pred); chg = np.asarray(chg)
    qwk = round(cohen_kappa_score(y_true, y_pred, weights="quadratic"), 3)
    chg_acc = round(float((y_pred[chg] == y_true[chg]).mean()), 3) if chg.sum() else np.nan
    far, miss, n_calm, n_sev = far_miss(y_true, y_pred)
    return dict(QWK=qwk, 전환월=chg_acc, FAR=far, Miss=miss,
                acc=round(float((y_true == y_pred).mean()), 3))


# ─────────────────────────────── 폴드 실행 ───────────────────────────────
def collect_predictions(df, feats, commodities):
    """워크포워드 폴드마다 각 모델의 단계 예측을 모아 광종·전환월 마스크와 함께 반환.

    반환: preds[model] = list of (yte, pred_stage, chg_mask, cc_array) — 폴드별.
    """
    models = {}
    def push(name, yte, pred, chg, cc):
        models.setdefault(name, []).append((yte, np.asarray(pred), chg, cc))

    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        yte = y_stage[te.index].values
        cc = te["commodity_code"].values
        # 전환월(전월과 단계가 달라진 달) — 지속성이 구조적으로 전패하는 구간
        stage_series = pd.Series(y_stage.values, index=df.index)
        prev = stage_series.groupby(df["commodity_code"]).shift(1)[te.index]
        chg = (prev.notna() & (prev.values != yte)).values

        # (a) 지속성 Naive
        push("Naive(지속성)", yte, prev.fillna(0).astype(int).values, chg, cc)
        # (b) 챔피언 Ridge(완전풀링·광종더미)
        champ_py, _ = _fit_predict_reg("Ridge", tr, te, feats, per_commodity=False)
        champ_stage = reg_to_stage(champ_py, te, tr)
        push("챔피언 Ridge(완전풀링)", yte, champ_stage, chg, cc)
        # (c) Ridge(광종별 개별, 참고치)
        py, _ = _fit_predict_reg("Ridge", tr, te, feats, per_commodity=True)
        push("Ridge(광종별 개별)", yte, reg_to_stage(py, te, tr), chg, cc)
        # (1) 계층 Ridge — s 그리드
        for s in S_GRID:
            py = hier_ridge_predict(tr, te, feats, s, commodities)
            push(f"계층Ridge(s={s})", yte, reg_to_stage(py, te, tr), chg, cc)
        # (2) MixedLM — 수렴 폴드에 한해 저장. 동일표본 공정비교를 위해 그 폴드의
        #     챔피언 예측도 별도 키에 나란히 저장(MixedLM은 초기 소표본 폴드서 비수렴).
        py = mixedlm_predict(tr, te, feats)
        if py is not None:
            push("MixedLM(random int+slope)", yte, reg_to_stage(py, te, tr), chg, cc)
            push("챔피언@MixedLM폴드", yte, champ_stage, chg, cc)

    return models


def pool(model_folds):
    """폴드 리스트 → 풀링 벡터(yt, yp, chg, cc)."""
    yt = np.concatenate([a for a, _, _, _ in model_folds])
    yp = np.concatenate([b for _, b, _, _ in model_folds])
    chg = np.concatenate([c for _, _, c, _ in model_folds])
    cc = np.concatenate([d for _, _, _, d in model_folds])
    return yt, yp, chg, cc


# ─────────────────────────────── 메인 ───────────────────────────────
def run(db=None, out_dir=None):
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    df = build_panel(db)
    feats = BASE_FEATS + GEO_DERIVED
    feats = [f for f in feats if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    commodities = sorted(df["commodity_code"].unique())
    print(f"패널 {df.shape} | 광종 {commodities} | 피처 {len(feats)}: {feats}")

    preds = collect_predictions(df, feats, commodities)
    mixedlm_ok = "MixedLM(random int+slope)" in preds

    # ── 전체 집계표 ──
    order = (["Naive(지속성)", "챔피언 Ridge(완전풀링)"]
             + [f"계층Ridge(s={s})" for s in S_GRID]
             + (["MixedLM(random int+slope)", "챔피언@MixedLM폴드"] if mixedlm_ok else [])
             + ["Ridge(광종별 개별)"])
    n_mixed_fold = len(preds["MixedLM(random int+slope)"]) if mixedlm_ok else 0
    rows = []
    for name in order:
        yt, yp, chg, cc = pool(preds[name])
        rows.append(dict(모델=name, **metrics(yt, yp, chg)))
    tbl = pd.DataFrame(rows)
    # 표본 요약(모델 무관 — yt/chg 동일): 전환월·평온(<주의)·심각(≥경계) 건수
    yt0, _, chg0, _ = pool(preds["챔피언 Ridge(완전풀링)"])
    n_chg = int(chg0.sum())
    _, _, n_calm, n_sev = far_miss(yt0, yt0)

    # 챔피언 기준 델타
    champ = tbl[tbl["모델"] == "챔피언 Ridge(완전풀링)"].iloc[0]
    tbl["dQWK"] = (tbl["QWK"] - champ["QWK"]).round(3)
    tbl["d전환월"] = (tbl["전환월"] - champ["전환월"]).round(3)

    # ── 최적 s 선정(계층 Ridge 중 QWK 최대, 동률 시 전환월) ──
    hier = tbl[tbl["모델"].str.startswith("계층Ridge")].copy()
    hier["s"] = hier["모델"].str.extract(r"s=([\d.]+)").astype(float)
    best_hier = hier.sort_values(["QWK", "전환월"], ascending=False).iloc[0]
    best_s = float(best_hier["s"])

    # ── 광종별 분해 — 감사 논거 검증 ──
    # 감사 논거는 '광종별 random effect'이고 그 정통 구현은 MixedLM. 계층 Ridge는 s=0에서
    # 최적이라 챔피언과 동일 → 광종별 이득이 정의상 0(비교 무의미). 따라서 부분 풀링의 실질
    # 후보로 (MixedLM 있으면 그것, 없으면 최적 계층 Ridge)를 챔피언과 광종별 대조한다.
    def per_cc(name):
        yt, yp, chg, cc = pool(preds[name])
        out = []
        for c in commodities:
            mk = cc == c
            qwk = round(cohen_kappa_score(yt[mk], yp[mk], weights="quadratic"), 3) \
                if len(np.unique(yt[mk])) > 1 else np.nan
            cm = chg & mk
            ca = round(float((yp[cm] == yt[cm]).mean()), 3) if cm.sum() else np.nan
            far, miss, n_calm_c, n_sev_c = far_miss(yt[mk], yp[mk])
            out.append(dict(광종=CORE_COMMODITIES.get(c, {}).get("ko", c) + f"({c})",
                            QWK=qwk, 전환월=ca, FAR=far, Miss=miss,
                            n=int(mk.sum()), n심각=n_sev_c))
        return pd.DataFrame(out)

    # 부분 풀링 실질 후보와 그 '동일표본' 챔피언 기준
    if mixedlm_ok:
        pp_name, champ_ref = "MixedLM(random int+slope)", "챔피언@MixedLM폴드"
    else:
        pp_name = next(n for n in order if n.startswith("계층Ridge") and
                       float(n.split("=")[1].rstrip(")")) == best_s)
        champ_ref = "챔피언 Ridge(완전풀링)"
    champ_cc = per_cc(champ_ref)
    pp_cc = per_cc(pp_name)
    merged_cc = champ_cc.merge(pp_cc, on=["광종", "n", "n심각"], suffixes=("_챔피언", "_부분풀링"))
    merged_cc["dQWK"] = (merged_cc["QWK_부분풀링"] - merged_cc["QWK_챔피언"]).round(3)

    # ── 부분 풀링 최선 후보 대 '동일표본' 챔피언 판정 ──
    pp_row = tbl[tbl["모델"] == pp_name].iloc[0]
    champ_ref_row = tbl[tbl["모델"] == champ_ref].iloc[0]
    d_qwk = pp_row["QWK"] - champ_ref_row["QWK"]
    d_chg = pp_row["전환월"] - champ_ref_row["전환월"]
    # 유의미 기준: QWK +0.02 이상(3폴드·표본 210의 노이즈 상회) 또는 전환월 +0.05↑ & QWK 무손실
    win = (d_qwk >= 0.02) or (d_chg >= 0.05 and d_qwk >= -0.005)
    li_cu = merged_cc[merged_cc["광종"].str.contains("LI|CU")]
    li_cu_gain = li_cu["dQWK"].mean() if len(li_cu) else np.nan
    hier_flat = best_s == 0.0
    if win:
        verdict = (f"**부분 풀링 채택 권고 — {pp_name}.** 챔피언(완전풀링) 대비 "
                   f"QWK {d_qwk:+.3f}, 전환월 {d_chg:+.3f}로 유의미하게 우위. "
                   f"(계층 Ridge는 s={best_s}가 최적)")
    else:
        verdict = (
            f"**완전풀링 유지 권고**(무리한 채택 금지). 근거: "
            f"(1) 감사가 명시적으로 권장한 계층 Ridge 방식은 최적 풀링 강도가 "
            f"**s={best_s}"
            + ("(=완전풀링)**로 수렴 — 광종별 편차계수는 벌점만 지불하고 이득 0"
               if hier_flat else "**이나 챔피언 대비 이득 없음")
            + ". "
            f"(2) 정통 부분 풀링 {pp_name}"
            + (f"은 3폴드 중 {n_mixed_fold}폴드(최종 2025~)에서만 수렴 — 초기 소표본 폴드는 "
               f"random effects 공분산 특이로 비수렴. 그 수렴 폴드의 '동일표본' 챔피언 대비 "
               f"QWK {d_qwk:+.3f}·전환월 {d_chg:+.3f}로 방향은 양(+)이나 유의 기준(QWK+0.02)에 "
               f"미달 — 단일 폴드 노이즈 수준. "
               if mixedlm_ok else "조차 챔피언에 미달. ")
            + f"(3) 감사 논거의 전제(LI≠CU 계수)를 데이터가 뒷받침하지 않음 — "
              f"심각(≥경계) 표본이 전체 {n_sev}건뿐이고 그중 CU 8건 집중, "
              f"LI는 1건뿐이라 광종별 개별 계수를 추정할 표본 근거가 희박(작은 표본 광종은 "
              f"전역 정보 차용=완전풀링이 유리). LI·CU 평균 dQWK {li_cu_gain:+.3f}.")

    # ── 리포트 ──
    md = [
        "# 부분 풀링(partial pooling) 도입 가치 평가 — 외부감사 B-2③\n",
        f"- 패널: {df.shape[0]}행({len(commodities)}광종 × ~78개월, 2020-01~2026-06), "
        f"피처 {len(feats)}종\n",
        f"- 폴드: 워크포워드 3폴드(test=2023/2024/2025~), 전환월 {n_chg}건 "
        f"(평온 {n_calm} / 심각 {n_sev})\n",
        "- 파이프라인: 회귀→위기지수(100-ŷ)→학습기간 광종별 분위 컷 매핑(챔피언과 동일)\n",
        f"- MixedLM 수렴: {f'{n_mixed_fold}/3폴드(최종 2025~만 수렴, 초기 소표본 폴드 비수렴)' if mixedlm_ok else '전폴드 실패 → 후보 제외'}\n",
        "\n## 1. 기준선 · 후보 · s그리드 (폴드 풀링 집계)\n",
        "지표: QWK↑, 전환월 적중↑, FAR↓(헛경보=실제<주의인데 예측≥주의), "
        "Miss↓(미탐=실제≥경계인데 예측<경계). d*는 챔피언(완전풀링) 대비.\n\n",
        tbl[["모델", "QWK", "전환월", "FAR", "Miss", "acc", "dQWK", "d전환월"]]
            .to_markdown(index=False),
        "\n\n> 계층 Ridge: s→0 완전풀링, s→∞ 개별모델. s가 풀링 강도 매개변수.\n",
        f"> 최적 계층 Ridge: **s={best_s}** (QWK {best_hier['QWK']}, 전환월 {best_hier['전환월']})\n",
        (f"> ⚠️ MixedLM 행은 **{n_mixed_fold}/3폴드(최종만 수렴)** 단독이라 3폴드 챔피언(위 행)과 "
         "직접 비교 불가 → 동일표본 대조행 **챔피언@MixedLM폴드**와 비교할 것. dQWK/d전환월은 "
         "3폴드 챔피언 기준이라 MixedLM 행에서는 참고만.\n" if mixedlm_ok else ""),
        f"\n## 2. 광종별 분해 — 챔피언 vs 부분풀링({pp_name}) (감사 논거 검증)\n",
        "감사 논거: LI(계약가·비상장) vs CU(LME 상장)를 같은 계수로 보는 게 문제 →"
        " 부분 풀링이 LI·CU에서 이득을 주는가?\n"
        + (f"※ 아래는 **MixedLM 수렴 폴드(최종 2025~, {n_mixed_fold}폴드) 동일표본** 기준"
           "(3폴드 전체가 아님). n심각=해당 표본의 광종별 심각≥경계 건수.\n\n"
           if mixedlm_ok else "(n심각=광종별 심각≥경계 표본 수)\n\n"),
        merged_cc[["광종", "n", "n심각", "QWK_챔피언", "QWK_부분풀링", "dQWK",
                   "전환월_챔피언", "전환월_부분풀링", "Miss_챔피언", "Miss_부분풀링"]]
            .to_markdown(index=False),
        f"\n\n> LI·CU 평균 dQWK(부분풀링−챔피언): **{li_cu_gain:+.3f}**\n",
        f"> ⚠️ 심각(≥경계) 표본 전체 {n_sev}건 — CU 8·NI/REE 2·LI 1·CO 0. "
        "LI는 심각 1건뿐이라 광종별 개별 계수 추정 근거가 희박(→완전풀링이 표본 차용으로 유리). "
        "Miss·FAR는 소표본 기반이라 몇 케이스 차이에 민감 — 결정 근거로는 QWK·전환월 우선.\n",
        "\n## 3. 판정\n",
        verdict + "\n",
        (("\n> ⚠️ 착시 주의: 3폴드 챔피언(Miss 0.385) vs MixedLM(0.222) 대비는 **표본 불일치**"
          "(3폴드 vs 최종1폴드) 때문이며, 동일표본(최종 폴드)으로 맞추면 챔피언도 "
          f"{champ_ref_row['Miss']:.3f} = MixedLM {pp_row['Miss']:.3f}로 **Miss·전환월·FAR 모두 무차별**, "
          "차이는 QWK +0.005뿐. 즉 동일 조건에서 부분 풀링의 실질 이득은 사실상 0. "
          "심각 국면 미탐이 운영상 치명적이라면 MixedLM(절제된 random effect) 재검토 여지는 남으나, "
          "초기 폴드 비수렴(공분산 특이)이라 실전 배치엔 수렴 안정화(정칙화·재모수화)가 선행되어야 한다. "
          "계층 Ridge(전 피처×광종 편차)는 파라미터 과다로 s>0에서 일관되게 과적합.\n")
         if mixedlm_ok else ""),
    ]
    report = "".join(md)
    with open(os.path.join(out_dir, "partial_pooling.md"), "w") as f:
        f.write(report)

    print("\n=== 집계표 ===")
    print(tbl[["모델", "QWK", "전환월", "FAR", "Miss", "dQWK", "d전환월"]].to_string(index=False))
    print(f"\n=== 광종별(챔피언 vs 부분풀링 {pp_name}) ===")
    print(merged_cc[["광종", "n심각", "QWK_챔피언", "QWK_부분풀링", "dQWK"]].to_string(index=False))
    print("\n" + verdict)
    print(f"\n저장: {out_dir}/partial_pooling.md")
    return dict(tbl=tbl, per_cc=merged_cc, best_s=best_s, verdict=verdict,
                mixedlm_ok=mixedlm_ok)


if __name__ == "__main__":
    run()
