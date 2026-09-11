"""Compatibility adapters around existing IW/MX/THS/AK runners."""
from __future__ import annotations

import os
from typing import Any, Callable

from .base import Provider
from .errors import NotSupported, ProviderUnavailable, QuotaExceeded, RateLimited, SchemaDrift
from .models import DataResult, ProviderIdentity


class RunnerProvider(Provider):
    def __init__(self, name: str, family: str, runner: Callable[..., tuple], *, key: str | None = None):
        self.identity = ProviderIdentity(name, family)
        self._runner = runner
        self._key = key

    def configured(self) -> bool:
        return not self._key or bool(os.environ.get(self._key))

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if not self.configured():
            raise ProviderUnavailable(f"{self._key} 未设置")
        label = str(params.get("label") or capability)
        result = self._runner(label=label, capability=capability, params=params)
        _label, body, ok, _elapsed, src = result
        if not ok:
            low = str(body).lower()
            if "quota" in low or "额度" in low or "次数已用完" in low:
                raise QuotaExceeded(str(body))
            if "429" in low or "limit" in low:
                raise RateLimited(str(body))
            if "schema" in low or "列缺失" in low:
                raise SchemaDrift(str(body))
            raise ProviderUnavailable(str(body))
        return DataResult(value={"rendered": body}, source=src,
                          provider_family=self.identity.family,
                          status="ok", capability=capability)


def iw_runner(*, label: str, capability: str, params: dict[str, Any]):
    from sources.iwencai_runner import run_iw
    return run_iw(label, params.get("skill_id", "hithink-market-query"),
                  params.get("query", ""), int(params.get("limit") or 5))


def mx_runner(*, label: str, capability: str, params: dict[str, Any]):
    from sources.mx_runner import run_mx
    return run_mx(label, params.get("query", ""), int(params.get("limit") or 5))


def ths_runner(*, label: str, capability: str, params: dict[str, Any]):
    if capability in {"limit_up_pool", "limit_down_pool", "limit_break_pool", "limit_ladder"}:
        from sources.ths_limitup import run_ths_limitup
        kind = {"limit_up_pool": "zt_pool", "limit_down_pool": "dt_count",
                "limit_break_pool": "bomb_count", "limit_ladder": "ladder"}[capability]
        return run_ths_limitup(kind)
    if capability in {"daily_k", "weekly_k", "monthly_k"}:
        from sources.ths_line import run_ths_kline
        return run_ths_kline(f"{params.get('code', '')} {params.get('days', 60)}")
    if capability == "sector_fundflow":
        from sources.ths_fundflow import run_ths_fundflow
        return run_ths_fundflow(params.get("sector_kind", "industry"))
    raise NotSupported(capability)


def ak_runner(*, label: str, capability: str, params: dict[str, Any]):
    if capability in {"limit_up_pool", "limit_down_pool", "limit_break_pool", "limit_ladder"}:
        from sources.zt_pool_ak import run_akshare_ztpool
        kind = {"limit_up_pool": "zt_pool", "limit_down_pool": "dt_count",
                "limit_break_pool": "bomb_count", "limit_ladder": "promotion"}[capability]
        return run_akshare_ztpool(kind)
    if capability == "etf":
        from sources.etf_ak import run_akshare_etf
        return run_akshare_etf()
    raise NotSupported(capability)


def default_legacy_providers() -> dict[str, Provider]:
    return {
        "iwencai": RunnerProvider("iwencai", "ths_family", iw_runner, key="IWENCAI_API_KEY"),
        "mx": RunnerProvider("mx", "eastmoney_family", mx_runner, key="MX_APIKEY"),
        "ths_dataapi": RunnerProvider("ths_dataapi", "ths_family", ths_runner),
        "akshare_eastmoney": RunnerProvider("akshare_eastmoney", "eastmoney_family", ak_runner),
    }
