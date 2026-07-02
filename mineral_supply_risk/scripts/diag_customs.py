# -*- coding: utf-8 -*-
"""관세청 API 진단 — 로컬(네트워크 열림)에서 실행.
   python -m scripts.diag_customs
키 로딩 상태 + 실제 HTTP 응답(returnReasonCode/returnAuthMsg)을 그대로 출력한다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from urllib.parse import unquote, urlencode
from msr.config import DATA_GO_KR_KEY_ENC, DATA_GO_KR_KEY_DEC

BASE = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

def mask(k): return "" if not k else f"{k[:6]}...{k[-4:]} (len={len(k)})"

print("=== 1) 키 로딩 상태 ===")
print("  DECODING:", mask((DATA_GO_KR_KEY_DEC or '').strip()))
print("  ENCODING:", mask((DATA_GO_KR_KEY_ENC or '').strip()))
if not (DATA_GO_KR_KEY_DEC or DATA_GO_KR_KEY_ENC):
    print("  ❌ 키가 비었음 → .env 미로딩 또는 python-dotenv 미설치. 여기서 중단."); sys.exit(1)

params = {"strtYymm": "202401", "endYymm": "202412", "hsSgn": "7402", "cnt": "10"}

print("\n=== 2) 방식A: DECODING 키를 params로 (requests 인코딩) ===")
try:
    r = requests.get(BASE, params={**params, "serviceKey": (DATA_GO_KR_KEY_DEC or '').strip()}, timeout=30)
    print("  HTTP", r.status_code, "| 요청 serviceKey(앞60):", r.url.split('serviceKey=')[1][:60])
    print("  응답 앞 600자:\n", r.text[:600])
except Exception as e:
    print("  예외:", e)

print("\n=== 3) 방식B: ENCODING 키를 URL에 verbatim ===")
try:
    url = f"{BASE}?serviceKey={(DATA_GO_KR_KEY_ENC or '').strip()}&{urlencode(params)}"
    r = requests.get(url, timeout=30)
    print("  HTTP", r.status_code)
    print("  응답 앞 600자:\n", r.text[:600])
except Exception as e:
    print("  예외:", e)

print("\n※ 응답에 SERVICE_KEY_IS_NOT_REGISTERED_ERROR(코드30) 이면 → 이 키가 해당 API에 "
      "'활용신청/승인'이 안 된 것. data.go.kr 마이페이지에서 '품목별 국가별 수출입실적' 활용신청 필요.")
