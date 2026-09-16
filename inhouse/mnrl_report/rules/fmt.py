"""서식 규칙 — 양식 표기(억달러·천톤·천달러·%·p)로 통일. 반올림은 여기서만."""
from __future__ import annotations


def num(v: float | None, nd: int = 1) -> str:
    """소수 nd자리, 끝자리 0 제거, 천 단위 쉼표."""
    if v is None:
        return "-"
    s = f"{v:,.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def pct(v: float | None, nd: int = 1) -> str:
    return "-" if v is None else f"{num(v, nd)}%"


def signed_dir(v: float | None, up: str = "상승", down: str = "하락", flat: str = "보합") -> str:
    """방향어 — 부호가 아니라 말로(report_gen _signed_pct 관례)."""
    if v is None:
        return "-"
    if v > 0:
        return up
    if v < 0:
        return down
    return flat


def points(v: float | None, nd: int = 2) -> str:
    return "-" if v is None else f"{num(abs(v), nd)}p"


def eok_usd(usd: float | None, nd: int = 1) -> str:
    """USD → 억달러(양식 B7 "1.9억달러")."""
    return "-" if usd is None else f"{num(usd / 1e8, nd)}억달러"


def k_usd(usd: float | None) -> str:
    """USD → 천달러(양식 "386,379천달러")."""
    return "-" if usd is None else f"{num(usd / 1e3, 0)}천달러"


def k_usd_u(usd: float | None) -> str:
    """USD → U$천 표기(양식 A6-④ "U$86,537천")."""
    return "-" if usd is None else f"U${num(usd / 1e3, 0)}천"


def kton(ton: float | None, nd: int = 1) -> str:
    """톤 → 천톤(양식 "24천톤"). 1백만톤 이상은 백만톤, 1천톤 미만은 톤("2.8톤" — "0천톤" 방지)."""
    if ton is None:
        return "-"
    if abs(ton) >= 1e6:
        return f"{num(ton / 1e6, 1)}백만톤"
    if abs(ton) < 1e3:
        return f"{num(ton, 1)}톤"
    return f"{num(ton / 1e3, nd)}천톤"


def josa(word: str, with_final: str, without_final: str) -> str:
    """한글 받침 유무로 조사 선택 — josa("중국","이","가")→"중국이", josa("호주","이","가")→"호주가".
    마지막 글자가 한글이 아니면(괄호·숫자·영문) 받침 있음 쪽을 쓴다."""
    if not word:
        return with_final
    ch = word[-1]
    if "가" <= ch <= "힣":
        return with_final if (ord(ch) - ord("가")) % 28 else without_final
    return with_final


def hhi(v: float | None) -> str:
    return "-" if v is None else num(v, 0)


def ratio_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or not prev:
        return None
    return (cur - prev) / prev * 100


def yy(year: int | str) -> str:
    """’26년 표기."""
    return f"`{str(year)[-2:]}년"
