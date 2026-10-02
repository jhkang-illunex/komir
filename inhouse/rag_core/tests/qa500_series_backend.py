"""Test-only series GoldPlan assembler; reuses qa500_backend.fixture unchanged.

gold(case, db) has the same (program, sources, SQL oracles) interface as the
shared backend. Only synthetic retrieval is replaced in execute(); ALL derive
nodes run through the real LiveOperatorFactory and PipeRuntime. A main-agent
Calculate delegate is required; this module does not monkeypatch it.

43 uses explicitly recorded inclusive calendar-month windows (Oct/Jul/Jan to
Dec 31). Different trailing/as-of interpretations have no default contract.
80 exposes the computed change; a claim truth tolerance/verdict has no contract.
63/64 retrieve prior December explicitly to calculate January's MoM return.
The remaining scope limits are not full-question PASS.
"""
import json

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, PipeRuntime, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence
from inhouse.rag_core.tests.qa500_backend import CASES, fixture, query, read_fixture


SUPPORTED = {43, 45, 46, 47, 48, 63, 64, 80}
CONTRACT_GAPS = {
    43: "Calendar-month inside windows are explicit; trailing/as-of interpretation unspecified.",
    80: "Computed endpoint change only; exact-claim tolerance/verdict unspecified.",
}


