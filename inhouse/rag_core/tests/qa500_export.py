"""Export reproducible QA500 evidence, never consumed by application code."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

from inhouse.rag_core.tests import qa500_backend as backend
from inhouse.rag_core.tests import qa500_multiturn as multiturn
from inhouse.rag_core.tests import qa500_series_backend as series
from inhouse.rag_core.tests.test_qa500_series import assert_rows
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus


def serialize(value):
    if is_dataclass(value):return asdict(value)
    if hasattr(value,'value'):return value.value
    raise TypeError(type(value).__name__)


def save(path,value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2,default=serialize)+'\n').encode()
    if path.suffix=='.gz':
        path.write_bytes(gzip.compress(raw,mtime=0))
    else:path.write_bytes(raw)


async def export(out,inputs,reports=(),logs=()):
    out.mkdir(parents=True,exist_ok=True)
    runs=[]
    for source in inputs:
        raw=source.read_bytes()
        destination=out/(source.name+'.gz')
        destination.write_bytes(gzip.compress(raw,mtime=0))
        rows=[json.loads(line) for line in raw.splitlines()]
        assert len({r['id'] for r in rows})==len(rows)
        runs.append({'file':destination.name,'sha256':hashlib.sha256(raw).hexdigest(),
            'questions':len(rows),'utterances':sum(len(r['turns']) for r in rows),
            'stage_statuses':dict(Counter(t['status'] for r in rows for t in r['turns']))})
    base=await backend.run()
    save(out/'gold_backend.json.gz',base)
    db=backend.fixture();extra=[]
    for case in backend.CASES:
        pattern=int(case['pattern_id'][4:])
        if pattern not in series.SUPPORTED:continue
        record={'id':case['id'],'pattern_id':case['pattern_id'],'backend_executed':False,
                'physical_tool_executed':False,'contract_gap':series.CONTRACT_GAPS.get(pattern)}
        try:
            program,_,_=series.gold(case,db)
            result,expected=await series.execute(case,db)
            record.update(backend_executed=True,gold_ast=program.to_dict(),expected=expected,
                actual={root:asdict(result.results[root]) for root in program.roots})
            for root,want in expected.items():
                got=result.results[root]
                assert got.status==ResultStatus.SUCCESS,got.failure_reason
                assert got.evidence and got.source and got.provenance
                assert_rows(got.value,want)
            record['status']='COMPONENT_PASS_CONTRACT_GAP' if record['contract_gap'] else 'BACKEND_PASS'
        except Exception as exc:
            record.update(status='EXECUTION_FAIL',error=f'{type(exc).__name__}: {exc}')
        extra.append(record)
    save(out/'gold_series.json.gz',extra)
    turns=await multiturn.run()
    save(out/'gold_multiturn.json.gz',turns)
    fixture_counts={'observations':db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
        'documents':db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],
        'by_domain':dict(db.execute('SELECT domain,COUNT(*) FROM observations GROUP BY domain')),
        'minerals':db.execute('SELECT COUNT(DISTINCT mineral) FROM observations').fetchone()[0],
        'countries':db.execute('SELECT COUNT(DISTINCT country) FROM observations').fetchone()[0],
        'year_range':list(db.execute('SELECT MIN(year),MAX(year) FROM observations').fetchone())}
    db.close()
    summary={'created_at':datetime.now(timezone.utc).isoformat(),'as_of':'2026-10-01',
        'source_count':len(backend.CASES),'gemma_runs':runs,'synthetic_fixture':fixture_counts,
        'gold_backend':dict(Counter(r['status'] for r in base)),
        'gold_series':dict(Counter(r['status'] for r in extra)),
        'gold_multiturn':turns['counts'],
        'scope':'Gold backend and real Gemma shadow are separate measurements. No PostgreSQL, HTTP SSE or production deployment is implied.'}
    ragkit=Path(backend.__file__).resolve().parents[1]/'ragkit'
    summary['implementation_sha256']={name:hashlib.sha256((ragkit/name).read_bytes()).hexdigest()
        for name in ('semantic_v2.py','semantic_ir.py','live_multihop.py','relational_ops.py',
                     'analytical_aggregate.py','analytical_share.py','analytical_series.py')}
    archives=[]
    for path in (*reports,*logs):
        raw=path.read_bytes()
        destination=out/(path.name+'.gz')
        destination.write_bytes(gzip.compress(raw,mtime=0))
        archives.append({'file':destination.name,'sha256':hashlib.sha256(raw).hexdigest()})
    summary['additional_evidence']=archives
    save(out/'execution_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,nargs='+',required=True)
    parser.add_argument('--reports',type=Path,nargs='*',default=[])
    parser.add_argument('--logs',type=Path,nargs='*',default=[])
    args=parser.parse_args()
    asyncio.run(export(args.output,args.inputs,args.reports,args.logs))
