"""
Simple in-process TTL cache.
Keys are arbitrary strings; values are (data, expiry_timestamp).
Thread-safe enough for single-process uvicorn deployments.
"""
import time
from threading import Lock
from typing import Any, Optional

_store: dict[str, tuple[Any, float]] = {}
_lock = Lock()

# TTLs in seconds
TTL_QUOTES = 60
TTL_HISTORICAL = 900
TTL_FX = 300
TTL_FUNDAMENTALS = 3600
TTL_RFR = 86400
TTL_FRONTIER = 900


def get(key: str) -> Optional[Any]:
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        data, expiry = entry
        if time.time() > expiry:
            del _store[key]
            return None
        return data


def set(key: str, value: Any, ttl: int) -> None:
    with _lock:
        _store[key] = (value, time.time() + ttl)


def delete(key: str) -> None:
    with _lock:
        _store.pop(key, None)


def clear_prefix(prefix: str) -> None:
    with _lock:
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            del _store[k]
