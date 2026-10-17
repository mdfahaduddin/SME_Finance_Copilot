"""Sliding-window rate limiter.

With REDIS_URL set, counts live in Redis (shared by every API worker and container). Without it, an
in-memory window is used, which is only correct for a single process (development and tests).
If Redis is unreachable at runtime the limiter fails open for that request and logs a warning, so an
outage of the cache never locks every user out.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app.config import get_settings

log = logging.getLogger("smecopilot.ratelimit")
_redis = None
_redis_checked = False


def _redis_client():
    global _redis, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        url = get_settings().redis_url
        if url:
            import redis
            _redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
    return _redis


class RateLimiter:
    def __init__(self, name: str, max_calls: int, window_seconds: float):
        self.name = name
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _deny(self, retry: int) -> None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down",
                            headers={"Retry-After": str(max(retry, 1))})

    def check(self, key: str) -> None:
        r = _redis_client()
        if r is not None:
            try:
                self._check_redis(r, key)
                return
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 - any Redis failure
                log.warning("Rate limiter: Redis unavailable, allowing request (%s)", self.name)
                return
        self._check_memory(key)

    def _check_memory(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                self._deny(int(self.window - (now - q[0])) + 1)
            q.append(now)

    def _check_redis(self, r, key: str) -> None:
        now = time.time()
        rk = f"rl:{self.name}:{key}"
        pipe = r.pipeline()
        pipe.zremrangebyscore(rk, 0, now - self.window)
        pipe.zcard(rk)
        pipe.zrange(rk, 0, 0, withscores=True)
        _, count, oldest = pipe.execute()
        if count >= self.max_calls:
            retry = int(self.window - (now - oldest[0][1])) + 1 if oldest else int(self.window)
            self._deny(retry)
        pipe = r.pipeline()
        pipe.zadd(rk, {f"{now}:{uuid.uuid4().hex[:8]}": now})
        pipe.expire(rk, int(self.window) + 1)
        pipe.execute()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter("login", max_calls=5, window_seconds=60)
register_limiter = RateLimiter("register", max_calls=5, window_seconds=3600)
recovery_limiter = RateLimiter("recovery", max_calls=5, window_seconds=900)
mfa_limiter = RateLimiter("mfa", max_calls=5, window_seconds=60)
action_limiter = RateLimiter("action", max_calls=20, window_seconds=60)
chat_limiter = RateLimiter("chat", max_calls=20, window_seconds=60)
import_limiter = RateLimiter("import", max_calls=10, window_seconds=300)

ALL_LIMITERS = [login_limiter, register_limiter, recovery_limiter, mfa_limiter, action_limiter, chat_limiter,
                import_limiter]
