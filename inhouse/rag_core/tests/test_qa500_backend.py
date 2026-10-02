"""Gold operator regression, deliberately distinct from natural-language E2E."""
import asyncio
import pytest
from dataclasses import replace
from inhouse.rag_core.tests.qa500_backend import CASES, SUPPORTED, fixture, validate_case


@pytest.fixture(scope='module')
def synthetic_db():
    db=fixture()
    yield db
    db.close()


@pytest.mark.parametrize('case',[c for c in CASES if int(c['pattern_id'][4:]) in SUPPORTED],ids=lambda c:c['id'])
def test_independent_sql_oracle(case,synthetic_db):
    record=asyncio.run(validate_case(case,synthetic_db))
    assert record['backend_executed'],record
    assert record['status']=='BACKEND_PASS',record['errors']


@pytest.mark.parametrize('mutator',[
    lambda r:replace(r,value=list(reversed(r.value))),
    lambda r:replace(r,unit='kg'),
    lambda r:replace(r,evidence=(),source=(),provenance=()),
])
def test_oracle_detects_order_unit_and_evidence_corruption(mutator,synthetic_db):
    # Unequal grouped totals exercise order; shared test DB only, never live.
    synthetic_db.execute("UPDATE observations SET value=value+20 WHERE hs='PRODUCT'")
    try:
        case=next(c for c in CASES if c['pattern_id']=='PAT-015')
        record=asyncio.run(validate_case(case,synthetic_db,result_mutator=mutator))
        assert record['status']=='EXECUTION_FAIL',record
    finally:
        synthetic_db.execute("UPDATE observations SET value=value-20 WHERE hs='PRODUCT'")
