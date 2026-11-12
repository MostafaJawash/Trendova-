"""Keyset (cursor) pagination for the product list (Requirement 3). The `page` parameter keeps working unchanged."""
import pytest
from tests.conftest import make_user

pytestmark = pytest.mark.req3_phase1
BASE = '/api/v1'


@pytest.fixture
def catalog(client):
    admin = client.post(BASE + '/auth/login', json={'email': 'admin@test.example', 'password': 'adminpassword1'})
    admin_h = {'Authorization': 'Bearer ' + admin.json()['access_token']}
    cat = client.post(BASE + '/categories', json={'name': 'Keyset', 'description': 'x'}, headers=admin_h).json()['id']
    for i in range(23):   # tied prices and names on purpose: the id tie-break must keep pages stable
        r = client.post(BASE + '/products', headers=admin_h, data={'name': f'Thing {i % 5}', 'description': 'd', 'price': str([5, 5, 7.5][i % 3]), 'category_id': cat, 'initial_quantity': 1})
        assert r.status_code == 201, r.text
    # sqlite stores CURRENT_TIMESTAMP without a fraction while bound datetimes carry one, so string comparison of equal
    # instants is wrong there (a test-database artefact; MySQL compares real DATETIMEs). Rewrite created_at through the ORM so
    # stored and bound values have the same format, keeping deliberate ties (3 products share each instant).
    from datetime import datetime, timedelta
    from app.core.database import SessionLocal
    from app.modules.products.models import Product
    with SessionLocal() as db:
        for n, p in enumerate(db.query(Product).order_by(Product.id).all()):
            p.created_at = datetime(2026, 1, 1) + timedelta(minutes=n // 3)
        db.commit()
    _, h = make_user(client, 'keyset@test.example')
    return client, h


def _walk(client, h, query, limit):
    ids, cursor, pages = [], None, 0
    while True:
        url = f'{BASE}/products?limit={limit}&{query}' + (f'&cursor={cursor}' if cursor else '')
        body = client.get(url, headers=h).json()
        ids += [i['id'] for i in body['items']]
        pages += 1
        cursor = body['next_cursor']
        if not cursor or pages > 20:
            return ids, pages


@pytest.mark.parametrize('query', ['', 'sort_by=price&order=asc', 'sort_by=price&order=desc', 'sort_by=name&order=asc', 'sort_by=name&order=desc', 'sort_by=created_at&order=asc'])
def test_cursor_walk_equals_offset_pages(catalog, query):
    client, h = catalog
    offset_ids = []
    for page in range(1, 8):
        offset_ids += [i['id'] for i in client.get(f'{BASE}/products?limit=5&page={page}&{query}', headers=h).json()['items']]
    keyset_ids, pages = _walk(client, h, query, 5)
    assert keyset_ids == offset_ids and len(keyset_ids) == 23 and len(set(keyset_ids)) == 23


def test_page_parameter_still_works_and_cursor_wins(catalog):
    client, h = catalog
    first = client.get(f'{BASE}/products?limit=5', headers=h).json()
    page2 = client.get(f'{BASE}/products?limit=5&page=2', headers=h).json()
    via_cursor = client.get(f'{BASE}/products?limit=5&page=9&cursor={first["next_cursor"]}', headers=h).json()   # page is ignored
    assert [i['id'] for i in via_cursor['items']] == [i['id'] for i in page2['items']]
    assert via_cursor['total'] == first['total'] == 23


def test_last_page_has_no_next_cursor(catalog):
    client, h = catalog
    body = client.get(f'{BASE}/products?limit=5&page=5', headers=h).json()
    assert len(body['items']) == 3 and body['next_cursor'] is None


def test_bad_cursor_and_cursor_for_another_sort_are_rejected(catalog):
    client, h = catalog
    for bad in ('not-a-cursor', 'e30', ''):
        if bad:
            r = client.get(f'{BASE}/products?cursor={bad}', headers=h)
            assert r.status_code == 422 and r.json()['error']['code'] == 'INVALID_CURSOR'
    c = client.get(f'{BASE}/products?limit=5&sort_by=price&order=asc', headers=h).json()['next_cursor']
    r = client.get(f'{BASE}/products?limit=5&cursor={c}', headers=h)   # cursor was issued for price asc, request is created_at desc
    assert r.status_code == 422
