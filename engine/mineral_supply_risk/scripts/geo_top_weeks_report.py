# -*- coding: utf-8 -*-
"""광종별 지수 상위 20개 주간 대표 이벤트 사례표(B-7) — 피드백기반_수정플랜 P2.

geo_index(freq='W') 상위 20개 주간(광종별)을 뽑아, 해당 주(obs_date가 period~period+6일)에
속한 geo_event 중 severity가 가장 높은 대표 이벤트 최대 3건(발행처·헤드라인/근거문구·
severity·direction)을 사람이 읽을 수 있는 표로 정리 — "지수가 왜 올라갔는지" 신호 타당성을
빠르게 검토할 수 있는 근거자료 제공. 모델링 변경 없음, 순수 조회·요약.

실행: python3 -m scripts.geo_top_weeks_report
산출: outputs/model_opt/geo_top_weeks_report.md
"""
from __future__ import annotations
import os

import duckdb
import pandas as pd

from msr.config import DB_PATH, OUT

TOP_N = 20
EVENTS_PER_WEEK = 3


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db, read_only=True)

    idx = con.execute("""
        select commodity_code, period, idx_value, n_events, raw_score
        from geo_index where freq='W'
    """).fetchdf()
    idx["period"] = pd.to_datetime(idx["period"])

    ev = con.execute("""
        select event_id, commodity_code, obs_date, country, event_type, direction,
               severity, confidence, evidence_quote, source, provider, dimension
        from geo_event
    """).fetchdf()
    ev["obs_date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    con.close()

    top = (idx.sort_values(["commodity_code", "idx_value"], ascending=[True, False])
              .groupby("commodity_code").head(TOP_N).copy())
    top = top.sort_values(["commodity_code", "idx_value"], ascending=[True, False])
    print(f"광종별 상위 {TOP_N}개 주간 추출: 총 {len(top)}행")

    rows = []
    n_no_event = 0
    for _, r in top.iterrows():
        cc, p0 = r["commodity_code"], r["period"]
        p1 = p0 + pd.Timedelta(days=6)
        wk_ev = ev[(ev["commodity_code"] == cc) & (ev["obs_date"] >= p0) & (ev["obs_date"] <= p1)]
        wk_ev = wk_ev.sort_values("severity", ascending=False).head(EVENTS_PER_WEEK)
        if len(wk_ev) == 0:
            n_no_event += 1
        rows.append(dict(commodity=cc, week=p0.strftime("%Y-%m-%d"), idx_value=float(r["idx_value"]),
                          n_events_week=int(r["n_events"]), events=wk_ev))
    print(f"이벤트 매칭 실패(대표 이벤트 0건) 주간: {n_no_event}/{len(top)}")

    write_report(rows, n_no_event)


def write_report(rows, n_no_event):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "geo_top_weeks_report.md")
    L = []
    L.append("# 광종별 지수 상위 20개 주간 대표 이벤트 사례표 (B-7)\n")
    L.append(f"작성: 2026-07-16 · 조회: `geo_index`(freq='W', {DB_PATH_NOTE()})에서 광종별 "
             f"idx_value 상위 {TOP_N}개 주간 추출 → 각 주간(period~period+6일)에 속한 "
             f"`geo_event`를 severity 내림차순 상위 {EVENTS_PER_WEEK}건 대표 이벤트로 매칭. "
             f"모델링 변경 없음, 순수 조회.\n")
    L.append(f"대표 이벤트 0건으로 매칭된 주간: {n_no_event}/{len(rows)}건 "
             f"(사유는 각 주 항목에 '매칭 이벤트 없음'으로 표기 — 이벤트 결측이 아니라 "
             f"해당 광종·주간 조합에 직접 태깅된 이벤트가 없을 수 있음).\n")

    cur_cc = None
    for r in rows:
        if r["commodity"] != cur_cc:
            cur_cc = r["commodity"]
            L.append(f"\n## {cur_cc}\n")
            L.append("| 주(월요일 기준) | idx_value | 주간 n_events | 대표 이벤트(발행처/국가/유형/방향/severity/근거) |")
            L.append("|---|---|---|---|")
        if len(r["events"]) == 0:
            ev_str = "매칭 이벤트 없음"
        else:
            parts = []
            for _, e in r["events"].iterrows():
                quote = str(e["evidence_quote"])[:80].replace("|", "/").replace("\n", " ") if pd.notna(e["evidence_quote"]) else ""
                parts.append(f"[{e['source']}/{e['country']}/{e['event_type']}/{e['direction']}/"
                             f"sev={e['severity']:.2f}] {quote}")
            ev_str = "<br>".join(parts)
        L.append(f"| {r['week']} | {r['idx_value']:.2f} | {r['n_events_week']} | {ev_str} |")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[geo_top_weeks_report] 리포트 → {path}")


def DB_PATH_NOTE():
    return os.environ.get("MSR_DB", DB_PATH)


if __name__ == "__main__":
    run()
