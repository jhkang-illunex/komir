# -*- coding: utf-8 -*-
"""신규 거래소 재고(NI SHFE·LI GFEX) 전환탐지 검증 (2026-07-24, CO 정찰 후속).

collect_exchange_inventory.py 적재분을 diagnosis_aux_features_eval과 동일 프레임에
투입해, CU·NI(LME 재고)에서 확인된 "재고→전환탐지 개선"이 신규 소스에서 재현되는지
검정한다.

피처(공용 컬럼 — NI·LI 모두 "중국 내 거래소 실물 재고"라는 같은 의미축):
  cninv_z52 · cninv_chg4 · cninv_chg13  (NI←SHFE_99QH_W, LI←GFEX_OFFICIAL_W)
가용시점: 두 소스 모두 금요일 스냅샷을 당일 공개 → 다음 월요일(obs_date)에 사용
가능하므로 avail = 기준일 + 3일(주간평균 계열의 +7일보다 짧은 것이 정당).

검정축:
  (a) NI만: NOLAG / +LME재고(INV) / +SHFE(cninv) / +둘다 — SHFE가 LME 너머 추가
      신호를 주는가
  (b) LI만: NOLAG / +GFEX(cninv) — ⚠ 사전 명시: GFEX는 2023-07 상장이라 학습
      커버리지가 얇고 LI 전환주는 테스트 전 기간 2건뿐 → 통계 판정 불가, 방향 참고만
  (c) 5광종 풀링: 기존 최적(NOLAG+INV)에 cninv 추가 시 변화

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_exch_inventory_eval
산출: outputs/model_opt/diagnosis_exch_inventory_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics                # noqa: E402
from scripts.diagnosis_aux_features_eval import (                          # noqa: E402
    build_aux, INV_F, _asof_join, e2_delta_classifier,
)

CNINV_F = ["cninv_z52", "cninv_chg4", "cninv_chg13"]
SRC_MAP = {"NI": {"SHFE_99QH_W"}, "LI": {"GFEX_OFFICIAL_W", "GFEX_EM_MIRROR_W"}}


def build_cninv(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    inv = con.execute("""SELECT commodity_code, CAST(obs_date AS DATE) AS obs_date, val, src
        FROM fact_inventory_exch
        WHERE src IN ('SHFE_99QH_W','GFEX_OFFICIAL_W','GFEX_EM_MIRROR_W')
        ORDER BY commodity_code, obs_date""").df()
    con.close()
    inv["obs_date"] = pd.to_datetime(inv["obs_date"]).astype("datetime64[ns]")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")

    inv = inv[[s in SRC_MAP.get(cc, set()) for cc, s in zip(inv["commodity_code"], inv["src"])]]
    inv = inv.drop_duplicates(subset=["commodity_code", "obs_date"], keep="first")
    inv = inv.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    # 시계열 공백(LI: GFEX 레이트리밋으로 2024-12~2026-03 미수집) 경계를 넘는 롤링 계산
    # 금지 — 3주 초과 공백마다 세그먼트를 끊고 세그먼트 내부에서만 롤링/변화율 계산
    inv["_seg"] = inv.groupby("commodity_code")["obs_date"] \
        .transform(lambda s: (s.diff() > pd.Timedelta(days=21)).cumsum())
    g = inv.groupby(["commodity_code", "_seg"])["val"]
    inv["cninv_z52"] = g.transform(
        lambda s: (s - s.rolling(52, min_periods=20).mean())
        / s.rolling(52, min_periods=20).std().replace(0, np.nan))
    inv["cninv_chg4"] = g.transform(lambda s: s.pct_change(4))
    inv["cninv_chg13"] = g.transform(lambda s: s.pct_change(13))
    # 재고 0 기저의 pct_change → ±inf 방지(GFEX 상장 초기 창단량 0 실측)
    inv[CNINV_F] = inv[CNINV_F].replace([np.inf, -np.inf], np.nan)
    inv["avail_date"] = inv["obs_date"] + pd.Timedelta(days=3)
    # 신선도 마스크용 — 조인된 값이 실제 언제 관측치인지 함께 부착
    inv["cninv_srcdate"] = inv["obs_date"]
    out = _asof_join(panel, inv, CNINV_F + ["cninv_srcdate"], by_commodity=True)
    # 공백 구간에서 backward as-of가 끌어온 낡은 값(>14일) 제거 — LI 공백기 오염 방지
    stale = (out["obs_date"] - out["cninv_srcdate"]) > pd.Timedelta(days=14)
    out.loc[stale.fillna(True), CNINV_F] = np.nan
    return out.drop(columns=["cninv_srcdate"])


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    df = add_dynamics(df)
    df = build_aux(db, df)      # 기존 LME 재고(INV_F)·거시 피처
    df = build_cninv(db, df)    # 신규 SHFE·GFEX
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    for cc in ["NI", "LI"]:
        sub = df[df["commodity_code"] == cc]
        print(f"{cc} cninv 커버리지: {float(sub['cninv_z52'].notna().mean()):.2f} "
              f"({sub.loc[sub['cninv_z52'].notna(), 'obs_date'].min()}~)")

    results = []
    # (a) NI만
    df_ni = df[df["commodity_code"] == "NI"].reset_index(drop=True)
    for tag, feats in [("NOLAG", nolag), ("NOLAG+LME재고", nolag + INV_F),
                        ("NOLAG+SHFE재고", nolag + CNINV_F),
                        ("NOLAG+LME+SHFE", nolag + INV_F + CNINV_F)]:
        r = e2_delta_classifier(df_ni, feats, "Logistic")
        results.append(dict(축="NI만", 구성=tag, **r))

    # (b) LI만 — 방향 참고 전용(전환주 2건)
    df_li = df[df["commodity_code"] == "LI"].reset_index(drop=True)
    for tag, feats in [("NOLAG", nolag), ("NOLAG+GFEX재고", nolag + CNINV_F)]:
        r = e2_delta_classifier(df_li, feats, "Logistic")
        results.append(dict(축="LI만(참고, n_chg=2)", 구성=tag, **r))

    # (c) 5광종 풀링
    for tag, feats in [("NOLAG+LME재고(기존 최적)", nolag + INV_F),
                        ("NOLAG+LME+CN재고", nolag + INV_F + CNINV_F)]:
        r = e2_delta_classifier(df, feats, "Logistic")
        results.append(dict(축="풀링", 구성=tag, **r))

    tab = pd.DataFrame(results)
    print(tab.round(4).to_string(index=False))
    write_report(tab)
    return tab


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def write_report(tab: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_exch_inventory_eval.md")
    L = []
    L.append("# 신규 거래소 재고(NI SHFE·LI GFEX) 전환탐지 검증\n")
    L.append("작성: 2026-07-24 · collect_exchange_inventory.py 적재분 검정. 프레임·평가는 "
             "diagnosis_aux_features_eval과 동일(E2 Δ타깃 Logistic, 워크포워드 3폴드 풀링, "
             "as-of 가용시점 +3일). CO는 무료 수집 경로 부재로 미포함"
             "(co_inventory_recon.md 참조).\n")
    L.append("\n| 축 | 구성 | QWK | acc | chg_acc | up_acc | n_chg | FAR |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['축']} | {r['구성']} | {_fmt(r['QWK'])} | {_fmt(r['acc'])} | "
                 f"{_fmt(r['chg_acc'])} | {_fmt(r['up_acc'])} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'])} |")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[exch_inventory_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
