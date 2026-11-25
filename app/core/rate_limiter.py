from abc import ABC, abstractmethod
from collections import defaultdict
from threading import RLock
from time import monotonic
from app.core import redis as rds
from app.core.config import settings

class RateLimiter(ABC):
    @abstractmethod
    def retry_after(self, key): ...
    @abstractmethod
    def failed(self, key): ...
    @abstractmethod
    def clear(self, key): ...

class InMemoryRateLimiter(RateLimiter):
    def __init__(self, max_attempts=5, window=900):
        self.max_attempts, self.window = max_attempts, window
        self.entries = defaultdict(list)
        self.lock = RLock()
    def retry_after(self, key):
        with self.lock:
            now = monotonic()
            self.entries[key] = [t for t in self.entries[key] if now-t < self.window]
            return max(1, int(self.window - (now-self.entries[key][0]))) if len(self.entries[key]) >= self.max_attempts else 0
    def failed(self, key):
        with self.lock: self.entries[key].append(monotonic())
    def clear(self, key):
        with self.lock: self.entries.pop(key, None)

limiter = InMemoryRateLimiter()


class RedisRateLimiter(RateLimiter):
    """Shared fixed-window login limiter; falls back safely to the test/local limiter.

    Redis is deliberately the authority whenever configured so attempts made via
    different app replicas cannot bypass a process-local dictionary.
    """
    def __init__(self, fallback, max_attempts=5, window=900):
        self.fallback, self.max_attempts, self.window = fallback, max_attempts, window

    def _key(self, value):
        import hashlib
        return rds.key('login-limit:' + hashlib.sha256(repr(value).encode()).hexdigest())

    def retry_after(self, value):
        if not settings.redis_login_limiter or not rds.get_redis(): return self.fallback.retry_after(value)
        key = self._key(value)
        count = rds.call('get', key, default=None)
        if count is None: return 0
        if int(count) < self.max_attempts: return 0
        ttl = rds.call('ttl', key, default=None)
        return max(1, int(ttl or 1))

    def failed(self, value):
        if not settings.redis_login_limiter or not rds.get_redis(): return self.fallback.failed(value)
        key = self._key(value)
        count = rds.call('incr', key, default=None)
        if count == 1: rds.call('expire', key, self.window, default=None)

    def clear(self, value):
        if not settings.redis_login_limiter or not rds.get_redis(): return self.fallback.clear(value)
        rds.call('delete', self._key(value), default=None)


shared_limiter = RedisRateLimiter(limiter)
