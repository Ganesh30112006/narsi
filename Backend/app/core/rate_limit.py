"""In-process sliding-window rate limiter.

Suitable for a single API process. When running several API instances, enforce the same limits at a
shared layer (reverse proxy / API gateway) — this limiter is per-process by design (no Redis dependency).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque


def parse_rate(spec: str) -> tuple[int, float]:
    """ "10/60" → (10 requests, 60 seconds)."""
    count, _, window = spec.partition("/")
    return int(count), float(window or 60)


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, spec: str) -> int | None:
        """Records a hit. Returns None if allowed, else seconds until the next request is allowed."""
        limit, window = parse_rate(spec)
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, math.ceil(hits[0] + window - now))
            hits.append(now)
            if len(self._hits) > 50_000:  # bound memory under key-spraying
                self._evict(now - window)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, cutoff: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]


limiter = RateLimiter()
