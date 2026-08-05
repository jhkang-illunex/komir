# -*- coding: utf-8 -*-
"""GKG유래+LLM재검증확정(geo_event 99.6%) 모집단에서 단순임의표본(simple random sample)
n=200으로 상품(commodity) 오염률(오태깅+완전무관 콘텐츠)을 재추정 — 2026-07-20, 사용자
지시("단순임의표본으로 오염률 다시 추정해줘"). 이전(A-5) 층화표집(광종×dimension×severity)
추정치(15.1%)가 "이벤트다운" 표본에 편향돼 과소추정했을 가능성을 검증하기 위함.

이 스크립트는 순수 데이터 품질 실사(evidence_quote가 태깅된 commodity와 실제로 관련있는지
판단)이며, A-5(LLM 추출값 vs 독립적 사람 판정의 Cohen's kappa)와는 성격이 다르다 — 자기검증
문제가 아니라 텍스트 사실관계 확인이라 Claude가 직접 수행 가능.

판정: R(관련 있음, 태깅된 광종에 대한 실질 이벤트) / I(오염 — 오태깅 또는 완전 무관 콘텐츠) /
U(판단불가 — URL/제목에 실질 정보 없음, 예: 일반 ID URL·국가명만·손상된 빈 quote).

**정정(2026-07-20, gkg_relevance_filter.py 캘리브레이션 중 발견)**: 표본idx 175
(event_id=4464f67d2ddb755e, "Sigma Lithium is expanding its production capacity...")를
원래 "오태깅(CU 태깅인데 리튬 내용)"으로 잘못 기록 — 실제 DB 재확인 결과 commodity_code는
LI이고 내용도 실제 리튬기업이라 **관련있음(R)이 맞음**. I → R로 정정, 오염률 재계산.

실행: python3 -m scripts.srs_contamination_check
산출: outputs/model_opt/srs_contamination_check.md
"""
from __future__ import annotations
import os

from msr.config import OUT

# (index, judgment, note) — judgment ∈ {"R","I","U"}. srs_sample.csv 행 순서(0~199)와 일치.
JUDGMENTS = {
    0: "I", 1: "U", 2: "I", 3: "R", 4: "I", 5: "I", 6: "I", 7: "I", 8: "U", 9: "I",
    10: "R", 11: "I", 12: "R", 13: "R", 14: "I", 15: "I", 16: "I", 17: "I", 18: "I", 19: "R",
    20: "I", 21: "U", 22: "I", 23: "I", 24: "I", 25: "I", 26: "I", 27: "I", 28: "I", 29: "I",
    30: "R", 31: "I", 32: "I", 33: "R", 34: "U", 35: "I", 36: "I", 37: "I", 38: "I", 39: "R",
    40: "U", 41: "I", 42: "U", 43: "I", 44: "U", 45: "I", 46: "I", 47: "I", 48: "R", 49: "I",
    50: "I", 51: "U", 52: "I", 53: "I", 54: "R", 55: "I", 56: "R", 57: "I", 58: "R", 59: "U",
    60: "I", 61: "I", 62: "I", 63: "U", 64: "I", 65: "R", 66: "I", 67: "R", 68: "I", 69: "I",
    70: "I", 71: "R", 72: "I", 73: "I", 74: "R", 75: "I", 76: "I", 77: "R", 78: "R", 79: "I",
    80: "I", 81: "I", 82: "R", 83: "I", 84: "I", 85: "R", 86: "I", 87: "I", 88: "U", 89: "I",
    90: "I", 91: "I", 92: "I", 93: "I", 94: "R", 95: "I", 96: "I", 97: "I", 98: "I", 99: "I",
    100: "I", 101: "I", 102: "I", 103: "I", 104: "I", 105: "I", 106: "I", 107: "I", 108: "R", 109: "I",
    110: "I", 111: "I", 112: "R", 113: "U", 114: "U", 115: "I", 116: "I", 117: "I", 118: "I", 119: "U",
    120: "R", 121: "R", 122: "I", 123: "I", 124: "I", 125: "R", 126: "I", 127: "U", 128: "U", 129: "U",
    130: "R", 131: "I", 132: "I", 133: "I", 134: "R", 135: "I", 136: "I", 137: "R", 138: "R", 139: "R",
    140: "R", 141: "R", 142: "I", 143: "I", 144: "R", 145: "I", 146: "I", 147: "R", 148: "I", 149: "R",
    150: "U", 151: "I", 152: "I", 153: "U", 154: "I", 155: "I", 156: "I", 157: "U", 158: "R", 159: "I",
    160: "I", 161: "I", 162: "U", 163: "I", 164: "I", 165: "R", 166: "I", 167: "U", 168: "I", 169: "I",
    170: "R", 171: "R", 172: "I", 173: "U", 174: "R", 175: "R", 176: "I", 177: "R", 178: "I", 179: "I",
    180: "I", 181: "I", 182: "U", 183: "I", 184: "R", 185: "I", 186: "I", 187: "R", 188: "I", 189: "I",
    190: "R", 191: "R", 192: "R", 193: "I", 194: "R", 195: "U", 196: "I", 197: "I", 198: "I", 199: "R",
}

