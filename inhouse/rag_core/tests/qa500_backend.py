"""Test-only gold plans using real PipeLowerer/PipeRuntime and live operators.

The I/O boundary alone is replaced by a shared deterministic SQLite fixture.
This is not real PostgreSQL/ActionTool E2E. SQL independently supplies oracles.
QA IDs/pattern branches in this TEST module never enter production imports.
"""
import asyncio
from calendar import monthrange
from dataclasses import asdict
import json
import math
from pathlib import Path
import sqlite3

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory, _action_id, _action_slots
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, PipeRuntime, TypedResult, ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


HERE = Path(__file__).parent
CASES = json.loads((HERE / 'qa_build_order2_4_500.json').read_text())["cases"]
SUPPORTED = {1, 2, 3, 4, 5, 8, 9, 10, 12, 13, 14, 15, 16, 19, 21, 22, 23, 24, 25, 26, 27, 30, 31, 32, 33, 37, 38, 39, 40, 41, 42, 44, 49, 52, 53, 60, 61, 62, 68, 77, 79, 81, 95}
MINERALS = ("니켈", "구리", "리튬", "코발트", "텅스텐", "아연", "알루미늄", "망간", "흑연")
COUNTRIES = ("인도네시아", "칠레", "호주", "콩고민주공화국", "중국", "한국")


def fixture():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE observations(domain TEXT, mineral TEXT, year INTEGER, month TEXT, date TEXT, country TEXT, hs TEXT, series TEXT, value REAL, unit TEXT)")
    data = []
    for mi, mineral in enumerate(MINERALS):
        for year in range(2019, 2026):
            for month in range(1, 13):
                for day in (5, 20):
                    value = 100 + mi * 7 + (year - 2019) * 3 + ((month * 5) % 11)
                    data.append(("price", mineral, year, f"{month:02}", f"{year}-{month:02}-{day:02}", None, None, None, value, "USD/t"))
                    data.append(("inventory", mineral, year, f"{month:02}", f"{year}-{month:02}-{day:02}", None, None, None, value * 10, "t"))
                for ci, country in enumerate(COUNTRIES):
                    for hs in ("RAW", "INTERMEDIATE", "PRODUCT"):
                        value = (mi + 1) * 100 + (ci % 3) * 20 + month + year - 2019
                        data.append(("trade", mineral, year, f"{month:02}", f"{year}-{month:02}-01", country, hs, None, value, "USD"))
                for series in ("HI001", "HI002", "HI003", "HI004"):
                    data.append(("indicator", mineral, year, f"{month:02}", f"{year}-{month:02}-01", None, None, series, 100 + month + int(series[-1]), "index"))
            for ci, country in enumerate(COUNTRIES):
                value = (mi + 1) * 10 + (ci % 3) * 4 + year - 2019
                data.append(("production", mineral, year, None, str(year), country, None, None, value, "t"))
                data.append(("reserves", mineral, year, None, str(year), country, None, None, None if ci == 0 else 0 if ci == 1 else value * 10, "t"))
    db.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)", data)
    db.execute('ALTER TABLE observations ADD COLUMN high_price REAL')
    db.execute('ALTER TABLE observations ADD COLUMN low_price REAL')
    db.execute("UPDATE observations SET high_price=value+CAST(month AS INTEGER),low_price=value-CAST(month AS INTEGER) WHERE domain='price'")
    db.execute('CREATE TABLE documents(kind TEXT,year INTEGER,month INTEGER,date TEXT,title TEXT,mineral_list TEXT,body TEXT)')
    docs=[]
    for year in range(2019,2026):
        for month in range(1,13):
            minerals=[MINERALS[month%len(MINERALS)],MINERALS[(month+2)%len(MINERALS)],MINERALS[(month+5)%len(MINERALS)]]
            body='합성 문서. 언급 광종: '+', '.join(minerals)+'. 실제 시장 사실이 아님.'
            docs.append(('monthly',year,month,f'{year}-{month:02}-25',f'합성 희소금속 월간동향 {year}-{month:02}',json.dumps(minerals,ensure_ascii=False),body))
            for day in range(1,21,2):
                docs.append(('news',year,month,f'{year}-{month:02}-{day:02}',f'합성 자원뉴스 {year}-{month:02}-{day:02}',json.dumps(list(MINERALS),ensure_ascii=False),'합성 기사: '+', '.join(MINERALS)))
    db.executemany('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',docs)
    return db


def query(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params)]


