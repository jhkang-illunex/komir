# -*- coding: utf-8 -*-
"""구리(CU) proxy 역방향 신호 조사 (2026-07-16, 감사 후속 · 발주처 안건 5번).

배경: 결과변수 proxy 검증(build_proxy_label.py, 2026-07-15)에서 '가격 급변'(vol90>기준기간
P95, 향후 3개월) 결과라벨을 교사 위기지수(ci_teacher)가 강하게 선행 —
  LI 0.90 · NI 0.91 · REE 0.99 (AUC)
그런데 구리만 AUC 0.18로 **역방향**(교사가 높을수록 급변이 오히려 안 옴).

가설(팀리드): 구리는 LME 상장 광종이라 가격 변동성이 수급이 아닌 거시·투기 요인에 지배되어
교사 수급지수와 탈동조(decoupling)한다.

본 스크립트는 5개 항목으로 가설을 검증한다(전부 read_only, 기존 자산 무수정).
  1. 에피소드 열거: CU vol_spike=1 월 ±1개월의 가격방향·CASH-3M 스프레드·FX 13주 변동성·
     geo_index·심각(sev≥2) 이벤트 → 수급발/거시·투기발 판정
  2. 역방향 해부: ci_teacher P75+ 월 vs vol_spike 월의 ±6개월 시차 교차상관
  3. 통제 후 재검증: 부분상관/로지스틱 y_vol ~ ci_teacher + fx_vol
  4. 대안 proxy: (a) 백워데이션 진입 (b) 가격 급등만(상위 P95) → 교사 AUC 재계산
  5. 결론·권고

실행: python3 scripts/investigate_cu_proxy.py
산출: outputs/proxy_label/cu_investigation.md
"""
from __future__ import annotations
import os

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

# ── 경로/상수 ─────────────────────────────────────────────────────────────
DB = os.environ.get("MSR_DB",
    "/home/nuri/dev/git/ws/mine_ws/komir/warehouse/minerals.duckdb")
FX_CSV = ("/home/nuri/dev/git/ws/mine_ws/documents/"
          "1. 광물가격, 재고량, 지수 등 (1)/3. 원달러 환율.csv")
OUT_MD = ("/home/nuri/dev/git/ws/mine_ws/komir/mineral_supply_risk/"
          "outputs/proxy_label/cu_investigation.md")
CC = "CU"
ANCHOR = ("2020-01-01", "2023-12-31")   # build_proxy_label과 동일 기준기간
VOL_W = 13                              # 13주(≈90일) 변동성 창
HORIZON = 3                             # 향후 3개월


# ── 데이터 로더 ────────────────────────────────────────────────────────────
def load_weekly_price(con) -> pd.DataFrame:
    """CU 주간 LME_CASH·LME_3M → 로그수익률·vol90·스프레드."""
    px = con.execute(f"""
        SELECT c.obs_date, c.val AS cash, m.val AS m3 FROM
          (SELECT obs_date,val FROM fact_price
             WHERE commodity_code='{CC}' AND price_type='LME_CASH' AND freq='W') c
          LEFT JOIN (SELECT obs_date,val FROM fact_price
             WHERE commodity_code='{CC}' AND price_type='LME_3M' AND freq='W') m
          USING(obs_date) ORDER BY c.obs_date""").df()
    px["obs_date"] = pd.to_datetime(px["obs_date"])
    px["ret"] = np.log(px["cash"].clip(lower=1e-9)).diff()
    px["vol90"] = px["ret"].rolling(VOL_W).std()
    px["spread"] = px["cash"] - px["m3"]          # >0 → 백워데이션
    px["month"] = px["obs_date"].values.astype("datetime64[M]")
    return px


def load_fx() -> pd.DataFrame:
    """원달러 주간환율 → 13주 로그수익률 변동성(fx_vol). 2021-06부터 존재."""
    df = pd.read_csv(FX_CSV, encoding="cp949", skiprows=2, header=None,
                     names=["date", "krw", "unit"])
    df = df[df["date"].astype(str).str.match(r"\d{4}/\d{2}/\d{2}")].copy()   # 헤더/카피라이트 제거
    df["date"] = pd.to_datetime(df["date"], format="%Y/%m/%d")
    df["krw"] = pd.to_numeric(df["krw"], errors="coerce")
    df = df.dropna(subset=["krw"]).sort_values("date")
    df["fx_ret"] = np.log(df["krw"]).diff()
    df["fx_vol13"] = df["fx_ret"].rolling(VOL_W).std()
    df["month"] = df["date"].values.astype("datetime64[M]")
    return df.groupby("month", as_index=False).agg(fx_vol=("fx_vol13", "mean"),
                                                    krw=("krw", "mean"))


