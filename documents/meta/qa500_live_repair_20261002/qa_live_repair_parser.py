import asyncio,json
from pathlib import Path
from common.llm_client import KomirJsonLLM
from rag_core.ragkit import live_multihop as live
from rag_core.ragkit.history_context import ConversationContext,Turn,UserUtterance
from rag_core.ragkit.pipe_runtime import TypedResult,ExecutionResult,ResultStatus
from rag_core.ragkit.semantic_ir import SemanticProgram,RequirementNode,Operator,ValueType

async def main():
    llm=KomirJsonLLM({'base_url':'http://127.0.0.1:52302/v1','model':'gemma-4-26b-a4b','temperature':0,'timeout':90,'retries':1})
    original=llm.invoke;records=[]
    def invoke(**kwargs):
        result=original(**kwargs);records.append(result.record);return result
    llm.invoke=invoke
    source=TypedResult.success(ValueType.TIME_SERIES,[{'기준일':'2026-09-30','통상가격':'10'}],entity=('니켈',))
    prior=Turn('prior','test',UserUtterance('이전조회'),semantic_program=SemanticProgram((RequirementNode('root',Operator.RETRIEVE,args={'metric':'price'}),),('root',)),result=ExecutionResult('p',ResultStatus.SUCCESS,{'root':source},()))
    cases=[('sum','2024년 구리 생산량의 전체 국가 합계는 얼마야?',ConversationContext('empty')),
           ('composition','2024년 구리 생산량 평균과 합계, 둘의 차이를 알려줘',ConversationContext('empty')),
           ('reference','방금 조회된 광종은 무엇인가요?',ConversationContext('test',(prior,))),
           ('refresh','그 광종들의 가격을 지금 다시 조회해줘',ConversationContext('test',(prior,)))]
    out=[]
    for ident,q,ctx in cases:
        records.clear();live.clear_semantic_cache()
        try: result={'program':(await live._parse_ast(llm,q,ctx)).to_dict()}
        except Exception as e:result={'error':str(e)}
        row={'id':ident,'query':q,**result,'raw':list(records)};out.append(row)
        print(ident,result,flush=True)
    Path('/tmp/qa-live-repair-parser.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
asyncio.run(main())