def read_fixture(db,node):
    """Only execution arguments select data; never the Gold node id/oracle."""
    slots=_action_slots(node).model_dump(mode='json',exclude_none=True)
    args=node.args
    period=slots.get('period') or {}
    if node.operator==Operator.RETRIEVE_DOCUMENT:
        sql='SELECT date,title,mineral_list,body FROM documents WHERE kind=?'
        scopes={'news':'news','monthly':'monthly','희소금속 월간동향':'monthly','일일 자원뉴스':'news'}
        if args.get('topic') not in scopes:
            raise ValueError('fixture_document_scope_unavailable')
        params=[scopes[args['topic']]]
        if args.get('mineral'):
            sql+=' AND EXISTS(SELECT 1 FROM json_each(documents.mineral_list) WHERE value=?)';params.append(args['mineral'])
    else:
        domain=args.get('domain')
        if domain=='resource':domain=slots['metric']
        sql="SELECT date,CASE WHEN domain IN ('production','reserves') THEN date ELSE substr(date,1,7) END period,month,country,hs,series,value,high_price,low_price,unit FROM observations WHERE domain=? AND mineral=?"
        params=[domain,slots.get('mineral')]
        if slots.get('resource_country'):
            sql+=' AND country=?';params.append(slots['resource_country'])
        if slots.get('indicator_variant'):
            sql+=' AND series=?';params.append({'composite':'HI001','major_metals':'HI002','minor_metals':'HI003'}[slots['indicator_variant']])
    if period.get('kind')=='calendar_year':
        sql+=' AND substr(date,1,4)=?';params.append(str(period['calendar_year']))
    elif period.get('kind')=='range':
        # Annual observations are positioned at year end only for clipping
        # complete-year resource requests; do not fabricate intra-year values.
        expr="CASE WHEN length(date)=4 THEN date||'-12-31' ELSE date END"
        for key,comparator in [('start','>='),('end','<=')]:
            if period.get(key):sql+=f' AND {expr}{comparator}?';params.append(period[key])
    else:
        raise ValueError('fixture requires explicit supported period')
    data=query(db,sql,params)
    if node.operator==Operator.RETRIEVE_DOCUMENT:
        for row in data:row['mineral_list']=json.loads(row['mineral_list'])
    return data,sql,params