def load_monthly(con) -> pd.DataFrame:
    """proxy 라벨 + nowcast(교사) + geo_index + 심각이벤트 수를 광종-월로 병합."""
    pl = con.execute(f"""SELECT month, vol90, vol_thr, vol_spike, imp_dev,
                                import_drop, bad_event, proxy_bad_next3m
                         FROM mart_proxy_label WHERE commodity_code='{CC}'
                         ORDER BY month""").df()
    nc = con.execute(f"""SELECT CAST(month AS DATE) AS mo, ci_teacher, ci_pred,
                                stage_pred
                         FROM mart_diagnosis_nowcast WHERE commodity_code='{CC}'
                         ORDER BY mo""").df().rename(columns={"mo": "month"})
    gi = con.execute(f"""SELECT CAST(period AS DATE) AS month, idx_value AS geo_idx,
                                n_events AS geo_n
                         FROM geo_index WHERE commodity_code='{CC}' AND freq='M'
                         ORDER BY month""").df()
    sev = con.execute(f"""SELECT date_trunc('month', CAST(obs_date AS DATE)) AS month,
                                 count(*) FILTER (WHERE severity>=2) AS sev2,
                                 count(*) FILTER (WHERE severity>=3) AS sev3
                          FROM geo_event WHERE commodity_code='{CC}'
                          GROUP BY 1 ORDER BY 1""").df()
    for d in (pl, nc, gi, sev):
        d["month"] = pd.to_datetime(d["month"])
    m = (pl.merge(nc, on="month", how="left")
           .merge(gi, on="month", how="left")
           .merge(sev, on="month", how="left")
           .sort_values("month").reset_index(drop=True))
    return m


# ── 대표 이벤트 유형 ───────────────────────────────────────────────────────
def rep_event_types(con, month: pd.Timestamp, k: int = 3) -> str:
    """해당 월 CU 심각(sev≥2) 이벤트의 상위 event_type k개."""
    q = con.execute(f"""
        SELECT event_type, count(*) n FROM geo_event
        WHERE commodity_code='{CC}' AND severity>=2
          AND date_trunc('month', CAST(obs_date AS DATE))=DATE '{month:%Y-%m-01}'
        GROUP BY 1 ORDER BY 2 DESC LIMIT {k}""").df()
    if q.empty:
        return "-"
    return ", ".join(f"{r.event_type}({r.n})" for r in q.itertuples())


