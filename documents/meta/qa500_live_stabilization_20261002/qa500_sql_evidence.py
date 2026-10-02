import json,os,psycopg2
from datetime import datetime,timezone

c=psycopg2.connect(os.environ['PG_DSN'].replace('postgresql+psycopg2://','postgresql://'))
cur=c.cursor();cur.execute('SHOW transaction_read_only');assert cur.fetchone()[0]=='on'
out={'checked_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'queries':[]}
def query(name,sql,params=()):
    cur.execute(sql,params);cols=[d[0] for d in cur.description]
    rows=[dict(zip(cols,row)) for row in cur.fetchall()]
    out['queries'].append({'name':name,'sql':sql,'bindings':params,'rows':rows})
    return rows

query('master','SELECT mnrknd_unq_cd,mnrl_nm_ko,mnrl_nm_en,ko_data_src_cd FROM public.ai_mnrl_mst WHERE mnrl_nm_en IN (%s,%s,%s)',('Copper','Nickel','Lithium'))
query('price502','SELECT mnrl_prc_crtr_sn,crtr_ymd,cmerc_prc,lowst_prc,hghst_prc,status FROM public.ko_mnrl_prc WHERE mnrl_prc_crtr_sn=%s AND crtr_ymd<=to_char(CURRENT_DATE,%s) AND status=%s ORDER BY crtr_ymd DESC LIMIT 1',(502,'YYYYMMDD','Y'))
query('price502_basis','SELECT mnrknd_unq_cd,prc_crtr,prc_unit_cd,weig_unit_cd,arch_cd FROM public.ko_mnrl_prc_crtr WHERE mnrl_prc_crtr_sn=%s',(502,))
query('production_population','SELECT t.ntn_eng_cd,t.mass_unit_cd,t.se_cd,t.prdctn_quty,t.prdctn_quty_ton FROM public.ko_rsrc_prdctn_quty t JOIN public.ai_mnrl_mst m USING(mnrknd_unq_cd) WHERE m.mnrl_nm_en=%s AND t.crtr_yr=%s ORDER BY t.ntn_eng_cd',('Copper','2024'))
query('production_country_aggregate','WITH countries AS (SELECT t.ntn_eng_cd,SUM(t.prdctn_quty_ton) value FROM public.ko_rsrc_prdctn_quty t JOIN public.ai_mnrl_mst m USING(mnrknd_unq_cd) WHERE m.mnrl_nm_en=%s AND t.crtr_yr=%s AND t.ntn_eng_cd NOT IN (%s,%s) GROUP BY t.ntn_eng_cd) SELECT COUNT(*) countries,SUM(value) total_ton,AVG(value) mean_ton,SUM(value)-AVG(value) difference_ton FROM countries',('Copper','2024','SU','OT'))
query('production_top5','WITH countries AS (SELECT t.ntn_eng_cd,SUM(t.prdctn_quty_ton) value FROM public.ko_rsrc_prdctn_quty t JOIN public.ai_mnrl_mst m USING(mnrknd_unq_cd) WHERE m.mnrl_nm_en=%s AND t.crtr_yr=%s AND t.ntn_eng_cd NOT IN (%s,%s) GROUP BY t.ntn_eng_cd ORDER BY value DESC LIMIT 5) SELECT SUM(value) top5_total_ton FROM countries',('Copper','2024','SU','OT'))
c.close()
h=psycopg2.connect(os.environ['MSR_DB']);cur=h.cursor()
cur.execute('SELECT session_id,turn_id,result_id,program_json,result_json,result_snapshots_json FROM ai_chatbot.multihop_semantic_turn ORDER BY created_at')
out['isolated_history']=[dict(zip([d[0] for d in cur.description],row)) for row in cur.fetchall()]
h.close()
print(json.dumps(out,ensure_ascii=False,default=str,indent=2))
