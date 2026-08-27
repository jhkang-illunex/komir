import json, sys
path = sys.argv[1]
d = json.load(open(path))
for e in d["entries"]:
    if e["status"] != "ok":
        print("ERR", e["page_id"], e["combo_key"][:40], e["status"], e.get("error", "")[:80]); continue
    if not e["llm_refined"]:
        w = [x for x in e["warnings"] if x.startswith("LLM ")][-1]
        n = {s: len(e["summary"][s]) for s in ("core_diagnosis", "major_changes", "current_position")}
        print("FALLBACK", e["page_id"], e["combo_key"][:40], "| claims/section", n, "|", w.split("검증 사유: ")[-1][:40])
        for a in e.get("llm_attempts", []):
            if "output" in a:
                out = a["output"]
                allowed = dict(a["allowed"])
                used = [(sec, s["evidence_ids"]) for sec in out for s in out[sec]]
                wrong = [(sec, i) for sec, ids in used for i in ids if allowed.get(i) not in (None, sec)]
                missing = [i for i in allowed if i not in {i for _, ids in used for i in ids}]
                print("   attempt", a["elapsed"], "s | sections", {k: len(v) for k, v in out.items()}, "| wrong-section", wrong, "| missing", missing, "| unknown", [i for _, ids in used for i in ids if i not in allowed])
            else:
                print("   attempt error", a.get("error"))
    if e["violations"]:
        print("VIOL", e["page_id"], e["combo_key"][:40], e["violations"])
        md = e["markdown"]; i = md.find("## 주요 변화"); print("   ", md[i:i + 300].replace("\n", " "))
