"""Live queue tests; run only inside the compose tester container."""
import json
import time
import base64
from urllib.request import urlopen
import pytest
from tests.req3.live import Api, container_stopped, docker, cname

pytestmark=pytest.mark.req4
MAILPIT='http://mailpit:8025/api/v1/messages'

def queue_depth(name='email.order_created'):
    from urllib.request import Request
    token=base64.b64encode(b'trendova:trendova-local-password').decode()
    request=Request(f'http://rabbitmq:15672/api/queues/%2F/{name}',headers={'Authorization':f'Basic {token}'})
    with urlopen(request,timeout=5) as response:return json.load(response)['messages_ready']

def mail_count():
    with urlopen(MAILPIT,timeout=5) as response:return json.load(response).get('total',0)

def wait_for(predicate,timeout=25):
    end=time.time()+timeout
    while time.time()<end:
        try:
            if predicate():return True
        except Exception:
            pass
        time.sleep(.25)
    return False

def test_worker_stop_start_five_orders_are_not_lost():
    api=Api(); admin=api.admin(); _,user=api.new_user(); product,_=api.new_product(admin,quantity=20)
    before=mail_count()
    with container_stopped('worker'):
        started=time.monotonic(); orders=[api.order(user,product) for _ in range(5)]; elapsed=time.monotonic()-started
        assert len({order['id'] for order in orders})==5
        assert wait_for(lambda:queue_depth()>=5)
        assert elapsed<10
    assert wait_for(lambda:mail_count()>=before+5)
    assert wait_for(lambda:queue_depth()==0)

def test_rabbitmq_down_stores_outbox_and_returns_201():
    api=Api(); admin=api.admin(); _,user=api.new_user(); product,_=api.new_product(admin,quantity=3)
    with container_stopped('rabbitmq'):
        response=api.c.post('/orders',headers=user,json={'items':[{'product_id':product,'quantity':1}]})
        assert response.status_code==201,response.text
    assert wait_for(lambda:queue_depth()==0,timeout=90)

def test_smtp_failure_retries_to_dlq_and_next_message_is_processed():
    api=Api(); admin=api.admin(); _,user=api.new_user(); product,_=api.new_product(admin,quantity=4)
    dead_before=queue_depth('email.dead')
    with container_stopped('mailpit'):
        failed=api.order(user,product)
        assert wait_for(lambda:queue_depth('email.dead')>=dead_before+1,timeout=45)
    before=mail_count(); api.order(user,product)
    assert wait_for(lambda:mail_count()>=before+1,timeout=30)
