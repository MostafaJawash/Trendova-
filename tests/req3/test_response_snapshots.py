"""Response-snapshot regression tests (Requirement 3).

The list / detail / my-orders JSON bodies must stay byte-for-byte equivalent while the queries behind
them are optimised (indexes, favorites EXISTS, count shortcut, keyset, selectinload ...) and, later,
cached. The golden files in tests/req3/snapshots were generated from the code BEFORE any query change:

    UPDATE_SNAPSHOTS=1 pytest tests/req3/test_response_snapshots.py     # regenerate on purpose only

Only additive fields are tolerated (`next_cursor` on list pages); everything else is compared exactly:
fields, key order, item order, counts and the per-user `is_favorite` flags. Timestamps and reservation
uuids are masked because they differ between runs.
"""
import json
import os
from pathlib import Path
import pytest
from tests.conftest import make_user

pytestmark = pytest.mark.req3_phase1
SNAP_DIR = Path(__file__).parent / 'snapshots'
BASE = '/api/v1'
ADDITIVE_KEYS = {'next_cursor'}   # fields added on top of the original contract
TS_KEYS = {'created_at', 'updated_at'}


def _normalize(node):
    if isinstance(node, dict):
        return {k: ('<ts>' if k in TS_KEYS else '<uuid>' if k == 'reservation_id' and v else _normalize(v))
                for k, v in node.items() if k not in ADDITIVE_KEYS}
    if isinstance(node, list):
        return [_normalize(x) for x in node]
    return node


def _check(name, response, failures=None):
    assert response.status_code == 200, response.text
    # key order is part of the contract: dump WITHOUT sort_keys
    actual = json.dumps(_normalize(response.json()), indent=1, ensure_ascii=False) + '\n'
    path = SNAP_DIR / f'{name}.json'
    if os.getenv('UPDATE_SNAPSHOTS') == '1':
        SNAP_DIR.mkdir(exist_ok=True)
        path.write_text(actual, encoding='utf-8')
        return
    assert path.exists(), f'missing golden file {path} (generate with UPDATE_SNAPSHOTS=1 on the reference code)'
    if actual != path.read_text(encoding='utf-8'):
        if failures is None:
            raise AssertionError(f'{name}: response body changed')
        failures.append(name)


@pytest.fixture
def world(client):
    """Deterministic catalog: 3 categories, 24 products (some tied prices/names), 1 inactive,
    two customers with different favorites, admin, and a few multi-item orders."""
    admin = client.post(BASE + '/auth/login', json={'email': 'admin@test.example', 'password': 'adminpassword1'})
    admin_h = {'Authorization': 'Bearer ' + admin.json()['access_token']}
    cats = [client.post(BASE + '/categories', json={'name': n, 'description': f'{n} desc'}, headers=admin_h).json()['id']
            for n in ('Alpha', 'Beta', 'Gamma')]
    names = ['Wireless Headphones', 'Smart Lamp', 'Portable Speaker', 'Classic Watch', 'Pro Keyboard', 'Mini Router']
    pids = []
    for i in range(24):
        r = client.post(BASE + '/products', headers=admin_h, data={
            'name': f'{names[i % 6]} {i // 6}', 'description': 'Great ' + names[(i + 1) % 6].lower() + (' headphones' if i % 5 == 0 else ''),
            'price': str([10, 20, 20, 35.5, 5, 99.99][i % 6]), 'category_id': cats[i % 3], 'initial_quantity': 50 + i})
        assert r.status_code == 201, r.text
        pids.append(r.json()['id'])
    assert client.delete(f'{BASE}/products/{pids[7]}', headers=admin_h).status_code == 204   # inactive product
    a, a_h = make_user(client, 'snap_a@test.example')
    b, b_h = make_user(client, 'snap_b@test.example')
    for pid in (pids[0], pids[3], pids[4], pids[9]):
        assert client.post(f'{BASE}/favorites/{pid}', headers=a_h).status_code in (200, 201)
    assert client.post(f'{BASE}/favorites/{pids[3]}', headers=b_h).status_code in (200, 201)
    for items in ([(pids[0], 2), (pids[1], 1)], [(pids[2], 1)], [(pids[3], 3), (pids[4], 1), (pids[5], 2)], [(pids[8], 1)]):
        r = client.post(BASE + '/orders', headers=a_h, json={'items': [{'product_id': p, 'quantity': q} for p, q in items]})
        assert r.status_code == 201, r.text
    assert client.post(BASE + '/orders', headers=b_h, json={'items': [{'product_id': pids[1], 'quantity': 1}]}).status_code == 201
    return {'c': client, 'admin': admin_h, 'a': a_h, 'b': b_h, 'pids': pids, 'cats': cats}


