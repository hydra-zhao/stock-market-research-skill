"""Jin10 remains the macro/global-news primary provider."""
from __future__ import annotations

import os
from typing import Any

from .base import Provider
from .errors import NotSupported, ProviderUnavailable
from .models import DataResult, ProviderIdentity


class Jin10Provider(Provider):
    identity = ProviderIdentity("jin10", "jin10_family")

    def configured(self) -> bool:
        return bool(os.environ.get("JIN10_MCP_TOKEN"))

    def supports(self, capability: str) -> bool:
        return capability in {"macro_news", "macro_calendar"}

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if not self.supports(capability):
            raise NotSupported(capability)
        if not self.configured():
            raise ProviderUnavailable("JIN10_MCP_TOKEN 未设置")
        import jin10_mcp
        try:
            value = (jin10_mcp.list_calendar() if capability == "macro_calendar" else
                     jin10_mcp.list_paged(params.get("kind", "list_flash"),
                                          pages=params.get("pages")))
        except Exception as exc:
            raise ProviderUnavailable(str(exc)) from exc
        return DataResult(value=value, source="jin10", provider_family="jin10_family",
                          status="ok", capability=capability)
