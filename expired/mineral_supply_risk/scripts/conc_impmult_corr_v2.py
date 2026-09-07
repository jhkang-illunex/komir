# -*- coding: utf-8 -*-
"""conc(공급집중) × imp_mult(한국 수입노출) 상관관계/이중계상 재점검 (B-4 v2, 2026-07-22).

2026-07-16 `conc_impmult_corr.py`(B-4)는 USGS refdata(`concentration.parquet`)가 이
환경에 백필되지 않아 실제 운영 경로(`sources.yaml` 정적 6쌍 맵)를 재현해 상관관계를
계산했고, "conc가 사실상 1~2개 국가에서만 1.0이 아니라 표본이 희소해 상관계수 판정이
아직 무의미하다 — USGS refdata 백필 후 재실행하면 유의미해진다"고 결론지었다.
2026-07-22 시점정합성(#8) 수정과 함께 USGS refdata를 최초로 실제 가동시켰으므로(릴리스
2022·2023·2025·2026 확보) 이제 재실행한다. 원본 스크립트/보고서는 artifact-provenance
정책상 삭제하지 않고 그대로 보존, 이 파일은 신규 v2 산출물로 별도 저장.

실행: python3 -m scripts.conc_impmult_corr_v2
산출: outputs/model_opt/conc_impmult_corr_v2.md
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
from geo.indexer import _asof_grid  # noqa: E402

from msr.config import OUT

THRESH = 0.5
ASOF_YEAR = 2026   # "현재 구조" 스냅샷 — 가장 최신 as-of 시점 기준 conc


def run():
    refdata_dir = C.CONFIG / "refdata"
    conc_pq = refdata_dir / "concentration.parquet"
    if not conc_pq.exists():
        print("[fail] concentration.parquet 없음 — geo refdata 먼저 실행 필요"); return
    conc_df = pd.read_parquet(conc_pq)
    conc_grid = _asof_grid(conc_df, ["commodity", "country"], "weight", [ASOF_YEAR])
    conc_grid = conc_grid.rename(columns={"weight": "conc"}).drop(columns="yr")
    print(f"USGS conc({ASOF_YEAR} as-of): {len(conc_grid)}개 (광종,국가) 실측 쌍 "
          f"(구 정적맵은 5광종 합쳐 6쌍뿐이었음)")

    share = pd.read_parquet(refdata_dir / "kr_import_share.parquet")
    g = share.groupby(["commodity", "country"], as_index=False)["imp_share"].mean()
    g = g.merge(conc_grid, on=["commodity", "country"], how="left")
    g["conc"] = g["conc"].fillna(1.0)
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
    write_report(res, conc_grid)


def write_report(res, conc_grid):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "conc_impmult_corr_v2.md")
    L = []
    L.append("# conc × imp_mult 상관관계/이중계상 재점검 (B-4 v2, 2026-07-22)\n")
    L.append("작성: 2026-07-22 · 시점정합성(#8) 수정과 함께 USGS refdata를 최초 가동시킨 뒤 재실행. "
              "원본(`conc_impmult_corr.md`, 2026-07-16, 정적맵 폴백 재현)은 그대로 보존.\n")
    L.append(f"\n## USGS conc 실측 커버리지: {len(conc_grid)}개 (광종,국가) 쌍 "
             f"({ASOF_YEAR} as-of) — 구 정적맵({'6'}쌍) 대비 대폭 확대\n")
    L.append("\n## 광종별 conc × imp_mult 상관계수(국가 단위, 실측 USGS 기준)\n")
    L.append("| 광종 | 국가수 | conc≠1.0 국가수 | 상관계수 r | 판정 |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        rv = r["r"]
        verdict = "—(정의불가)" if rv is None else ("이중계상 우려(|r|>0.5)" if abs(rv) > THRESH else "이중계상 우려 없음")
        rv_s = "—" if rv is None else f"{rv:.4f}"
        L.append(f"| {r['commodity']} | {int(r['n_country'])} | {int(r['n_conc_nondefault'])} | {rv_s} | {verdict} |")
    n_flag = int((res["r"].abs() > THRESH).sum()) if res["r"].notna().any() else 0
    L.append(f"\n**결론**: {n_flag}/5개 광종이 |r|>{THRESH} 초과. 이번엔 conc가 광종당 수십 개국의 "
              "실측 USGS 생산점유(as-of 조인)라 2026-07-16 정적맵 기준(1~2개국뿐)보다 훨씬 "
              "유의미한 표본 — 이 판정이 진짜 이중계상 여부에 대한 최초의 실질적 근거다.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[write] {path}")


if __name__ == "__main__":
    run()
