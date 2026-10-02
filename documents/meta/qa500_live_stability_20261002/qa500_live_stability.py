import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from inhouse.rag_core.tests.qa500_linkage_eval import cases, fresh_holdout_cases, repair_holdout_cases, collect
from inhouse.rag_core.tests.qa500_stability_eval import constrained_holdout_cases, boundary_holdout_cases, summarize
from inhouse.rag_core.tests.qa500_stage_eval import holdout_cases

if __name__ == '__main__':
    selected = cases()+fresh_holdout_cases()+repair_holdout_cases()+constrained_holdout_cases()+boundary_holdout_cases()+holdout_cases()
    assert len(selected)==40 and len({c['id'] for c in selected})==40
    rows=[]
    with Path('/tmp/qa500-live-stability.jsonl').open('x') as out, ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        jobs={pool.submit(collect,c): repeat for repeat in (1,2,3) for c in selected}
        for future in as_completed(jobs):
            row=future.result(); row['repeat']=jobs[future];rows.append(row)
            out.write(json.dumps(row,ensure_ascii=False)+'\n');out.flush()
            print(row['case']['id'],row['repeat'],row['status'],flush=True)
    Path('/tmp/qa500-live-stability-summary.json').write_text(json.dumps(summarize(rows,[c['id'] for c in selected],3),ensure_ascii=False,indent=2))