def gold(case, db):
    p = int(case['pattern_id'][4:]); b = case['semantic_requirement']['parameter_bindings']
    # Test-only semantic-equivalent data goals. Parsing away contaminated
    # instructions is separately tested with the real model, not assumed here.
    p = {38:1,39:13,40:3}.get(p,p)
    y, m, month, country = b['y'], b['m'], b['month'], b['country']
    nodes = []; sources = {}; roots = []; oracles = {}

    def retrieve(domain, *, year=y, mineral=m, where='', params=(), field='value', extra='', period=None, **slots):
        ident = f"r{len(nodes)}"
        metric = {'trade':'import_value','indicator':'indicator','inventory':'inventory'}.get(domain, domain)
        # SQL filter is synthetic I/O only; temporal args are independently recorded.
        expression=field if field in {'high_price','low_price'} else 'value'
        sql = "SELECT date,month,country,hs,series," + expression + " AS " + field + ",unit FROM observations WHERE domain=? AND mineral=? AND year=?" + where
        data = query(db, sql, (domain, mineral, year, *params))
        args = {'metric':metric, 'domain':'resource' if domain in {'production','reserves'} else domain,
                'mineral':mineral, 'period':period or {'kind':'calendar_year','calendar_year':year},**slots}
        if domain == 'indicator': args['indicator'] = 'composite_index'
        nodes.append(RequirementNode(ident, Operator.RETRIEVE, args=args))
        sources[ident] = (data, sql, [domain,mineral,year,*params])
        return ident

    def op(operator, inputs, **args):
        ident = f"n{len(nodes)}"
        nodes.append(RequirementNode(ident, operator, tuple(InputRef(i) for i in inputs), args=args))
        return ident

    def finish(node, expected):
        roots.append(node); oracles[node] = expected

    def document(kind, *, mention=False, in_month=False):
        ident=f'd{len(nodes)}'
        sql='SELECT date,title,mineral_list,body FROM documents WHERE kind=? AND year=?'
        params=[kind,y]
        if mention:
            sql+=' AND EXISTS(SELECT 1 FROM json_each(documents.mineral_list) WHERE value=?)';params.append(m)
        if in_month:
            sql+=' AND month=?';params.append(month)
        data=query(db,sql,params)
        for row in data:row['mineral_list']=json.loads(row['mineral_list'])
        nodes.append(RequirementNode(ident,Operator.RETRIEVE_DOCUMENT,args={
            'topic':kind,
            'mineral':m if mention else None,'period':{'kind':'range','start':f'{y}-{month:02}-01','end':f'{y}-{month:02}-{monthrange(y,month)[1]}'} if in_month else {'kind':'calendar_year','calendar_year':y}}))
        sources[ident]=(data,sql,params)
        return ident

    def aggregate(r, operation, **args):
        return op(Operator.AGGREGATE,[r],field='value',aggregation=operation,**args)

    if p in {1,2,8,27}:
        domain = 'inventory' if p==8 else 'indicator' if p==27 else 'price'
        field = 'high_price' if p==1 else 'low_price' if p==2 else 'value'
        where = ' AND month=?' if p==2 else " AND series='HI001'" if p==27 else ''
        params = (f'{month:02}',) if p==2 else ()
        period={'kind':'range','start':f'{y}-{month:02}-01','end':f'{y}-{month:02}-{monthrange(y,month)[1]}'} if p==2 else None
        r = retrieve(domain,where=where,params=params,field=field,period=period,**({'indicator_variant':'composite'} if p==27 else {}))
        choose = 'MAX' if p in {1,8} else 'MIN'
        final = op(Operator.PROJECT,[op(Operator.ARG_MAX if choose=='MAX' else Operator.ARG_MIN,[r],field=field,ties='all')], fields=['date',field])
        predicate = "domain=? AND mineral=? AND year=?"+where
        expected = query(db,f"SELECT date,{field} FROM observations WHERE {predicate} AND {field}=(SELECT {choose}({field}) FROM observations WHERE {predicate})",(domain,m,y,*params,domain,m,y,*params))
        finish(final,expected)
    elif p in {3,4}:
        r=retrieve('price',field='value')
        n=aggregate(r,'mean' if p==3 else 'first',group_by=['month'],null_policy='skip',include_count=p==3,order_by='date')
        sql = "SELECT month,AVG(value) value,COUNT(value) observation_count FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month" if p==3 else "SELECT month,value,MIN(date) date FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month"
        finish(n,query(db,sql,(m,y)))
    elif p==5:
        r=retrieve('price',where=' AND date<=?',params=(f'{y}-{month:02}-{monthrange(y,month)[1]}',),period={'kind':'range','end':f'{y}-{month:02}-{monthrange(y,month)[1]}'})
        n=aggregate(r,'last',order_by='date')
        finish(n,query(db,"SELECT value,date FROM observations WHERE domain='price' AND mineral=? AND date<=? ORDER BY date DESC LIMIT 1",(m,f'{y}-{month:02}-{monthrange(y,month)[1]}')))
    elif p==9:
        r=retrieve('price'); n=aggregate(r,'stddev_pop',include_count=True)
        row=query(db,"SELECT AVG(value*value)-AVG(value)*AVG(value) variance,COUNT(value) n FROM observations WHERE domain='price' AND mineral=? AND year=?",(m,y))[0]
        finish(n,[{'value':math.sqrt(max(0,row['variance'])),'observation_count':row['n']}])
    elif p==10:
        period={'kind':'range','start':f'{y}-{month:02}-01','end':f'{y}-{month:02}-{monthrange(y,month)[1]}'}
        a=retrieve('price',where=' AND month=?',params=(f'{month:02}',),field='high_price',period=period)
        bnode=retrieve('price',where=' AND month=?',params=(f'{month:02}',),field='low_price',period=period)
        high=op(Operator.ARG_MAX,[a],field='high_price',ties='all')
        low=op(Operator.ARG_MIN,[bnode],field='low_price',ties='all')
        for node,field,fn in ((high,'high_price','MAX'),(low,'low_price','MIN')):
            finish(op(Operator.PROJECT,[node],fields=['date',field]),query(db,f"SELECT date,{field} FROM observations WHERE domain='price' AND mineral=? AND year=? AND month=? AND {field}=(SELECT {fn}({field}) FROM observations WHERE domain='price' AND mineral=? AND year=? AND month=?)",(m,y,f'{month:02}',m,y,f'{month:02}')))
        # Scalar aggregates prevent a Cartesian comparison of tied dates.
        highvalue=op(Operator.AGGREGATE,[a],field='high_price',aggregation='max',output_field='value')
        lowvalue=op(Operator.AGGREGATE,[bnode],field='low_price',aggregation='min',output_field='value')
        final=op(Operator.PROJECT,[op(Operator.COMPARE,[highvalue,lowvalue],field='value',operation='difference')],fields=['difference'])
        finish(final,query(db,"SELECT MAX(high_price)-MIN(low_price) difference FROM observations WHERE domain='price' AND mineral=? AND year=? AND month=?",(m,y,f'{month:02}')))
    elif p==37:
        a=aggregate(retrieve('trade'),'sum',group_by=['country'])
        final=op(Operator.PROJECT,[op(Operator.TOP_K,[op(Operator.SORT,[a],field='value',order='desc',tie_breaker='country')],k=3)],fields=['country','value'])
        finish(final,query(db,"SELECT country,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country ORDER BY value DESC,country LIMIT 3",(m,y)))
    elif p==15:
        r=retrieve('trade'); a=aggregate(r,'sum',group_by=['hs']); n=op(Operator.SORT,[a],field='value',order='desc')
        finish(n,query(db,"SELECT hs,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY hs ORDER BY value DESC",(m,y)))
    elif p in {12,13,14,16,19,22,53,62}:
        domain='reserves' if p==22 else 'trade'
        dim='hs' if p==16 else 'country'
        monthly=p==19
        groups=['month',dim] if monthly else [dim]
        r=retrieve(domain)
        agg=aggregate(r,'sum',group_by=groups,null_policy='skip' if p==22 else 'reject')
        share=op(Operator.CALCULATE,[agg],field='value',calculation='share',group_by=['month'] if monthly else [])
        # Independent SQL grouped totals and window functions; no production
        # calculation helper is reused by this oracle.
        group_sql=f"SELECT {','.join(groups)},SUM(value) value FROM observations WHERE domain=? AND mineral=? AND year=? GROUP BY {','.join(groups)} HAVING COUNT(value)>0"
        oracle_share=f"SELECT {','.join(groups)},value*100.0/SUM(value) OVER ({'PARTITION BY month' if monthly else ''}) value FROM ({group_sql})"
        params=(domain,m,y)
        if p==12:
            top=op(Operator.TOP_K,[op(Operator.SORT,[share],field='value',order='desc',tie_breaker='country')],k=3)
            final=aggregate(top,'sum')
            finish(final,query(db,'SELECT SUM(value) value FROM ('+oracle_share+' ORDER BY value DESC,country LIMIT 3)',params))
        elif p==13:
            finish(share,query(db,oracle_share,params))
            contrib=op(Operator.CALCULATE,[agg],field='value',calculation='hhi',output='contributions')
            finish(contrib,query(db,f'SELECT {dim},value*value value FROM ({oracle_share})',params))
            finish(op(Operator.CALCULATE,[agg],field='value',calculation='hhi'),query(db,f'SELECT SUM(value*value) value FROM ({oracle_share})',params))
        elif p in {14,19,22}:
            target='중국' if p==14 else country
            final=op(Operator.FILTER,[share],predicate={'field':'country','operator':'equals','value':target})
            if p==22:
                # One country's reserve is NULL in the common fixture. The
                # global denominator is unknowable, not a smaller known sum.
                finish(final,{'failure':'dependency_failed','upstream_reason':'aggregate_input_incomplete'})
            else:
                finish(final,query(db,'SELECT * FROM ('+oracle_share+') WHERE country=?',(*params,target)))
            if p==14:
                finish(op(Operator.FILTER,[agg],predicate={'field':'country','operator':'equals','value':target}),query(db,group_sql+' AND country=?',(*params,target)))
                finish(aggregate(agg,'sum'),query(db,'SELECT SUM(value) value FROM ('+group_sql+')',params))
        elif p==16:
            finish(share,query(db,oracle_share,params))
        else:
            first=op(Operator.CALCULATE,[agg],field='value',calculation='hhi')
            second_domain='production' if p==62 else 'trade';second_year=y if p==62 else y-1
            second_agg=aggregate(retrieve(second_domain,year=second_year),'sum',group_by=['country'])
            second=op(Operator.CALCULATE,[second_agg],field='value',calculation='hhi')
            final=op(Operator.COMPARE,[first,second],field='value',operation='difference')
            final=op(Operator.PROJECT,[final],fields=['left_value','right_value','difference'])
            a=query(db,'SELECT SUM(value*value) value FROM ('+oracle_share+')',params)[0]['value']
            bval=query(db,'SELECT SUM(value*value) value FROM ('+oracle_share+')',(second_domain,m,second_year))[0]['value']
            finish(final,[{'left_value':a,'right_value':bval,'difference':a-bval}])
    elif p==21:
        r=retrieve('production'); n=op(Operator.TOP_K,[op(Operator.SORT,[r],field='value',order='desc')],k=5)
        final=op(Operator.PROJECT,[n],fields=['country','value'])
        finish(final,query(db,"SELECT country,value FROM observations WHERE domain='production' AND mineral=? AND year=? ORDER BY value DESC,rowid LIMIT 5",(m,y)))
    elif p==23:
        r=retrieve('production',where=' AND country=?',params=(country,))
        # Explicit cross-year retrieval scope in the golden node, not a default-year overwrite.
        sql="SELECT date AS period,value,unit FROM observations WHERE domain='production' AND mineral=? AND country=? AND year BETWEEN ? AND ?"
        sources[r]=(query(db,sql,(m,country,b['start_year'],y)),sql,[m,country,b['start_year'],y])
        nodes[-1]=RequirementNode(r,Operator.RETRIEVE,args={**nodes[-1].args,'period':{'kind':'range','start':f"{b['start_year']}-01-01",'end':f'{y}-12-31'},'resource_country':country})
        for method,direction in [('first','ASC'),('last','DESC')]:
            n=aggregate(r,method,order_by='period')
            finish(n,query(db,sql.replace('date AS period,value,unit','value,date AS period')+f' ORDER BY date {direction} LIMIT 1',(m,country,b['start_year'],y)))
    elif p in {24,25}:
        domain='production' if p==24 else 'reserves';r=retrieve(domain)
        n=aggregate(r,'sum' if p==24 else 'mean',null_policy='skip' if p==25 else 'reject',include_count=True)
        finish(n,query(db,f"SELECT {'SUM' if p==24 else 'AVG'}(value) value,COUNT(value) observation_count FROM observations WHERE domain=? AND mineral=? AND year=?",(domain,m,y)))
    elif p==26:
        r=retrieve('production');sql="SELECT date AS period,value,unit FROM observations WHERE domain='production' AND mineral=? AND country=? AND year BETWEEN ? AND ?"
        sources[r]=(query(db,sql,(m,country,b['start_year'],y)),sql,[m,country,b['start_year'],y])
        nodes[-1]=RequirementNode(r,Operator.RETRIEVE,args={**nodes[-1].args,'period':{'kind':'range','start':f"{b['start_year']}-01-01",'end':f'{y}-12-31'},'resource_country':country})
        f=op(Operator.FILTER,[r],predicate={'field':'value','operator':'greater_than','value':0})
        finish(aggregate(f,'count'),query(db,sql.replace('date AS period,value,unit','COUNT(value) value')+' AND value>0',(m,country,b['start_year'],y)))
        finish(op(Operator.PROJECT,[f],fields=['period']),query(db,sql.replace('date AS period,value,unit','date AS period')+' AND value>0',(m,country,b['start_year'],y)))
    elif p==30:
        r=retrieve('indicator');n=aggregate(r,'last',group_by=['series'],order_by='date')
        finish(n,query(db,"SELECT series,value,MAX(date) date FROM observations WHERE domain='indicator' AND mineral=? AND year=? GROUP BY series",(m,y)))
    elif p in {31,32,33,68,95}:
        doc=document('news' if p==33 else 'monthly',mention=p in {31,33,68,95},in_month=p==33)
        selected=op(Operator.TOP_K,[op(Operator.SORT,[doc],field='date',order='desc')],k=2 if p==31 else 9 if p==33 else 1)
        data,sql,params=sources[doc]
        chosen=query(db,sql+' ORDER BY date DESC LIMIT '+str(2 if p==31 else 9 if p==33 else 1),params)
        if p in {31,33}:
            finish(op(Operator.PROJECT,[selected],fields=['title','date']),[{'title':r['title'],'date':r['date']} for r in chosen])
        else:
            extracted=op(Operator.PROJECT,[selected],fields=['mineral_list'])
            minerals=json.loads(chosen[0]['mineral_list'])
            if p==32:
                # Membership in the selected latest document is observable
                # directly; no earlier document replacement is permitted.
                finish(extracted,minerals)
            else:
                # Current filter does not support scalar MineralSet predicates;
                # document fixture projection excludes the anchor only through
                # an explicit typed filter. Never pre-filter fixture source.
                filtered=op(Operator.FILTER,[extracted],predicate={'field':'mineral','operator':'not_equals','value':m})
                for output in (['latest_value','time_series'] if p==95 else ['latest_value']):
                    period={'kind':'range','start':f'{y}-10-01' if output=='time_series' else f'{y}-01-01','end':f'{y}-12-31'}
                    n=op(Operator.FOR_EACH,[filtered],domain='price',metric='price',output=output,period=period)
                    expected=[]
                    for mineral in minerals:
                        if mineral==m:continue
                        prices=query(db,"SELECT date,value FROM observations WHERE domain='price' AND mineral=? AND date BETWEEN ? AND ? ORDER BY date DESC"+(' LIMIT 1' if output=='latest_value' else ''),(mineral,period['start'],period['end']))
                        expected.append({'mineral':mineral,'prices':prices})
                    finish(n,{'foreach':expected,'output':output,'document':chosen[0]['title']})
    elif p in {42,52}:
        domain='price' if p==42 else 'trade'
        dimension='month' if p==42 else 'country'
        a=aggregate(retrieve(domain),'mean' if p==42 else 'sum',group_by=[dimension])
        second_year=y-1 if p==42 else b['start_year']
        second_domain=domain
        if p==106:
            second_year=y;second_domain='production'
        bnode=aggregate(retrieve(second_domain,year=second_year),'mean' if p==42 else 'sum',group_by=[dimension])
        if p!=42:
            a=op(Operator.CALCULATE,[a],calculation='share',field='value')
            bnode=op(Operator.CALCULATE,[bnode],calculation='share',field='value')
        operation='percent_change' if p==42 else 'difference'
        n=op(Operator.COMPARE,[a,bnode],field='value',join_key=dimension,operation=operation)
        if p in {52,106}:n=op(Operator.SORT,[n],field='difference',order='desc')
        if p==106:n=op(Operator.ARG_MAX,[n],field='difference',ties='all')
        final=op(Operator.PROJECT,[n],fields=[dimension,'left_value','right_value',operation])
        def sqlvalues(d,yr):
            group=f"SELECT {dimension},{'AVG' if p==42 else 'SUM'}(value) value FROM observations WHERE domain=? AND mineral=? AND year=? GROUP BY {dimension}"
            if p!=42:group=f'SELECT {dimension},value*100.0/SUM(value) OVER () value FROM ({group})'
            return group,[d,m,yr]
        left,lp=sqlvalues(domain,y);right,rp=sqlvalues(second_domain,second_year)
        calculation='(l.value-r.value)/ABS(r.value)*100' if p==42 else 'l.value-r.value'
        expected=query(db,f'SELECT l.{dimension},l.value left_value,r.value right_value,{calculation} {operation} FROM ({left}) l JOIN ({right}) r USING({dimension})',lp+rp)
        if p==106:
            peak=max(e['difference'] for e in expected);expected=[e for e in expected if e['difference']==peak]
            price=aggregate(retrieve('price'),'mean')
            finish(price,query(db,"SELECT AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year=?",(m,y)))
        finish(final,expected)
    elif p==44:
        r=retrieve('price');a=aggregate(r,'max');bnode=aggregate(r,'last',order_by='date')
        final=op(Operator.PROJECT,[op(Operator.COMPARE,[bnode,a],field='value',operation='percent_change')],fields=['left_value','right_value','percent_change'])
        vals=query(db,"SELECT MAX(value) high,(SELECT value FROM observations WHERE domain='price' AND mineral=? AND year=? ORDER BY date DESC LIMIT 1) latest FROM observations WHERE domain='price' AND mineral=? AND year=?",(m,y,m,y))[0]
        finish(final,[{'left_value':vals['latest'],'right_value':vals['high'],'percent_change':(vals['latest']-vals['high'])/vals['high']*100}])
        finish(op(Operator.PROJECT,[op(Operator.ARG_MAX,[r],field='value',ties='all')],fields=['date','value']),query(db,"SELECT date,value FROM observations WHERE domain='price' AND mineral=? AND year=? AND value=(SELECT MAX(value) FROM observations WHERE domain='price' AND mineral=? AND year=?)",(m,y,m,y)))
        finish(bnode,query(db,"SELECT value,date FROM observations WHERE domain='price' AND mineral=? AND year=? ORDER BY date DESC LIMIT 1",(m,y)))
    elif p in {41,49,79}:
        if p==41:
            a=aggregate(retrieve('price',where=" AND month<='06'",period={'kind':'range','start':f'{y}-01-01','end':f'{y}-06-30'}),'mean');bnode=aggregate(retrieve('price',where=" AND month>='07'",period={'kind':'range','start':f'{y}-07-01','end':f'{y}-12-31'}),'mean')
            vals=query(db,"SELECT AVG(CASE WHEN month<='06' THEN value END) a,AVG(CASE WHEN month>'06' THEN value END) b FROM observations WHERE domain='price' AND mineral=? AND year=?",(m,y))[0]
        elif p==79:
            a=aggregate(retrieve('price',year=y-1),'mean');bnode=aggregate(retrieve('price'),'mean')
            vals=query(db,"SELECT AVG(CASE WHEN year=? THEN value END) a,AVG(CASE WHEN year=? THEN value END) b FROM observations WHERE domain='price' AND mineral=?",(y-1,y,m))[0]
        else:
            a=aggregate(retrieve('trade',year=y-1,where=' AND CAST(month AS INTEGER)<=?',params=(month,),period={'kind':'range','start':f'{y-1}-01-01','end':f'{y-1}-{month:02}-{monthrange(y-1,month)[1]}'}),'sum');bnode=aggregate(retrieve('trade',where=' AND CAST(month AS INTEGER)<=?',params=(month,),period={'kind':'range','start':f'{y}-01-01','end':f'{y}-{month:02}-{monthrange(y,month)[1]}'}),'sum')
            vals=query(db,"SELECT SUM(CASE WHEN year=? THEN value END) a,SUM(CASE WHEN year=? THEN value END) b FROM observations WHERE domain='trade' AND mineral=? AND CAST(month AS INTEGER)<=?",(y-1,y,m,month))[0]
        for operation in (['difference'] if p==79 else ['difference','percent_change']):
            n=op(Operator.COMPARE,[bnode,a],field='value',operation=operation)
            final=op(Operator.PROJECT,[n],fields=['left_value','right_value',operation])
            expected=vals['b']-vals['a'] if operation=='difference' else (vals['b']-vals['a'])/abs(vals['a'])*100
            finish(final,[{'left_value':vals['b'],'right_value':vals['a'],operation:expected}])
    elif p in {60,61}:
        a=retrieve('production');bnode=aggregate(retrieve('trade'),'sum',group_by=['country'])
        if p==60:
            a=op(Operator.TOP_K,[op(Operator.SORT,[a],field='value',order='desc')],k=5)
            bnode=op(Operator.TOP_K,[op(Operator.SORT,[bnode],field='value',order='desc')],k=5)
        n=op(Operator.JOIN,[a,bnode],join_key='country',how='inner' if p==60 else 'full')
        final=op(Operator.PROJECT,[n],fields=['country','match_status'])
        prod=query(db,"SELECT country FROM observations WHERE domain='production' AND mineral=? AND year=? ORDER BY value DESC,rowid"+(' LIMIT 5' if p==60 else ''),(m,y))
        tr=query(db,"SELECT country,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country ORDER BY value DESC,country"+(' LIMIT 5' if p==60 else ''),(m,y))
        countries={r['country'] for r in prod}&{r['country'] for r in tr}
        finish(final,[{'country':c,'match_status':'matched'} for c in sorted(countries)])
    elif p==77:
        a=aggregate(retrieve('price'),'mean',group_by=['month']);bnode=aggregate(retrieve('trade'),'sum',group_by=['month'])
        n=op(Operator.JOIN,[a,bnode],join_key='month',how='full');final=op(Operator.PROJECT,[n],fields=['month','left.value','right.value'])
        finish(final,query(db,"SELECT p.month,p.value AS 'left.value',t.value AS 'right.value' FROM (SELECT month,AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month) p JOIN (SELECT month,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY month) t USING(month)",(m,y,m,y)))
    elif p==81:
        a=aggregate(retrieve('production'),'sum');bnode=aggregate(retrieve('trade'),'sum')
        n=op(Operator.COMPARE,[a,bnode],field='value',operation='ratio'); roots.append(n);oracles[n]={'failure':'unit_mismatch'}
    else:
        raise ValueError('gold plan not registered')
    return SemanticProgram(tuple(nodes),tuple(roots)),sources,oracles


