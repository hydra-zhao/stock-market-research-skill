"""Official/announcement risk adapter. Fuyao anomaly never verifies this chain."""
from __future__ import annotations

from typing import Any

from .base import Provider
from .errors import NotSupported, RiskVerificationFailed
from .models import DataResult, ProviderIdentity


class RiskOfficialProvider(Provider):
    identity = ProviderIdentity("risk_official", "official_disclosure_family")

    def supports(self, capability: str) -> bool:
        return capability == "risk_events"

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if not self.supports(capability):
            raise NotSupported(capability)
        from sources.risk_scan import scan_code
        code = str(params["code"])[:6]
        try:
            hits, source = scan_code(code, em=params.get("em"), cninfo=params.get("cninfo"),
                                     today=params.get("today"))
        except Exception as exc:
            raise RiskVerificationFailed(str(exc)) from exc
        is_eastmoney = source == "东财"
        family = "eastmoney_family" if is_eastmoney else "official_disclosure_family"
        verification = "eastmoney_announcement" if is_eastmoney else "official_disclosure"
        return DataResult(value=hits, source=source, provider_family=family,
                          status="ok", capability=capability,
                          metadata={
                              "verification": verification,
                              "announcement_chain_verified": True,
                              "official_disclosure_verified": not is_eastmoney,
                              "official_regulatory_verified": False,
                              "official_chain_verified": not is_eastmoney,
                          })