LIST_CASES = {
    'list_default': '/products',
    'list_limit5_page2': '/products?limit=5&page=2',
    'list_limit5_last_partial_page': '/products?limit=5&page=5',
    'list_beyond_last_page': '/products?limit=5&page=9',
    'list_category': '/products?category={cat0}&limit=3',
    'list_category_page2': '/products?category={cat1}&limit=3&page=2',
    'list_sort_price_asc': '/products?sort_by=price&order=asc&limit=10',
    'list_sort_price_desc': '/products?sort_by=price&order=desc&limit=10&page=2',
    'list_sort_name_asc': '/products?sort_by=name&order=asc&limit=10',
    'list_sort_name_desc': '/products?sort_by=name&order=desc&limit=10',
    'list_price_range': '/products?minPrice=10&maxPrice=36&limit=20',
    'list_search_headphones': '/products?search=headphones&limit=20',
    'list_search_upper_case': '/products?search=SMART&limit=5',
    'list_search_no_match': '/products?search=zzzzz',
    'list_search_plus_category': '/products?search=great&category={cat2}&limit=4',
}


def test_product_list_bodies_are_stable(world):
    failures = []
    for case in sorted(LIST_CASES):
        for who in ('a', 'b', 'admin'):
            url = LIST_CASES[case].format(cat0=world['cats'][0], cat1=world['cats'][1], cat2=world['cats'][2])
            _check(f'{case}__{who}', world['c'].get(BASE + url, headers=world[who]), failures)
    assert not failures, 'list bodies changed: ' + ', '.join(failures)


def test_product_detail_bodies_are_stable(world):
    # stock comes from the in-memory fake in unit-test mode; the body keeps `stock.quantity`
    failures = []
    for idx in (0, 1, 3, 4, 9):
        for who in ('a', 'b', 'admin'):
            _check(f'detail_{idx}__{who}', world['c'].get(f"{BASE}/products/{world['pids'][idx]}", headers=world[who]), failures)
    assert not failures, 'detail bodies changed: ' + ', '.join(failures)
    assert world['c'].get(f"{BASE}/products/{world['pids'][7]}", headers=world['a']).status_code == 404   # inactive


ORDER_CASES = [
    ('orders_a_default', '/orders'),
    ('orders_a_limit2_page1', '/orders?limit=2'),
    ('orders_a_limit2_page2', '/orders?limit=2&page=2'),
    ('orders_a_limit2_page3', '/orders?limit=2&page=3'),
    ('orders_a_status_pending', '/orders?status=pending'),
    ('orders_a_status_cancelled', '/orders?status=cancelled'),
]


def test_my_orders_bodies_are_stable(world):
    failures = []
    for case, url in ORDER_CASES:
        _check(case, world['c'].get(BASE + url, headers=world['a']), failures)
    _check('orders_b_default', world['c'].get(BASE + '/orders', headers=world['b']), failures)
    _check('orders_admin_all', world['c'].get(BASE + '/orders?limit=3', headers=world['admin']), failures)
    _check('orders_admin_filter_user', world['c'].get(BASE + '/orders', headers=world['admin'], params={'user_id': 2}), failures)
    assert not failures, 'order bodies changed: ' + ', '.join(failures)
