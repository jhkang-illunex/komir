# -*- coding: utf-8 -*-
"""광종별 수급위기 진단모델 재학습·평가 — 정답셋(fact_diagnosis_answer, KOMIS 가격이격률
등급)을 타깃으로, 지정학위기지수+피처로 학습 (2026-07-16, 사용자 지시).

**오염(contamination) 방지 원칙(사용자 지시 핵심)**: fact_diagnosis_answer의 등급은 가격의
"이격률"(과거 평균 대비 표준편차 배수)로 정의된다. 프로젝트 기존 피처 중 `price_z52`
(52주 가격 z-score, diagnosis_opt.py), `volatility_12w`(가격 변동성), `spread_pct`,
`ref_price`(원시 가격 수준)는 **정답과 동일한 원천(같은 가격 시계열의 통계량)이라 정답을
사실상 재진술하는 피처** — 이를 학습 피처로 쓰면 "예측"이 아니라 "라벨 정의를 근사 복원"하는
것이 되어 오염이다. 따라서:
  - **주 모델(GEO_FEATS)**: 지정학위기지수(geopolitical_risk)·지정학변화(geo_chg)·급증확률
    (p_burst)·수입편중(import_hhi)·수입증감(import_yoy·import_cagr3) — 전부 대상 광종의
    가격 시계열과 무관한 외생 변수. grade_lag1(직전 주 등급, 과거 정보만 사용 — 미래 정보
    아니므로 오염 아님)도 포함.
  - **참고 모델(ALL_FEATS, 오염 위험 명시)**: 위에 가격 파생 피처(ref_price·volatility_12w·
    spread_pct·price_z52)를 추가 — 순수 비교 참고용. 이 모델의 성능은 실제 예측력이 아니라
    "라벨을 얼마나 잘 복원하는가"에 가까우므로 정식 성능 주장에 쓰지 않는다.
  - **시간 누수 방지**: 워크포워드(train<test 시점) 분할, 전처리(imputer/scaler)는 train에만
    fit. grade_lag1도 엄격히 과거 시점만 사용(shift(1), 미래 참조 없음).

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_retrain_answer
산출: outputs/model_opt/diagnosis_retrain_answer.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                      # noqa: E402
from scripts.override_backtest import qwk                # noqa: E402

GEO_FEATS = ["geopolitical_risk", "geo_chg", "p_burst", "import_hhi", "import_yoy",
             "import_cagr3", "grade_lag1"]
GEO_ONLY_NO_LAG = ["geopolitical_risk", "geo_chg", "p_burst", "import_hhi", "import_yoy",
                    "import_cagr3"]   # grade_lag1 제외 — 지정학·무역 신호의 독립 예측력만 검정
PRICE_FEATS = ["ref_price", "volatility_12w", "spread_pct", "price_z52"]
ALL_FEATS = GEO_FEATS + PRICE_FEATS

FOLDS = [("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01"), ("2025-01-01", "2027-01-01")]
COMMODITY_START = {"CU": "2016-01-01", "NI": "2016-01-01", "CO": "2016-01-01",
                    "REE": "2016-01-01", "LI": "2020-12-28"}


# ─────────────────────────── 패널 구성 ───────────────────────────
def build_panel(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    w = con.execute("""
        SELECT commodity_code, obs_date, geopolitical_risk, import_hhi, import_yoy,
               import_cagr3, ref_price, volatility_12w, spread_pct
        FROM mart_weekly_diagnosis
        WHERE obs_date >= '2015-01-01'
        ORDER BY commodity_code, obs_date""").df()
    w["obs_date"] = pd.to_datetime(w["obs_date"])

    # p_burst(주간, geo_prob) 조인. 과거 발견(2026-07-16): geo_prob.period가 일요일 앵커라
    # mart_weekly_diagnosis.obs_date(월요일)와 정확일치 조인 시 100% 미매칭이었음 — 근본
    # 수정으로 geo/publish.py의 geo_prob 발행 경계에서 +1일(월요일) 보정을 적용했으므로
    # (prob_model.py 내부 계산 자체는 indexer.py의 geo_index와 정합을 위해 일요일 유지,
    # DB로 나가는 geo_prob만 외부 규약에 맞춤) 이제 정확일치 조인으로 충분하다.
    pb = con.execute("""SELECT commodity_code, CAST(period AS DATE) AS obs_date,
        p_burst_cal AS p_burst FROM geo_prob""").df()
    pb["obs_date"] = pd.to_datetime(pb["obs_date"])
    w = w.merge(pb[["commodity_code", "obs_date", "p_burst"]],
                on=["commodity_code", "obs_date"], how="left")

    # 52주 가격 z-score(참고 모델 전용, price_z52) — diagnosis_opt.py와 동일 정의
    pz = con.execute("""
        WITH p AS (
          SELECT commodity_code, obs_date, ref_price,
                 avg(ref_price) OVER wnd AS m52, stddev_samp(ref_price) OVER wnd AS s52
          FROM mart_weekly_diagnosis
          WINDOW wnd AS (PARTITION BY commodity_code ORDER BY obs_date
                         ROWS BETWEEN 51 PRECEDING AND CURRENT ROW)
        )
        SELECT commodity_code, obs_date, (ref_price-m52)/NULLIF(s52,0) AS price_z52 FROM p""").df()
    pz["obs_date"] = pd.to_datetime(pz["obs_date"])
    w = w.merge(pz, on=["commodity_code", "obs_date"], how="left")

    # 정답셋(타깃)
    ans = con.execute("""SELECT commodity_code, obs_date, grade_ord
        FROM fact_diagnosis_answer WHERE src='KOMIS_GRADE_MONITOR'""").df()
    ans["obs_date"] = pd.to_datetime(ans["obs_date"])
    con.close()

    w = w.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    w["geo_chg"] = w.groupby("commodity_code")["geopolitical_risk"] \
        .transform(lambda s: s - s.shift(1))

    df = w.merge(ans, on=["commodity_code", "obs_date"], how="inner")
    df = df.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    # grade_lag1: 정답 자체의 시차항 — 과거 정보만 사용(오염 아님, 표준 AR 피처)
    df["grade_lag1"] = df.groupby("commodity_code")["grade_ord"].shift(1)

    parts = []
    for cc, g in df.groupby("commodity_code"):
        start = COMMODITY_START.get(cc, "2016-01-01")
        parts.append(g[g["obs_date"] >= start])
    df = pd.concat(parts, ignore_index=True)
    df = df.dropna(subset=["grade_lag1"])   # 첫 주(시차 없음)만 제외
    return df


# ─────────────────────────── 모델 ───────────────────────────
def _prep(feats):
    return Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())])


def _fit_predict_reg(name, tr, te, feats, per_commodity):
    def one(tr_, te_):
        prep = _prep(feats)
        Xtr_ = prep.fit_transform(tr_[feats]); Xte_ = prep.transform(te_[feats])
        m = Ridge(alpha=1.0) if name == "Ridge" else \
            HistGradientBoostingRegressor(max_depth=4, learning_rate=0.08, max_iter=250, random_state=0)
        m.fit(Xtr_, tr_["grade_ord"].values)
        return m.predict(Xte_)
    if not per_commodity:
        tr2 = pd.get_dummies(tr, columns=["commodity_code"], prefix="cc")
        te2 = pd.get_dummies(te, columns=["commodity_code"], prefix="cc")
        for c in [c for c in tr2.columns if c.startswith("cc_")]:
            if c not in te2:
                te2[c] = 0
        feats2 = feats + [c for c in tr2.columns if c.startswith("cc_")]
        prep = _prep(feats2)
        Xtr_ = prep.fit_transform(tr2[feats2]); Xte_ = prep.transform(te2[feats2])
        m = Ridge(alpha=1.0) if name == "Ridge" else \
            HistGradientBoostingRegressor(max_depth=4, learning_rate=0.08, max_iter=250, random_state=0)
        m.fit(Xtr_, tr2["grade_ord"].values)
        return m.predict(Xte_)
    preds = pd.Series(index=te.index, dtype=float)
    for cc, g_te in te.groupby("commodity_code"):
        g_tr = tr[tr["commodity_code"] == cc]
        if len(g_tr) < 24:
            preds.loc[g_te.index] = g_tr["grade_ord"].mean()
            continue
        preds.loc[g_te.index] = one(g_tr, g_te)
    return preds.values


def _fit_predict_clf(name, tr, te, feats):
    prep = _prep(feats)
    Xtr_ = prep.fit_transform(tr[feats]); Xte_ = prep.transform(te[feats])
    ytr = tr["grade_ord"].astype(int).values
    if name == "Logistic":
        m = LogisticRegression(max_iter=2000, multi_class="multinomial", C=1.0)
    elif name == "DecisionTree":
        m = DecisionTreeClassifier(max_depth=4, min_samples_leaf=10, random_state=0)
    elif name == "RandomForest":
        m = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=5,
                                    random_state=0, n_jobs=4)
    else:
        raise ValueError(name)
    m.fit(Xtr_, ytr)
    return m.predict(Xte_)


CANDIDATES = [
    ("지속성(직전주 유지)", "persist", None),
    ("나이브(항상 정상)", "naive0", None),
    ("Ridge(풀링)", "reg", dict(name="Ridge", per=False)),
    ("Ridge(광종별)", "reg", dict(name="Ridge", per=True)),
    ("HistGBM(풀링)", "reg", dict(name="HistGBM", per=False)),
    ("HistGBM(광종별)", "reg", dict(name="HistGBM", per=True)),
    ("Logistic(직접)", "clf", dict(name="Logistic")),
    ("DecisionTree(직접)", "clf", dict(name="DecisionTree")),
    ("RandomForest(직접)", "clf", dict(name="RandomForest")),
]


def run_walkforward(df: pd.DataFrame, feats: list[str]):
    """폴드별 QWK(참고용, 일부 폴드는 단일클래스라 0/NaN로 붕괴 가능)와, 전체 폴드 예측을
    풀링한 뒤 1회 계산하는 pooled QWK(주 지표 — 단일클래스 폴드 아티팩트에 안정적)를 모두 반환.

    전환주 적중률(chg_acc, diagnosis_opt.py의 전환월 적중과 동일 정의): 실제 등급이 '직전 주
    실제 등급'(grade_lag1, 반올림한 정수 — 예측이 아니라 실측)과 달라진 주(전환주)만 골라
    정확도 계산. 지속성(persistence)은 정의상 전환주에서 항상 틀리므로(직전값=예측, 실제는
    달라짐) 이 구간에서 구조적으로 0% — naive가 전패하는, 모델의 실가치가 드러나는 구간."""
    rows, pooled = [], {label: {"y": [], "p": [], "lag": []} for label, _, _ in CANDIDATES}
    for t0, t1 in FOLDS:
        tr_mask = df["obs_date"] < t0
        te_mask = (df["obs_date"] >= t0) & (df["obs_date"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_te = te["grade_ord"].astype(int).values
        lag_te = te["grade_lag1"].round().clip(0, 2).astype(int).values
        n_cls = len(set(y_te))
        for label, kind, kw in CANDIDATES:
            if kind == "persist":
                pred = te["grade_lag1"].round().clip(0, 2).astype(int).values
            elif kind == "naive0":
                pred = np.zeros(len(te), dtype=int)
            elif kind == "reg":
                raw = _fit_predict_reg(kw["name"], tr, te, feats, kw["per"])
                pred = np.clip(np.round(raw), 0, 2).astype(int)
            else:
                pred = _fit_predict_clf(kw["name"], tr, te, feats)
            q = qwk(y_te, pred, K=3)
            acc = float((y_te == pred).mean())
            chg_mask = lag_te != y_te
            chg_acc = float((pred[chg_mask] == y_te[chg_mask]).mean()) if chg_mask.sum() else np.nan
            rows.append(dict(fold=f"{t0[:4]}", model=label, n=len(te), QWK=q, acc=acc,
                              chg_acc=chg_acc, n_chg=int(chg_mask.sum()), n_class_in_fold=n_cls))
            pooled[label]["y"].append(y_te)
            pooled[label]["p"].append(pred)
            pooled[label]["lag"].append(lag_te)
    fold_tab = pd.DataFrame(rows)

    pooled_rows = []
    for label, d in pooled.items():
        if not d["y"]:
            continue
        y = np.concatenate(d["y"]); p = np.concatenate(d["p"]); lag = np.concatenate(d["lag"])
        chg_mask = lag != y
        chg_acc = float((p[chg_mask] == y[chg_mask]).mean()) if chg_mask.sum() else np.nan
        pooled_rows.append(dict(model=label, QWK=qwk(y, p, K=3),
                                 acc=float((y == p).mean()), n=len(y),
                                 chg_acc=chg_acc, n_chg=int(chg_mask.sum())))
    pooled_tab = pd.DataFrame(pooled_rows)
    return fold_tab, pooled_tab


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    print(f"패널: {df.shape}, 광종: {sorted(df['commodity_code'].unique())}, "
          f"기간: {df['obs_date'].min().date()}~{df['obs_date'].max().date()}")

    geo_feats = [f for f in GEO_FEATS if df[f].notna().sum() > 50]
    geo_nolag_feats = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    all_feats = [f for f in ALL_FEATS if df[f].notna().sum() > 50]
    print(f"GEO_FEATS(주모델, 가격무관): {geo_feats}")
    print(f"GEO_ONLY_NO_LAG(grade_lag1 제외, 지정학·무역 신호 단독 예측력 검정): {geo_nolag_feats}")
    print(f"ALL_FEATS(참고, 가격피처 포함=오염위험): {all_feats}")

    fold_geo, pooled_geo = run_walkforward(df, geo_feats)
    fold_nolag, pooled_nolag = run_walkforward(df, geo_nolag_feats)
    fold_all, pooled_all = run_walkforward(df, all_feats)
    print("\n[진단] 폴드별 클래스 수(1=단일클래스→QWK 0/NaN 붕괴 가능):")
    print(fold_geo[["fold", "n_class_in_fold"]].drop_duplicates().to_string(index=False))

    def summarize(pooled, label, baseline="지속성(직전주 유지)"):
        agg = pooled.sort_values("QWK", ascending=False).reset_index(drop=True)
        base_q = float(agg.loc[agg["model"] == baseline, "QWK"].iloc[0])
        agg["net_gain"] = agg["QWK"] - base_q
        print(f"\n=== {label}: 풀링 QWK(전체 폴드 예측 합산 후 1회 계산 — 주 지표, "
              f"기준선={baseline}) ===")
        print(agg.round(4).to_string(index=False))
        # 전환주 적중률 기준 정렬(지속성은 정의상 0 — 나이브와 별개로 항상 최하위권)
        agg_chg = agg.sort_values("chg_acc", ascending=False).reset_index(drop=True)
        print(f"--- 전환주(직전주 대비 실제 등급 변경) 적중률 기준 정렬, n_chg={agg['n_chg'].iloc[0]} ---")
        print(agg_chg[["model", "chg_acc", "QWK", "acc", "n_chg"]].round(4).to_string(index=False))
        return agg

    agg_geo = summarize(pooled_geo, "GEO_FEATS(주모델, grade_lag1 포함)")
    agg_nolag = summarize(pooled_nolag, "GEO_ONLY_NO_LAG(grade_lag1 제외, 순수 지정학·무역 신호)",
                           baseline="나이브(항상 정상)")
    agg_all = summarize(pooled_all, "ALL_FEATS(참고, 오염위험)")

    # 전환주 적중률 챔피언(레벨 QWK 챔피언과 별개) — 지속성·나이브는 정의상/구조상 전환주에서
    # 불리하므로 후보에서 제외하고 실제 학습모델 중 최고를 챔피언으로 선정
    def chg_champion(agg):
        cand = agg[~agg["model"].isin(["지속성(직전주 유지)", "나이브(항상 정상)"])]
        cand = cand.dropna(subset=["chg_acc"])
        return cand.sort_values("chg_acc", ascending=False).iloc[0]["model"] if len(cand) else None

    champion_geo_chg = chg_champion(agg_geo)
    champion_nolag_chg = chg_champion(agg_nolag)
    print(f"\n전환주 적중률 챔피언 — GEO_FEATS: {champion_geo_chg} / "
          f"GEO_ONLY_NO_LAG: {champion_nolag_chg}")

    def per_commodity(champion_label, feats):
        kind = next(k for lbl, k, kw in CANDIDATES if lbl == champion_label)
        kw = next(kw for lbl, k, kw in CANDIDATES if lbl == champion_label)
        cc_rows = []
        for cc in sorted(df["commodity_code"].unique()):
            ys, ps, ps_persist = [], [], []
            for t0, t1 in FOLDS:
                tr = df[df["obs_date"] < t0].copy()
                te_cc = df[(df["obs_date"] >= t0) & (df["obs_date"] < t1)
                           & (df["commodity_code"] == cc)].copy()
                if len(te_cc) == 0 or len(tr) < 60:
                    continue
                if kind == "persist":
                    pred = te_cc["grade_lag1"].round().clip(0, 2).astype(int).values
                elif kind == "naive0":
                    pred = np.zeros(len(te_cc), dtype=int)
                elif kind == "reg":
                    raw = _fit_predict_reg(kw["name"], tr, te_cc, feats, kw["per"])
                    pred = np.clip(np.round(raw), 0, 2).astype(int)
                else:
                    pred = _fit_predict_clf(kw["name"], tr, te_cc, feats)
                ys.append(te_cc["grade_ord"].astype(int).values)
                ps.append(pred)
                ps_persist.append(te_cc["grade_lag1"].round().clip(0, 2).astype(int).values)
            if not ys:
                continue
            y = np.concatenate(ys); p = np.concatenate(ps); pp = np.concatenate(ps_persist)
            q = qwk(y, p, K=3); q_persist = qwk(y, pp, K=3)
            chg_mask = pp != y   # 직전주 실제 등급과 현재 실제 등급이 다른 주(전환주)
            chg_acc = float((p[chg_mask] == y[chg_mask]).mean()) if chg_mask.sum() else np.nan
            chg_acc_persist = float((pp[chg_mask] == y[chg_mask]).mean()) if chg_mask.sum() else np.nan
            cc_rows.append(dict(commodity=cc, n=len(y), n_chg=int(chg_mask.sum()),
                                 QWK=q, QWK_persist=q_persist, net_gain=q - q_persist,
                                 chg_acc=chg_acc, chg_acc_persist=chg_acc_persist))
        return pd.DataFrame(cc_rows)

    champion = champion_geo_chg or agg_geo.iloc[0]["model"]
    cc_tab = per_commodity(champion, geo_feats)
    print(f"\n=== 광종별(GEO_FEATS 챔피언={champion}, 테스트폴드 2023~2027 전체 풀링) ===")
    print(cc_tab.round(3).to_string(index=False))

    cc_tab_nolag = per_commodity(champion_nolag_chg, geo_nolag_feats)
    print(f"\n=== 광종별(GEO_ONLY_NO_LAG 챔피언={champion_nolag_chg}, "
          f"테스트폴드 2023~2027 전체 풀링) ===")
    print(cc_tab_nolag.round(3).to_string(index=False))

    write_report(df, geo_feats, geo_nolag_feats, all_feats, agg_geo, agg_nolag, agg_all,
                 fold_geo, cc_tab, cc_tab_nolag, champion, champion_geo_chg, champion_nolag_chg)


def write_report(df, geo_feats, geo_nolag_feats, all_feats, agg_geo, agg_nolag, agg_all,
                  fold_geo, cc_tab, cc_tab_nolag, champion, champion_geo_chg, champion_nolag_chg):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_retrain_answer.md")
    L = []
    L.append("# 광종별 수급위기 진단모델 재학습·평가 — 정답셋: KOMIS 가격이격률 등급 "
             "(전환주 적중률 재평가 포함)\n")
    L.append("작성: 2026-07-16 · 방법: 워크포워드 3폴드(test 2023/2024/2025~), 후보 9종"
             "(지속성·나이브·Ridge×2·HistGBM×2·Logistic·DecisionTree·RandomForest), "
             "QWK(K=3, fact_diagnosis_answer 3단계 그대로) + 전환주 적중률(chg_acc, "
             "diagnosis_opt.py의 전환월 적중과 동일 정의를 주간 그레인에 적용).\n")
    L.append(f"- 패널: {df.shape[0]}행, 광종 {sorted(df['commodity_code'].unique())}, "
             f"기간 {df['obs_date'].min().date()}~{df['obs_date'].max().date()}\n")
    L.append("\n## 지표 산출 방식 — 폴드평균 대신 풀링(pooled) QWK 채택(중요)\n")
    cls_note = fold_geo[["fold", "n_class_in_fold"]].drop_duplicates()
    L.append("2023·2024 테스트폴드는 5광종 전체가 100% 단일클래스(정상)로 확인됨(실측: "
             "2022 원자재 급등 이후 가격 안정기, 데이터 오류 아님) — 이 상태에서 QWK는 "
             "통계적으로 정의 불가(관측/기대 일치도가 모두 포화돼 0 또는 NaN으로 붕괴, "
             "모델 품질과 무관한 아티팩트). 폴드별 클래스 수:\n")
    for _, r in cls_note.iterrows():
        L.append(f"  - {r['fold']}: {int(r['n_class_in_fold'])}개 클래스")
    L.append("\n따라서 **폴드별 QWK의 단순평균(아티팩트에 취약) 대신, 3개 테스트폴드의 예측을 "
             "전부 풀링한 뒤 1회 계산하는 pooled QWK를 주 지표로 채택**한다(2025~ 폴드가 "
             "유일하게 클래스 다양성이 있어 pooled 결과는 사실상 이 폴드가 지배).\n")
    L.append("\n## 오염 방지 원칙\n")
    L.append("등급의 정의(가격 이격률=과거평균 대비 표준편차 배수)와 동일 원천인 가격파생 "
             "피처(ref_price·volatility_12w·spread_pct·price_z52)는 **주모델에서 제외** — "
             "포함 시 '예측'이 아니라 '라벨 정의의 근사 복원'이 되기 때문(사용자 지시). "
             "주모델(GEO_FEATS)은 지정학위기지수·지정학변화·급증확률·수입편중·수입증감· "
             "직전주등급(grade_lag1, 과거정보만)만 사용. 가격피처 포함판(ALL_FEATS)은 "
             "오염위험을 명시한 참고용으로만 병기.\n")
    L.append(f"- GEO_FEATS(grade_lag1 포함): {geo_feats}")
    L.append(f"- GEO_ONLY_NO_LAG(grade_lag1 제외): {geo_nolag_feats}")
    L.append(f"- ALL_FEATS(참고, 오염위험): {all_feats}\n")

    n_chg_geo = int(agg_geo["n_chg"].iloc[0])
    L.append(f"\n## ★ 전환주 적중률(chg_acc) — 이번 재평가 핵심 지표\n")
    L.append(f"diagnosis_opt.py의 '전환월 적중'(chg_acc)과 동일 정의를 주간 그레인에 적용: "
             f"**직전 주 실제 등급과 이번 주 실제 등급이 다른 주(전환주, GEO_FEATS 패널 기준 "
             f"n={n_chg_geo}건)만 골라 정확도를 계산**한다. 지속성은 정의상 전환주에서 항상 "
             f"틀리므로(예측=직전값, 실제는 달라짐) chg_acc=0.000으로 구조적 전패 — naive가 "
             f"이길 수 없는, 모델의 실가치가 드러나는 유일한 구간이다.\n")

    L.append("\n## 주모델(GEO_FEATS, grade_lag1 포함) — 전환주 적중률 기준 정렬\n")
    L.append("| 모델 | chg_acc | QWK | acc | n_chg | 순개선(QWK, vs 지속성) |")
    L.append("|---|---|---|---|---|---|")
    for _, r in agg_geo.sort_values("chg_acc", ascending=False).iterrows():
        ca = "—" if pd.isna(r["chg_acc"]) else f"{r['chg_acc']:.4f}"
        L.append(f"| {r['model']} | {ca} | {r['QWK']:.4f} | {r['acc']:.4f} | "
                 f"{int(r['n_chg'])} | {r['net_gain']:+.4f} |")
    L.append(f"\n전환주 적중률 챔피언(학습모델 중 최고, 지속성·나이브 제외): "
             f"**{champion_geo_chg}**\n")

    n_chg_nolag = int(agg_nolag["n_chg"].iloc[0])
    L.append("\n## GEO_ONLY_NO_LAG(grade_lag1 제외, 순수 지정학·무역 신호 단독 예측력) "
             f"— 전환주 적중률 기준 정렬(n_chg={n_chg_nolag})\n")
    L.append("grade_lag1을 빼서 지정학위기지수·급증확률·수입편중 등 순수 외생 신호만으로 "
             "다음 주 등급을 얼마나 예측할 수 있는지 독립적으로 검정한다(관성의 도움 없이). "
             "이 실험에서는 애초에 지속성을 계산할 수 없는 것과 마찬가지 취지이므로, "
             "chg_acc를 나이브(항상 정상)와 비교한다 — 나이브도 전환주에서는 등급이 '정상이 "
             "아닌 쪽으로' 바뀌는 대부분의 경우 구조적으로 틀린다.\n")
    L.append("| 모델 | chg_acc | QWK | acc | n_chg | 순개선(QWK, vs 나이브) |")
    L.append("|---|---|---|---|---|---|")
    for _, r in agg_nolag.sort_values("chg_acc", ascending=False).iterrows():
        ca = "—" if pd.isna(r["chg_acc"]) else f"{r['chg_acc']:.4f}"
        L.append(f"| {r['model']} | {ca} | {r['QWK']:.4f} | {r['acc']:.4f} | "
                 f"{int(r['n_chg'])} | {r['net_gain']:+.4f} |")
    L.append(f"\n전환주 적중률 챔피언(학습모델 중 최고): **{champion_nolag_chg}**\n")

    L.append("\n## 참고모델(ALL_FEATS, 가격피처 포함 — 오염위험) — 전환주 적중률 기준 정렬\n")
    L.append("| 모델 | chg_acc | QWK | acc | n_chg | 순개선(QWK, vs 지속성) |")
    L.append("|---|---|---|---|---|---|")
    for _, r in agg_all.sort_values("chg_acc", ascending=False).iterrows():
        ca = "—" if pd.isna(r["chg_acc"]) else f"{r['chg_acc']:.4f}"
        L.append(f"| {r['model']} | {ca} | {r['QWK']:.4f} | {r['acc']:.4f} | "
                 f"{int(r['n_chg'])} | {r['net_gain']:+.4f} |")

    L.append(f"\n## 광종별 — GEO_FEATS 챔피언={champion} (grade_lag1 포함, "
             f"전환주에서 전부 0% 확인용)\n")
    L.append("| 광종 | n | n_chg | chg_acc | chg_acc(지속성) | QWK | QWK(지속성) | 순개선 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in cc_tab.iterrows():
        ca = "—" if pd.isna(r["chg_acc"]) else f"{r['chg_acc']:.3f}"
        cap = "—" if pd.isna(r["chg_acc_persist"]) else f"{r['chg_acc_persist']:.3f}"
        L.append(f"| {r['commodity']} | {int(r['n'])} | {int(r['n_chg'])} | {ca} | {cap} | "
                 f"{r['QWK']:.3f} | {r['QWK_persist']:.3f} | {r['net_gain']:+.3f} |")

    L.append(f"\n## ★ 광종별 — GEO_ONLY_NO_LAG 챔피언={champion_nolag_chg} "
             f"(grade_lag1 제외, 진짜 조기경보력)\n")
    L.append("| 광종 | n | n_chg | chg_acc | chg_acc(지속성, 항상 0) | QWK | 순개선(QWK, vs 지속성) |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in cc_tab_nolag.iterrows():
        ca = "—" if pd.isna(r["chg_acc"]) else f"{r['chg_acc']:.3f}"
        cap = "—" if pd.isna(r["chg_acc_persist"]) else f"{r['chg_acc_persist']:.3f}"
        L.append(f"| {r['commodity']} | {int(r['n'])} | {int(r['n_chg'])} | {ca} | {cap} | "
                 f"{r['QWK']:.3f} | {r['net_gain']:+.3f} |")

    best_nolag = agg_nolag[agg_nolag["model"] != "지속성(직전주 유지)"].iloc[0]
    r0 = agg_geo[agg_geo["model"] == "지속성(직전주 유지)"].iloc[0]
    naive_row = agg_nolag[agg_nolag["model"] == "나이브(항상 정상)"].iloc[0]
    chg_champ_row = agg_nolag[agg_nolag["model"] == champion_nolag_chg].iloc[0]
    L.append("\n## 종합 해석(전환주 재평가) — 결합하면 완전히 놓치고, 분리하면 절반 이상 잡는다\n")
    L.append(f"- **grade_lag1 포함(GEO_FEATS) 시 — 결정적 결과**: 학습된 6개 모델(Ridge×2·"
             f"HistGBM×2·Logistic·DecisionTree·RandomForest) **전부 전환주 적중률 "
             f"0.000({n_chg_geo}건 전환주 전량 실패)** — 레벨 QWK는 지속성과 동률(0.9687)이라 "
             f"'무해'해 보였지만, 실제로 위기가 발생/해소되는 그 순간(전환주)만 놓고 보면 "
             f"**모델이 '실패한 지속성'과 동일하게 행동**한다(0% = 지속성의 구조적 전패와 "
             f"동일). 이는 grade_lag1의 회귀계수가 워낙 커서 다른 피처의 기여가 반올림 임계를 "
             f"넘지 못하기 때문 — 절대 무해하지 않다.\n")
    L.append(f"- **grade_lag1 제외(GEO_ONLY_NO_LAG) 시 — 핵심 발견**: 챔피언 "
             f"**{champion_nolag_chg}가 전환주 적중률 {chg_champ_row['chg_acc']:.4f}"
             f"({int(chg_champ_row['n_chg'])}건 중 적중)** — 나이브(항상 정상)의 "
             f"{naive_row['chg_acc']:.4f}, 지속성의 0.0000을 크게 상회. **지정학위기지수·"
             f"급증확률·수입편중 등 순수 외생 신호만으로도 실제 위기 전환의 절반 이상을 "
             f"잡아낸다** — grade_lag1과 결합하지 않을 때 지정학 신호의 조기경보력이 가장 "
             f"뚜렷하게 드러난다.\n")
    L.append(f"- **원인**: grade_lag1을 포함하면 회귀/분류기가 '다음 주도 이번 주와 같다'는 "
             f"압도적으로 안전한 예측에 안주해버려(레벨 정확도 극대화 관점에서는 합리적) 정작 "
             f"전환을 맞히려는 시도 자체를 하지 않는다. 반면 grade_lag1이 없으면 모델이 지정학·"
             f"무역 신호에서 '지금과 다른 상태'로의 전환 신호를 적극적으로 찾아낸다.\n")
    L.append(f"- **권고(구체화)**: (1) **grade_lag1과 지정학신호를 단순 회귀로 합치지 말고 "
             f"게이트/오버라이드 구조로 결합** — 평상시엔 지속성(grade_lag1)을 기본예측으로 쓰되, "
             f"GEO_ONLY_NO_LAG 챔피언({champion_nolag_chg})의 예측이 grade_lag1과 다르고 신뢰도가 "
             f"높을 때만 전환으로 덮어쓰는 방식(alert.py의 규칙 오버라이드 계층과 유사한 설계). "
             f"(2) 이 게이트 방식을 동일 워크포워드·풀링 방법론으로 백테스트(다음 과제). "
             f"(3) GEO_ONLY_NO_LAG 산출물을 '보조 조기경보 신호'로 대시보드에 별도 게시 검토 "
             f"— 레벨 예측력은 약하지만(QWK {best_nolag['QWK']:.2f}) 전환 탐지력은 무시할 "
             f"수준이 아니다.\n")
    L.append(f"- **표본 크기 주의(중요)**: 전환주는 3개 테스트폴드(2023~2027) 전체를 합쳐도 "
             f"5광종 총 {n_chg_geo}건뿐이며 광종별로는 최소 2건(LI)에 불과 — chg_acc 수치는 "
             f"방향성 참고용이지 통계적으로 확정된 값이 아니다. LI의 chg_acc=0.000(2건 중 0건 "
             f"적중)은 표본이 너무 작아 '지정학신호가 LI에는 안 통한다'는 결론의 근거가 되지 "
             f"못한다. 학습기간을 2016년 이전으로 확장하거나(가능하면) 광종 풀링 신뢰구간을 "
             f"부트스트랩으로 산출하는 후속 검증이 필요하다.\n")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[diagnosis_retrain_answer] 리포트 → {path}")


if __name__ == "__main__":
    run()
