# -*- coding: utf-8 -*-
"""방향긍정 보류 14건 결합(joint) 검정 (2026-07-31, 사용자 요청).

배경: R10 하네스는 후보를 순차/그리디로 하나씩만 챔피언 위에 얹어 검정한다.
개별로는 CI가 0을 포함해 "방향긍정 보류"로 남은 14건이, 광종축 안에서
전부 결합했을 때는(상호작용/합산 효과로) 유의해질 수 있는지 확인 — 이건
지금까지 한 번도 검정한 적 없는 조합이다.

대상(r10_retune_report.md 실측 재확인, 2026-07-31):
  NI(9): ni_ph·jp_ni·cn_ni·au_ni·ph_psa·id_ni·us_ni·supdiv_ni·fgap_ni
  CU(3): cn_cu·au_cu·cl_cu_ref
  LI(1): fgap_li — 광종 내 유일 후보라 결합 대상 없음(개별 결과=결합 결과, 재실행 불요)
  풀링(1): bill_jp — 상동, 재실행 불요

방법: r10_retune_harness.py와 동일 파이프라인(build_panel→...→build_derived_features)
재사용, meta[name]["feats"]를 광종별로 concat해 e2_delta_classifier 스크리닝 +
bootstrap_diff 확정검정. 채택 기준·부트스트랩 시드(rng=0)까지 완전히 동일해
결과가 직접 비교 가능하다.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics, e2_delta_classifier  # noqa: E402
from scripts.diagnosis_aux_features_eval import build_aux, INV_F  # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch  # noqa: E402
from scripts.diagnosis_priority_feeds_eval import build_pmi, PMI_F, bootstrap_diff  # noqa: E402
from scripts.diag_refine1 import build_refined  # noqa: E402
from scripts.diagnosis_tier1_eval import build_tier1, CNOI_F  # noqa: E402
from scripts.r10_retune_harness import build_new_features, build_derived_features  # noqa: E402

JOINT_GROUPS = {
    "NI": ["ni_ph", "jp_ni", "cn_ni", "au_ni", "ph_psa", "id_ni", "us_ni",
          "supdiv_ni", "fgap_ni"],
    "CU": ["cn_cu", "au_cu", "cl_cu_ref"],
}


def main():
    db = os.environ["MSR_DB"]
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    print(f"패널 종점: {df['obs_date'].max().date()}")
    df = add_dynamics(df); df = build_aux(db, df)
    df = exch.build_cninv(db, df); df = build_pmi(db, df); df = build_refined(db, df)
    df = build_tier1(db, df)
    df, meta = build_new_features(db, df)
    df, meta2 = build_derived_features(db, df)
    meta.update(meta2)

    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    PER_CC_CHAMP = {"CU": nolag + CNOI_F, "NI": nolag + INV_F + exch.CNINV_F}
    rng = np.random.default_rng(0)

    print("\n=== 방향긍정 보류 14건 결합(joint) 검정 ===")
    for cc, names in JOINT_GROUPS.items():
        missing = [n for n in names if n not in meta]
        if missing:
            print(f"[{cc}] [warn] meta 누락: {missing} — 건너뜀")
            continue
        joint_feats = []
        for n in names:
            joint_feats += meta[n]["feats"]
        base_feats = PER_CC_CHAMP[cc]
        d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
        base = e2_delta_classifier(d1, base_feats, "Logistic")
        joint = e2_delta_classifier(d1, base_feats + joint_feats, "Logistic")
        print(f"\n[{cc}] 결합 {len(names)}건({', '.join(names)})")
        print(f"  기준(개별 채택분 포함 챔피언): QWK {base['QWK']:.4f} "
              f"chg {base['chg_acc']:.4f} FAR {base['FAR']:.4f}")
        print(f"  결합 스크리닝: QWK {joint['QWK']:.4f} chg {joint['chg_acc']:.4f} "
              f"FAR {joint['FAR']:.4f}")
        b = bootstrap_diff(d1, base_feats, base_feats + joint_feats, nolag, rng)
        print(f"  부트스트랩: QWK CI [{b['qwk_ci'][0]:+.4f},{b['qwk_ci'][1]:+.4f}] "
              f"P={b['qwk_p']:.3f} | chg CI [{b['chg_ci'][0]:+.3f},"
              f"{b['chg_ci'][1]:+.3f}] P={b['chg_p']:.3f}")
        adopt = (b["qwk_ci"][0] > 0) or (b["chg_ci"][0] > 0 and b["qwk_ci"][0] > -0.005)
        print(f"  → {'**결합 채택후보(유의)**' if adopt else '결합도 방향긍정 보류(무차별)'}")


if __name__ == "__main__":
    main()
