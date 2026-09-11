"""Typed provider failures used by the routing layer."""


class ProviderError(RuntimeError):
    status = "unavailable"


class ProviderUnavailable(ProviderError):
    status = "unavailable"


class QuotaExceeded(ProviderError):
    status = "quota_exhausted"


class RateLimited(ProviderError):
    status = "rate_limited"


class SchemaDrift(ProviderError):
    status = "schema_drift"


class DataStale(ProviderError):
    status = "stale"


class IncompleteIntraday(ProviderError):
    status = "incomplete_intraday"


class NotSupported(ProviderError):
    status = "not_supported"


class RiskVerificationFailed(ProviderError):
    status = "unverified"
