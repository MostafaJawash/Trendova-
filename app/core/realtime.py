"""Pusher HTTP API client. Publishing is deliberately fail-open."""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from app.core.config import settings

log = logging.getLogger(__name__)

def publish(channel: str, event: str, payload: dict):
    try:
        body = json.dumps({'name': event, 'channels': [channel], 'data': json.dumps(payload, default=str)}, separators=(',', ':')).encode()
        timestamp = str(int(time.time()))
        params = {'auth_key': settings.pusher_key, 'auth_timestamp': timestamp, 'auth_version': '1.0', 'body_md5': hashlib.md5(body).hexdigest()}
        query = urlencode(sorted(params.items()))
        path = f'/apps/{settings.pusher_app_id}/events'
        signature = hmac.new(settings.pusher_secret.encode(), f'POST\n{path}\n{query}'.encode(), hashlib.sha256).hexdigest()
        url = f'{settings.pusher_scheme}://{settings.pusher_host}:{settings.pusher_port}{path}?{query}&auth_signature={signature}'
        with urlopen(Request(url, body, {'Content-Type': 'application/json'}), timeout=1.5) as response:
            response.read()
    except Exception:
        log.warning('Real-time publish failed for %s; request remains successful', event, exc_info=True)
