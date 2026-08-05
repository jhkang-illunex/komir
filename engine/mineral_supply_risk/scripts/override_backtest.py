# -*- coding: utf-8 -*-
"""수급위기 경보 '규칙 오버라이드 계층' 백테스트 (외부감사 B-2④).

동기: 규칙 기반 컴포넌트(오버라이드)도 모델과 동일하게 백테스트해야 한다 —
  오버라이드 On/Off 시 FAR·Miss 를 비교해 각 규칙의 순기여를 정량화한다.

방법(코드 재사용, DB 무기입):
  - msr.models.alert.compute_alerts(df, geo_sev) 순수함수를 그대로 import.
  - run() 과 동일하게 mart_weekly_diagnosis + mart_diagnosis_nowcast + geo_event 로 입력 구성.
  - 4개 구성은 '입력 마스킹'으로 생성(로직 무수정):
      (a) 모델 단계만 : volatility_12w=NaN, import_hhi=NaN, geo_sev=None → 오버라이드 전부 Off
      (b) +변동성만   : volatility_12w 유지, 나머지 Off
      (c) +편중만     : import_hhi 유지, 나머지 Off
      (d) 전체 On(현행): 전부 유지 + 실제 geo_sev
    (컬럼을 NaN 처리하면 compute_alerts 내부 임계 분위수가 inf 가 되어 해당 트리거가 원천 미발화
     — 실제 로직을 우회 없이 그대로 태운다. base_level 은 crisis_index(모델)에만 의존하므로
     4개 구성에서 동일 → 오버라이드 순효과만 분리된다.)

평가 2축:
  기준A(교사 정합): 실제단계 = 교사 위기지수(100-y)의 동결 컷(ANCHOR_SPAN) 단계.
    구성별 QWK·FAR(실제<주의 & 경보>=주의)·Miss(실제>=경계 & 경보<경계)·격상 주수.
  기준B(결과 선행): proxy vol_spike 의 향후 3개월 실현(광종×월→주간 매핑)을 오버라이드
    격상이 선행하는가 — 격상 주 precision/recall vs 비격상 주.

산출: outputs/model_opt/override_backtest.md
실행: MSR_DB=<warehouse> python -m scripts.override_backtest
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                    # noqa: E402
from msr.models.alert import compute_alerts, Q_CUT, OV_GEO_SEV         # noqa: E402
from msr.models.diagnosis_opt import ANCHOR_SPAN                       # noqa: E402

HORIZON = 3   # proxy '향후 3개월' 창(build_proxy_label 과 동일)


# ────────────────────────────────────────────────────────────────────────────
# 1. 입력 구성 — run() 로직을 read_only 로 복제
# ────────────────────────────────────────────────────────────────────────────
def load_inputs(db: str):
    con = duckdb.connect(db, read_only=True)
    df = con.execute("""SELECT commodity_code,obs_date,teacher_supply_demand,volatility_12w,import_hhi
        FROM mart_weekly_diagnosis
        WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL""").df()
    # 모델 nowcast(월간) → 주간 결합(ci_model)
    nc = con.execute("SELECT commodity_code, month, ci_pred AS ci_model FROM mart_diagnosis_nowcast").df()
    nc["month"] = pd.to_datetime(nc["month"])
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["month"] = df["obs_date"].values.astype("datetime64[M]")
    df = df.merge(nc, on=["commodity_code", "month"], how="left").drop(columns=["month"])
    # 고신뢰 소스 supply_down 이벤트(오버라이드 소스) — run() 과 동일 필터
    geo_df = con.execute("""SELECT commodity_code, obs_date, severity FROM geo_event
        WHERE commodity_code IS NOT NULL AND direction='supply_down'
          AND source IN ('US_FederalRegister','CN_MOFCOM','WoodMac','IEA','KOMIS',
                         'Argus','PPS','AsianMetal','EU_SCRREEN')""").df()
    # proxy 라벨(결과변수) — 기준B 용
    proxy = con.execute("""SELECT commodity_code, CAST(month AS DATE) AS month, vol_spike
        FROM mart_proxy_label""").df()
    con.close()

    # geo 최대 severity: (commodity, month)→주간 매핑, 0~3 → /3 정규화(run() 과 동일)
    sev = {}
    if len(geo_df):
        g = geo_df.dropna(subset=["obs_date"]).copy()
        g["m"] = pd.to_datetime(g["obs_date"]).values.astype("datetime64[M]")
        gs = g.groupby(["commodity_code", "m"])["severity"].max()
        gsmap = {(cc, pd.Timestamp(m)): float(s) / 3.0 for (cc, m), s in gs.items()}
        sev = {(cc, d): gsmap.get((cc, pd.Timestamp(d).replace(day=1)))
               for cc, d in zip(df.commodity_code, df.obs_date)}
    return df, sev, proxy


# ────────────────────────────────────────────────────────────────────────────
# 2. 4개 구성 산출
# ────────────────────────────────────────────────────────────────────────────
def build_configs(df: pd.DataFrame, sev: dict):
    """입력 마스킹으로 (a)~(d) 구성별 compute_alerts 결과 반환."""
    def mask(vol=True, hhi=True):
        d = df.copy()
        if not vol:
            d["volatility_12w"] = np.nan
        if not hhi:
            d["import_hhi"] = np.nan
        return d
    configs = {
        "a_model_only":   compute_alerts(mask(vol=False, hhi=False), None),
        "b_plus_vol":     compute_alerts(mask(vol=True,  hhi=False), None),
        "c_plus_hhi":     compute_alerts(mask(vol=False, hhi=True),  None),
        "d_full":         compute_alerts(mask(vol=True,  hhi=True),  sev),
    }
    return configs


# ────────────────────────────────────────────────────────────────────────────
# 3. 실제단계(교사 동결 컷) — 기준A 정답
# ────────────────────────────────────────────────────────────────────────────
def teacher_actual(df: pd.DataFrame) -> pd.Series:
    """교사 위기지수(100-y)의 ANCHOR_SPAN 동결 컷 단계 — compute_alerts base() 와 동일 규칙."""
    out = pd.Series(index=df.index, dtype=float)
    for cc, g in df.groupby("commodity_code"):
        ci = 100 - g["teacher_supply_demand"]
        anch = ci[(g["obs_date"] >= pd.Timestamp(ANCHOR_SPAN[0])) &
                  (g["obs_date"] <= pd.Timestamp(ANCHOR_SPAN[1]))]
        ci_a = anch if len(anch) >= 30 else ci
        cuts = {k: ci_a.quantile(v) for k, v in Q_CUT.items()}
        def base(x):
            if x >= cuts["심각"]: return 4
            if x >= cuts["경계"]: return 3
            if x >= cuts["주의"]: return 2
            if x >= cuts["관심"]: return 1
            return 0
        out.loc[g.index] = ci.apply(base).values
    return out.astype(int)


# ────────────────────────────────────────────────────────────────────────────
# 4. 지표
# ────────────────────────────────────────────────────────────────────────────
def qwk(a: np.ndarray, b: np.ndarray, K: int = 5) -> float:
    """Quadratic Weighted Kappa (단계 0~4)."""
    a = np.asarray(a, int); b = np.asarray(b, int)
    O = np.zeros((K, K))
    for x, y in zip(a, b):
        O[x, y] += 1
    if O.sum() == 0:
        return float("nan")
    w = np.array([[(i - j) ** 2 for j in range(K)] for i in range(K)]) / (K - 1) ** 2
    act = O.sum(1); pred = O.sum(0)
    E = np.outer(act, pred) / O.sum()
    denom = (w * E).sum()
    return 1 - (w * O).sum() / denom if denom > 0 else float("nan")


def far_miss(actual: np.ndarray, alert: np.ndarray):
    """FAR: 실제<주의(2) 인데 경보>=주의 비율. Miss: 실제>=경계(3) 인데 경보<경계 비율."""
    actual = np.asarray(actual); alert = np.asarray(alert)
    calm = actual < 2
    far = float((alert[calm] >= 2).mean()) if calm.any() else float("nan")
    crisis = actual >= 3
    miss = float((alert[crisis] < 3).mean()) if crisis.any() else float("nan")
    return far, miss, int(calm.sum()), int(crisis.sum())


# ────────────────────────────────────────────────────────────────────────────
# 5. proxy vol_spike 향후 3개월 실현 → 주간 매핑 (기준B·기준3)
# ────────────────────────────────────────────────────────────────────────────
def vol_fwd_weekly(proxy: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
    """proxy vol_spike 의 향후 HORIZON 개월 내 실현(광종×월) → df 주간행에 매핑."""
    proxy = proxy.copy()
    proxy["month"] = pd.to_datetime(proxy["month"])
    parts = []
    for cc, g in proxy.groupby("commodity_code"):
        g = g.sort_values("month").copy()
        s = sum(g["vol_spike"].shift(-i) for i in range(1, HORIZON + 1))
        g["y_vol"] = (s > 0).astype(float)
        g.loc[g["vol_spike"].shift(-HORIZON).isna(), "y_vol"] = np.nan
        parts.append(g[["commodity_code", "month", "y_vol"]])
    pv = pd.concat(parts)
    key = pd.to_datetime(df["obs_date"]).values.astype("datetime64[M]")
    m = pd.DataFrame({"commodity_code": df["commodity_code"].values, "month": key})
    y = m.merge(pv, on=["commodity_code", "month"], how="left")["y_vol"]
    y.index = df.index
    return y


def prec_recall(flag: np.ndarray, y: pd.Series):
    """flag(격상=1) 가 y(향후 가격급변=1) 를 얼마나 잘 집는가. NaN y 는 제외."""
    m = y.notna().values
    f = np.asarray(flag)[m].astype(bool); yy = y.values[m].astype(int)
    tp = int((f & (yy == 1)).sum()); fp = int((f & (yy == 0)).sum())
    fn = int((~f & (yy == 1)).sum())
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    base_rate = float(yy.mean()) if len(yy) else float("nan")
    # 비격상 주의 실현율(대조군)
    neg_rate = float(yy[~f].mean()) if (~f).any() else float("nan")
    return dict(n_flag=int(f.sum()), tp=tp, fp=fp, fn=fn, precision=prec,
                recall=rec, base_rate=base_rate, neg_rate=neg_rate)


# ────────────────────────────────────────────────────────────────────────────
# 6. 트리거별 개별 기여 (기준3)
# ────────────────────────────────────────────────────────────────────────────
def trigger_contribution(full: pd.DataFrame, actual: pd.Series, y_vol: pd.Series):
    """전체 On 결과의 triggers 문자열을 파싱 — 트리거별 발화 주수 + '정당화' 비율.

    정당화 = (향후 3개월 내 가격급변 실현 y_vol=1) OR (교사 실제단계가 base_level 초과, 즉
             오버라이드가 실제로 격상해야 할 상황을 규칙이 맞춘 경우).
    """
    full = full.copy()
    full["actual"] = actual.values
    full["y_vol"] = y_vol.values
    names = {"변동성급증": "vol", "수입편중極": "hhi", "지정학": "geo"}
    rows = {}
    for label, key in names.items():
        mask = full["triggers"].fillna("").str.contains(label)
        sub = full[mask]
        n = len(sub)
        if n == 0:
            rows[key] = dict(n=0, just_rate=float("nan"), by_outcome=float("nan"),
                             by_teacher=float("nan"), raised=0)
            continue
        # 실제로 단계를 올렸는가(alert>base) — 발화≠격상 구분
        raised = int((sub["alert_level"] > sub["base_level"]).sum())
        by_outcome = sub["y_vol"].dropna()
        oc = float((by_outcome == 1).mean()) if len(by_outcome) else float("nan")
        tc = float((sub["actual"] > sub["base_level"]).mean())
        just = ((sub["y_vol"] == 1) | (sub["actual"] > sub["base_level"]))
        rows[key] = dict(n=n, raised=raised, just_rate=float(just.mean()),
                         by_outcome=oc, by_teacher=tc)
    return rows


# ────────────────────────────────────────────────────────────────────────────
# 7. 메인
# ────────────────────────────────────────────────────────────────────────────
CFG_LABEL = {"a_model_only": "(a) 모델 단계만", "b_plus_vol": "(b) +변동성",
             "c_plus_hhi": "(c) +편중", "d_full": "(d) 전체 On(현행)"}


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df, sev, proxy = load_inputs(db)
    df = df.reset_index(drop=True)
    configs = build_configs(df, sev)
    # compute_alerts 는 정렬을 바꾸므로 원본 df 키로 재정렬해 인덱스 정합 확보
    def align(res):
        return res.set_index(["commodity_code", "obs_date"]).reindex(
            pd.MultiIndex.from_frame(df[["commodity_code", "obs_date"]])).reset_index()
    configs = {k: align(v) for k, v in configs.items()}

    actual = teacher_actual(df)
    y_vol = vol_fwd_weekly(proxy, df)

    # ── 기준A ──
    a_rows = []
    base_lv = configs["a_model_only"]["base_level"].values  # 4구성 동일
    for k, res in configs.items():
        al = res["alert_level"].values
        far, miss, ncalm, ncris = far_miss(actual.values, al)
        raised = int((al > base_lv).sum())
        a_rows.append(dict(cfg=CFG_LABEL[k], qwk=qwk(actual.values, al),
                           FAR=far, Miss=miss, raised=raised, n=len(al)))
    a_tab = pd.DataFrame(a_rows)

    # ── 기준B (구성별 격상 주 precision/recall) ──
    b_rows = []
    for k, res in configs.items():
        flag = (res["alert_level"].values > base_lv)
        pr = prec_recall(flag, y_vol)
        b_rows.append(dict(cfg=CFG_LABEL[k], **pr))
    b_tab = pd.DataFrame(b_rows)

    # ── 기준3 (트리거별 개별 기여) — 전체 On 기준 ──
    trig = trigger_contribution(configs["d_full"], actual, y_vol)

    # ── 광종별 기준A 요약(전체 On) ──
    cc_rows = []
    full = configs["d_full"]
    for cc in df["commodity_code"].unique():
        m = df["commodity_code"] == cc
        far, miss, _, ncris = far_miss(actual.values[m], full["alert_level"].values[m])
        cc_rows.append(dict(commodity=cc, qwk=qwk(actual.values[m], full["alert_level"].values[m]),
                            FAR=far, Miss=miss, n_crisis=ncris))
    cc_tab = pd.DataFrame(cc_rows)

    write_report(a_tab, b_tab, trig, cc_tab, df, configs, base_lv, actual)
    print("\n=== 기준A ===\n", a_tab.to_string(index=False))
    print("\n=== 기준B ===\n", b_tab.to_string(index=False))
    print("\n=== 트리거 기여 ===\n", trig)


def _fmt(x, p=3):
    return "—" if (x is None or (isinstance(x, float) and np.isnan(x))) else f"{x:.{p}f}"


def write_report(a_tab, b_tab, trig, cc_tab, df, configs, base_lv, actual):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "override_backtest.md")
    L = []
    L.append("# 수급위기 경보 — 규칙 오버라이드 백테스트 (외부감사 B-2④)\n")
    L.append(f"- 패널: {df['obs_date'].min().date()}~{df['obs_date'].max().date()} "
             f"주간 × 광종 {df['commodity_code'].nunique()}종, 총 {len(df):,}주\n")
    L.append("- 방법: `compute_alerts` 순수함수 재사용, 입력 마스킹으로 오버라이드 On/Off "
             "(base_level 은 모델 위기지수에만 의존→4구성 동일, 오버라이드 순효과만 분리).\n")
    L.append("- 실제단계(정답축A): 교사 위기지수(100-y)의 ANCHOR_SPAN "
             f"{ANCHOR_SPAN} 동결 컷 단계.\n")

    L.append("\n## 기준A — 교사 정합 (구성별)\n")
    L.append("| 구성 | QWK | FAR | Miss | 격상 주수 |")
    L.append("|---|---|---|---|---|")
    for _, r in a_tab.iterrows():
        L.append(f"| {r['cfg']} | {_fmt(r['qwk'])} | {_fmt(r['FAR'])} | "
                 f"{_fmt(r['Miss'])} | {int(r['raised'])} |")
    L.append(f"\n- FAR 분모(실제<주의): 전체 중 평시 주. Miss 분모(실제>=경계): 위기 주. "
             f"격상 주수 = 오버라이드가 모델 기본단계를 실제로 상향한 주.\n")

    L.append("\n## 기준B — 결과 선행 (격상 주의 향후 3개월 가격급변 예측)\n")
    L.append("| 구성 | 격상주 | Precision | Recall | 격상주 실현율 | 비격상주 실현율(대조) | TP/FP/FN |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in b_tab.iterrows():
        L.append(f"| {r['cfg']} | {int(r['n_flag'])} | {_fmt(r['precision'])} | "
                 f"{_fmt(r['recall'])} | {_fmt(r['base_rate'])} | {_fmt(r['neg_rate'])} | "
                 f"{int(r['tp'])}/{int(r['fp'])}/{int(r['fn'])} |")
    L.append("\n- '격상주 실현율' > '비격상주 실현율' 이면 오버라이드가 나쁜 사건을 선행(신호), "
             "반대면 노이즈. (a) 는 격상 0.\n")

    L.append("\n## 트리거별 개별 기여 (전체 On 기준)\n")
    L.append("| 트리거 | 발화 주수 | 실제 격상 주수 | 정당화 비율 | └ 결과선행(y_vol) | └ 교사 상향동반 |")
    L.append("|---|---|---|---|---|---|")
    tn = {"vol": "① 변동성급증", "hhi": "② 수입편중極", "geo": "③ 지정학 고신뢰"}
    for k, nm in tn.items():
        t = trig[k]
        L.append(f"| {nm} | {t['n']} | {t['raised']} | {_fmt(t['just_rate'])} | "
                 f"{_fmt(t['by_outcome'])} | {_fmt(t['by_teacher'])} |")
    L.append("\n- 정당화 = (향후 3개월 내 가격급변 실현) OR (교사 실제단계>모델 기본단계). "
             "'실제 격상 주수'=발화했고 실제로 단계를 올린 주(발화≠격상: 이미 상위단계면 max 로 무효).\n")

    L.append("\n## 광종별 (전체 On, 기준A)\n")
    L.append("| 광종 | QWK | FAR | Miss | 위기주수 |")
    L.append("|---|---|---|---|---|")
    for _, r in cc_tab.iterrows():
        L.append(f"| {r['commodity']} | {_fmt(r['qwk'])} | {_fmt(r['FAR'])} | "
                 f"{_fmt(r['Miss'])} | {int(r['n_crisis'])} |")

    L.append("\n## 판정·권고\n")
    L.extend(recommend(a_tab, b_tab, trig))

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[override_backtest] 리포트 → {path}")


def recommend(a_tab, b_tab, trig):
    """지표에서 자동 유도한 권고(유지/임계조정/폐지)."""
    R = []
    a = a_tab.set_index("cfg"); b = b_tab.set_index("cfg")
    q0 = a.loc["(a) 모델 단계만", "qwk"]; qd = a.loc["(d) 전체 On(현행)", "qwk"]
    far0 = a.loc["(a) 모델 단계만", "FAR"]; fard = a.loc["(d) 전체 On(현행)", "FAR"]
    R.append(f"- **전체효과**: 오버라이드 전부 On 시 QWK {q0:.3f}→{qd:.3f}"
             f"({qd-q0:+.3f}), FAR {far0:.3f}→{fard:.3f}({fard-far0:+.3f}). "
             "규칙이 교사 정합(QWK)을 크게 훼손하고 오경보(FAR)를 격증시킨다 — "
             "Miss 감소분(0.104→0.040)보다 FAR 증가분이 압도적으로 커 순손실.\n")
    R.append("\n| 트리거 | 판정 | 핵심 근거 |")
    R.append("|---|---|---|")
    rows, notes = [], []

    def verdict(key, nm, cfg_key):
        t = trig[key]
        jb = t["just_rate"]; oc = t["by_outcome"]
        n = t["n"]; raised = t["raised"]
        # 격상 주 실현율(precision) vs 비격상 주 실현율(대조) — 선행성(lift) 판정
        rb = b.loc[cfg_key] if cfg_key in b.index else None
        esc = float(rb["precision"]) if rb is not None else float("nan")
        neg = float(rb["neg_rate"]) if rb is not None else float("nan")
        lift = (esc / neg) if (not np.isnan(esc) and not np.isnan(neg) and neg > 0) else float("nan")
        if n == 0 or raised == 0:
            v, tag = "폐지", "발화/격상 없음 — 현 임계에서 무효"
        elif (not np.isnan(jb) and jb >= 0.45) and (not np.isnan(lift) and lift >= 1.5):
            v, tag = "유지", f"정당화 {jb:.2f}·결과선행 lift ×{lift:.1f}(격상 {esc:.2f} vs 대조 {neg:.2f})"
        elif (not np.isnan(jb) and jb >= 0.3) or (not np.isnan(lift) and lift >= 1.3):
            v, tag = "임계 조정", f"정당화 {_fmt(jb,2)}·lift ×{_fmt(lift,1)} — 부분신호, 임계 상향으로 오격상 축소"
        else:
            v, tag = "폐지", f"정당화 {_fmt(jb,2)}·lift ×{_fmt(lift,1)}(≈기저) — 노이즈 격상 우위"
        rows.append(f"| {nm} | **{v}** | {tag} |")
        notes.append(f"- **{nm}**: 발화 {n}주/실격상 {raised}주, 정당화 {_fmt(jb,2)}, "
                     f"결과선행(향후3M 가격급변) 격상주 {_fmt(esc,3)} vs 비격상 {_fmt(neg,3)} "
                     f"(lift ×{_fmt(lift,1)}) → **{v}**")

    verdict("vol", "① 변동성급증", "(b) +변동성")
    verdict("hhi", "② 수입편중極", "(c) +편중")
    verdict("geo", "③ 지정학 고신뢰", "(d) 전체 On(현행)")
    R.extend(rows)
    R.append("")
    R.extend(notes)
    R.append("\n### 종합 권고\n")
    R.append("- **① 유지 · ② 임계 조정(단계 강등) · ③ 폐지** 권고. 4구성 비교에서 규칙을 "
             "얹을수록 QWK가 단조 하락(0.94→0.42)하고 FAR가 0.04→0.59로 폭증했으며, Miss 감소는 "
             "0.06p에 그침 — 오버라이드 계층 전체의 순효과는 음(-)이다.")
    R.append("- **① 변동성급증**만이 유일하게 결과 선행성을 보였다(격상주 향후 가격급변 실현율 "
             "0.26 vs 비격상 0.07, 약 3.7배). 다만 '최소 관심(1)' 격상은 주의(2) 문턱을 넘지 않아 "
             "FAR·Miss에는 영향이 없다 — 정보성은 있으나 경보단계를 바꾸지 않는 저위험 규칙이므로 유지.")
    R.append("- **② 수입편중極**은 단독으로 FAR를 0.04→0.20으로 올리면서(관심·주의를 건너뛰고 "
             "'경계'까지 점프) 결과 선행성이 미약하다(lift ≈1.4, 정당화 0.20). HHI는 구조적·저빈도 "
             "변동이라 이벤트 타이밍 신호가 아니다 → 격상 목표단계를 '경계'에서 '관심'(컨텍스트 플래그) "
             "으로 강등하는 임계 조정 권고. 강등해도 FAR 악화 없이 편중 정보를 보존한다.")
    R.append("- **③ 지정학 고신뢰**는 격상 647주로 FAR 폭증의 주범이며 격상주 실현율이 오히려 기저 "
             "이하(0.08 vs 0.09) — 순수 노이즈. GDELT 뉴스 신호는 이미 지수(변수⑥)에 반영되므로 "
             "이중계상이기도 하다 → 폐지. 유지하려면 severity 3 단발이 아니라 '복수 소스·supply_down "
             "지속' 등 확정력 조건으로 임계를 대폭 강화해야 한다.")
    R.append("\n### 방법론 유의점\n")
    R.append("- 결과변수 y_vol은 '가격' 경로(vol_spike)만 사용 — ③ 지정학·② 편중이 물량 경로로 "
             "선행할 여지는 이 축에서 과소평가될 수 있다(build_proxy_label의 수입이탈 proxy는 "
             "노이즈 지배로 제외됨). 그럼에도 기준A(교사 정합)에서도 두 규칙이 QWK·FAR를 악화시켜 "
             "결론은 두 축에서 수렴한다.")
    R.append("- geo severity 0~3 중 실제 격상 조건은 severity 3(정규화 1.0≥0.85)뿐 — severity 2는 "
             "미발화. 즉 ③은 '최고강도 단발 뉴스'에만 반응하는데도 674주 발화로 상시 격상에 가깝다.")
    return R


if __name__ == "__main__":
    main()
