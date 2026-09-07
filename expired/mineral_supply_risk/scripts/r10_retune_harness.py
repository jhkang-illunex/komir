# -*- coding: utf-8 -*-
"""R10 표준 재검정 하네스 — 신규 데이터 등록→피처화→검정→리포트 원커맨드
(2026-07-25, "데이터 올 때마다 재튜닝" 고충의 구조적 해법).

사용법:
  MSR_DB=<warehouse> python -m scripts.r10_retune_harness            # 전체
  MSR_DB=<warehouse> python -m scripts.r10_retune_harness --quick    # 스크리닝만

설계(주말 탐색 R1~R9에서 확립된 원칙의 코드화):
  1. SERIES_SPEC에 신규 시리즈를 한 줄 등록(원천 테이블·광종 매핑·지연일·컷 플래그)
     → 표준 시간구조 피처(yoy·chg3·z24 — 승자 방법론)로 자동 가공, as-of 누수방지.
  2. 진단 Δ 프레임 스크리닝(Logistic — 빠름): 광종축(해당 광종 단독)+풀링,
     챔피언 파레토(QWK·chg·FAR) 비교 → 유망 후보만 부트스트랩(CI 하한>0 기준).
  3. 유망 후보는 보팅 챔피언 프레임(Bagging×2 소프트보팅)에서 확정 검정.
  4. 예측 exog 검정: XT 신챔피언 구성에 후보 추가, 6오리진 스크리닝 →
     ΔWAPE>0.005만 18오리진 부트스트랩.
  5. 판정 자동 분류: 채택후보(유의)/방향긍정(보류)/기각 + 커버리지 교란 플래그
     (시작 2018+ 또는 꼬리 정지 시 자동 경고 — CLN·COT2 교훈).

⚠ 채택은 자동화하지 않는다 — 하네스는 검정·분류까지, 채택 결정과 이웃 강건성·
재발행 강건성 확인은 사람이 리포트를 보고 한다(E4·재발행 교훈).
"""
from __future__ import annotations
import argparse
import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                                # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import (                          # noqa: E402
    add_dynamics, e2_delta_classifier,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F, _asof_join  # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                      # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                       # noqa: E402
    build_pmi, PMI_F, bootstrap_diff,
)
from scripts.diag_refine1 import build_refined                            # noqa: E402

