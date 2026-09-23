from pathlib import Path
import json, sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[4]/'inhouse'))
from common.db import pg_connect
c=pg_connect();c.set_session(readonly=True);out={}
def sql(q,p=()):
 with c.cursor() as k:
  k.execute(q,p);return [dict(zip([x[0] for x in k.description],r)) for r in k.fetchall()]
def events(n):return json.loads((HERE/'live_raw'/f'{n}_turn1.events.json').read_text())
def tables(n):return [x for x in events(n) if 'rows'in x]
try:
 for n in ['AC01','AC02','AC03','AC04','AC05']:
  t=tables(n)[0]; errs=[]
  for row in t['rows']:
   found=sql('SELECT lowst_prc,hghst_prc,cmerc_prc FROM public.ko_mnrl_prc WHERE mnrl_prc_crtr_sn=%s AND crtr_ymd=%s',(int(float(row[0])),row[1]))
   if len(found)!=1 or any(abs(float(found[0][key])-float(row[i+2]))>.001 for i,key in enumerate(['lowst_prc','hghst_prc','cmerc_prc'])):errs.append(row)
  out[n]={'displayed_rows_checked':len(t['rows']),'mismatch_rows':errs,'serial':t['rows'][0][0],'numeric_match':not errs,'full_contract_pass':False,'limitation':'표 원값만 대조. 더미 선택·기간·표시 정책 별도 판정'}
 r=sql("SELECT crtr_ymd,cmerc_prc FROM public.ko_mnrl_prc WHERE mnrl_prc_crtr_sn=502 AND crtr_ymd BETWEEN '20250101' AND '20251231' ORDER BY crtr_ymd")
 out['AC07']={'first':r[0],'last':r[-1],'independent_pct':round((float(r[-1]['cmerc_prc'])/float(r[0]['cmerc_prc'])-1)*100,2),'actual_stat':tables('AC07')[1]['rows'][0]}
 pre=json.loads((HERE/'rdb_preconditions.json').read_text())['checks']
 rank=pre['lithium_rank_default']['rows']; total=sum(float(x['imports']) for x in rank)
 out['AC08']={'total':total,'expected_top5':[dict(x,share_pct=round(float(x['imports'])/total*100,2)) for x in rank[:5]],'actual':tables('AC08')[0]['rows']}
 out['AC10']={'independent':pre['hs2603000000']['rows'],'actual':tables('AC10')[0]['rows']}
 for n,code,kind,field in [('AC12','MNRL0001','burudg','burudg_quty_ton'),('AC13','MNRL0006','prdctn','prdctn_quty_ton'),('AC13_reserve','MNRL0006','burudg','burudg_quty_ton')]:
  r=sql(f'SELECT ntn_eng_cd,sum({field}) amount FROM public.ko_rsrc_{kind}_quty WHERE mnrknd_unq_cd=%s AND crtr_yr=\'2026\' GROUP BY 1 ORDER BY 2 DESC',(code,)); total=sum(float(x['amount']) for x in r)
  out[n]={'total':total,'expected':[dict(x,share_pct=round(float(x['amount'])/total*100,2)) for x in r[:5]],'actual':tables(n.split('_')[0])[1 if '_'in n else 0]['rows']}
 r=pre['lithium_yearly_trade']['rows'];out['AC16']={'independent':r,'expected_tsi':[(float(x['exports'])-float(x['imports']))/(float(x['exports'])+float(x['imports'])) for x in r],'actual':tables('AC16')[0]['rows']}
 out['AC17']={'independent_years':r,'missing_previous_year':not any(x['year']=='2024' for x in r)}
 r=pre['lithium_china_2025']['rows'];total=sum(float(x['imports']) for x in r);out['AC18']={'denominator':total,'china':[dict(x,expected_dependency=100*float(x['imports'])/total) for x in r if x['trgt_ntn']=='중국']}
 out['dummy_master']=sql("SELECT mnrknd_unq_cd,mnrl_nm_ko,ko_data_src_cd FROM public.ai_mnrl_mst WHERE mnrknd_unq_cd IN ('MNRL0001','MNRL0002','MNRL0003','MNRL0006','MNRL0008')")
finally:
 c.close();(HERE/'independent_numeric_verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
print('numeric verification saved')
