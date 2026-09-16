"""원장(public 스키마) 조회 → facts. 규칙 문장은 여기서 나온 숫자만 쓴다.

원칙
- 개발 더미는 원천으로 인정하지 않는다: 행 단위 더미는 `ai_dev_dummy_load`
  (tbl_nm, mnrknd_unq_cd, nat_key)로, 진단·거시·뉴스는 model_ver/src_nm의
  DEV_DUMMY 표식으로 걸러 facts에서 뺀다(→ 해당 문장은 NULL).
  예외: `cfg.allow_dummy`(MNRL_REPORT_ALLOW_DUMMY=1, --allow-dummy)가 켜지면 더미도
  원천으로 쓴다 — 실데이터 적재 전 화면을 채워 보기 위한 임시 스위치(2026-09-16).
- 모든 수치는 원장 값 그대로(반올림·축약은 rules/fmt.py에서만).
- 단위 가정: ko_cstm_cmmrc.incm_amt=USD, incm_weig=kg(config.customs_weight_kg),
  ko_rsrc_*_ton=톤, ntn_eng_cd 'SU'=세계 합계, 'OT'=기타.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import db
from .config import DUMMY_MARK, ReportConfig, from_ymd, to_ymd

MNRL_MST_SQL = """
select mnrknd_unq_cd, mnrl_nm_ko, status_cd, use_yn, prc_cat_cd, ko_data_src_cd
from public.ai_mnrl_mst where use_yn='Y' and status_cd='READY' order by sort_ordr
"""


def minerals(cfg: ReportConfig) -> list[dict]:
    rows = db.fetch_all(MNRL_MST_SQL)
    if cfg.minerals:
        order = {c: i for i, c in enumerate(cfg.minerals)}
        rows = sorted((r for r in rows if r["mnrknd_unq_cd"] in order), key=lambda r: order[r["mnrknd_unq_cd"]])
    return rows


def mineral_name(code: str) -> str | None:
    r = db.fetch_one("select mnrl_nm_ko from public.ai_mnrl_mst where mnrknd_unq_cd=:c", {"c": code})
    return r["mnrl_nm_ko"] if r else None


#: ai_ntn_mst(25개국)에 없는 USGS 국가코드 폴백 — ISO 3166-1 alpha-2 확정분만. 여기도
#: 없으면 코드 그대로 노출된다(지어내지 않는다).
_ISO_FALLBACK = {
    "KZ": "카자흐스탄", "KP": "북한", "VN": "베트남", "ES": "스페인", "PT": "포르투갈", "BO": "볼리비아",
    "RW": "르완다", "MN": "몽골", "TJ": "타지키스탄", "UZ": "우즈베키스탄", "MM": "미얀마", "TH": "태국",
    "ZW": "짐바브웨", "CD": "콩고민주공화국", "ZM": "잠비아", "PE": "페루", "CL": "칠레", "AR": "아르헨티나",
    "MX": "멕시코", "TR": "튀르키예", "PH": "필리핀", "NC": "뉴칼레도니아", "MG": "마다가스카르", "CU": "쿠바",
}


def country_names() -> dict[str, str]:
    names = dict(_ISO_FALLBACK)
    names.update({r["ntn_cd"]: r["ntn_nm_ko"] for r in db.fetch_all("select ntn_cd, ntn_nm_ko from public.ai_ntn_mst")})
    return names


def dummy_codes(table: str, cfg: ReportConfig) -> set[str]:
    """해당 테이블에서 더미 행이 있는 광종코드 집합(그 광종의 그 테이블은 통째로 불신).
    allow_dummy면 빈 집합(=아무것도 거르지 않음)."""
    if cfg.allow_dummy:
        return set()
    return {r["mnrknd_unq_cd"] for r in db.fetch_all(
        "select distinct mnrknd_unq_cd from public.ai_dev_dummy_load where tbl_nm=:t", {"t": table})}


# ── 주간 가격(공단 주간 파일, 비철 6종) ──────────────────────────────
def weekly_price(code: str, base: date) -> dict | None:
    """base 주(월요일)의 주간 기준가격·전주비 + 4주 전(전월 대체)·52주 전(전년) 값."""
    rows = db.fetch_all(
        """select crtr_ymd, cmerc_prc, wow_pct, lme_invt, lme_invt_wow_pct
           from public.ko_wkly_mnrl_prc where mnrknd_unq_cd=:c and crtr_ymd<=:b
           order by crtr_ymd desc limit 60""",
        {"c": code, "b": to_ymd(base)})
    if not rows or rows[0]["crtr_ymd"] != to_ymd(base):
        return None
    cur = rows[0]
    by = {r["crtr_ymd"]: r for r in rows}
    prev4 = by.get(to_ymd(base - timedelta(weeks=4)))
    prev52 = by.get(to_ymd(base - timedelta(weeks=52)))
    monthly: dict[str, list[float]] = {}
    for r in rows:
        if r["cmerc_prc"] is not None:
            monthly.setdefault(r["crtr_ymd"][:6], []).append(float(r["cmerc_prc"]))
    return {
        "as_of": cur["crtr_ymd"], "price": _f(cur["cmerc_prc"]), "wow_pct": _f(cur["wow_pct"]),
        "mom_pct": _pct(cur["cmerc_prc"], prev4["cmerc_prc"]) if prev4 else None,
        "yoy_pct": _pct(cur["cmerc_prc"], prev52["cmerc_prc"]) if prev52 else None,
        "lme_invt": _f(cur["lme_invt"]), "lme_invt_wow_pct": _f(cur["lme_invt_wow_pct"]),
        "monthly_avg": {k: sum(v) / len(v) for k, v in monthly.items()},
        "weekly": [(r["crtr_ymd"], _f(r["cmerc_prc"])) for r in rows[:8]],
    }


# ── 진단(ai_mnrl_diag / ai_dash_diag) — 더미 차단 ────────────────────
def mineral_diag(code: str, base: date, cfg: ReportConfig) -> dict | None:
    rows = db.fetch_all(
        """select base_ymd, score, grade, score_wow_pct, model_ver
           from public.ai_mnrl_diag where mnrknd_unq_cd=:c and base_ymd<=:b
           order by base_ymd desc limit 30""",
        {"c": code, "b": to_ymd(base)})
    if not cfg.allow_dummy:
        rows = [r for r in rows if (r.get("model_ver") or "") != DUMMY_MARK]
    if not rows or rows[0]["base_ymd"] != to_ymd(base):
        return None
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    streak = 0
    for r in rows:
        if r["grade"] == cur["grade"]:
            streak += 1
        else:
            break
    month = cur["base_ymd"][:6]
    prev_month = to_ymd(from_ymd(cur["base_ymd"]).replace(day=1) - timedelta(days=1))[:6]
    avg = lambda m: _mean([float(r["score"]) for r in rows if r["base_ymd"][:6] == m and r["score"] is not None])  # noqa: E731
    return {
        "score": _f(cur["score"]), "grade": cur["grade"],
        "score_wow": _f(cur["score"]) - _f(prev["score"]) if prev and prev["score"] is not None else None,
        "score_mom": (avg(month) - avg(prev_month)) if avg(month) is not None and avg(prev_month) is not None else None,
        "streak_wk": streak,
    }


def overall_diag(base: date, cfg: ReportConfig) -> dict | None:
    r = db.fetch_one("select * from public.ai_dash_diag where base_ymd=:b", {"b": to_ymd(base)})
    if not r or ((r.get("model_ver") or "") == DUMMY_MARK and not cfg.allow_dummy):
        return None
    return {k: (_f(v) if k.endswith(("_score", "_wow")) else v) for k, v in r.items()}


def macro(code: str, base: date, cfg: ReportConfig) -> dict | None:
    """거시지표(GSCPI·GPR 등) 최신값 + 4주 전(전월 대체)·52주 전(전년) 대비 차이(p)."""
    rows = db.fetch_all(
        """select indc_val, wow_pct, base_ymd, src_nm from public.ai_macro_indc
           where indc_cd=:i and base_ymd<=:b order by base_ymd desc limit 60""",
        {"i": code, "b": to_ymd(base)})
    if not cfg.allow_dummy:
        rows = [r for r in rows if (r.get("src_nm") or "") != DUMMY_MARK]
    if not rows:
        return None
    cur = rows[0]
    by = {r["base_ymd"]: r for r in rows}
    ref = from_ymd(cur["base_ymd"])
    prev4 = by.get(to_ymd(ref - timedelta(weeks=4)))
    prev52 = by.get(to_ymd(ref - timedelta(weeks=52)))
    val = _f(cur["indc_val"])
    return {"val": val, "wow_pct": _f(cur["wow_pct"]), "as_of": cur["base_ymd"],
            "mom_diff": val - _f(prev4["indc_val"]) if prev4 and val is not None and prev4["indc_val"] is not None else None,
            "yoy_diff": val - _f(prev52["indc_val"]) if prev52 and val is not None and prev52["indc_val"] is not None else None}


# ── 관세청(ko_cstm_cmmrc) — 광종 HS 전체 합산 ─────────────────────────
def customs(code: str, base: date, cfg: ReportConfig, ntn: dict[str, str]) -> dict | None:
    if code in dummy_codes("ko_cstm_cmmrc", cfg):
        return None
    rows = db.fetch_all(
        """select substr(c.crtr_ymd,1,6) ym, c.trgt_ntn_cd, c.trgt_ntn,
                  sum(c.incm_weig) w, sum(c.incm_amt) a, sum(c.exp_amt) ea
           from public.ko_cstm_cmmrc c join public.ai_hs_mnrl_map h on h.hs_cd=c.hs_cd and h.use_yn='Y'
           where h.mnrknd_unq_cd=:c and c.crtr_ymd<=:b
           group by 1,2,3""",
        {"c": code, "b": to_ymd(base)})
    if not rows:
        return None
    kg = 1000.0 if cfg.customs_weight_kg else 1.0
    by_month: dict[str, dict[str, float]] = {}
    by_year_ntn: dict[str, dict[str, float]] = {}
    for r in rows:
        m = by_month.setdefault(r["ym"], {"w": 0.0, "a": 0.0})
        m["w"] += _f(r["w"]) or 0.0
        m["a"] += _f(r["a"]) or 0.0
        yn = by_year_ntn.setdefault(r["ym"][:4], {})
        name = ntn.get(r["trgt_ntn_cd"]) or r["trgt_ntn"] or r["trgt_ntn_cd"]
        yn[name] = yn.get(name, 0.0) + (_f(r["a"]) or 0.0)
    latest_ym = max(by_month)
    y, mth = int(latest_ym[:4]), int(latest_ym[4:])
    ytd = lambda yy: {"w": sum(v["w"] for k, v in by_month.items() if k[:4] == str(yy) and int(k[4:]) <= mth),  # noqa: E731
                      "a": sum(v["a"] for k, v in by_month.items() if k[:4] == str(yy) and int(k[4:]) <= mth)}
    year_tot = {yy: {"w": sum(v["w"] for k, v in by_month.items() if k[:4] == yy),
                     "a": sum(v["a"] for k, v in by_month.items() if k[:4] == yy)} for yy in {k[:4] for k in by_month}}
    prev_year = str(y - 1)
    base_year = str(y - 5)
    shares_year = prev_year if prev_year in by_year_ntn else str(y)
    tot = sum(by_year_ntn[shares_year].values()) or 1.0
    shares = sorted(((n, a / tot * 100) for n, a in by_year_ntn[shares_year].items()), key=lambda x: -x[1])
    return {
        "latest_ym": latest_ym,
        "month": {"ton": by_month[latest_ym]["w"] / kg, "usd": by_month[latest_ym]["a"]},
        "month_prev_year": {"ton": by_month.get(f"{y-1}{mth:02d}", {}).get("w", 0) / kg,
                            "usd": by_month.get(f"{y-1}{mth:02d}", {}).get("a")},
        "ytd": {"ton": ytd(y)["w"] / kg, "usd": ytd(y)["a"]},
        "ytd_prev_year": {"ton": ytd(y - 1)["w"] / kg, "usd": ytd(y - 1)["a"]},
        "year_tot": {yy: {"ton": v["w"] / kg, "usd": v["a"]} for yy, v in year_tot.items()},
        "prev_year": prev_year, "base_year": base_year,
        "cagr_pct": _cagr(year_tot.get(base_year, {}).get("a"), year_tot.get(prev_year, {}).get("a"),
                          int(prev_year) - int(base_year))
        if base_year in year_tot and prev_year in year_tot else None,
        "shares_year": shares_year, "shares": shares[:5],
        "hhi": sum(s * s for _, s in shares),
    }


# ── USGS(ko_rsrc_*) ──────────────────────────────────────────────────
def usgs(code: str, base: date, table: str, col: str, ntn: dict[str, str], cfg: ReportConfig) -> dict | None:
    if code in dummy_codes(table, cfg):
        return None
    rows = db.fetch_all(
        f"""select crtr_yr, ntn_eng_cd, {col} v from public.{table}
            where mnrknd_unq_cd=:c and crtr_yr<=:y and {col} is not null
            and crtr_yr=(select max(crtr_yr) from public.{table} where mnrknd_unq_cd=:c and crtr_yr<=:y and {col} is not null)
            order by v desc""",
        {"c": code, "y": str(base.year)})
    if not rows:
        return None
    world = next((_f(r["v"]) for r in rows if r["ntn_eng_cd"] == "SU"), None)
    ranked = [(ntn.get(r["ntn_eng_cd"], "기타" if r["ntn_eng_cd"] == "OT" else r["ntn_eng_cd"]), _f(r["v"]))
              for r in rows if r["ntn_eng_cd"] not in ("SU", "OT")]
    if world is None:
        world = sum(v for _, v in ranked)
    shares = [(n, v, v / world * 100 if world else None) for n, v in ranked]
    return {"year": rows[0]["crtr_yr"], "world_ton": world, "top": shares[:5],
            "cr3_pct": sum(s for _, _, s in shares[:3] if s is not None)}


# ── helpers ──────────────────────────────────────────────────────────
def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _pct(cur: Any, prev: Any) -> float | None:
    cur, prev = _f(cur), _f(prev)
    if cur is None or not prev:
        return None
    return (cur - prev) / prev * 100


def _cagr(start: Any, end: Any, years: int) -> float | None:
    start, end = _f(start), _f(end)
    if not start or end is None or years <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None
