"""Minimal provider protocol. Business code depends on this, not API details."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import DataResult, ProviderIdentity


class Provider(ABC):
    identity: ProviderIdentity

    @abstractmethod
    def fetch(self, capability: str, **params: Any) -> DataResult:
        raise NotImplementedError

    def configured(self) -> bool:
        return True

    def supports(self, capability: str) -> bool:
        return True
