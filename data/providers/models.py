"""Stable data and provenance contracts shared by every provider."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")

PUBLIC_STATUSES = {"ok", "degraded", "stale", "unverified", "unavailable", "incomplete"}
ERROR_STATUSES = {
    "not_supported", "quota_exhausted", "rate_limited", "schema_drift",
    "incomplete_intraday",
}


@dataclass
class DataResult(Generic[T]):
    value: T | None
    source: str
    provider_family: str
    as_of: str | None = None
    status: str = "ok"
    fallback_from: str | None = None
    capability: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """Whether callers may consume this result as complete data.

        ``incomplete`` is deliberately excluded.  Providers may still return a
        partial value for diagnostics, but statistics and hard-gate callers
        must opt into such a value explicitly instead of inheriting a
        fail-open default from the common contract.
        """
        return self.value is not None and self.status in {"ok", "degraded", "stale"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderIdentity:
    name: str
    family: str
