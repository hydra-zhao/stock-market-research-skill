"""Capability-driven routing: the only source-priority truth for new data paths."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .base import Provider
from .cache import MemoryCache, cache_key
from .errors import ProviderError, SchemaDrift
from .fuyao import FuyaoProvider
from .models import DataResult
from .risk_official import RiskOfficialProvider

VALID_MODES = {"legacy", "hybrid", "fuyao_primary"}


def data_mode() -> str:
    mode = os.environ.get("STOCK_DATA_MODE", "hybrid").strip().lower()
    return mode if mode in VALID_MODES else "hybrid"


def load_matrix(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else Path(__file__).with_name("capabilities.yaml")
    return json.loads(target.read_text(encoding="utf-8"))


class ProviderRegistry:
    def __init__(self, matrix: dict[str, Any] | None = None,
                 providers: dict[str, Provider] | None = None, mode: str | None = None) -> None:
        self.matrix = matrix or load_matrix()
        self.mode = mode or data_mode()
        self.providers = providers or self._defaults()
        self.cache = MemoryCache()
        self.schema_drifts: dict[tuple[str, str], int] = {}
        self.disabled: set[tuple[str, str]] = set()

    @staticmethod
    def _defaults() -> dict[str, Provider]:
        from .ak import AkProvider
        from .eastmoney_qfq import EastmoneyQfqProvider
        from .iwencai import IwencaiProvider
        from .jin10 import Jin10Provider
        from .mx import MxProvider
        from .tencent_qfq import TencentQfqProvider
        from .ths import ThsProvider
        return {"fuyao": FuyaoProvider(), "iwencai": IwencaiProvider(),
                "mx": MxProvider(), "ths_dataapi": ThsProvider(),
                "akshare_eastmoney": AkProvider(), "jin10": Jin10Provider(),
                "risk_official": RiskOfficialProvider(),
                "eastmoney_qfq": EastmoneyQfqProvider(),
                "tencent": TencentQfqProvider()}

    def config(self, capability: str) -> dict[str, Any]:
        try:
            return self.matrix["capabilities"][capability]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability}") from exc

    def experimental_providers(self, capability: str) -> set[str]:
        """本能力声明为 experimental 的 provider 名单（唯一事实源=capabilities.yaml）。

        旧实现把门禁写成 `capability == "swing_qfq_history"` 硬编码：新增
        experimental 能力时门禁自动失效（改名/换源即静默放行），且审计脚本读不出
        "谁被 experimental 挡着"。改读能力配置的 `experimental_providers` 后，
        门禁、健康检查与文档声明同源。未声明的能力返回空集（=无门禁）。
        """
        return set(self.config(capability).get("experimental_providers", []))

    def order(self, capability: str, *, allow_experimental: bool = False) -> list[str]:
        cfg = self.config(capability)
        primary = cfg["primary"]
        if primary == "fuyao":
            requested = os.environ.get("STOCK_PRIMARY_A_SHARE_SOURCE", "fuyao").strip()
            if requested in self.providers:
                primary = requested
        normal = [primary, *cfg.get("fallback", [])]
        # ``candidate`` and ``disabled`` are governance states, not comments.
        # Neither may silently become an active route when a matrix entry is
        # edited or when a fallback is added later.
        blocked = set(cfg.get("candidate", [])) | set(cfg.get("disabled", []))
        if not allow_experimental:
            # experimental provider 默认不进任何路由（与 candidate/disabled 同级），
            # 只有调用方显式 allow_experimental 才参与。
            blocked |= self.experimental_providers(capability)
        normal = [name for name in normal if name not in blocked]
        if self.mode != "legacy":
            return list(dict.fromkeys(normal))
        legacy = [p for p in normal if p != "fuyao"]
        return list(dict.fromkeys(legacy or normal))

    def route(self, capability: str, **params: Any) -> DataResult:
        cfg = self.config(capability)
        route_params = dict(params)
        # experimental provider 只能由明确的局部调用方 opt-in；默认路由不把
        # 它当作正式 arbitration 来源。该标志不会传入 provider。
        allow_experimental = bool(route_params.pop("allow_experimental", False))
        experimental = self.experimental_providers(capability)
        # primary 就是 experimental 源且未 opt-in → 整条能力不可用（fail-closed，
        # 不静默降级到别的源）。旧实现在此硬编码 capability 名，现由配置声明。
        if cfg.get("primary") in experimental and not allow_experimental:
            return DataResult(
                value=None, source="none", provider_family="none",
                status="not_supported", capability=capability,
                error="experimental provider requires explicit allow_experimental",
                metadata={"raw_status": "experimental_blocked",
                          "active_order": [], "route_failures": []})
        # Keep the edge qfq cache identity complete even when callers omit
        # defaults: the cutoff is the last completed trading day, and the
        # adjustment/provider version are part of the production contract.
        if capability in {"pattern_edge_history", "pattern_edge_index_history",
                          "swing_qfq_history"}:
            from common.calendar import completed_day
            route_params.setdefault("cutoff", completed_day())
            route_params.setdefault(
                "adjust_method",
                "raw" if capability == "pattern_edge_index_history" else "qfq")
            route_params.setdefault("provider_version",
                                    str(cfg.get("provider_version", "1")))
        if capability == "swing_qfq_history":
            route_params.setdefault("count", int(cfg.get("window", 380)))
            route_params.setdefault("min_rows", int(cfg.get("min_rows", 120)))
        failures: list[tuple[str, str, str]] = []
        cfg_routes = [cfg.get("primary"), *cfg.get("fallback", [])]
        blocked = set(cfg.get("candidate", [])) | set(cfg.get("disabled", []))
        for name in dict.fromkeys(x for x in cfg_routes if x in blocked):
            failures.append((name, "not_supported",
                             "provider is candidate/disabled and cannot be active"))
        if not allow_experimental:
            # 非 primary 的 experimental 源同样不进本轮路由（recorded 为失败原因，
            # 与 candidate/disabled 同形，便于审计本轮为何没走它）。
            for name in dict.fromkeys(x for x in cfg_routes if x in experimental):
                failures.append((name, "not_supported",
                                 "experimental provider requires explicit allow_experimental"))
        ordered = self.order(capability, allow_experimental=allow_experimental)
        if not ordered:
            status = failures[-1][1] if failures else "unavailable"
            return DataResult(value=None, source="none", provider_family="none", status=status,
                              capability=capability,
                              error=failures[-1][2] if failures else "no active provider",
                              metadata={"raw_status": status, "route_failures": failures,
                                        "active_order": []})
        first = cfg.get("primary")
        if first == "fuyao":
            requested = os.environ.get("STOCK_PRIMARY_A_SHARE_SOURCE", "fuyao").strip()
            if requested in self.providers:
                first = requested
        # Legacy mode intentionally skips an active Fuyao primary, but a
        # candidate/disabled primary remains the recorded fallback cause.
        if self.mode == "legacy" and first == "fuyao" and first not in blocked:
            first = ordered[0]
        last_failure_result: DataResult | None = None
        last_failure_name: str | None = None
        for name in ordered:
            if (name, capability) in self.disabled:
                failures.append((name, "schema_drift", "temporarily disabled"))
                continue
            provider = self.providers.get(name)
            if provider is None:
                failures.append((name, "unavailable", "provider not registered"))
                continue
            partial = bool(route_params.get("include_today"))
            # Capability/provider version participates in the cache key.  The
            # edge qfq contract additionally receives code/window/cutoff/
            # adjust_method from the caller, so a cached segment can never be
            # mistaken for another stock, window, cutoff, or adjustment mode.
            ck = cache_key(name, capability,
                           schema_version=str(cfg.get("provider_version", "1")),
                           partial=partial, **route_params)
            if cfg.get("cacheable"):
                hit = self.cache.get(ck)
                if hit is not None:
                    if capability not in {"pattern_edge_history",
                                          "pattern_edge_index_history"}:
                        # Preserve the pre-existing legacy cache behavior
                        # byte-for-byte; only the additive edge contract needs
                        # cache lineage markers on a defensive copy.
                        return hit
                    cached = copy.deepcopy(hit)
                    cached.metadata["cache_hit"] = True
                    cached.metadata["from_cache"] = True
                    if isinstance(cached.value, dict):
                        cached.value["cache_hit"] = True
                        cached.value["from_cache"] = True
                    return cached
            try:
                result = provider.fetch(capability, **route_params)
                result.capability = capability
                # Provider adapters may return a typed failure result instead
                # of raising ProviderError.  Treat those statuses identically
                # so fallback and schema-drift disabling continue to work.
                if result.status in {"unavailable", "rate_limited", "schema_drift",
                                     "not_supported", "quota_exhausted",
                                     "incomplete_intraday"} and not result.usable:
                    last_failure_result = result
                    last_failure_name = name
                    failures.append((name, result.status,
                                     result.error or f"{name} returned {result.status}"))
                    key = (name, capability)
                    if result.status == "schema_drift":
                        self.schema_drifts[key] = self.schema_drifts.get(key, 0) + 1
                        if self.schema_drifts[key] >= 2:
                            self.disabled.add(key)
                    continue
                if name != first:
                    result.fallback_from = first
                    if result.status == "ok":
                        result.status = "degraded"
                if failures:
                    result.metadata["route_failures"] = failures
                if cfg.get("cacheable") and result.usable:
                    self.cache.set(ck, result, int(cfg.get("ttl_seconds", 300)))
                return result
            except ProviderError as exc:
                failures.append((name, exc.status, str(exc)[:160]))
                key = (name, capability)
                if isinstance(exc, SchemaDrift):
                    self.schema_drifts[key] = self.schema_drifts.get(key, 0) + 1
                    if self.schema_drifts[key] >= 2:
                        self.disabled.add(key)
            except Exception as exc:  # adapters must not break the fallback chain
                failures.append((name, "unavailable", f"{type(exc).__name__}: {exc}"[:160]))
        status = failures[-1][1] if failures else "unavailable"
        # Preserve the last concrete provider as the failure source.  A typed
        # provider failure must still be eligible for fallback, but when the
        # route is exhausted the caller needs to know which provider actually
        # produced the terminal evidence (and legacy callers rely on source).
        source = failures[-1][0] if failures else "none"
        provider_family = self.matrix.get("vendor_families", {}).get(source, "none")
        if (last_failure_result is not None and failures and
                failures[-1][0] == source == last_failure_name):
            metadata = dict(last_failure_result.metadata)
            metadata.update({"raw_status": status, "route_failures": failures})
        else:
            metadata = {"raw_status": status, "route_failures": failures}
        failure_value = (last_failure_result.value
                         if last_failure_result is not None and failures and
                         failures[-1][0] == source == last_failure_name
                         else None)
        return DataResult(value=failure_value, source=source, provider_family=provider_family,
                          status=status, capability=capability,
                          error=failures[-1][2] if failures else "no provider",
                          metadata=metadata)

    def crosscheck_relation(self, left: str, right: str) -> str:
        families = self.matrix.get("vendor_families", {})
        return "SAME_VENDOR_ONLY" if families.get(left) == families.get(right) else "CROSS_SOURCE"


_DEFAULT: ProviderRegistry | None = None


def get_registry(*, reset: bool = False) -> ProviderRegistry:
    global _DEFAULT
    if reset or _DEFAULT is None or _DEFAULT.mode != data_mode():
        _DEFAULT = ProviderRegistry()
    return _DEFAULT
