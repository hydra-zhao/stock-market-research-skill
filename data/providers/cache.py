"""Small provider cache with complete/partial-day aware keys."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


def cache_key(provider: str, capability: str, *, schema_version: str = "1",
              partial: bool = False, **params: Any) -> str:
    payload = {
        "provider": provider, "capability": capability, "schema_version": schema_version,
        "partial": bool(partial), "params": params,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    expires: float
    value: Any


class MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, _Entry] = {}

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        if item.expires < time.time():
            self._items.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._items[key] = _Entry(time.time() + max(0, int(ttl)), value)

    def clear(self) -> None:
        self._items.clear()
