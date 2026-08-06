# -*- coding: utf-8 -*-
"""발행처·카테고리·날짜·광종 규칙 분류 (LLM 미사용)."""
import re

def source_of(path: str) -> str:
    p = path.lower()
    if "gdelt" in p: return "GDELT"
    if "gnews" in p: return "GoogleNews"
    # 수집기(collector/) 공시 소스 — inbox/us_trade/·inbox/cn_trade/ 경로로 투척됨(2026-07-12)
    if "us_trade" in p or "federalregister" in p: return "US_FederalRegister"
    if "cn_trade" in p or "mofcom" in p: return "CN_MOFCOM"
    if "우드맥킨지" in path or "woodmac" in p or "wood mac" in p or any(
        k in p for k in ["investment-horizon", "short-term-outlook", "long-term-outlook",
                          "strategic-planning", "sto-data", "market-balance", "sto_data"]):
        return "WoodMac"
    if "asian" in p or ("weekly" in p and "market summary" in p) or "market-summary" in p:
        return "AsianMetal"
    if "argus" in p or "non-ferrous" in p: return "Argus"
    if "iea" in p or "critical minerals" in p or "criticalminerals" in p: return "IEA"
    if "scrreen" in p: return "EU_SCRREEN"
    if "komis" in p or any(k in path for k in ["주간광물","희소금속","전략광종","자원정보","광업요람"]): return "KOMIS"
    if "조달" in path or "pps" in p: return "PPS"
    # 조달청 원자재시장분석센터 "주간 경제·비철금속 시장동향" — 파일명에 "조달"이 없어 실측(2026-07-07)
    # 미분류 확인됨. 공백유무 2종 표기(2013~2016 "비철금속시장동향" / 2020~ "비철금속 시장 동향")를
    # 공백 제거 비교로 한 번에 처리.
    if "비철금속시장동향" in path.replace(" ", ""):
        return "PPS"
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

COMMODITY_KEYWORDS = {
    # 중국어 키워드(2026-07-12): cn_trade 공시(중국 상무부) 대응 — 稀土(희토)·钕(네오디뮴) 등.
    # 钴(코발트)·锂(리튬)·镍(니켈)은 단독 한자라 오탐 여지가 있으나 중국어 문서에서만 등장하는
    # 글자들이라(한/영 문서에 나타나지 않음) 실질 오탐 경로가 없음. 铜(동)도 동일.
    "REE": ("희토", "네오디", "neod", "rare earth", "ndfeb", "稀土", "钕"),
    "LI": ("리튬", "lithium", "锂"),
    "NI": ("니켈", "nickel", "镍"),
    "CO": ("코발트", "cobalt", "钴"),
    "CU": ("동_", "동/", "_동", "구리", "copper", "铜"),
}


def _match_commodity(hay: str) -> str | None:
    for cc, kws in COMMODITY_KEYWORDS.items():
        if any(k in hay for k in kws):
            return cc
    return None


def commodities_in(text: str) -> list[str]:
    """텍스트 전체(문서 제한 없음)에서 언급된 모든 광종. 다광종 문서(조달청·Argus·IEA 등) 처리용."""
    low = (text or "").lower()
    return [cc for cc, kws in COMMODITY_KEYWORDS.items() if any(k in low for k in kws)]


def commodity_of(path: str, text: str = "") -> str | None:
    """문서 대표 광종 1개 추정(아카이브 폴더명·단일광종 문서용).
    파일명을 텍스트보다 우선 검사한다 — 실측(2026-07-07): WoodMac 니켈 보고서가 2쪽 광고문구
    ("...Aluminium Lithium")에 낚여 LI로 오분류되는 문제 확인. 파일명(의도적 명명)이 본문
    앞부분(광고·목차 등 잡음 많음)보다 신뢰도가 높다."""
    hit = _match_commodity(path.lower())
    if hit:
        return hit
    return _match_commodity((path + " " + text[:800]).lower())