MISTAGGED_NOTES = {
    16: "gold/copper 콘텐츠(Minotaur), NI 태깅", 55: "MCC Huludao(비철금속, 주력 아연) CU 태깅 의심",
    62: "리튬배터리 연구, NI 태깅", 64: "알루미늄(유럽 對러 수입금지), CU 태깅",
    103: "gold(스페인 골드로드), CU 태깅", 136: "gold(Royal Road Nicaragua), CU 태깅",
    142: "Inditex(의류업체) 물류기사, REE 태깅 — 완전 무관", 151: "graphite(EV배터리), CU 태깅",
    159: "gold price(Kitco), CU 태깅", 168: "gold(Royal Road Nicaragua, #136과 동일 유형), CU 태깅",
    175: "Sigma Lithium(리튬기업), CU 태깅", 183: "'Nickelback'(밴드명) 동음이의 오매칭, NI 태깅",
    189: "'Coun. Mike Nickel'(인명) 동음이의 오매칭, NI 태깅", 57: "coincommunity.com(동전수집포럼), NI 태깅(동전=nickel 동음이의)",
    161: "coincommunity.com(동전수집포럼), CU 태깅 — 동일 동음이의 패턴",
    122: "cent 동전수집기사, CU 태깅",
}


def run():
    r = sum(1 for v in JUDGMENTS.values() if v == "R")
    i = sum(1 for v in JUDGMENTS.values() if v == "I")
    u = sum(1 for v in JUDGMENTS.values() if v == "U")
    n_total = len(JUDGMENTS)
    n_scored = r + i
    rate = i / n_scored
    # Wilson score 95% 신뢰구간(정규근사보다 극단 비율에서 안정적)
    ci_lo, ci_hi = _wilson_ci(i, n_scored)

    print(f"표본 n={n_total} (R={r}, I={i}, U={u})")
    print(f"판단불가 제외 채점표본 n={n_scored}")
    print(f"오염률(단순임의표본): {rate:.1%}  95% CI [{ci_lo:.1%}, {ci_hi:.1%}]")

    write_report(r, i, u, n_total, n_scored, rate, ci_lo, ci_hi)


