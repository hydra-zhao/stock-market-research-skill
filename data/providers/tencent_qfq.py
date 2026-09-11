"""Tencent qfq history provider for the swing precision layer.

This capability is intentionally separate from the legacy case-library caller:
the registry owns its request window, cutoff, completeness status and
provenance.  It is not a fallback for ``pattern_history`` or the pattern-edge
Eastmoney contract.
"""
from __future__ import annotations

from typing import Any

from .base import Provider
from .models import DataResult, ProviderIdentity

CAPABILITY = "swing_qfq_history"
PROVIDER_VERSION = "tencent_qfq_v1"
PROVIDER_FAMILY = "tencent_family"
DEFAULT_MIN_ROWS = 120
DEFAULT_WINDOW = 380


class TencentQfqProvider(Provider):
    identity = ProviderIdentity("tencent", PROVIDER_FAMILY)

    def supports(self, capability: str) -> bool:
        return capability == CAPABILITY

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if capability != CAPABILITY:
            return self._failure(capability, "not_supported",
                                 f"tencent 不支持 capability={capability}")

        code = str(params.get("code") or "").strip()
        if not code:
            return self._failure(capability, "unavailable", "缺少股票代码")
        try:
            count = max(1, int(params.get("count") or DEFAULT_WINDOW))
            min_rows = max(1, int(params.get("min_rows") or DEFAULT_MIN_ROWS))
        except (TypeError, ValueError) as exc:
            return self._failure(capability, "incomplete", f"窗口参数非法: {exc}")

        cutoff = str(params.get("cutoff") or "").strip()
        start = str(params.get("start") or "").strip()
        end = str(params.get("end") or cutoff).strip()
        try:
            from case_lib import fetch_tencent_kline

            bars = fetch_tencent_kline(code, "day", start=start, end=end,
                                       count=count)
        except Exception as exc:  # provider boundary: preserve typed result
            return self._failure(capability, "unavailable",
                                 f"腾讯前复权日K不可用: {type(exc).__name__}: {exc}",
                                 code=code, requested_rows=count,
                                 required_rows=min_rows, cutoff=cutoff)

        rows = list(bars or [])
        dates = [str(row.get("date") or "") for row in rows
                 if isinstance(row, dict)]
        valid_dates = bool(rows) and len(dates) == len(rows) and all(dates)
        unique_dates = len(set(dates)) == len(dates)
        ordered = dates == sorted(dates)
        def _positive(row: Any) -> bool:
            if not isinstance(row, dict):
                return False
            try:
                values = [row.get(field) for field in ("open", "close", "high", "low")]
                return all(value is not None and float(value) > 0 for value in values)
            except (TypeError, ValueError):
                return False

        positive_prices = bool(rows) and all(_positive(row) for row in rows)
        complete = (len(rows) >= min_rows and valid_dates and unique_dates
                    and ordered and positive_prices)
        status = "ok" if complete else "incomplete"
        as_of = dates[-1] if dates and ordered else None
        metadata = {
            "provider_version": PROVIDER_VERSION,
            "provider_used": self.identity.name,
            "adjust_method": "qfq",
            "code": code,
            "requested_rows": count,
            "required_rows": min_rows,
            "rows": len(rows),
            "coverage": round(len(rows) / count, 6) if count else None,
            "cutoff": cutoff or None,
            "as_of": as_of,
            "completeness": {
                "min_rows": len(rows) >= min_rows,
                "valid_dates": valid_dates,
                "unique_dates": unique_dates,
                "ordered_dates": ordered,
                "positive_prices": positive_prices,
            },
            "lineage": "tencent_qfq_daily_k",
        }
        if not complete:
            metadata["incomplete_reason"] = "样本不足或序列完整性校验未通过"
        return DataResult(value=rows, source=self.identity.name,
                          provider_family=self.identity.family, as_of=as_of,
                          status=status, capability=capability,
                          metadata=metadata)

    def _failure(self, capability: str, status: str, error: str,
                 **meta: Any) -> DataResult:
        metadata = {
            "provider_version": PROVIDER_VERSION,
            "provider_used": self.identity.name,
            "adjust_method": "qfq",
            "lineage": "tencent_qfq_daily_k",
            "rows": 0,
            "coverage": 0.0,
        }
        metadata.update(meta)
        as_of = metadata.get("as_of")
        if not isinstance(as_of, str):
            as_of = None
        return DataResult(value=None, source=self.identity.name,
                          provider_family=self.identity.family,
                          as_of=as_of, status=status,
                          capability=capability, error=error, metadata=metadata)
