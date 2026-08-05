# -*- coding: utf-8 -*-
"""수급위기 진단모델 Lead time(선행 예측) 성능 평가 (2026-07-16, 외부감사 B-2①②).

질문(감사): "나우캐스트(h=0)만으론 정책 가치가 없다 — 예측 지평(lead time)별 성능과
허위경보율·미탐지율을 제시하라."

접근:
  진단·교사가 월 단위이므로 지평은 h=0(현행 나우캐스트)·1·2·3개월(주 환산 ≈ 0/4/9/13주).
  시점 t의 피처로 t+h의 4단계를 예측한다. diagnosis_opt와 동일한 워크포워드 3폴드 +
  Ridge(풀링)+분위매핑을 그대로 재사용하되, 타깃(교사 y·단계)만 광종별 shift(-h)한다.

미래참조(look-ahead) 차단 — 검증 포인트:
  · 피처는 t 시점 관측치. BASE_FEATS/GEO_DERIVED에는 당월 교사 y(t)가 없고 y_lag1=y(t-1)만
    포함되므로, 모델이 t+h를 맞히려 t의 교사를 훔쳐보는 일이 구조적으로 없다.
  · 타깃은 df.groupby(광종)['y'].shift(-h) → t행의 학습·평가 타깃 = t+h의 값(과거가 아닌 미래).
  · 학습 표본에서 타깃이 없는 꼬리(마지막 h개월)는 y_target NaN으로 제외 → 미래 없는 행 학습 금지.
  · 단계 컷은 폴드별 '학습기간 현재 crisis_index' 분위에서만 계산(reg_to_stage/stage_labels와
    동일) → 테스트·미래 분포 누수 없음.

지속성 Naive의 정직한 정의:
  예측을 만드는 시점에 '실제로 관측 가능한 마지막 단계'는 stage(t-1)이다(모델이 아는 최신 교사도
  y_lag1=y(t-1)). 따라서 지속성 예측 = stage(t-1)로 stage(t+h)를 예측(원본 단계 시계열 shift(1)).
  h=0에서 이는 diagnosis_opt의 'Naive(전월단계 유지, shift(1))'와 정확히 일치 → 현행 나우캐스트와
  기준선이 정합한다. 지속성은 정의상 '단계 변화'를 절대 예측하지 못한다(전환 recall=0).

지표(h별, 폴드 풀링):
  (a) QWK  (b) 전환월(t+h 단계가 최신 관측단계와 달라진 달) precision·recall
  (c) FAR(허위경보율): 실제 단계<2(주의 미만)인데 예측≥2(주의 이상)인 비율
  (d) Miss(미탐지율): 실제 단계≥3(경계 이상)인데 예측<3인 비율
  (e) 위 지표를 지속성 Naive 기준선에 대해서도 동일 산출.

부록: 비용민감 임계 스캔(미탐:오탐=5:1 가정) — h별 최적 경보 컷오프 이동. 비용비는 발주처 합의 필요.

실행: MSR_DB=<warehouse> python -m scripts.lead_time_eval
산출: outputs/model_opt/lead_time.md (+ 콘솔 표)
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                        # noqa: E402
from msr.models.diagnosis_opt import (FOLDS, BASE_FEATS, GEO_DERIVED,      # noqa: E402
                                      build_panel, stage_labels,
                                      reg_to_stage, _fit_predict_reg)

HORIZONS = [0, 1, 2, 3]                 # 개월
H_WEEKS = {0: "0주", 1: "≈4주", 2: "≈9주", 3: "≈13주"}   # 주 환산(리포트 병기)
COST_RATIO = (5, 1)                     # (미탐 비용, 오탐 비용) — 발주처 합의 필요(예시 가정)


# ─────────────────────────────── 지표 ───────────────────────────────
def _qwk(yt, yp):
    """QWK — 한쪽이 상수면(단계 분산 0) 정의 불가 → NaN."""
    if len(np.unique(yt)) < 2 or len(np.unique(yp)) < 2:
        return np.nan
    return round(cohen_kappa_score(yt, yp, weights="quadratic"), 3)


def metrics(yte, pred, last_obs):
    """h별 폴드 풀링 지표. yte=실제 t+h 단계, pred=예측, last_obs=최신관측단계(전환 기준=stage(t-1))."""
    yte, pred, last_obs = map(lambda a: np.asarray(a, int), (yte, pred, last_obs))
    # 전환월 = t+h 단계가 예측시점 최신관측단계와 달라진 달 (지속성이 구조적으로 놓치는 실가치 구간)
    actual_chg = yte != last_obs
    pred_chg = pred != last_obs
    tp = int((actual_chg & pred_chg).sum())
    prec = tp / int(pred_chg.sum()) if pred_chg.sum() else np.nan
    rec = tp / int(actual_chg.sum()) if actual_chg.sum() else np.nan
    # FAR: 실제<2(주의 미만)인데 예측≥2 / Miss: 실제≥3(경계 이상)인데 예측<3
    neg = yte < 2
    far = int(((pred >= 2) & neg).sum()) / int(neg.sum()) if neg.sum() else np.nan
    pos = yte >= 3
    miss = int(((pred < 3) & pos).sum()) / int(pos.sum()) if pos.sum() else np.nan
    return dict(QWK=_qwk(yte, pred),
                전환P=round(prec, 3) if not np.isnan(prec) else None,
                전환R=round(rec, 3) if not np.isnan(rec) else None,
                FAR=round(far, 3) if not np.isnan(far) else None,
                Miss=round(miss, 3) if not np.isnan(miss) else None,
                n=len(yte), n전환=int(actual_chg.sum()), n경계=int(pos.sum()))


def cost_scan(yte, pred, ratio=COST_RATIO):
    """비용민감 경보 컷오프 스캔. 경보=pred>=thr, 사건=실제단계>=3(경계 이상).
    비용 = w_miss×(미탐 건수) + w_fa×(오탐 건수). 최소 비용 thr과 곡선 반환."""
    w_miss, w_fa = ratio
    yte, pred = np.asarray(yte, int), np.asarray(pred, int)
    event = yte >= 3
    curve = {}
    for thr in (1, 2, 3, 4):
        alarm = pred >= thr
        miss = int((event & ~alarm).sum())      # 사건인데 경보 없음
        fa = int((~event & alarm).sum())        # 비사건인데 경보
        curve[thr] = dict(miss=miss, fa=fa, cost=w_miss * miss + w_fa * fa)
    best = min(curve, key=lambda k: curve[k]["cost"])
    return best, curve


# ─────────────────────────────── 평가 ───────────────────────────────
def eval_horizon(df, feats, h):
    """지평 h의 워크포워드 3폴드 풀링 예측 — (모델 지표, Naive 지표, 원자료) 반환."""
    m_yte, m_pred, m_last = [], [], []      # 모델
    n_pred = []                              # Naive(=last_obs와 동일하지만 명시적으로 축적)
    cc = df["commodity_code"]
    y_future_all = df.groupby(cc)["y"].shift(-h)     # t행 → t+h 교사값(학습·평가 공통 타깃원)
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        # 폴드 단계 시계열(학습기간 컷 적용, diagnosis_opt.stage_labels 재사용) → shift로 t+h·t-1 파생
        y_stage = stage_labels(df, tr_mask)
        ss = pd.Series(y_stage.values, index=df.index)
        target_stage = ss.groupby(cc).shift(-h)      # 실제 t+h 단계(평가 정답)
        last_stage = ss.groupby(cc).shift(1)         # 예측시점 최신 관측단계 = 지속성 예측
        # 학습: 미래 타깃이 존재하는 학습기간 행만(꼬리 h개월 제외 → 미래없는 행 학습 금지)
        tr_idx = df.index[tr_mask & y_future_all.notna()]
        te_idx = df.index[te_mask & target_stage.notna()]
        if len(te_idx) == 0 or len(tr_idx) < 60:
            continue
        tr = df.loc[tr_idx].copy()
        te = df.loc[te_idx].copy()
        tr_fit = tr.assign(y=y_future_all.loc[tr_idx].values)   # 학습 타깃을 t+h 교사로 교체
        pred_y, _ = _fit_predict_reg("Ridge", tr_fit, te, feats, per_commodity=False)
        pred_stage = reg_to_stage(pred_y, te, tr)    # tr 원본 crisis_index 폴드컷 → 예측 단계 매핑
        yte = target_stage.loc[te_idx].astype(int).values
        last = last_stage.loc[te_idx].fillna(0).astype(int).values
        m_yte.append(yte); m_pred.append(np.asarray(pred_stage, int)); m_last.append(last)
        n_pred.append(last)                          # 지속성 예측 = 최신 관측단계
    yte = np.concatenate(m_yte); pred = np.concatenate(m_pred); last = np.concatenate(m_last)
    npred = np.concatenate(n_pred)
    return metrics(yte, pred, last), metrics(yte, npred, last), (yte, pred, npred)


def run(db=None, out_dir=None):
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    df = build_panel(db)
    feats = [f for f in BASE_FEATS + GEO_DERIVED
             if f in df.columns and df[f].notna().sum() > 50 and df[f].nunique() > 2]
    print(f"패널 {df.shape} | 광종 {df['commodity_code'].nunique()} | 피처 {len(feats)}: {feats}")

    model_rows, naive_rows, raw = [], [], {}
    for h in HORIZONS:
        m, n, data = eval_horizon(df, feats, h)
        raw[h] = data
        model_rows.append(dict(h=h, 주=H_WEEKS[h], **m))
        naive_rows.append(dict(h=h, 주=H_WEEKS[h], **n))
    mdf = pd.DataFrame(model_rows)
    ndf = pd.DataFrame(naive_rows)

    # 판정: QWK가 Naive 대비 우위인 최대 연속 h
    edge = []
    for h in HORIZONS:
        mq = mdf.loc[mdf.h == h, "QWK"].iloc[0]
        nq = ndf.loc[ndf.h == h, "QWK"].iloc[0]
        edge.append((h, mq, nq, (mq is not None and nq is not None and mq > nq)))
    max_edge_h = -1
    for h, _mq, _nq, win in edge:
        if win:
            max_edge_h = h
        else:
            break     # 연속 우위가 끊기는 지평 직전까지
    verdict = (f"모델(Ridge 풀링+분위매핑)은 **h={max_edge_h}개월({H_WEEKS.get(max_edge_h,'')})까지** "
               f"지속성 Naive 대비 QWK 우위를 유지한다." if max_edge_h >= 0 else
               "모델이 어떤 지평에서도 지속성 Naive를 넘지 못했다.")

    # 비용민감 부록
    cost_rows = []
    for h in HORIZONS:
        yte, pred, _npred = raw[h]
        best, curve = cost_scan(yte, pred)
        cost_rows.append(dict(h=h, 주=H_WEEKS[h], 최적경보컷=f"단계≥{best}",
                              **{f"thr≥{k}_cost": v["cost"] for k, v in curve.items()}))
    cdf = pd.DataFrame(cost_rows)

    # ── 콘솔 ──
    print("\n=== 모델(Ridge 풀링+분위매핑) — 지평별 ===")
    print(mdf.to_string(index=False))
    print("\n=== 지속성 Naive 기준선 — 지평별 ===")
    print(ndf.to_string(index=False))
    print(f"\n판정: {verdict}")
    print("\n=== 비용민감 경보 컷오프 스캔(미탐:오탐=5:1) ===")
    print(cdf.to_string(index=False))

    # ── 리포트 ──
    show = ["h", "주", "QWK", "전환P", "전환R", "FAR", "Miss", "n", "n전환", "n경계"]
    with open(os.path.join(out_dir, "lead_time.md"), "w") as fo:
        fo.write(
            "# 수급위기 진단모델 Lead time(선행 예측) 성능표\n\n"
            "외부감사 B-2①② 대응. 시점 t의 피처로 t+h의 4단계를 예측(diagnosis_opt와 동일한 "
            "워크포워드 3폴드·Ridge 풀링+분위매핑, 타깃만 광종별 shift(-h)). 지평 h=0은 현행 "
            "나우캐스트와 정합. 주 환산: h=0→0주, 1→≈4주, 2→≈9주, 3→≈13주.\n\n"
            "**미래참조 차단**: 피처는 t 시점 관측치(당월 교사 y(t) 미포함, y_lag1=y(t-1)만) / "
            "타깃은 shift(-h)로 t+h / 학습 표본은 타깃 없는 꼬리 제외 / 단계 컷은 폴드 학습기간 "
            "분포에서만 산출.\n\n"
            "**지표 정의**: QWK=이차가중 카파. 전환월=t+h 단계가 예측시점 최신 관측단계와 달라진 "
            "달, P/R=그 전환 이벤트 탐지 정밀도·재현율. FAR(허위경보율)=실제<2인데 예측≥2 비율. "
            "Miss(미탐지율)=실제≥3(경계 이상)인데 예측<3 비율.\n\n"
            "**지속성 Naive 정의**: 예측시점 최신 관측단계 stage(t-1)로 t+h를 예측(모델이 아는 "
            "최신 교사도 y_lag1). h=0에서 diagnosis_opt의 shift(1) Naive와 일치. 지속성은 정의상 "
            "단계 변화를 예측하지 못하므로 전환 recall=0.\n\n"
            f"## 1) 모델 — 지평별 성능\n{mdf[show].to_markdown(index=False)}\n\n"
            f"## 2) 지속성 Naive 기준선 — 지평별 성능\n{ndf[show].to_markdown(index=False)}\n\n"
            f"## 3) 판정\n{verdict}\n\n"
            "지평별 QWK 대비:\n\n| h(개월) | 모델 QWK | Naive QWK | 우위 |\n|---|---|---|---|\n"
            + "".join(f"| {h} | {mq} | {nq} | {'○' if win else '×'} |\n"
                     for h, mq, nq, win in edge)
            + "\n> h=0(나우캐스트)에서 모델과 Naive의 QWK 격차가 진단 레이어의 순수 부가가치이며, "
              "지평이 길어질수록 격차가 좁혀지다 역전되는 지점이 '정책적으로 신뢰 가능한 최대 선행'이다.\n\n"
            "## 부록 A) 비용민감 경보 컷오프 스캔\n\n"
            "가정: 미탐:오탐 비용 = 5:1(**발주처 합의 필요** — 예시값). 사건=실제 단계≥3(경계 이상), "
            "경보=예측 단계≥thr. 비용 = 5×미탐건수 + 1×오탐건수. thr별 총비용과 최소비용 컷오프:\n\n"
            f"{cdf.to_markdown(index=False)}\n\n"
            "> 지평이 길수록 예측이 둔화(회귀 평활)되어, 동일 비용비에서 최적 경보 컷오프가 더 낮은 "
            "단계로 내려가는(민감도를 높이는) 경향이 나타나면 이는 '선행 예측일수록 더 이른/느슨한 "
            "경보가 비용최적'이라는 운영 함의를 준다. 비용비가 확정되면 h별 컷오프를 운영 규칙에 반영.\n"
        )
    print(f"\n저장: {out_dir}/lead_time.md")
    return dict(model=mdf, naive=ndf, verdict=verdict, cost=cdf, max_edge_h=max_edge_h)


if __name__ == "__main__":
    run()
