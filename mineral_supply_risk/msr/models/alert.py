# -*- coding: utf-8 -*-
"""
핵심광물 수급위기 경보 4단계 산출 로직
근거: 「국가자원안보 확보를 위한 고시」 제7조 / 과업지시서 붙임2
  단계: 0 정상 · 1 관심(Blue) · 2 주의(Yellow) · 3 경계(Orange) · 4 심각(Red)

설계: (A) 위기지수 분위수 기반 기본단계  +  (B) 규칙 오버라이드(격상)  +  (C) 히스테리시스
  - 위기지수 = 100 - 수급동향지표(교사신호/모델예측)  → 높을수록 위기
  - 광종별 임계값 차등(과업: 희토류 편중도 단독 트리거 등)
"""
import os
import duckdb, numpy as np, pandas as pd
from ..config import DB_PATH as _DB_DEFAULT, OUT as _OUT

LEVELS={0:"정상",1:"관심",2:"주의",3:"경계",4:"심각"}
COLORS={0:"#9e9e9e",1:"#2f6fed",2:"#f5c518",3:"#f28c1c",4:"#d0342c"}

# 자원안보특별법 붙임2 정성기준 → 정량 규칙 매핑
#  관심: 가격변동성 증가            → volatility 상위
#  주의: 수급위기 가능성/변동성 급증 → 위기지수 분위수 + 지정학 이벤트
#  경계: 수송로 일부봉쇄/조달 일부차질 → 지정학 severity 高 or 편중도 極
#  심각: 전면봉쇄/조달 전면차질      → 위기지수 극단 + 복합 트리거

# 위기지수 분위수 컷 (광종 공통 기본, config로 광종별 override 가능)
Q_CUT={"관심":0.50,"주의":0.70,"경계":0.85,"심각":0.95}
# 규칙 오버라이드 임계(광종별 히스토리 분위수)
OV_GEO_SEV=0.85      # 지정학 이벤트 severity 이 이상이면 격상
OV_HHI_Q=0.90        # 수입편중 HHI 상위 → 최소 경계
OV_VOL_Q=0.90        # 가격변동성 급증 → 최소 관심

def compute_alerts(df, geo_sev=None):
    """df: mart_weekly_diagnosis(2020+, 광종별). geo_sev: (commodity,week)->max severity dict"""
    df=df.sort_values(["commodity_code","obs_date"]).copy()
    df["crisis_index"]=100-df["teacher_supply_demand"]   # 높을수록 위기
    out=[]
    for cc,g in df.groupby("commodity_code"):
        g=g.copy()
        ci=g["crisis_index"]
        # (A) 분위수 기반 기본단계
        cuts={k:ci.quantile(v) for k,v in Q_CUT.items()}
        def base(x):
            if x>=cuts["심각"]:return 4
            if x>=cuts["경계"]:return 3
            if x>=cuts["주의"]:return 2
            if x>=cuts["관심"]:return 1
            return 0
        g["base_level"]=ci.apply(base)
        # (B) 규칙 오버라이드
        hhi_thr=g["import_hhi"].quantile(OV_HHI_Q) if g["import_hhi"].notna().any() else np.inf
        vol_thr=g["volatility_12w"].quantile(OV_VOL_Q) if g["volatility_12w"].notna().any() else np.inf
        lvl=[]; trig=[]
        for _,r in g.iterrows():
            L=r["base_level"]; t=[]
            # 가격변동성 급증 → 최소 관심
            if pd.notna(r["volatility_12w"]) and r["volatility_12w"]>=vol_thr: L=max(L,1); t.append("변동성급증")
            # 수입편중 極 → 최소 경계 (과업: 희토류 편중도 단독 트리거)
            if pd.notna(r["import_hhi"]) and r["import_hhi"]>=hhi_thr: L=max(L,3); t.append("수입편중極")
            # 지정학 severe 이벤트 → +1 격상, 최소 주의
            sev=(geo_sev or {}).get((cc, r["obs_date"]))
            if sev is not None and sev>=OV_GEO_SEV: L=min(4,max(L+1,2)); t.append(f"지정학{sev:.2f}")
            lvl.append(L); trig.append("+".join(t))
        g["rule_level"]=lvl; g["triggers"]=trig
        # (C) 히스테리시스: 하향은 2주 지속시만 반영(진동 방지)
        fin=[]; prev=0; pend=None; cnt=0
        for L in g["rule_level"]:
            if L>=prev: fin.append(L); prev=L; pend=None; cnt=0
            else:
                if pend==L: cnt+=1
                else: pend=L; cnt=1
                if cnt>=2: fin.append(L); prev=L; pend=None; cnt=0
                else: fin.append(prev)
        g["alert_level"]=fin
        g["alert_name"]=g["alert_level"].map(LEVELS)
        out.append(g)
    return pd.concat(out)

