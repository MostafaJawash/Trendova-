"""RabbitMQ topology, publishing and a small transactional-outbox dispatcher."""
import json
import logging
from datetime import datetime

import pika
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.orders.models import OutboxEvent

log = logging.getLogger(__name__)
EXCHANGE = 'orders'; DLX = 'orders.dlx'; QUEUE = 'email.order_created'; DEAD = 'email.dead'

def _connection():
    return pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))

def declare(channel):
    channel.exchange_declare(EXCHANGE, 'direct', durable=True)
    channel.exchange_declare(DLX, 'direct', durable=True)
    channel.queue_declare(DEAD, durable=True)
    channel.queue_bind(DEAD, DLX, 'dead')
    channel.queue_declare(QUEUE, durable=True)
    channel.queue_bind(QUEUE, EXCHANGE, 'email')
    # Each retry queue dead-letters to the main queue after its TTL. The worker routes
    # failures to the next one and the third failure to the dead-letter exchange.
    for attempt, ttl in ((1, 1000), (2, 5000), (3, 15000)):
        name = f'email.retry.{attempt}'
        channel.queue_declare(name, durable=True, arguments={
            'x-message-ttl': ttl, 'x-dead-letter-exchange': EXCHANGE,
            'x-dead-letter-routing-key': 'email',
        })

def publish(payload: dict):
    connection = _connection()
    try:
        channel = connection.channel(); declare(channel); channel.confirm_delivery()
        channel.basic_publish(EXCHANGE, 'email', json.dumps(payload, default=str).encode('utf-8'),
            properties=pika.BasicProperties(delivery_mode=2, content_type='application/json'))
    finally:
        connection.close()

def enqueue_in_transaction(db, event_type: str, payload: dict):
    db.add(OutboxEvent(event_type=event_type, payload=json.dumps(payload, default=str)))

def dispatch_outbox(limit=100):
    """Best-effort publisher. Rows stay pending on any broker failure."""
    db = SessionLocal()
    try:
        rows = db.scalars(select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id).limit(limit)).all()
        for row in rows:
            try:
                publish(json.loads(row.payload))
                row.published_at = datetime.utcnow()
                row.attempts += 1
                db.commit()
                log.info('Published outbox event %s', row.id)
            except Exception:
                row.attempts += 1; db.commit()
                log.warning('RabbitMQ unavailable; outbox event %s remains pending', row.id, exc_info=True)
                break
        return len(rows)
    finally:
        db.close()
