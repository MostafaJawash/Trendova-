"""Redis cache-aside helpers (Requirement 3). Everything is fail-open: a Redis problem means "serve from the DB".

Keys (all prefixed `trendova:` by app.core.redis):
  products:ver                         integer namespace version; any product/category mutation does INCR (O(1) invalidation)
  products:list:v{N}:{hash(params)}    one list page (envelope: etag NL ids NL body), TTL ~60 s +-10 %
  products:detail:{id}                 STATIC part of a product (name, description, price, category), TTL ~300 s +-10 %
  lock:products:...                    SET NX PX 5000 stampede lock
Never cached: stock, orders, favorites, anything user-specific, auth data.
"""
import hashlib
import json
import logging
import random
import threading
import time
from app.core import redis as rds
from app.core.config import settings

log = logging.getLogger(__name__)
_ERR = object()          # sentinel: Redis could not be asked (distinct from "key missing" = None)
_lock = threading.Lock()
STATS = {'hit': 0, 'miss': 0, 'bypass': 0, 'fills': 0, 'stampede_waits': 0, 'stampede_fallthrough': 0, 'invalidations': 0, 'errors': 0}
_pending_ver = False     # an INCR that failed (Redis down) and must be retried before the next cache read
_pending_detail = set()  # detail keys whose DELETE failed


def stat(name, n=1):
    with _lock:
        STATS[name] += n


def stats():
    with _lock:
        s = dict(STATS)
    total = s['hit'] + s['miss']
    s['hit_ratio'] = round(s['hit'] / total, 4) if total else None
    return s


def reset_stats():
    with _lock:
        for k in STATS:
            STATS[k] = 0


def enabled():
    return bool(settings.cache_enabled and settings.redis_url)


def jitter(ttl):
    return max(1, int(round(ttl * (1 + random.uniform(-settings.cache_ttl_jitter, settings.cache_ttl_jitter)))))


def etag_of(body: bytes):
    """Strong ETag = hash of the EXACT response body bytes."""
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def params_hash(params: dict):
    return hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:24]


# ---------------- invalidation (call AFTER the DB commit succeeded) ----------------
def _flush_pending():
    global _pending_ver
    if _pending_ver and rds.call('incr', rds.key('products:ver'), default=_ERR) is not _ERR:
        _pending_ver = False
    for k in list(_pending_detail):
        if rds.call('delete', k, default=_ERR) is not _ERR:
            _pending_detail.discard(k)


def invalidate_products(product_id=None):
    """Product or category changed: new list namespace (INCR products:ver) and drop the detail key. No KEYS/SCAN."""
    global _pending_ver
    if not enabled():
        return
    stat('invalidations')
    if rds.call('incr', rds.key('products:ver'), default=_ERR) is _ERR:
        _pending_ver = True       # retried on the next cache access once Redis is back
    if product_id is not None:
        k = rds.key(f'products:detail:{product_id}')
        if rds.call('delete', k, default=_ERR) is _ERR:
            _pending_detail.add(k)


def catver():
    """Category-mutation counter. Detail entries remember the value they were built under (a category rename changes
    the category name inside every detail of that category, and we cannot enumerate those keys)."""
    v = rds.call('get', rds.key('products:catver'), default=None)
    return int(v) if v is not None else 0


def invalidate_categories():
    """Category created/renamed/deleted (call after commit): new list namespace AND every cached detail becomes invalid."""
    global _pending_ver
    if not enabled():
        return
    invalidate_products()
    rds.call('incr', rds.key('products:catver'), default=None)


def list_version():
    v = rds.call('get', rds.key('products:ver'), default=_ERR)
    if v is _ERR:
        return None
    return int(v) if v is not None else 0   # missing -> 0, so the first INCR (=1) always changes the namespace


# ---------------- get-or-fill with stampede protection ----------------
def get_or_fill(key, ttl, build, valid=None):
    """-> (bytes, 'HIT'|'MISS'|'BYPASS'). `build()` returns the bytes to cache (called by exactly one request per
    cold key; losers wait briefly for the winner, then fall through to the DB themselves). Empty bytes are never
    cached (used for "not found"). `valid(raw)` may reject an entry that is no longer current (treated as a miss)."""
    if _pending_ver or _pending_detail:
        _flush_pending()
    raw = rds.call('get', key, default=_ERR)
    if raw is _ERR:
        stat('bypass'); stat('errors')
        return build(), 'BYPASS'
    if raw is not None and (valid is None or valid(raw)):
        stat('hit')
        return raw, 'HIT'
    lock_key = key.replace('trendova:', 'trendova:lock:', 1)
    got = rds.call('set', lock_key, 1, nx=True, px=settings.cache_lock_ms, default=_ERR)
    if got is _ERR:
        stat('bypass'); stat('errors')
        return build(), 'BYPASS'
    if got:  # winner: fill, then release the lock
        try:
            stat('miss'); stat('fills')
            data = build()
            if data:
                rds.call('set', key, data, ex=ttl, default=None)
            return data, 'MISS'
        finally:
            rds.call('delete', lock_key, default=None)
    # loser: wait briefly for the winner's fill
    stat('stampede_waits')
    deadline = time.monotonic() + settings.cache_wait_ms / 1000
    while time.monotonic() < deadline:
        time.sleep(0.02)
        raw = rds.call('get', key, default=_ERR)
        if raw is _ERR:
            break
        if raw is not None and (valid is None or valid(raw)):
            stat('hit')
            return raw, 'HIT'
    stat('stampede_fallthrough'); stat('miss'); stat('fills')
    return build(), 'MISS'


# ---------------- list envelope: etag NL comma-separated product ids NL body ----------------
def pack(etag: str, ids, body: bytes) -> bytes:
    return etag.encode() + b'\n' + ','.join(str(i) for i in ids).encode() + b'\n' + body


def unpack(raw: bytes):
    etag, ids, body = raw.split(b'\n', 2)
    return etag.decode(), [int(x) for x in ids.split(b',') if x], body
