# -*- coding: utf-8 -*-
"""conc(공급집중) × imp_mult(한국 수입노출) 상관관계/이중계상 점검(B-4) — 피드백기반_수정플랜 P2.

geo/indexer.py의 compute()가 실제 운영에서 쓰는 두 가중치의 원천 refdata를 그대로 읽어
광종별 국가 단위 상관계수를 산출한다. |r|>0.5인 광종은 곱셈 결합(score에 conc×imp_mult가
모두 곱해짐)이 동일 신호를 이중계상할 위험이 있어 max 결합 또는 직교화(잔차화) 검토 대상.

**중요 발견(2026-07-16)**: `geo/indexer.py._load_refdata()`가 읽는
`geo_data/config/refdata/concentration.parquet`(USGS 연도별 국가점유)가 **아직 백필되지
않아 파일이 존재하지 않음** — 따라서 `compute()`의 `conc_df is not None` 분기(USGS 우선)는
운영에서 한 번도 실행된 적이 없고, 실제로는 폴백 분기(`sources.yaml`의 정적
`supply_concentration` 맵, 6개 (광종,국가) 쌍만 1.0이 아닌 값, 나머지는 전부 1.0 기본값)가
쓰이고 있다. 이 스크립트는 **실제 운영 경로(정적 맵)를 그대로 재현**해 상관관계를 계산한다
— USGS refdata 백필 후에는 재계산 필요(별도 과제, next-tasks-komir 항목 6).

imp_mult 재현: indexer.py._apply_kr_exposure()와 동일하게 (1+s_imp)를 광종별 이벤트
모집단 mean-one 정규화. 이벤트별이 아니라 국가×연도 그리드 전체에 대해 계산(이벤트 가중치
없이 국가 단위 균등 가중) — 이벤트 분포 가중을 반영하려면 geo_event 조인이 필요하나, 이
분석의 목적(정적 conc와 s_imp 자체의 구조적 상관 여부)에는 연도 평균 국가 단위로 충분.

실행: python3 -m scripts.conc_impmult_corr
산출: outputs/model_opt/conc_impmult_corr.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
from geo import config as C  # noqa: E402

from msr.config import OUT

THRESH = 0.5


def run():
    conc_map = (C.load_yaml("sources.yaml") or {}).get("supply_concentration") or {}
    conc_map = {k: float(v) for k, v in conc_map.items()}
    print(f"정적 conc 맵: {len(conc_map)}개 (광종,국가) 쌍 — {conc_map}")

    refdata_dir = C.CONFIG / "refdata"
    conc_pq = refdata_dir / "concentration.parquet"
    usgs_missing = not conc_pq.exists()
    print(f"USGS concentration.parquet 존재 여부: {not usgs_missing} "
          f"({'미백필 — 정적 맵 폴백 경로로 재현' if usgs_missing else '존재 — 정적 맵과 별개로 재검증 필요'})")

    share = pd.read_parquet(refdata_dir / "kr_import_share.parquet")
    # 국가×연도 평균으로 국가 단위 대표 s_imp 산출(이벤트 가중 없이 refdata 자체 구조 분석)
    g = share.groupby(["commodity", "country"], as_index=False)["imp_share"].mean()
    g["conc"] = g.apply(lambda r: conc_map.get(f"{r['commodity']}:{r['country']}", 1.0), axis=1)
    raw = 1.0 + g["imp_share"]
    g["imp_mult"] = raw / raw.groupby(g["commodity"]).transform("mean")

    rows = []
    for cc, sub in g.groupby("commodity"):
        r = sub["conc"].corr(sub["imp_mult"])
        n_nondefault = int((sub["conc"] != 1.0).sum())
        rows.append(dict(commodity=cc, n_country=len(sub), n_conc_nondefault=n_nondefault,
                          r=round(r, 4) if pd.notna(r) else None))
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))

    write_report(res, conc_map, usgs_missing, g)


def write_report(res, conc_map, usgs_missing, g):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "conc_impmult_corr.md")
    L = []
    L.append("# conc × imp_mult 상관관계/이중계상 점검 (B-4)\n")
    L.append("작성: 2026-07-16 · `geo/indexer.py`가 실제로 쓰는 refdata 경로를 그대로 재현.\n")

    L.append("\n## 핵심 발견: USGS refdata 미백필 → 실제로는 정적 맵 경로가 운영 중\n")
    L.append(f"`geo_data/config/refdata/concentration.parquet` "
             f"{'미존재' if usgs_missing else '존재'} — `indexer.py._load_refdata()`가 "
             f"`None`을 반환하면 `compute()`는 USGS 연도별 국가점유 분기를 건너뛰고 "
             f"`sources.yaml`의 정적 `supply_concentration` 맵(**{len(conc_map)}개 (광종,국가) "
             f"쌍만 1.0이 아닌 값**, 나머지 전체 국가는 기본값 1.0)으로 폴백한다. 즉 현재 "
             f"운영 중인 지수의 `conc` 가중치는 사실상 대부분의 이벤트에서 상수 1.0이고, "
             f"공급집중 신호가 실질적으로 반영되는 것은 이 {len(conc_map)}쌍뿐이다.\n")
    L.append("| 광종:국가 | conc |")
    L.append("|---|---|")
    for k, v in conc_map.items():
        L.append(f"| {k} | {v} |")

    L.append("\n## 광종별 conc × imp_mult 상관계수(국가 단위, USGS 도입 전 정적 맵 기준)\n")
    L.append("| 광종 | 국가수 | conc≠1.0 국가수 | 상관계수 r | 판정 |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        rv = r["r"]
        verdict = "—(정의불가)" if rv is None else ("이중계상 우려(|r|>0.5)" if abs(rv) > THRESH else "이중계상 우려 없음")
        rv_s = "—" if rv is None else f"{rv:.4f}"
        L.append(f"| {r['commodity']} | {int(r['n_country'])} | {int(r['n_conc_nondefault'])} | {rv_s} | {verdict} |")

    n_flag = int((res["r"].abs() > THRESH).sum()) if res["r"].notna().any() else 0
    L.append(f"\n**결론**: {n_flag}/5개 광종이 |r|>{THRESH} 임계치 초과. 단, conc가 사실상 "
             f"광종당 1~2개 국가에서만 1.0이 아니므로(전체 {len(conc_map)}쌍, 5광종 평균 "
             f"1.2쌍) 표본 대부분이 conc=1.0 상수라 상관계수가 이 소수 비상수 국가의 imp_mult "
             f"값에 크게 좌우되는 구조 — **현재로선 상관계수 자체보다 'conc 신호가 국가 커버리지 "
             f"측면에서 너무 희소하다'는 것이 더 시급한 문제**(USGS refdata 백필로 우선 해결 "
             f"필요, next-tasks-komir 항목 6). 백필 후 이 스크립트를 재실행하면 (광종,국가,연도) "
             f"전 조합에 실질 conc 값이 생겨 상관관계 판정이 비로소 유의미해진다.\n")

    L.append("\n## 재현성\n")
    L.append("`geo/indexer.py._apply_kr_exposure()`와 동일한 mean-one 정규화 식을 재사용, "
             "이벤트 가중 없이 (광종,국가) 단위로 연도 평균 imp_share를 사용 — 실제 지수 "
             "계산에서는 이벤트 발생 빈도에 따라 국가별 가중이 달라지므로 이 결과는 refdata "
             "구조 자체의 상관관계이며 이벤트 가중 반영 상관관계와는 다를 수 있음.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[conc_impmult_corr] 리포트 → {path}")


if __name__ == "__main__":
    run()
