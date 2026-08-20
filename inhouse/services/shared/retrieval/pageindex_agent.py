# -*- coding: utf-8 -*-
"""PageIndex 에이전틱 순회 — pageindex.py 모듈독스트링이 후속과제로 남긴 "LLM이
목차 트리를 타고 들어가며 탐색"하는 층. `documents/meta/CONTAINER_ARCHITECTURE.md`
§5-4 ③이 그리던 범위이자, chatbot_graph.py 2026-08-13 절 "3차 실측"에서 실측
확인된 한계 — 국가별·순위·집계형 질문(예: "그 나라 2번째로 많이 나는 광종은?",
"1위 생산국과의 생산량 차이는?")은 검색어를 아무리 잘 바꿔도 단발 검색
(pageindex.lookup) 1회로 못 푼다. USGS Mineral Commodity Summaries가 광종별로
조직돼 있어("국가별" 조직이 아님) 국가 순위를 답하려면 여러 광종 섹션을 훑어
국가별 수치를 대조(에이전틱 집계)해야 하기 때문이다.

**실측으로 발견한 데이터 함정 두 가지(코드로 우회, 데이터 자체는 안 건드림)**:
1. `data_lake/semi_structure/okf_documents/생산매장량_USGS/USGS_{2019,2020,
   2021,2023,2024,2025,2026}.md`에서 CU/NI/CO/LI(구리·니켈·코발트·리튬) 4개
   광종의 "######" 헤딩이 PDF→MD 변환에서 통째로 유실됐다(`pageindex_trees`의
   해당 문서 트리에 그 광종 노드가 아예 없음 — `grep -c "^#+\\s*COPPER$"` 등으로
   재현 확인). 헤딩이 4개 광종 전부 온전한 연도판은 `USGS_2022.md` 하나뿐이다.
   `pageindex.search_nodes()`/`toc()`는 트리 노드 기반이라 이 4개 광종을 그
   나머지 연도판에서는 절대 못 찾는다.
2. 하지만 헤딩만 유실됐을 뿐 **본문(국가별 세계생산량 표 포함)은 원문에
   그대로 남아 있다**(실측 확인 — `USGS_2024.md` 3385행 부근에 COPPER의
   "World Mine and Refinery Production and Reserves" 표가 온전한 국가별
   수치와 함께 존재하지만, 헤딩이 없어 앞 문단(비스무트 등)의 본문으로
   잘못 병합돼 있다). 그래서 이 모듈은 트리 노드 검색에 의존하지 않고 OKF
   원문 텍스트를 광종명 밀도로 직접 스캔해 "World ... Production" 단락을
   찾는다(`_find_world_production_block`) — 헤딩 유무와 무관하게 동작하고,
   여러 연도판(판마다 최근 2개년 수치)을 모아 "최근 N년" 질문에도 답할 근거를
   만들 수 있다. 연도를 하드코딩하지 않는다 — 향후 재적재로 헤딩 결함이
   고쳐지면 트리 기반 탐색도 자연히 같이 맞아떨어진다(이 모듈의 정확성은
   원문 텍스트에만 의존, 트리 상태와 무관).

트리 기반 결정적 도구(find_documents/search_nodes/read_node_text/toc,
pageindex.py)는 건드리지 않는다 — 광종 세계생산 집계가 아닌 일반 문서 탐색은
여전히 그쪽이 맡고, chatbot_graph.py는 route.pageindex_mode=="agentic"일
때만 이 모듈을 부른다("simple"이면 기존 pageindex.lookup() 그대로).

동기 함수다(KomirJsonLLM.invoke·파일 I/O 전부 블로킹) — chatbot_graph._retrieve_node
가 이미 그렇듯 ThreadPoolExecutor 안에서 호출할 것을 전제한다."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

_INHOUSE_ROOT = Path(__file__).resolve().parents[3]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from shared.llm_client import LLM_TRANSIENT_ERRORS, KomirJsonLLM  # noqa: E402
from shared.retrieval import pageindex  # noqa: E402
from shared.retrieval.evidence import Evidence  # noqa: E402

# 2026-08-13 herd 코드리뷰(비판자②)로 실측 발견한 "LLM 장애 시 근거 유실" 버그의
# 수정을 llm_client.LLM_TRANSIENT_ERRORS로 승격했다(chatbot_graph.py의 route/
# reformulate/verify 노드와 공유 — 자세한 이유는 그 상수의 docstring 참고).

MAX_AGENT_STEPS = 5  # 스텝마다 LLM 1회 왕복 — chatbot_graph.MAX_ATTEMPTS(외부 재시도)와
                      # 별개 예산. "빠른 시간내에" 요구사항상 무한 탐색은 안 함(project 관례).
MAX_EDITIONS = 3      # 광종 1건당 최대 몇 개 연도판을 모을지("최근 N년" 근거용)
_MIN_DENSITY = 3       # "World...Production" 앞 window자 안에 광종명이 최소 이만큼
                        # 나와야 그 단락을 그 광종 걸로 인정(다른 광종 단락 오탐 방지 —
                        # 근거 없이 "USGS_2022가 맞겠지" 식으로 가정하지 않기 위한 최소 방어선)
_WINDOW = 1800          # 밀도 판정에 쓰는 앞쪽 문맥 길이(글자수)
_BLOCK_MAX_CHARS = 3200 # 한 광종 표 근거로 담을 최대 글자수(국가별 표+주석 포함,
                         # 표가 잘리면 안 되므로 넉넉히 잡음 — 실측: COPPER 표까지
                         # 포함해도 3200자 안에 다 들어감)

_WORLD_PRODUCTION_RE = re.compile(r"World[^\n:]{0,60}Production[^\n:]{0,40}:", re.IGNORECASE)

#: "World ... Production:" 뒤가 실제 표가 아니라 다른 광종 챕터로 미루는
#: 상호참조 문구인 경우(실측 확인: RARE EARTHS 밀도 스캔이 YTTRIUM/SCANDIUM
#: 섹션의 "See the Rare Earths chapter." 상호참조를 오탐한 사례 — 그 문단은
#: "rare earth"를 프롬프트문에서 여러 번 언급해 밀도만 보면 진짜 RARE EARTHS
#: 챕터보다 높게 나온다) — 이런 스텁은 밀도가 아무리 높아도 기각한다.
_STUB_PREFIX_RE = re.compile(r"^\s*(?:\d+\s*)?See\b", re.IGNORECASE)
#: 실제 국가별 표는 숫자(천 단위 콤마 포함)가 촘촘하다 — 상호참조·서술형 문단과
#: 구분하는 2차 방어선(위 스텁 정규식이 못 잡는 다른 표현의 상호참조까지 포괄).
_NUMERIC_TOKEN_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\b\d{2,}\b")
_MIN_NUMERIC_TOKENS = 8

_USGS_GROUP_PREFIX = "생산매장량_USGS"

#: 코퍼스에서 실제 쓰는 표기와 어긋나는 광종명(REE 등 프로젝트 코드가 "네오디뮴"
#: 같은 별칭을 쓰더라도 코퍼스 헤딩은 "RARE EARTHS"다) — 밀도 판정용 보조 키워드만,
#: open_commodity 인자 자체는 여전히 코퍼스 표기(대문자 영문)를 요구한다.
_COMMODITY_ALIASES: dict[str, tuple[str, ...]] = {
    "RARE EARTHS": ("rare earth", "rare-earth"),
    "RARE EARTHS1": ("rare earth", "rare-earth"),
}

#: list_known_commodities()가 걸러낼 비-광종 전역 헤딩(전부 대문자라 다른 필터로는
#: 안 걸러짐) — 실측한 USGS 목차 구조 기준.
_NON_COMMODITY_TITLES = {
    "CONTENTS", "INTRODUCTION", "INSTANT INFORMATION", "KEY PUBLICATIONS",
    "WHERE TO OBTAIN PUBLICATIONS", "SIGNIFICANT EVENTS, TRENDS, AND ISSUES",
    "APPENDIX A", "APPENDIX B", "APPENDIX C", "APPENDIX D",
}


def _commodity_needles(commodity: str) -> tuple[str, ...]:
    base = commodity.strip().lower()
    extra = _COMMODITY_ALIASES.get(commodity.strip().upper(), ())
    return (base, *extra)


def _looks_like_data_table(block_text: str) -> bool:
    """상호참조 스텁("See the Rare Earths chapter." 등)을 걸러내는 2차 방어선.

    `_STUB_PREFIX_RE`가 못 잡는 다른 표현이라도, 진짜 국가별 표는 숫자(특히
    천단위 콤마)가 촘촘하다 — 서술형 문단은 보통 그 정도로 많지 않다(실측:
    RARE EARTHS 오탐 사례의 스텁 문단은 숫자 토큰 5개 미만, 진짜 표는
    20개 이상)."""

    after_colon = block_text.split(":", 1)[1] if ":" in block_text else block_text
    if _STUB_PREFIX_RE.match(after_colon.strip()):
        return False
    return len(_NUMERIC_TOKEN_RE.findall(block_text)) >= _MIN_NUMERIC_TOKENS


#: "World...Production and Reserves:" 바로 뒤에 붙는 개정 설명 문장("Reserves
#: for X were revised based on...")은 실제 국가별 수치보다 먼저 나와 인용
#: 발췌 앞부분을 차지한다 — chatbot_graph._verify_node가 근거당 앞 200자만
#: 보고 "충분한지" 판정하는데(evidence.text[:200]), 실측 확인: 이 문장이
#: 200자를 넘기면 진짜 표가 그 뒤에 있어도 verify가 "수치가 없다"고 오판해
#: 불필요한 reformulate 재시도를 태운다(코발트 실측 — 1차 검색에 정답이 이미
#: 있었는데도 재시도 발생). 표 헤더("Mine production ...")가 시작되는 첫 빈
#: 줄까지는 건너뛰어, 인용 발췌 앞머리에 실제 수치가 오게 한다.
_PREAMBLE_RE = re.compile(r"^(.*?:)\s*(.*?)\n\n", re.DOTALL)


def _promote_table_to_front(block: str) -> str:
    m = _PREAMBLE_RE.match(block)
    if m and len(m.group(2)) > 40:
        return m.group(1) + "\n\n" + block[m.end():]
    return block


#: 광종의 단위선언 줄("(Data in thousand metric tons of contained copper...)")은
#: "World...Production:"보다 훨씬 앞(그 광종 챕터 맨 앞)에 있어 블록 안에는
#: 안 잡힌다 — "생산량 차이는 얼마나 나?" 같은 질문에 단위 없이 숫자만 나오면
#: 안 되므로, World-Production 매칭 지점에서 뒤로(~3000자) 훑어 가장 가까운
#: 단위선언을 찾아 Evidence.unit으로 따로 싣는다(원문 표 자체는 안 건드림).
_UNIT_LINE_RE = re.compile(r"\(Data in [^)]{1,80}\)")
_UNIT_LOOKBACK_CHARS = 6000  # 실측: 광종 섹션 서두 단위선언~World Production 매칭 사이
                              # 거리가 3,700~5,500자대(도입부 서술이 긴 광종일수록 큼) —
                              # 3000자로는 놓치는 경우가 실제로 있어 넉넉히 늘림


def _find_unit_declaration(markdown_text: str, match_start: int) -> str | None:
    window_start = max(0, match_start - _UNIT_LOOKBACK_CHARS)
    candidates = list(_UNIT_LINE_RE.finditer(markdown_text, window_start, match_start))
    return candidates[-1].group(0) if candidates else None


def _find_world_production_block(markdown_text: str, commodity: str) -> dict | None:
    """`commodity`(영문, 대소문자 무관) 세계생산 단락을 원문에서 직접 찾는다
    (모듈 독스트링 함정 2번 — 헤딩 트리에 의존하지 않는다).

    문서 안의 모든 "World ... Production:" 매칭 각각에 대해, 그 앞 `_WINDOW`자
    안에서 광종명이 몇 번 나오는지 세어(밀도) 가장 높은 것을 고른다 — 같은
    광종 섹션이면 "구리는 ... 구리 ... 구리 생산은"처럼 광종명이 반복 등장하고,
    다른 광종 섹션이면 거의 안 나오는 경향(실측 확인: COPPER 섹션 앞 1800자
    안에 "copper" 8회 이상, 인접 DIAMOND 섹션 앞엔 0회)을 이용한다. `_MIN_DENSITY`
    미만이면 그 문서에 이 광종이 없다고 보고 다음 문서로 넘어간다(오탐보다
    누락이 안전 — 오탐은 엉뚱한 광종의 근거를 인용하게 만든다).

    밀도만으로는 안 걸러지는 오탐이 실측으로 하나 나왔다 — 희토류 계열 원소
    (이트륨·스칸듐 등)의 섹션은 "rare earth"를 서술문에서 자주 언급해서 정작
    RARE EARTHS 자신의 표보다 밀도가 더 높게 나올 수 있다. `_looks_like_data_table`
    로 후보 각각을 검증해서 통과 못 하면 밀도가 아무리 높아도 기각한다(동률이면
    문서에서 먼저 나오는 후보를 유지 — 실측상 진짜 챕터가 상호참조 챕터보다
    앞에 나오는 경향과 맞아떨어진다)."""

    needles = _commodity_needles(commodity)
    matches = list(_WORLD_PRODUCTION_RE.finditer(markdown_text))
    best: dict | None = None
    for i, m in enumerate(matches):
        window_start = max(0, m.start() - _WINDOW)
        preceding = markdown_text[window_start:m.start()].lower()
        density = sum(preceding.count(needle) for needle in needles)
        if density < _MIN_DENSITY:
            continue
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        block_end = min(block_end, m.start() + _BLOCK_MAX_CHARS)
        block = markdown_text[m.start():block_end]
        # 다음 "World...Production:" 매칭이 멀리 있으면(_BLOCK_MAX_CHARS로 잘림)
        # 다음 광종의 "(Data in ...)" 단위선언 줄까지 섞여 들어온다(실측: NICKEL
        # 블록 끝에 NIOBIUM 도입부가 붙어옴) — 블록은 "World...Production:"부터
        # 시작하므로(그 광종 자신의 단위선언은 이보다 앞쪽 문단에 있음) 블록 안에서
        # 이 패턴이 나오면 무조건 다음 광종 것이다.
        unit_line = re.search(r"\n\(Data in ", block)
        if unit_line:
            block = block[: unit_line.start()]
        block = _promote_table_to_front(block).strip()
        if not _looks_like_data_table(block):
            continue
        if best is None or density > best["density"]:
            unit = _find_unit_declaration(markdown_text, m.start())
            best = {"text": block, "density": density, "unit": unit}
    return best


def commodity_world_table(commodity: str, *, max_editions: int = MAX_EDITIONS) -> list[dict]:
    """광종 1건(영문 대문자, 예: "COPPER") -> 여러 USGS 연도판의 세계생산
    단락 목록(최신 연도부터, 밀도 판정을 통과한 것만 — `max_editions`건까지).

    각 dict: {"doc": "USGS_2024", "text": "...", "density": int}. 연도판마다
    보통 최근 2개년 수치를 담고 있어(예: USGS_2024는 2022·2023) 여러 판을
    모으면 "최근 N년 생산량" 질문에도 답할 근거가 된다(편차: 판마다 겹치는
    연도가 있을 수 있음 — 최종 판단은 생성 단계 LLM이 [근거]의 연도 라벨을
    보고 함)."""

    okf_root = Path(pageindex.OKF_DOCUMENTS_ROOT) / _USGS_GROUP_PREFIX
    if not okf_root.is_dir():
        return []
    results: list[dict] = []
    # 파일명이 "USGS_YYYY.md"라 문자열 내림차순 정렬이 곧 연도 내림차순이다.
    for path in sorted(okf_root.glob("*.md"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        block = _find_world_production_block(text, commodity)
        if block is None:
            continue
        results.append({
            "doc": path.stem, "text": block["text"], "density": block["density"], "unit": block.get("unit"),
        })
        if len(results) >= max_editions:
            break
    return results


def _candidate_titles(tree: dict) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for node, _path in pageindex.iter_nodes(tree.get("structure", [])):
        title = (node.get("title") or "").strip()
        norm = re.sub(r"\d+$", "", title).strip()
        if not norm or norm in _NON_COMMODITY_TITLES:
            continue
        letters_only = re.sub(r"[^A-Za-z]", "", norm)
        if len(letters_only) < 3 or not norm.isupper():
            continue
        if norm in seen:
            continue
        seen.add(norm)
        names.append(norm)
    return names


def list_known_commodities() -> list[str]:
    """캐노니컬 광종명 목록 — 광종 헤딩(전부 대문자 제목)을 가장 많이 잡아낸
    USGS 트리에서 뽑는다. 연도를 하드코딩하지 않는다 — 지금은 실측상 USGS_2022가
    골라지지만(91개), 향후 재적재로 다른 연도판의 헤딩 결함이 고쳐지면 그쪽이
    앞서는 순간 자동으로 넘어간다. **트리 전체 노드 수가 아니라 "광종처럼 보이는
    제목의 개수"로 비교한다** — 실측 함정: 총 노드 수 1위인 연도판(USGS_2023,
    266개)이 오히려 광종 헤딩은 24개뿐이었다(각주·Tariff 등 잡다한 하위 노드가
    많을 뿐 광종 자체 헤딩 인식률은 낮았던 사례) — 총 노드 수는 "헤딩이 온전한
    정도"의 대리지표로 안 맞는다.

    에이전트가 정확한 광종 철자를 모르거나 "이 나라가 다른 뭘 캐는지" 후보를
    넓혀야 할 때 참고용으로만 쓴다(밀도 판정 자체는 여전히 commodity_world_table이
    원문에서 다시 함)."""

    trees = [
        t for t in pageindex.load_trees()
        if str(t.get("okf_path", "")).startswith(_USGS_GROUP_PREFIX)
    ]
    if not trees:
        return []
    per_tree = [_candidate_titles(tree) for tree in trees]
    return max(per_tree, key=len)


#: USGS 표는 국가를 항상 알파벳순으로 나열한다(생산량순 아님) — 실측 확인된
#: 오답 사례: 로컬 소형 LLM이 이 표를 읽고 "콩고민주공화국이 주석 세계 2위"라고
#: 답했지만 실제로는(2025e 기준) 중국 71,000 > 인도네시아 61,000 > 페루 33,000 >
#: 브라질 28,000 > 콩고 27,000 순으로 콩고는 5위다 — 표 안에서 콩고가 China보다
#: 먼저 나온 건 그저 알파벳상 C-o가 C-h보다 뒤라서일 뿐인데, 등장 순서를 순위로
#: 착각한 것으로 보인다. `_rank_countries()`가 각 표의 국가별 첫 생산량 수치를
#: 직접 파싱해 내림차순으로 재정렬한 요약을 계산해두면, 생성 단계 LLM이 표를
#: 직접 정렬할 필요 없이 이 요약을 그대로 인용할 수 있다(advisor 권고: 프롬프트
#: 튜닝이 아니라 근거 자체에 결정적 정렬 주석을 붙일 것).
#: 2026-08-13 herd 코드리뷰(비판자②)로 실측 발견된 치명적 결함의 수정 — 원래
#: 목록이 짧아서 Turkmenistan(IODINE)·Bahrain(ALUMINUM)·Algeria/Syria
#: (PHOSPHATE ROCK)·Qatar/Kuwait/Turkmenistan(SULFUR)·Mauritania(IRON ORE)·
#: Belarus(SALT)·Burundi(TANTALUM) 같은 실제 상위권 생산국이 목록에 없어
#: 조용히 순위에서 빠지고 등수가 한 칸씩 밀려 올라가는 문제가 재현됐다(예:
#: ALUMINUM에서 Bahrain 1,620(실제 6위)이 누락되자 "6위 UAE, 7위 Australia,
#: 8위 Norway"로 전부 한 칸씩 밀린 오답). "오탐보다 누락이 안전"이라는 설계
#: 철학이 각주오염엔 지켜졌지만 국가명 커버리지엔 안 지켜진 사례 — 유엔
#: 회원국+USGS가 실제 쓰는 표기(예: "Burma", "Congo (Kinshasa)")를 기준으로
#: 거의 전체를 등재해 커버리지 공백을 최대한 없앤다. "Côte d'Ivoire"는 원문이
#: 합성문자 ô(U+00F4)·둥근 아포스트로피 ’(U+2019)를 쓴다는 것도 실측 확인—
#: 일반 오/작은따옴표로 적으면 절대 매칭 안 되던 버그도 같이 고침.
_KNOWN_COUNTRIES = sorted(
    [
        "Congo (Kinshasa)", "Congo (Brazzaville)", "Korea, Republic of", "Korea, North",
        "New Caledonia", "Papua New Guinea", "Dominican Republic", "South Africa",
        "Saudi Arabia", "Czechia", "United States", "United Kingdom", "United Arab Emirates",
        "Bosnia and Herzegovina", "North Macedonia", "Sierra Leone", "Côte d’Ivoire",
        "Burkina Faso", "Sri Lanka", "New Zealand", "Trinidad and Tobago", "Costa Rica",
        "El Salvador", "Equatorial Guinea", "Cabo Verde", "Timor-Leste", "South Sudan",
        "Solomon Islands", "Marshall Islands",
        "Afghanistan", "Albania", "Algeria", "Angola", "Andorra", "Antigua",
        "Australia", "Austria", "Argentina", "Armenia", "Azerbaijan",
        "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize",
        "Benin", "Bhutan", "Bolivia", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burma", "Burundi",
        "Cambodia", "Cameroon", "Canada", "Chad", "Chile", "China", "Colombia", "Comoros",
        "Cuba", "Cyprus",
        "Denmark", "Djibouti", "Dominica",
        "Ecuador", "Egypt", "Eritrea", "Estonia", "Eswatini", "Ethiopia",
        "Fiji", "Finland", "France",
        "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada",
        "Guatemala", "Guinea-Bissau", "Guinea", "Guyana",
        "Haiti", "Honduras", "Hungary",
        "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy",
        "Jamaica", "Japan", "Jordan",
        "Kazakhstan", "Kenya", "Kiribati", "Kosovo", "Kuwait", "Kyrgyzstan",
        "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein",
        "Lithuania", "Luxembourg",
        "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Mauritania",
        "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro",
        "Morocco", "Mozambique", "Myanmar",
        "Namibia", "Nauru", "Nepal", "Netherlands", "Nicaragua", "Niger", "Nigeria",
        "North Korea", "Norway",
        "Oman",
        "Pakistan", "Palau", "Panama", "Paraguay", "Peru", "Philippines", "Poland",
        "Portugal",
        "Qatar",
        "Romania", "Russia", "Rwanda",
        "Samoa", "San Marino", "Senegal", "Serbia", "Seychelles", "Singapore", "Slovakia",
        "Slovenia", "Somalia", "Spain", "Sudan", "Suriname", "Sweden", "Switzerland", "Syria",
        "Tajikistan", "Tanzania", "Thailand", "Togo", "Tonga", "Tunisia", "Turkey",
        "Turkmenistan", "Tuvalu",
        "Uganda", "Ukraine", "Uruguay", "Uzbekistan",
        "Vanuatu", "Venezuela", "Vietnam",
        "Yemen",
        "Zambia", "Zimbabwe",
        "Other countries", "Other",
    ],
    key=len, reverse=True,  # 긴 이름부터 매칭해야 부분 겹침(예: "Congo"가 "Congo (Kinshasa)"를 가로채는 것)을 막는다
)
_COUNTRY_RE = re.compile(
    "(?:" + "|".join(re.escape(name) for name in _KNOWN_COUNTRIES) + r")\d*"
)
#: 국가명 바로 다음 토큰이 "정상 서식의 숫자"인지 판정 — 실측으로 확정된 두
#: 가지 함정을 여기서 동시에 막는다.
#: 1) "W"(withheld)·"—"(zero/NA)처럼 그 나라의 실제 값이 없는 경우, 예전
#:    구현은 다음 숫자가 나올 때까지 뒤로 계속 찾아서 전혀 다른 열(매장량 등)의
#:    수치를 그 나라 생산량인 양 가져왔다(실측 오탐: 리튬 표에서 미국이 "W W"
#:    (생산량 비공개)인데 그 뒤 매장량 4,400,000을 생산량으로 오독). 이제는
#:    "바로 다음 토큰"만 보고, 숫자가 아니면 그 나라는 조용히 순위에서 뺀다
#:    (모르는 값을 추측해서 채우지 않는다).
#: 2) PDF→텍스트 변환에서 각주 숫자가 콤마 없이 실제 수치 앞에 들러붙는다
#:    (예: "China 14270,000" = 각주 "14" + 실제값 "270,000" — 쉼표 앞 자릿수가
#:    5자리라 "14,270,000"처럼 보이지도 않고 그냥 이어붙어 있다). 정상 서식은
#:    쉼표 앞이 항상 1~3자리다 — 이 정규식이 그 형식만 통과시킨다.
_WELL_FORMED_TOKEN_RE = re.compile(r"^e?(?:\d{1,3}(?:,\d{3})+|\d{1,3})$")
_NO_DATA_TOKENS = {"W", "—", "NA", "--", "-"}


def _first_token(text: str) -> str:
    m = re.match(r"\S+", text.lstrip())
    return m.group(0) if m else ""


def _parse_number_token(token: str) -> int | None:
    if not _WELL_FORMED_TOKEN_RE.match(token):
        return None
    digits = token[1:] if token.startswith("e") else token
    return int(digits.replace(",", ""))


_WORLD_TOTAL_RE = re.compile(r"World total \(rounded\)\s*", re.IGNORECASE)


def _table_only(block_text: str) -> str:
    """"World total" 이후(Resources·Substitutes·각주 등 서술형 구간)는 순위
    계산에서 제외한다 — 각주에 섞인 국가명+숫자(예: "9For Australia, ... 11
    million tons")가 표의 실제 생산량으로 오인되는 걸 막는 방어선."""

    m = _WORLD_TOTAL_RE.search(block_text)
    return block_text if m is None else block_text[: m.start()]


def _parse_world_total(block_text: str) -> int | None:
    m = _WORLD_TOTAL_RE.search(block_text)
    if m is None:
        return None
    return _parse_number_token(_first_token(block_text[m.end():]))


def _rank_countries(block_text: str, *, top_n: int = 8) -> list[tuple[str, int]] | None:
    """표 구간에서 국가명 바로 다음 토큰(해당 표의 첫 데이터 열)을 뽑아
    내림차순 정렬한다. 다음 중 하나라도 걸리면 이 표는 못 믿는다고 보고
    `None`을 돌려준다(호출부는 순위 없이 원문 표만 보여준다 — 오염된 순위를
    자신있게 내놓는 것보다 조용히 물러나는 쪽이 안전하다):

    - "World total" 줄 자체가 정상 서식이 아니면(각주 오염 의심) 개별 국가값도
      못 믿는다.
    - 국가명 바로 다음 토큰이 결측 마커(W/—/NA)가 아닌데도 정상 서식 숫자가
      아니면(예: "China 14270,000" — 각주 "14"가 콤마 없이 실제값 "270,000"
      앞에 들러붙음) 그 표 전체가 각주 오염됐다고 보고 즉시 기각한다. 국가
      하나만 조용히 빼고 나머지로 "부분 순위"를 내놓지 않는 이유: 오염이
      한 나라에서 관측됐다는 건 표 전체가 같은 변환 결함을 겪었을 개연성이
      높다는 뜻이고(실측: 희토류 표에서 중국·미국·미얀마 세 나라 모두 이
      패턴), 하필 오염된 행이 세계 1위 생산국인 경우(중국) "1위가 빠진
      순위"를 그럴듯하게 내놓는 게 가장 위험한 실패모드이기 때문이다.
    - 채택된 국가값 중 하나라도 world total 이상이면(개별국이 세계총계를
      넘을 수 없다) 각주 오염이 확실하다고 보고 그 표 전체를 기각한다."""

    table = _table_only(block_text)
    world_total = _parse_world_total(block_text)
    if world_total is None:
        return None

    matches = list(_COUNTRY_RE.finditer(table))
    ranked: list[tuple[str, int]] = []
    for i, m in enumerate(matches):
        name = re.sub(r"\d+$", "", m.group(0))
        window_end = matches[i + 1].start() if i + 1 < len(matches) else len(table)
        token = _first_token(table[m.end():window_end])
        if token in _NO_DATA_TOKENS or not token:
            continue  # 정당한 결측 — 오염 신호 아님, 그 나라만 순위에서 제외
        value = _parse_number_token(token)
        if value is None:
            return None  # 결측 마커도 정상 숫자도 아님 -> 각주 오염 의심, 표 전체 기각
        if value <= 0:
            continue
        if value >= world_total:
            return None  # 오염 확실 — 표 전체 기각
        ranked.append((name, value))
    ranked.sort(key=lambda item: -item[1])
    return ranked[:top_n]


_ALPHABETICAL_CAVEAT = (
    "[참고: 아래 국가 나열은 알파벳순이며 생산량 순위가 아닙니다 — 순위·비교 "
    "질문에는 반드시 수치를 직접 대조해서 판단하세요.]\n\n"
)


def _detect_focus_country(question: str) -> str | None:
    """질문 문장(보통 route가 대용어를 이미 국가명으로 풀어준 resolved_query)에
    등장하는 국가명을 찾는다 — 찾으면 그 나라를 기준으로 `_annotate_with_ranking`
    이 "이 광종에서 몇 위"를 결정적으로 계산해 붙인다(아래 함수 참고).

    2026-08-18 실측 발견 — "콩고민주공화국이 2위/3위인 다른 광종은?" 같은
    질문에서, 생성 LLM이 광종 여러 개(구리·니켈·코발트 등)의 원문 표를 눈으로
    훑어 콩고의 순위를 스스로 계산하다가 실제로는 순위표에 없는 광종(니켈)을
    "콩고가 2위"라고 잘못 답한 사례가 나왔다(같은 답변 안에 정답(구리)도
    괄호로 같이 냈지만 주된 주장은 틀렸다) — 순위 정렬 주석(_rank_countries)
    만으로는 "이 나라가 이 표에 있는지 없는지"까지는 안 알려줘서, 여러 표를
    한꺼번에 넘기면 소형 LLM이 결국 혼동했다. 첫 매칭 하나만 쓴다(질문 하나가
    여러 나라를 동시에 묻는 경우는 드물고, 과설계보다 단순함을 우선)."""

    m = _COUNTRY_RE.search(question)
    if not m:
        return None
    return re.sub(r"\d+$", "", m.group(0))


def _annotate_with_ranking(block_text: str, *, focus_countries: list[str] | None = None) -> str:
    """표 앞에 (1) 상위 8개국 순위 요약 (2) `focus_countries`(감시 대상 국가
    목록)가 있으면 각 나라의 정확한 순위(또는 "이 표에 없음") 확정문을
    덧붙인다. (2)가 특히 중요한 이유는 `_detect_focus_country` 실측 사례
    참고 — "이 나라가 이 광종 표에 있는지"를 생성 LLM이 다시 계산하게 두지
    않고 여기서 확정해서 준다.

    `focus_countries`가 여러 개인 건 `agentic_lookup`의 "감시목록 확장"
    설계 때문이다(2026-08-18, 4턴 체인 테스트) — "구리 상위 5개국 중에서
    다른 광종을 가장 많이 생산하는 나라는?" 같은 질문은 특정 국가 하나가
    아니라 이미 확정된 상위 N개국 전체를 이후에 여는 모든 광종 표와 대조해야
    답이 나온다. 국가 하나만 볼 땐 이 목록이 원소 1개일 뿐이라 기존 동작과
    같다."""

    full_ranking = _rank_countries(block_text, top_n=999)
    focus_countries = focus_countries or []
    if not full_ranking:  # None(오염 의심) 또는 빈 리스트(파싱된 국가 0건) 둘 다 동일 취급
        prefix = _ALPHABETICAL_CAVEAT
        if focus_countries:
            names = ", ".join(focus_countries)
            prefix += (
                f"[{names} 순위 확인 불가 — 이 표는 각주 오염 의심으로 자동순위 계산을 "
                f"하지 않았습니다. 순위를 단정하지 말고 원문 표를 직접 대조하세요.]\n\n"
            )
        return prefix + block_text

    display = full_ranking[:8]
    ranking_str = ", ".join(f"{i}위 {name} {value:,}" for i, (name, value) in enumerate(display, 1))
    lines = [
        f"[자동계산 순위(참고용, 표의 첫 데이터 열 기준 내림차순 — 국가 나열 "
        f"순서는 알파벳순일 뿐 순위가 아니니 아래 이 줄로 판단할 것)] {ranking_str}"
    ]
    if focus_countries:
        rank_by_name = {name: (i, v) for i, (name, v) in enumerate(full_ranking, 1)}
        parts = []
        for country in focus_countries:
            hit = rank_by_name.get(country)
            parts.append(f"{country}={hit[0]}위({hit[1]:,})" if hit else f"{country}=이 표에 없음")
        lines.append(
            "[지정 국가 순위(자동계산, 확정값 — 그대로 쓰고 스스로 다시 세지 마세요)] "
            + ", ".join(parts)
        )
    return "\n".join(lines) + "\n\n" + block_text


#: `find_uncovered_country_candidates()`가 표의 서술형 문장에서 온 잡음(예:
#: 각주·결측 마커·문서 상투어)을 국가 후보로 오인하지 않게 거르는 불용어.
#: 2026-08-18 herd 코드리뷰 후속과제③ — `_KNOWN_COUNTRIES`를 24개→약 190개로
#: 확충한 뒤, "정말 이걸로 충분한가"를 실측으로 검증하기 위해 만든 도구다.
_CANDIDATE_STOPWORDS = {
    "NA", "W", "The", "In", "Of", "See", "For", "Data", "World", "Table",
    "Other", "About", "Large", "Reserves", "Mine", "Production", "Substitutes",
    "Depletion", "Government", "Stockpile", "Recycling", "Tariff", "Import",
    "Export", "Events", "Trends", "Issues", "Domestic", "Salient", "Statistics",
    "United", "New", "Prepared", "Net", "Price", "Consumption",
}
_CANDIDATE_WORD_RE = re.compile(r"\b[A-Z][a-zA-Z.'’]{2,}\b")


def find_uncovered_country_candidates() -> dict[str, list[tuple[str, int]]]:
    """유지보수 점검용(런타임 경로에서 안 부름) — 코퍼스의 모든 광종(최신
    연도판 1개씩)을 훑어 `_COUNTRY_RE`가 모르는 "국가처럼 보이는 후보"(대문자로
    시작하는 단어 바로 뒤에 정상 서식 숫자가 오는 패턴)를 찾는다.

    실행 결과가 비면 화이트리스트가 "지금 이 코퍼스"를 다 커버한다는 뜻이다
    (2026-08-18 실측: 91개 광종 전수 스캔 결과 진짜 누락 0건, 잡음 2건뿐
    (`Wyoming`처럼 미국 국내 통계 문장에서 온 것) — 완전한 커버리지의 "증명"은
    아니지만 이 코퍼스 범위에선 화이트리스트 확충이 근본적 동적 추출 없이도
    충분했다는 근거가 된다). 연도판이 늘거나 코퍼스가 바뀌면 재실행해서
    확인할 것 — 단어 하나짜리 후보만 잡는다(다단어 조합은 "Large Japan"처럼
    문장 경계를 가로지르는 오탐이 실측으로 나와서 뺐다, 실제 누락 국가는
    거의 항상 한 단어이기도 하다)."""

    candidates: dict[str, list[tuple[str, int]]] = {}
    for commodity in list_known_commodities():
        blocks = commodity_world_table(commodity, max_editions=1)
        if not blocks:
            continue
        table = _table_only(blocks[0]["text"])
        known_spans = [(m.start(), m.end()) for m in _COUNTRY_RE.finditer(table)]
        for m in _CANDIDATE_WORD_RE.finditer(table):
            word = m.group(0)
            if word in _CANDIDATE_STOPWORDS:
                continue
            if any(start <= m.start() < end for start, end in known_spans):
                continue
            token = _first_token(table[m.end():m.end() + 20])
            value = _parse_number_token(token)
            if value is None or value <= 0:
                continue
            candidates.setdefault(word, []).append((commodity, value))
    return candidates


class AgentAction(BaseModel):
    action: Literal["open_commodity", "list_commodities", "finish"]
    commodity: str = ""
    note: str = ""


AGENT_INSTRUCTIONS = """당신은 PageIndex(USGS Mineral Commodity Summaries 연도판
코퍼스) 안에서 "광종별 세계 생산량(국가별 순위)" 근거를 찾는 조회 에이전트다.
직접 사용자에게 답하지 않는다 — 근거를 모으기만 한다. 매 스텝 정확히 하나의
JSON 행동을 고른다.

행동:
- open_commodity: commodity에 영문 대문자 광종명을 정확히 하나 넣는다(예:
  "COPPER", "NICKEL", "COBALT", "LITHIUM", "RARE EARTHS", "BAUXITE", "TIN").
  이 코퍼스는 광종명을 대문자 그대로만 인식한다(소문자로 넣으면 못 찾는다).
  해당 광종의 "국가별 세계 생산량" 단락을 여러 연도판에서 모아 온다.
- list_commodities: 이 코퍼스가 다루는 광종 전체 목록을 본다. 정확한 철자를
  모르거나, 특정 국가가 다른 무엇을 캐는지 후보를 넓혀야 할 때만 쓴다(매 스텝
  쓸 필요는 없다 — 답을 이미 알면 곧장 open_commodity로 간다).
- finish: 질문에 답하는 데 필요한 근거를 충분히 모았거나, 더 찾아도 소용없다고
  판단되면 멈춘다.

scratchpad에 이전 스텝 기록이 있다 — 이미 조회한 광종은 다시 열지 않는다.
질문이 "그 나라가 2번째/3번째로 많이 나는 광종은?"처럼 특정 국가의 순위를
묻는다면, 그 나라가 실제로 주요 생산국으로 알려진 광종 후보 몇 개(최대
3~4개)를 직접 열어 국가별 표에서 그 나라 수치를 확인해야 한다(모르면
list_commodities로 후보를 넓힌 뒤 고른다) — 광종 하나만 보고 끝내지 않는다."""


def _step_payload(question: str, history: list[dict], scratchpad: list[dict]) -> dict:
    return {"question": question, "history": history, "scratchpad": scratchpad}


def agentic_lookup(
    question: str,
    *,
    history: list[dict] | None = None,
    llm: KomirJsonLLM,
    max_steps: int = MAX_AGENT_STEPS,
    max_editions: int = MAX_EDITIONS,
) -> tuple[list[Evidence], list[str]]:
    """단일 진입점 — question(+history) -> (근거 리스트, 경고 리스트). LLM이
    매 스텝 open_commodity/list_commodities/finish 중 하나를 고르고, 여기서
    그 행동을 결정적 함수로 실행해 scratchpad에 결과 요약을 쌓아 다음 스텝
    판단 근거로 되먹인다(ReAct 스타일, 최대 `max_steps`회).

    실패 모드 처리(전부 부분 열화 — chatbot_graph._retrieve_node와 같은 원칙):
    - LLM 호출 자체가 죽으면(LLM_TRANSIENT_ERRORS) 그 시점까지 모은 근거만 반환.
    - 같은 (action, commodity) 조합이 반복되면 루프로 보고 즉시 종료.
    - open_commodity가 헛스윙(코퍼스에 없음)해도 다음 스텝은 계속 진행."""

    history = history or []
    scratchpad: list[dict] = []
    evidence: list[Evidence] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    checked: list[str] = []
    # 감시 대상 국가 목록 — 처음엔 질문 문장에 문자 그대로 나온 국가(있으면)만,
    # 첫 open_commodity 결과가 나오면 그 광종의 상위권 국가들도 자동으로
    # 추가된다(아래 루프, "reference_captured"). "구리 상위 5개국 중에서..."
    # 처럼 특정 국가가 아니라 어떤 광종의 상위 N개국 "집합"을 기준으로 다른
    # 광종을 대조해야 하는 질문에 대응하기 위함(_annotate_with_ranking 참고).
    focus_countries: list[str] = []
    seed = _detect_focus_country(question)
    if seed:
        focus_countries.append(seed)
    reference_captured = False

    for step in range(max_steps):
        try:
            invocation = llm.invoke(
                task="pageindex_agent_step", instructions=AGENT_INSTRUCTIONS,
                payload=_step_payload(question, history, scratchpad),
                output_model=AgentAction, max_tokens=120,
            )
            action = invocation.output
        except LLM_TRANSIENT_ERRORS as exc:
            warnings.append(f"pageindex_agent_llm_error:{type(exc).__name__}")
            break

        print(f"[pageindex_agent step {step + 1}] {action.action} commodity={action.commodity!r} note={action.note!r}")

        key = (action.action, action.commodity.strip().upper())
        if key in seen:
            warnings.append("pageindex_agent_repeat_guard")
            break
        seen.add(key)

        if action.action == "finish":
            break

        if action.action == "list_commodities":
            names = list_known_commodities()
            result = f"{len(names)}개 광종: " + ", ".join(names[:80]) if names else "광종 목록을 못 찾음"
            scratchpad.append({"step": step + 1, "action": "list_commodities", "result": result})
            continue

        commodity = action.commodity.strip().upper()
        if not commodity:
            scratchpad.append({"step": step + 1, "action": "open_commodity", "result": "commodity 미지정, 건너뜀"})
            continue

        blocks = commodity_world_table(commodity, max_editions=max_editions)
        checked.append(commodity)
        if not blocks:
            scratchpad.append({
                "step": step + 1, "action": "open_commodity", "commodity": commodity,
                "result": "코퍼스에서 세계생산 단락을 찾지 못함(철자 확인 또는 다른 광종 시도)",
            })
            continue

        annotated_texts = []
        for block in blocks:
            annotated = _annotate_with_ranking(block["text"], focus_countries=focus_countries)
            annotated_texts.append(annotated)
            evidence.append(Evidence(
                kind="pageindex",
                source=f"USGS Mineral Commodity Summaries {block['doc']}",
                section=f"{commodity} · 국가별 세계 생산량",
                text=annotated,
                unit=block.get("unit"),
            ))
        if not reference_captured:
            # 이번 루프에서 "처음" 연 광종의 상위 5개국을 감시목록에 편입한다
            # (질문이 특정 국가 없이 "이 광종 상위 5개국 중에서..."로 시작하는
            # 경우, 첫 open_commodity가 사실상 그 "상위 N개국"의 기준 광종이다).
            top5 = _rank_countries(blocks[0]["text"], top_n=5) or []
            for name, _value in top5:
                if name not in focus_countries and name not in ("Other countries", "Other"):
                    focus_countries.append(name)
            reference_captured = True
        # 스텝 판단 LLM이 "이미 답을 찾았는지" 스스로 가늠할 수 있도록 첫 연도판의
        # 순위 요약(또는 알파벳순 주의문구)을 미리보기로 되먹인다 — 이게 없으면
        # 메타정보("2개 연도판 확보")만 보고는 같은 광종을 괜히 또 열어보는
        # 낭비가 실측으로 관찰됐다(코발트→콩고 체인 3턴째, TIN을 두 번 연속 선택).
        preview = annotated_texts[0].split("\n\n", 1)[0][:220]
        scratchpad.append({
            "step": step + 1, "action": "open_commodity", "commodity": commodity,
            "result": f"{len(blocks)}개 연도판 확보({', '.join(b['doc'] for b in blocks)}) — {preview}",
        })

    if checked:
        # "5위권 생산국 전수조사" 같은 질문은 광종 수십 개를 다 훑어야 완전할
        # 수 있는데 max_steps로 몇 개만 확인하고 끝났을 수 있다 — 로그에
        # 비완전성을 명시한다(verify_node/재시도 판단에도 참고가 됨).
        warnings.append(f"pageindex_agent_checked:{','.join(checked)}")
    if not evidence:
        warnings.append("pageindex_agent_no_evidence")
    return evidence, warnings


if __name__ == "__main__":  # 수동 점검용
    import json as _json

    if len(sys.argv) > 1 and sys.argv[1] == "--check-coverage":
        gaps = find_uncovered_country_candidates()
        if not gaps:
            print("국가명 화이트리스트 커버리지 이상 없음(누락 후보 0건).")
        else:
            print(f"미확인 후보 {len(gaps)}건 — _KNOWN_COUNTRIES 추가 검토 필요:")
            for word, hits in sorted(gaps.items(), key=lambda kv: -len(kv[1])):
                print(f"  {word!r}: {len(hits)}회, 예시={hits[:3]}")
    else:
        q = sys.argv[1] if len(sys.argv) > 1 else "코발트 세계 생산량 1위 국가는?"
        ev, warn = agentic_lookup(q, llm=KomirJsonLLM())
        print(_json.dumps(
            {"warnings": warn, "evidence": [vars(e) for e in ev]}, ensure_ascii=False, indent=2,
        ))
