# -*- coding: utf-8 -*-
"""GKG 관련성 판정 필터 — gkg_parse.py/gkg_verify.py 공통 사용 (2026-07-20 /goal 재설계).

배경: 07-20 단순임의표본(n=200) 기반 오염률 재추정 결과 71.4%(정정후) — 기존 SECONDARY_SIGNAL_
KEYWORDS 게이트가 CO/LI/REE(키워드매칭 광종)에만 걸리고 CU/NI(GDELT 전용 테마코드 매칭)는
아예 관련성 검사를 안 거치는 구조적 공백이 근본 원인으로 확인됨(WORKLOG 2026-07-20 참조).

반복 튜닝 이력(상세: mineral_supply_risk/outputs/model_opt/gkg_relevance_filter_calibration.md):
  v1(범용 채굴 키워드만): 정확도 85.1%
  v2(상품별 이름·생산기업 인식 추가): 92.6%
  v3(신호 우선순위 3단 재조정 — 회사명이 NOISE보다 우선, 상품명 단어는 NOISE 통과 후에만 인정): 93.7%
  v4(전부 단어경계(\\b) 매칭 전환 — "ore"가 "before"/"forecast"에 부분매칭되던 버그를
     독립 검증표본(n=150, 다른 seed)에서 발견해 수정): 94.3%(캘리브레이션) / 독립셋도 90%대 중반
     — 이 버전.

사용처:
  - geo/gkg_parse.py — 파싱 시점(evidence_quote 생성 전 kw_haystack)에 전 상품(CU/NI 포함) 게이트.
  - geo/gkg_verify.py — LLM 재검증 전/후 2차 안전망(선택적).
  - mineral_supply_risk/scripts/gkg_backfill_relevance.py — 기존 1.8M 데이터 소급 정제.
  - mineral_supply_risk/scripts/gkg_relevance_filter.py — 캘리브레이션 하네스(이 모듈을 re-export).
"""
from __future__ import annotations
import re

COMMODITY_NAMES = {
    "CU": ("copper",),
    "NI": ("nickel",),
    "CO": ("cobalt",),
    "LI": ("lithium",),
    "REE": ("rare earth", "neodymium", "ndfeb", "nd magnet", "dysprosium"),
}

# 주요 생산기업(2026-07-20 표본에서 실제 관찰된 것 + 업계 주지 기업 — 완전한 목록 아님,
# 소급 정제 재실행 시 관찰된 회사명으로 계속 보강 권고).
#
# 2026-07-20 /goal 정제 후 SRS 재검증(n=200)에서 발견: BHP/Glencore/Teck/Rio Tinto/Anglo
# American/Zijin/Votorantim/Vale/Eramet 같은 "다각화 대기업"을 회사명 목록에 넣으면 그 회사의
# 구리·니켈과 무관한 사업(석탄·아연·철광석 등)이나 일반 주식뉴스까지 관련으로 오인정하는 부작용이
# 큼(실측: 정제 후 관련성 75.0%로 목표 90% 미달, 원인 분석 결과 이 부작용이 지배적).
# 단일 상품 특화 기업(Freeport·Codelco·First Quantum 등)은 회사명만으로 자동 인정해도 안전하지만,
# 다각화 대기업은 회사명 대신 **그 회사의 특정 구리/니켈 자산명**(Escondida 등)만 신호로 인정 —
# 이러면 "BHP's Escondida"(구리광산 특정)는 여전히 잡히고 "BHP Group 주식 매수"(일반) 는 걸러진다.
COMMODITY_COMPANIES = {
    "CU": ("freeport-mcmoran", "freeport", "southern copper", "codelco",
           "antofagasta", "kghm", "first quantum", "hudbay", "ivanhoe", "turquoise hill",
           "metminco", "panoro", "ero copper", "capstone",
           "mmg", "amarc",
           "luminex resources", "aldebaran", "atlantic richfield",
           "jubilee metals",
           # 다각화 대기업 자체명 대신 그 회사의 구리 특화 자산명만(위 설명 참조).
           "escondida", "oyu tolgoi", "bougainville", "panguna",
           # 2026-07-20 2차 재확인(n=40)에서 확정 오탐 발견: Katanga는 Glencore의 DRC 구리-코발트
           # 광산(회사명 아닌 지명/자산명이라 위 원칙과 동일하게 특화 신호로 추가).
           "katanga"),
    "NI": ("norilsk", "sherritt", "igo", "panoramic resources", "western areas",
           "nickel 28", "dundas minerals", "pt vale indonesia",
           "victory nickel", "gungnir", "moho resources",
           # 2026-07-20 2차 재확인(n=40)에서 확정 오탐 발견: Thompson, Manitoba는 Vale의 대표
           # 니켈광산 도시 — "thompson" 단독은 흔한 인명/지명이라 오탐 위험 커서 복합구문으로 한정.
           "thompson manitoba"),
    "CO": ("china molybdenum", "cmoc", "erg", "umicore", "jervois", "huayou"),
    "LI": ("albemarle", "sqm", "ganfeng", "sigma lithium", "pilbara minerals", "livent",
           "allkem", "core lithium", "piedmont lithium", "tianqi"),
    "REE": ("lynas", "mp materials", "china northern rare earth", "iluka",
             "american rare earths"),
}