# ─────────────────────────────────────────────────────────────────────
# 신규 시리즈 등록부 — 새 데이터가 오면 여기 한 줄 추가가 전부다.
#   (name, table, key, cc_map, lag_days, note)
#   table: 'ind'(fact_indicator.indicator) | 'ser'(fact_series.series_code)
#   cc_map: {광종: 원천키} — 광종축 피처로 광종별 as-of 조인
#   lag_days: 발표 지연 보수치(as-of)
# ─────────────────────────────────────────────────────────────────────
SERIES_SPEC = [
    # Tier3 (2026-07-25 수집)
    ("li_sam", "ind", {"LI": "CL_LI_EXPORT_WGT"}, 75, "칠레 LI(남미축1)"),
    ("li_ar",  "ind", {"LI": "AR_LI_EXPORT_WGT"}, 120, "아르헨 LI(남미축2)"),
    ("ni_ph",  "ind", {"NI": "PH_NI_EXPORT_WGT"}, 120, "필리핀 NI 광석(대체공급)"),
    ("ree_my", "ind", {"REE": "MY_REE_EXPORT_WGT"}, 90, "말레이 REE(비중국 정제)"),
    ("jp_ni",  "ind", {"NI": "JP_NI_IMPORT_WGT"}, 60, "일본 NI 수입(아시아 수요)"),
    ("uscu_p", "ind", {"CU": "CU_US_MINE_PROD"}, 60, "USGS 미 광산생산"),
    ("uscu_s", "ind", {"CU": "CU_US_STOCK_T"}, 60, "USGS 미 총재고"),
    ("comex",  "ind", {"CU": "CU_COMEX_STOCK_T"}, 60, "COMEX 재고(USGS 우회)"),
    # Tier4 (2026-07-25 수집)
    ("cn_cu",  "ind", {"CU": "CN_CU_IMPORT_WGT"}, 75, "중국 CU 수입(⚠2024-12컷)"),
    ("cn_ni",  "ind", {"NI": "CN_NI_IMPORT_WGT"}, 75, "중국 NI 수입(⚠컷)"),
    ("cn_li",  "ind", {"LI": "CN_LI_IMPORT_WGT"}, 75, "중국 LI 수입(⚠컷)"),
    ("jp_cu",  "ind", {"CU": "JP_CU_IMPORT_WGT"}, 60, "일본 CU 수입"),
    ("jp_co",  "ind", {"CO": "JP_CO_IMPORT_WGT"}, 60, "일본 CO 수입"),
    ("in_cu",  "ind", {"CU": "IN_CU_IMPORT_WGT"}, 120, "인도 CU 수입"),
    ("ca_co",  "ind", {"CO": "CA_CO_EXPORT_WGT"}, 90, "캐나다 CO 수출"),
    ("no_ni",  "ind", {"NI": "NO_NI_EXPORT_WGT"}, 90, "노르웨이 NI 수출"),
    ("us_ree", "ind", {"REE": "US_REE_EXPORT_WGT"}, 60, "미국 REE 수출"),
    ("br_li",  "ind", {"LI": "BR_LI_EXPORT_WGT"}, 120, "브라질 LI 수출"),
    ("de_ni",  "ind", {"NI": "DE_NI_IMPORT_WGT"}, 75, "독일 NI 수입(EU 수요)"),
    ("de_co",  "ind", {"CO": "DE_CO_IMPORT_WGT"}, 75, "독일 CO 수입"),
    ("de_li",  "ind", {"LI": "DE_LI_IMPORT_WGT"}, 75, "독일 LI 수입"),
    ("icsg_p", "ind", {"CU": "CU_WORLD_MINE_PROD"}, 75, "ICSG 세계 광산생산(⚠축적형·짧음)"),
    ("icsg_u", "ind", {"CU": "CU_WORLD_USAGE"}, 75, "ICSG 세계 사용(⚠짧음)"),
    ("ng",   "ser", {"*": "NG_HENRYHUB_M"}, 35, "헨리허브 가스(에너지비)"),
    ("cli_cn", "ser", {"*": "OECD_CLI_CN_M"}, 45, "OECD 중국 CLI"),
    ("cli_kr", "ser", {"*": "OECD_CLI_KR_M"}, 45, "OECD 한국 CLI"),
    ("cn_el",  "ser", {"*": "CN_ELEC_CONS_M"}, 45, "중국 전력소비"),
    ("ksh_el", "ser", {"*": "KSH_ELEC_M"}, 40, "한국 전자부품 출하"),
    ("ksh_au", "ser", {"*": "KSH_AUTO_M"}, 40, "한국 자동차 출하"),
    ("bill_am", "ser", {"*": "WSTS_BILL_AM_M"}, 40, "WSTS Americas"),
    ("bill_eu", "ser", {"*": "WSTS_BILL_EU_M"}, 40, "WSTS Europe"),
    ("bill_jp", "ser", {"*": "WSTS_BILL_JP_M"}, 40, "WSTS Japan"),
    # 해외기관 직접 수집 (2026-07-28, collect_intl_agency_feeds — 발주처 확장 요청)
    ("pe_cu_x", "ind", {"CU": "PE_CU_EXPORT_WGT"}, 75, "페루 CU 수출물량(BCRP·SUNAT)"),
    ("pe_cu_p", "ind", {"CU": "PE_CU_PROD_MINE"}, 75, "페루 CU 광산생산(BCRP·MINEM)"),
    ("au_cu",  "ind", {"CU": "AU_CU_EXPORT_KAUD"}, 75, "호주 동광 수출액(ABS)"),
    ("au_ni",  "ind", {"NI": "AU_NI_EXPORT_KAUD"}, 75, "호주 니켈광 수출액(ABS)"),
    ("ph_psa", "ind", {"NI": "PH_NI_EXPORT_WGT_PSA"}, 75,
     "필리핀 NI(PSA·BOC 직접 — ni_ph 원천중복, 대체 후보)"),
    ("gacc_cu", "ind", {"CU": "CN_CU_ORE_IMPORT_QTY_GACC"}, 30,
     "중국 동정광 수입(GACC 월보, 래그~3주 ⚠2018+)"),
    ("gacc_cuw", "ind", {"CU": "CN_CU_UNWROUGHT_IMPORT_QTY_GACC"}, 30,
     "중국 미가공동 수입(GACC ⚠2018+)"),
    ("gacc_ree", "ind", {"REE": "CN_REE_EXPORT_QTY_GACC"}, 30,
     "중국 REE 수출(GACC — 수출통제 직접축 ⚠2018+)"),
    # 2026-07-29 신규(ARCA·BPS·Census — 발주처 확장 요청 키 발급분)
    ("ar_li_arca", "ind", {"LI": "AR_LI_EXPORT_WGT_ARCA"}, 60,
     "아르헨 LI(ARCA 관세청 직접 — li_ar 원천중복, 2019-01~ 대체후보)"),
    ("id_ni",  "ind", {"NI": "ID_NI_EXPORT_BPS_WGT"}, 75,
     "인니 NI 수출(BPS 관세청 직접, 니켈전용챕터 청정, 2014-01~ — 기존 ID_NI_EXPORT_WGT는 UN_COMTRADE라 이름충돌 방지로 _BPS 접미)"),
    ("id_co_um", "ind", {"CO": "ID_CO_UNWROUGHT_EXPORT_BPS_WGT"}, 75,
     "인니 CO 미가공수출(BPS ⚠2024-08~ 단표본)"),
    ("id_li_carb", "ind", {"LI": "ID_LI_CARBONATE_EXPORT_BPS_WGT"}, 75,
     "인니 LI 탄산리튬수출(BPS ⚠산발 17건)"),
    ("us_ni",  "ind", {"NI": "US_NI_UNWROUGHT_IMPORT_VAL"}, 60,
     "미 NI 수입액(Census, CBP대체, 2013-01~)"),
    ("us_co",  "ind", {"CO": "US_CO_IMPORT_VAL"}, 60, "미 CO 수입액(Census)"),
    ("us_co_dut", "ind", {"CO": "US_CO_IMPORT_DUT"}, 60,
     "미 CO 관세부담액(Census, 정책리스크 신호)"),
    ("us_li",  "ind", {"LI": "US_LI_CARBONATE_IMPORT_VAL"}, 60,
     "미 LI 수입액(Census)"),
    ("us_ree_imp", "ind", {"REE": "US_REE_COMPOUND_IMPORT_VAL"}, 60,
     "미 REE화합물 수입액(Census) — ⚠기존 us_ree(REE 수출)와 name 구분"),
    ("us_ree_dut", "ind", {"REE": "US_REE_COMPOUND_IMPORT_DUT"}, 60,
     "미 REE 관세부담액(Census, 301조 신호 — 실효세율 60%대 실측)"),
    ("us_cu",  "ind", {"CU": "US_CU_REFINED_IMPORT_VAL"}, 60,
     "미 CU 정련동 수입액(Census)"),
    # 2026-07-30: tier2 검정 공백 발견 후 등록(칠레 CU·DRC CO — 07-25/07-28
    # 부터 수집만 하고 SERIES_SPEC 미등록 상태였음)
    ("cl_cu_mine", "ind", {"CU": "CL_CU_PROD_MINE"}, 90,
     "칠레 CU 광산생산(COCHILCO, 세계 최대 생산국, 2015-01~)"),
    ("cl_cu_ref", "ind", {"CU": "CL_CU_PROD_REF"}, 90,
     "칠레 CU 정련생산(COCHILCO, 2015-01~)"),
    ("cd_co", "ind", {"CO": "CN_CO_IMPORT_COD_WGT"}, 75,
     "DRC CO(중국 수입 미러 — DRC 자체 미보고, 세계 최대 생산국, 2016-01~2024-12)"),
]
STALE_DAYS = 200          # 꼬리 정지 경고 임계
MIN_START = "2018-07-01"  # 이보다 늦게 시작하면 커버리지 교란 플래그