def gold(case, db):
    p = int(case['pattern_id'][4:])
    if p not in SUPPORTED:
        raise ValueError('series gold plan not registered')
    bindings = case['semantic_requirement']['parameter_bindings']
    year, mineral = bindings['y'], bindings['m']
    nodes, sources, roots, oracles = [], {}, [], {}

    def op(operator, inputs=(), **args):
        ident = f's{len(nodes)}'
        nodes.append(RequirementNode(ident, operator, tuple(InputRef(i) for i in inputs), args=args))
        return ident

    def retrieve(domain, mineral=mineral, prior_month=False):
        sql = "SELECT date,substr(date,1,7) period,value,unit FROM observations WHERE domain=? AND mineral=?"
        sql += ' AND date BETWEEN ? AND ?' if prior_month else ' AND year=?'
        if domain == 'indicator':
            sql += " AND series='HI001'"
        params = (domain, mineral, f'{year-1}-12-01', f'{year}-12-31') if prior_month else (domain, mineral, year)
        args = dict(domain=domain, metric=domain, mineral=mineral,
                    period={'kind':'calendar_year', 'calendar_year':year})
        if domain == 'indicator':
            args['indicator'] = 'composite_index'
            args['indicator_variant'] = 'composite'
        if prior_month:
            args['period'] = {'kind':'range','start':f'{year-1}-12-01','end':f'{year}-12-31'}
        ident = op(Operator.RETRIEVE, **args)
        sources[ident] = (query(db, sql, params), sql, params)
        return ident

    def calc(source, calculation, time_field='date', **args):
        return op(Operator.CALCULATE, [source], calculation=calculation,
                  field='value', time_field=time_field, **args)

    def monthly(source):
        return op(Operator.AGGREGATE, [source], field='value', aggregation='mean', group_by=['period'])

    def finish(node, sql, params):
        roots.append(node)
        oracles[node] = query(db, sql, params)

    predicate = "domain='price' AND mineral=? AND year=?"
    if p in {43, 80}:
        source = retrieve('price')
        for count in ([3, 6, 12] if p == 43 else [12]):
            start, end = f'{year}-{13-count:02}-01', f'{year}-12-31'
            node = calc(source, 'endpoint_change', start=start, end=end, endpoint_policy='inside')
            finish(node, "WITH p AS (SELECT date,value,unit FROM observations WHERE " + predicate +
                   " AND date BETWEEN ? AND ?), a AS (SELECT * FROM p ORDER BY date LIMIT 1), "
                   "b AS (SELECT * FROM p ORDER BY date DESC LIMIT 1) "
                   "SELECT (b.value-a.value)/ABS(a.value)*100 value,a.date start_date,b.date end_date,"
                   "a.value start_value,b.value end_value,a.unit source_unit,(SELECT COUNT(*) FROM p) observation_count FROM a,b",
                   (mineral, year, start, end))
    elif p == 45:
        node = calc(retrieve('price'), 'threshold_first', threshold_ratio=0.5, comparison='le')
        finish(node, "WITH p AS (SELECT date,value FROM observations WHERE " + predicate +
               "), b AS (SELECT * FROM p ORDER BY date LIMIT 1), "
               "hit AS (SELECT p.* FROM p,b WHERE p.value<=b.value*0.5 ORDER BY p.date LIMIT 1) "
               "SELECT EXISTS(SELECT 1 FROM hit) matched,(SELECT date FROM hit) date,(SELECT value FROM hit) value,"
               "b.date base_date,b.value*0.5 threshold,'USD/t' unit FROM b", (mineral, year))
    elif p in {46, 48}:
        for selected in (mineral, bindings['m2']):
            source = retrieve('price', selected)
            if p == 46:
                node = calc(monthly(source), 'base100', time_field='period')
                finish(node, "WITH p AS (SELECT substr(date,1,7) date,AVG(value) value FROM observations WHERE " + predicate +
                       " GROUP BY substr(date,1,7)), b AS (SELECT * FROM p ORDER BY date LIMIT 1) "
                       "SELECT p.date,b.date base_date,b.value base_value,'USD/t' source_unit,p.value/b.value*100 value FROM p,b",
                       (selected, year))
            else:
                returns = calc(source, 'periodic_return', frequency='observation', null_policy='skip')
                node = op(Operator.AGGREGATE, [returns], field='value', aggregation='stddev_samp', include_count=True)
                finish(node, "WITH p AS (SELECT value,LAG(value) OVER(ORDER BY date) previous FROM observations WHERE " + predicate +
                       "), r AS (SELECT (value-previous)/ABS(previous)*100 v FROM p WHERE previous IS NOT NULL) "
                       "SELECT sqrt((SUM(v*v)-SUM(v)*SUM(v)/COUNT(*))/(COUNT(*)-1)) value,COUNT(*) observation_count FROM r",
                       (selected, year))
    elif p == 47:
        left, right = retrieve('inventory'), retrieve('price')
        joined = op(Operator.JOIN, [left, right], join_key='date', how='full')
        node = op(Operator.CALCULATE, [joined], calculation='correlation', time_field='date',
                  field='left.value', other_field='right.value', unit_field='left_unit',
                  other_unit_field='right_unit', null_policy='pairwise')
        finish(node, """WITH i AS (SELECT date,value FROM observations WHERE domain='inventory' AND mineral=? AND year=?),
               p AS (SELECT date,value FROM observations WHERE domain='price' AND mineral=? AND year=?),
               dates AS (SELECT date FROM i UNION SELECT date FROM p),
               pairs AS (SELECT i.value x,p.value y FROM dates LEFT JOIN i USING(date) LEFT JOIN p USING(date)),
               used AS (SELECT * FROM pairs WHERE x IS NOT NULL AND y IS NOT NULL)
               SELECT (AVG(x*y)-AVG(x)*AVG(y))/sqrt((AVG(x*x)-AVG(x)*AVG(x))*(AVG(y*y)-AVG(y)*AVG(y))) value,
               COUNT(*) observation_count,
               (SELECT COUNT(*) FROM pairs WHERE x IS NOT NULL AND y IS NULL) left_only_count,
               (SELECT COUNT(*) FROM pairs WHERE x IS NULL AND y IS NOT NULL) right_only_count,
               (SELECT COUNT(*) FROM pairs WHERE x IS NULL AND y IS NULL) neither_count FROM used""",
               (mineral, year, mineral, year))
    else:
        returns = []
        for domain in ('indicator', 'price'):
            returns.append(calc(monthly(retrieve(domain, prior_month=True)), 'periodic_return', time_field='period', frequency='month'))
        node = op(Operator.JOIN, returns, join_key='date', how='inner')
        if p == 64:
            node = op(Operator.FILTER, [node], predicate={'field':'left.value','operator':'greater_than','value':0})
            node = op(Operator.FILTER, [node], predicate={'field':'right.value','operator':'less_than','value':0})
        node = op(Operator.PROJECT, [node], fields=['date', 'left.value', 'right.value'])
        sql = """WITH m AS (SELECT domain,substr(date,1,7) date,AVG(value) v FROM observations
            WHERE mineral=? AND date BETWEEN ? AND ? AND (domain='price' OR (domain='indicator' AND series='HI001'))
            GROUP BY domain,substr(date,1,7)), p AS (SELECT *,LAG(v) OVER(PARTITION BY domain ORDER BY date) prev FROM m),
            r AS (SELECT domain,date,(v-prev)/ABS(prev)*100 v FROM p WHERE prev IS NOT NULL)
            SELECT i.date,i.v AS 'left.value',p.v AS 'right.value' FROM r i JOIN r p USING(date)
            WHERE i.domain='indicator' AND p.domain='price'"""
        if p == 64:
            sql += ' AND i.v>0 AND p.v<0'
        finish(node, sql, (mineral, f'{year-1}-12-01', f'{year}-12-31'))
    return SemanticProgram(tuple(nodes), tuple(roots)), sources, oracles


def typed_source(data):
    return TypedResult.success(ValueType.TIME_SERIES, data, unit=data[0].get('unit') if data else None,
        source=('synthetic-sqlite',), evidence=(Evidence('structured','synthetic-sqlite','series',json.dumps(data)),),
        provenance=('qa500:synthetic',))


async def execute(case, db):
    """Runtime integration entry point for main after installing the delegate."""
    program, sources, expected = gold(case, db)
    factory = LiveOperatorFactory(message='', session_id='qa500-series', profile='public', llm=None, history=[])
    def build(node, dependencies, bindings):
        if node.node_id in sources:
            data,_,_=read_fixture(db,node)
            return FunctionStep(node.node_id, node.operator.value, lambda _ctx, _inputs: typed_source(data),
                                dependencies=dependencies, bindings=bindings)
        return factory.build(node=node, dependencies=dependencies, bindings=bindings)
    pipe = PipeLowerer(build).lower(program, pipe_id='series-'+case['id'])
    return await PipeRuntime().execute(pipe), expected
