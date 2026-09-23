import json, dataclasses
from rag_core.retrieval.dense_pg import dense_search_pg
from rag_core.retrieval.pageindex import lookup
from rag_core.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS
out={}
for key,q in [('AC25','리튬 수급 이슈를 설명하는 보고서를 찾아줘'),('AC26','삼원계 배터리와 니켈·코발트 수요의 관계를 설명하는 보고서를 찾아줘')]:
 try:
  rows=dense_search_pg(q,k=6,exclude_src=PRIVATE_ONLY_SOURCE_GROUPS)
  out[key]={'query':q,'dense':[dataclasses.asdict(x) for x in rows], 'pageindex':lookup(q,exclude_source_groups=PRIVATE_ONLY_SOURCE_GROUPS)}
 except Exception as e:out[key]={'query':q,'error':str(e)}
print('AUDIT_JSON='+json.dumps(out,ensure_ascii=False,default=str))
