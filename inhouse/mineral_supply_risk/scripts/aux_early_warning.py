# -*- coding: utf-8 -*-
"""보조 조기경보(Δ분류 보팅) 운영 발행 (2026-07-25, 신챔피언 운영 반영 ②).

지금까지 '보조 조기경보 채택 동작점'은 백테스트 문서상으로만 존재했다(운영 미발행).
이 스크립트가 신챔피언 구성을 운영 발행한다:

  모델: 소프트보팅 = Bagging25(Logistic, 채택동작점 피처 — p_burst 포함)
                   + Bagging25(Logistic, 대체 피처 — p_burst→gsev_z13)
        양 멤버에 +OECD 한국 CLI 3피처(2026-07-26 R10 채택 — Logistic 프레임
        P=1.000·이웃 9/12 강건, 보팅 반영분은 3축 파레토(QWK 0.871→0.889·전환
        0.231→0.269·FAR 0.146→0.145)이나 보팅 부트스트랩 P=0.937 유의 미달 명기)
        ("보팅은 원천이 다를 때만" — NB2 확률 vs 원시 이벤트 누적 + 거시 사이클.
         r10_retune_report.md / broad_method_sweep.md)
  타깃: 주간 등급변화 Δ∈{-1,0,+1}(당주 라벨 vs 전주) — nowcast 성격의 보조 신호.
  발행: 검증은 워크포워드로 기완료 — 발행 모델은 전 기간 재적합(prob_model과 동일
        규약). 최신 관측주(패널 종점, 발주처 정답 가용 한계)의 5광종에 대해
        Δ예측·트리거·방향확률 발행 → out_aux_early_warning.

⚠ 운영 등급예측(out_diagnosis_alert, Ridge 지속성 중심)과 별개의 병기 신호 —
경보 등급을 바꾸지 않으며, 전환 가능성 주의를 촉구하는 보조 트리거다(hard 결합은
2차례 백테스트로 기각된 이력 — 피드백 메모리 참조).

실행: MSR_DB=<warehouse> python -m scripts.aux_early_warning
"""
from __future__ import annotations
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import BaggingClassifier
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH                                             # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics, pooled_design  # noqa: E402
from scripts.diagnosis_aux_features_eval import build_aux, INV_F           # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                       # noqa: E402
from scripts.diagnosis_priority_feeds_eval import build_pmi, PMI_F         # noqa: E402
from scripts.diag_refine1 import build_refined                             # noqa: E402
from scripts.r10_retune_harness import _z                                  # noqa: E402


CLI_F = ["cli_yoy", "cli_chg3", "cli_z24"]


def build_cli(db: str, panel) -> "pd.DataFrame":
    """OECD 한국 CLI(월간, avail=+45일) — R10 채택 피처."""
    from scripts.diagnosis_aux_features_eval import _asof_join
    from db.dbio import connect_ro
    con = connect_ro(db)
    x = con.execute("""SELECT CAST(obs_date AS DATE) obs_date,
        CAST(val AS DOUBLE PRECISION) val FROM fact_series
        WHERE series_code='OECD_CLI_KR_M' ORDER BY 1""").df()
    con.close()
    x["obs_date"] = pd.to_datetime(x["obs_date"])
    x["cli_yoy"] = x["val"].pct_change(12)
    x["cli_chg3"] = x["val"].pct_change(3)
    x["cli_z24"] = _z(x["val"])
    x["avail_date"] = x["obs_date"] + pd.Timedelta(days=45)
    return _asof_join(panel, x.replace([np.inf, -np.inf], np.nan), CLI_F,
                      by_commodity=False)

MODEL_VERSION = ("aux_early_warning_v2(소프트보팅 Bagging25×2+OECD한국CLI — "
                 "워크포워드 QWK 0.889/전환 0.269/FAR 0.145, 2026-07-26 R10 채택)")
GRADE_KO = {-1: "하향", 0: "유지", 1: "상향"}


def main() -> None:
    db = os.environ.get("MSR_DB", DB_PATH)
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_pmi(db, df)
    df = build_refined(db, df)
    df = build_cli(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    nolag_sub = [("gsev_z13" if f == "p_burst" else f) for f in nolag]
    feats_a = nolag + INV_F + exch.CNINV_F + PMI_F + CLI_F
    feats_b = nolag_sub + INV_F + exch.CNINV_F + PMI_F + CLI_F

    last = df["obs_date"].max()
    tr = df.copy()                                     # 발행: 전 기간 재적합
    te = df[df["obs_date"] == last].copy()
    print(f"[aux-ew] 패널 {len(df)}행, 발행 기준주 {pd.Timestamp(last).date()} "
          f"({len(te)}광종)")
    dtr = np.clip(tr["grade_ord"].values - tr["grade_lag1"].round().values,
                  -1, 1).astype(int)
    probs = []
    classes = None
    for feats in (feats_a, feats_b):
        Xtr, Xte = pooled_design(tr, te, feats)
        m = BaggingClassifier(
            LogisticRegression(max_iter=2000, class_weight="balanced"),
            n_estimators=25, random_state=0, n_jobs=-1)
        m.fit(Xtr, dtr)
        probs.append(m.predict_proba(Xte))
        classes = list(m.classes_)
    P = np.mean(probs, axis=0)
    dhat = np.array(classes)[P.argmax(axis=1)].astype(int)

    def pcol(cls):
        return P[:, classes.index(cls)] if cls in classes else np.zeros(len(te))

    out = pd.DataFrame({
        "commodity_code": te["commodity_code"].values,
        "obs_date": pd.Timestamp(last).date(),
        "delta_pred": dhat,
        "direction": [GRADE_KO[int(v)] for v in dhat],
        "trigger": (dhat != 0),
        "p_down": np.round(pcol(-1), 4),
        "p_stay": np.round(pcol(0), 4),
        "p_up": np.round(pcol(1), 4),
        "model_version": MODEL_VERSION,
        "basis": json.dumps({
            "frame": "Δ분류(당주 등급 vs 전주) 소프트보팅, 전 기간 재적합 발행",
            "validation": "워크포워드 3폴드(보팅+CLI) QWK 0.889·전환 0.269·FAR 0.145. "
                          "CLI 채택 근거: Logistic 프레임 P=1.000·이웃 9/12 강건 "
                          "(보팅 프레임 반영분은 3축 파레토, P=0.937 유의 미달 명기)",
            "note": "운영 등급예측과 별개의 병기 보조신호 — 경보 등급 불변경"},
            ensure_ascii=False),
        "generated_at": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
    })
    # 2026-08-19(postgres cutover): duckdb 전용 register/CHECKPOINT 대신 dbio.upsert_df
    # (duckdb/postgres 자동 분기)로 obs_date 1일치 upsert.
    from db.dbio import upsert_df
    upsert_df(out, "out_aux_early_warning", db,
              del_where=f"obs_date = '{out['obs_date'].iloc[0]}'")
    print(out[["commodity_code", "obs_date", "direction", "trigger",
               "p_down", "p_stay", "p_up"]].to_string(index=False))
    print(f"[aux-ew] out_aux_early_warning {len(out)}행 발행 완료")


if __name__ == "__main__":
    main()
