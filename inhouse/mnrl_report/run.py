"""주간 실행 진입점(파이프라인). 문장은 engines/가 만들고, 이 모듈은 읽기→엔진→쓰기→기록만 한다.

    cd inhouse && python -m mnrl_report.run [--base-ymd 20260615] [--minerals MNRL0008,MNRL0002]
                                            [--scope all|overall|mnrl] [--llm] [--allow-dummy] [--temp-fill]
                                            [--force] [--dry-run]

절차(보고 주차 base_ymd 1개):
 0. 엔진 준비 — RuleEngine(+옵션 GenEngine) 버전을 계산해 ai_rpt_engine_ver에 등록
 1. 원장 조회 → facts(광종별 price/diag/customs/production/reserve, 전체 overall/gscpi)
 2. RuleEngine.generate → RULE 컬럼(광종 수만큼 + 전체 1행)
 3. (옵션) GenEngine.generate → LLM 컬럼(근거 = RULE 결과 + 뉴스 제목)
 3′. (옵션 --temp-fill) TempEngine.generate → 3에서 비어 남은 LLM 컬럼을 임시 문안으로 메운다.
    임시 문안이 하나라도 들어간 행은 llm_model_ver가 temp 엔진 버전(model_nm TEMP_TEXT)을 가리킨다
 4. writer.upsert — DRAFT 행만 갱신, MANUAL은 비었을 때 고정 문안 시드(fixed_texts + 임시 문안 +
    더미 허용 시 GSCPI·GPR 값), rule_ver/llm_model_ver에 엔진 버전(YYMMDD-sha8)을 찍는다
 5. 행마다 ai_rpt_gen_run에 실행 로그(엔진·버전·채움/폐기·근거 파일)
 6. facts 스냅샷을 data_lake/mnrl_report/facts_{base_ymd}.json에 남긴다(감사용)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime

from . import sources, writer
from .config import from_ymd, get_config, latest_monday, to_ymd
from .engines import GenEngine, RuleEngine, TempEngine
from .engines import registry
from .engines.base import EngineResult

log = logging.getLogger("mnrl_report")

_FIXED = os.path.join(os.path.dirname(__file__), "resources", "fixed_texts.json")


def _fixed_texts() -> dict:
    try:
        with open(_FIXED, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def collect_mineral_facts(code: str, name: str, base: date, cfg, ntn: dict) -> dict:
    return {
        "name": name,
        "price": sources.weekly_price(code, base),
        "diag": sources.mineral_diag(code, base, cfg),
        "customs": sources.customs(code, base, cfg, ntn),
        "production": sources.usgs(code, base, "ko_rsrc_prdctn_quty", "prdctn_quty_ton", ntn, cfg),
        "reserve": sources.usgs(code, base, "ko_rsrc_burudg_quty", "burudg_quty_ton", ntn, cfg),
    }


def _round2(v):
    return None if v is None else round(float(v), 2)


def overall_manual_from_facts(facts: dict) -> dict:
    """MANUAL(→RULE 전환 예정) 수치 컬럼의 시드 — 거시지표 원천이 facts에 있을 때만.
    실값 원천이 없어 평소엔 빈 dict이고, --allow-dummy일 때 더미 GSCPI·GPR이 들어온다."""
    out: dict = {}
    g, gpr = facts.get("gscpi"), facts.get("gpr")
    if g:
        out.update(gscpi_val=_round2(g["val"]), gscpi_mom=_round2(g.get("mom_diff")), gscpi_yoy=_round2(g.get("yoy_diff")))
    if gpr:
        out.update(geo_risk_idx=_round2(gpr["val"]), geo_risk_wow_pct=_round2(gpr.get("wow_pct")))
    return {k: v for k, v in out.items() if v is not None}


def _merge_temp(gen_res: EngineResult | None, temp_res: EngineResult) -> EngineResult:
    """생성형 결과 위에 임시 문안을 '빈 컬럼만' 덧댄다. 생성형이 채운 컬럼이 우선."""
    merged = EngineResult(table=temp_res.table, notes=list(temp_res.notes))
    if gen_res is not None:
        merged.columns.update({c: v for c, v in gen_res.columns.items() if v not in (None, "")})
        merged.evidence = dict(gen_res.evidence)
        merged.notes = list(gen_res.notes) + merged.notes
    for c, v in temp_res.columns.items():
        if merged.columns.get(c) in (None, ""):
            merged.columns[c] = v
    if gen_res is not None:  # 임시 문안으로 메워진 컬럼은 더 이상 폐기 상태가 아니다
        merged.dropped = {c: r for c, r in gen_res.dropped.items() if merged.columns.get(c) in (None, "")}
    return merged


def _facts_path(cfg, base: date) -> str:
    return os.path.join(cfg.facts_dir, f"facts_{to_ymd(base)}.json")


def _produce(table: str, ctx: dict, rule_eng: RuleEngine, gen_eng: GenEngine | None, *,
             row_key: str, base_ymd: str, seed: dict | None, force: bool, dry_run: bool,
             facts_path: str, temp_eng: TempEngine | None = None) -> dict:
    """행 1건: 규칙 → (생성형) → (임시 문안) → upsert → 실행 로그. 반환: 결과 요약 dict."""
    started = datetime.now()
    rule_res = rule_eng.generate(table, ctx)
    gen_res = None
    if gen_eng is not None:
        gen_res = gen_eng.generate(table, {**ctx, "rule": rule_res})
    temp_res = None
    fill_res, fill_ver = gen_res, gen_eng.version.ver if gen_eng else None
    if temp_eng is not None:
        temp_res = temp_eng.generate(table, {**ctx, "rule": rule_res})
        fill_res = _merge_temp(gen_res, temp_res)
        # 실제로 임시 문안이 들어간 컬럼(생성형이 비운 자리)만 temp 실행 로그에 남긴다
        temp_used = [c for c in temp_res.columns if gen_res is None or gen_res.columns.get(c) in (None, "")]
        temp_res.columns = {c: temp_res.columns[c] for c in temp_used}
        if temp_used or gen_res is None:  # 임시 문안이 들어간 행은 temp 버전으로 표시
            fill_ver = temp_eng.version.ver
        seed = {**temp_eng.manual(table, ctx), **(seed or {})}  # 고정 문안(fixed_texts)이 있으면 그것이 우선
    status = "error"
    err = None
    try:
        status = writer.upsert(table, rule_res, rule_eng.version.ver, gen=fill_res, gen_ver=fill_ver,
                               manual_seed=seed, force=force, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — 로그에 남기고 다시 올린다
        err = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        if not dry_run:
            registry.log_run(base_ymd=base_ymd, table=table, row_key=row_key, engine=rule_eng,
                             write_stts=status, cols_filled=rule_res.filled, dropped=None,
                             facts_path=facts_path, started=started, err=err)
            if gen_eng is not None and gen_res is not None:
                registry.log_run(base_ymd=base_ymd, table=table, row_key=row_key, engine=gen_eng,
                                 write_stts=status, cols_filled=gen_res.filled, dropped=gen_res.dropped,
                                 facts_path=facts_path, started=started, err=err)
            if temp_eng is not None and temp_res is not None:
                registry.log_run(base_ymd=base_ymd, table=table, row_key=row_key, engine=temp_eng,
                                 write_stts=status, cols_filled=temp_res.filled, dropped=temp_res.dropped,
                                 facts_path=facts_path, started=started, err=err)
    out = {"status": status, "rule_cols_filled": rule_res.filled}
    if gen_res is not None:
        out["gen_cols_filled"] = gen_res.filled
        out["gen_dropped"] = gen_res.dropped
        if gen_res.notes:
            out["gen_notes"] = gen_res.notes
    if temp_res is not None:
        out["temp_cols_filled"] = temp_res.filled
        out["temp_cols"] = sorted(temp_res.columns)
    return out


def run(base: date, *, scope: str = "all", llm: bool | None = None, force: bool = False,
        dry_run: bool = False) -> dict:
    cfg = get_config()
    use_llm = cfg.llm_enabled if llm is None else llm
    rule_eng = RuleEngine(cfg)
    gen_eng = GenEngine(cfg) if use_llm else None
    temp_eng = TempEngine(cfg) if cfg.temp_fill else None
    if not dry_run:
        registry.ensure_tables()
        registry.register(rule_eng)
        if gen_eng:
            registry.register(gen_eng)
        if temp_eng:
            registry.register(temp_eng)
    engines_meta = {"rule": rule_eng.version.ver}
    if gen_eng:
        engines_meta["gen"] = gen_eng.version.ver
        engines_meta["gen_model"] = gen_eng.model_nm
    if temp_eng:
        engines_meta["temp"] = temp_eng.version.ver
    if cfg.allow_dummy:
        log.warning("--allow-dummy: 개발 더미(DEV_DUMMY)를 원천으로 허용 — 정량 문장은 실데이터가 아니다")
    log.info("엔진 버전: %s", engines_meta)

    ntn = sources.country_names()
    fixed = _fixed_texts()
    minerals = sources.minerals(cfg)
    base_ymd = to_ymd(base)
    facts_path = _facts_path(cfg, base)
    facts_all: dict = {"base_ymd": base_ymd, "engines": engines_meta, "allow_dummy": cfg.allow_dummy, "minerals": {}}
    results: dict = {"base_ymd": base_ymd, "engines": engines_meta, "allow_dummy": cfg.allow_dummy,
                     "mnrl": {}, "overall": None}
    common = dict(force=force, dry_run=dry_run, facts_path=facts_path, base_ymd=base_ymd, temp_eng=temp_eng)

    for m in minerals:
        code, name = m["mnrknd_unq_cd"], m["mnrl_nm_ko"]
        facts = collect_mineral_facts(code, name, base, cfg, ntn)
        facts_all["minerals"][code] = facts
        if not any(facts[k] for k in ("price", "diag", "customs", "production", "reserve")):
            results["mnrl"][code] = {"name": name, "status": "skipped(no source)"}
            continue
        if scope in ("all", "mnrl"):
            ctx = {"base": base, "code": code, "facts": facts, "news": []}
            seed = (fixed.get("ai_rpt_mnrl") or {}).get(code)
            out = _produce("ai_rpt_mnrl", ctx, rule_eng, gen_eng, row_key=code, seed=seed, **common)
            out.update(name=name, sources={k: bool(v) for k, v in facts.items() if k != "name"})
            results["mnrl"][code] = out
            log.info("%s(%s): %s, RULE 채움 %d%s%s", name, code, out["status"], out["rule_cols_filled"],
                     f", GEN 채움 {out['gen_cols_filled']} 폐기 {len(out['gen_dropped'])}" if gen_eng else "",
                     f", TEMP 채움 {out['temp_cols_filled']}" if temp_eng else "")

    if scope in ("all", "overall"):
        facts_all["overall"] = sources.overall_diag(base, cfg)
        facts_all["gscpi"] = sources.macro("GSCPI", base, cfg)
        facts_all["gpr"] = sources.macro("GPR", base, cfg)
        ctx = {"base": base, "code": None, "facts": facts_all, "news": []}
        seed = {**overall_manual_from_facts(facts_all), **((fixed.get("ai_rpt_overall") or {}).get("_default") or {})}
        results["overall"] = _produce("ai_rpt_overall", ctx, rule_eng, gen_eng, row_key=base_ymd, seed=seed, **common)
        log.info("overall: %s", results["overall"]["status"])

    os.makedirs(cfg.facts_dir, exist_ok=True)
    with open(facts_path, "w", encoding="utf-8") as f:
        json.dump(facts_all, f, ensure_ascii=False, indent=1, default=str)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="통합보고서 주간 생성 파이프라인(규칙 엔진 + 옵션 생성형 엔진)")
    ap.add_argument("--base-ymd", help="보고 주차 월요일 YYYYMMDD(기본: 가장 최근 월요일)")
    ap.add_argument("--minerals", help="광종코드 쉼표 목록(기본: 진단 대상 5광종 TARGET_MINERALS, all=READY 전부)")
    ap.add_argument("--scope", choices=["all", "overall", "mnrl"], default="all")
    ap.add_argument("--llm", action="store_true", help="생성형 엔진(GenEngine) 실행(기본 비활성)")
    ap.add_argument("--allow-dummy", action="store_true",
                    help="개발 더미(DEV_DUMMY·ai_dev_dummy_load)를 원천으로 허용(임시, 화면 채우기용)")
    ap.add_argument("--temp-fill", action="store_true",
                    help="비어 남은 LLM 컬럼을 resources/temp_texts.json 임시 문안으로 채움(TempEngine)")
    ap.add_argument("--force", action="store_true", help="REVIEWED/DONE 행도 덮어씀")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.minerals:
        os.environ["MNRL_REPORT_MINERALS"] = a.minerals
    if a.allow_dummy:
        os.environ["MNRL_REPORT_ALLOW_DUMMY"] = "1"
    if a.temp_fill:
        os.environ["MNRL_REPORT_TEMP_FILL"] = "1"
    base = from_ymd(a.base_ymd) if a.base_ymd else latest_monday()
    if base.weekday() != 0:
        ap.error("--base-ymd는 월요일이어야 합니다")
    res = run(base, scope=a.scope, llm=True if a.llm else None, force=a.force, dry_run=a.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
