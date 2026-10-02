"""Evidence accounting checks, not extra QA semantic PASS claims."""
import json
from pathlib import Path


def test_each_registered_question_has_one_independent_stage_record():
    root=Path(__file__).resolve().parents[3]
    source=json.loads((Path(__file__).parent/'qa_build_order2_4_500.json').read_text())
    report=json.loads((root/source['execution_report']).read_text())
    records=report['records']
    assert {r['id'] for r in records}=={q['id'] for q in source['cases']}
    assert len(records)==len({r['id'] for r in records})==500
    statuses=('PASS','FAILED','CAPABILITY_GAP','UNSUPPORTED','BLOCKED','PENDING')
    assert sum(report[s] for s in statuses)==500
    assert report['PENDING']==0
    for s in statuses:
        assert report[s]==sum(r['status']==s for r in records)
    for r in records:
        assert r['gemma_called'] and r['reason']
        assert r['production_http_sse_executed'] is False
        assert isinstance(r['runtime_executed'],bool)
        assert isinstance(r['all_turns_runtime_executed'],bool)
        assert r['trace_artifact'] and r['semantic_audit_artifact']
