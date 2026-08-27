import json, re, sys
from decimal import Decimal, InvalidOperation
d = json.load(open(sys.argv[1]))
PAT = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
def toks(t):
    out = set()
    for tok in PAT.findall(t):
        pct = tok.endswith("%"); raw = tok.rstrip("%").replace(",", "")
        try: n = str(Decimal(raw).normalize())
        except InvalidOperation: n = raw
        out.add(n + ("%" if pct else ""))
    return out
for e in d["entries"]:
    if e["status"] != "ok" or e["llm_refined"]:
        continue
    print("====", e["page_id"], e["combo_key"])
    for a in e.get("llm_attempts", []):
        if "output" not in a: print("  error", a.get("error")); continue
        allowed = {}
        # 근거 사실문은 summary(규칙기반)에서 복원: 각 문장 text = fact, evidence_ids=[id]
        for sec in ("core_diagnosis", "major_changes", "current_position"):
            for s in e["summary"][sec]:
                allowed[s["evidence_ids"][0]] = s["text"]
        for sec, sents in a["output"].items():
            for s in sents:
                ev = " ".join(allowed.get(i, "") for i in s["evidence_ids"])
                extra = toks(s["text"]) - toks(ev)
                if extra:
                    print(f"  [{sec}] extra={sorted(extra)}")
                    print("     text:", s["text"][:220])
                    print("     evid:", ev[:220])