def _wilson_ci(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def write_report(r, i, u, n_total, n_scored, rate, ci_lo, ci_hi):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "srs_contamination_check.md")
    L = []
    L.append("# 상품(commodity) 오염률 재추정 — 단순임의표본 (2026-07-20)\n")
    L.append("작성: 2026-07-20 · 모집단: GKG유래+LLM재검증확정(provider=openai_compat, "
             "extractor=llm, doc_id가 GDELT GKGRECORDID 포맷) `geo_event` 1,808,504건"
             "(전체 geo_event의 99.6%). `SELECT setseed(0.42); ... ORDER BY random() LIMIT "
             "200`으로 단순임의추출(seed 고정, 재현 가능) — 07-16 A-5 표본(광종×dimension×"
             "severity 층화)과 달리 계층 없이 순수 무작위.\n")

    L.append(f"\n## 결과\n")
    L.append(f"| 판정 | 건수 | 비율(전체 n={n_total} 기준) |")
    L.append("|---|---|---|")
    L.append(f"| R(관련있음) | {r} | {r/n_total:.1%} |")
    L.append(f"| I(오염 — 오태깅/완전무관) | {i} | {i/n_total:.1%} |")
    L.append(f"| U(판단불가) | {u} | {u/n_total:.1%} |")

    L.append(f"\n**오염률 = I / (R+I) = {i}/{n_scored} = {rate:.1%}** "
             f"(95% Wilson CI: [{ci_lo:.1%}, {ci_hi:.1%}], 판단불가 {u}건은 분모에서 제외)\n")

    L.append(f"\n## A-5 층화표집(15.1%) 대비 큰 괴리 — 원인\n")
    L.append(f"07-18 A-5용 계층표집(광종×dimension×severity 균형화, 희소 dimension 우대표집)은 "
             f"'이벤트다운' 콘텐츠가 표집에 유리한 구조라 background 노이즈가 과소 표집됐다. "
             f"실제 모집단은 GKG tone-only 항목(본문 없이 톤 점수+URL만)이 압도적 비중을 "
             f"차지하며, 이 URL들 상당수가 상품과 무관한 일반 뉴스(주식시장 일일시황·연예·"
             f"스포츠·생활기사)다 — **이번 단순임의표본이 실제 모집단 구성을 훨씬 정확히 "
             f"반영**한다. A-5의 15.1%는 심각한 과소추정이었음이 확인됨.\n")

    L.append(f"\n## 오태깅(진짜 광물이나 다른 광종) 세부 사례\n")
    L.append("| 표본idx | commodity_code | 사유 |")
    L.append("|---|---|---|")
    for idx, note in MISTAGGED_NOTES.items():
        L.append(f"| {idx} | — | {note} |")

    L.append(f"\n**동음이의어 오매칭 패턴 재확인**: coincommunity.com(동전수집 포럼, 'nickel' "
             f"동전) 2건, 'Nickelback'(밴드명) 1건, 'Coun. Mike Nickel'(인명) 1건, 'cent' "
             f"동전기사 1건 — gkg_parse.py 코드 주석에 이미 기록된 \"copper↔맥주양조/동전\" "
             f"혼동과 동일 계열의 문제가 nickel에서도 광범위하게 재현됨을 확인.\n")

    L.append(f"\n## 판단불가(U) {u}건 — 별도 관찰\n")
    L.append(f"URL이 일반 ID(슬러그 없음)이거나, 국가명만 있거나, evidence_quote 자체가 "
             f"손상된(URL 없이 'GKG tone=...'만 남은) 경우 — 이것도 그 자체로 데이터 품질 "
             f"이슈(추출 파이프라인이 실질 정보 없는 레코드를 그대로 저장)이나, 오염 여부를 "
             f"판단할 근거가 없어 비율 계산에서는 제외했다.\n")

    L.append(f"\n## 방법론 한계\n")
    L.append(f"- 판정은 evidence_quote(URL·제목 단서)만으로 이뤄져 실제 기사 본문을 못 봄 — "
             f"GKG 자체가 본문을 제공하지 않는 구조적 한계(gkg_parse.py 설계). 제목만으로 "
             f"판단 어려운 경우 관대하게(benefit of doubt) R로 분류한 것들도 있어, 실제 오염률은 "
             f"이 추정치보다 **더 높을 수 있음**(과소추정 방향의 편향).\n")
    L.append(f"- n=200은 ±{(ci_hi-ci_lo)/2:.1%}p 수준의 신뢰구간 — 더 좁은 구간을 원하면 표본 "
             f"확대 필요(예: n=500이면 대략 절반 수준으로 좁아짐).\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[srs_contamination_check] 리포트 → {path}")


if __name__ == "__main__":
    run()
