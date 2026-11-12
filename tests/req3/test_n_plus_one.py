"""N+1 / query-shape tests (Requirement 3, database layer).

* Unit part (sqlite, fake inventory): the number of SQL statements of list / detail / my-orders must stay CONSTANT as the page
  size grows (no per-row query), counted with the same counter the app exposes as X-DB-Query-Count.
* Live part (needs REQ3_DB_URL, the seeded MySQL): hot-query EXPLAIN ANALYZE assertions - no full scan, no filesort, and a
  bounded number of rows actually examined.
"""
import os
import re
import pytest
from app.core import query_counter
from tests.conftest import make_user

pytestmark = pytest.mark.req3_phase1
BASE = '/api/v1'


@pytest.fixture
def busy_world(client):
    admin = client.post(BASE + '/auth/login', json={'email': 'admin@test.example', 'password': 'adminpassword1'})
    admin_h = {'Authorization': 'Bearer ' + admin.json()['access_token']}
    cat = client.post(BASE + '/categories', json={'name': 'N1 cat', 'description': 'x'}, headers=admin_h).json()['id']
    pids = []
    for i in range(36):
        r = client.post(BASE + '/products', headers=admin_h, data={'name': f'Item {i}', 'description': 'd', 'price': '5.00', 'category_id': cat, 'initial_quantity': 100})
        assert r.status_code == 201, r.text
        pids.append(r.json()['id'])
    _, user_h = make_user(client, 'n1_user@test.example')
    for pid in pids[:20]:
        assert client.post(f'{BASE}/favorites/{pid}', headers=user_h).status_code in (200, 201)
    for i in range(14):   # 14 orders x 3 items
        r = client.post(BASE + '/orders', headers=user_h, json={'items': [{'product_id': pids[(i + k) % 36], 'quantity': 1} for k in range(3)]})
        assert r.status_code == 201, r.text
    return {'c': client, 'h': user_h, 'pids': pids}


def _count(client, url, headers):
    query_counter.install(__import__('app.core.database', fromlist=['engine']).engine)
    with query_counter.count_queries(any_thread=True) as log:
        r = client.get(BASE + url, headers=headers)
    assert r.status_code == 200, r.text
    return log.count, r


def test_list_query_count_is_constant_in_page_size(busy_world):
    w = busy_world
    counts = {limit: _count(w['c'], f'/products?limit={limit}', w['h'])[0] for limit in (1, 5, 20, 36)}
    assert len(set(counts.values())) == 1, f'list statements grow with limit: {counts}'


def test_my_orders_query_count_is_constant_in_page_size(busy_world):
    w = busy_world
    counts = {limit: _count(w['c'], f'/orders?limit={limit}', w['h'])[0] for limit in (1, 5, 10, 14)}
    assert len(set(counts.values())) == 1, f'my-orders statements grow with limit: {counts}'


def test_detail_query_count_is_constant(busy_world):
    w = busy_world
    counts = {pid: _count(w['c'], f'/products/{pid}', w['h'])[0] for pid in w['pids'][:6]}
    assert len(set(counts.values())) == 1, counts


def test_list_issues_one_favorites_query_not_one_per_row(busy_world):
    w = busy_world
    with query_counter.count_queries(any_thread=True) as log:
        w['c'].get(BASE + '/products?limit=36', headers=w['h'])
    fav = [s for s in log.statements if 'FROM favorites' in s]
    assert len(fav) == 1, fav


# ---------------------------------------------------------------- live EXPLAIN assertions
DB_URL = os.getenv('REQ3_DB_URL')
live = pytest.mark.skipif(not DB_URL, reason='REQ3_DB_URL not set (needs the seeded MySQL of the compose stack)')

def _plans(fn):
    """Run `fn(db)` against the seeded MySQL, capture every SELECT the real application code emits and EXPLAIN ANALYZE each."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    eng = create_engine(DB_URL)
    seen = []

    @event.listens_for(eng, 'before_cursor_execute')
    def _cap(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            seen.append((statement, parameters))
    with sessionmaker(bind=eng)() as db:
        fn(db)
    out = []
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        for stmt, params in seen:
            cur.execute('EXPLAIN ANALYZE ' + (cur.mogrify(stmt, params) if params else stmt))
            out.append((stmt, chr(10).join(r[0] for r in cur.fetchall())))
    finally:
        raw.close()
        eng.dispose()
    return out


def _rows(plan):
    return [int(x) for x in re.findall(r'actual time=[\d.]+\.\.[\d.]+ rows=(\d+)', plan)]


def _is_count(stmt):
    return 'count(' in stmt.lower()


def _assert_page_queries_are_indexed(plans, max_rows):
    page = [(s, p) for s, p in plans if not _is_count(s)]
    assert page
    for stmt, plan in page:
        assert 'Table scan' not in plan, f'full scan: {stmt} {plan}'
        assert 'Sort:' not in plan and 'filesort' not in plan.lower(), f'filesort: {stmt} {plan}'
        rows = _rows(plan)
        assert not rows or max(rows) <= max_rows, f'examined {max(rows)} rows (limit {max_rows}): {stmt} {plan}'


def _user_id():
    return 1001   # hottest seeded customer (about 16k orders)


@live
def test_category_page_plan():
    from app.modules.products import service
    _assert_page_queries_are_indexed(_plans(lambda db: service.products(db, _user_id(), 1, 20, category_id=3)), 100)


@live
def test_newest_page_plan():
    from app.modules.products import service
    _assert_page_queries_are_indexed(_plans(lambda db: service.products(db, _user_id(), 1, 20)), 100)


@live
def test_search_page_plan_uses_index_order():
    from app.modules.products import service
    _assert_page_queries_are_indexed(_plans(lambda db: service.products(db, _user_id(), 1, 20, search='wireless')), 2000)


@live
def test_keyset_deep_page_plan_examines_only_the_page():
    from app.modules.products import service
    holder = {}
    _plans(lambda db: holder.setdefault('cursor', service.products(db, _user_id(), 899, 20)['next_cursor']))
    plans = _plans(lambda db: service.products(db, _user_id(), 1, 20, cursor=holder['cursor']))
    _assert_page_queries_are_indexed(plans, 100)      # OFFSET page 900 examines 18,000 rows; the cursor page 20


@live
def test_my_orders_page_plan():
    from app.modules.orders import service
    _assert_page_queries_are_indexed(_plans(lambda db: service.list_orders(db, _user_id(), 1, 10)), 100)


@live
def test_detail_plan_is_a_primary_key_lookup():
    from app.modules.products import service
    plans = _plans(lambda db: service.product(db, 12345, _user_id(), False))
    assert plans and all('Table scan' not in plan for _, plan in plans)
