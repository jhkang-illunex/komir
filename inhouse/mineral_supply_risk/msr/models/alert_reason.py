# -*- coding: utf-8 -*-
"""경보 사유(근거텍스트) 생성 — 자원안보특별법 붙임2 공식문안 + 데이터근거 + 지정학 이벤트 인용"""
import duckdb, pandas as pd, numpy as np, csv, re
import os as _os
from ..config import DB_PATH as _DB_DEFAULT, OUT as _OUT
_ALERT_DIR = _os.path.join(str(_OUT), "alert")   # alert.run()이 쓰는 산출 위치(cwd 의존 제거)

# 자원안보특별법 붙임2 「자원안보위기 경보 발령의 기준」 공식 문안 (3대 기준 카테고리)
OFFICIAL={
 1:{"name":"관심(Blue)","c1":"주요 생산국의 정세불안(테러·폭동 등으로 인한 생산차질 및 수출제한 우려)",
    "c2":"저장·생산·공급 시설의 재난 발생 징후 포착 및 수송경로 불안정성 증가로 인한 운송차질 우려",
    "c3":"국제 핵심광물 시장의 가격 변동성 증가"},
 2:{"name":"주의(Yellow)","c1":"주요 생산국의 정세불안 증가(생산·수송시설 파괴 등으로 인한 생산차질 발생 및 부분적 수출제한)",
    "c2":"저장·생산·공급 시설의 재난 발생 및 수송경로 불안정성 확산으로 수급위기 발생 가능성이 있는 상태",
    "c3":"국제 핵심광물 시장의 가격 변동성 급증"},
 3:{"name":"경계(Orange)","c1":"주요 생산국의 정세불안 심화(전쟁발발, 주요시설 파괴, 추가 수출제한 등)",
    "c2":"저장·생산·공급 시설의 대형재난 발생 및 수송경로 일부 봉쇄로 인한 단기적 차질",
    "c3":"국제 핵심광물 시장의 가격 변동성 급증 및 핵심광물 조달 일부 차질"},
 4:{"name":"심각(Red)","c1":"주요 생산국의 정세 악화(주변국 전쟁 확산, 대규모 생산·수송시설 파괴, 전면적 수출제한 등)",
    "c2":"저장·생산·공급 시설의 대형재난 발생 및 수송경로 전면봉쇄로 인한 장기적 차질",
    "c3":"국제 핵심광물 시장의 가격 변동성 급증 및 핵심광물 조달 전면 차질"},
}
# 지정학 event_type → 공식기준 카테고리 매핑
GEO_C1={"sanction","export_restriction","nationalization","conflict","tariff","policy_cost","policy_subsidy"}
GEO_C2={"supply_disruption"}

def build(db=_DB_DEFAULT, alert_csv=None):
    alert_csv = alert_csv or _os.path.join(_ALERT_DIR, "alert_timeline.csv")
    df=pd.read_csv(alert_csv, parse_dates=["obs_date"])
    con=duckdb.connect(db, read_only=True)
    # 광종×월 대표 지정학 이벤트(최고 severity + 유형 + 근거인용)
    ge=con.execute("""
      SELECT commodity_code, date_trunc('month',obs_date) m, event_type, country, severity, evidence_quote,
             row_number() OVER (PARTITION BY commodity_code,date_trunc('month',obs_date) ORDER BY severity DESC) rn
      FROM geo_event WHERE commodity_code IS NOT NULL AND severity IS NOT NULL""").df()
    con.close()
    ge=ge[ge.rn<=2]
    gmap={}
    for r in ge.itertuples():
        gmap.setdefault((r.commodity_code, pd.Timestamp(r.m)),[]).append(
            dict(type=r.event_type,country=r.country,sev=r.severity,quote=str(r.evidence_quote)[:90]))
    def reason(r):
        L=int(r.alert_level)
        if L==0: return "정상 — 위기지수·변동성·지정학 트리거 모두 임계 이하."
        o=OFFICIAL[L]; parts=[]
        # 활성 기준 판별
        evs=gmap.get((r.commodity_code, pd.Timestamp(r.obs_date).replace(day=1)),[])
        has_c1=any(e["type"] in GEO_C1 and (e["sev"] or 0)>=0.6 for e in evs)
        has_c2=any(e["type"] in GEO_C2 and (e["sev"] or 0)>=0.6 for e in evs)
        # 공식 문안(해당 카테고리 우선, 없으면 c3 가격/조달)
        crit=[]
        if has_c1: crit.append(o["c1"])
        if has_c2: crit.append(o["c2"])
        crit.append(o["c3"])   # 가격변동성/조달차질은 항상 관련(위기지수 기반)
        official=" / ".join(crit[:2])
        # 데이터 근거
        drv=[f"수급위기지수 {r.crisis_index:.0f}/100"]
        if isinstance(r.triggers,str) and r.triggers and r.triggers!="nan":
            drv.append(r.triggers)
        base=f"[{r.commodity_code} · {o['name']}] {official}. (산출근거: {', '.join(drv)})"
        # 지정학 이벤트 인용
        if evs:
            e=evs[0]
            base+=f" 관련 이벤트: '{e['quote']}'"+(f" ({e['country']}, severity {e['sev']:.2f})" if e['country'] else f" (severity {e['sev']:.2f})")
        return base
    df["사유"]=df.apply(reason,axis=1).map(lambda x: re.sub(r"\s+"," ",str(x)).strip())
    # JSON 저장(견고) + 파이썬 csv 모듈로 CSV
    keep=["commodity_code","obs_date","alert_level","alert_name","crisis_index","triggers","사유"]
    d2=df[keep].copy(); d2["obs_date"]=d2["obs_date"].astype(str)
    _os.makedirs(_ALERT_DIR, exist_ok=True)
    d2.to_json(_os.path.join(_ALERT_DIR,"alert_timeline_사유.json"),orient="records",force_ascii=False,indent=1)
    return df

if __name__=="__main__":
    df=build()
    print("=== 최근 경보 + 사유 ===\n")
    latest=df.sort_values("obs_date").groupby("commodity_code").tail(1)
    for _,r in latest.sort_values("alert_level",ascending=False).iterrows():
        print(r["사유"],"\n")
