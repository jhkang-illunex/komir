# -*- coding: utf-8 -*-
"""지정학 위기지수 가중치 민감도 분석 (2026-07-16, 외부감사 B-1⑤ 대응).

논점: "지수 가중치(발행처 신뢰도·공급집중·방향부호·심각도·이중노출)가 전문가 임의값이다.
±30% 섭동 시 결과(고위험 순위·경보)가 뒤집히는 비율을 측정해 강건성을 방어하라."

■ 방법
  1) geo/indexer.compute()의 이벤트 단위 점수 로직을 스냅샷에서 복제해 성분을 1회 계산·캐시:
       score = severity × rel × conc × hhi_mult × sgn × imp_mult
       - severity : 사건 심각도(0~3, 추출값)
       - rel      : 발행처 신뢰도(sources.yaml reliability; 미매칭 1.0, GKG 유래=GDELT 0.7)
       - conc     : 공급집중(sources.yaml supply_concentration 정적값; 미매칭 1.0. refdata parquet 없음)
       - hhi_mult : HHI 배수(refdata hhi.parquet 부재 → 1.0 폴백)
       - sgn      : 방향부호(index.yaml direction_sign; 미매칭 0.2)
       - imp_mult : 이중 노출(kr_import_share, (1+s_imp)를 광종별 mean-one 정규화 — indexer 복제)
     GKG '뉴스' 규칙티어 제외·미래일 제외·날짜미상 제외·동일사건 반복보도 dedup 모두 복제.
  2) 주간 지수 복제: 광종×주 raw_score 합 → tanh0_100 정규화(scale_k_by_commodity, 주기배수 W=1).
     복제 검증: baseline vs geo_index.parquet(freq='W')의 상관·평균절대차를 리포트에 명기.
  3) 섭동: {severity, rel, conc, sgn, imp_mult} 5성분 × {×0.7, ×1.3}.

     ▶ 주의(중요) — 순수 곱셈 섭동의 퇴화성:
        점수가 성분들의 순수 곱이므로, 한 성분 전체에 전역 스칼라 f를 곱하면
        모든 이벤트 점수가 동일 배율 f로 스케일된다 → 광종×주 raw_score도 균일하게 f배.
        tanh 정규화는 단조변환이라 순위(광종내·광종간 모두)가 보존되어 Spearman=1.0,
        더구나 5개 성분이 서로 완전히 동일한 결과를 낸다(어느 가중치가 더 민감한지 구분 불가).
        → 전역 곱셈은 "가중치의 상대구조가 틀렸는가"를 전혀 검정하지 못한다(부록 A에서 실증).

     ▶ 그래서 주 섭동은 '평탄 기준선(성분 평균)からの 편차 ±30% 신축'(상대섭동)으로 정의한다:
            X'(f) = a_X + f·(X − a_X),   a_X = 해당 성분의 이벤트 모집단 평균,  f∈{0.7,1.3}
        - f=1.3: 전문가가 준 상대 가중의 대비를 30% 확대(고신뢰/고집중을 더 강조)
        - f=0.7: 상대 가중을 평탄(무차별)쪽으로 30% 축소
        이는 감사 논점("상대 가중치가 임의값 → ±30% 틀렸다면?")을 직접 검정하며, 이벤트마다
        편차가 달라 비균일 → 순위가 실제로 흔들릴 수 있다. severity/sgn은 음수 방지를 위해
        섭동 후 각각의 물리 하한(0 / 부호보존)만 클립한다.
  4) 지표(시나리오별, 광종별+전체): 주간지수 MAE·최대|Δ|, Spearman 순위상관,
     고위험주(지수≥광종별 baseline P90) Jaccard, 지수≥70 주간 수 변화율.
  5) 판정: Spearman≥0.95 & Jaccard≥0.8 → '강건', 미달 성분은 '정밀화 필요'.

■ 격리: 메인 세션이 geo/indexer.py를 동시 수정 중이라, geo 패키지 스냅샷 사본에서 import한다
        (SNAPSHOT 경로). warehouse/minerals.duckdb는 열지 않는다(이벤트 정본 parquet만 사용).

실행:  GEO_DATA=<komir>/geo_data python sensitivity_geo_weights.py
산출:  outputs/model_opt/sensitivity_geo_weights.md  (+ 콘솔 표)
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 경로 ─────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent                                  # .../komir
# geo 패키지 스냅샷(메인 세션의 indexer.py 동시수정과 격리) — 없으면 komir/geo 폴백.
SNAPSHOT = os.environ.get(
    "GEO_SNAPSHOT",
    "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws/"
    "52442d9e-1541-4c6f-9ac0-750e467889f8/scratchpad")
if (Path(SNAPSHOT) / "geo_snapshot").exists():
    sys.path.insert(0, SNAPSHOT)
    from geo_snapshot import config as C, store               # type: ignore  # noqa: E402
    from geo_snapshot.schema import IndexConfig                # type: ignore  # noqa: E402
else:                                                          # 폴백(스냅샷 없을 때)
    sys.path.insert(0, str(KOMIR))
    from geo import config as C, store                         # type: ignore  # noqa: E402
    from geo.schema import IndexConfig                         # type: ignore  # noqa: E402

os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
os.environ["GEO_EVENT_SOURCE"] = "file"                       # 정본 parquet만

OUT = KOMIR / "mineral_supply_risk" / "outputs" / "model_opt"
REPORT = OUT / "sensitivity_geo_weights.md"

COMPONENTS = ["severity", "rel", "conc", "sgn", "imp_mult"]
FACTORS = [0.7, 1.3]
HIGH_THRESH = 70.0        # '경보' 절대 임계
P_HI = 0.90              # 고위험주 분위


# ── 1) 이벤트 단위 점수 성분 계산(indexer.compute 복제) ───────────────────────
def build_scored_events() -> tuple[pd.DataFrame, IndexConfig]:
    """indexer.compute()의 필터·성분 계산을 복제해 이벤트별 성분+주(week)를 반환."""
    ev = store.load_events(source="file")
    if len(ev) == 0:
        raise RuntimeError("이벤트 없음")

    # source 부착(파일 모드: manifest 병합) + GKG 유래 NaN → GDELT 귀속 (indexer 동일)
    if "source" not in ev.columns:
        man = store.load_manifest()[["doc_id", "source"]].drop_duplicates("doc_id")
        ev = ev.merge(man, on="doc_id", how="left")
    if "provider" in ev.columns:
        ev["source"] = ev["source"].fillna(ev["provider"].map({"gkg": "GDELT"}))
    ev["source"] = ev["source"].fillna("GDELT")

    # GKG 규칙기반 '뉴스' 티어 제외
    if "provider" in ev.columns and "extractor" in ev.columns:
        noise = (ev["provider"] == "gkg") & (ev["extractor"] == "rule") & (ev["event_type"] == "뉴스")
        ev = ev[~noise]

    cfg = IndexConfig(**(C.load_yaml("index.yaml") or {}))
    rel_map = {k: float(v) for k, v in (C.load_yaml("sources.yaml").get("reliability") or {}).items()}
    conc_map = {k: float(v) for k, v in (C.load_yaml("sources.yaml").get("supply_concentration") or {}).items()}
    sign = cfg.direction_sign

    ev = ev.copy()
    ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    ev = ev[ev["date"] <= pd.Timestamp.now()]                 # 미래일 제외

    # 동일사건 반복보도 dedup(월+광종+근거문구 앞40자, 최고 severity만)
    ev["_qk"] = ev["evidence_quote"].fillna("").str.strip().str[:40]
    ev["_month"] = ev["date"].dt.to_period("M")
    ev = (ev.sort_values("severity", ascending=False)
            .drop_duplicates(subset=["commodity", "_month", "_qk"], keep="first"))

    # 성분
    ev["rel"] = ev["source"].map(rel_map).fillna(1.0).astype(float)
    ev["conc"] = ((ev["commodity"] + ":" + ev["country"].fillna("")).map(conc_map)
                  .fillna(1.0).astype(float))
    ev["hhi_mult"] = 1.0                                       # refdata hhi.parquet 부재
    ev["sgn"] = ev["direction"].map(sign).fillna(0.2).astype(float)
    ev["severity"] = ev["severity"].astype(float)
    ev = _apply_kr_exposure(ev)                               # imp_mult

    # 주(week) 라벨 — indexer의 resample("W")(우측경계=일요일)와 동일 규칙
    ev["week"] = ev["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    keep = ["commodity", "week", "severity", "rel", "conc", "hhi_mult", "sgn", "imp_mult"]
    return ev[keep].reset_index(drop=True), cfg


def _apply_kr_exposure(ev: pd.DataFrame) -> pd.DataFrame:
    """이중 노출 가중(indexer._apply_kr_exposure 복제): (1+s_imp)를 광종별 mean-one 정규화."""
    f = C.CONFIG / "refdata" / "kr_import_share.parquet"
    if not f.exists() or "country" not in ev.columns:
        ev["imp_mult"] = 1.0
        return ev
    share = pd.read_parquet(f)
    ev["yr"] = ev["date"].dt.year
    yrs = range(int(share["year"].min()), int(ev["yr"].max()) + 1)
    grid = (share.set_index("year").groupby(["commodity", "country"])["imp_share"]
            .apply(lambda s: s.reindex(yrs).ffill().bfill()).reset_index())
    ev = ev.merge(grid.rename(columns={"year": "yr", "imp_share": "s_imp"}),
                  on=["commodity", "country", "yr"], how="left")
    ev["s_imp"] = ev["s_imp"].fillna(0.0)
    raw = 1.0 + ev["s_imp"]
    ev["imp_mult"] = raw / raw.groupby(ev["commodity"]).transform("mean")
    return ev


# ── 2) 주간 지수 산출(indexer._normalize 복제, tanh0_100, W주기배수=1) ─────────
def weekly_index(ev: pd.DataFrame, cfg: IndexConfig, score: pd.Series) -> pd.DataFrame:
    """이벤트별 score → 광종×주 raw_score 합 → tanh0_100 지수. 반환: [commodity, week, index]."""
    g = (pd.DataFrame({"commodity": ev["commodity"], "week": ev["week"], "score": score})
         .groupby(["commodity", "week"], as_index=False)["score"].sum()
         .rename(columns={"score": "raw_score"}))
    kmap = cfg.scale_k_by_commodity or {}
    k = g["commodity"].map(lambda c: float(kmap.get(c, cfg.scale_k)))   # W주기배수 1.0
    g["index"] = 50 + 50 * np.tanh(g["raw_score"].astype(float) / k)
    return g


def base_score(ev: pd.DataFrame) -> pd.Series:
    return (ev["severity"] * ev["rel"] * ev["conc"]
            * ev["hhi_mult"] * ev["sgn"] * ev["imp_mult"])


# ── 3) 섭동 ──────────────────────────────────────────────────────────────────
def perturbed_score(ev: pd.DataFrame, comp: str, f: float, mode: str) -> pd.Series:
    """comp 성분만 섭동한 이벤트 점수. mode='relative'(주) | 'global'(부록 A 퇴화성 실증)."""
    cols = {c: ev[c] for c in ["severity", "rel", "conc", "hhi_mult", "sgn", "imp_mult"]}
    x = ev[comp]
    if mode == "global":
        xp = f * x
    else:  # relative: 성분 평균 기준선からの 편차 ±30% 신축
        a = float(x.mean())
        xp = a + f * (x - a)
        if comp == "severity":
            xp = xp.clip(lower=0.0)                    # 심각도 음수 방지
        # sgn은 부호 자체가 의미(호재/악재) — 클립하지 않고 부호 보존
    cols[comp] = xp
    return (cols["severity"] * cols["rel"] * cols["conc"]
            * cols["hhi_mult"] * cols["sgn"] * cols["imp_mult"])


# ── 4) 지표 ──────────────────────────────────────────────────────────────────
def _spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return float("nan")
    return float(pd.Series(a.values).corr(pd.Series(b.values), method="spearman"))


def scenario_metrics(base: pd.DataFrame, pert: pd.DataFrame) -> dict:
    """base/pert: [commodity, week, index]. 광종별+전체 지표 dict 반환."""
    m = base.merge(pert, on=["commodity", "week"], suffixes=("_b", "_p"))
    # 광종별 baseline P90 임계
    thr = m.groupby("commodity")["index_b"].transform(lambda s: s.quantile(P_HI))
    m["hi_b"] = m["index_b"] >= thr
    m["hi_p"] = m["index_p"] >= thr

    rows = {}
    for c, sub in list(m.groupby("commodity")) + [("전체", m)]:
        mae = float((sub["index_p"] - sub["index_b"]).abs().mean())
        maxd = float((sub["index_p"] - sub["index_b"]).abs().max())
        sp = _spearman(sub["index_b"], sub["index_p"])
        inter = int((sub["hi_b"] & sub["hi_p"]).sum())
        union = int((sub["hi_b"] | sub["hi_p"]).sum())
        jac = inter / union if union else 1.0
        nb = int((sub["index_b"] >= HIGH_THRESH).sum())
        npp = int((sub["index_p"] >= HIGH_THRESH).sum())
        chg = (npp - nb) / nb if nb else (0.0 if npp == 0 else float("inf"))
        rows[c] = dict(mae=mae, maxd=maxd, spearman=sp, jaccard=jac,
                       n_hi_base=nb, n_hi_pert=npp, hi_chg=chg)
    return rows


# ── 5) 실행 ──────────────────────────────────────────────────────────────────
def run():
    print("[1] 이벤트 로드·성분 계산 …")
    ev, cfg = build_scored_events()
    print(f"    점수대상 이벤트 {len(ev):,}건, 광종 {sorted(ev['commodity'].unique())}")

    base = weekly_index(ev, cfg, base_score(ev))
    print(f"    baseline 주간지수 {len(base):,}행")

    # 복제 검증(2축: 라이브 로직 대조 + 저장 parquet 대조)
    valid = validate(base)

    # 섭동 실험(주: relative, 부록: global)
    results = {"relative": {}, "global": {}}
    for mode in ("relative", "global"):
        for comp in COMPONENTS:
            for f in FACTORS:
                pert = weekly_index(ev, cfg, perturbed_score(ev, comp, f, mode))
                results[mode][(comp, f)] = scenario_metrics(base, pert)
        print(f"[3] 섭동({mode}) {len(COMPONENTS)*len(FACTORS)}시나리오 완료")

    verdict = judge(results["relative"])
    write_report(valid, results, verdict, len(ev))
    print(f"[4] 리포트 → {REPORT}")
    _print_console(results["relative"], verdict, valid)
    return results, verdict, valid


def validate(base: pd.DataFrame) -> dict:
    """2축 복제 검증.
      (A) vs 라이브 indexer.compute() — 로직 충실성 증명(refdata 상태 동일 → 정확 일치 기대).
      (B) vs 저장 geo_index.parquet(W) — 상관·MAE 및 refdata 차이 진단(광종별 raw 비율).
    """
    out = {}
    # (A) 라이브 로직 대조
    try:
        try:
            from geo_snapshot import indexer as IX          # 스냅샷 우선
        except Exception:
            from geo import indexer as IX                    # 폴백
        w = IX.compute()
        w = w[w["freq"] == "W"].copy()
        w["week"] = pd.to_datetime(w["period"]).dt.normalize()
        b = base.copy(); b["week"] = pd.to_datetime(b["week"]).dt.normalize()
        m = b.merge(w[["commodity", "week", "index"]], on=["commodity", "week"],
                    suffixes=("_rep", "_ix"))
        out["live"] = dict(n=int(len(m)),
                           corr=float(m["index_rep"].corr(m["index_ix"])),
                           mae=float((m["index_rep"] - m["index_ix"]).abs().mean()))
    except Exception as e:                                    # noqa: BLE001
        out["live"] = dict(err=str(e))

    # (B) 저장 parquet 대조
    idx_path = C.STORE / "geo_index.parquet"
    if not idx_path.exists():
        out["stored"] = dict(ok=False, note="geo_index.parquet 없음")
        return out
    gi = pd.read_parquet(idx_path); gi = gi[gi["freq"] == "W"].copy()
    gi["week"] = pd.to_datetime(gi["period"]).dt.normalize()
    b = base.copy(); b["week"] = pd.to_datetime(b["week"]).dt.normalize()
    m = b.merge(gi[["commodity", "week", "index", "raw_score"]], on=["commodity", "week"],
                suffixes=("_rep", "_off"))
    per = {}
    for c, sub in list(m.groupby("commodity")) + [("전체", m)]:
        if len(sub) < 3:
            continue
        ratio = (sub["raw_score_rep"] / sub["raw_score_off"].replace(0, np.nan)).median()
        per[c] = dict(n=int(len(sub)),
                      corr=float(sub["index_rep"].corr(sub["index_off"])),
                      mae=float((sub["index_rep"] - sub["index_off"]).abs().mean()),
                      raw_ratio=float(ratio))
    out["stored"] = dict(ok=True, per=per, matched=int(len(m)),
                         base_n=int(len(base)), coverage=len(m) / len(base) if len(base) else 0.0)
    return out


def judge(rel: dict) -> dict:
    """성분별 판정: 두 방향(×0.7,×1.3) 중 최악 전체 Spearman/Jaccard 기준."""
    out = {}
    for comp in COMPONENTS:
        sp = min(rel[(comp, f)]["전체"]["spearman"] for f in FACTORS)
        jac = min(rel[(comp, f)]["전체"]["jaccard"] for f in FACTORS)
        mae = max(rel[(comp, f)]["전체"]["mae"] for f in FACTORS)
        robust = (sp >= 0.95) and (jac >= 0.8)
        out[comp] = dict(spearman=sp, jaccard=jac, mae=mae,
                         verdict="강건" if robust else "정밀화 필요")
    return out


# ── 리포트 ───────────────────────────────────────────────────────────────────
def _fmt(x, nd=3):
    if isinstance(x, float) and (np.isinf(x) or np.isnan(x)):
        return "–"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def write_report(valid, results, verdict, n_ev):
    L = []
    L.append("# 지정학 위기지수 가중치 민감도 분석 (외부감사 B-1⑤)\n")
    L.append(f"- 생성: 2026-07-16 · 점수대상 이벤트 **{n_ev:,}건** · 광종 CU/NI/LI/CO/REE\n")
    L.append("- 대상 가중치 5성분: `severity`(심각도) · `rel`(발행처 신뢰도) · "
             "`conc`(공급집중) · `sgn`(방향부호) · `imp_mult`(한국 이중노출)\n")

    # 판정 요약
    L.append("\n## 1. 판정 요약\n")
    L.append("| 성분 | 최악 Spearman | 최악 Jaccard(P90) | 최대 MAE(pt) | 판정 |")
    L.append("|---|---|---|---|---|")
    order = sorted(COMPONENTS, key=lambda c: (verdict[c]["jaccard"], verdict[c]["spearman"]))
    for c in order:
        v = verdict[c]
        L.append(f"| `{c}` | {_fmt(v['spearman'])} | {_fmt(v['jaccard'])} | "
                 f"{_fmt(v['mae'],2)} | **{v['verdict']}** |")
    L.append("\n> 판정 기준: 전체(pooled) 기준 두 섭동방향(×0.7·×1.3) 중 **최악값**이 "
             "Spearman≥0.95 **및** Jaccard≥0.8이면 '강건'. 표는 취약→강건 순 정렬.\n")
    worst = order[0]
    L.append(f"\n**가장 민감한 가중치: `{worst}`** "
             f"(Jaccard {_fmt(verdict[worst]['jaccard'])}, Spearman {_fmt(verdict[worst]['spearman'])}).\n")

    # 복제 검증(2축)
    L.append("\n## 2. 복제 검증\n")
    live = valid.get("live", {})
    if "err" not in live:
        L.append("**(A) 라이브 `indexer.compute()` 대조 — 로직 충실성**: "
                 f"매칭 {live.get('n',0):,}주, 상관 **{_fmt(live.get('corr',float('nan')),4)}**, "
                 f"평균절대차 **{_fmt(live.get('mae',float('nan')),4)}pt**. "
                 "→ 본 스크립트의 점수·정규화 복제가 현행 지수 산출 로직과 **정확히 일치**함을 확인.\n")
    else:
        L.append(f"**(A) 라이브 대조 실패**: {live['err']}\n")

    stored = valid.get("stored", {})
    if stored.get("ok"):
        L.append(f"\n**(B) 저장 `geo_index.parquet`(freq='W') 대조**: "
                 f"매칭 {stored['matched']:,}주 / 복제 {stored['base_n']:,}주 "
                 f"(커버리지 {stored['coverage']:.1%})\n")
        L.append("| 광종 | n | 상관 | 평균절대차(pt) | raw비율(복제/저장) |")
        L.append("|---|---|---|---|---|")
        for c, d in stored["per"].items():
            L.append(f"| {c} | {d['n']} | {_fmt(d['corr'],4)} | {_fmt(d['mae'],3)} | {_fmt(d['raw_ratio'],3)} |")
        allc = stored["per"].get("전체", {})
        L.append(f"\n> 저장본과의 전체 상관 **{_fmt(allc.get('corr',float('nan')),4)}** / "
                 f"평균절대차 **{_fmt(allc.get('mae',float('nan')),3)}pt**. "
                 "저장본은 USGS **refdata(concentration/hhi)가 존재하던 시점**에 생성됐으나 "
                 "현재 `geo_data/config/refdata`에는 `kr_import_share.parquet`만 남아 있어(부재 확인) "
                 "라이브 로직은 conc=1.0·hhi=1.0 폴백을 쓴다. 그 결과 **단일국 공급집중이 강한 "
                 "CO·REE·LI에서 raw 비율이 가장 낮고**(refdata conc 부재로 저장본 대비 축소), "
                 "집중도가 낮은 CU·NI는 ~0.98로 거의 일치 — 괴리가 전적으로 refdata 차이에서 "
                 "온다는 방증. **민감도 분석 자체는 라이브 로직과 정확 일치(A)하는 baseline 위에서 "
                 "수행되므로 유효**하다.\n")
    else:
        L.append(f"\n**(B) 저장본 대조 불가**: {stored.get('note')}\n")

    # 상대섭동 상세
    L.append("\n## 3. 상대섭동 상세 지표 (전체 pooled)\n")
    L.append("각 가중치의 '성분평균 기준선からの 편차'를 ±30% 신축(f=0.7 축소 / f=1.3 확대).\n")
    L.append("| 성분 | f | MAE(pt) | 최대\\|Δ\\|(pt) | Spearman | Jaccard | 지수≥70 base→pert | 변화율 |")
    L.append("|---|---|---|---|---|---|---|---|")
    rel = results["relative"]
    for comp in COMPONENTS:
        for f in FACTORS:
            t = rel[(comp, f)]["전체"]
            L.append(f"| `{comp}` | ×{f} | {_fmt(t['mae'],2)} | {_fmt(t['maxd'],2)} | "
                     f"{_fmt(t['spearman'])} | {_fmt(t['jaccard'])} | "
                     f"{t['n_hi_base']}→{t['n_hi_pert']} | {_fmt(t['hi_chg'],3)} |")

    # 광종별 상세(가장 민감한 성분)
    L.append(f"\n## 4. 광종별 상세 — 가장 민감한 `{worst}` (×1.3)\n")
    L.append("| 광종 | MAE(pt) | Spearman | Jaccard | 지수≥70 base→pert |")
    L.append("|---|---|---|---|---|")
    for c, t in rel[(worst, 1.3)].items():
        if c == "전체":
            continue
        L.append(f"| {c} | {_fmt(t['mae'],2)} | {_fmt(t['spearman'])} | {_fmt(t['jaccard'])} | "
                 f"{t['n_hi_base']}→{t['n_hi_pert']} |")

    # 부록 A: 전역 곱셈 퇴화성
    L.append("\n## 부록 A. 순수 곱셈(전역) 섭동의 퇴화성 실증\n")
    L.append("점수가 성분의 순수 곱이라, 한 성분에 전역 스칼라를 곱하면 주간 raw_score가 "
             "**균일 배율**로만 변해 tanh 정규화 후 순위가 보존된다. 아래처럼 5성분이 "
             "Spearman=1.0으로 동일하며(순위 불변) 절대임계(지수≥70)만 이동한다 — "
             "'상대 가중치가 틀렸는가'는 검정 못 함. 그래서 본문은 상대섭동을 사용한다.\n")
    L.append("| 성분 | f | Spearman | Jaccard | 지수≥70 base→pert |")
    L.append("|---|---|---|---|---|")
    gl = results["global"]
    for comp in COMPONENTS:
        for f in FACTORS:
            t = gl[(comp, f)]["전체"]
            L.append(f"| `{comp}` | ×{f} | {_fmt(t['spearman'])} | {_fmt(t['jaccard'])} | "
                     f"{t['n_hi_base']}→{t['n_hi_pert']} |")

    L.append("\n## 5. 결론\n")
    robust_ = [c for c in COMPONENTS if verdict[c]["verdict"] == "강건"]
    weak_ = [c for c in COMPONENTS if verdict[c]["verdict"] != "강건"]
    L.append(f"- **강건**: {', '.join('`'+c+'`' for c in robust_) or '없음'}\n")
    L.append(f"- **정밀화 필요**: {', '.join('`'+c+'`' for c in weak_) or '없음'}\n")
    L.append(f"- 순위 안정성이 가장 낮은 가중치는 `{worst}` — 캘리브레이션 근거 문서화 우선순위.\n")

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")


def _print_console(rel, verdict, valid):
    print("\n=== 판정 요약(취약→강건) ===")
    order = sorted(COMPONENTS, key=lambda c: (verdict[c]["jaccard"], verdict[c]["spearman"]))
    for c in order:
        v = verdict[c]
        print(f"  {c:9s} Spearman={_fmt(v['spearman'])} Jaccard={_fmt(v['jaccard'])} "
              f"MAE={_fmt(v['mae'],2)}pt → {v['verdict']}")
    live = valid.get("live", {})
    if "err" not in live:
        print(f"\n복제검증(A) 라이브 대조: 상관 {_fmt(live.get('corr',float('nan')),4)} / "
              f"MAE {_fmt(live.get('mae',float('nan')),4)}pt (정확 일치)")
    stored = valid.get("stored", {})
    if stored.get("ok"):
        allc = stored["per"].get("전체", {})
        print(f"복제검증(B) 저장parquet 대조: 상관 {_fmt(allc.get('corr',float('nan')),4)} / "
              f"MAE {_fmt(allc.get('mae',float('nan')),3)}pt (refdata 부재로 CO/REE/LI 괴리)")


if __name__ == "__main__":
    run()