# 2026-07-20 정제 후 SRS 재검증(2회, n=200×2)에서 확정: 상품명 단어 단독 매칭(NAME_RE)이
# "Copper River"(강 이름)·"Copper Mountain College"(대학)·"Nickel Boys"(영화)·"a nickel"
# (5센트 동전 속어)·"Copper Moose"(식당) 같은 지명/브랜드/속어 동음이의어를 계속 통과시켜
# 관련성 실측이 72~75%에 머무름(목표 90% 미달)을 확인 — 개별 동음이의어를 하나씩 막는 건
# 발산적(끝이 없음)이라, 상품명 단독 매칭 시 시장/생산 맥락어가 함께 있어야만 인정하도록
# 구조를 바꾼다(공급위기 진단 시스템 목적상 시장/공급 맥락 없는 상품명 언급은 애초에 무관).
MARKET_CONTEXT_KEYWORDS = (
    "price", "prices", "pricing", "output", "production", "produce", "produces",
    "demand", "supply", "market", "markets", "futures", "spot",
    "rise", "rises", "rising", "fall", "falls", "falling", "gain", "gains",
    "slip", "slips", "slump", "slumps", "rally", "rallies", "surge", "surges",
    "dip", "dips", "steady", "climb", "climbs", "advance", "advances",
    "surplus", "deficit", "shortage", "export", "exports", "import", "imports",
    "trade", "tariff", "tariffs", "inventory", "inventories", "stockpile",
    "stockpiles", "reserves", "grade", "assay", "resource", "resources",
    "project", "guidance", "quarter", "earnings", "revenue", "output",
    "shipment", "shipments", "supply chain", "sanction", "embargo",
    "sale", "sales", "sold", "sell", "sells", "selling", "divest", "divestment",
    "acquisition", "acquire", "acquires", "acquired",
)

# 범용 채굴·공급망 문맥어(상품명이 명시되지 않아도 이 정도는 있어야 최소 신호로 인정 —
# CU/NI처럼 GDELT 전용 테마코드로 이미 매칭된 것을 보강하는 약한 신호 용도). 지정학/무역
# 일반어(sanction·embargo·tariff·strike 등)는 광물 맥락 없이도 너무 흔해 제외 — 채굴·생산
# 밸류체인에 실제로 특화된 어휘만 남긴다. **전부 단어경계 매칭**(예: "ore"가 "before"/
# "forecast"/"forest"에 부분매칭되는 걸 막기 위해 짧은 단어일수록 특히 중요).
GENERIC_MINING_KEYWORDS = (
    "mine", "mines", "mined", "mining", "miner", "miners", "smelter", "smelters", "smelting",
    "refinery", "refineries", "refining",
    "concentrate", "concentrator", "ore", "ores", "tonne", "tonnes", "metric ton",
    "grams per tonne", "drilling", "drill", "exploration", "prospecting",
    "deposit", "deposits",
    "porphyry", "royalty", "royalties", "extraction", "beneficiation", "base metals",
    "feedstock",
    "critical minerals", "flotation", "anode", "alloy", "alloys", "geophysics",
    "geophysical", "flotation plant", "metallurgical",
)
# 알려진 다른(추적대상 외) 금속 전문기업 — 상품명 없이 이 회사명만 있으면 오태깅 강한 의심.
OTHER_METAL_COMPANIES = ("royal road resources",)

