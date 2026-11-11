"""Real end-to-end check through the Go inventory service (fake mode cannot cover the gRPC path).

Runs against a live stack over HTTP, so it is skipped unless E2E_BASE_URL is set, e.g.
  docker compose run --rm --no-deps -e E2E_BASE_URL=http://app:8000/api/v1 ... pytest -m req3_phase1
It creates one throw-away product and one user (the product is soft-deleted at the end).
"""
import os
import uuid
import httpx
import pytest

BASE = os.getenv('E2E_BASE_URL')
pytestmark = [pytest.mark.req3_phase1, pytest.mark.skipif(not BASE, reason='E2E_BASE_URL not set (needs the running compose stack)')]


def _login(c, email, password):
    r = c.post('/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def test_order_flows_through_the_go_inventory_service():
    tag = uuid.uuid4().hex[:8]
    with httpx.Client(base_url=BASE, timeout=30) as c:
        admin = _login(c, os.getenv('E2E_ADMIN_EMAIL', 'admin@example.com'), os.getenv('E2E_ADMIN_PASSWORD', 'ChangeMe123!'))
        # initial stock is written to Postgres through the SetStock RPC
        p = c.post('/products', headers=admin, data={'name': f'e2e-{tag}', 'price': '9.99', 'category_id': 1, 'initial_quantity': 5})
        assert p.status_code == 201, p.text
        pid = p.json()['id']
        try:
            email = f'e2e-{tag}@example.com'
            assert c.post('/auth/register', json={'email': email, 'name': 'E2E', 'password': 'password123'}).status_code == 201
            user = _login(c, email, 'password123')

            stock = lambda: c.get(f'/products/{pid}', headers=admin).json()['stock']
            assert stock() == {'quantity': 5, 'status': 'available'}  # read through GetQuantity

            o = c.post('/orders', headers=user, json={'items': [{'product_id': pid, 'quantity': 2}]})
            assert o.status_code == 201, o.text  # Reserve RPC
            assert stock()['quantity'] == 3

            too_many = c.post('/orders', headers=user, json={'items': [{'product_id': pid, 'quantity': 4}]})
            assert too_many.status_code == 409 and too_many.json()['error']['code'] == 'INSUFFICIENT_STOCK'
            assert stock()['quantity'] == 3  # a rejected reservation changes nothing

            cancel = c.patch(f"/orders/{o.json()['id']}/status", headers=admin, json={'status': 'cancelled'})
            assert cancel.status_code == 200, cancel.text  # Release RPC
            assert stock()['quantity'] == 5
        finally:
            c.delete(f'/products/{pid}', headers=admin)
