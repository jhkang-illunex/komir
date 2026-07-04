# -*- coding: utf-8 -*-
"""
관세청 '품목별 국가별 수출입실적(GW)' OpenAPI 수집기
 - 공공데이터포털: getNitemtradeList (HS부호 × 국가 × 월별)
 - 반환: XML → DataFrame(year,month,hscode,country,imp_usd,imp_wgt,exp_usd,exp_wgt)
사용: collect(hs_list, start_yymm, end_yymm) -> DataFrame
"""
import re, time, requests, pandas as pd, xml.etree.ElementTree as ET
from urllib.parse import unquote
from ..config import DATA_GO_KR_KEY_ENC, DATA_GO_KR_KEY_DEC

BASE = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"


class QuotaExceeded(RuntimeError):
    """일일/트래픽 호출 한도 초과(429 또는 returnReasonCode 22/23). 재시도 무의미 → 즉시 중단."""


def _mask(s) -> str:
    """로그 노출용: URL 내 serviceKey 값을 가림(키 유출 방지)."""
    return re.sub(r"(serviceKey=)[^&\s]+", r"\1***", str(s))

def _key():
    """serviceKey 반환. Decoding(원문) 키를 params로 넘기면 requests가 인코딩키와
    동일한 바이트로 인코딩하므로 정상. 둘 다 비면 명확히 에러."""
    dec = (DATA_GO_KR_KEY_DEC or "").strip().strip('"').strip("'")
    enc = (DATA_GO_KR_KEY_ENC or "").strip().strip('"').strip("'")
    key = dec or (unquote(enc) if enc else "")
    if not key:
        raise RuntimeError(
            "관세청 serviceKey가 비었습니다. 원인 점검:\n"
            "  1) .env 에 DATA_GO_KR_SERVICE_KEY_DECODING(또는 _ENCODING) 값이 있는지\n"
            "  2) 실행 파이썬에 python-dotenv 설치됐는지(pip install python-dotenv)\n"
            "  3) .env 위치: 프로젝트 루트(mineral_supply_risk/.env)")
    return key

def _parse_xml(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # XML이 아니면(HTML/JSON 에러 등) 본문 앞부분을 그대로 노출
        raise RuntimeError(f"응답이 XML이 아님(키/엔드포인트/네트워크 의심): {text[:300]!r}")
    # data.go.kr 인증오류: <cmmMsgHeader><returnReasonCode>30</><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</>
    hdr = root.find(".//cmmMsgHeader")
    if hdr is not None:
        code = hdr.findtext("returnReasonCode")
        if code and code not in ("00", "0"):
            msg = hdr.findtext("returnAuthMsg") or hdr.findtext("errMsg") or ""
            if code in ("22", "23"):
                raise QuotaExceeded(f"API {code}: {msg} → 호출 한도 초과(트래픽/일일). 자정(KST) 리셋 후 재시도.")
            hint = ""
            if code == "30":
                hint = " → 이 키가 '품목별 국가별 수출입실적' API에 활용신청/승인됐는지 확인(마이페이지)."
            raise RuntimeError(f"API error {code}: {msg}{hint}")
    # 헤더 없이 resultCode 형태인 경우도 처리
    rc = root.findtext(".//resultCode")
    if rc and rc not in ("00", "0", "0000"):
        raise RuntimeError(f"API resultCode {rc}: {root.findtext('.//resultMsg')}")
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
            if r.status_code == 429:
                raise QuotaExceeded("HTTP 429 Too Many Requests (일일/트래픽 한도)")
            r.raise_for_status()
            return _parse_xml(r.text)        # 한도코드(22/23)면 QuotaExceeded 발생
        except QuotaExceeded:
            raise                            # 재시도 무의미 → 즉시 전파
        except Exception as e:
            if a == retries-1: raise
            time.sleep(2*(a+1))

def _year_windows(strt_yymm, end_yymm):
    """[strt,end]를 12개월 이내 창으로 분할. 관세청 API는 1콜당 최대 1년만 허용."""
    sy, sm = int(strt_yymm[:4]), int(strt_yymm[4:6])
    ey, em = int(end_yymm[:4]), int(end_yymm[4:6])
    wins, y = [], sy
    while y <= ey:
        a = f"{y}{sm:02d}" if y == sy else f"{y}01"
        b = f"{y}{em:02d}" if y == ey else f"{y}12"
        wins.append((a, b)); y += 1
    return wins

def _month_windows(strt_yymm, end_yymm):
    """[strt,end]를 1개월 창으로 분할(strtYymm=endYymm). 월간 by-국가 수집용."""
    sy, sm = int(strt_yymm[:4]), int(strt_yymm[4:6])
    ey, em = int(end_yymm[:4]), int(end_yymm[4:6])
    out, y, m = [], sy, sm
    while (y, m) <= (ey, em):
        ym = f"{y}{m:02d}"; out.append((ym, ym))
        m += 1
        if m > 12: m = 1; y += 1
    return out

def _clean_frame(rows, freq):
    """원시 행 리스트 → 정제 DataFrame(총계행 제거·수치화·연/월 보정)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ["exp_usd", "exp_wgt", "imp_usd", "imp_wgt"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    # ⚠️ '총계' 행(year='총계', country/hscode='-')이 섞여옴 → 제거
    df["country"] = df["country"].astype(str).str.strip()
    df["hscode"] = df["hscode"].astype(str).str.strip()
    df = df[~df["country"].isin(["총계", "합계", "총 계", "Total", "World", "-", ""])]
    df = df[~df["hscode"].isin(["-", ""])]
    # year: 응답 year가 숫자 아니면 조회연도(q_year)로 보정
    df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(
        pd.to_numeric(df.get("q_year"), errors="coerce"))
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    if freq == "M":  # 월간 모드면 조회월로 채움(연간은 비움)
        df["month"] = pd.to_numeric(df.get("q_month"), errors="coerce").astype("Int64")
    return df.reset_index(drop=True)


def collect(hs_list, strt_yymm, end_yymm, sleep=0.3, freq="A", sink=None):
    """hs_list: HS부호 목록. freq: 'A'(연간 1콜=1년) | 'M'(월간 1콜=1개월).
    sink=None: 전량 정제 DataFrame 반환(구 동작).
    sink(df_hs): 지정 시 HS 단위로 정제분을 콜백에 흘려 **증분 적재**(중단 시 손실 최소화)하고 적재행수 반환.
    QuotaExceeded는 상위로 전파되어 즉시 중단(그때까지 sink된 분은 보존)."""
    windows = _month_windows(strt_yymm, end_yymm) if freq == "M" else _year_windows(strt_yymm, end_yymm)
    total = len(hs_list) * len(windows)
    n, written, all_rows = 0, 0, []
    for hs in hs_list:
        hs_rows = []
        for a, b in windows:
            n += 1
            try:
                rows = fetch_one(hs, a, b) or []
            except QuotaExceeded:
                raise                                    # 한도 초과 → 전체 중단
            except Exception as e:
                print(f"  [warn] hs={hs} {a}~{b} 실패: {_mask(e)}")
                rows = []
            for x in rows:
                x["hs_query"] = hs
                x["q_year"] = a[:4]
                x["q_month"] = a[4:6]
            hs_rows += rows
            if n % 100 == 0:
                print(f"  ... {n}/{total} 콜")
            time.sleep(sleep)
        if sink is not None:
            df_hs = _clean_frame(hs_rows, freq)
            if not df_hs.empty:
                sink(df_hs); written += len(df_hs)
        else:
            all_rows += hs_rows
    if sink is not None:
        return written
    return _clean_frame(all_rows, freq)
