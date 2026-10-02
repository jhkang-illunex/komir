import asyncio,json,sys
from pathlib import Path
from common.llm_client import KomirJsonLLM
from rag_core.ragkit import live_multihop as live
from rag_core.ragkit.history_context import ConversationContext,Turn,UserUtterance,_execution_from_dict
from rag_core.ragkit.semantic_ir import SemanticProgram

async def main():
    llm=KomirJsonLLM({'base_url':'http://127.0.0.1:52302/v1','model':'gemma-4-26b-a4b','temperature':0,'timeout':90,'retries':1})
    original=llm.invoke;records=[]
    def invoke(**kwargs):
        result=original(**kwargs);records.append(result.record);return result
    llm.invoke=invoke
    raw=json.load(open('/tmp/qa-live-repair-sql-final.json'))
    sid=json.load(open('/tmp/qa-live-repair-sse/document-r4.json'))['request']['session_id']
    saved=[r for r in raw['isolated_history'] if r['session_id']==sid][-1]
    turn=Turn(saved['turn_id'],sid,UserUtterance(''),semantic_program=SemanticProgram.from_dict(saved['program_json']),result=_execution_from_dict(saved['result_json']))
    fresh=ConversationContext('empty');ctx=ConversationContext(sid,(turn,))
    cases=[('difference','2024년 구리 생산량의 합계와 평균을 계산하고 합계에서 평균을 빼줘',fresh),
      ('refresh','그 광종들의 가격을 지금 다시 조회해줘',ctx),
      ('reference','위 결과에서 최신 가격 조회에 성공한 광종만 알려줘',ctx),
      ('heldout-metric','2024년 니켈 생산량을 국가별로 더한 뒤 국가 평균을 빼주세요.',fresh),
      ('heldout-operation','2024년 구리 생산량 최댓값을 최솟값으로 나눈 비율은?',fresh)]
    out=[]
    for ident,q,context in cases:
        records.clear();live.clear_semantic_cache()
        try: result={'program':(await live._parse_ast(llm,q,context)).to_dict()}
        except Exception as e:result={'error':str(e)}
        row={'id':ident,'query':q,**result,'raw':list(records)};out.append(row)
        print(ident,result,flush=True)
    Path('/tmp/stability33-parser-'+sys.argv[1]+'.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
asyncio.run(main())