# ---- 경보 사유(자원안보특별법 붙임2 문안) ----
_C2_PAT = ("strike", "shutdown", "disruption", "curtail", "closure", "force majeure",
           "파업", "차질", "가동중단", "폐쇄", "봉쇄", "감산")


def _geo_category(event_type: str) -> str:
    """자유텍스트 event_type → 공식기준 카테고리(c1 정세/수출제한, c2 시설/수송 차질)."""
    t = (event_type or "").lower()
    return "c2" if any(k in t for k in _C2_PAT) else "c1"


def _build_reasons(res: pd.DataFrame, geo_df: pd.DataFrame) -> pd.Series:
    from .alert_reason import OFFICIAL
    gmap = {}
    if geo_df is not None and len(geo_df):
        g = geo_df.dropna(subset=["obs_date"]).copy()
        g["m"] = pd.to_datetime(g["obs_date"]).values.astype("datetime64[M]")
        for r in g.sort_values("severity", ascending=False).itertuples():
            gmap.setdefault((r.commodity_code, pd.Timestamp(r.m)), []).append(r)

    def reason(r):
        L = int(r.alert_level)
        if L == 0:
            return "정상 — 위기지수·변동성·지정학 트리거 모두 임계 이하."
        o = OFFICIAL[L]
        evs = gmap.get((r.commodity_code, pd.Timestamp(r.obs_date).replace(day=1)), [])
        crit = []
        if any(_geo_category(e.event_type) == "c1" and (e.severity or 0) >= 2 for e in evs): crit.append(o["c1"])
        if any(_geo_category(e.event_type) == "c2" and (e.severity or 0) >= 2 for e in evs): crit.append(o["c2"])
        crit.append(o["c3"])                    # 가격변동성/조달(위기지수 기반)은 항상 관련
        drv = [f"수급위기지수 {r.crisis_index:.0f}/100"]
        if isinstance(r.triggers, str) and r.triggers: drv.append(r.triggers)
        base = f"[{r.commodity_code} · {o['name']}] {' / '.join(crit[:2])}. (산출근거: {', '.join(drv)})"
        if evs:
            e = evs[0]
            q = str(e.evidence_quote or "")[:90]
            base += f" 관련 이벤트: '{q}' ({e.country or '-'}, sev {float(e.severity):.1f}/3)"
        return base[:2000]

    return res.apply(reason, axis=1)


