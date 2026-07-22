# -*- coding: utf-8 -*-
"""
관세청 '품목별 국가별 수출입실적(GW)' OpenAPI 수집기
 - 공공데이터포털: getNitemtradeList (HS부호 × 국가 × 월별)
 - 반환: XML → DataFrame(year,month,hscode,country,imp_usd,imp_wgt,exp_usd,exp_wgt)
사용: collect(hs_list, start_yymm, end_yymm) -> DataFrame
"""
import time, requests, pandas as pd, xml.etree.ElementTree as ET
from urllib.parse import unquote
from ..config import DATA_GO_KR_KEY_ENC, DATA_GO_KR_KEY_DEC

BASE = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

def _key():
    # requests가 자동 인코딩하므로 Decoding(원문) 키 사용 권장
    return DATA_GO_KR_KEY_DEC or unquote(DATA_GO_KR_KEY_ENC)

def _parse_xml(text):
    root = ET.fromstring(text)
    # 에러 체크
    hdr = root.find(".//cmmMsgHeader")
    if hdr is not None:
        code = hdr.findtext("returnReasonCode")
        if code and code not in ("00", "0"):
            raise RuntimeError(f"API error {code}: {hdr.findtext('errMsg')}")
    rows = []
    for it in root.findall(".//item"):
        g = lambda t: (it.findtext(t) or "").strip()
        rows.append({
            "year": g("year"), "month": g("month"),
            "hscode": g("hsCd") or g("hscode"),
            "country": g("statKor") or g("statCd"),
            "exp_usd": g("expDlr"), "exp_wgt": g("expWgt"),
            "imp_usd": g("impDlr"), "imp_wgt": g("impWgt"),
            "balance": g("balPayments"),
        })
    return rows

def fetch_one(hs, strt_yymm, end_yymm, retries=3):
    params = {"serviceKey": _key(), "strtYymm": strt_yymm, "endYymm": end_yymm,
              "hsSgn": hs, "cnt": "1000"}
    for a in range(retries):
        try:
            r = requests.get(BASE, params=params, timeout=30)
            r.raise_for_status()
            return _parse_xml(r.text)
        except Exception as e:
            if a == retries-1: raise
            time.sleep(2*(a+1))

def collect(hs_list, strt_yymm, end_yymm, sleep=0.3):
    """hs_list: HS부호(2/4/6/10자리) 목록. 반환: 정제 DataFrame(월별·국가별)."""
    all_rows = []
    for hs in hs_list:
        rows = fetch_one(hs, strt_yymm, end_yymm) or []
        for x in rows: x["hs_query"] = hs
        all_rows += rows
        time.sleep(sleep)
    df = pd.DataFrame(all_rows)
    if df.empty: return df
    for c in ["exp_usd","exp_wgt","imp_usd","imp_wgt"]:
        df[c] = pd.to_numeric(df[c].str.replace(",",""), errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    # month 없는 합계행 제거, 월 정규화
    df = df[df["month"].astype(str).str.len()>0]
    return df.reset_index(drop=True)