# 다른 추적대상 외 금속/원자재 — 이게 등장하고 태깅된 상품명 자체가 없으면 오태깅 강력 의심.
OTHER_METALS = ("gold", "lead", "zinc", "aluminum", "aluminium", "tin", "silver",
                 "iron ore", "platinum", "palladium", "crude oil", "natural gas",
                 "graphite", "antimony", "tungsten", "manganese", "uranium",
                 "molybdenum", "chromium", "vanadium")

# 평범한 다어(multi-word) 노이즈 구문 — GKG evidence_quote가 URL 슬러그(하이픈 구분)인
# 경우가 대다수라 공백을 [-\s]로 유연 매칭해야 실제로 걸린다(2026-07-20 발견: "water fixtures"
# 리터럴이 실제 데이터의 "water-fixtures"를 못 잡던 치명적 버그 — NOISE_PATTERNS 전체가
# 이 문제를 안고 있어서 아래처럼 _wb_pattern과 동일한 하이픈/공백 유연화를 거친다).
NOISE_PHRASES = (
    "wall street", "stock market", "closing prices for", "stock futures",
    "golden globe", "gladiator", "ghost town", "pet of the day", "hiking trail",
    "cent coins", "cent coin", "graphics card", "hardware review",
    "toxic sulfur", "metal-organic framework", "congestion tax",
    "buy signal on oil", "noncompete agreement", "river salmon", "video game",
    "oil prices", "auto workers", "anti-russia sanction", "russia sanction",
    "reverse osmosis", "national forest", "pile burns", "healthful uses",
    "australian dollar forecast", "water fixtures", "forum topic",
)
# 이미 정규식 문법(앵커·수량자·대체)을 쓰는 패턴 — 그대로 유지.
NOISE_REGEX = (
    r"\bstocks?\s+(slip|rise|edge|jump|fall|drop|slide|surge|dip|steadie)",
    r"\btsx\b", r"\bdow\b", r"\bnasdaq\b", r"\basx\b", r"\bs&p\s*500\b",
    r"\bloonie\b", r"\byen\b", r"\bfed rate\b", r"\bfomc\b",
    r"\bgrammy\b", r"\bgala\b", r"\bfashion\b", r"\bskincare\b",
    r"\brecipe\b", r"\bwine\b", r"\bmovie\b", r"\bdocumentary\b",
    r"\bjewelry\b", r"\bcosmetics\b", r"\bchairlift\b",
    r"\bfishing\b", r"\bbeach\b", r"\bhurricane\b",
    r"\bcoincommunity\b", r"\bnumismatic\b", r"quarters?[-\s](is|are)[-\s]worth",
    r"\bpenny\b", r"\bnickelback\b", r"\bcoun\.?\s+\w+\s+nickel\b",
    r"forum/topic", r"topic_id=", r"ad_vault", r"pdfdisplayad",
    r"\[quote from text\]", r"^\[.*\]$",
    # 2026-07-20 삭제대상 재확인(n=50)에서 발견: "drone"이 실제 탐사기업의 UAV 지질조사 보도자료
    # ("Fabled Copper Corp...UAV drone mission survey")까지 상품명 매칭보다 먼저 걸러버린 확정
    # 오탐(false negative) — 소비자 드론 리뷰 배제라는 원래 목적보다 탐사 드론조사 누락 피해가
    # 더 크다고 판단해 제거.
    r"\bearbuds\b", r"\bgpu\b",
    r"exoskin|eskin", r"\bimmigration\b",
    r"guides?/\d+/",
    r"\bopec\b", r"\buaw\b",
    r"\bausd\b",
    # 2026-07-20 정제 후 SRS 재검증(n=200×2)에서 발견: 상품명이 지명·브랜드·관용구의 일부로
    # 쓰이는 동음이의어들 — 광업/시장과 무관함이 명백해 노이즈로 명시 배제.
    r"\bcopper[-,\s]+river\b", r"\bcopper[-,\s]+mountain[-,\s]+college\b",
    r"\bcopper[-,\s]+country\b", r"\bcopper[-,\s]+cove\b", r"\bcopper[-,\s]+moose\b",
    r"\bnickel[-,\s]+plate\b", r"\bnickel[-,\s]+boys\b",
    r"(down|up)[-,\s]+a[-,\s]+nickel\b", r"\bnickel[-,\s]+per[-,\s]+gallon\b",
    r"\bnickel-and-dime\b",
    # 2026-07-20 3차 정제 신규 제거대상 재확인(n=50)에서 추가 확정: 가정용품/보석/동전수집/
    # 지명/무관 브랜드가 "copper"/"nickel" 단어를 포함하는 사례들. GKG evidence_quote는
    # URL 슬러그(하이픈)가 많아 다어 구문은 전부 [-,\s]+로 유연 매칭 필요(NOISE_PHRASES와
    # 동일한 문제 — 이 구간은 NOISE_REGEX라 _wb_pattern 자동변환을 안 받으므로 수동 처리).
    r"\bfaucet\b", r"\bbathroom\b", r"\bkitchen[-,\s]+sink\b", r"\bkitchen[-,\s]+knobs?\b",
    r"\bfrying[-,\s]+pan\b", r"\bcookware\b", r"\bearrings?\b", r"\bcocktail[-,\s]+mugs?\b",
    r"\bdrinking[-,\s]+from[-,\s]+copper[-,\s]+cups?\b", r"\bcopper[-,\s]+cups?\b",
    r"\bcopper[-,\s]+canyon\b", r"\bcopper[-,\s]+harbor\b",
    r"\bcopper[-,\s]+mountain[-,\s]+technologies\b",
    r"\bcoinweek\b", r"\bheritage[-,\s]+auctions\b", r"\bimmunis[-,\s]+columbia\b",
    r"\bpossessing[-,\s]+copper[-,\s]+wire\b",
    # 2026-07-20 정제 후 최종 SRS(n=200)에서 추가 확정: 예술/선거구/주립공원/동전화폐/고고학/
    # 수질규제/개썰매경주/조리도구/절도/인명 등 상품명 단어가 산업과 무관하게 쓰이는 사례.
    r"\breuse[-,\s]+century[-,\s]+old[-,\s]+copper\b",
    r"\bnickel[-,\s]+belt[-,\s]+(ndp|candidate|election|riding|mpp?)\b",
    r"\bcopper[-,\s]+falls[-,\s]+state[-,\s]+park\b",
    r"\bkeep[-,\s]+their[-,\s]+copper[-,\s]+coins\b", r"\bcopper[-,\s]+coins?\b",
    r"\bancient[-,\s]+egyptian[-,\s]+papyri\b",
    r"\bwater[-,\s]+quality[-,\s]+criteria[-,\s]+for[-,\s]+copper\b",
    r"\bcopper[-,\s]+basin[-,\s]+\d+[-,\s]+sled[-,\s]+dog\b",
    r"\bstores[-,\s]+her[-,\s]+copper[-,\s]+pans\b", r"\bcopper[-,\s]+pans\b",
    r"\blight[-,\s]+rail[-,\s]+copper[-,\s]+thefts?\b",
    r"\bmichael[-,\s]+copper\b",
)


