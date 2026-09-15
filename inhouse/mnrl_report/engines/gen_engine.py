"""생성형 엔진 — LLM으로 LLM 정책 컬럼(원인·해석·정책 서술)을 쓴다.

버전 해시 입력: 이 파일 + `engines/prompts/*.md`(컬럼별 지시문) + 모델명.
프롬프트 한 줄만 바뀌어도, 모델을 바꿔도 버전이 바뀐다.

동작
1. 근거 = 규칙 엔진 결과(RULE 컬럼 문장 + evidence 수치) + 뉴스 제목(있으면).
   원장 JSON은 절대 직접 주지 않는다.
2. 컬럼마다 프롬프트 파일의 `## <컬럼>` 지시문으로 1회 호출(JSON 모드 아님, 평문).
   헤더에 `[needs:news]`가 붙은 컬럼(원인·사건 서술)은 뉴스 근거가 ctx에 없으면 호출 자체를
   생략하고 `no_news_evidence`로 폐기 — 수치만 보고 원인을 짓지 못하게 한다.
3. 검증(`validate`): 빈 출력, 근거 밖 숫자(연도·월·주차·개수 표기 제외), 금지어(단정 표현),
   "정보가 없습니다"류 메타 문장, 비어 있는 자리표시자([원인 ]·"에서 가 주요"), 근거와 반대인
   방향어(근거 "4.61% 상승"→출력 "4.61% 하락"), 길이 초과면 폐기 → `EngineResult.dropped[col] = 사유`. 폐기된 컬럼은 NULL로 남는다(규칙 대체문
   없음 — 이 컬럼들은 본래 서술 자리).
4. temperature는 common 설정(.env LLM_TEMPERATURE=0)을 따르지만 vLLM 출력이
   호출마다 흔들릴 수 있으므로(2026-09-13 실측) 동일 근거라도 문장은 달라질 수 있다.
   그래서 결과와 함께 근거·버전을 반드시 로그(ai_rpt_gen_run)에 남긴다.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from common.config import get_settings

from ..config import ReportConfig
from ..policy import LLM, POLICIES, RULE
from .base import Engine, EngineResult, EngineVersion, compute_version

log = logging.getLogger(__name__)
_HERE = Path(__file__).resolve().parent
PROMPT_DIR = _HERE / "prompts"

_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
_YEAR_RE = re.compile(r"^(19|20)\d\d$")
# 날짜·개수 표기는 "근거 밖 숫자" 검사에서 제외: `25년·'25년·2025년·7월·3주차·3개국·2분기·15일
_DATE_LIKE_RE = re.compile(r"[`'‘’]?\d{2,4}년|\d{1,2}월|\d{1,3}(?:주차|주|개국|분기|일|개월|개)")
_FORBIDDEN = ("반드시", "확실히", "틀림없이", "확정적으로", "100%")
# "근거가 없다"는 메타 서술은 보고서 문장이 아니다 — 모델이 (없음) 대신 이렇게 답하는 것을 실측(2026-09-15)
_META_PHRASES = ("정보가 없", "정보도 없", "정보는 없", "근거에", "근거가 없", "근거는 없", "포함되어 있지 않",
                 "원인 없음", "제공되지 않", "알 수 없습니다", "확인할 수 없", "언급되지 않", "명시되지 않")
# 지시문의 [원인] 자리가 비어 나온 문장: "공급측면에서 가 주요 원인", "[원인 ]", "[]", "( )"
_PLACEHOLDER_RE = re.compile(
    r"\[\s*(원인|사건|국가)?\s*\]|\(\s*\)|(^|\s)(가|은|는|을|를) "
    r"|(은|는|이|가|을|를|의|로|에서)\s+(입니다|합니다|됩니다|였습니다|이었습니다)"  # "원인은 입니다"
    r"|(은|는|이|가|을|를|의|로|에서)\s*[.。]$")  # "정보는 ." 처럼 조사로 끝나는 문장
_MAX_CHARS = {"_default": 600, "title": 60}


_HEADER_RE = re.compile(r"^## (?P<col>\S+)(?:\s+\[needs:(?P<needs>[a-z,]+)\])?\s*$")


def load_prompts(table: str) -> tuple[str, dict[str, str], dict[str, set[str]]]:
    """`## _system` 절과 `## <컬럼> [needs:news]` 절로 나뉜 md 파일을
    (system, {col: instr}, {col: {"news", ...}})로. needs에 적힌 근거가 ctx에 없으면 그 컬럼은
    LLM을 부르지 않고 폐기(no_<근거>_evidence)한다 — 원인·사건 서술을 수치만 보고 짓지 못하게."""
    text = (PROMPT_DIR / f"{table}.md").read_text(encoding="utf-8")
    system, cols, needs, cur, buf = "", {}, {}, None, []

    def flush():
        nonlocal system
        body = "\n".join(buf).strip()
        if cur == "_system":
            system = body
        elif cur:
            cols[cur] = body
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            flush()
            cur, buf = m.group("col"), []
            if cur != "_system":
                needs[cur] = set(filter(None, (m.group("needs") or "").split(",")))
        else:
            buf.append(line)
    flush()
    return system, cols, needs


def _numbers(text: str) -> set[str]:
    """측정값(가격·비율·물량)만 추린다 — 연도·월·주차·개수 표기는 제외."""
    cleaned = _DATE_LIKE_RE.sub(" ", text or "")
    return {n.replace(",", "") for n in _NUM_RE.findall(cleaned) if not _YEAR_RE.match(n.replace(",", ""))}


_DIR_RE = re.compile(r"(\d[\d,]*\.?\d*)%?[^\d%]{0,8}?(상승|하락|증가|감소)")
_DIR_GROUP = {"상승": "up", "증가": "up", "하락": "down", "감소": "down"}


def _directions(text: str) -> dict[str, set[str]]:
    """숫자 → 그 뒤 8자 안에 붙은 방향어(상승/증가=up, 하락/감소=down) 집합."""
    out: dict[str, set[str]] = {}
    for num, word in _DIR_RE.findall(text or ""):
        out.setdefault(num.replace(",", ""), set()).add(_DIR_GROUP[word])
    return out


def validate(col: str, text: str, evidence: str) -> str | None:
    """폐기 사유(None이면 통과)."""
    t = (text or "").strip()
    if not t:
        return "empty"
    if any(w in t for w in _FORBIDDEN):
        return "forbidden_phrase"
    if any(w in t for w in _META_PHRASES):
        return "meta_no_info_sentence"
    if _PLACEHOLDER_RE.search(t):
        return "empty_placeholder"
    limit = _MAX_CHARS["title"] if col.endswith("_title") else _MAX_CHARS["_default"]
    if len(t) > limit:
        return f"too_long({len(t)}>{limit})"
    extra = _numbers(t) - _numbers(evidence)
    if extra:
        return f"number_not_in_evidence({','.join(sorted(extra))[:40]})"
    ev_dir = _directions(evidence)
    for num, dirs in _directions(t).items():
        if num in ev_dir and not (dirs & ev_dir[num]):  # 근거는 4.61% 상승인데 출력이 4.61% 하락
            return f"direction_mismatch({num})"
    return None


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_NONE_TOKENS = ("(없음)", "없음")


def unwrap(text: str) -> str:
    """모델이 JSON 껍데기·코드펜스·따옴표로 감싼 출력을 평문 문장으로 벗긴다. "(없음)" 토큰은 제거."""
    t = _FENCE_RE.sub("", (text or "").strip()).strip()
    if t.startswith("{"):
        try:
            obj = json.loads(t)
            vals = [v for v in obj.values() if isinstance(v, str)] if isinstance(obj, dict) else []
            t = vals[0] if vals else ""
        except ValueError:  # 깨진 JSON: 첫 "키": "값" 의 값만, 없으면 따옴표 안 문자열
            m = re.search(r'"\s*:\s*"([^"]*)"?', t)
            t = m.group(1) if m else re.sub(r'^[{\s"]+|[}\s"]+$', "", t)
    t = t.strip().strip('"').strip()
    if t in _NONE_TOKENS or "(없음)" in t:  # 문장 안에 (없음)을 섞어 쓰면 통째로 비운다("…정보는 ." 잔해 방지)
        return ""
    return t


def evidence_text(rule: EngineResult, news: list[str]) -> str:
    lines = [f"- {c}: {v}" for c, v in rule.columns.items()
             if POLICIES[rule.table].get(c) == RULE and v not in (None, "")]
    for k, v in rule.evidence.items():
        if isinstance(v, dict):
            brief = {kk: vv for kk, vv in v.items() if not isinstance(vv, (dict, list))}
            lines.append(f"- {k}: {brief}")
    if news:
        lines.append("- 뉴스 제목: " + " / ".join(news))
    return "\n".join(lines)


class GenEngine(Engine):
    engine_cd = "gen"
    engine_type = "GEN"

    def __init__(self, cfg: ReportConfig, chat=None):
        self.cfg = cfg
        settings = get_settings()
        self.model_nm = settings.LLM_MODEL
        files = [Path(__file__)] + sorted(PROMPT_DIR.glob("*.md"))
        self._version = compute_version(self.engine_cd, files, extra=f"{settings.LLM_PROVIDER}:{self.model_nm}")
        self._chat = chat

    @property
    def version(self) -> EngineVersion:
        return self._version

    def _client(self):
        if self._chat is None:
            from common.llm_client import get_chat_client
            # 공용 클라이언트는 json_mode=True(response_format=json_object)가 기본 — 여기선 평문 문장이
            # 필요하므로 끈다(켜 두면 {"컬럼": "..."} 껍데기가 그대로 저장되는 것을 실측, 2026-09-15).
            self._chat = get_chat_client({**get_settings().llm_cfg(), "json_mode": False})
        return self._chat

    def generate(self, table: str, ctx: dict) -> EngineResult:
        rule: EngineResult = ctx["rule"]
        evidence = evidence_text(rule, ctx.get("news") or [])
        system, prompts, needs = load_prompts(table)
        res = EngineResult(table=table, evidence={"evidence_text": evidence})
        if not evidence.strip():
            res.notes.append("근거 없음 — 생성 생략")
            return res
        available = {"news"} if ctx.get("news") else set()
        chat = None
        for col, kind in POLICIES[table].items():
            if kind != LLM or col not in prompts:
                continue
            missing = needs.get(col, set()) - available
            if missing:
                res.dropped[col] = "no_" + "_".join(sorted(missing)) + "_evidence"
                continue
            chat = chat or self._client()
            user = f"[항목] {col}\n[지시]\n{prompts[col]}\n\n[근거]\n{evidence}"
            try:
                out = chat.complete(system, user, max_tokens=400)
                text = unwrap(out.text)
            except Exception as exc:  # noqa: BLE001 — 한 컬럼 실패가 배치를 막지 않게
                res.dropped[col] = f"llm_error:{type(exc).__name__}"
                log.warning("gen %s.%s 실패: %s", table, col, exc)
                continue
            if not text:
                res.dropped[col] = "empty"
                continue
            reason = validate(col, text, evidence)
            if reason:
                res.dropped[col] = reason
                log.info("gen %s.%s 폐기: %s", table, col, reason)
            else:
                res.columns[col] = text
        return res
