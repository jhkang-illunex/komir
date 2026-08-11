# -*- coding: utf-8 -*-
"""y_lag1(전월 교사값) 발행지연 가정 민감도 — 2026-08-10 사용자 지시.

배경: 진단 챔피언(Ridge 풀링+분위매핑)의 워크포워드 QWK는 y_lag1(전월 교사=수급동향지표)
에 절대적으로 의존한다(outputs/model_opt/report.md 피처제거민감도: y_lag1 dQWK 0.765,
2위 price_z52는 0.069). 그런데 mart_weekly_diagnosis의 교사 조인(weekly_mart.py:61-62)은
avail_date 없이 자기 참조월로만 조인돼 "발표 즉시 안다"고 가정한다 — 실제 KOMIS 발행지연이
1개월보다 길면 y_lag1은 운영 시점엔 아직 모르는 값을 안다고 가정하는 셈이라 QWK가 낙관적으로
부풀려질 수 있다. 정확한 지연일수는 KOMIS 확인 전엔 알 수 없음(로컬 문서엔 "갱신주기=월간"만
있고 몇일 지연인지는 없음) — 이 스크립트는 그 확인 전에 "지연이 실제로 2개월·3개월이라면
성능이 얼마나 빠지는가"를 먼저 정량화해 두는 민감도 체크다. 결론이 채택/기각을 뜻하지 않음
— 순수 진단.

방법: diagnosis_opt.py와 동일한 워크포워드 3폴드(FOLDS)·동일 챔피언(Ridge 풀링+분위매핑)
구성에서 y_lag1 자리만 y_lag2(2개월 전)·y_lag3(3개월 전)으로 교체해 재평가. 비교 기준선으로
Naive(전월단계 유지)도 동일하게 지연을 늘린 버전(N개월 전 단계 유지)을 같이 낸다 — y_lagN
챔피언이 NaiveN보다 얼마나 더 나은지가 "그 지연 가정에서도 모델이 여전히 가치 있는지"를 보여줌.

실행: MSR_DB=<warehouse> python -m scripts.ylag_publication_delay_sensitivity
산출: outputs/model_opt/ylag_publication_delay_sensitivity.md
"""
from __future__ import annotations
import os, sys

import pandas as pd
from sklearn.metrics import cohen_kappa_score, f1_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                          # noqa: E402
from msr.models.diagnosis_opt import (                                       # noqa: E402
    build_panel, BASE_FEATS, FOLDS, Q_CUT, stage_labels, _fit_predict_reg,
    reg_to_stage, rps,
)

LAGS = (1, 2, 3)


def _add_lags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["commodity_code", "month"]).reset_index(drop=True)
    g = df.groupby("commodity_code")["y"]
    for n in LAGS:
        df[f"y_lag{n}"] = g.shift(n)
    return df


def _feats_for_lag(df: pd.DataFrame, n: int) -> list[str]:
    feats = BASE_FEATS + ["geo_chg", "p_burst", "price_z52", f"y_lag{n}"]
    return [f for f in feats if df[f].notna().sum() > 50 and df[f].nunique() > 2]


def _walkforward(df: pd.DataFrame, feats: list[str], naive_lag: int) -> list[dict]:
    """champion(Ridge 풀링+매핑) vs NaiveN(N개월 전 단계 유지) — FOLDS 워크포워드."""
    rows = []
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        yte_s = y_stage[te.index].values
        stage_series = pd.Series(y_stage.values, index=df.index)
        stage_prev = stage_series.groupby(df["commodity_code"]).shift(1)[te.index]
        chg_mask = stage_prev.notna() & (stage_prev.values != yte_s)

        # champion: Ridge(풀링)+분위매핑, 피처세트만 지연별로 교체
        pred_y, _ = _fit_predict_reg("Ridge", tr, te, feats, per_commodity=False)
        pred = reg_to_stage(pred_y, te, tr)
        chg_acc = float((pred[chg_mask.values] == yte_s[chg_mask.values]).mean()) \
            if chg_mask.sum() else float("nan")
        rows.append(dict(fold=t0[:4], model=f"Ridge(풀링)+y_lag{naive_lag}",
                         QWK=round(cohen_kappa_score(yte_s, pred, weights="quadratic"), 3),
                         macroF1=round(f1_score(yte_s, pred, average="macro"), 3),
                         RPS=round(rps(yte_s, pred), 4),
                         acc=round(float((yte_s == pred).mean()), 3),
                         chg_acc=round(chg_acc, 3) if chg_mask.sum() else None,
                         n_chg=int(chg_mask.sum())))

        # NaiveN: N개월 전 단계를 그대로 이번달 예측으로(지연이 N개월이면 이게 진짜 기준선)
        pred_n = stage_series.groupby(df["commodity_code"]).shift(naive_lag)[te.index] \
            .fillna(0).astype(int).values
        chg_acc_n = float((pred_n[chg_mask.values] == yte_s[chg_mask.values]).mean()) \
            if chg_mask.sum() else float("nan")
        rows.append(dict(fold=t0[:4], model=f"Naive{naive_lag}(N개월전 단계유지)",
                         QWK=round(cohen_kappa_score(yte_s, pred_n, weights="quadratic"), 3),
                         macroF1=round(f1_score(yte_s, pred_n, average="macro"), 3),
                         RPS=round(rps(yte_s, pred_n), 4),
                         acc=round(float((yte_s == pred_n).mean()), 3),
                         chg_acc=round(chg_acc_n, 3) if chg_mask.sum() else None,
                         n_chg=int(chg_mask.sum())))
    return rows


def run(db=None, out_dir=None):
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)

    df = _add_lags(build_panel(db))
    all_rows = []
    for n in LAGS:
        feats = _feats_for_lag(df, n)
        print(f"[lag={n}] 피처: {feats}")
        all_rows += _walkforward(df, feats, n)

    res = pd.DataFrame(all_rows)
    agg = (res.groupby("model")[["QWK", "macroF1", "RPS", "acc", "chg_acc"]]
              .mean().round(3))
    order = [s for n in LAGS
             for s in (f"Ridge(풀링)+y_lag{n}", f"Naive{n}(N개월전 단계유지)")]
    agg = agg.reindex(order)
    print("\n=== 지연가정별 워크포워드 평균(3폴드) ===")
    print(agg.to_string())

    res.to_csv(f"{out_dir}/ylag_publication_delay_sensitivity_folds.csv", index=False)
    with open(f"{out_dir}/ylag_publication_delay_sensitivity.md", "w") as fo:
        fo.write(
            "# y_lag 발행지연 가정 민감도\n\n"
            "실제 KOMIS 수급동향지표 발행지연을 확인하기 전, '지연이 1/2/3개월이라면 챔피언 "
            "QWK가 얼마나 빠지는지'를 먼저 정량화한 진단(채택/기각 실험 아님).\n\n"
            f"{agg.to_markdown()}\n\n## 폴드별 상세\n{res.to_markdown(index=False)}\n"
        )
    print(f"저장: {out_dir}/ylag_publication_delay_sensitivity.md")
    return agg


if __name__ == "__main__":
    run()
