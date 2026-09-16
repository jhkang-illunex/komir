"""임시 문안 엔진 — LLM 정책 컬럼(원인·해석·정책 제언)을 고정 임시 문안으로 채운다.

왜 있나(2026-09-16): 뉴스 원천 미연결·진단 실값 미적재로 서술 컬럼이 거의 전부 NULL이라
보고서 화면이 비어 보였다. 사용자 요청("임시로 내용을 우선 채워 달라")으로, 생성형 엔진이
채우지 못한 서술 컬럼을 `resources/temp_texts.json`의 임시 문안으로 메운다.

원칙
- 임시 문안은 **분석 결과가 아니다**. 발주처 양식(통합보고서_템플릿_*_260915.md)의 예시 문장과
  광종별 일반 배경을 옮긴 자리표시 문장이며, 숫자를 담지 않는다(수치는 RULE 컬럼이 담당).
- 추적: 이 엔진도 버전(YYMMDD-sha8, 해시 입력 = 이 파일 + temp_texts.json)을 갖고
  `ai_rpt_engine_ver`에 engine_cd='temp', model_nm='TEMP_TEXT'로 등록된다. 임시 문안이 들어간
  행은 `llm_model_ver`가 이 버전을 가리키므로 "어느 행이 임시인가"를 SQL로 가려낼 수 있다.
- 우선순위: 생성형 엔진(GenEngine)이 채운 컬럼은 건드리지 않고 비어 있는 컬럼만 메운다
  (run.py가 병합). 뉴스·실값이 연결되면 임시 문안은 자연히 밀려난다.
- 문안 파일 구조: {table: {"_default": {col: text}, "<광종코드>": {col: text}}}. 광종 절이
  _default를 덮어쓴다. 문장 안의 `{name}`은 광종명(ai_mnrl_mst.mnrl_nm_ko)으로 치환.
  MANUAL 정책 컬럼(price_bg_long_txt·domestic_prod_txt)도 같은 파일에 두며 `manual()`로
  꺼내 writer의 시드(비어 있을 때만)로 넘긴다.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import ReportConfig
from ..policy import LLM, MANUAL, POLICIES
from .base import Engine, EngineResult, EngineVersion, compute_version

TEMP_FILE = Path(__file__).resolve().parents[1] / "resources" / "temp_texts.json"
#: 제목 컬럼 길이 한도(gen_engine._MAX_CHARS와 동일 취지). 본문은 DB 컬럼(text)이라 제한 없음.
_TITLE_MAX = 60


def load_texts(path: Path = TEMP_FILE) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _section(data: dict, table: str, code: str | None, name: str | None) -> dict[str, str]:
    sec = data.get(table) or {}
    merged = dict(sec.get("_default") or {})
    if code:
        merged.update(sec.get(code) or {})
    out = {}
    for col, text in merged.items():
        if not isinstance(text, str) or not text.strip():
            continue
        out[col] = text.replace("{name}", name or "").strip()
    return out


class TempEngine(Engine):
    engine_cd = "temp"
    engine_type = "TEMP"
    model_nm = "TEMP_TEXT"

    def __init__(self, cfg: ReportConfig, path: Path = TEMP_FILE):
        self.cfg = cfg
        self.path = path
        self._data = load_texts(path)
        self._version = compute_version(self.engine_cd, [Path(__file__), path])

    @property
    def version(self) -> EngineVersion:
        return self._version

    def _texts(self, table: str, ctx: dict) -> dict[str, str]:
        code = ctx.get("code")
        name = (ctx.get("facts") or {}).get("name") if code else None
        return _section(self._data, table, code, name)

    def generate(self, table: str, ctx: dict) -> EngineResult:
        """LLM 정책 컬럼만 돌려준다(정책 밖 키는 무시, 제목은 길이 검사)."""
        res = EngineResult(table=table, notes=["임시 문안(temp_texts.json) — 분석 결과 아님"])
        policy = POLICIES[table]
        for col, text in self._texts(table, ctx).items():
            if policy.get(col) != LLM:
                continue
            if col.endswith("_title") and len(text) > _TITLE_MAX:
                res.dropped[col] = f"too_long({len(text)}>{_TITLE_MAX})"
                continue
            res.columns[col] = text
        return res

    def manual(self, table: str, ctx: dict) -> dict[str, str]:
        """MANUAL 정책 컬럼의 임시 시드(writer가 비어 있을 때만 쓴다)."""
        policy = POLICIES[table]
        return {c: t for c, t in self._texts(table, ctx).items() if policy.get(c) == MANUAL}
