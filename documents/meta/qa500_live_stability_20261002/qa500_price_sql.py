import os,json,psycopg2
c=psycopg2.connect(os.environ['PG_DSN'].replace('postgresql+psycopg2://','postgresql://'))
q=c.cursor();q.execute('SHOW transaction_read_only');assert q.fetchone()[0]=='on'
sql="""SELECT substr(crtr_ymd,1,4)||'-'||substr(crtr_ymd,5,2) AS month_key,
AVG(cmerc_prc) average_price,COUNT(*) observation_count
FROM public.ko_mnrl_prc WHERE mnrl_prc_crtr_sn=%s AND status='Y'
AND last_del_dt IS NULL AND cmerc_prc IS NOT NULL AND crtr_ymd BETWEEN %s AND %s
GROUP BY substr(crtr_ymd,1,4),substr(crtr_ymd,5,2) ORDER BY month_key"""
params=(502,'20251001','20260930');q.execute(sql,params)
rows=[dict(zip([d[0] for d in q.description],row)) for row in q.fetchall()]
print(json.dumps({'sql':sql,'bindings':params,'rows':rows},default=str,ensure_ascii=False,indent=2))
c.close()
