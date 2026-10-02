import hashlib,json,subprocess,sys
from pathlib import Path
def run(args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode:raise RuntimeError('validation docker operation failed: '+args[1])
    return p.stdout.strip()
source=json.loads(run(['docker','inspect','komir-rag-chat-qa-sse32']))[0]
assert source['Config']['Image']=='komir-rag-chat:qa-live-repair32-r4'
assert source['HostConfig']['PortBindings']['8002/tcp']==[{'HostIp':'127.0.0.1','HostPort':'18012'}]
env=dict(x.split('=',1) for x in source['Config']['Env'])
assert 'komir-qa-history31' in env['MSR_DB'] and 'komir-qa-history31' in env['MULTIHOP_HISTORY_DSN']
assert 'default_transaction_read_only' in env['PG_DSN']
image=sys.argv[1];assert image.startswith('komir-rag-chat:qa-live-stability33-')
run(['docker','stop','komir-rag-chat-qa-sse32'])
args=['docker','run','-d','--name','komir-rag-chat-qa-sse33','--network','komir-qa-sse31','--add-host','host.docker.internal:host-gateway','-p','127.0.0.1:18012:8002']
for k,v in env.items():args+=['-e',k+'='+v]
for m in source['Mounts']:args+=['-v',m['Source']+':'+m['Destination']+':ro']
args+=[image];ident=run(args)
meta={'container_id':ident,'port':18012,'image_tag':image,'image_id':run(['docker','image','inspect',image,'--format','{{.Id}}']),
'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['inhouse/rag_core/ragkit/live_multihop.py','inhouse/rag_core/ragkit/chatbot.py','inhouse/rag_core/ragkit/chatbot_graph.py','inhouse/rag_core/ragkit/chatbot_events.py','inhouse/rag_core/ragkit/_mcp_tools_common.py']}}
Path('/tmp/stability33-environment.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta,indent=2))