def _z(s, w=24, mp=12):
    return (s - s.rolling(w, min_periods=mp).mean()) \
        / s.rolling(w, min_periods=mp).std().replace(0, np.nan)


def build_derived_features(db: str, panel: pd.DataFrame):
    """신규 데이터로만 가능해진 파생 피처(2026-07-25 신규 엔지니어링):
      supdiv : 공급국 다변화 — 광종별 복수 공급 흐름의 월간 점유율 HHI
               (LI: 칠레+아르헨+호주+브라질 / NI: 인니+필리핀+노르웨이) —
               집중도 상승 = 공급 리스크. z24·chg3.
      fgap   : 수요-공급 흐름 갭 — (주요 수입국 합 − 주요 수출국 합)의 z24
               (양수 = 초과수요/재고소진 신호). NI·LI.
    전부 as-of(구성 흐름의 최장 지연 적용)."""
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT commodity_code cc, indicator,
        CAST(obs_date AS DATE) obs_date, CAST(val AS DOUBLE) val
        FROM fact_indicator WHERE indicator LIKE '%_WGT'""").df()
    con.close()
    ind["obs_date"] = pd.to_datetime(ind["obs_date"])
    piv = ind.pivot_table(index="obs_date", columns="indicator", values="val")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")
    meta = {}

    GROUPS = {
        ("LI", "supdiv_li"): (["CL_LI_EXPORT_WGT", "AR_LI_EXPORT_WGT",
                               "AU_LI_EXPORT_WGT", "BR_LI_EXPORT_WGT"], "hhi", 120),
        ("NI", "supdiv_ni"): (["ID_NI_EXPORT_WGT", "PH_NI_EXPORT_WGT",
                               "NO_NI_EXPORT_WGT"], "hhi", 120),
        ("NI", "fgap_ni"): ((["CN_NI_IMPORT_WGT", "JP_NI_IMPORT_WGT",
                              "DE_NI_IMPORT_WGT"],
                             ["ID_NI_EXPORT_WGT", "PH_NI_EXPORT_WGT",
                              "NO_NI_EXPORT_WGT"]), "gap", 120),
        ("LI", "fgap_li"): ((["CN_LI_IMPORT_WGT", "DE_LI_IMPORT_WGT"],
                             ["CL_LI_EXPORT_WGT", "AR_LI_EXPORT_WGT",
                              "AU_LI_EXPORT_WGT", "BR_LI_EXPORT_WGT"]), "gap", 120),
    }
    for (cc, name), (spec, kind, lag) in GROUPS.items():
        try:
            if kind == "hhi":
                cols = [c for c in spec if c in piv.columns]
                if len(cols) < 2:
                    continue
                sub = piv[cols].dropna(how="all")
                sh = sub.div(sub.sum(axis=1), axis=0)
                base = (sh ** 2).sum(axis=1)
            else:
                imp = [c for c in spec[0] if c in piv.columns]
                expo = [c for c in spec[1] if c in piv.columns]
                if not imp or not expo:
                    continue
                base = piv[imp].sum(axis=1) - piv[expo].sum(axis=1)
            f = pd.DataFrame({"obs_date": base.index})
            f[f"{name}_z24"] = _z(base.reset_index(drop=True))
            f[f"{name}_chg3"] = base.reset_index(drop=True).pct_change(3) \
                if kind == "hhi" else base.reset_index(drop=True).diff(3)
            f["commodity_code"] = cc
            f["avail_date"] = f["obs_date"] + pd.Timedelta(days=lag)
            f = f.replace([np.inf, -np.inf], np.nan)
            feats = [f"{name}_z24", f"{name}_chg3"]
            panel = _asof_join(panel, f, feats, by_commodity=True)
            meta[name] = {"feats": feats, "ccs": [cc], "flags": [],
                          "note": f"파생({kind})"}
        except Exception as e:
            print(f"  [warn] 파생 {name} 실패({type(e).__name__})")
    return panel, meta


def build_new_features(db: str, panel: pd.DataFrame):
    """SERIES_SPEC 전체를 표준 시간구조 피처로 가공해 패널에 as-of 병합.
    반환: (panel, {name: {"feats": [...], "ccs": [...], "flags": [...]}})"""
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT commodity_code, indicator, CAST(obs_date AS DATE)
        obs_date, CAST(val AS DOUBLE) val FROM fact_indicator ORDER BY 2,3""").df()
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date,
        CAST(val AS DOUBLE) val FROM fact_series ORDER BY 1,2""").df()
    con.close()
    for d in (ind, ser):
        d["obs_date"] = pd.to_datetime(d["obs_date"])
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")
    meta = {}
    for name, table, cc_map, lag, note in SERIES_SPEC:
        feats = [f"{name}_yoy", f"{name}_chg3", f"{name}_z24"]
        frames, flags, ccs = [], [], []
        for cc, key in cc_map.items():
            x = (ind[ind["indicator"] == key] if table == "ind"
                 else ser[ser["series_code"] == key]).sort_values("obs_date").copy()
            if len(x) < 24:
                flags.append(f"{key}: {len(x)}행 — 표본부족 제외")
                continue
            start, end = x["obs_date"].min(), x["obs_date"].max()
            if str(start.date()) > MIN_START:
                flags.append(f"커버리지교란 의심(시작 {start.date()})")
            if (pd.Timestamp.now() - end).days > STALE_DAYS:
                flags.append(f"꼬리정지(최신 {end.date()})")
            v = x["val"]
            x[f"{name}_yoy"] = v.pct_change(12)
            x[f"{name}_chg3"] = v.pct_change(3)
            x[f"{name}_z24"] = _z(v)
            x["avail_date"] = x["obs_date"] + pd.Timedelta(days=lag)
            if cc == "*":
                frames.append(("*", x))
            else:
                x["commodity_code"] = cc
                frames.append((cc, x))
                ccs.append(cc)
        if not frames:
            continue
        if frames[0][0] == "*":
            x = frames[0][1].replace([np.inf, -np.inf], np.nan)
            panel = _asof_join(panel, x, feats, by_commodity=False)
            ccs = ["*"]
        else:
            allx = pd.concat([f for _, f in frames], ignore_index=True) \
                .replace([np.inf, -np.inf], np.nan)
            panel = _asof_join(panel, allx, feats, by_commodity=True)
        meta[name] = {"feats": feats, "ccs": ccs, "flags": flags, "note": note}
    return panel, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="스크리닝만(부트스트랩 생략)")
    args = ap.parse_args()
    db = os.environ["MSR_DB"]
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    print(f"패널 종점: {df['obs_date'].max().date()}")
    df = add_dynamics(df); df = build_aux(db, df)
    df = exch.build_cninv(db, df); df = build_pmi(db, df); df = build_refined(db, df)
    from scripts.diagnosis_tier1_eval import build_tier1
    df = build_tier1(db, df)          # CU 채택 동작점(CNOI) 기준선용
    df, meta = build_new_features(db, df)
    df, meta2 = build_derived_features(db, df)
    meta.update(meta2)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    CHAMP = nolag + INV_F + exch.CNINV_F + PMI_F
    # 광종별 기준선 = 각 광종의 실제 채택 동작점(2026-07-25 정정 — 풀링 피처를
    # 광종 단독에 쓰면 결측 탓에 약한 기준선이 되어 가짜 유의 발생, 실측 교훈)
    from scripts.diagnosis_tier1_eval import CNOI_F
    PER_CC_CHAMP = {"CU": nolag + CNOI_F,
                    "NI": nolag + INV_F + exch.CNINV_F,
                    "LI": nolag, "CO": nolag, "REE": nolag}
    champ = e2_delta_classifier(df, CHAMP, "Logistic")
    print(f"챔피언(스크리닝 프레임): QWK {champ['QWK']:.4f} chg "
          f"{champ['chg_acc']:.4f} FAR {champ['FAR']:.4f}\n")

    L = ["# R10 표준 재검정 리포트\n",
         f"패널 종점 {df['obs_date'].max().date()} · 스크리닝=Logistic Δ프레임 · "
         f"챔피언 QWK {champ['QWK']:.4f}/chg {champ['chg_acc']:.4f}/"
         f"FAR {champ['FAR']:.4f}\n",
         "| 그룹 | 축 | QWK | chg | FAR | 플래그 | 판정 |", "|---|---|---|---|---|---|---|"]
    promising = []
    rng = np.random.default_rng(0)
    for name, m in meta.items():
        flags = "; ".join(m["flags"]) or "—"
        cov = df[m["feats"][0]].notna().mean()
        if cov < 0.05:
            L.append(f"| {name}({m['note']}) | — | — | — | — | 커버리지 {cov:.0%} | 데이터없음 |")
            print(f"{name}: 데이터 없음(커버리지 {cov:.0%}) — 수집 확인 필요")
            continue
        # 광종축: 해당 광종 단독 / 공통(*): 풀링
        if m["ccs"] == ["*"]:
            r = e2_delta_classifier(df, CHAMP + m["feats"], "Logistic")
            axis = "풀링"
            base = champ
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
        verdict = "유망→부트스트랩" if better else "기각(스크리닝)"
        if better:
            promising.append((name, m, axis))
        L.append(f"| {name}({m['note']}) | {axis} | {r['QWK']:.4f} | "
                 f"{r['chg_acc']:.4f} | {r['FAR']:.4f} | {flags} | {verdict} |")
        print(f"{name} [{axis}]: QWK {r['QWK']:.4f} chg {r['chg_acc']:.4f} "
              f"FAR {r['FAR']:.4f} | {verdict} | {flags}")

    if not args.quick and promising:
        L.append("\n## 유망 후보 부트스트랩(vs 챔피언)\n")
        for name, m, axis in promising:
            dfx = df if axis == "풀링" else \
                df[df["commodity_code"] == axis].reset_index(drop=True)
            bf = CHAMP if axis == "풀링" else PER_CC_CHAMP.get(axis, nolag)
            b = bootstrap_diff(dfx, bf, bf + m["feats"], nolag, rng)
            line = (f"{name} [{axis}]: QWK CI [{b['qwk_ci'][0]:+.4f},"
                    f"{b['qwk_ci'][1]:+.4f}] P={b['qwk_p']:.3f} | chg CI "
                    f"[{b['chg_ci'][0]:+.3f},{b['chg_ci'][1]:+.3f}] P={b['chg_p']:.3f}")
            adopt = (b["qwk_ci"][0] > 0) or (b["chg_ci"][0] > 0 and b["qwk_ci"][0] > -0.005)
            line += " → **채택후보(유의)**" if adopt else " → 방향긍정 보류"
            L.append(f"- {line}")
            print(line)

    # ═══ 예측(exog) 스크리닝 — XT 신챔피언 구성 + 신규 월간 exog ═══
    if not args.quick:
        L.append("\n## 예측 exog 스크리닝(XT 신챔피언 대비, 6오리진)\n")
        L.append("| 후보 | ton | unit | 판정 |")
        L.append("|---|---|---|---|")
        fres = forecast_screen(db)
        for name, wt, wu, base_t, base_u, verdict in fres:
            L.append(f"| {name} | {wt:.4f} | {wu:.4f} | {verdict} |")
        if fres:
            L.append(f"\n기준(XT 신챔피언): ton {fres[0][3]:.4f} / unit {fres[0][4]:.4f}"
                     f" — ΔWAPE>0.005 후보만 18오리진 확정 검정 대상")

    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "r10_retune_report.md")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[r10] 리포트 → {path}")
    print("주의: 채택 확정 전 이웃 강건성·재발행 강건성·보팅 프레임 확정 검정 필요(수동)")


def forecast_screen(db: str):
    """신규 월간 시리즈를 XT 신챔피언 구성에 추가해 6오리진 WAPE 스크리닝.
    exog는 참조월+발표지연을 시프트로 보수 반영(기존 exog eval 규약)."""
    import msr.models.forecast_unit as fu
    from scripts.midas_eval import build_midas_panel, LAMBDAS
    from sklearn.ensemble import ExtraTreesRegressor
    from scripts.forecast_exog_eval import ORIGINS

    fdf = fu.build_panel(db)
    fdf, _ = build_midas_panel(db, fdf)
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT indicator, CAST(obs_date AS DATE) obs_date,
        CAST(val AS DOUBLE) val, commodity_code FROM fact_indicator""").df()
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date,
        CAST(val AS DOUBLE) val FROM fact_series""").df()
    con.close()
    for d in (ind, ser):
        d["obs_date"] = pd.to_datetime(d["obs_date"])
    fdf["month"] = pd.to_datetime(fdf["month"])
    cand_cols = {}
    for name, table, cc_map, lag, note in SERIES_SPEC:
        shift = max(1, round(lag / 30))
        key = list(cc_map.values())[0]
        cc = list(cc_map.keys())[0]
        x = (ind[ind["indicator"] == key] if table == "ind"
             else ser[ser["series_code"] == key]).sort_values("obs_date").copy()
        if len(x) < 36:
            continue
        col = f"x_{name}"
        x[col] = x["val"].pct_change(12).shift(shift).replace(
            [np.inf, -np.inf], np.nan)
        x = x.rename(columns={"obs_date": "month"})[["month", col] +
                                                    (["commodity_code"] if cc != "*" else [])]
        if cc == "*":
            fdf = fdf.merge(x, on="month", how="left")
        else:
            fdf = fdf.merge(x, on=["month", "commodity_code"], how="left")
        cand_cols[name] = col
    base = list(fu.FEATS)
    TONF = base + [f"wgeo_{t}" for t in LAMBDAS]
    UNITF = base + ["wpx_w0", "wpx_slope", "wfx_w0", "wfx_slope"]

    def wape(target, feats):
        rows = []
        for o in ORIGINS:
            bm = pd.Timestamp(o)
            hist = fdf[fdf["month"] <= bm].copy()
            feat = fu._features(hist, target)
            for h in range(1, 13):
                d = fu._direct_matrix(feat, h)
                d2 = pd.get_dummies(d, columns=["commodity_code"], prefix="cc")
                cc_cols = sorted(c for c in d2.columns if c.startswith("cc_"))
                cols = [c for c in feats if c in d2.columns] + cc_cols
                tr = d2.dropna(subset=["lag1", "y_h"]).sort_values("month")
                med = tr[cols].median(numeric_only=True)
                w = None
                if target == "ton":
                    age = (bm - tr["month"]).dt.days.values / 30.4
                    w = np.exp(-np.log(2) * age / 24)
                m = ExtraTreesRegressor(n_estimators=300, min_samples_leaf=3,
                                        random_state=0, n_jobs=-1)
                X, y = tr[cols].fillna(med), tr["y_h"].values
                m.fit(X, y, sample_weight=w) if w is not None else m.fit(X, y)
                pr = d2[d2["month"] == bm]
                yh = np.exp(m.predict(pr[cols].fillna(med)))
                for i, idx in enumerate(pr.index):
                    rows.append(dict(commodity_code=d.loc[idx, "commodity_code"],
                                     month=bm + pd.DateOffset(months=h),
                                     pred=float(yh[i])))
        p = pd.DataFrame(rows)
        act = fdf.set_index(["commodity_code", "month"])[target]
        p["actual"] = [act.get((c, mm), np.nan)
                       for c, mm in zip(p["commodity_code"], p["month"])]
        p = p.dropna(subset=["actual"])
        return float((p["pred"] - p["actual"]).abs().sum()
                     / p["actual"].abs().sum())

    base_t, base_u = wape("ton", TONF), wape("unit", UNITF)
    out = []
    for name, col in cand_cols.items():
        wt = wape("ton", TONF + [col])
        wu = wape("unit", UNITF + [col])
        verdict = "유망(ton)" if base_t - wt > 0.005 else \
        ("유망(unit)" if base_u - wu > 0.005 else "기각")
        out.append((name, wt, wu, base_t, base_u, verdict))
        print(f"예측 {name}: ton {wt:.4f}(기준 {base_t:.4f}) unit {wu:.4f}"
              f"(기준 {base_u:.4f}) → {verdict}")
    return out


if __name__ == "__main__":
    main()
