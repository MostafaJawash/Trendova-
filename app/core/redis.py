"""Redis access (sync redis-py). Every call is fail-open: a Redis error or timeout never raises to the caller.

* keys are prefixed `trendova:`
* 150 ms connect/socket timeouts (REDIS settings) so a dead Redis costs at most one short stall per call;
  after a failure a short circuit breaker skips Redis for a moment instead of stalling every request.
"""
import logging
import time
from app.core.config import settings

log = logging.getLogger(__name__)
PREFIX = 'trendova:'
BREAKER_SECONDS = 2.0
_client = None
_down_until = 0.0

def key(name):
    return PREFIX + name

def _make_client():
    import redis
    return redis.Redis.from_url(settings.redis_url, socket_timeout=settings.redis_timeout_seconds,
                                socket_connect_timeout=settings.redis_timeout_seconds, health_check_interval=0)

def get_redis():
    """Return the shared client, or None when Redis is not configured or is in the breaker window."""
    global _client
    if not settings.redis_url or time.monotonic() < _down_until:
        return None
    if _client is None:
        _client = _make_client()
    return _client

def set_client(client):
    """Tests: inject a fake client (None restores the real one)."""
    global _client, _down_until
    _client = client; _down_until = 0.0

def _failed(op, exc):
    global _down_until
    _down_until = time.monotonic() + BREAKER_SECONDS
    log.warning('Redis %s failed (%s: %s); falling back to the database', op, type(exc).__name__, exc)

def call(op, *args, default=None, **kwargs):
    """Run one Redis command; return `default` on any error (fail-open)."""
    r = get_redis()
    if r is None:
        return default
    try:
        return getattr(r, op)(*args, **kwargs)
    except Exception as exc:  # redis.RedisError, OSError, timeouts
        _failed(op, exc)
        return default

def ping():
    r = get_redis()
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception as exc:
        _failed('ping', exc)
        return False

# ---------------- read-your-writes markers ----------------
def mark_written(user_id=None, products=False):
    """After a SUCCESSFUL commit: reads by this user go to the primary for RYW_WINDOW_SECONDS.
    `products=True` also sets a global marker so product search (replica) falls back to the primary."""
    if not settings.use_read_replica:
        return
    ttl = settings.ryw_window_seconds
    if user_id is not None:
        call('set', key(f'ryw:{user_id}'), 1, ex=ttl)
    if products:
        call('set', key('ryw:products'), 1, ex=ttl)

def has_marker(user_id=None, products=False):
    """True when a marker exists (or Redis cannot be asked -> the caller must then use the primary)."""
    r = get_redis()
    if r is None:
        return True
    names = []
    if user_id is not None:
        names.append(key(f'ryw:{user_id}'))
    if products:
        names.append(key('ryw:products'))
    if not names:
        return False
    try:
        return any(v is not None for v in r.mget(names))
    except Exception as exc:
        _failed('mget', exc)
        return True
