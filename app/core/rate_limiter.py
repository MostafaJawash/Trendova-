from abc import ABC, abstractmethod
from collections import defaultdict
from threading import RLock
from time import monotonic

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
