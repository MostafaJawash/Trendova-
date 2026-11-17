import pytest
from tests.conftest import make_user

pytestmark=pytest.mark.req4

def _auth(client, headers, channel):
    return client.post('/api/v1/broadcasting/auth',json={'socket_id':'42.7','channel_name':channel},headers=headers)

def test_private_channel_authorization_four_cases(setup):
    client=setup['client']; admin=setup['admin']; product_id=setup['product']['id']
    owner,owner_headers=make_user(client,'req4_owner@example.com')
    other,other_headers=make_user(client,'req4_other@example.com')
    order=client.post('/api/v1/orders',json={'items':[{'product_id':product_id,'quantity':1}]},headers=owner_headers)
    assert order.status_code==201,order.text
    order_id=order.json()['id']
    assert _auth(client,admin,'private-admin-orders').status_code==200
    assert _auth(client,owner_headers,'private-admin-orders').status_code==403
    assert _auth(client,owner_headers,f'private-order.{order_id}').status_code==200
    assert _auth(client,other_headers,f'private-order.{order_id}').status_code==403

def test_private_channel_rejects_missing_token(client):
    response=_auth(client,{},'private-admin-orders')
    assert response.status_code==401
