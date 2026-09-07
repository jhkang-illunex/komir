# -*- coding: utf-8 -*-
"""[3] 뷰 생성: 광종별 년/월 이슈파일(md·yaml) — provenance 포함."""
import pandas as pd
from . import config as C, store


def generate(index_df: pd.DataFrame):
    ev = store.load_events()
    man = store.load_manifest()[["doc_id", "source", "orig_name"]].drop_duplicates("doc_id")
    if len(ev):
        ev = ev.merge(man, on="doc_id", how="left")
        ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    idx_m = index_df[index_df.freq == "M"].copy() if len(index_df) else pd.DataFrame()

    for _, r in idx_m.iterrows():
        c = r["commodity"]; ym = str(r["period"])[:7]; y, m = ym.split("-")
        d = C.WIKI / c / y
        d.mkdir(parents=True, exist_ok=True)
        rows = ev[(ev["commodity"] == c) & (ev["date"].dt.strftime("%Y-%m") == ym)] if len(ev) else pd.DataFrame()
        # markdown
        lines = [f"# {c} 지정학 이슈 — {ym}", "",
                 f"- 월간 지수: **{r['index']:.1f}** (raw {r['raw_score']:.2f}, 이벤트 {int(r['n_events'])}건)", ""]
        if len(rows):
            lines.append("| event_type | dir | sev | country | 출처 | 근거 |")
            lines.append("|---|---|---|---|---|---|")
            for _, e in rows.iterrows():
                q = str(e.get("evidence_quote", ""))[:80].replace("|", "／").replace("\n", " ")
                lines.append(f"| {e['event_type']} | {e['direction']} | {e['severity']:.0f} | "
                             f"{e.get('country') or '-'} | {e.get('source') or '-'}:{str(e.get('orig_name') or '')[:24]} | {q} |")
        else:
            lines.append("_이벤트 없음_")
        (d / f"{m}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[wiki] {C.WIKI} 갱신")
