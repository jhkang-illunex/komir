import json, re, sys
from collections import defaultdict
d = json.load(open(sys.argv[1]))
by_rule = defaultdict(list)
for e in d["entries"]:
    for v in e.get("violations", []):
        by_rule[v.split(" ")[0]].append((e, v))
def body(md):
    i = md.find("## 핵심"); j = md.find("## 주요 지표")
    return md[i:j if j > 0 else None].replace("\n", " ")
for rule, items in by_rule.items():
    print(f"\n===== {rule} ({len(items)}건) — 페이지: {sorted({e['page_id'] for e,_ in items})}")
    for e, v in items[:3]:
        print(f"-- {e['combo_key'][:45]} | {v[:90]}")
        txt = body(e["markdown"])
        if rule == "G02":
            for m in re.finditer(r".{40}(evidence|근거 id|current_state|allowed_evidence|output_contract|evidence_id).{40}", txt, re.I):
                print("   …" + m.group(0) + "…"); break
        elif rule == "G05":
            for m in re.finditer(r".{40}\d{4}-\d{2}.{30}", txt):
                print("   …" + m.group(0) + "…"); break
        elif rule == "G04":
            print("   " + txt[:400])
        elif rule == "P-global-02":
            i = txt.find("## 주요 변화"); print("   " + txt[i:i+350])
        elif rule == "P-map-01":
            print("   " + txt[:500])
print("\n===== FALLBACKS")
for e in d["entries"]:
    if e["status"] == "ok" and not e["llm_refined"]:
        print(e["page_id"], e["combo_key"][:40], [w[-60:] for w in e["warnings"] if w.startswith("LLM ")])
