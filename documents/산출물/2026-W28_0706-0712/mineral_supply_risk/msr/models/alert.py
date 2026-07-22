# -*- coding: utf-8 -*-
"""
핵심광물 수급위기 경보 4단계 산출 로직
근거: 「국가자원안보 확보를 위한 고시」 제7조 / 과업지시서 붙임2
  단계: 0 정상 · 1 관심(Blue) · 2 주의(Yellow) · 3 경계(Orange) · 4 심각(Red)

설계: (A) 위기지수 분위수 기반 기본단계  +  (B) 규칙 오버라이드(격상)  +  (C) 히스테리시스
  - 위기지수 = 100 - 수급동향지표(교사신호/모델예측)  → 높을수록 위기
  - 광종별 임계값 차등(과업: 희토류 편중도 단독 트리거 등)
"""
import duckdb, numpy as np, pandas as pd

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

if __name__=="__main__":
    con=duckdb.connect("/tmp/mdb.duckdb", read_only=True)
    df=con.execute("""SELECT commodity_code,obs_date,teacher_supply_demand,volatility_12w,
        import_hhi,geopolitical_risk FROM mart_weekly_diagnosis
        WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL""").df()
    # 지정학 최대 severity: (commodity, month)기준을 주간에 매핑
    gs=con.execute("""SELECT commodity_code, date_trunc('month',obs_date) m, max(severity) s
        FROM geo_event WHERE commodity_code IS NOT NULL GROUP BY 1,2""").df()
    con.close()
    df["m"]=pd.to_datetime(df["obs_date"]).values.astype("datetime64[M]")
    gsmap={(r.commodity_code, pd.Timestamp(r.m)):r.s for r in gs.itertuples()}
    df["obs_date"]=pd.to_datetime(df["obs_date"])
    sev={(cc,d):gsmap.get((cc, pd.Timestamp(d).replace(day=1))) for cc,d in zip(df.commodity_code,df.obs_date)}
    res=compute_alerts(df, sev)
    print("경보 분포(광종×단계):")
    print(res.groupby(["commodity_code","alert_name"]).size().unstack(fill_value=0))
    res[["commodity_code","obs_date","teacher_supply_demand","crisis_index","base_level",
         "rule_level","alert_level","alert_name","triggers"]].to_csv(
         "/sessions/dreamy-modest-lamport/mnt/광해광업/claude_output/alert/alert_timeline.csv",index=False)
    print("\n저장: alert_timeline.csv")