def run(db=None, model_version="alert_rule_v1"):
    """mart_weekly_diagnosis(위기지수) + geo_event(지정학) → 경보 4단계 + 사유
    → out_diagnosis_alert 적재. 입력 부족 시 None(스킵)."""
    db = db or _DB_DEFAULT
    con = duckdb.connect(db, read_only=True)
    try:
        have = {c[0] for c in con.execute("DESCRIBE mart_weekly_diagnosis").fetchall()}
    except Exception:
        con.close(); print("[alert] mart_weekly_diagnosis 없음 → 스킵."); return None
    need = {"commodity_code", "obs_date", "teacher_supply_demand", "volatility_12w", "import_hhi"}
    if need - have:
        con.close(); print(f"[alert] 마트 컬럼 부족({sorted(need - have)}) → 스킵."); return None
    df = con.execute("""SELECT commodity_code,obs_date,teacher_supply_demand,volatility_12w,import_hhi
        FROM mart_weekly_diagnosis
        WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL""").df()
    try:
        # 오버라이드 트리거는 고신뢰 소스(공시·큐레이션 보고서)의 공급위축 이벤트로 제한.
        # 실측(2026-07-12): GKG(182만건) 병합 후 무제한 조회 시 severity 3 뉴스가 거의 매주
        # 존재 → 경보가 상시 격상(심각 25~30%). 붙임2 계열1의 "수출제한 실시" 같은 트리거는
        # 뉴스 보도가 아니라 확정력 있는 근거(관보·업계 큐레이션)로만 발동해야 한다.
        # GDELT 뉴스 신호는 이미 지수(변수⑥)로 점수 단계에 반영되고 있으므로 이중계상도 방지.
        geo_df = con.execute("""SELECT commodity_code, obs_date, event_type, country,
            severity, evidence_quote FROM geo_event
            WHERE commodity_code IS NOT NULL
              AND direction = 'supply_down'
              AND source IN ('US_FederalRegister','CN_MOFCOM','WoodMac','IEA','KOMIS',
                             'Argus','PPS','AsianMetal','EU_SCRREEN')""").df()
    except Exception:
        geo_df = pd.DataFrame()
        print("  [warn] geo_event 없음 — 지정학 오버라이드 없이 산출(geo-publish 먼저 권장)")
    con.close()
    if df.empty:
        print("[alert] 교사신호 없음 → 스킵."); return None

    # 지정학 최대 severity: (commodity, month) → 주간 매핑.
    # 스케일 정합: geo severity는 0~3, OV_GEO_SEV(0.85)는 0~1 기준 → /3 정규화(2.55/3 이상만 격상).
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    sev = {}
    if len(geo_df):
        g = geo_df.dropna(subset=["obs_date"]).copy()
        g["m"] = pd.to_datetime(g["obs_date"]).values.astype("datetime64[M]")
        gs = g.groupby(["commodity_code", "m"])["severity"].max()
        gsmap = {(cc, pd.Timestamp(m)): float(s) / 3.0 for (cc, m), s in gs.items()}
        sev = {(cc, d): gsmap.get((cc, pd.Timestamp(d).replace(day=1)))
               for cc, d in zip(df.commodity_code, df.obs_date)}

    res = compute_alerts(df, sev)
    res["reason"] = _build_reasons(res, geo_df)
    print("경보 분포(광종×단계):")
    print(res.groupby(["commodity_code", "alert_name"]).size().unstack(fill_value=0).to_string())

    # out_diagnosis_alert 계약으로 적재
    from ..storage import db as store
    out = pd.DataFrame({
        "commodity_code": res["commodity_code"],
        "obs_date": pd.to_datetime(res["obs_date"]).dt.date,
        "risk_score": res["crisis_index"].round(4),
        "risk_proba": None,
        "alert_level": res["alert_name"],
        "reason": res["reason"],
        "model_version": model_version,
        "generated_at": pd.Timestamp.now().floor("s"),
    })
    store.upsert_df(out, "out_diagnosis_alert", del_where="1=1")
    # CSV 부산물(감사용)
    out_dir = os.path.join(str(_OUT), "alert"); os.makedirs(out_dir, exist_ok=True)
    res[["commodity_code", "obs_date", "teacher_supply_demand", "crisis_index", "base_level",
         "rule_level", "alert_level", "alert_name", "triggers", "reason"]].to_csv(
         os.path.join(out_dir, "alert_timeline.csv"), index=False)
    latest = res.sort_values("obs_date").groupby("commodity_code").tail(1)
    print(f"[alert] out_diagnosis_alert {len(out)}행 적재 · 최신 경보:",
          {r.commodity_code: r.alert_name for r in latest.itertuples()})
    return {"rows": len(out), "latest": {r.commodity_code: r.alert_name for r in latest.itertuples()}}


if __name__=="__main__":
    run()
