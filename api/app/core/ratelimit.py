"""Login throttling: a sliding window of failed attempts per account and per client.

In memory, which is right for a single-process prototype; a multi-worker deployment
would back the same interface with Redis. Only *failures* count, so a user who signs in
correctly is never slowed down, and a success clears that account's window.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.config import settings


class LoginThrottle:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _keys(username: str, client: str) -> tuple[str, str]:
        return f"user:{username.strip().lower()}", f"client:{client}"

    def _prune(self, key: str, now: float) -> deque[float]:
        window = self._failures[key]
        horizon = now - settings.login_window_seconds
        while window and window[0] <= horizon:
            window.popleft()
        return window

    def retry_after(self, username: str, client: str) -> int:
        """Seconds until another attempt is allowed; 0 when the caller may try now."""
        now = time.monotonic()
        user_key, client_key = self._keys(username, client)
        limits = (
            (user_key, settings.login_max_failures_per_account),
            (client_key, settings.login_max_failures_per_client),
        )
        wait = 0.0
        with self._lock:
            for key, limit in limits:
                window = self._prune(key, now)
                if len(window) >= limit:
                    wait = max(wait, window[0] + settings.login_window_seconds - now)
        return int(wait) + 1 if wait > 0 else 0

    def record_failure(self, username: str, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in self._keys(username, client):
                self._failures[key].append(now)

    def record_success(self, username: str) -> None:
        user_key, _ = self._keys(username, "")
        with self._lock:
            self._failures.pop(user_key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()
