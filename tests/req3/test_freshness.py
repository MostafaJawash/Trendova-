"""THE key sentence of Requirement 3: "a product edit is visible immediately, even with the cache and the read replica".

Everything here runs with the replica deliberately LAGGING (SOURCE_DELAY=3) and with the list and the detail ALREADY
cached before the edit. Live: final app (USE_READ_REPLICA, CACHE_ENABLED, ETAG_ENABLED on) + `tester` container.
"""
import time
import pytest
from tests.req3 import live

pytestmark = [pytest.mark.req3_phase2, pytest.mark.skipif(not live.BASE, reason='E2E_BASE_URL not set (needs the compose stack)')]


@pytest.fixture(scope='module')
def api():
    return live.Api()


def test_admin_edit_is_visible_immediately_in_list_and_detail_despite_cache_and_lagging_replica(api):
    admin = api.admin(); pid, cat = api.new_product(admin, price='10.00', quantity=4)
    _, customer = api.new_user()
    list_url = f'/products?category={cat}&limit=20'
    with live.source_delay(3):
        assert api.c.get(list_url, headers=customer).headers['x-cache'] == 'MISS'
        assert api.c.get(list_url, headers=customer).headers['x-cache'] == 'HIT'        # cached
        api.c.get(f'/products/{pid}', headers=customer); assert api.c.get(f'/products/{pid}', headers=customer).headers['x-cache'] == 'HIT'
        for price in ('21.00', '22.00', '23.00'):                                        # repeated edits, each read right away
            api.edit_price(admin, pid, price)
            d = api.c.get(f'/products/{pid}', headers=customer)
            l = api.c.get(list_url, headers=customer)
            assert d.json()['price'] == price, d.text
            assert [i['price'] for i in l.json()['items'] if i['id'] == pid] == [price], l.text
        # name change also shows up in the search (replica) path right away: the product-write marker sends it to the primary
        r = api.c.put(f'/products/{pid}', headers=admin, data={'name': 'req3_test_renamed_zzq'})
        assert r.status_code == 200
        s = api.c.get('/products?search=renamed_zzq', headers=customer).json()
        assert [i['id'] for i in s['items']] == [pid]


def test_reservation_through_the_order_flow_shows_reduced_stock_immediately(api):
    admin = api.admin(); pid, cat = api.new_product(admin, quantity=9)
    _, customer = api.new_user()
    with live.source_delay(3):
        api.c.get(f'/products/{pid}', headers=customer); assert api.c.get(f'/products/{pid}', headers=customer).headers['x-cache'] == 'HIT'
        api.order(customer, pid, 4)
        d = api.c.get(f'/products/{pid}', headers=customer)
        assert d.json()['stock'] == {'quantity': 5, 'status': 'available'}, d.text
        l = api.c.get(f'/products?category={cat}&include_stock=true', headers=customer).json()
        assert l['items'][0]['stock']['quantity'] == 5
        api.order(customer, pid, 5)
        assert api.c.get(f'/products/{pid}', headers=customer).json()['stock']['quantity'] == 0
        over = api.c.post('/orders', headers=customer, json={'items': [{'product_id': pid, 'quantity': 1}]})
        assert over.status_code == 409                                                  # Requirement 2 guarantee intact


def test_category_rename_is_visible_in_cached_detail_immediately(api):
    admin = api.admin(); pid, cat = api.new_product(admin)
    _, customer = api.new_user()
    api.c.get(f'/products/{pid}', headers=customer)
    assert api.c.get(f'/products/{pid}', headers=customer).headers['x-cache'] == 'HIT'
    new_name = live.tag()
    assert api.c.put(f'/categories/{cat}', headers=admin, json={'name': new_name}).status_code == 200
    assert api.c.get(f'/products/{pid}', headers=customer).json()['category']['name'] == new_name


def test_favorites_are_per_user_even_with_a_shared_cache(api):
    admin = api.admin(); pid, cat = api.new_product(admin)
    _, u1 = api.new_user(); _, u2 = api.new_user()
    api.c.get(f'/products?category={cat}', headers=u1); api.c.get(f'/products?category={cat}', headers=u2)
    assert api.c.post(f'/favorites/{pid}', headers=u1).status_code in (200, 201)
    l1 = api.c.get(f'/products?category={cat}', headers=u1).json()['items'][0]
    l2 = api.c.get(f'/products?category={cat}', headers=u2).json()['items'][0]
    assert (l1['is_favorite'], l2['is_favorite']) == (True, False)
    assert api.c.get(f'/products/{pid}', headers=u1).json()['is_favorite'] is True
    assert api.c.get(f'/products/{pid}', headers=u2).json()['is_favorite'] is False
