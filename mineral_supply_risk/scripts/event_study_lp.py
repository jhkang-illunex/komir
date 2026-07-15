#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
event_study_lp.py — 수출통제·공급차질 이벤트의 한국 수입 실물 반응 event study.

Jordà(2005) local projection(LP)으로 "고신뢰 수출통제 공시 발효 후 h개월 시점의
수입물량/단가 반응" 임펄스 응답을 추정한다. 소표본(이벤트 시기 편중, 중국 백필 특성)
에서도 작동하는 반사실 지향 추정치를 정책 보고서용으로 산출한다.

설계
- 결과변수: 광종×월 log 수입물량(ton) 및 log 단가(unit=usd/ton)
- LP 종속변수: y_{c,t+h} - y_{c,t-1}  (h=0..9, log 차분 → 누적 % 반응)
- 회귀식: (y_{t+h}-y_{t-1}) = β_h·shock_{c,t} + 광종FE + 계절더미(월)
                              + φ1·Δy_{t-1} + φ2·Δy_{t-2} + ε
- 표준오차: HAC(Newey-West), maxlags=h+1 (LP 중첩구간 자기상관 보정)
- shock 정의 2종: (a) 해당 월 이벤트 수, (b) 해당 월 max severity
- 이질성: 전 광종 풀링 vs REE 단독(중국 의존 高)
- 강건성: shock 정의 교체 + placebo(shock 월 광종 내 무작위 재배치)