def _wb_pattern(words: tuple[str, ...]) -> str:
    """각 단어/구를 단어경계(\\b)로 감싸 부분문자열 오탐(예: "ore"가 "before"에 매칭)을 방지.
    GKG evidence_quote는 URL 슬러그(하이픈 구분, "critical-minerals")가 많아 다어 구문의
    공백을 "공백/하이픈/쉼표" 중 하나로 유연 매칭(2단계 재조정 — "critical minerals"가
    "critical-minerals-markets"를 못 잡던 문제; 2026-07-20 추가 — "Thompson Manitoba"가
    실제 데이터의 "Thompson, Manitoba"(쉼표+공백)를 못 잡던 문제)."""
    parts = []
    for w in words:
        esc = re.escape(w).replace(r"\ ", r"[-,\s]+")
        parts.append(rf"\b{esc}\b")
    return "|".join(parts)


_NOISE_RE = re.compile(_wb_pattern(NOISE_PHRASES) + "|" + "|".join(NOISE_REGEX), re.IGNORECASE)
_GENERIC_RE = re.compile(_wb_pattern(GENERIC_MINING_KEYWORDS), re.IGNORECASE)
_MARKET_RE = re.compile(_wb_pattern(MARKET_CONTEXT_KEYWORDS), re.IGNORECASE)
_OTHER_RE = re.compile(_wb_pattern(OTHER_METALS), re.IGNORECASE)
_NAME_RE = {cc: re.compile(_wb_pattern(names), re.IGNORECASE) for cc, names in COMMODITY_NAMES.items()}
_COMPANY_RE = {cc: re.compile(_wb_pattern(cos), re.IGNORECASE) for cc, cos in COMMODITY_COMPANIES.items()}
_OTHER_CO_RE = re.compile(_wb_pattern(OTHER_METAL_COMPANIES), re.IGNORECASE)


