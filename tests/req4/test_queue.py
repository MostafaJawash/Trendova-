import json
import pytest
from app.core import queue
from app.core.database import SessionLocal
from app.modules.orders.models import OutboxEvent

pytestmark=pytest.mark.req4

class Channel:
    def __init__(self):self.exchanges=[];self.queues=[];self.bindings=[]
    def exchange_declare(self,*args,**kwargs):self.exchanges.append((args,kwargs))
    def queue_declare(self,*args,**kwargs):self.queues.append((args,kwargs))
    def queue_bind(self,*args,**kwargs):self.bindings.append((args,kwargs))

def test_topology_is_durable_with_three_retry_queues():
    channel=Channel();queue.declare(channel)
    names=[args[0] if args else kwargs.get('queue') for args,kwargs in channel.queues]
    assert {'email.order_created','email.dead','email.retry.1','email.retry.2','email.retry.3'} <= set(names)
    retry=[kwargs['arguments']['x-message-ttl'] for args,kwargs in channel.queues if (args[0] if args else kwargs.get('queue','')).startswith('email.retry.')]
    assert retry==[1000,5000,15000]
    assert all(kwargs.get('durable') for args,kwargs in channel.queues)

def test_order_creation_persists_outbox_before_broker_publish(setup):
    client=setup['client']; product_id=setup['product']['id']
    from tests.conftest import make_user
    _,headers=make_user(client,'req4_outbox@example.com')
    response=client.post('/api/v1/orders',json={'items':[{'product_id':product_id,'quantity':1}]},headers=headers)
    assert response.status_code==201,response.text
    with SessionLocal() as db:
        events=db.query(OutboxEvent).filter(OutboxEvent.published_at.is_(None)).all()
        assert any(json.loads(event.payload)['order']['id']==response.json()['id'] for event in events)
