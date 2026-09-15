"""엔진 인터페이스와 버전 계산.

버전 = `YYMMDD-sha8`
- sha8: 엔진을 구성하는 파일(규칙 코드·프롬프트·정책)의 내용을 정렬해 이어붙인
  sha256 앞 8자리 + 모델명 같은 추가 문자열(extra). 파일 한 줄만 바뀌어도 버전이
  바뀐다 — "어느 규칙/프롬프트로 만든 문장인지"를 행 단위로 추적하기 위함.
- YYMMDD: 그 파일들의 최종 변경일 중 최댓값. 커밋된 깨끗한 파일은 마지막 커밋일(clone·
  checkout으로 mtime이 바뀌어도 같은 코드=같은 날짜), 미커밋·미추적 파일은 mtime —
  그래서 미커밋 변경도 새 버전으로 잡힌다.
"""
from __future__ import annotations

import hashlib
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EngineVersion:
    engine_cd: str
    ver_date: str          # YYMMDD
    sha: str               # 8 hex
    files: tuple[str, ...]  # 저장소 상대 경로
    extra: str = ""        # 모델명 등 해시에 섞은 추가 식별자

    @property
    def ver(self) -> str:
        return f"{self.ver_date}-{self.sha}"


_INHOUSE = Path(__file__).resolve().parents[2]


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(_INHOUSE))
    except ValueError:
        return p.name


def _file_time(p: Path) -> float:
    """버전 날짜용 파일 시각. git에 커밋돼 있고 변경이 없으면 마지막 커밋 시각(clone·checkout으로
    mtime이 바뀌어도 같은 코드는 같은 날짜), 미커밋·미추적이거나 git이 없으면(컨테이너) mtime."""
    try:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(p)], cwd=p.parent,
                               capture_output=True, text=True, timeout=5)
        if dirty.returncode == 0 and not dirty.stdout.strip():
            ct = subprocess.run(["git", "log", "-1", "--format=%ct", "--", str(p)], cwd=p.parent,
                                capture_output=True, text=True, timeout=5)
            if ct.returncode == 0 and ct.stdout.strip():
                return float(ct.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return p.stat().st_mtime


def compute_version(engine_cd: str, files: list[Path], extra: str = "") -> EngineVersion:
    h = hashlib.sha256()
    latest = 0.0
    rel: list[str] = []
    for p in sorted(files):
        data = p.read_bytes()
        h.update(p.name.encode())
        h.update(data)
        latest = max(latest, _file_time(p))
        rel.append(_rel(p))
    if extra:
        h.update(extra.encode())
    return EngineVersion(engine_cd=engine_cd, ver_date=datetime.fromtimestamp(latest).strftime("%y%m%d"),
                         sha=h.hexdigest()[:8], files=tuple(rel), extra=extra)


@dataclass
class EngineResult:
    table: str
    columns: dict[str, Any] = field(default_factory=dict)   # 채운 컬럼(정책 범위 내)
    evidence: dict[str, Any] = field(default_factory=dict)  # 문장의 근거(숫자·원천) 스냅샷
    dropped: dict[str, str] = field(default_factory=dict)   # 컬럼 → 폐기 사유(검증 실패 등)
    notes: list[str] = field(default_factory=list)

    @property
    def filled(self) -> int:
        return sum(1 for v in self.columns.values() if v not in (None, ""))


class Engine(ABC):
    engine_cd: str = ""
    engine_type: str = ""      # RULE | GEN
    model_nm: str | None = None

    @property
    @abstractmethod
    def version(self) -> EngineVersion: ...

    @abstractmethod
    def generate(self, table: str, ctx: dict) -> EngineResult:
        """ctx: {"base": date, "code": str|None, "facts": dict, "rule": EngineResult|None,
        "news": list[str]} — 엔진마다 필요한 키만 읽는다."""
