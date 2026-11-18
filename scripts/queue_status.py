"""Print RabbitMQ ready, unacknowledged and dead-letter counts."""
import base64, json, os
from urllib.request import Request, urlopen

url=os.getenv('RABBITMQ_MANAGEMENT_URL','http://localhost:15672').rstrip('/')
user=os.getenv('RABBITMQ_USER','trendova'); password=os.getenv('RABBITMQ_PASSWORD','trendova-local-password')
auth=base64.b64encode(f'{user}:{password}'.encode()).decode()
def count(queue):
    req=Request(f'{url}/api/queues/%2F/{queue}',headers={'Authorization':f'Basic {auth}'})
    with urlopen(req,timeout=3) as response:return json.load(response)
for name in ('email.order_created','email.dead'):
    data=count(name); print(f"{name}: ready={data['messages_ready']} unacked={data['messages_unacknowledged']}")