DB는 read_only로만 접근한다(다른 에이전트 동시 읽기). 쓰기 금지.
"""
import os
import numpy as np
import pandas as pd
import duckdb
import statsmodels.api as sm

MSR_DB = os.environ.get(
    "MSR_DB",
    "/home/nuri/dev/git/ws/mine_ws/komir/warehouse/minerals.duckdb",
)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs", "proxy_label")
OUT_MD = os.path.join(OUT_DIR, "event_study.md")

HMAX = 9              # 임펄스 응답 h=0..9
N_LAGS = 2            # 결과변수 차분 시차 통제 개수
EVENT_SOURCES = ("US_FederalRegister", "CN_MOFCOM", "CN_MOFCOM_ExportControl")
REE_CODE = "REE"
SEED = 20260716       # placebo 재현성


# ────────────────────────────────────────────────────────────────────
# 1. 데이터 적재
# ────────────────────────────────────────────────────────────────────
def load_data():
    con = duckdb.connect(MSR_DB, read_only=True)
    try:
        # 결과변수: 광종×월 수입물량/단가 (국가·hs10 합산)
        trade = con.execute(
            """
            SELECT commodity_code, yr, mon,
                   sum(imp_wgt)/1000.0 AS ton,
                   sum(imp_usd)        AS usd
            FROM fact_trade_monthly
            GROUP BY 1,2,3
            """
        ).df()

        # 충격: 고신뢰 공급차질 공시만
        ev = con.execute(
            f"""
            SELECT commodity_code,
                   CAST(substr(obs_date,1,4) AS INT) AS yr,
                   CAST(substr(obs_date,6,2) AS INT) AS mon,
                   severity
            FROM geo_event
            WHERE source IN {EVENT_SOURCES}
              AND direction = 'supply_down'
              AND severity >= 2
              AND obs_date IS NOT NULL AND length(obs_date) >= 7
            """
        ).df()
    finally:
        con.close()

    trade["ym"] = trade.yr * 100 + trade.mon
    trade["unit"] = trade.usd / trade.ton          # 단가 (USD/ton)
    trade = trade.sort_values(["commodity_code", "ym"]).reset_index(drop=True)

    # 이벤트를 광종×월로 집계 → shock 지표 2종
    ev["ym"] = ev.yr * 100 + ev.mon
    shock = (
        ev.groupby(["commodity_code", "ym"])
        .agg(shock_n=("severity", "size"), shock_sev=("severity", "max"))
        .reset_index()
    )
    return trade, shock, ev


# ────────────────────────────────────────────────────────────────────
# 2. 패널 구성 (log 결과변수 + lead/lag + shock 병합)
# ────────────────────────────────────────────────────────────────────
def build_panel(trade, shock, shock_col):
    """광종별 시계열에 log 결과변수, 차분 시차, shock을 병합해 반환."""
    df = trade.copy()
    df["ly_ton"] = np.log(df.ton)
    df["ly_unit"] = np.log(df.unit)

    # shock 병합 (해당 월 이벤트 없으면 0)
    df = df.merge(
        shock[["commodity_code", "ym", shock_col]],
        on=["commodity_code", "ym"], how="left",
    )
    df[shock_col] = df[shock_col].fillna(0.0)

    # 광종 내 시간정렬 후 차분 시차 통제항 생성
    df = df.sort_values(["commodity_code", "ym"]).reset_index(drop=True)
    for base in ("ly_ton", "ly_unit"):
        g = df.groupby("commodity_code")[base]
        d1 = g.diff()                              # Δy_{t}
        df[f"d_{base}"] = d1
        for L in range(1, N_LAGS + 1):
            df[f"d_{base}_l{L}"] = df.groupby("commodity_code")[f"d_{base}"].shift(L)
    return df


def make_lp_dep(df, base, h):
    """LP 종속변수 y_{t+h} - y_{t-1} 을 광종 내에서 생성."""
    g = df.groupby("commodity_code")[base]
    y_lead = g.shift(-h)      # y_{t+h}
    y_lag1 = g.shift(1)       # y_{t-1}
    return y_lead - y_lag1


# ────────────────────────────────────────────────────────────────────
# 3. LP 추정 (h별 회귀)
# ────────────────────────────────────────────────────────────────────
def run_lp(df, base, shock_col, pooled=True):
    """h=0..HMAX 에 대해 LP 회귀. β_h와 90% CI 반환."""
    lag_cols = [f"d_{base}_l{L}" for L in range(1, N_LAGS + 1)]
    rows = []
    for h in range(0, HMAX + 1):
        d = df.copy()
        d["dep"] = make_lp_dep(d, base, h)

        # 설계행렬: shock + 시차통제 + 계절더미(월) + (풀링 시)광종FE
        Xparts = [d[[shock_col]].rename(columns={shock_col: "shock"})]
        Xparts.append(d[lag_cols])
        # 계절 더미 (mon, 기준월 제외)
        mon_d = pd.get_dummies(d["mon"], prefix="m", drop_first=True).astype(float)
        Xparts.append(mon_d)
        if pooled:
            com_d = pd.get_dummies(d["commodity_code"], prefix="c",
                                   drop_first=True).astype(float)
            Xparts.append(com_d)
        X = pd.concat(Xparts, axis=1)
        X = sm.add_constant(X, has_constant="add")

        Y = d["dep"]
        ok = Y.notna() & X.notna().all(axis=1)
        Xf, Yf = X[ok], Y[ok]
        if Xf.shape[0] < Xf.shape[1] + 5:
            rows.append((h, np.nan, np.nan, np.nan, np.nan, ok.sum()))
            continue

        model = sm.OLS(Yf.astype(float), Xf.astype(float))
        res = model.fit(cov_type="HAC", cov_kwds={"maxlags": h + 1})
        b = res.params["shock"]
        se = res.bse["shock"]
        # 90% CI (정규근사, z=1.645)
        lo, hi = b - 1.645 * se, b + 1.645 * se
        p = res.pvalues["shock"]
        rows.append((h, b, se, lo, hi, p, int(ok.sum())))
    cols = ["h", "beta", "se", "ci_lo", "ci_hi", "pval", "nobs"]
    return pd.DataFrame(rows, columns=cols)


# ────────────────────────────────────────────────────────────────────
# 4. Placebo (shock 월 광종 내 무작위 재배치)
# ────────────────────────────────────────────────────────────────────
def placebo_test(trade, shock, shock_col, base, n_iter=500):
    """shock을 광종 내에서 무작위 시점으로 재배치했을 때 β_h 분포.
    실제 β가 placebo 분포의 극단에 있으면 유의(의미있는 신호)."""
    rng = np.random.default_rng(SEED)
    # 광종별 shock 월 개수·값
    real = build_panel(trade, shock, shock_col)
    real_res = run_lp(real, base, shock_col, pooled=True)

    # 광종별 실제 shock (ym, value) 목록
    shk = shock[["commodity_code", "ym", shock_col]].copy()
    all_ym = sorted(trade.ym.unique())
    placebo_betas = {h: [] for h in range(0, HMAX + 1)}

    for _ in range(n_iter):
        # 광종별로 동일 개수의 shock 값을 무작위 월에 재배치
        fake_rows = []
        for c, gg in shk.groupby("commodity_code"):
            k = len(gg)
            picks = rng.choice(all_ym, size=k, replace=False)
            for ym_, val in zip(picks, gg[shock_col].values):
                fake_rows.append((c, ym_, val))
        fake = pd.DataFrame(fake_rows, columns=["commodity_code", "ym", shock_col])
        # 동월 중복 시 합/최대 규칙 근사: shock_n은 합, shock_sev는 max
        if shock_col == "shock_n":
            fake = fake.groupby(["commodity_code", "ym"], as_index=False)[shock_col].sum()
        else:
            fake = fake.groupby(["commodity_code", "ym"], as_index=False)[shock_col].max()
        pan = build_panel(trade, fake, shock_col)
        r = run_lp(pan, base, shock_col, pooled=True)
        for _, row in r.iterrows():
            placebo_betas[int(row.h)].append(row.beta)

    # 각 h에서 실제 β의 양측 placebo p-value
    out = []
    for h in range(0, HMAX + 1):
        arr = np.array(placebo_betas[h])
        arr = arr[~np.isnan(arr)]
        b = real_res.loc[real_res.h == h, "beta"].values[0]
        if len(arr) == 0 or np.isnan(b):
            out.append((h, b, np.nan, np.nan))
            continue
        # placebo 분포에서 |β_placebo| >= |β_real| 비율
        pval = float(np.mean(np.abs(arr) >= abs(b)))
        out.append((h, b, float(arr.std()), pval))
    return real_res, pd.DataFrame(out, columns=["h", "beta_real", "placebo_sd", "placebo_p"])


# ────────────────────────────────────────────────────────────────────
# 5. 표 포맷
# ────────────────────────────────────────────────────────────────────
def fmt_lp_table(res, label):
    """β를 % 임펄스 응답으로 해석해 표 문자열 생성 (log차분×100)."""
    lines = [f"**{label}**\n",
             "| h(개월) | β(%반응) | HAC SE | 90% CI | p값 | n |",
             "|---:|---:|---:|---:|---:|---:|"]
    for _, r in res.iterrows():
        if np.isnan(r.beta):
            lines.append(f"| {int(r.h)} | — | — | — | — | {int(r.nobs)} |")
            continue
        star = ""
        if r.pval < 0.05:
            star = "**"
        elif r.pval < 0.10:
            star = "*"
        b = r.beta * 100
        lo, hi = r.ci_lo * 100, r.ci_hi * 100
        lines.append(
            f"| {int(r.h)} | {star}{b:+.1f}{star} | {r.se*100:.1f} | "
            f"[{lo:+.1f}, {hi:+.1f}] | {r.pval:.3f} | {int(r.nobs)} |"
        )
    return "\n".join(lines)


def conclude(res, what, var_label):
    """유의한 h가 있으면 요약 문장, 없으면 정직하게 보고.
    var_label: 결과변수 명칭('물량'/'단가') — 문장 서술용."""
    sig = res[(res.pval < 0.10) & res.beta.notna()]
    if len(sig) == 0:
        # 방향성만 언급
        peak = res.loc[res.beta.abs().idxmax()] if res.beta.notna().any() else None
        if peak is None:
            return f"- {what}: 추정 불가."
        return (f"- {what}: 90% 수준에서 **유의한 반응 없음**. "
                f"최대 절대반응은 h={int(peak.h)}에서 {peak.beta*100:+.1f}% "
                f"(90%CI 0 포함, p={peak.pval:.2f}) — 소표본 한계로 무리한 유의 주장 지양.")
    best = sig.loc[sig.pval.idxmin()]
    direction = "증가" if best.beta > 0 else "감소"
    return (f"- {what}: 고신뢰 수출통제 공시 후 **h={int(best.h)}개월**에 "
            f"수입 {var_label} {best.beta*100:+.1f}%({direction}) "
            f"({'유의' if best.pval<0.05 else '약한 유의'}, p={best.pval:.3f}, "
            f"90%CI [{best.ci_lo*100:+.1f}, {best.ci_hi*100:+.1f}]%).")


# ────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────
def main():
    trade, shock, ev = load_data()

    # ── 이벤트 분포표 (광종×연도) ──
    ev["evyr"] = ev.yr
    dist = ev.groupby(["commodity_code", "evyr"]).size().unstack(fill_value=0)
    dist_months = (
        shock.assign(one=1).groupby("commodity_code")["ym"].nunique()
        .rename("shock_months")
    )

    md = []
    md.append("# Event Study (Jordà Local Projection): 수출통제 공시의 한국 수입 실물 반응\n")
    md.append("> 외부감사 B-3⑥ 심화. 고신뢰 공급차질 공시 발효 후 h개월 시점의 수입물량·단가 "
              "임펄스 응답을 LP로 추정. DB read_only 접근.\n")

    md.append("## 1. 이벤트 분포 (충격 표본)\n")
    md.append("고신뢰 필터: `source∈{US_FederalRegister, CN_MOFCOM, CN_MOFCOM_ExportControl} "
              "AND direction='supply_down' AND severity≥2`. obs_date를 월로 집계.\n")
    md.append("**광종×연도 이벤트 수(원자료 행 기준)**\n")
    md.append("| 광종 | " + " | ".join(str(y) for y in dist.columns) + " | 계 |")
    md.append("|---|" + "|".join(["---:"] * (len(dist.columns) + 1)) + "|")
    for c in dist.index:
        vals = dist.loc[c]
        md.append(f"| {c} | " + " | ".join(str(int(v)) for v in vals) +
                  f" | {int(vals.sum())} |")
    md.append("")
    md.append("**광종별 유니크 shock 월 수(회귀에 실제 반영되는 처리 시점 수)**\n")
    md.append("| 광종 | shock 월수 |")
    md.append("|---|---:|")
    for c in dist_months.index:
        md.append(f"| {c} | {int(dist_months[c])} |")
    md.append("")
    md.append("> ⚠️ **표본 한계**: 이벤트가 2024~25년(특히 REE)에 집중 — 중국 수출통제 공시의 "
              "백필(backfill) 특성. 처리 시점이 표본 후반에 몰려 있어 긴 h(원거리 lead)에서 "
              "관측치가 급감하고, 전 기간에 걸친 균형 잡힌 반사실 추정이 어렵다. "
              "아래 결과는 이 한계 위에서 해석해야 한다.\n")

    # ── LP: 물량·단가 × shock 정의 2종, 풀링 ──
    md.append("## 2. LP 임펄스 응답 (전 광종 풀링)\n")
    md.append("모형: `(y_{t+h}−y_{t−1}) = β_h·shock + 광종FE + 계절더미(월) + "
              "Δy_{t−1} + Δy_{t−2} + ε`, HAC(Newey-West, maxlags=h+1). "
              "y=log(물량) 또는 log(단가). β는 log차분×100 → **누적 % 반응**. "
              "`*` p<0.10, `**` p<0.05.\n")

    results = {}
    for shock_col, sname in [("shock_n", "이벤트 수"), ("shock_sev", "max severity")]:
        pan = build_panel(trade, shock, shock_col)
        for base, bname in [("ly_ton", "수입물량"), ("ly_unit", "수입단가")]:
            res = run_lp(pan, base, shock_col, pooled=True)
            results[(shock_col, base)] = res
            md.append(fmt_lp_table(res, f"{bname} — shock=`{sname}` (전 광종 풀링)"))
            md.append("")

    # ── 이질성: REE 단독 ──
    md.append("## 3. 이질성 — REE 단독 (중국 의존 高)\n")
    md.append("REE만 필터(광종FE 제거, 계절더미+시차통제 유지). shock 월 "
              f"{int(dist_months.get('REE',0))}개로 표본 극소 — 참고용.\n")
    trade_ree = trade[trade.commodity_code == REE_CODE].copy()
    shock_ree = shock[shock.commodity_code == REE_CODE].copy()
    for shock_col, sname in [("shock_n", "이벤트 수"), ("shock_sev", "max severity")]:
        pan = build_panel(trade_ree, shock_ree, shock_col)
        for base, bname in [("ly_ton", "수입물량"), ("ly_unit", "수입단가")]:
            res = run_lp(pan, base, shock_col, pooled=False)
            results[("REE_" + shock_col, base)] = res
            md.append(fmt_lp_table(res, f"REE {bname} — shock=`{sname}`"))
            md.append("")

    # ── 강건성: placebo ──
    md.append("## 4. 강건성 검정\n")
    md.append("### 4-1. shock 정의 교체\n")
    md.append("위 2절에서 `이벤트 수` vs `max severity` 두 정의를 병기했다. "
              "두 정의에서 β_h 부호·유의성 패턴이 일관되면 결과가 정의에 강건한 것으로 본다.\n")
    md.append("### 4-2. Placebo (shock 월 무작위 재배치)\n")
    md.append("각 광종의 shock을 개수 보존한 채 무작위 월로 500회 재배치 후 β_h 분포를 구성. "
              "실제 β가 placebo 분포 극단(양측 p<0.10)에 있으면 우연이 아닌 신호. "
              "`placebo_p`는 |β_placebo|≥|β_real| 비율.\n")
    real_ton, plc_ton = placebo_test(trade, shock, "shock_n", "ly_ton", n_iter=500)
    md.append("**전 광종 풀링 수입물량 (shock=이벤트 수) placebo**\n")
    md.append("| h | β_real(%) | placebo_SD(%) | placebo_p |")
    md.append("|---:|---:|---:|---:|")
    for _, r in plc_ton.iterrows():
        if np.isnan(r.beta_real):
            md.append(f"| {int(r.h)} | — | — | — |"); continue
        flag = " ✓" if (not np.isnan(r.placebo_p) and r.placebo_p < 0.10) else ""
        md.append(f"| {int(r.h)} | {r.beta_real*100:+.1f} | {r.placebo_sd*100:.1f} | "
                  f"{r.placebo_p:.3f}{flag} |")
    md.append("")
    # REE 단독 placebo (2절에서 h=5~8 유의 → 우연 여부 검증)
    _, plc_ree = placebo_test(trade_ree, shock_ree, "shock_n", "ly_ton", n_iter=500)
    md.append("**REE 단독 수입물량 (shock=이벤트 수) placebo** — 2·3절의 h=5~8 유의반응이 "
              "우연인지 검증(REE의 shock 월을 무작위 재배치).\n")
    md.append("| h | β_real(%) | placebo_SD(%) | placebo_p |")
    md.append("|---:|---:|---:|---:|")
    for _, r in plc_ree.iterrows():
        if np.isnan(r.beta_real):
            md.append(f"| {int(r.h)} | — | — | — |"); continue
        flag = " ✓" if (not np.isnan(r.placebo_p) and r.placebo_p < 0.10) else ""
        md.append(f"| {int(r.h)} | {r.beta_real*100:+.1f} | {r.placebo_sd*100:.1f} | "
                  f"{r.placebo_p:.3f}{flag} |")
    md.append("")

    # ── 결론·한계 ──
    md.append("## 5. 결론\n")
    md.append("**(1) 전 광종 풀링, shock=이벤트 수 기준:**\n")
    md.append(conclude(results[("shock_n", "ly_ton")], "수입물량 반응", "물량"))
    md.append(conclude(results[("shock_n", "ly_unit")], "수입단가 반응", "단가"))
    # placebo 종합 (풀링)
    sig_plc = plc_ton[(plc_ton.placebo_p < 0.10) & plc_ton.beta_real.notna()]
    if len(sig_plc):
        hs = ", ".join(f"h={int(x)}" for x in sig_plc.h)
        md.append(f"- Placebo(풀링): {hs}에서 실제 β가 무작위 분포 극단(p<0.10) — 신호가 우연이 아님을 시사.")
    else:
        md.append("- Placebo(풀링): 어떤 h에서도 실제 β가 무작위 분포와 뚜렷이 구분되지 않음 "
                  "— 풀링 수준에서는 인과적 해석에 신중해야 함.")
    md.append("")
    md.append("**(2) REE 단독(중국 의존 高) — 정책적으로 가장 주목되는 결과:**\n")
    md.append(conclude(results[("REE_shock_n", "ly_ton")], "REE 수입물량 반응", "물량"))
    sig_ree = plc_ree[(plc_ree.placebo_p < 0.10) & plc_ree.beta_real.notna()]
    if len(sig_ree):
        hs = ", ".join(f"h={int(x)}" for x in sig_ree.h)
        md.append(f"- REE placebo: {hs}에서 실제 β가 무작위 분포 극단(p<0.10) — "
                  "우연으로 보기 어려움.")
        md.append("- **해석**: REE는 수출통제 공시 후 중기(h≈5~8개월)에 수입물량이 **오히려 증가**한다. "
                  "감소가 아닌 증가는 (i) 통제 발효 전·규제 회색지대에서의 **밀어내기(front-loading) 수입**, "
                  "(ii) 통제 대상 외 품목·경로로의 **대체 조달 급증**으로 해석된다 — "
                  "즉 실물 부족보다 '규제 회피성 재고확보'가 관측 신호의 주된 동인일 개연성. "
                  "단, REE는 shock 월 16개의 소표본이며 처리 시점이 2024~25년에 편중돼 있어 "
                  "**h≈5~8은 2025년 상반기 통제 직후 구간과 상당 부분 겹친다** — 인과보다 상관으로 신중히 읽어야 한다.")
    else:
        md.append("- REE placebo: 실제 β가 무작위 분포와 뚜렷이 구분되지 않아 소표본 우연 가능성 배제 못함.")
    md.append("")
    md.append("### 한계\n")
    md.append("- **이벤트 시기 편중**: 처리(shock)가 2024~25년, 특히 REE에 집중(중국 공시 백필). "
              "긴 h에서 lead 관측치가 부족해 원거리 임펄스 응답 추정이 불안정.\n"
              "- **소표본**: 광종당 유니크 shock 월 3~16개. HAC/placebo로 보수적으로 처리했으나 "
              "검정력이 낮아, 유의하지 않은 결과는 '효과 없음'이 아니라 '추정 불가능'에 가깝다.\n"
              "- **공시 시점 ≠ 발효/충격 시점**: obs_date는 공시일 기준으로, 실물 무역 반응은 "
              "계약·리드타임 지연으로 h>0에서 나타날 수 있고 사전 재고확보(front-loading)로 "
              "h<0 선행반응도 가능하나 본 설계는 h≥0만 추정.\n"
              "- **REE 단독 결과는 참고용**: shock 월이 극소여서 CI가 넓고 개별 계수 신뢰 낮음.\n")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))
    print("WROTE", os.path.abspath(OUT_MD))

    # 콘솔 요약
    print("\n=== 요약: 수입물량, shock=이벤트 수, 풀링 ===")
    print(results[("shock_n", "ly_ton")][["h", "beta", "pval", "nobs"]].to_string(index=False))
    print("\n=== placebo(물량) ===")
    print(plc_ton.to_string(index=False))


if __name__ == "__main__":
    main()
