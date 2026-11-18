"""Email worker: ack only after SMTP success, retry with delayed queues, then DLQ."""
import json
import logging
import smtplib
import time
from email.message import EmailMessage
import pika
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.database import SessionLocal
import app.core.model_registry  # register relationship targets for the standalone worker
from app.core.queue import EXCHANGE, DLX, QUEUE, declare
from app.modules.orders.models import SentEmail

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger(__name__)

def send_email(payload):
    message = EmailMessage(); message['From'] = settings.smtp_from; message['To'] = payload['recipient']; message['Subject'] = f"Order #{payload['order']['id']} {payload['kind']}"
    order = payload['order']; items = '\n'.join(f"- {x['product_name']} x{x['quantity']}: {x['subtotal']}" for x in order['items'])
    message.set_content(f"Order #{order['id']} is {order['status']}.\nTotal: {order['total_amount']}\nItems:\n{items}")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as smtp:
        if settings.smtp_starttls: smtp.starttls()
        if settings.smtp_user: smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)

def already_sent(payload):
    db = SessionLocal()
    try:
        marker = SentEmail(order_id=payload['order']['id'], kind=payload['kind']); db.add(marker); db.commit(); return False
    except IntegrityError:
        db.rollback(); return True
    finally: db.close()

def callback(channel, method, properties, body):
    payload = json.loads(body)
    if already_sent(payload):
        log.info('Duplicate email ignored order=%s kind=%s', payload['order']['id'], payload['kind']); channel.basic_ack(method.delivery_tag); return
    try:
        send_email(payload); log.info('Email sent order=%s kind=%s', payload['order']['id'], payload['kind']); channel.basic_ack(method.delivery_tag)
    except Exception:
        # Marker is removed so another delivery may make the actual send attempt.
        db = SessionLocal(); db.query(SentEmail).filter_by(order_id=payload['order']['id'], kind=payload['kind']).delete(); db.commit(); db.close()
        attempt = int(payload.get('attempt', 0)) + 1
        if attempt >= 3:
            channel.basic_publish(DLX, 'dead', body, properties=pika.BasicProperties(delivery_mode=2)); log.exception('Email moved to DLQ')
        else:
            payload['attempt'] = attempt
            channel.basic_publish('', f'email.retry.{attempt}', json.dumps(payload).encode(), properties=pika.BasicProperties(delivery_mode=2)); log.exception('Email failed; scheduled retry %s', attempt)
        channel.basic_ack(method.delivery_tag)

def main():
    while True:
        try:
            connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url)); channel = connection.channel(); declare(channel); channel.basic_qos(prefetch_count=1); channel.basic_consume(QUEUE, callback, auto_ack=False)
            log.info('Email worker consuming %s', QUEUE); channel.start_consuming()
        except Exception:
            log.exception('RabbitMQ connection/consumer failed; retrying in 2 seconds')
            time.sleep(2)
if __name__ == '__main__': main()