async def validate_case(case, db, *, result_mutator=None):
    record={'id':case['id'],'pattern_id':case['pattern_id'],'backend_executed':False,'physical_tool_executed':False}
    try:
        program,sources,expected=gold(case,db)
        record['gold_ast']=program.to_dict();record['expected']=expected
        calls=[]
        class FixtureFactory(LiveOperatorFactory):
            async def _call_action(self,node,action_id,*,mineral=None,minerals=None):
                assert action_id=='price.series'
                period=node.args['period'];output=node.args['output']
                sql="SELECT date,value FROM observations WHERE domain='price' AND mineral=? AND date BETWEEN ? AND ? ORDER BY date DESC"+(' LIMIT 1' if output=='latest_value' else '')
                data=query(db,sql,(mineral,period['start'],period['end']))
                calls.append({'node':node.node_id,'action':action_id,'resolved_mineral':mineral,'output':output,'period':period})
                return TypedResult.success(ValueType.TIME_SERIES,data,entity=(mineral,),unit='USD/t',period=period,
                    source=('synthetic-sqlite',),evidence=(Evidence('structured','synthetic-sqlite',mineral,json.dumps(data)),),provenance=('qa500:synthetic',))
        factory=FixtureFactory(message='',session_id='qa500-fixture',profile='public',llm=None,history=[])
        def build(node,dependencies,bindings):
            if node.node_id in sources:
                data,sql,params=read_fixture(db,node)
                calls.append({'node':node.node_id,'action':_action_id(node),'slots':_action_slots(node).model_dump(mode='json'), 'fixture_sql':sql,'params':params})
                async def retrieve(ctx,inputs):
                    return TypedResult.success(ValueType.DOCUMENT_EVIDENCE if node.operator==Operator.RETRIEVE_DOCUMENT else ValueType.FACT_SET,data,unit=data[0].get('unit') if data else None,
                        source=('synthetic-sqlite',),evidence=(Evidence('structured','synthetic-sqlite','qa500',json.dumps(data,ensure_ascii=False)),),provenance=('qa500:synthetic',))
                return FunctionStep(node.node_id,node.operator.value,retrieve,dependencies=dependencies,bindings=bindings)
            return factory.build(node=node,dependencies=dependencies,bindings=bindings)
        pipe=PipeLowerer(build).lower(program,pipe_id='qa500-'+case['id'])
        record['lowering']=calls
        result=await PipeRuntime().execute(pipe);record['backend_executed']=True
        if result_mutator:
            for root in program.roots:result.results[root]=result_mutator(result.results[root])
        record['actual']={root:{'status':result.results[root].status.value,'value':result.results[root].value,'reason':result.results[root].failure_reason,'unit':result.results[root].unit,'evidence_count':len(result.results[root].evidence),'source':result.results[root].source,'provenance':result.results[root].provenance} for root in program.roots}
        errors=[]
        node_map={n.node_id:n for n in program.nodes}
        def expected_unit(node_id):
            node=node_map[node_id];args=node.args
            if node.operator==Operator.RETRIEVE:
                return {'price':'USD/t','trade':'USD','resource':'t','inventory':'t','indicator':'index'}[args['domain']]
            if node.operator in {Operator.RETRIEVE_DOCUMENT,Operator.FOR_EACH}:return None
            units=[expected_unit(ref.node_id) for ref in node.inputs]
            if node.operator==Operator.AGGREGATE and args['aggregation']=='count':return None
            if node.operator==Operator.CALCULATE:return 'HHI(0-10000)' if args['calculation']=='hhi' else '%'
            if node.operator==Operator.COMPARE and args.get('operation')=='percent_change':return '%'
            if node.operator==Operator.JOIN:return units[0] if len(set(units))==1 else None
            return units[0] if units else None
        def check_order(root,rows):
            node=node_map[root]
            while node.operator in {Operator.PROJECT,Operator.TOP_K,Operator.FILTER} and node.inputs:
                node=node_map[node.inputs[0].node_id]
            if node.operator not in {Operator.SORT,Operator.RANK} or not rows:return
            field=node.args['field'];values=[r.get(field) for r in rows if isinstance(r,dict)]
            if any(v is None for v in values):
                errors.append(f'{root}: sort field lost before output');return
            if values!=sorted(values,reverse=node.args.get('order','desc')=='desc'):
                errors.append(f'{root}: requested ordering violated')
        def stable(rows):return sorted(rows,key=lambda r:json.dumps(r,sort_keys=True,ensure_ascii=False))
        for root,want in expected.items():
            got=result.results[root]
            if got.status==ResultStatus.SUCCESS:
                if got.unit!=expected_unit(root):errors.append(f'{root}: unit contract mismatch')
                if not got.evidence or not got.source or not got.provenance:errors.append(f'{root}: evidence/source/provenance lost')
                check_order(root,got.value)
            if isinstance(want,dict) and 'foreach' in want:
                if got.status!=ResultStatus.SUCCESS:errors.append(f'{root}: {got.failure_reason}');continue
                actual=[{'mineral':r['mineral'],'prices':r['value']} for r in got.value]
                if stable(actual)!=stable(want['foreach']):errors.append(f'{root}: mineral/price binding mismatch')
                if want['document'] not in str([ev.text for ev in got.evidence]):errors.append(f'{root}: document provenance lost')
                continue
            if isinstance(want,dict) and 'failure' in want:
                if want.get('upstream_reason'):
                    if got.status==ResultStatus.SUCCESS or not any(r.failure_reason==want['upstream_reason'] for r in result.results.values()):
                        errors.append(f'{root}: expected explicit upstream failure {want}')
                elif got.failure_reason!=want['failure']:errors.append(f'{root}: expected {want}, got {got.failure_reason}')
                continue
            if got.status!=ResultStatus.SUCCESS:errors.append(f'{root}: {got.failure_reason}');continue
            actual=stable(got.value);target=stable(want)
            if len(actual)!=len(target):errors.append(f'{root}: row count {len(actual)} != {len(target)}');continue
            for a,e in zip(actual,target):
                if not isinstance(e,dict):
                    if a!=e:errors.append(f'{root}: entity mismatch')
                    continue
                if a.keys()!=e.keys():errors.append(f'{root}: fields mismatch');continue
                for key in e:
                    if isinstance(e[key],(int,float)):
                        if not isinstance(a[key],(int,float)) or not math.isclose(a[key],e[key],rel_tol=1e-9,abs_tol=1e-8):errors.append(f'{root}: {key} numeric mismatch')
                    elif a[key]!=e[key]:errors.append(f'{root}: {key} mismatch')
        record.update(status='BACKEND_PASS' if not errors else 'EXECUTION_FAIL',errors=errors)
    except Exception as exc:
        record.update(status='AST_OR_LOWERING_FAIL',errors=[f'{type(exc).__name__}: {exc}'])
    return record


async def run():
    db=fixture();records=[]
    for case in CASES:
        if int(case['pattern_id'][4:]) in SUPPORTED:
            records.append(await validate_case(case,db))
    return records


if __name__=='__main__':
    import sys
    output=asyncio.run(run())
    Path(sys.argv[1]).write_text(json.dumps(output,ensure_ascii=False,indent=2,default=lambda obj: asdict(obj))+'\n')
    from collections import Counter
    print(Counter(r['status'] for r in output))
    for r in output:
        if r['status']!='BACKEND_PASS':print(r['id'],r['errors'])