_D1 = re.compile(r"(20\d{2})[._-]?(0[1-9]|1[0-2])[._-]?(0[1-9]|[12]\d|3[01])")
# 비0패딩 월/일(예: "2020.5.12", "2016.1.19") — 조달청보고서 파일명에서 실측 확인(2026-07-07).
# _D1은 0패딩 없인 구분자도 생략 가능해 오매칭 위험이 있어, 구분자를 필수로 강제해 안전하게 분리.
_D1_LOOSE = re.compile(r"(20\d{2})[._-](0?[1-9]|1[0-2])[._-](0?[1-9]|[12]\d|3[01])(?!\d)")
_D2 = re.compile(r"(20\d{2})[._-](0[1-9]|1[0-2])")
# yymmdd: 앞뒤 숫자 경계 필수(6자리 문서번호 오인 방지)
_D3 = re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_MON = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}
# 2026-07-07 추가(날짜미상 695건 분석, §9): 연도가 월이름보다 앞에 오는 배치(Asian Metal Weekly),
# 한글 "년/월", 계간지 회차, 연도전용(월/일 없는 연간 발행물).
_YMD_MON_SUFFIX = re.compile(r"(20\d{2})-(\d{1,2})[-–](\d{1,2})[-_ ]([A-Za-z]{3,9})", re.I)
_KOR_YM = re.compile(r"(20\d{2})\s*년\s*(0?[1-9]|1[0-2])\s*월")
_YEAR_ISSUE = re.compile(r"(20\d{2})[_-](\d{1,2})\s*호")
_YEAR_ONLY = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _valid(y, mo, d) -> str | None:
    """달력 검증(2/30 같은 불가능 날짜 배제) 후 ISO 문자열."""
    import datetime as _dt
    try:
        return _dt.date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def date_of(name: str) -> str | None:
    for m in _D1.finditer(name):                     # 달력 유효한 첫 후보 채택
        v = _valid(m.group(1), m.group(2), m.group(3))
        if v: return v
    for m in _D1_LOOSE.finditer(name):               # 비0패딩(구분자 필수) 폴백
        v = _valid(m.group(1), m.group(2), m.group(3))
        if v: return v
    # 월이름: 모든 후보 순회(앞선 비-월 3글자 토큰에 가로막히지 않게 finditer)
    for m in re.finditer(r"([A-Za-z]{3})[a-z]*[-_ ](20\d{2})", name):
        mon = _MON.get(m.group(1).lower())
        if mon: return f"{m.group(2)}-{mon:02d}-01"
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
    for m in _D3.finditer(name):
        v = _valid("20" + m.group(1), m.group(2), m.group(3))
        if v: return v
    # 아래는 2026-07-07 추가: 날짜미상 695건 실측 분석(§9)에서 드러난 패턴들.
    # 연도 먼저 + 일-일 + 월이름(Asian Metal Weekly류, "...-2022-24-28-Jan.pdf") — 378건 중 187건 매치
    m = _YMD_MON_SUFFIX.search(name)
    if m:
        mon = _MON.get(m.group(4)[:3].lower())
        if mon:
            v = _valid(m.group(1), mon, m.group(2))   # 시작일 기준
            if v: return v
    # 한글 "YYYY년 MM월"
    m = _KOR_YM.search(name)
    if m: return f"{m.group(1)}-{int(m.group(2)):02d}-01"
    # "YYYY_N호"(계간지 등 발행회차) — 월 특정 불가, 연도 중반으로 근사
    m = _YEAR_ISSUE.search(name)
    if m: return f"{m.group(1)}-07-01"
    # 연도만(월/일 구분자 없는 연간 발행물, 예: "광업요람_2024.pdf") — 최후순위, 연도 중반 근사
    m = _YEAR_ONLY.search(name)
    if m:
        y = int(m.group(1))
        if 2000 <= y <= 2035:
            return f"{y}-07-01"
    return None
