"""Fuyao adapter for verified structured A-share capabilities."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from .base import Provider
from .errors import IncompleteIntraday, NotSupported, ProviderUnavailable, RateLimited, SchemaDrift
from .local_compute import resample_bars
from .models import DataResult, ProviderIdentity


class FuyaoProvider(Provider):
    identity = ProviderIdentity("fuyao", "ths_family")
    _supported = {
        "daily_k", "weekly_k", "monthly_k", "market_daily_dump", "limit_up_pool",
        "limit_down_pool", "limit_break_pool", "limit_ladder", "hotrank", "anomaly", "lhb",
    }

    def configured(self) -> bool:
        return bool(os.environ.get("FUYAO_API_KEY") or os.environ.get("HITHINK_FINANCE_API_KEY"))

    def supports(self, capability: str) -> bool:
        return capability in self._supported

    @staticmethod
    def _as_of(value: Any) -> str | None:
        if isinstance(value, list) and value:
            return str(value[-1].get("date") or value[-1].get("trade_date") or "") or None
        if isinstance(value, dict):
            return str(value.get("trade_date") or value.get("date") or value.get("timestamp") or "") or None
        return None

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if not self.supports(capability):
            raise NotSupported(f"fuyao does not implement {capability}")
        if not self.configured():
            if capability not in {"daily_k", "weekly_k", "monthly_k", "market_daily_dump"}:
                raise ProviderUnavailable("FUYAO_API_KEY 未设置")
            from sources.market_dump import DUMP_PATH
            if not DUMP_PATH.exists():
                raise ProviderUnavailable("FUYAO_API_KEY 未设置且无本地 dump 缓存")
        try:
            value = self._fetch(capability, **params)
        except Exception as exc:
            message = str(exc)
            if "4001" in message or "429" in message or "频率" in message:
                raise RateLimited(message) from exc
            if "列缺失" in message or "schema" in message.lower():
                raise SchemaDrift(message) from exc
            raise ProviderUnavailable(message) from exc
        status = "ok"
        metadata: dict[str, Any] = {"schema_version": "fuyao-v1"}
        if capability in {"weekly_k", "monthly_k"}:
            metadata.update({
                "derived": True,
                "derived_from": {
                    "capability": "daily_k",
                    "source": self.identity.name,
                    "provider_family": self.identity.family,
                },
                "derivation": f"local_resample_{capability}",
            })
        if params.get("include_today") and _is_intraday(params.get("now")):
            status = "incomplete"
            metadata["raw_status"] = IncompleteIntraday.status
        as_of = (self._as_of(value) or params.get("date") or
                 datetime.now().astimezone().isoformat(timespec="seconds"))
        return DataResult(value=value, source=self.identity.name,
                          provider_family=self.identity.family, as_of=str(as_of),
                          status=status, capability=capability, metadata=metadata)

    def _fetch(self, capability: str, **params: Any) -> Any:
        from sources import hithink_runner as ht
        from sources import market_dump

        if capability in {"daily_k", "weekly_k", "monthly_k"}:
            bars = market_dump.stock_bars(params["code"],
                                          days=int(params.get("days") or (5000 if params.get("start") else 500)),
                                          include_today=bool(params.get("include_today", False)),
                                          now=params.get("now"))
            start, end = params.get("start"), params.get("end")
            bars = [b for b in bars if (not start or b["date"] >= start) and (not end or b["date"] <= end)]
            if capability == "weekly_k":
                return resample_bars(bars, "weekly")
            if capability == "monthly_k":
                return resample_bars(bars, "monthly")
            return bars
        if capability == "market_daily_dump":
            exact = params.get("date")
            return market_dump.frame(start=exact or params.get("start"), end=exact or params.get("end"),
                                     include_today=bool(params.get("include_today", False)),
                                     now=params.get("now"))
        if capability in {"limit_up_pool", "limit_down_pool", "limit_break_pool"}:
            kind = {"limit_up_pool": "up", "limit_down_pool": "down",
                    "limit_break_pool": "break"}[capability]
            total, items = ht._fetch_all_pages(ht.HT_POOL_PATHS[kind], params.get("date"))
            return {"total": total, "items": items}
        if capability == "limit_ladder":
            return ht.ht_get("/api/a-share/special-data/limit-up-ladder").get("data", {})
        if capability == "hotrank":
            rank_size = int(params.get("rank_size") or 30)
            # The upstream endpoint currently returns its default page even when
            # a smaller rank_size is requested. Keep our provider contract exact.
            return ht.fetch_hot_list(rank_size)[:rank_size]
        if capability == "anomaly":
            return ht.fetch_anomaly_list(params.get("date"))
        if capability == "lhb":
            date = params.get("date") or datetime.now().strftime("%Y-%m-%d")
            return ht.ht_get("/api/a-share/special-data/dragon-tiger-list",
                             {"date": date, "board_type": params.get("board_type", "all")}).get("data", {})
        raise NotSupported(capability)


def _is_intraday(now=None) -> bool:
    from common.calendar import is_intraday
    return is_intraday(now)