def is_relevant(text: str, commodity: str) -> bool:
    """text가 태깅된 commodity(CU/NI/CO/LI/REE)와 실제로 관련 있는지 판정.

    신호 우선순위(2026-07-20 4단 재조정 — 정제 후 SRS 재검증 2회에서 발견한 지명/브랜드
    동음이의어 문제 대응):
      1) **생산기업명 매칭은 무조건 최우선**(가장 특이적 신호) — "Hudbay Minerals (TSX: HBM)
         price target raised"처럼 진짜 관련기사가 거래소 티커(TSX) 노이즈 패턴에 걸려
         누락되는 문제 방지.
      2) NOISE_PATTERNS 확인 — 여기서 걸리면 거부.
      3) **상품명 단어 매칭은 시장/생산 맥락어(MARKET_CONTEXT_KEYWORDS) 또는 범용 채굴어
         (GENERIC_MINING_KEYWORDS)가 함께 있어야만 인정** — 단순 단어 매칭만으로는 "Copper
         River"(강 이름)·"Copper Mountain College"(대학)·"Nickel Boys"(영화)·"a nickel"
         (5센트 동전 속어) 같은 지명/브랜드/속어를 걸러낼 수 없음이 실측(정제 후 SRS n=200×2,
         관련성 72~75%로 목표 90% 미달)으로 확인됨 — 공급위기 진단 목적상 시장/생산 맥락이
         전혀 없는 상품명 언급은 애초에 무관하다고 봄이 타당.
      4) 타금속·범용 채굴어 순.
    모든 키워드 매칭은 단어경계(\\b) 기준 — 부분문자열 오탐 방지.
    """
    if not text or commodity not in COMMODITY_NAMES:
        return False
    t = text.lower()

    if _COMPANY_RE[commodity].search(t):
        return True

    if _NOISE_RE.search(t):
        return False

    # 2026-07-20 "시장맥락어 co-occurrence 요구" 시도 — 정제 후 SRS로 검증한 결과 과잉수정으로
    # 판명(시장/기업행위 어휘가 사실상 무한정: retreats/hovers/plunge/steadies/premiums/mineral
    # ization/anomalies/property/spin-out/reorganisation 등 전부 나열 불가능 — 신규 제거대상
    # 재확인 n=50에서 60%가 오탐으로 확정, 즉시 롤백). 대신 실제 관찰된 동음이의어를 NOISE에
    # 정확히 등재하는 원래 방식(회사명>노이즈>상품명)으로 유지 — MARKET_CONTEXT_KEYWORDS는
    # 참고용으로만 남겨두고 게이트에는 쓰지 않는다.
    if _NAME_RE[commodity].search(t):
        return True

    # 다른 "추적 대상 5종 중 하나"(우리가 잡는 상품이지만 태깅된 것과 다른 상품)의 이름이
    # 등장하면 교차 오태깅(예: NI 태깅인데 "lithium" 언급) — 이것도 OTHER_METALS와 동일하게
    # 거부 대상(2026-07-20 독립 검증표본에서 발견: "Chile...nationalize lithium mining"이
    # NI로 태깅된 사례).
    for other_cc, other_re in _NAME_RE.items():
        if other_cc != commodity and other_re.search(t):
            return False

    # 상품명 자체는 없지만 다른 추적대상 외 금속·금속기업이 등장 → 오태깅 강한 의심(거부).
    if _OTHER_RE.search(t) or _OTHER_CO_RE.search(t):
        return False

    # 상품명도 타금속도 없는 경우: 범용 채굴 문맥어가 있으면 약한 신호로 인정
    # (CU/NI는 GDELT 전용 테마로 이미 1차 검증됐다는 전제하의 보강 신호).
    return bool(_GENERIC_RE.search(t))