# ── 1. 에피소드 열거 ───────────────────────────────────────────────────────
def episodes(con, m: pd.DataFrame, px: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """vol_spike=1 월 ±1개월의 신호 표. 가격방향·스프레드·FX·geo·이벤트."""
    # 월별 가격(월말 CASH)·월평균 스프레드
    pxm = px.groupby("month").agg(cash=("cash", "last"),
                                  spread=("spread", "mean")).reset_index()
    pxm["mom"] = pxm["cash"].pct_change()                  # 전월대비 가격변화
    base = m.merge(pxm, on="month", how="left").merge(fx, on="month", how="left")

    # 조사 범위: 2020~2026 (교사 CI 가용구간). mart_proxy_label은 2004~ 존재하나
    # 교사·FX가 없는 이전 스파이크(GFC 등)는 판정 대상에서 제외.
    spikes = base.loc[(base["vol_spike"] == 1) &
                      (base["month"] >= "2020-01-01"), "month"].tolist()
    rows = []
    for s in spikes:
        for off in (-1, 0, 1):
            mo = (s + pd.DateOffset(months=off))
            r = base[base["month"] == mo]
            if r.empty:
                continue
            r = r.iloc[0]
            rows.append({
                "episode": f"{s:%Y-%m}", "offset": off, "month": f"{mo:%Y-%m}",
                "cash": round(r["cash"], 0) if pd.notna(r["cash"]) else np.nan,
                "가격MoM%": round(r["mom"] * 100, 1) if pd.notna(r["mom"]) else np.nan,
                "스프레드": round(r["spread"], 1) if pd.notna(r["spread"]) else np.nan,
                "백워데이션": "예" if pd.notna(r["spread"]) and r["spread"] > 0 else "아니오",
                "FX_vol": round(r["fx_vol"], 4) if pd.notna(r["fx_vol"]) else np.nan,
                "geo_idx": round(r["geo_idx"], 1) if pd.notna(r["geo_idx"]) else np.nan,
                "sev2": int(r["sev2"]) if pd.notna(r["sev2"]) else 0,
                "교사CI": round(r["ci_teacher"], 1) if pd.notna(r["ci_teacher"]) else np.nan,
                "대표이벤트": rep_event_types(con, mo) if off == 0 else "",
            })
    return pd.DataFrame(rows)


# ── 2. 시차 교차상관 ───────────────────────────────────────────────────────
def lag_crosscorr(m: pd.DataFrame) -> pd.DataFrame:
    """ci_teacher 상위분위(P75+) 지시자 × vol_spike의 ±6개월 시차 상관.

    corr(lag=L) = corr( 1[ci_teacher_t P75+],  vol_spike_{t+L} )
      L>0: 교사가 먼저(선행), 변동성이 나중  → 양수면 교사 선행
      L<0: 변동성이 먼저, 교사가 나중(지연 반응) → 양수면 교사 지연
    """
    d = m.dropna(subset=["ci_teacher"]).sort_values("month").reset_index(drop=True)
    thr = d["ci_teacher"].quantile(0.75)
    hi = (d["ci_teacher"] >= thr).astype(float)
    sp = d["vol_spike"].astype(float)
    rows = []
    for L in range(-6, 7):
        c = hi.corr(sp.shift(-L))    # vol_spike_{t+L}
        rows.append({"lag(월)": L, "corr": round(c, 3) if pd.notna(c) else np.nan,
                     "해석": ("교사 선행" if L > 0 else "교사 지연" if L < 0 else "동시")})
    return pd.DataFrame(rows), thr


# ── 3. 통제 후 재검증 ──────────────────────────────────────────────────────
def controlled(m: pd.DataFrame, fx: pd.DataFrame) -> dict:
    """y_vol(향후3m 급변) ~ ci_teacher + fx_vol 로지스틱 + 부분상관."""
    d = m.sort_values("month").copy()
    s = sum(d["vol_spike"].shift(-k) for k in range(1, HORIZON + 1))
    d["y_vol"] = (s > 0).astype(float)
    d.loc[d["vol_spike"].shift(-HORIZON).isna(), "y_vol"] = np.nan
    d = d.merge(fx, on="month", how="left")
    dd = d.dropna(subset=["y_vol", "ci_teacher", "fx_vol"]).copy()

    res = {"n": len(dd), "n_pos": int(dd["y_vol"].sum())}
    if dd["y_vol"].nunique() < 2 or len(dd) < 10:
        res["note"] = "표본/양성 부족 — 로지스틱 생략"
        return res
    # 표준화
    X = dd[["ci_teacher", "fx_vol"]].copy()
    Xz = (X - X.mean()) / X.std(ddof=0)
    y = dd["y_vol"].astype(int).values
    # 단변량 AUC
    res["auc_teacher_only"] = round(roc_auc_score(y, dd["ci_teacher"]), 3)
    res["auc_fxvol_only"] = round(roc_auc_score(y, dd["fx_vol"]), 3)
    # 로지스틱(정규화로 완전분리 방지)
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(C=1.0, max_iter=1000)
    lr.fit(Xz.values, y)
    res["coef_ci_teacher(표준화)"] = round(float(lr.coef_[0][0]), 3)
    res["coef_fx_vol(표준화)"] = round(float(lr.coef_[0][1]), 3)
    # 부분상관: fx_vol 통제 후 y_vol~ci_teacher
    res["partial_corr(fx통제)"] = round(_partial_corr(
        dd["y_vol"].values, dd["ci_teacher"].values, dd["fx_vol"].values), 3)
    res["raw_corr(y,ci_teacher)"] = round(np.corrcoef(dd["y_vol"], dd["ci_teacher"])[0, 1], 3)
    return res


def _partial_corr(y, x, z) -> float:
    """z를 통제한 x-y 부분상관 = 잔차 상관."""
    def resid(a, b):
        b1 = np.c_[np.ones_like(b), b]
        beta, *_ = np.linalg.lstsq(b1, a, rcond=None)
        return a - b1 @ beta
    ry, rx = resid(np.asarray(y, float), z), resid(np.asarray(x, float), z)
    return float(np.corrcoef(rx, ry)[0, 1])


# ── 4. 대안 proxy ─────────────────────────────────────────────────────────
def alt_proxies(m: pd.DataFrame, px: pd.DataFrame) -> list[str]:
    """(a) 백워데이션 진입 (b) 가격 급등만(상위 P95) → 교사 AUC 재계산."""
    out = []
    d = m.sort_values("month").copy()

    # (a) 백워데이션 진입: 월평균 스프레드>0 를 나쁜 사건으로
    spm = px.groupby("month").agg(spread=("spread", "mean")).reset_index()
    d = d.merge(spm, on="month", how="left")
    d["backwd"] = (d["spread"] > 0).astype(float)
    d.loc[d["spread"].isna(), "backwd"] = np.nan
    _auc_forward(d, "backwd", "교사→백워데이션(향후3m)", out)

    # (b) 급등만: 월 최대 주간 상승수익률이 기준기간 상방 P95 초과
    up = px.copy()
    up["up_ret"] = up["ret"].clip(lower=0)
    upm = up.groupby("month", as_index=False).agg(up_max=("ret", "max"))
    anc = upm[(upm["month"] >= ANCHOR[0]) & (upm["month"] <= ANCHOR[1])]
    thr = anc["up_max"].quantile(0.95)
    upm["surge"] = (upm["up_max"] > thr).astype(float)
    d = d.merge(upm[["month", "up_max", "surge"]], on="month", how="left")
    out.append(f"급등 임계(기준기간 상방수익률 P95) = {thr:.4f}, "
               f"급등월 수 = {int(d['surge'].sum())}")
    _auc_forward(d, "surge", "교사→가격급등만(향후3m)", out)
    return out


def _auc_forward(d: pd.DataFrame, col: str, label: str, out: list) -> None:
    """col의 향후 3개월 내 발생(y) vs ci_teacher AUC."""
    d = d.sort_values("month").copy()
    s = sum(d[col].shift(-k) for k in range(1, HORIZON + 1))
    y = (s > 0).astype(float)
    y[d[col].shift(-HORIZON).isna()] = np.nan
    dd = d.assign(y=y).dropna(subset=["y", "ci_teacher"])
    yy = dd["y"].astype(int)
    if yy.nunique() < 2:
        out.append(f"AUC[{label}] — 단일클래스(평가불가), 기저율 {yy.mean():.2f} (n={len(dd)})")
        return
    a = roc_auc_score(yy, dd["ci_teacher"])
    out.append(f"AUC[{label}] = {a:.3f}  (기저율 {yy.mean():.2f}, 양성 {int(yy.sum())}, n={len(dd)})")


# ── 리포트 작성 ────────────────────────────────────────────────────────────
def main():
    con = duckdb.connect(DB, read_only=True)
    px = load_weekly_price(con)
    fx = load_fx()
    m = load_monthly(con)

    ep = episodes(con, m, px, fx)
    xc, thr = lag_crosscorr(m)
    ctrl = controlled(m, fx)
    alts = alt_proxies(m, px)
    con.close()

    L = []
    L.append("# 구리(CU) proxy 역방향 신호 조사\n")
    L.append("_2026-07-16 · 감사 후속(발주처 안건 5번) · read_only, 기존 자산 무수정_\n")
    L.append("## 배경\n")
    L.append("결과변수 proxy 검증(2026-07-15)에서 '가격 급변'(vol90>기준기간 P95, 향후 3개월) "
             "결과라벨을 교사 위기지수가 강하게 선행 — **LI 0.90 · NI 0.91 · REE 0.99**. "
             "그러나 **구리만 AUC 0.18로 역방향**(교사가 높을수록 급변이 오히려 안 옴).\n")
    L.append("**가설**: 구리는 LME 상장 광종이라 가격 변동성이 수급이 아닌 거시·투기 요인에 "
             "지배되어 교사 수급지수와 탈동조한다.\n")

    L.append("\n## 1. 에피소드 열거 (vol_spike=1 월 ±1개월)\n")
    L.append("CU는 2020~2026 전 기간에서 vol_spike(vol90>기준기간 P95=0.0392)가 **단 3개월**"
             "(2020-04·2020-06·2022-08)뿐이다. 각 ±1개월 신호:\n")
    L.append(ep.to_markdown(index=False))
    L.append("\n\n_주: FX_vol(원달러 13주 변동성)은 원자료가 2021-06부터라 2020 에피소드는 결측. "
             "스프레드>0=백워데이션(현물>선물, 물리적 타이트 신호). 교사CI 높을수록 수급위기._\n")

    L.append("\n### 에피소드 판정\n")
    L.append(
        "| 에피소드 | 시장 국면(공지된 사건) | 신호 근거 | 판정 |\n"
        "|---|---|---|---|\n"
        "| 2020-04 | COVID 수요충격→붕괴 후 부양책 반등 | 교사CI 10.2(**최저**, 수급 안정)인데 "
        "변동성 폭발; 가격 −14.6%→+7.5% V자; 콘탱고(스프레드<0) 유지; 지정학 특이신호 없음 | **거시·투기발** |\n"
        "| 2020-06 | COVID 회복랠리(중국 부양·달러 약세) | 교사CI 25(낮음); 가격 +13.3% 급등 지속; "
        "수급 이탈(import_drop) 없음 | **거시·투기발** |\n"
        "| 2022-08 | Fed 급속긴축·경기침체 우려·달러 초강세 | 교사CI 완만(57~69); 매크로 리스크오프發 "
        "변동성이 주동인. 단 스프레드가 백워데이션(+12→+79)으로 전환돼 **물리적 타이트가 일부 공존** — "
        "이 신호는 vol이 아닌 기간구조로 잡힌다 | **주로 거시발(+수급 일부)** |\n")
    L.append("\n세 에피소드 **모두 거시·투기가 주동인**(2022-08만 물리적 타이트 일부 공존). "
             "알려진 진성 수급 스퀴즈(2024-05 COMEX 숏스퀴즈 등)는 "
             "가격이 급등했으나 13주 변동성 임계를 넘지 못해 vol_spike로 잡히지도 않았다 — "
             "vol_spike 정의 자체가 CU의 수급 이벤트를 놓친다.\n")

    L.append("\n## 2. 역방향의 해부 — 시차 교차상관\n")
    L.append(f"ci_teacher 상위분위 임계(P75) = {thr:.1f}. "
             "1[교사 P75+]_t 와 vol_spike_(t+L) 의 상관(L=선행+/지연−):\n\n")
    L.append(xc.to_markdown(index=False))
    L.append("\n\n동시~±3개월 구간의 상관이 모두 **음(−0.11~−0.13)**이고, 큰 양의 시차(L=+4~+6)에서 "
             "부호가 뒤집히는 것은 2020+ 구간의 vol_spike가 3건뿐이라 나오는 노이즈다. "
             "요컨대 교사 고국면 → 변동성 발생으로 이어지는 **일관된 선행/지연 구조가 없다**. "
             "실제로 향후3m 급변(y_vol=1) 월은 전부 교사CI가 낮은 2020 COVID 국면(CI 10~34)과 "
             "2022 중반(Fed 긴축)에 몰려 있고, 교사CI 최고월(2026-01~03·2021-05·2022-02, CI 97~99)에는 "
             "급변이 전혀 없다. → '교사가 늦게 반응'이 아니라 **아예 다른 국면**(탈동조).\n")

    L.append("\n## 3. 거시 통제 후 재검증 (로지스틱/부분상관)\n")
    L.append("y_vol(향후3m 급변) ~ ci_teacher + fx_vol(원달러 13주 변동성). "
             "FX 가용구간(2021-06~)으로 표본 한정:\n\n```\n")
    for k, v in ctrl.items():
        L.append(f"{k}: {v}\n")
    L.append("```\n")
    L.append("fx_vol(거시 대리변수)을 통제한 뒤에도 ci_teacher의 표준화 계수·부분상관이 여전히 "
             "**음(−)**으로 남는다 — '교사 수급지수는 CU 가격급변을 (역방향으로도) 설명 못함'이 강화된다. "
             "fx_vol 자체의 단변량 AUC(0.59)가 교사(0.46)보다 높아, CU 급변의 예측력은 수급이 아닌 "
             "거시 쪽에 있음을 보인다.\n")
    L.append("\n**중요 뉘앙스**: 이 FX 가용구간(2021-06~) 표본에서 교사 단변량 AUC는 0.46으로 "
             "**0.5 근처(무정보)**다. 원 검증의 극단값 0.18은 상당 부분 **2020 COVID 국면**(교사CI 최저인데 "
             "변동성 최대)에서 나온다 — 즉 CU 교사는 '적극적 역예측기'라기보다 '**가격 변동성과 무관/탈동조**'로 "
             "읽는 것이 정확하며, 2020이 그 탈동조를 극적으로 드러낸 사례다. 어느 해석이든 '대칭 변동성' "
             "결과라벨이 CU에 부적합하다는 결론은 동일하다. CU vol_spike 양성표본이 극소(전 기간 3건)라 "
             "계수는 참고치이며, 결론은 항목 1·2·4의 정성·구조 증거에 무게를 둔다.\n")

    L.append("\n## 4. 대안 proxy 검정 (CU 한정)\n")
    L.append("현행 '대칭 변동성' 대신 수급을 더 직접 반영할 후보 두 가지의 교사 AUC:\n\n```\n")
    for a in alts:
        L.append(a + "\n")
    L.append("```\n")
    L.append("- **(a) 백워데이션 진입**(현물>3M선물): 물리적 타이트의 직접 신호. **AUC 0.55로 0.5를 넘긴 "
             "유일한 정의** — CU proxy를 '변동성'에서 '기간구조'로 교체할 (약한) 근거.\n")
    L.append("- **(b) 가격 급등만**(하락 제외, 상방수익률 P95): 대칭 변동성에서 하락(거시 리스크오프) 성분을 "
             "제거해도 **AUC 0.46으로 여전히 0.5 미달** — 상승 국면도 교사와 정합하지 않는다.\n")

    L.append("\n## 5. 결론 · 권고\n")
    L.append("**(a) 가설: 채택.** 세 vol_spike 에피소드가 전부 거시·투기가 주동인이고(COVID·Fed긴축), "
             "교사CI 최고국면엔 변동성이 없으며(동시~±3개월 음상관, 일관된 선행/지연 구조 부재), "
             "진성 수급 스퀴즈는 대칭 변동성 정의로 포착조차 안 되고, 거시(fx_vol)의 예측력이 교사보다 높다. "
             "CU 가격 변동성은 LME 거시·투기 채널이 지배해 교사 수급지수와 탈동조한다. "
             "AUC 0.18은 '모델 결함'이 아니라 **CU에 한해 '대칭 변동성' 결과라벨이 부적합**하다는 신호다.\n")
    L.append("\n**(b) CU proxy 재정의 권고**:\n")
    L.append("1. CU 결과라벨에서 '대칭 vol90 급변'을 **폐기**한다(교사 AUC 0.18로 역방향, 부적합 확정).\n")
    L.append("2. 대체 후보 중 **CASH-3M 백워데이션 진입**만 AUC 0.55로 0.5를 넘겼다(급등만 0.46은 탈락). "
             "백워데이션을 CU 결과라벨로 채택하되, 개선폭이 미미(0.55)하므로 **단독 선행지표로 과신 금지**.\n")
    L.append("3. 개선폭이 한계적인 만큼, CU는 '가격 기반 수급위기 선행'을 목표로 두기보다 **거시 연동 "
             "모니터링 대상**으로 분리하고, 교사 경보를 기간구조(백워데이션)·재고·수입집중(HHI) 지표와 "
             "**병렬 트랙**으로 함께 해석하도록 운영 설계를 바꾼다.\n")
    L.append("4. 최종 라벨·경보 재정의는 발주처 협의(감사 A-1(a))에 상정 — 본 결과를 근거자료로 첨부.\n")
    L.append("\n**(c) 발주 문서용 경보 해석 주석**:\n")
    L.append("> 구리(CU)의 수급위기 경보는 '가격 변동성' 결과와 역방향으로 나타난다. 이는 모델 오류가 "
             "아니라, 구리 가격 변동성이 수급 요인이 아닌 거시·투기(LME 선물·환율) 요인에 지배되기 "
             "때문이다. 따라서 구리 경보는 가격 변동성이 아닌 기간구조(백워데이션)·수입집중도 지표와 함께 "
             "해석해야 하며, 변동성 급등만으로 수급위기를 판단해서는 안 된다.\n")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))

    # 콘솔 요약
    print("=== CU proxy 조사 완료 ===")
    print(f"에피소드(vol_spike=1): {ep['episode'].nunique()}건 —",
          ", ".join(sorted(ep["episode"].unique())))
    print("\n[시차 교차상관 요약]")
    print(xc.to_string(index=False))
    print("\n[통제 후 재검증]", ctrl)
    print("\n[대안 proxy]")
    for a in alts:
        print("  " + a)
    print(f"\n리포트: {OUT_MD}")


if __name__ == "__main__":
    main()
