"""Bounded, process-local admission controls; no database or network access."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
import time


@dataclass
class _Bucket:
    tokens: float
    touched: float


class TokenBuckets:
    """Reject new identities when full rather than evicting active limits."""

    def __init__(self, rate: float, burst: int, capacity: int = 8192):
        if rate <= 0 or burst < 1 or capacity < 1:
            raise ValueError("Traffic limits must be positive")
        self.rate, self.burst, self.capacity = rate, burst, capacity
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, identity: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            # Fully refilled idle buckets can be forgotten without granting a bypass.
            expiry = self.burst / self.rate
            while self._buckets:
                first = next(iter(self._buckets))
                if now - self._buckets[first].touched < expiry:
                    break
                self._buckets.popitem(last=False)
            bucket = self._buckets.get(identity)
            if bucket is None:
                if len(self._buckets) >= self.capacity:
                    return False
                bucket = _Bucket(float(self.burst), now)
                self._buckets[identity] = bucket
            bucket.tokens = min(self.burst, bucket.tokens + max(0, now - bucket.touched) * self.rate)
            bucket.touched = now
            self._buckets.move_to_end(identity)
            if bucket.tokens < 1:
                return False
            bucket.tokens -= 1
            return True


class TTLCache:
    """Thread-safe TTL/LRU cache with a hard entry bound."""

    def __init__(self, ttl: float, capacity: int = 256):
        self.ttl, self.capacity = ttl, capacity
        self._items: OrderedDict[str, tuple[object, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if expiry <= time.monotonic():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: str, value: object) -> None:
        with self._lock:
            now = time.monotonic()
            for expired in [k for k, (_, expiry) in self._items.items() if expiry <= now]:
                del self._items[expired]
            self._items[key] = (value, now + self.ttl)
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)
