# -*- coding: utf-8 -*-
"""발행처·카테고리·날짜·광종 규칙 분류 (LLM 미사용)."""
import re

def source_of(path: str) -> str:
    p = path.lower()
    if "우드맥킨지" in path or "woodmac" in p or "wood mac" in p or any(
        k in p for k in ["investment-horizon", "short-term-outlook", "long-term-outlook",
                          "strategic-planning", "sto-data", "market-balance", "sto_data"]):
        return "WoodMac"
    if "asian" in p or ("weekly" in p and "market summary" in p) or "market-summary" in p:
        return "AsianMetal"
    if "argus" in p or "non-ferrous" in p: return "Argus"
    if "iea" in p or "critical minerals" in p or "criticalminerals" in p: return "IEA"
    if "komis" in p or any(k in path for k in ["주간광물","희소금속","전략광종","자원정보","광업요람"]): return "KOMIS"
    if "조달" in path or "pps" in p: return "PPS"
    return "ETC"

def category_of(path: str, text: str = "") -> str:
    p = (path + " " + text[:500]).lower()
    if any(k in p for k in ["주간", "weekly"]): return "주간동향"
    if any(k in p for k in ["월간", "monthly", "전망", "outlook"]): return "월간전망"
    if any(k in p for k in ["balance", "수급", "밸런스", "supply", "demand"]): return "수급밸런스"
    if any(k in p for k in ["price", "가격", "prices"]): return "가격"
    if any(k in p for k in ["규제", "제재", "정책", "sanction", "policy", "export control"]): return "정책·규제"
    if any(k in p for k in ["뉴스", "news", "지정학", "geopolit"]): return "지정학·뉴스"
    return "기타"

def commodity_of(path: str, text: str = "") -> str | None:
    p = (path + " " + text[:800]).lower()
    if any(k in path for k in ["희토", "네오디"]) or any(k in p for k in ["neod", "rare earth", "ndfeb"]): return "REE"
    if "리튬" in path or "lithium" in p: return "LI"
    if "니켈" in path or "nickel" in p: return "NI"
    if "코발트" in path or "cobalt" in p: return "CO"
    if any(k in path for k in ["동_", "동/", "_동", "구리"]) or "copper" in p: return "CU"
    return None

_D1 = re.compile(r"(20\d{2})[._-]?(0[1-9]|1[0-2])[._-]?(0[1-9]|[12]\d|3[01])")
_D2 = re.compile(r"(20\d{2})[._-](0[1-9]|1[0-2])")
_D3 = re.compile(r"(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])")  # yymmdd
_MON = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}

def date_of(name: str) -> str | None:
    m = _D1.search(name)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"([A-Za-z]{3})[a-z]*[-_ ](20\d{2})", name)
    if m and m.group(1).lower() in _MON: return f"{m.group(2)}-{_MON[m.group(1).lower()]:02d}-01"
    m = _D2.search(name)
    if m: return f"{m.group(1)}-{m.group(2)}-01"
    # 구분자 없는 YYYYMM (예: _202403)
    m = re.search(r"(20\d{2})(0[1-9]|1[0-2])(?!\d)", name)
    if m: return f"{m.group(1)}-{m.group(2)}-01"
    # 분기: q3-2024 / 2024-q3 / q3_2024
    m = re.search(r"q([1-4])[-_ ]?(20\d{2})", name, re.I) or re.search(r"(20\d{2})[-_ ]?q([1-4])", name, re.I)
    if m:
        g = m.groups()
        q, y = (g[0], g[1]) if g[0].isdigit() and len(g[0]) == 1 else (g[1], g[0])
        return f"{y}-{(int(q)-1)*3+1:02d}-01"
    m = _D3.search(name)
    if m: return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None
